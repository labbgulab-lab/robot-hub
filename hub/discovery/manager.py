"""Runs the detectors and turns sightings into presence events (PLAN.md 6).

The manager owns three things the detectors deliberately do not:

* **The key.** A sighting is named by the adapter's `stable_key()` -- unit_id,
  MAC or USB serial, never an IP (2.2). When that adapter is not installed the
  same identity is derived here from the sighting's own metadata, so Phase 1
  works before any adapter exists and the two agree once one does.
* **Loss.** Detectors only ever say "I can see this". A robot that has not
  been sighted for `discovery.lost_after_s` is reported lost exactly once.
* **Isolation.** Each detector runs under a supervisor: one that raises is
  restarted with a backoff and a sentence in the log, and the other three
  carry on. A robot you do not own must cost nothing (13.6).

`on_found` fires on first sight and again whenever a known robot's address
changes -- Reachy and Furhat held 172.20.10.10 within one hour on the same
session (2.2), so an address is news, not identity.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

from ..adapters.base import Found
from ..config import Config
from ..events import EventBus
from .mdns import MdnsDetector
from .netscan import NetscanDetector
from .selfnet import SelfNetDetector
from .usbwatch import UsbWatchDetector

log = logging.getLogger("hub.discovery")

REAP_INTERVAL_S = 1.0
RESTART_BACKOFF_START_S = 2.0
RESTART_BACKOFF_CAP_S = 60.0

# Metadata keys that are a real identity, strongest first. An address is
# never among them (2.2).
IDENTITY_KEYS = ("unit_id", "usb_serial", "mac", "studio_id", "serial_number")


class DiscoveryManager:
    def __init__(self, config: Config, bus: EventBus,
                 on_found: Callable[[Found], None],
                 on_lost: Callable[[str, str], None],
                 on_network: Callable[[dict[str, Any]], None]) -> None:
        self.config = config
        self.bus = bus
        self._on_found = on_found
        self._on_lost = on_lost
        self._on_network = on_network

        self.selfnet = SelfNetDetector(config, bus, self._network)
        self._detectors: list[Any] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

        self._found: dict[str, Found] = {}
        self._seen: dict[str, float] = {}
        # fingerprint -> key, cached; None means "this sighting has no identity"
        self._keys: dict[str, Optional[str]] = {}
        self._anonymous: dict[str, str] = {}  # type_id -> key of an unnamed card

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        discovery = self.config.discovery

        wants_mdns = any(self.config.robot(t).enabled
                         for t in ("reachy_wireless", "reachy_lite", "naoqi"))
        if discovery.mdns and wants_mdns:
            self._spawn(MdnsDetector(self.config, self.bus, self._sighting))
        if discovery.netscan and self.config.robot("furhat").enabled:
            self._spawn(NetscanDetector(self.config, self.bus, self._sighting))
        if discovery.usb and self.config.robot("reachy_lite").enabled:
            self._spawn(UsbWatchDetector(self.config, self.bus, self._sighting))

        self._spawn(self.selfnet)
        self._tasks.append(asyncio.create_task(self._reaper(), name="discovery:reaper"))

    async def rescan(self) -> None:
        """Ask every detector to look now (hub/core.py's Scan button).

        Discovery never stops, so this only shortens the wait after someone
        powers a robot on. Detectors run on their own tasks: a rescan wakes
        them, it does not sweep on the caller's.
        """
        await asyncio.gather(
            *(d.rescan() for d in self._detectors if hasattr(d, "rescan")),
            return_exceptions=True)

    async def stop(self) -> None:
        self._running = False
        self._detectors = []
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        if tasks:
            # Await every cancellation: a task still pending at interpreter
            # exit is where "Task was destroyed but it is pending" comes from.
            await asyncio.gather(*tasks, return_exceptions=True)

    def snapshot(self) -> dict[str, Found]:
        return dict(self._found)

    # ---------------------------------------------------------- supervision
    def _spawn(self, detector: Any) -> None:
        self._detectors.append(detector)
        self._tasks.append(asyncio.create_task(
            self._supervise(detector), name="discovery:{}".format(detector.name)))

    async def _supervise(self, detector: Any) -> None:
        backoff = RESTART_BACKOFF_START_S
        while True:
            try:
                await detector.run()
                return  # a detector that returns has said why and is done
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.exception("%s detector crashed", detector.name)
                self.bus.emit_log(
                    "warn",
                    "{} discovery stopped with {}: {}. Restarting it in "
                    "{:.0f} s; the other detectors are unaffected.".format(
                        detector.name, type(exc).__name__, exc, backoff))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RESTART_BACKOFF_CAP_S)

    # -------------------------------------------------------------- reaping
    async def _reaper(self) -> None:
        while True:
            await asyncio.sleep(REAP_INTERVAL_S)
            deadline = time.time() - self.config.discovery.lost_after_s
            for key in [k for k, seen in self._seen.items() if seen < deadline]:
                found = self._found.pop(key, None)
                self._seen.pop(key, None)
                type_id = found.type_id if found else "unknown"
                if self._anonymous.get(type_id) == key:
                    self._anonymous.pop(type_id, None)
                for fingerprint in [f for f, k in self._keys.items() if k == key]:
                    self._keys.pop(fingerprint, None)
                self._call(self._on_lost, type_id, key)

    # ------------------------------------------------------------ sightings
    def _sighting(self, found: Found) -> None:
        """Called by every detector, on the event loop thread."""
        key = self._key_for(found)
        if key is None:
            return
        self.selfnet.record_robot_address(found.address)
        self._seen[key] = time.time()
        previous = self._found.get(key)
        self._found[key] = found
        if previous is None:
            self._call(self._on_found, found)
            return
        if (previous.address, previous.port) != (found.address, found.port):
            self.bus.emit_log(
                "info",
                "{} moved from {} to {}; the card follows the robot, not the "
                "address.".format(found.type_id, previous.address, found.address))
            self._call(self._on_found, found)

    def _key_for(self, found: Found) -> Optional[str]:
        fingerprint = _fingerprint(found)
        if fingerprint is not None and fingerprint in self._keys:
            key = self._keys[fingerprint]
        else:
            key = self._resolve_key(found, fingerprint)
            if fingerprint is not None:
                self._keys[fingerprint] = key

        if key is None:
            # The sighting carries no identity of its own -- the Lite's mDNS
            # record has no unit_id (2.2). If a stronger detector has already
            # named this robot, refresh that card; otherwise hold one unnamed
            # card for this type until the USB serial arrives.
            named = [k for k, f in self._found.items()
                     if f.type_id == found.type_id
                     and k != self._anonymous.get(found.type_id)]
            if named:
                return named[0]
            placeholder = self._anonymous.get(found.type_id)
            if placeholder is None:
                placeholder = "{}:unnamed".format(found.type_id)
                self._anonymous[found.type_id] = placeholder
            return placeholder

        stale = self._anonymous.get(found.type_id)
        if stale is not None and stale != key:
            # A named sighting supersedes the placeholder; drop it rather than
            # leave two cards for one robot.
            self._anonymous.pop(found.type_id, None)
            self._found.pop(stale, None)
            self._seen.pop(stale, None)
            self._call(self._on_lost, found.type_id, stale)
        return key

    def _resolve_key(self, found: Found, fingerprint: Optional[str]) -> Optional[str]:
        """Ask the adapter, so the manager and the core agree on the key.

        An installed adapter that refuses to key a sighting is right -- the
        Lite's own adapter refuses anything without a USB serial -- so that
        answer is kept, not overridden with a guess. Resolved once per
        identity and cached: this runs on every sighting, and constructing an
        adapter is the caller's code, not ours.
        """
        try:
            from ..adapters import get_adapter_class
            cls = get_adapter_class(found.type_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("no adapter lookup for %s: %s", found.type_id, exc)
            return fingerprint
        if cls is None:
            return fingerprint
        try:
            return str(cls(found, self.config).stable_key(found))
        except Exception as exc:  # noqa: BLE001
            log.debug("the %s adapter will not key this sighting: %s",
                      found.type_id, exc)
            return None

    # ------------------------------------------------------------ callbacks
    def _network(self, info: dict[str, Any]) -> None:
        self._call(self._on_network, info)

    def _call(self, callback: Callable[..., Any], *args: Any) -> None:
        """A callback that raises is a bug in the consumer, not a reason to
        stop discovering robots (13.5)."""
        try:
            callback(*args)
        except Exception as exc:  # noqa: BLE001
            log.exception("discovery callback failed")
            self.bus.emit_log("warn", "discovery callback failed: {}".format(exc))


def _fingerprint(found: Found) -> Optional[str]:
    for field in IDENTITY_KEYS:
        value = found.meta.get(field)
        if value:
            return "{}:{}".format(found.type_id, str(value).strip().lower())
    if found.address in ("127.0.0.1", "localhost", "::1"):
        # A loopback sighting is hosted by this laptop, so its mDNS hostname
        # names the laptop, not the robot -- the Lite advertises
        # DESKTOP-xxxx.local (profiles/reachy-mini-lite.md). Only a USB serial
        # names that robot.
        return None
    server = str(found.meta.get("server", "")).strip().lower()
    if server and not server.replace(".", "").isdigit():
        # A hostname is an identity; the address it currently resolves to is
        # not (2.2). NAO advertises `nao.local` on both cable and WiFi.
        return "{}:{}".format(found.type_id, server)
    return None
