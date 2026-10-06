"""The laptop's own interfaces -- a first-class detector (PLAN.md 2.8).

On 2026-09-14 the laptop silently roamed from the hotspot to campus WiFi.
Every robot went unreachable at once, the desktop app's log simply froze, and
there was no error anywhere. It read as "the robot hung" and cost about an
hour. The hub watches its own network so that failure says what it is instead
of showing four mysteriously dead cards.

`discovery.expected_subnet` pins the answer when the lab knows it. When it is
blank the subnet is *inferred*: the manager reports the address of every robot
it actually finds, and the last such subnet becomes the one to be off of. Both
paths emit the same event, only when it changes:

    {"on_robot_subnet": bool, "interfaces": ["172.20.10.4/28", ...]}
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any, Callable, Optional

from ..config import Config
from ..events import EventBus

log = logging.getLogger("hub.discovery.selfnet")


class SelfNetDetector:
    name = "network"

    def __init__(self, config: Config, bus: EventBus,
                 on_network: Callable[[dict[str, Any]], None]) -> None:
        self.config = config
        self.bus = bus
        self.on_network = on_network
        self._last: Optional[dict[str, Any]] = None
        self._robot_network: Optional[Any] = None   # inferred, when unset in config
        self._interfaces: list[Any] = []            # refreshed by the run loop
        self._wake = asyncio.Event()

    # ------------------------------------------------------- manager hooks
    def record_robot_address(self, address: str) -> None:
        """Remember the subnet a robot was actually found on (2.8).

        Loopback is ignored on purpose: the Reachy Mini Lite is reported at
        127.0.0.1 because the desktop app is its daemon host (2.6), and USB
        presence says nothing at all about which WiFi this laptop is on.
        """
        if self.config.discovery.expected_subnet:
            return
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return
        if ip.is_loopback or ip.is_link_local or ip.version != 4:
            return
        network = self._containing_network(ip) or ipaddress.ip_network(
            "{}/24".format(ip), strict=False)
        if self._robot_network != network:
            self._robot_network = network
            log.info("robots are on %s", network)

    # ------------------------------------------------------------ lifecycle
    async def rescan(self) -> None:
        """Re-state the network now, unchanged or not -- someone pressing Scan
        is entitled to see the banner's answer again."""
        self._last = None
        self._wake.set()

    async def run(self) -> None:
        interval = max(0.5, float(self.config.discovery.selfnet_interval_s))
        while True:
            info = self.snapshot()
            if info != self._last:
                self._last = info
                try:
                    self.on_network(info)
                except Exception as exc:  # noqa: BLE001
                    log.warning("network callback raised: %s", exc)
            try:
                await asyncio.wait_for(self._wake.wait(), interval)
            except asyncio.TimeoutError:
                continue
            finally:
                self._wake.clear()

    # -------------------------------------------------------------- reading
    def snapshot(self) -> dict[str, Any]:
        interfaces = local_ipv4()
        self._interfaces = interfaces
        return {
            "on_robot_subnet": self._on_robot_subnet(interfaces),
            "interfaces": [str(n) for n in interfaces],
        }

    def _on_robot_subnet(self, interfaces: list[Any]) -> bool:
        if not interfaces:
            return False
        expected = self.config.discovery.expected_subnet.strip()
        if expected:
            try:
                wanted = ipaddress.ip_network(expected, strict=False)
            except ValueError:
                self.bus.emit_log(
                    "warn",
                    "discovery.expected_subnet is not a subnet: {!r}. Write it "
                    "like 172.20.10.0/28, or leave it blank to infer.".format(expected))
                return True
            return any(iface.ip in wanted for iface in interfaces)

        if self._robot_network is None:
            # Nothing has been found yet, so there is nothing to be off of.
            return True
        return any(iface.ip in self._robot_network for iface in interfaces)

    def _containing_network(self, ip: Any) -> Optional[Any]:
        for iface in self._interfaces or local_ipv4():
            if ip in iface.network:
                return iface.network
        return None


# ---------------------------------------------------------------- helpers
def local_ipv4() -> list[Any]:
    """Up, non-loopback IPv4 interfaces as ip_interface objects.

    A link-local 169.254 address means DHCP never answered, which is a
    failure, not a network -- so it only counts when it is all there is, and
    then the banner is what explains the dead cards.
    """
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        log.warning("psutil unavailable, cannot watch this laptop's network: %s", exc)
        return []

    import socket

    stats = psutil.net_if_stats()
    real: list[Any] = []
    apipa: list[Any] = []
    for name, addrs in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        for addr in addrs:
            if addr.family != socket.AF_INET or not addr.address:
                continue
            if addr.address.startswith("127."):
                continue
            try:
                iface = ipaddress.ip_interface(
                    "{}/{}".format(addr.address, addr.netmask or "255.255.255.0"))
            except ValueError:
                continue
            (apipa if addr.address.startswith("169.254.") else real).append(iface)
    return real or apipa
