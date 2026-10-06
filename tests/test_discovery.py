"""Discovery tests, all offline.

These pin the measured traps from PLAN.md 2 -- the ones that cost hours to
find and would be cheap to "simplify" away later:

  * identity comes from TXT model + unit_id, never the mDNS instance name,
    which Bonjour renames by boot order (2.2)
  * the Lite's advertised Tailscale address is unreachable and must be
    replaced by the loopback the desktop app proxies it onto (6)
  * an open port 80 is not proof of life on this laptop (2.9)
  * the laptop's own roaming is a first-class signal, not an edge case (2.8)

    .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.config import load_config  # noqa: E402
from hub.discovery import mdns as M  # noqa: E402
from hub.discovery import usbwatch as U  # noqa: E402
from hub.discovery.manager import DiscoveryManager  # noqa: E402
from hub.events import EventBus  # noqa: E402


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def detector(config):
    return M.MdnsDetector(config, EventBus(), lambda found: None)


class FakeInfo:
    """Shaped like zeroconf.ServiceInfo, for the fields mdns.py reads."""

    def __init__(self, props, addrs, server="host.local.", port=8000):
        self.properties = props
        self._addrs = addrs
        self.server = server
        self.port = port

    def parsed_addresses(self):
        return self._addrs


def reachy(model, unit=None, addrs=("172.20.10.10",), name="reachy_mini"):
    props = {b"model": model.encode()}
    if unit:
        props[b"unit_id"] = unit.encode()
    return (M.REACHY_SERVICE, f"{name}._reachy-mini._tcp.local.",
            FakeInfo(props, list(addrs)))


# --------------------------------------------------------------------- mDNS
def test_the_measured_capture_resolves_to_the_right_two_robots(detector):
    """The exact pair observed with both Reachys powered on 2026-09-14."""
    wireless = detector._to_found(*reachy(
        "Reachy Mini Wireless", "58b3b6a4bf81179a",
        ("172.20.10.10",), name="reachy_mini-2"))
    lite = detector._to_found(*reachy(
        "Reachy Mini Lite", None, ("100.98.102.61",), name="reachy_mini"))

    assert wireless.type_id == "reachy_wireless"
    assert wireless.address == "172.20.10.10"
    assert lite.type_id == "reachy_lite"
    # The Lite advertises a Tailscale address nothing can reach.
    assert lite.address == "127.0.0.1"


def test_identity_survives_the_instance_name_swapping(detector):
    """The "-2" suffix lands on whichever robot booted second. If the type or
    the key followed the name, the two Reachys would trade cards on reboot."""
    first = detector._to_found(*reachy(
        "Reachy Mini Wireless", "58b3b6a4bf81179a", name="reachy_mini-2"))
    after_reboot = detector._to_found(*reachy(
        "Reachy Mini Wireless", "58b3b6a4bf81179a",
        ("172.20.10.14",), name="reachy_mini"))

    assert after_reboot.type_id == first.type_id
    assert after_reboot.txt("unit_id") == first.txt("unit_id")
    assert after_reboot.address != first.address


def test_a_pepper_on_the_naoqi_service_is_a_pepper_not_a_nao(detector):
    # 2026-10-06: Pepper.local advertises RobotType=Pepper (exact case). It
    # used to be dropped; now it gets its own card, never a NAO's.
    pepper = detector._to_found(
        M.NAOQI_SERVICE, "Pepper._naoqi._tcp.local.",
        FakeInfo({b"RobotType": b"Pepper"}, ["172.20.10.2"], port=9559))
    assert pepper is not None and pepper.type_id == "pepper"
    assert pepper.address == "172.20.10.2"


def test_an_unknown_naoqi_robot_type_is_ignored(detector):
    assert detector._to_found(
        M.NAOQI_SERVICE, "R._naoqi._tcp.local.",
        FakeInfo({b"RobotType": b"Romeo"}, ["10.0.0.7"], port=9559)) is None


def test_unknown_reachy_model_is_ignored(detector):
    assert detector._to_found(*reachy("Reachy Mini Mk9")) is None


def test_routable_address_beats_link_local(detector):
    nao = detector._to_found(
        M.NAOQI_SERVICE, "NAO._naoqi._tcp.local.",
        FakeInfo({b"RobotType": b"Nao"}, ["169.254.9.9", "10.0.0.5"], port=9559))
    assert nao.address == "10.0.0.5"

    # ...but link-local is perfectly valid when the cable is all there is.
    cable = detector._to_found(
        M.NAOQI_SERVICE, "NAO._naoqi._tcp.local.",
        FakeInfo({b"RobotType": b"Nao"}, ["169.254.9.9"], port=9559))
    assert cable.address == "169.254.9.9"


# ---------------------------------------------------------------------- USB
def test_usb_serial_parsing():
    assert U._serial_from_device_id(
        r"USB\VID_38FB&PID_1001\100025004261401779") == "100025004261401779"
    # A generated instance path depends on which port it was plugged into,
    # so it is not an identity.
    assert U._serial_from_device_id(
        r"USB\VID_38FB&PID_1001&MI_00\7&2A3B1C4D&0&0000") is None
    assert U._serial_from_device_id(r"USB\VID_38FB&PID_1001") is None


# ------------------------------------------------------------------ netscan
def test_netscan_refuses_an_oversized_subnet(config):
    """A /16 sweep would be thousands of pings every few seconds."""
    import ipaddress
    from hub.discovery.netscan import NetscanDetector

    config.discovery.netscan_max_hosts = 256
    bus = EventBus()
    det = NetscanDetector(config, bus, lambda f: None)
    net = ipaddress.ip_network("10.0.0.0/16")
    det._refuse(net, net.num_addresses)

    said = " ".join(e["text"] for e in bus.recent())
    assert "Not sweeping" in said, "it must say why it declined, not go quiet"
    assert "netscan_max_hosts" in said, "and name the setting that would allow it"

    det._refuse(net, net.num_addresses)
    assert said.count("Not sweeping") == 1, "and say it once, not every cycle"


def test_furhat_fingerprint_needs_the_real_title():
    """Port 80 answering is not proof: the Check Point adapter on this laptop
    makes connect() succeed for hosts that do not exist (2.9), so the only
    acceptable evidence is Studio's own title in a real HTTP body."""
    from hub.discovery.netscan import STUDIO_TITLE

    assert STUDIO_TITLE.search("<html><head><title>Furhat Studio</title></head>")
    assert STUDIO_TITLE.search("<title> Furhat  Studio </title>")
    assert not STUDIO_TITLE.search("<html><title>Router Login</title></html>")
    assert not STUDIO_TITLE.search("")


