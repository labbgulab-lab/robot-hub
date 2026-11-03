"""Furhat detector: ICMP-gated sweep plus an HTTP fingerprint (PLAN.md 2.1, 6).

Furhat advertises **no mDNS at all** -- an `_services._dns-sd._udp` browse for
it returned `[]` (profiles/furhat.md). It has no hostname, no reverse DNS and
no JSON status endpoint, so the only type-based signature it offers is the
Studio page on port 80: `<title>Furhat Studio</title>`.

**A TCP connect to port 80 is not a liveness probe on this laptop.** The Check
Point VPN adapter hooks outbound port-80 connects and makes `connect()`
succeed for hosts that do not exist (2.9), which would light up a Furhat card
for every address in the subnet. Hence two gates: ICMP first, then a real HTTP
reply that actually contains the title.

Identity is the MAC from the ARP table, never the IP: within one hour on
2026-09-14 `172.20.10.10` was held by the wireless Reachy and then by Furhat
(2.2). A sighting the hub cannot name is reported as a log sentence and
dropped -- a card keyed on an address would be worse than no card.

**Big networks.** A network larger than `discovery.netscan_max_hosts` is not
swept whole: the laptop's own /24 inside it is, plus
`discovery.netscan_nearby_24s` /24s on each side. The lab WiFi is a /16 that
drops all multicast, so mDNS finds nothing there. DHCP hands out several
neighbouring /24s: on 2026-11-03 the laptop was 172.19.84.41, reachy6 and
reachy7 84.x, reachy8 85.33, and live devices sat in 80.x-85.x.

**Robots already found** are re-checked directly every `KNOWN_REFRESH_S`. A
ping-gated /24 sweep takes longer than `discovery.lost_after_s`, so without
this a robot only the sweep can see would drop off and come back every round.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import sys
from typing import Any, Callable, Optional

from ..adapters.base import Found
from ..config import Config
from ..events import EventBus

log = logging.getLogger("hub.discovery.netscan")

STUDIO_TITLE = re.compile(r"<title>\s*Furhat\s+Studio\s*</title>", re.I)
STUDIO_PORT = 80
REACHY_PORT = 8000
NAOQI_PORT = 9559
# A NAOqi identity costs a Python 2.7 start (seconds), so it is asked rarely.
NAOQI_ID_TTL_S = 300.0
NAOQI_MISS_TTL_S = 60.0
MAX_CONCURRENCY = 64
# How often a robot the sweep found is asked again, by address; well inside
# discovery.lost_after_s (12 s).
KNOWN_REFRESH_S = 3.0
# Silent this many refreshes in a row (~9 s) before the sweep has to find it again.
KNOWN_MISSES = 3
PING_TIMEOUT_S = 2.0
HTTP_TIMEOUT_S = 2.5
BODY_LIMIT = 20000

# A Studio page id, only ever used when the ARP table has no MAC for the host.
_PAGE_IDS = (
    re.compile(r'data-robot-id="([A-Za-z0-9._:-]{4,})"'),
    re.compile(r'"(?:robotId|serialNumber|serial)"\s*:\s*"([A-Za-z0-9._:-]{4,})"'),
    re.compile(r'Furhat[- ]([0-9A-Fa-f]{6,})'),
)

_MAC_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})\s")


class NetscanDetector:
    name = "netscan"

    def __init__(self, config: Config, bus: EventBus,
                 on_found: Callable[[Found], None]) -> None:
        self.config = config
        self.bus = bus
        self.on_found = on_found
        self._sem = asyncio.Semaphore(MAX_CONCURRENCY)
        # The known-robot refresh has its own lane (and HTTP client): behind
        # a nine-/24 sweep's pings in the shared one it waited past
        # lost_after_s, and every card dropped off every round (2026-11-03).
        self._known_sem = asyncio.Semaphore(8)
        self._misses: dict[str, int] = {}    # refresh misses in a row, by address
        self._refused: set[str] = set()      # subnets already complained about
        self._nameless: set[str] = set()     # addresses already complained about
        self._robots: dict[str, Found] = {}  # Reachy / NAO / Pepper the sweep found, by address
        self._wake = asyncio.Event()

    async def rescan(self) -> None:
        """Sweep now instead of waiting out the cadence."""
        self._wake.set()

    async def _idle(self, interval: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), interval)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake.clear()

    async def run(self) -> None:
        try:
            import httpx  # optional at import time (13.6)
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log(
                "warn",
                "Furhat discovery is off: httpx did not import ({}). "
                "Install it with: pip install -r requirements.txt".format(exc))
            return

        interval = max(1.0, float(self.config.discovery.netscan_interval_s))
        limits = httpx.Limits(max_connections=MAX_CONCURRENCY)
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True,
                                     limits=limits) as client, \
                httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, follow_redirects=True) as known_client:
            refresher = asyncio.create_task(self._refresh_known(known_client),
                                            name="discovery:netscan-known")
            try:
                while True:
                    try:
                        await self._sweep(client)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        self.bus.emit_log(
                            "warn",
                            "network sweep for robots failed this round: {}".format(exc))
                    await self._idle(interval)
            finally:
                refresher.cancel()
                await asyncio.gather(refresher, return_exceptions=True)

    # ---------------------------------------------------------------- sweep
    def _targets(self) -> list[str]:
        targets: list[str] = []
        limit = self.config.discovery.netscan_max_hosts
        for network, own in local_networks():
            hosts = max(network.num_addresses - 2, 1)
            if hosts > limit:
                near = _neighbourhood(network, own, self.config.discovery.netscan_nearby_24s)
                if not near or 254 > limit:
                    self._refuse(network, hosts)
                    continue
                self._refuse(network, hosts, near)
                for block in near:
                    targets += [str(h) for h in block.hosts() if str(h) != own]
                continue
            targets += [str(h) for h in network.hosts() if str(h) != own]
        # A robot found before is asked again even if it now sits outside
        # what is swept (it can only have come from a sweep, so it is local).
        swept = set(targets)
        targets += [ip for ip in self._robots if ip not in swept]
        return targets

    async def _sweep(self, client: Any) -> None:
        targets = self._targets()
        if not targets:
            return

        # An address that has already served a real Studio page skips the ping
        # gate (the gate exists for the VPN's fake port-80 answers, 2.9; the
        # page check below still demands a real reply). Over the iPhone
        # hotspot single pings get lost, and two in a row dropped a healthy
        # Furhat off discovery every minute or so (2026-10-05). A robot the
        # sweep already knows skips it for the same reason.
        pinged = await asyncio.gather(*(
            self._ping(ip) if ip not in self._studio_seen and ip not in self._robots
            else _true()
            for ip in targets))
        alive = [ip for ip, ok in zip(targets, pinged) if ok]
        if not alive:
            return

        pages = await asyncio.gather(*(self._studio_page(client, ip) for ip in alive))
        hits = [(ip, body) for ip, body in zip(alive, pages) if body is not None]
        self._studio_seen = {ip for ip, _body in hits}
        studio = {ip for ip, _body in hits}
        try:
            await self._other_robots(client, [ip for ip in alive if ip not in studio])
        except Exception as exc:  # noqa: BLE001
            log.warning("sweep for Reachy / NAOqi failed this round: %s", exc)
        if not hits:
            return

        arp = await arp_table()
        for ip, body in hits:
            mac = arp.get(ip)
            page_id = None if mac else _page_id(body)
            if not mac and not page_id:
                # Never key a card on an address (2.2) -- say so and move on.
                if ip not in self._nameless:
                    self._nameless.add(ip)
                    self.bus.emit_log(
                        "warn",
                        "A Furhat Studio page answered at {} but this laptop has no "
                        "ARP entry for it and the page carries no id, so the hub "
                        "cannot give it a stable name. Put the robot on the same "
                        "subnet as the laptop and it will appear.".format(ip))
                continue
            self._nameless.discard(ip)
            self._emit(Found(
                type_id="furhat",
                address=ip,
                port=STUDIO_PORT,
                meta={"mac": mac, "studio_id": page_id, "source": "netscan"},
            ))

    _studio_seen: set = frozenset()

    # ------------------------------------------------- Reachy, NAO, Pepper
    # They announce themselves over mDNS, and on the iPhone hotspot that is
    # enough. A lab member's Android hotspot did not pass mDNS between devices
    # (2026-10-06): NAO and Reachy had joined it, Furhat -- found here, by
    # address -- showed up, they did not. So the sweep asks every live address
    # too, and keys each robot exactly as its mDNS sighting would, so a robot
    # seen both ways is one card: Reachy by the daemon's hardware_id (== its
    # mDNS unit_id), NAO / Pepper by "<robot name>.local" (== its mDNS server).

    async def _other_robots(self, client: Any, ips: list[str]) -> None:
        if not ips:
            return
        reachy_on = self.config.robot("reachy_wireless").enabled
        naoqi_on = (self.config.robot("naoqi").enabled
                    or self.config.robot("pepper").enabled)
        reachy_ips: set[str] = set()
        if reachy_on:
            statuses = await asyncio.gather(*(self._reachy_status(client, ip) for ip in ips))
            for ip, status in zip(ips, statuses):
                hardware_id = (status or {}).get("hardware_id")
                if not hardware_id:
                    continue            # the Lite reports none; it is USB anyway
                reachy_ips.add(ip)
                self._emit_robot(Found(type_id="reachy_wireless", address=ip, port=REACHY_PORT,
                                       meta={"unit_id": str(hardware_id), "source": "netscan"}))
        if not naoqi_on:
            return
        rest = [ip for ip in ips if ip not in reachy_ips]
        open_ = await asyncio.gather(*(self._port_open(ip, NAOQI_PORT) for ip in rest))
        for ip in [ip for ip, ok in zip(rest, open_) if ok]:
            ident = await self._naoqi_identity(ip)
            if not ident or not ident.get("robot_name"):
                continue
            name = str(ident["robot_name"]).strip()
            pepper = (str(ident.get("body_type", "")).lower() == "juliette"
                      or name.lower().startswith("pepper"))
            type_id = "pepper" if pepper else "naoqi"
            if not self.config.robot(type_id).enabled:
                continue
            self._emit_robot(Found(type_id=type_id, address=ip, port=NAOQI_PORT,
                                   meta={"server": "{}.local".format(name), "source": "netscan"}))

    # ------------------------------------------------ robots already found
    def _emit_robot(self, found: Found) -> None:
        self._robots[found.address] = found
        self._emit(found)

    async def _refresh_known(self, client: Any) -> None:
        while True:
            await asyncio.sleep(KNOWN_REFRESH_S)
            await self._refresh_once(client)

    async def _refresh_once(self, client: Any) -> None:
        known = list(self._robots.values())
        if not known:
            return
        alive = await asyncio.gather(*(self._still_there(client, f) for f in known),
                                     return_exceptions=True)
        for found, ok in zip(known, alive):
            if ok is True:
                self._misses.pop(found.address, None)
                self._emit(found)
                continue
            if self._robots.get(found.address) is not found:
                continue
            misses = self._misses.get(found.address, 0) + 1
            if ok is False or misses >= KNOWN_MISSES:
                # Replaced by another robot (False), or silent KNOWN_MISSES times
                # in a row: the full sweep finds it again, wherever it is.
                self._robots.pop(found.address, None)
                self._misses.pop(found.address, None)
            else:
                self._misses[found.address] = misses

    async def _still_there(self, client: Any, found: Found) -> Optional[bool]:
        """True: still there. False: another robot answers at that address.
        None: no answer (one lost reply is not a lost robot)."""
        if found.type_id == "reachy_wireless":
            status = await self._reachy_status(client, found.address, self._known_sem)
            if not status:
                return None
            return str(status.get("hardware_id") or "") == found.meta.get("unit_id")
        # NAO / Pepper: the port is enough between sweeps; the sweep itself
        # re-reads the identity (cached NAOQI_ID_TTL_S).
        return (await self._port_open(found.address, found.port, self._known_sem)) or None

    async def _reachy_status(self, client: Any, ip: str,
                             sem: Optional[asyncio.Semaphore] = None) -> Optional[dict]:
        async with sem or self._sem:
            try:
                response = await client.get(
                    "http://{}:{}/api/daemon/status".format(ip, REACHY_PORT))
                data = response.json() if response.status_code == 200 else None
            except Exception:  # noqa: BLE001
                return None
        return data if isinstance(data, dict) else None

    async def _port_open(self, ip: str, port: int,
                         sem: Optional[asyncio.Semaphore] = None) -> bool:
        async with sem or self._sem:
            try:
                _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 1.5)
            except (OSError, asyncio.TimeoutError):
                return False
            w.close()
            return True

    _naoqi_ids: dict = {}
    _naoqi_unavailable_said = False

    async def _naoqi_identity(self, ip: str) -> Optional[dict]:
        """robot_name + body_type through the NAO adapter's own Python 2.7
        helper; cached, because each ask starts Python 2.7 and the SDK."""
        loop = asyncio.get_running_loop()
        cached = self._naoqi_ids.get(ip)
        if cached and cached[0] > loop.time():
            return cached[1]
        from ..adapters.base import AdapterUnavailable
        from ..adapters.naoqi import NaoqiAdapter
        try:
            probe = NaoqiAdapter(Found(type_id="naoqi", address=ip, port=NAOQI_PORT,
                                       meta={}), self.config)
            ident = await probe._call("identity", retries=1)
        except AdapterUnavailable as exc:
            if not self._naoqi_unavailable_said:
                self._naoqi_unavailable_said = True
                self.bus.emit_log("warn", "A NAOqi robot answers at {}, but this laptop "
                                          "cannot talk to it: {}".format(ip, exc))
            ident = None
        except Exception as exc:  # noqa: BLE001
            log.debug("no NAOqi identity from %s: %s", ip, exc)
            ident = None
        ttl = NAOQI_ID_TTL_S if ident else NAOQI_MISS_TTL_S
        self._naoqi_ids = {**self._naoqi_ids, ip: (loop.time() + ttl, ident)}
        return ident

    def _refuse(self, network: Any, hosts: int, near: Any = None) -> None:
        text = str(network)
        if text in self._refused:
            return
        self._refused.add(text)
        limit = self.config.discovery.netscan_max_hosts
        if near is None:
            self.bus.emit_log(
                "warn",
                "Not sweeping {} for robots: {} hosts is more than "
                "discovery.netscan_max_hosts ({}). Raise that setting, or put the "
                "robot on a smaller subnet.".format(text, hosts, limit))
            return
        first, last = min(near, key=lambda b: b.network_address), max(
            near, key=lambda b: b.network_address)
        span = str(first) if len(near) == 1 else "{} to {}".format(first, last)
        self.bus.emit_log(
            "info",
            "Not sweeping all of {} ({} hosts is more than "
            "discovery.netscan_max_hosts, {}): sweeping {}, this laptop's part of "
            "it (discovery.netscan_nearby_24s = {} on each side), for robots that "
            "mDNS cannot reach. A robot elsewhere in {} still appears through "
            "mDNS if this network passes it.".format(
                text, hosts, limit, span, self.config.discovery.netscan_nearby_24s, text))

    def _emit(self, found: Found) -> None:
        try:
            self.on_found(found)
        except Exception as exc:  # noqa: BLE001
            log.warning("discovery callback raised for %s: %s", found.type_id, exc)

    # ---------------------------------------------------------------- probes
    async def _ping(self, ip: str) -> bool:
        if sys.platform == "win32":
            args = ["ping", "-n", "1", "-w", "700", ip]
        else:
            args = ["ping", "-c", "1", "-W", "1", ip]
        async with self._sem:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *args, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
            except (OSError, NotImplementedError) as exc:
                log.debug("cannot run ping: %s", exc)
                return False
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), PING_TIMEOUT_S)
            except asyncio.TimeoutError:
                proc.kill()
                return False
        if proc.returncode != 0:
            return False
        # Windows `ping` exits 0 for a router's "Destination host unreachable"
        # reply, so the reply itself has to be the robot's.
        text = out.decode("utf-8", "replace").lower()
        return "ttl=" in text or sys.platform != "win32"

    async def _studio_page(self, client: Any, ip: str) -> Optional[str]:
        async with self._sem:
            try:
                response = await client.get("http://{}/".format(ip))
            except Exception as exc:  # noqa: BLE001
                log.debug("no HTTP from %s: %s", ip, exc)
                return None
        body = response.text[:BODY_LIMIT]
        return body if STUDIO_TITLE.search(body) else None


# ---------------------------------------------------------------- helpers
def local_networks() -> list[tuple[Any, str]]:
    """Every IPv4 network this laptop is actually on, as (network, own ip).

    Down interfaces, loopback and APIPA are skipped: none of them can carry a
    Furhat, and sweeping 169.254.0.0/16 is exactly the kind of silent waste
    the max-hosts guard exists to stop.
    """
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        log.warning("psutil unavailable, cannot enumerate interfaces: %s", exc)
        return []

    import socket

    stats = psutil.net_if_stats()
    out: list[tuple[Any, str]] = []
    seen: set[str] = set()
    for name, addrs in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.address or not addr.netmask:
                continue
            if addr.address.startswith(("127.", "169.254.")):
                continue
            try:
                network = ipaddress.ip_network(
                    "{}/{}".format(addr.address, addr.netmask), strict=False)
            except ValueError:
                continue
            if str(network) in seen:
                continue
            seen.add(str(network))
            out.append((network, addr.address))
    return out


async def arp_table() -> dict[str, str]:
    """ip -> mac, lowercase colon form. Empty dict when it cannot be read."""
    if sys.platform.startswith("linux"):
        return await asyncio.to_thread(_arp_from_proc)
    try:
        proc = await asyncio.create_subprocess_exec(
            "arp", "-a", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), 5.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("could not read the ARP table: %s", exc)
        return {}
    table: dict[str, str] = {}
    for line in out.decode("utf-8", "replace").splitlines():
        match = _MAC_RE.match(line)
        if match:
            table[match.group(1)] = match.group(2).replace("-", ":").lower()
    return table


def _arp_from_proc() -> dict[str, str]:
    table: dict[str, str] = {}
    try:
        with open("/proc/net/arp", "r", encoding="utf-8") as fh:
            for line in fh.readlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[3] != "00:00:00:00:00:00":
                    table[parts[0]] = parts[3].lower()
    except OSError as exc:
        log.debug("could not read /proc/net/arp: %s", exc)
    return table


def _neighbourhood(network: Any, own: str, radius: int = 0) -> list[Any]:
    """The laptop's own /24 inside a bigger network, then the `radius` /24s on
    each side of it, nearest first (all inside `network`). Empty if the
    network is not bigger than a /24."""
    if network.prefixlen >= 24:
        return []
    home = ipaddress.ip_network("{}/24".format(own), strict=False)
    blocks = [home]
    for step in range(1, max(0, radius) + 1):
        for sign in (1, -1):
            try:
                block = ipaddress.ip_network(
                    (int(home.network_address) + sign * step * 256, 24))
            except ValueError:
                continue
            if block.subnet_of(network):
                blocks.append(block)
    return blocks


def _page_id(body: str) -> Optional[str]:
    for pattern in _PAGE_IDS:
        match = pattern.search(body)
        if match:
            return match.group(1)
    return None


async def _true() -> bool:
    return True
