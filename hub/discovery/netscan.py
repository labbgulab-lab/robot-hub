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
MAX_CONCURRENCY = 64
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
        self._refused: set[str] = set()      # subnets already complained about
        self._nameless: set[str] = set()     # addresses already complained about
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
                                     limits=limits) as client:
            while True:
                try:
                    await self._sweep(client)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.bus.emit_log(
                        "warn",
                        "network sweep for Furhat failed this round: {}".format(exc))
                await self._idle(interval)

    # ---------------------------------------------------------------- sweep
    async def _sweep(self, client: Any) -> None:
        targets: list[str] = []
        for network, own in local_networks():
            hosts = max(network.num_addresses - 2, 1)
            if hosts > self.config.discovery.netscan_max_hosts:
                self._refuse(network, hosts)
                continue
            targets += [str(h) for h in network.hosts() if str(h) != own]
        if not targets:
            return

        # An address that has already served a real Studio page skips the ping
        # gate (the gate exists for the VPN's fake port-80 answers, 2.9; the
        # page check below still demands a real reply). Over the iPhone
        # hotspot single pings get lost, and two in a row dropped a healthy
        # Furhat off discovery every minute or so (2026-10-05).
        pinged = await asyncio.gather(*(
            self._ping(ip) if ip not in self._studio_seen else _true()
            for ip in targets))
        alive = [ip for ip, ok in zip(targets, pinged) if ok]
        if not alive:
            return

        pages = await asyncio.gather(*(self._studio_page(client, ip) for ip in alive))
        hits = [(ip, body) for ip, body in zip(alive, pages) if body is not None]
        self._studio_seen = {ip for ip, _body in hits}
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

    def _refuse(self, network: Any, hosts: int) -> None:
        text = str(network)
        if text in self._refused:
            return
        self._refused.add(text)
        self.bus.emit_log(
            "warn",
            "Not sweeping {} for Furhat: {} hosts is more than "
            "discovery.netscan_max_hosts ({}). Raise that setting, or put the "
            "robot on a smaller subnet.".format(
                text, hosts, self.config.discovery.netscan_max_hosts))

    def _emit(self, found: Found) -> None:
        try:
            self.on_found(found)
        except Exception as exc:  # noqa: BLE001
            log.warning("discovery callback raised for furhat: %s", exc)

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


def _page_id(body: str) -> Optional[str]:
    for pattern in _PAGE_IDS:
        match = pattern.search(body)
        if match:
            return match.group(1)
    return None


async def _true() -> bool:
    return True
