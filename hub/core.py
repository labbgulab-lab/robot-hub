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
from .config import Config, custom_data_dir
from .events import EventBus
from . import inuse
from . import keycheck
from .keys import KEYS_FILE, PROVIDERS, ROBOT_SLOTS, KeyError_, KeyStore, normalize_provider
from . import network as hub_network
from . import settings as hub_settings
from . import registry as R
from .registry import BATTERY_LOW_PCT, Registry
from .requirements import SetupManager
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
# Keys are re-checked with their free test call at most this often (and on
# demand); never at import, never as a paid call (STUDENT-APP-PLAN 3).
KEY_CHECK_EVERY_S = 3600.0
KEY_LOOP_S = 300.0
# The network state is re-read this often, and at once when something changes.
NETWORK_EVERY_S = 10.0
# Robot types whose app is a lab-staff tool; the card lists the action, and
# Launch refuses it unless Settings > Staff tools is on.
STAFF_ONLY_ACTIONS = {"naoqi": ["nao_app"]}


class ActionError(Exception):
    """A request the hub refuses; `code` is the friendly-error code."""

    def __init__(self, message: str, code: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra

    def body(self) -> dict[str, Any]:
        return {"ok": False, "error": str(self), "code": self.code, **self.extra}


def _hold_label(resource: str) -> str:
    kind, _, value = resource.partition(":")
    if kind == "audio_in":
        return "Microphone ({})".format(value) if value else "Microphone"
    if kind == "audio_out":
        return "Speaker ({})".format(value) if value else "Speaker"
    if kind == "port":
        return "Port {}".format(value)
    return value or kind


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
        self.network: dict[str, Any] = {"on_robot_subnet": True, "interfaces": [],
                                        "state": "searching", "ssid": None, "band": None,
                                        "kind": "none", "ranges": [],
                                        "hotspot": {"devices": 1,
                                                    "limit": hub_network.HOTSPOT_LIMIT},
                                        "robots_network": {"ssid": None, "last_seen": None}}
        self._manager: Any = None
        # Speaking keys live here, on the laptop, and are sent at launch. In
        # the data folder, so an update never takes them (STUDENT-APP-PLAN 2.1).
        self.keys = KeyStore(config.data_dir / KEYS_FILE)
        # The free test call's HTTP layer (hub/keycheck.py); tests swap it.
        self.key_transport: Optional[keycheck.Transport] = None
        self._key_task: Optional[asyncio.Task] = None
        self._key_checks: dict[str, asyncio.Task] = {}
        # The student's settings (data/settings.json); stored values such as
        # auto_connect and the lab WiFi are applied onto `config` here.
        self.settings = hub_settings.open_store(config.data_dir, config)
        # What this laptop needs before a robot works (hub/requirements.py).
        self.setup = SetupManager(config, self.bus, self.settings)
        self.setup.listeners.append(self._setup_changed)
        self._kit_ready = self._safe_kit_ready()
        # The WiFi reading (hub/wifi.py) is blocking; tests swap this.
        self.wifi_reader: Any = None
        self._network_task: Optional[asyncio.Task] = None
        self._network_wake: Optional[asyncio.Event] = None
        self._battery_warned: set[str] = set()
        # Robots whose in-use marker this hub wrote (removed at Disconnect).
        self._marked: set[str] = set()
        self._seed_cards()

    # ---------------------------------------------------------------- setup
    def _seed_cards(self) -> None:
        """Four dim cards exist before any robot is powered on (Phase 0).
        NAO and Pepper's say "needs setup" while the kit is missing, even
        with no robot present (STUDENT-APP-PLAN 4.1)."""
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
                needs_setup=self._needs_setup(type_id),
                staff_only_actions=list(STAFF_ONLY_ACTIONS.get(type_id, [])),
            )

    # ---------------------------------------------------------------- setup
    def _safe_kit_ready(self) -> bool:
        try:
            return self.setup.kit_ready()
        except Exception:  # noqa: BLE001
            return False

    def _needs_setup(self, type_id: str) -> Optional[str]:
        if type_id in ("naoqi", "pepper") and not self._kit_ready:
            return "naoqi_kit"
        return None

    def _setup_changed(self) -> None:
        """A setup item moved: re-label the placeholder cards and, when the
        kit came or went, identify every NAOqi robot again (no restart)."""
        ready = self._safe_kit_ready()
        changed = ready != self._kit_ready
        self._kit_ready = ready
        for type_id in ("naoqi", "pepper"):
            ph = "placeholder:{}".format(type_id)
            r = self.registry.get(ph)
            if r is None:
                continue
            self.registry.upsert(ph, needs_setup=self._needs_setup(type_id))
            if ready and r.state == R.DISABLED and r.needs_setup is None:
                self.registry.upsert(ph, address=None, disabled_reason=None)
                self.registry.set_state(ph, R.ABSENT, "waiting for this robot to appear")
        if changed and self._manager is not None:
            hook = getattr(self._manager, "naoqi_setup_changed", None)
            if hook is not None:
                try:
                    hook()
                except Exception:  # noqa: BLE001
                    pass

    # ----------------------------------------------------------- staff tools
    def staff_tools_on(self) -> bool:
        """Settings > Staff tools. A lab checkout (no ROBOT_HUB_DATA) that
        never set it keeps every tool, as before the student app."""
        stored = getattr(self.settings, "_data", {})
        if "staff_tools" in stored:
            return bool(stored["staff_tools"])
        if custom_data_dir() is None:
            return True
        return bool(self.settings.get("staff_tools"))

    # ------------------------------------------------------------------ keys
    def _key_robots(self) -> list[Any]:
        """Real robots (not placeholders) whose type takes a key."""
        return [r for r in self.registry.all()
                if not r.key.startswith("placeholder:") and r.type_id in ROBOT_SLOTS
                and (r.key in self.adapters or r.type_id == "furhat")]

    def keys_event(self) -> dict[str, Any]:
        robots = self._key_robots()
        used_by: dict[str, list[str]] = {}
        for r in robots:
            for slot in ROBOT_SLOTS.get(r.type_id, {}):
                entry, _how = self.keys.for_robot(r.key, r.type_id, slot)
                if entry is not None and r.name not in used_by.setdefault(entry["id"], []):
                    used_by[entry["id"]].append(r.name)
        return {"type": "keys", **self.keys.public(used_by),
                # Kept for the old page: each speaking robot's main key.
                "robots": {r.key: self.keys.robot_public(r.key, r.type_id)
                           for r in robots
                           if getattr(self.adapters.get(r.key), "uses_speech_key", False)},
                "slots": {r.key: self.keys.robot_slots_public(r.key, r.type_id)
                          for r in robots}}

    def _keys_changed(self) -> dict[str, Any]:
        event = self.keys_event()
        self.bus.publish(event)
        return event

    async def add_key(self, provider: str, label: str, key: str) -> dict[str, Any]:
        """Test the key with its provider's free call, then save it.
        Raises ActionError (DUPLICATE, NOT_A_KEY, UNKNOWN_PROVIDER, KEY_REFUSED).
        No internet: saved, with status "offline"."""
        secret = keycheck.clean(key)
        if not keycheck.looks_like_a_key(secret):
            raise ActionError("That doesn't look like an API key.", "NOT_A_KEY")
        if self.keys.find_secret(secret) is not None:
            raise ActionError("That key is already here.", "DUPLICATE")
        wanted = normalize_provider(provider)
        if wanted in ("", "auto"):
            candidates = keycheck.detect(secret)
            if not candidates:
                raise ActionError("Which service is this key from?", "UNKNOWN_PROVIDER",
                                  candidates=list(PROVIDERS))
        elif wanted in PROVIDERS:
            candidates = [wanted]
        else:
            raise ActionError("Which service is this key from?", "UNKNOWN_PROVIDER",
                              candidates=list(PROVIDERS))

        chosen, status, first = None, None, None
        for candidate in candidates:
            result = await keycheck.check(candidate, secret, self.key_transport)
            first = first or result
            if result["state"] != "bad":
                chosen, status = candidate, result
                break
        if chosen is None:
            raise ActionError((first or {}).get("detail") or "That key was refused.",
                              "KEY_REFUSED", provider=candidates[0])
        try:
            entry = self.keys.add(chosen, label, secret, status=status)
        except KeyError_ as exc:
            raise ActionError(str(exc), exc.code, **exc.extra) from exc
        self.bus.emit_log("ok", "key added: {} ({}, ...{}; {})".format(
            entry["label"], entry["provider"], entry["tail"], status["state"]))
        return {"ok": True, "key": entry, **self._keys_changed()}

    async def check_key(self, key_id: str) -> dict[str, Any]:
        entry = self.keys.get(key_id)
        if entry is None:
            raise ActionError("That key is not here any more.", "UNKNOWN_KEY", 404)
        running = self._key_checks.get(key_id)
        if running is not None and not running.done():
            await asyncio.wait({running})
        else:
            task = asyncio.ensure_future(self._check_one(key_id))
            self._key_checks[key_id] = task
            try:
                await asyncio.wait({task})
            finally:
                self._key_checks.pop(key_id, None)
        return {"ok": True, "key": self.keys.public_entry(key_id), **self.keys_event()}

    async def _check_one(self, key_id: str) -> None:
        entry = self.keys.get(key_id)
        if entry is None:
            return
        previous = dict(entry.get("status") or {})
        self.keys.set_status(key_id, {**keycheck.status("checking", "Checking"),
                                      "credit": previous.get("credit")}, save=False)
        self._keys_changed()
        result = await keycheck.check(entry["provider"], entry["key"], self.key_transport)
        if result["state"] == "offline" and previous.get("state") in ("works", "no_credit", "bad"):
            # No internet says nothing new about the key: keep what we knew.
            result = {**previous, "detail": previous.get("detail") or "", "offline": True}
        self.keys.set_status(key_id, result)
        if result.get("state") != previous.get("state") and previous.get("state"):
            level = "warn" if result.get("state") in ("bad", "no_credit") else "info"
            self.bus.emit_log(level, "key {}: {}".format(entry["label"], result.get("detail")
                                                         or result.get("state")))
        self._keys_changed()

    async def check_keys(self, max_age_s: float = KEY_CHECK_EVERY_S) -> int:
        """Re-check every key not checked within `max_age_s`; returns how many."""
        due = self.keys.due_for_check(max_age_s)
        if due:
            await asyncio.gather(*(self._check_one(k) for k in due), return_exceptions=True)
        return len(due)

    def enable_key_checks(self) -> None:
        """Background re-checks (free calls), at most hourly per key. Started
        by hub.main.main() only, never at import or in tests."""
        if self._key_task is None or self._key_task.done():
            self._key_task = asyncio.create_task(self._key_loop())

    async def _key_loop(self) -> None:
        while True:
            try:
                await self.check_keys()
            except Exception as exc:  # noqa: BLE001
                log.info("key re-check failed: %s", exc)
            await asyncio.sleep(KEY_LOOP_S)

    def remove_key(self, key_id: str) -> dict[str, Any]:
        try:
            self.keys.remove(key_id)
        except KeyError_ as exc:
            raise ActionError("That key is not here any more.", exc.code, 404) from exc
        self.bus.emit_log("info", "key removed")
        return {"ok": True, **self._keys_changed()}

    def assign_key(self, robot_key: str, key_id: Optional[str],
                   slot: str = "main") -> dict[str, Any]:
        r = self.registry.get(robot_key)
        type_id = r.type_id if r is not None else None
        try:
            self.keys.assign(robot_key, key_id, slot, type_id)
        except KeyError_ as exc:
            raise ActionError(str(exc), exc.code, 404 if exc.code == "UNKNOWN_KEY" else 400) from exc
        entry = self.keys.get(key_id) if key_id else None
        what = "speak through" if (slot or "main") == "main" else "use the voice key"
        self.bus.emit_log("info", "{} will {} {}{}".format(
            r.name if r else robot_key, what,
            entry["label"] if entry else "the default key",
            " (applies at next Launch)" if r and r.state == R.RUNNING else ""))
        return {"ok": True, **self._keys_changed()}

    async def start(self) -> None:
        # No first-run key seed any more: keys come only from the Keys popup.
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
        self._network_wake = asyncio.Event()
        self._network_task = asyncio.create_task(self._network_loop())

    async def stop(self) -> None:
        for task in (self._network_task, self._key_task):
            if task is not None:
                task.cancel()
        self._network_task = self._key_task = None
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
        self.network_changed()
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
            self._note_disabled(found, str(exc), getattr(exc, "requirement", None))
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
        self.registry.upsert(key, type_id=found.type_id, name=name, address=found.address,
                             needs_setup=None,
                             staff_only_actions=list(STAFF_ONLY_ACTIONS.get(found.type_id, [])))

        if key in self.adapters:
            self.adapters[key].found = found
        else:
            self.adapters[key] = adapter
            if found.type_id in ROBOT_SLOTS:
                self._keys_changed()    # a new card needs its key picker
            self.network_changed()

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

    def _note_disabled(self, found: Found, reason: str,
                       requirement: Optional[str] = None) -> None:
        """A missing local prerequisite disables one card, nothing else (13.6).
        With a `requirement` (NAO/Pepper without the kit) the card says which
        setup step fixes it (`needs_setup`)."""
        key = "placeholder:{}".format(found.type_id)
        r = self.registry.get(key)
        was = (r.state, r.address) if r is not None else None
        self.registry.upsert(key, type_id=found.type_id,
                             name=self.config.robot(found.type_id).display_name
                             or DISPLAY_NAMES.get(found.type_id, found.type_id),
                             address=found.address, disabled_reason=reason,
                             needs_setup=requirement)
        self.registry.set_state(key, R.DISABLED, reason)
        if was != (R.DISABLED, found.address):
            self.bus.emit_log("warn", "{}: {}".format(
                DISPLAY_NAMES.get(found.type_id, found.type_id), reason))

    def _on_lost(self, type_id: str, key: str) -> None:
        self.network_changed()
        r = self.registry.get(key)
        if r is None:
            # A sighting with no card of its own (a NAOqi robot seen without
            # the kit lives on its type's placeholder): that card goes dim.
            ph = self.registry.get("placeholder:{}".format(type_id))
            if ph is not None and ph.state == R.DISABLED:
                self.registry.upsert(ph.key, address=None)
                self.registry.set_state(ph.key, R.ABSENT, "waiting for this robot to appear")
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
        self.network = {**self.network, **info}
        self.bus.publish({"type": "network", **self.network})
        self.network_changed()
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

    # --------------------------------------------------------- network state
    def network_changed(self) -> None:
        """Something moved (a robot, an interface): re-read the network soon."""
        if self._network_wake is not None:
            self._network_wake.set()

    def _present_robots(self) -> list[dict[str, Any]]:
        out = []
        for r in self.registry.all():
            if r.key.startswith("placeholder:") or not r.address:
                continue
            if r.state in (R.ABSENT, R.DISABLED):
                continue
            if r.address.startswith("127.") or r.address in ("localhost", "::1"):
                continue
            out.append({"type_id": r.type_id, "address": r.address, "name": r.name})
        return out

    def _read_wifi(self) -> dict[str, Any]:
        """Blocking: the WiFi, this laptop's addresses and VPN adapters."""
        if self.wifi_reader is not None:
            return self.wifi_reader()
        from . import wifi
        from .discovery.selfnet import local_ipv4, vpn_adapters
        addresses = [str(n) for n in local_ipv4()]
        info = wifi.status(addresses, self.config.network.lab_wifi)
        return {"wifi": info, "interfaces": addresses, "vpn": vpn_adapters()}

    async def refresh_network(self) -> dict[str, Any]:
        reading = await asyncio.to_thread(self._read_wifi)
        stats = {"sweeps": 0, "alive": 0, "ranges": []}
        hook = getattr(self._manager, "netscan_stats", None) if self._manager else None
        if hook is not None:
            try:
                stats = hook()
            except Exception:  # noqa: BLE001
                pass
        robots = self._present_robots()
        wifi_info = reading.get("wifi") or {}
        ssid = wifi_info.get("ssid")
        if robots and ssid:
            self.settings.note_robots_network(ssid)
        state = hub_network.compute(
            wifi=wifi_info, interfaces=reading.get("interfaces") or [],
            vpn=reading.get("vpn") or [], robots=robots,
            robots_network=self.settings.get("robots_network"),
            lab_wifi=self.config.network.lab_wifi, sweeps=stats.get("sweeps", 0),
            alive=stats.get("alive", 0), ranges=stats.get("ranges") or [])
        merged = {**self.network, **state}
        compare = ("state", "ssid", "band", "kind", "ranges", "hotspot", "robots_network", "vpn")
        if any(merged.get(k) != self.network.get(k) for k in compare):
            self.network = merged
            self.bus.publish({"type": "network", **merged})
        else:
            self.network = merged
        return merged

    async def _network_loop(self) -> None:
        wake = self._network_wake or asyncio.Event()
        while True:
            try:
                await self.refresh_network()
            except Exception as exc:  # noqa: BLE001
                log.info("network check failed: %s", exc)
            try:
                await asyncio.wait_for(wake.wait(), NETWORK_EVERY_S)
                await asyncio.sleep(0.5)        # let a burst of changes settle
            except asyncio.TimeoutError:
                pass
            wake.clear()

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
            bound = getattr(adapter, "probe_timeout_s", PROBE_TIMEOUT_S)
            try:
                health = await asyncio.wait_for(
                    adapter.probe(self.found.get(key, adapter.found)), bound)
            except asyncio.TimeoutError:
                health = {"online": False, "degraded": True,
                          "detail": "no answer within {:.0f} s".format(bound),
                          "battery": None}
            except Exception as exc:  # noqa: BLE001
                health = {"online": False, "degraded": True,
                          "detail": "probe failed: {}".format(exc), "battery": None}
            self._apply_health(key, health)

    def _apply_health(self, key: str, health: dict[str, Any]) -> None:
        r = self.registry.get(key)
        if r is None:
            return
        battery = health.get("battery")
        charging = health.get("charging") if "charging" in health else r.charging
        low = isinstance(battery, int) and battery < BATTERY_LOW_PCT
        self.registry.upsert(key, battery=battery, battery_low=low, charging=charging,
                             detail=health.get("detail", ""))
        self._battery_note(r, battery, low, charging)
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

    def _battery_note(self, r: Any, battery: Any, low: bool, charging: Any) -> None:
        """One warning each time a battery drops below the line, not one per probe."""
        if low and not charging:
            if r.key not in self._battery_warned:
                self._battery_warned.add(r.key)
                self.bus.emit_log("warn", "{} battery {}%. Plug it in soon.".format(
                    r.name, battery), key=r.key, battery_low=True)
        elif not low or charging:
            self._battery_warned.discard(r.key)

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
        if current is None:
            return
        # Lost (a real loss), or Available after a failed Connect.
        if current.state == R.ERROR or (current.state == R.DETECTED and current.connect_error
                                        and self.config.auto_connect):
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
        # A robot that was really lost stays Lost when the retry fails; any
        # other failed Connect leaves it Available with `connect_error`.
        lost_before = r.state == R.ERROR and key in self._connected_at
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
            self.registry.upsert(key, connect_error=None)
            self.registry.set_state(key, R.CONNECTED, "connected")
            self.bus.emit_log("ok", "{}: connected".format(r.name))
            self._flush_notes(r.name, adapter)
            # Who else is using it: an SSH read, in the background so a robot
            # without SSH never slows Connect (Launch reads it again).
            asyncio.ensure_future(self._read_in_use(key, adapter))

            # The announcement is proof the link is real -- but its failure
            # must never fail the connection (8). An auto-reconnect stays
            # silent: on 2026-10-12 Pepper said its line mid-demo after a
            # slow probe.
            text = self.config.robot(r.type_id).announcement(r.name)
            if reason == "auto-reconnect":
                self._backoff.pop(key, None)
                return {"ok": True}
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
            self.registry.upsert(key, connect_error="connect timed out")
            self.registry.set_state(key, R.ERROR if lost_before else R.DETECTED,
                                    "connect timed out")
            self.bus.emit_log("error", "{}: connect timed out".format(r.name))
            return {"ok": False, "error": "timeout", "code": "CONNECT_FAILED"}
        except Exception as exc:  # noqa: BLE001
            self._connect_failed(key)
            reason = str(exc) or type(exc).__name__
            self.registry.upsert(key, connect_error=reason)
            self.registry.set_state(key, R.ERROR if lost_before else R.DETECTED,
                                    "connect failed: {}".format(reason))
            self.bus.emit_log("error", "{}: connect failed - {}".format(r.name, reason))
            return {"ok": False, "error": reason, "code": "CONNECT_FAILED"}
        finally:
            self._busy.discard(key)

    # ------------------------------------------------------------ in use
    async def _read_in_use(self, key: str, adapter: Any) -> Optional[str]:
        """Read the robot's in-use marker (hub/inuse.py). Silent on failure."""
        if getattr(adapter, "remote_shell", None) is None:
            return None
        try:
            holder = await asyncio.wait_for(inuse.read(adapter), inuse.SSH_TIMEOUT_S + 6)
        except Exception:  # noqa: BLE001
            holder = None
        r = self.registry.get(key)
        if r is not None and r.in_use_by != holder:
            self.registry.upsert(key, in_use_by=holder)
            if holder:
                self.bus.emit_log("warn", "{}: another laptop ({}) is using it".format(
                    r.name, holder))
        return holder

    async def _mark_in_use(self, key: str, adapter: Any) -> None:
        if getattr(adapter, "remote_shell", None) is None:
            return
        try:
            if await asyncio.wait_for(inuse.write(adapter), inuse.SSH_TIMEOUT_S + 6):
                self._marked.add(key)
        except Exception:  # noqa: BLE001
            pass

    async def _unmark_in_use(self, key: str, adapter: Any) -> None:
        if key not in self._marked:
            return
        self._marked.discard(key)
        try:
            await asyncio.wait_for(inuse.clear(adapter), inuse.SSH_TIMEOUT_S + 6)
        except Exception:  # noqa: BLE001
            pass

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
        await self._unmark_in_use(key, adapter)
        try:
            await asyncio.wait_for(adapter.disconnect(), 15)
            result: dict[str, Any] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log("warn", "{}: disconnect reported {}".format(r.name, exc))
            result = {"ok": True, "warning": str(exc)}
        finally:
            self._busy.discard(key)
        self.resources.release_all(key)
        self.registry.upsert(key, system_url=None, can_speak=True, launch_error=None,
                             holds=[])
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
            return {"ok": False, "error": "connect first", "code": "CONNECT_FIRST"}
        if key in self._busy or key in self._postures:
            # A double-pressed Launch used to start a second launch that then
            # failed with "already running" (reachy2, 2026-09-23).
            return {"ok": False, "error": "{} is already busy".format(r.name), "code": "BUSY"}
        if "nao_app" in (r.staff_only_actions or []) and not self.staff_tools_on():
            # NAO's app (NAO_LLM) is a lab-staff tool; students get Connect,
            # Say and the postures (STUDENT-APP-PLAN S12).
            return {"ok": False, "code": "STAFF_ONLY",
                    "error": "The NAO app is for lab staff. Turn on Staff tools in Settings."}
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
            if not override and getattr(adapter, "remote_shell", None) is not None:
                holder = await self._read_in_use(key, adapter)
                if holder:
                    message = ("Another laptop ({}) is using {}. Press again to take it "
                               "over.".format(holder, r.name))
                    self.bus.emit_log("warn", "{}: {}".format(r.name, message))
                    return {"ok": False, "error": message, "code": "IN_USE",
                            "in_use_by": holder}
            try:
                self.resources.acquire(key, r.name, adapter.claims(), override=override)
            except ConflictError as exc:
                self.bus.publish({"type": "conflict", "key": key,
                                  "message": str(exc), "resource": exc.resource})
                self.bus.emit_log("error", "{}: {}".format(r.name, exc))
                return {"ok": False, "error": str(exc), "conflict": True,
                        "resource": exc.resource}

            self.registry.upsert(key, holds=self._holds(key))
            if getattr(adapter, "uses_speech_key", False):
                # Each slot's key (Pepper: main = GPT -> OPENAI_API_KEY, voice =
                # ElevenLabs -> ELEVENLABS_API_KEY), plus one key per provider.
                entry, how = self.keys.for_robot(key, r.type_id)
                adapter.credential = entry
                adapter.provider_env = self.keys.env_for_robot(key, r.type_id)
                if entry is not None:
                    self.bus.emit_log("info", "{}: speaking through {} (...{}; {})".format(
                        r.name, entry["label"], entry["key"][-4:], how))
                voice, _vhow = (self.keys.for_robot(key, r.type_id, "voice")
                                if "voice" in ROBOT_SLOTS.get(r.type_id, {}) else (None, ""))
                if voice is not None:
                    self.bus.emit_log("info", "{}: voice through {} (...{})".format(
                        r.name, voice["label"], voice["key"][-4:]))

            for note in await adapter.ensure_zero_instances():
                self.bus.emit_log("info", "{}: {}".format(r.name, note))

            # An adapter that may first install itself onto the robot (Reachy
            # wireless: pip + SFTP, minutes on first run) declares its own bound.
            url = await asyncio.wait_for(
                adapter.launch(),
                getattr(adapter, "launch_timeout_s", LAUNCH_TIMEOUT_S))
            self.registry.upsert(key, system_url=url, in_use_by=None)
            self.registry.set_state(key, R.RUNNING, "system running")
            self._flush_notes(r.name, adapter)
            self.bus.emit_log("ok", "{}: launched -> {}".format(r.name, url))
            # Tell other laptops this robot is taken; best effort, not awaited.
            asyncio.ensure_future(self._mark_in_use(key, adapter))
            return {"ok": True, "url": url}
        except Exception as exc:  # noqa: BLE001
            self.resources.release_all(key)
            self.registry.upsert(key, holds=[])
            # A timeout's message is empty; the card still needs a sentence.
            reason = str(exc) or ("timed out" if isinstance(exc, asyncio.TimeoutError)
                                  else type(exc).__name__)
            self.registry.upsert(key, launch_error=reason)
            self.bus.emit_log("error", "{}: launch failed - {}".format(r.name, reason))
            return {"ok": False, "error": reason}

    def _holds(self, key: str) -> list[str]:
        held = getattr(self.resources, "_held", {}) or {}
        return [_hold_label(h.resource) for h in held.values()
                if h.owner_key == key and h.mode == "require"]

    async def join_wifi(self, key: str, ssid: str, password: str,
                        lab: bool = False, open_network: bool = False) -> dict[str, Any]:
        """The card's "Add WiFi...": teach NAO / Pepper / Reachy a lab
        member's hotspot.

        The robot joins it now and keeps it, so it leaves this laptop's
        network on success and its card goes dim until the laptop follows.
        `lab` (Reachy only) saves the lab WiFi as the robot's fallback
        instead, without moving it. The password is passed on and never logged.
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
        if lab and getattr(adapter, "type_id", "") != "reachy_wireless":
            return {"ok": False, "error": "only a Reachy Mini keeps a lab WiFi "
                                          "fallback"}
        ssid = (ssid or "").strip()
        password = password or ""
        lab_wifi = self.config.network.lab_wifi
        if lab_wifi and ssid == lab_wifi and getattr(adapter, "type_id", "") == "reachy_wireless":
            lab = True          # never let the lab WiFi outrank a hotspot
        if (lab_wifi and ssid == lab_wifi and self.config.network.lab_wifi_open
                and not password):
            open_network = True
        if not ssid:
            return {"ok": False, "error": "a WiFi name has 1 to 32 characters",
                    "code": "BAD_WIFI"}
        if open_network and password:
            return {"ok": False, "error": "“{}” is set up as an open WiFi: leave the "
                                          "password empty".format(ssid), "code": "BAD_WIFI"}
        if not open_network and not 8 <= len(password) <= 63:
            return {"ok": False, "error": "a WiFi password has 8 to 63 characters",
                    "code": "BAD_WIFI"}
        self._busy.add(key)
        self.bus.emit_log("info", "{}: {} the WiFi “{}” (up to a minute)".format(
            r.name, "saving the lab" if lab else "joining", ssid))
        kwargs: dict[str, Any] = {"open_network": True} if open_network else {}
        try:
            message = await (adapter.join_wifi(ssid, password, lab=True, **kwargs) if lab
                             else adapter.join_wifi(ssid, password, **kwargs))
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
        try:
            settings = self.settings.public()
        except Exception:  # noqa: BLE001
            settings = {}
        try:
            setup = self.setup.items()
        except Exception:  # noqa: BLE001
            setup = []
        return {
            "robots": [r.to_event() for r in robots],
            "network": self.network,
            "settings": {**settings, "auto_connect": self.config.auto_connect},
            "keys": self.keys_event(),
            "setup": setup,
            "log": self.bus.recent(100),
        }

    def robot_detail(self, key: str) -> Optional[dict[str, Any]]:
        """GET /api/robots/{key}: the full card, with facts and key slots."""
        r = self.registry.get(key)
        if r is None:
            return None
        card = r.to_event()
        card.pop("type", None)
        adapter = self.adapters.get(key)
        card["keys"] = (self.keys.robot_slots_public(key, r.type_id)
                        if r.type_id in ROBOT_SLOTS else {})
        card["has_wifi"] = adapter is not None and hasattr(adapter, "join_wifi")
        card["postures"] = list(getattr(adapter, "postures", ()) or ())
        card["staff_tools"] = self.staff_tools_on()
        if r.needs_setup:
            try:
                card["setup"] = self.setup.item(r.needs_setup)
            except Exception:  # noqa: BLE001
                card["setup"] = None
        return card