# ------------------------------------------------------------------ manager
def test_manager_start_stop_is_clean_and_idempotent(config):
    config.discovery.mdns = False
    config.discovery.usb = False
    config.discovery.netscan = False

    async def run():
        mgr = DiscoveryManager(config, EventBus(), on_found=lambda f: None,
                               on_lost=lambda t, k: None, on_network=lambda i: None)
        await mgr.start()
        await asyncio.sleep(0.2)
        await mgr.stop()
        await mgr.stop()      # a second stop must not raise
        assert mgr.snapshot() == {}

    asyncio.run(run())


def test_the_robots_own_txt_address_beats_a_shared_hostname():
    # Two Reachys share the hostname reachy-mini.local; its A record answered
    # with reachy2's address for reachy3 (2026-10-05).
    from hub.discovery.mdns import _pick_address
    assert _pick_address({"address": "172.20.10.3"}, ["172.20.10.2"]) == "172.20.10.3"
    assert _pick_address({}, ["172.20.10.2"]) == "172.20.10.2"
    # link-local still loses to routable, wherever it came from
    assert _pick_address({"address": "169.254.4.4"}, ["172.20.10.14"]) == "172.20.10.14"


# ------------------------------------------- sweep: Reachy, NAO, Pepper
def test_the_sweep_finds_robots_mdns_cannot_reach(monkeypatch):
    # 2026-10-06, a Galaxy hotspot: NAO and reachy2 had joined, but no mDNS
    # reached the laptop. The sweep keys them as mDNS would, so it is one card.
    import asyncio
    from hub.config import load_config
    from hub.discovery import netscan as NS

    found = []
    d = NS.NetscanDetector(load_config(), type("B", (), {"emit_log": lambda *a: None})(),
                           found.append)

    async def status(client, ip):
        return {"hardware_id": "1bf3f0e96e9b0151"} if ip == "10.0.0.100" else None

    async def port_open(ip, port):
        return ip in ("10.0.0.214", "10.0.0.2")

    async def identity(ip):
        return ({"robot_name": "nao", "body_type": "Nao"} if ip == "10.0.0.214"
                else {"robot_name": "Pepper", "body_type": "Juliette"})

    monkeypatch.setattr(d, "_reachy_status", status)
    monkeypatch.setattr(d, "_port_open", port_open)
    monkeypatch.setattr(d, "_naoqi_identity", identity)
    asyncio.run(d._other_robots(None, ["10.0.0.100", "10.0.0.214", "10.0.0.2", "10.0.0.9"]))

    got = {(f.type_id, f.address): f.meta for f in found}
    assert got[("reachy_wireless", "10.0.0.100")]["unit_id"] == "1bf3f0e96e9b0151"
    assert got[("naoqi", "10.0.0.214")]["server"] == "nao.local"
    assert got[("pepper", "10.0.0.2")]["server"] == "Pepper.local"
    assert len(found) == 3
