"""The orchestrator: discovery -> registry -> adapters -> browser.

Owns the card state machine (PLAN.md 5.2) and the probe loops. Every robot
call here is wrapped in a timeout and run as its own task, because a slow
robot must never freeze a card, delay another robot, or block the loop (2.4).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from .adapters import (
    DISPLAY_NAMES,
    KNOWN_TYPES,
    AdapterUnavailable,
    Found,
    PostureRefused,
    RobotAdapter,
    get_adapter_class,
)
from .config import Config
from .events import EventBus
from .keys import KEYS_FILE, KeyError_, KeyStore
from . import registry as R
from .registry import Registry
from .resources import ConflictError, ResourceBroker

log = logging.getLogger("hub.core")

PROBE_INTERVAL_S = 2.0
PROBE_TIMEOUT_S = 6.0
CONNECT_TIMEOUT_S = 25.0
ANNOUNCE_TIMEOUT_S = 15.0
LAUNCH_TIMEOUT_S = 120.0
# Covers one SSH step already in flight (30 s command + 15 s connect slack).
DISCONNECT_CANCEL_WAIT_S = 50.0
BACKOFF_START_S = 2.0
BACKOFF_CAP_S = 30.0
# A Reachy daemon restart is ~20 s of ConnectionError, then clean (2.9).
# Ride it out instead of starting a reconnect storm.
GRACE_AFTER_CONNECT_S = 22.0


class Hub:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.bus = EventBus()
        self.registry = Registry(self.bus)
        self.resources = ResourceBroker(self.bus, config)
        self.adapters: dict[str, RobotAdapter] = {}
        self.found: dict[str, Found] = {}
        self._probe_tasks: dict[str, asyncio.Task] = {}
        self._busy: set[str] = set()
        # The task running each in-flight Launch, so Disconnect can cancel it.
        self._launches: dict[str, asyncio.Task] = {}
        # Cards with a posture command in flight. Kept apart from `_busy`,
        # which Disconnect clears on its way out.
        self._postures: set[str] = set()
        self._connected_at: dict[str, float] = {}
        self._backoff: dict[str, float] = {}
        self.network: dict[str, Any] = {"on_robot_subnet": True, "interfaces": []}
        self._manager: Any = None
        # Speaking keys live here, on the laptop, and are sent at launch.
        self.keys = KeyStore(config.repo_root / KEYS_FILE)
        self._seed_cards()

    # ---------------------------------------------------------------- setup
    def _seed_cards(self) -> None:
        """Four dim cards exist before any robot is powered on (Phase 0)."""
        for type_id in KNOWN_TYPES:
            cfg = self.config.robot(type_id)
            if not cfg.enabled:
                continue
            self.registry.upsert(
                f"placeholder:{type_id}",
                type_id=type_id,
                name=cfg.display_name or DISPLAY_NAMES[type_id],
                state=R.ABSENT,
                detail="waiting for this robot to appear",
            )

    def _seed_keys(self) -> None:
        """First run only: import the Gemini key this laptop already used."""
        if self.keys.public()["keys"]:
            return
        chat = self.config.path("reachy_wireless", "reachy_chat_path")
        if chat is not None:
            self.keys._seed(chat.parent / "reachy-mini llm gemini token.txt")

    # ------------------------------------------------------------------ keys
    def keys_event(self) -> dict[str, Any]:
        speaking = [r.key for r in self.registry.all()
                    if getattr(self.adapters.get(r.key), "uses_speech_key", False)]
        return {"type": "keys", **self.keys.public(),
                "robots": {k: self.keys.robot_public(k) for k in speaking}}

    def _keys_changed(self) -> dict[str, Any]:
        event = self.keys_event()
        self.bus.publish(event)
        return event

    def add_key(self, provider: str, label: str, key: str) -> dict[str, Any]:
        try:
            entry = self.keys.add(provider, label, key)
        except KeyError_ as exc:
            return {"ok": False, "error": str(exc)}
        self.bus.emit_log("ok", "key added: {} ({}, ...{})".format(
            entry["label"], entry["provider"], entry["tail"]))
        return {"ok": True, **self._keys_changed()}

    def remove_key(self, key_id: str) -> dict[str, Any]:
        try:
            self.keys.remove(key_id)
        except KeyError_ as exc:
            return {"ok": False, "error": str(exc)}
        self.bus.emit_log("info", "key removed")
        return {"ok": True, **self._keys_changed()}

    def assign_key(self, robot_key: str, key_id: Optional[str]) -> dict[str, Any]:
        r = self.registry.get(robot_key)
        try:
            self.keys.assign(robot_key, key_id)
        except KeyError_ as exc:
            return {"ok": False, "error": str(exc)}
        entry = self.keys.get(key_id) if key_id else None
        self.bus.emit_log("info", "{} will speak through {}{}".format(
            r.name if r else robot_key,
            entry["label"] if entry else "the default key",
            " (applies at next Launch)" if r and r.state == R.RUNNING else ""))
        return {"ok": True, **self._keys_changed()}

    async def start(self) -> None:
        self._seed_keys()
        try:
            from .discovery.manager import DiscoveryManager
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log("warn", "discovery unavailable: {}".format(exc))
            return
        self._manager = DiscoveryManager(
            self.config,
            self.bus,
            on_found=self._on_found,
            on_lost=self._on_lost,
            on_network=self._on_network,
        )
        await self._manager.start()
        self.bus.emit_log("ok", "discovery running")

    async def stop(self) -> None:
        for task in list(self._probe_tasks.values()):
            task.cancel()
        self._probe_tasks.clear()
        for key in list(self.adapters):
            try:
                await asyncio.wait_for(self.adapters[key].disconnect(), 5)
            except Exception:  # noqa: BLE001
                pass
        if self._manager is not None:
            await self._manager.stop()

    async def rescan(self) -> dict[str, Any]:
        """Sweep now instead of waiting for the next cadence."""
        self.bus.emit_log("info", "scanning for robots")
        manager = self._manager
        rescan = getattr(manager, "rescan", None) if manager is not None else None
        if rescan is None:
            self.registry.broadcast_all()
            return {"ok": True, "forced": False}
        try:
            await rescan()
            return {"ok": True, "forced": True}
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log("warn", "scan failed: {}".format(exc))
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------ discovery hooks
    def _on_found(self, found: Found) -> None:
        cls = get_adapter_class(found.type_id)
        if cls is None:
            self.bus.emit_log(
                "warn",
                "{} seen at {} but its adapter is not installed".format(
                    DISPLAY_NAMES.get(found.type_id, found.type_id), found.address),
            )
            return

        try:
            adapter = cls(found, self.config)
            key = adapter.stable_key(found)
        except AdapterUnavailable as exc:
            self._note_disabled(found, str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log("warn", "could not identify {}: {}".format(found.type_id, exc))
            return

        self.found[key] = found
        self._drop_placeholder(found.type_id)
        cfg = self.config.robot(found.type_id)
        name = cfg.name_for(key, DISPLAY_NAMES.get(found.type_id, found.type_id))
        existing = self.registry.get(key)
        self._evict_address(key, name, found.address)
        self.registry.upsert(key, type_id=found.type_id, name=name, address=found.address)

        if key in self.adapters:
            self.adapters[key].found = found
        else:
            self.adapters[key] = adapter
            if getattr(adapter, "uses_speech_key", False):
                self._keys_changed()    # a new card needs its key picker

        if existing is None or existing.state in (R.ABSENT, R.ERROR):
            self.registry.set_state(key, R.DETECTED, "detected at {}".format(found.address))
            self.bus.emit_log("ok", "{} appeared at {}".format(name, found.address))

        self._ensure_probe(key)
        current = self.registry.get(key)
        if self.config.auto_connect and current is not None and current.state == R.DETECTED:
            asyncio.create_task(self.connect(key, reason="auto-connect"))

    def _evict_address(self, key: str, name: str, address: str) -> None:
        """An address is never an identity (2.2): when a robot is sighted at
        an address another card holds, that card's robot is gone from it.

        2026-10-05: reachy2 went off, reachy3 came up on its old address, and
        reachy2's card stayed green -- its health probe was being answered by
        reachy3. A Disconnect pressed there would have put reachy3 to sleep.
        The old card is marked absent without calling its adapter: anything
        sent to that address now reaches the other robot.
        """
        for other in self.registry.all():
            if (other.key == key or other.address != address
                    or other.key.startswith("placeholder:")):
                continue
            self._connected_at.pop(other.key, None)
            self.resources.release_all(other.key)
            self.registry.upsert(other.key, address=None, system_url=None)
            self.registry.set_state(other.key, R.ABSENT,
                                    "its address now belongs to {}".format(name))
            self.bus.emit_log("warn", "{} is gone: {} now answers at {}".format(
                other.name, name, address))

    def _note_disabled(self, found: Found, reason: str) -> None:
        """A missing local prerequisite disables one card, nothing else (13.6)."""
        key = "placeholder:{}".format(found.type_id)
        self.registry.upsert(key, address=found.address, disabled_reason=reason)
        self.registry.set_state(key, R.DISABLED, reason)
        self.bus.emit_log("warn", "{}: {}".format(
            DISPLAY_NAMES.get(found.type_id, found.type_id), reason))

    def _on_lost(self, type_id: str, key: str) -> None:
        r = self.registry.get(key)
        if r is None:
            return
        # A robot the hub is actively running is not "lost" on one silent
        # detector cycle -- it goes amber and the probe loop decides (5.2).
        if r.state in (R.CONNECTED, R.RUNNING, R.CONNECTING):
            self.registry.set_state(key, R.DEGRADED, "stopped answering discovery")
            self.bus.emit_log("warn", "{} dropped off discovery".format(r.name))
            return
        self.registry.set_state(key, R.ABSENT, "not on the network")
        self.bus.emit_log("info", "{} is gone".format(r.name))

    def _on_network(self, info: dict[str, Any]) -> None:
        was = self.network.get("on_robot_subnet", True)
        self.network = info
        self.bus.publish({"type": "network", **info})
        if was and not info.get("on_robot_subnet", True):
            # The laptop silently roaming off the hotspot reads exactly like
            # "every robot hung". Say so instead of showing four dead cards.
            where = ", ".join(info.get("interfaces", [])) or "no usable interface"
            self.bus.emit_log(
                "error",
                "This laptop is no longer on the robots' network ({}). "
                "Robots will look dead until you rejoin.".format(where),
            )
        elif not was and info.get("on_robot_subnet", True):
            self.bus.emit_log("ok", "back on the robots' network")

    # ---------------------------------------------------------- placeholders
    def _drop_placeholder(self, type_id: str) -> None:
        ph = "placeholder:{}".format(type_id)
        if self.registry.get(ph) is not None:
            self.registry.remove(ph)

    # ---------------------------------------------------------- probe loops
    def _ensure_probe(self, key: str) -> None:
        task = self._probe_tasks.get(key)
        if task and not task.done():
            return
        self._probe_tasks[key] = asyncio.create_task(self._probe_loop(key))

    async def _probe_loop(self, key: str) -> None:
        while True:
            await asyncio.sleep(PROBE_INTERVAL_S)
            adapter = self.adapters.get(key)
            r = self.registry.get(key)
            if adapter is None or r is None:
                return
            if r.state in (R.ABSENT, R.DISABLED, R.CONNECTING) or key in self._busy:
                continue
            try:
                health = await asyncio.wait_for(
                    adapter.probe(self.found.get(key, adapter.found)), PROBE_TIMEOUT_S)
            except asyncio.TimeoutError:
                health = {"online": False, "degraded": True,
                          "detail": "no answer within {:.0f} s".format(PROBE_TIMEOUT_S),
                          "battery": None}
            except Exception as exc:  # noqa: BLE001
                health = {"online": False, "degraded": True,
                          "detail": "probe failed: {}".format(exc), "battery": None}
            self._apply_health(key, health)

    def _apply_health(self, key: str, health: dict[str, Any]) -> None:
        r = self.registry.get(key)
        if r is None:
            return
        self.registry.upsert(key, battery=health.get("battery"),
                             detail=health.get("detail", ""))
        # Only a robot that really completed Connect counts. A *failed*
        # connect also leaves the card in ERROR, and the next healthy probe
        # used to promote it to CONNECTED -- Launch then ran on a Furhat that
        # had never logged in, spoken, or had its voice set (2026-10-05).
        was_connected = (r.state in (R.CONNECTED, R.RUNNING, R.DEGRADED, R.ERROR)
                         and key in self._connected_at)
        online = bool(health.get("online"))
        degraded = bool(health.get("degraded"))
        if r.state == R.ERROR and key not in self._connected_at and online:
            return      # a failed connect: it stays ERROR until a retry succeeds

        if online and not degraded:
            if r.state == R.DEGRADED:
                self.bus.emit_log("ok", "{} recovered".format(r.name))
            if r.system_url:
                self.registry.set_state(key, R.RUNNING)
            elif was_connected:
                self.registry.set_state(key, R.CONNECTED)
            else:
                self.registry.set_state(key, R.DETECTED)
            self._backoff.pop(key, None)
            return

        if online and degraded:
            # Amber is honest -- Reachy's nb_error moves ~7 s before state (2.3)
            if r.state != R.DEGRADED:
                self.bus.emit_log("warn", "{}: {}".format(r.name, health.get("detail")))
            self.registry.set_state(key, R.DEGRADED)
            return

        if not was_connected:
            self.registry.set_state(key, R.DETECTED)
            return

        since = time.time() - self._connected_at.get(key, 0.0)
        if since < GRACE_AFTER_CONNECT_S:
            self.registry.set_state(key, R.DEGRADED, "not answering yet (daemon restart?)")
            return
        if r.state != R.ERROR:
            self.bus.emit_log("error", "{} lost: {}".format(r.name, health.get("detail")))
            self.registry.set_state(key, R.ERROR)
            asyncio.create_task(self._reconnect_later(key))

    def _connect_failed(self, key: str) -> None:
        """Forget any earlier connection, and with auto-connect on, try again
        with backoff -- a robot that just booted (Furhat: web page up before
        its event bus) refuses the first attempt."""
        self._connected_at.pop(key, None)
        if self.config.auto_connect:
            asyncio.create_task(self._reconnect_later(key))

    async def _reconnect_later(self, key: str) -> None:
        delay = min(self._backoff.get(key, BACKOFF_START_S), BACKOFF_CAP_S)
        self._backoff[key] = min(delay * 2, BACKOFF_CAP_S)
        r = self.registry.get(key)
        if r is not None:
            self.bus.emit_log("info", "{}: retrying in {:.0f} s".format(r.name, delay))
        await asyncio.sleep(delay)
        current = self.registry.get(key)
        if current is not None and current.state == R.ERROR:
            await self.connect(key, reason="auto-reconnect")

    # ------------------------------------------------------------- actions
    def _flush_notes(self, name: str, adapter: Any) -> None:
        """Adapters collect human sentences in `notes` (a voice change, a
        first-run install); nothing showed them until 2026-10-05."""
        notes = getattr(adapter, "notes", None)
        if notes is None:
            return
        for note in list(notes):
            self.bus.emit_log("info", "{}: {}".format(name, note))
        notes.clear()
        # From now on, each new note is logged as it is written.
        if hasattr(notes, "sink"):
            notes.sink = lambda text: self.bus.emit_log("info", "{}: {}".format(name, text))

    async def connect(self, key: str, reason: str = "") -> dict[str, Any]:
        adapter = self.adapters.get(key)
        r = self.registry.get(key)
        if adapter is None or r is None:
            return {"ok": False, "error": "unknown robot"}
        if key in self._busy or key in self._postures:
            return {"ok": False, "error": "already working on this robot"}
        self._busy.add(key)
        try:
            self.registry.set_state(key, R.CONNECTING, "connecting")
            self._flush_notes(r.name, adapter)
            self.bus.emit_log("info", "{}: connecting{}".format(
                r.name, " ({})".format(reason) if reason else ""))
            await asyncio.wait_for(adapter.connect(), CONNECT_TIMEOUT_S)
            self._connected_at[key] = time.time()

            try:
                extra = await asyncio.wait_for(adapter.system_status(), 8)
            except Exception:  # noqa: BLE001
                extra = {}
            self.registry.upsert(key, **{k: v for k, v in extra.items() if hasattr(r, k)})
            self.registry.set_state(key, R.CONNECTED, "connected")
            self.bus.emit_log("ok", "{}: connected".format(r.name))
            self._flush_notes(r.name, adapter)

            # The announcement is proof the link is real -- but its failure
            # must never fail the connection (8).
            text = self.config.robot(r.type_id).announcement(r.name)
            try:
                await asyncio.wait_for(adapter.announce(text), ANNOUNCE_TIMEOUT_S)
                self.registry.upsert(key, can_speak=True)
                self.bus.emit_log("ok", '{} said: "{}"'.format(r.name, text))
            except Exception as exc:  # noqa: BLE001
                self.registry.upsert(key, can_speak=False)
                self.registry.set_state(key, R.CONNECTED, "connected, but could not speak")
                self.bus.emit_log("warn", "{}: connected, but could not speak - {}".format(
                    r.name, exc))
            self._backoff.pop(key, None)
            return {"ok": True}
        except asyncio.TimeoutError:
            self._connect_failed(key)
            self.registry.set_state(key, R.ERROR, "connect timed out")
            self.bus.emit_log("error", "{}: connect timed out".format(r.name))
            return {"ok": False, "error": "timeout"}
        except Exception as exc:  # noqa: BLE001
            self._connect_failed(key)
            self.registry.set_state(key, R.ERROR, "connect failed: {}".format(exc))
            self.bus.emit_log("error", "{}: connect failed - {}".format(r.name, exc))
            return {"ok": False, "error": str(exc)}
        finally:
            self._busy.discard(key)

    async def disconnect(self, key: str) -> dict[str, Any]:
        adapter = self.adapters.get(key)
        r = self.registry.get(key)
        if adapter is None or r is None:
            return {"ok": False, "error": "unknown robot"}
        # A Launch still in flight is cancelled first. Before 2026-10-05 the
        # two ran side by side: Disconnect stopped the half-started app, the
        # Launch went on waiting for it, and Disconnect's cleanup cleared the
        # Launch's busy flag so a second Launch could start beside it.
        # The wait is long enough for an SSH step already on the wire to land
        # (adapters/base.py thread_finishing_on_cancel): the cleanup below
        # must run after it, or the robot app starts once Disconnect is done.
        task = self._launches.get(key)
        if task is not None and not task.done():
            task.cancel()
            self.bus.emit_log("info", "{}: cancelling the launch in flight".format(r.name))
            done, _ = await asyncio.wait({task}, timeout=DISCONNECT_CANCEL_WAIT_S)
            if not done:
                self.bus.emit_log("warn", "{}: the launch did not stop within {:.0f} s; "
                                  "disconnecting anyway".format(r.name, DISCONNECT_CANCEL_WAIT_S))
            else:
                self.bus.emit_log("info", "{}: launch cancelled by Disconnect".format(r.name))
        self._busy.add(key)
        try:
            await asyncio.wait_for(adapter.disconnect(), 15)
            result: dict[str, Any] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log("warn", "{}: disconnect reported {}".format(r.name, exc))
            result = {"ok": True, "warning": str(exc)}
        finally:
            self._busy.discard(key)
        self.resources.release_all(key)
        self.registry.upsert(key, system_url=None, can_speak=True, launch_error=None)
        if key not in self._postures:
            self.registry.upsert(key, posture_note=None, posture_failed=False)
        self.registry.set_state(key, R.DETECTED, "disconnected")
        self.bus.emit_log("info", "{}: disconnected".format(r.name))
        self._backoff.pop(key, None)
        self._connected_at.pop(key, None)
        return result

    async def launch(self, key: str, override: bool = False) -> dict[str, Any]:
        adapter = self.adapters.get(key)
        r = self.registry.get(key)
        if adapter is None or r is None:
            return {"ok": False, "error": "unknown robot"}
        if r.state not in (R.CONNECTED, R.RUNNING, R.DEGRADED):
            return {"ok": False, "error": "connect first"}
        if key in self._busy or key in self._postures:
            # A double-pressed Launch used to start a second launch that then
            # failed with "already running" (reachy2, 2026-09-23).
            return {"ok": False, "error": "{} is already busy".format(r.name)}
        self._busy.add(key)
        self.registry.upsert(key, launching_since=time.time(), launch_error=None)
        task = asyncio.create_task(self._launch_body(key, adapter, r, override))
        self._launches[key] = task
        try:
            await asyncio.wait({task})
            if task.cancelled():
                self.resources.release_all(key)
                return {"ok": False, "error": "cancelled by Disconnect"}
            return task.result()
        finally:
            self._launches.pop(key, None)
            self._busy.discard(key)
            self.registry.upsert(key, launching_since=None)

    async def _launch_body(self, key: str, adapter: Any, r: Any,
                           override: bool) -> dict[str, Any]:
        self._flush_notes(r.name, adapter)
        try:
            try:
                self.resources.acquire(key, r.name, adapter.claims(), override=override)
            except ConflictError as exc:
                self.bus.publish({"type": "conflict", "key": key,
                                  "message": str(exc), "resource": exc.resource})
                self.bus.emit_log("error", "{}: {}".format(r.name, exc))
                return {"ok": False, "error": str(exc), "conflict": True,
                        "resource": exc.resource}

            if getattr(adapter, "uses_speech_key", False):
                entry, how = self.keys.for_robot(key)
                adapter.credential = entry
                adapter.provider_env = self.keys.env_for_robot(key)
                if entry is not None:
                    self.bus.emit_log("info", "{}: speaking through {} (...{}; {})".format(
                        r.name, entry["label"], entry["key"][-4:], how))

            for note in await adapter.ensure_zero_instances():
                self.bus.emit_log("info", "{}: {}".format(r.name, note))

            # An adapter that may first install itself onto the robot (Reachy
            # wireless: pip + SFTP, minutes on first run) declares its own bound.
            url = await asyncio.wait_for(
                adapter.launch(),
                getattr(adapter, "launch_timeout_s", LAUNCH_TIMEOUT_S))
            self.registry.upsert(key, system_url=url)
            self.registry.set_state(key, R.RUNNING, "system running")
            self._flush_notes(r.name, adapter)
            self.bus.emit_log("ok", "{}: launched -> {}".format(r.name, url))
            return {"ok": True, "url": url}
        except Exception as exc:  # noqa: BLE001
            self.resources.release_all(key)
            # A timeout's message is empty; the card still needs a sentence.
            reason = str(exc) or ("timed out" if isinstance(exc, asyncio.TimeoutError)
                                  else type(exc).__name__)
            self.registry.upsert(key, launch_error=reason)
            self.bus.emit_log("error", "{}: launch failed - {}".format(r.name, reason))
            return {"ok": False, "error": reason}

    async def join_wifi(self, key: str, ssid: str, password: str) -> dict[str, Any]:
        """The card's "Add WiFi...": teach NAO / Pepper a lab member's hotspot.

        The robot joins it now and keeps it, so it leaves this laptop's
        network on success and its card goes dim until the laptop follows.
        The password is passed on and never logged.
        """
        adapter = self.adapters.get(key)
        r = self.registry.get(key)
        if adapter is None or r is None:
            return {"ok": False, "error": "unknown robot"}
        if not hasattr(adapter, "join_wifi"):
            return {"ok": False, "error": "{} has no Add WiFi".format(r.name)}
        if r.state not in (R.DETECTED, R.CONNECTED, R.RUNNING, R.DEGRADED):
            return {"ok": False, "error": "{} is not on the network".format(r.name)}
        task = self._launches.get(key)
        if (task is not None and not task.done()) or r.launching_since:
            return {"ok": False, "error": "{} is launching — wait for it "
                                          "first".format(r.name)}
        if key in self._busy or key in self._postures:
            return {"ok": False, "error": "{} is busy — try again when it "
                                          "settles".format(r.name)}
        ssid = (ssid or "").strip()
        self._busy.add(key)
        self.bus.emit_log("info", "{}: joining the WiFi “{}” (up to "
                                  "a minute)".format(r.name, ssid))
        try:
            message = await adapter.join_wifi(ssid, password)
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or type(exc).__name__
            self.bus.emit_log("error", "{}: could not join “{}” - {}".format(
                r.name, ssid, reason))
            return {"ok": False, "error": reason}
        finally:
            self._busy.discard(key)
        self.bus.emit_log("ok", "{}: {}".format(r.name, message))
        return {"ok": True, "message": message}

    async def posture(self, key: str, name: str) -> dict[str, Any]:
        """An operator posture button (NAO: sit / lie / stand).

        Refused -- never queued -- while the card is connecting, launching or
        already moving: a motion that starts after the operator has stopped
        watching is the dangerous kind. The adapter's own heat guard decides
        whether the motors may be powered at all.
        """
        adapter = self.adapters.get(key)
        r = self.registry.get(key)
        if adapter is None or r is None:
            return {"ok": False, "error": "unknown robot"}
        name = (name or "").strip().lower()
        offered = tuple(getattr(adapter, "postures", ()) or ())
        if not offered:
            return {"ok": False, "error": "{} has no posture controls".format(r.name)}
        if name not in offered:
            return {"ok": False, "error": "{} cannot {!r}; it offers {}".format(
                r.name, name, ", ".join(offered))}
        if r.state not in (R.CONNECTED, R.RUNNING):
            return {"ok": False, "error": "connect to {} first".format(r.name)}
        task = self._launches.get(key)
        if (task is not None and not task.done()) or r.launching_since:
            return {"ok": False, "error": "{} is launching \u2014 wait for it to "
                                          "finish before moving it".format(r.name)}
        if key in self._postures:
            return {"ok": False, "error": "{} is already moving".format(r.name)}
        if key in self._busy:
            return {"ok": False, "error": "{} is busy \u2014 try again when it "
                                          "settles".format(r.name)}

        self._busy.add(key)
        self._postures.add(key)
        self.registry.upsert(key, posture_pending=name, posture_note=None,
                             posture_failed=False)
        self.bus.emit_log("info", "{}: {} requested".format(r.name, name))
        bound = float(getattr(adapter, "posture_timeout_s", 60.0)) + 15.0
        try:
            message = await asyncio.wait_for(adapter.posture(name), bound)
        except PostureRefused as exc:
            reason = str(exc)
            self.bus.emit_log("warn", "{}: {} refused - {}".format(r.name, name, reason))
            self.registry.upsert(key, posture_note=reason, posture_failed=True)
            return {"ok": False, "error": reason, "refused": True}
        except Exception as exc:  # noqa: BLE001
            reason = str(exc) or ("no answer within {:.0f} s \u2014 check on it".format(bound)
                                  if isinstance(exc, asyncio.TimeoutError)
                                  else type(exc).__name__)
            self.bus.emit_log("error", "{}: {} failed - {}".format(r.name, name, reason))
            self.registry.upsert(key, posture_note=reason, posture_failed=True)
            return {"ok": False, "error": reason}
        finally:
            self._postures.discard(key)
            self._busy.discard(key)
            self.registry.upsert(key, posture_pending=None)
        self.bus.emit_log("ok", "{}: {}".format(r.name, message))
        self.registry.upsert(key, posture_note=message, posture_failed=False)
        return {"ok": True, "message": message}

    # -------------------------------------------------------------- state
    def _order(self, type_id: str) -> int:
        return KNOWN_TYPES.index(type_id) if type_id in KNOWN_TYPES else 99

    def snapshot(self) -> dict[str, Any]:
        robots = sorted(self.registry.all(), key=lambda x: self._order(x.type_id))
        return {
            "robots": [r.to_event() for r in robots],
            "network": self.network,
            "settings": {"auto_connect": self.config.auto_connect},
            "keys": self.keys_event(),
            "log": self.bus.recent(100),
        }
