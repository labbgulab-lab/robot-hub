"""mDNS detector: `_reachy-mini._tcp` and `_naoqi._tcp` (PLAN.md 2.1, 6).

One browser covers two robots. Three measured traps shaped this file.

**In-process, never the OS resolver.** Windows' own resolver failed on
`nao.local` while zeroconf resolved it fine (profiles/naoqi.md), so the hub
runs its own mDNS stack and never shells out to `ping`/`getaddrinfo`.

**The service instance name is not stable.** Both Reachys advertise as
`reachy_mini`, so Bonjour renames whichever one arrives second and the suffix
depends on boot order. Observed live with both robots powered (2.2):

    reachy_mini-2 -> 172.20.10.10   model=Reachy Mini Wireless  unit=58b3b6a4bf81179a
    reachy_mini   -> 100.98.102.61  model=Reachy Mini Lite      unit=None

So the type comes from TXT `model` and the identity from TXT `unit_id` (or,
for the Lite, the USB serial that `usbwatch` supplies). Never the instance
name -- keying on it would have swapped the two cards on the next reboot.

**The Lite's advertised address is unreachable.** It publishes its Tailscale
IP while the daemon binds `127.0.0.1` only (profiles/reachy-mini-lite.md), so
that address answers nothing, from any interface. The Lite is reported at the
loopback daemon URL from config instead.

zeroconf's callbacks are synchronous and run on its own thread, so every one
of them is marshalled onto the event loop with `call_soon_threadsafe`; no hub
state is ever touched from the zeroconf thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..adapters.base import Found
from ..config import Config
from ..events import EventBus

log = logging.getLogger("hub.discovery.mdns")

REACHY_SERVICE = "_reachy-mini._tcp.local."
NAOQI_SERVICE = "_naoqi._tcp.local."
SERVICES = (REACHY_SERVICE, NAOQI_SERVICE)
# RobotType in the _naoqi._tcp TXT record -> hub type.
NAOQI_TYPES = {"nao": "naoqi", "pepper": "pepper"}

MODEL_TYPES = {
    "reachy mini wireless": "reachy_wireless",
    "reachy mini lite": "reachy_lite",
}

RESOLVE_TIMEOUT_MS = 3000
REACHABLE_TIMEOUT_S = 1.5
DEFAULT_LITE_URL = "http://127.0.0.1:8000"


class MdnsDetector:
    name = "mDNS"

    def __init__(self, config: Config, bus: EventBus,
                 on_found: Callable[[Found], None]) -> None:
        self.config = config
        self.bus = bus
        self.on_found = on_found
        self._zc: Any = None
        self._browser: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._services: dict[tuple[str, str], Found] = {}
        self._tasks: set[asyncio.Task] = set()
        self._wake = asyncio.Event()

    async def rescan(self) -> None:
        """Re-check the known services now. A robot that has just booted
        announces itself unasked, so this only shortens the confirmation."""
        self._wake.set()

    async def _idle(self, interval: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), interval)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake.clear()

    # ------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        try:
            from zeroconf import ServiceBrowser, Zeroconf
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log(
                "warn",
                "mDNS discovery is off: zeroconf did not import ({}). "
                "Install it with: pip install -r requirements.txt".format(exc))
            return

        self._loop = asyncio.get_running_loop()
        # Zeroconf() opens and joins multicast sockets -- blocking work.
        self._zc = await asyncio.to_thread(Zeroconf)
        try:
            self._browser = ServiceBrowser(self._zc, list(SERVICES),
                                           handlers=[self._on_change])
            self.bus.emit_log("info", "mDNS browsing {} and {}".format(*SERVICES))
            refresh = max(1.0, min(4.0, self.config.discovery.lost_after_s / 3.0))
            while True:
                await self._idle(refresh)
                await self._resight()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        self._tasks.clear()
        browser, zc = self._browser, self._zc
        self._browser = self._zc = None
        try:
            if browser is not None:
                await asyncio.to_thread(browser.cancel)
            if zc is not None:
                await asyncio.to_thread(zc.close)
        except Exception as exc:  # noqa: BLE001
            log.debug("zeroconf shutdown: %s", exc)

    # ------------------------------------------------- zeroconf thread side
    def _on_change(self, zeroconf: Any, service_type: str, name: str,
                   state_change: Any) -> None:
        """Called on zeroconf's own thread. Hands everything to the loop."""
        removed = str(state_change).endswith("Removed")
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._dispatch, service_type, name, removed)
        except RuntimeError:
            pass  # loop already closing; nothing left to tell

    # ----------------------------------------------------- event loop side
    def _dispatch(self, service_type: str, name: str, removed: bool) -> None:
        if removed:
            if self._services.pop((service_type, name), None) is not None:
                log.info("mDNS withdrew %s", name)
            return
        task = asyncio.create_task(self._resolve(service_type, name))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _resolve(self, service_type: str, name: str) -> None:
        zc = self._zc
        if zc is None:
            return
        try:
            info = await asyncio.to_thread(
                zc.get_service_info, service_type, name, RESOLVE_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001
            log.debug("could not resolve %s: %s", name, exc)
            return
        if info is None:
            return
        found = self._to_found(service_type, name, info)
        if found is None:
            return
        self._services[(service_type, name)] = found
        self._emit(found)

    async def _resight(self) -> None:
        """Re-emit what is still answering.

        A PTR record can outlive the robot by a long way -- Avahi publishes it
        with a multi-hour TTL -- so a browser that only listens would keep a
        powered-off robot "present" for far longer than the 15 s the plan
        allows (10, Phase 1). One cheap TCP connect per known robot per cycle
        settles presence. It is not a health signal: an open port lies (2.3),
        and the adapter's probe is what decides whether the robot is well.
        """
        for found in list(self._services.values()):
            if await _reachable(found.address, found.port):
                self._emit(found)

    def _emit(self, found: Found) -> None:
        try:
            self.on_found(found)
        except Exception as exc:  # noqa: BLE001
            log.warning("discovery callback raised for %s: %s", found.type_id, exc)

    # -------------------------------------------------------------- parsing
    def _to_found(self, service_type: str, name: str, info: Any) -> Optional[Found]:
        txt = _decode_txt(getattr(info, "properties", {}) or {})
        instance = name.split(".")[0]
        meta: dict[str, Any] = dict(txt)
        meta.update({
            "instance": instance,
            "service": service_type,
            "server": (getattr(info, "server", "") or "").rstrip("."),
            "advertised_addresses": _ipv4s(info),
            "txt": txt,
            "source": "mdns",
        })

        if service_type == REACHY_SERVICE:
            model = str(txt.get("model", "")).strip()
            type_id = MODEL_TYPES.get(model.lower())
            if type_id is None:
                log.info("ignoring unknown Reachy model %r advertised by %s",
                         model, instance)
                return None
            if type_id == "reachy_lite":
                # The advertised address is Tailscale and answers nothing; the
                # desktop app is the Lite's daemon host, on loopback (2.6).
                host, port = self._lite_daemon()
                meta["ignored_advertised_address"] = txt.get("address", "")
                return Found(type_id=type_id, address=host, port=port, meta=meta)
            address = _pick_address(txt, meta["advertised_addresses"])
            if address is None:
                return None
            return Found(type_id=type_id, address=address,
                         port=getattr(info, "port", None), meta=meta)

        if service_type == NAOQI_SERVICE:
            robot_type = str(txt.get("RobotType", "") or txt.get("robottype", ""))
            # Pepper advertises RobotType=Pepper (exact case) on the same
            # service; a blank type is an older NAO.
            type_id = NAOQI_TYPES.get(robot_type.strip().lower() or "nao")
            if type_id is None:
                log.info("ignoring %s on %s: RobotType=%s", instance,
                         service_type, robot_type)
                return None
            address = _pick_address(txt, meta["advertised_addresses"])
            if address is None:
                return None
            return Found(type_id=type_id, address=address,
                         port=getattr(info, "port", None), meta=meta)

        return None

    def _lite_daemon(self) -> tuple[str, int]:
        raw = str(self.config.robot("reachy_lite").settings.get("daemon_url")
                  or DEFAULT_LITE_URL)
        parsed = urlparse(raw if "//" in raw else "http://" + raw)
        return (parsed.hostname or "127.0.0.1", parsed.port or 8000)


# ---------------------------------------------------------------- helpers
def _decode_txt(properties: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_key, raw_value in properties.items():
        key = raw_key.decode("utf-8", "replace") if isinstance(raw_key, bytes) else str(raw_key)
        if isinstance(raw_value, bytes):
            value = raw_value.decode("utf-8", "replace")
        elif raw_value is None:
            value = ""
        else:
            value = str(raw_value)
        out[key] = value
    return out


def _ipv4s(info: Any) -> list[str]:
    try:
        addresses = list(info.parsed_addresses())
    except Exception:  # noqa: BLE001
        return []
    return [a for a in addresses if ":" not in a]


def _pick_address(txt: dict[str, str], addresses: list[str]) -> Optional[str]:
    """A routable address beats a link-local one, but link-local is valid --
    NAO advertises 169.254.x while it is on the cable (profiles/naoqi.md).

    The address a robot puts in its own TXT record comes first. Every Reachy
    Mini ships with the hostname `reachy-mini`, so with two on the hotspot the
    A record of one answers for both: reachy3 (TXT 172.20.10.3) was reported
    at reachy2's 172.20.10.2 and evicted its card (2026-10-05). Pollen's own
    discovery prefers the TXT address for exactly this reason."""
    candidates = list(addresses)
    advertised = str(txt.get("address", "")).strip()
    if advertised and ":" not in advertised:
        candidates = [advertised] + [a for a in candidates if a != advertised]
    routable = [a for a in candidates if not a.startswith("169.254.")]
    ordered = routable + candidates
    return ordered[0] if ordered else None


async def _reachable(address: str, port: Optional[int]) -> bool:
    if not port:
        return True  # nothing to knock on; trust the advertisement
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port), REACHABLE_TIMEOUT_S)
    except (asyncio.TimeoutError, OSError):
        return False
    except Exception as exc:  # noqa: BLE001
        log.debug("reachability check on %s:%s raised %s", address, port, exc)
        return False
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 1.0)
    except Exception:  # noqa: BLE001
        pass
    return True
