"""tools/reachy_bringup.py end to end against a scripted robot and laptop
WiFi: a factory robot on reachy-mini-ap, and one already on the hotspot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import reachy_bringup as B  # noqa: E402

MAC = "88:A2:9E:00:00:04"
HW = "abcdef0123456789"
IP = "172.20.10.7"
HOME = {"ssid": "Tomer Iphone", "profile": "Tomer Iphone"}


class FakeRobot:
    log: list = []
    silent_move = False     # the forced move cuts the session before the reply

    def __init__(self, ip, user, password):
        self.ip = ip

    def run(self, command, stdin_text=None, timeout_s=60.0):
        FakeRobot.log.append((self.ip, command[:40], stdin_text))
        if "hubwifi" in command:
            move = command.rsplit(" ", 1)[-1]
            if FakeRobot.silent_move and move == "2":
                return -1, ""
            return 0, "CURRENT Hotspot\nSEEN no\nACTION saved\nMOVE {}\n".format(
                "yes" if move == "2" else "no")
        return 0, ""

    def identity(self):
        return {"wifi_mac": MAC, "pi_serial": "10000000aa", "os": "Debian 13"}

    def pin(self):
        return "97531"


class Done:
    returncode, stdout, stderr = 0, "", ""


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = {"joined": [], "posted": [], "on_hotspot": False, "version": "1.2.11"}
    FakeRobot.log = []
    FakeRobot.silent_move = False
    example = tmp_path / "config.example.toml"
    example.write_text('[robots.reachy_wireless]\n  [robots.reachy_wireless.settings]\n',
                       encoding="utf-8")
    monkeypatch.setattr(B, "EXAMPLE", example)
    monkeypatch.setattr(B, "OUT_DIR", tmp_path / "bringup")
    monkeypatch.setattr(B, "STATUS", tmp_path / "bringup" / "status.json")
    monkeypatch.setattr(B, "registered", lambda: {})
    monkeypatch.setattr(B, "write_config", lambda *a: w.setdefault("config", a))
    monkeypatch.setattr(B, "Robot", FakeRobot)
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setattr(B, "wlan_visible", lambda: {"reachy-mini-ap": "WPA2-Personal"})
    monkeypatch.setattr(B, "wlan_add_profile", lambda ssid, pw: w.setdefault("profile", (ssid, pw)))

    def join(profile, ssid, wait_s=40):
        w["joined"].append(ssid)
        if ssid == HOME["ssid"]:
            w["on_hotspot"] = True
        return True
    monkeypatch.setattr(B, "wlan_join", join)
    monkeypatch.setattr(B, "wlan_now", lambda: {"ssid": w["joined"][-1] if w["joined"] else HOME["ssid"]})

    def status(ip, timeout=3.0):
        if ip == B.AP_ADDRESS:
            return {"version": w["version"]}            # old daemons: no hardware_id
        return {"version": w["version"], "hardware_id": HW}
    monkeypatch.setattr(B, "daemon_status", status)
    monkeypatch.setattr(B, "sweep", lambda: {IP: status(IP)} if w["on_hotspot"] else {})
    monkeypatch.setattr(B, "arp_macs", lambda: {IP: MAC})

    def post(ip, path, body=None, timeout=15):
        w["posted"].append((ip, path, body))
        if path == "/update/start":
            w["version"] = "1.11.0"
        return {}
    monkeypatch.setattr(B, "post", post)
    monkeypatch.setattr(B, "get", lambda ip, path, timeout=15: {"is_available": True})
    return w


def _args(tmp_path, **kw):
    base = dict(name="reachy4", sn="SN4", fleet_file=tmp_path / "FLEET.md", host=None,
                skip_update=False, skip_app=False)
    base.update(kw)
    return argparse.Namespace(**base)


def _run(tmp_path, args=None, lab=("Lab Net", "labpass12")):
    details = {"name": "reachy4", "pollen_sn": "SN4", "hotspot": HOME["ssid"]}
    ok = B.bring_up(args or _args(tmp_path), details, HOME, "pollen", "root",
                    lab[0], lab[1], "hotpass12", tmp_path, tmp_path / "python.exe")
    return ok, details


def test_a_factory_robot_goes_from_its_own_wifi_to_the_fleet(world, tmp_path):
    ok, d = _run(tmp_path)
    assert ok
    # laptop: robot's AP, then back to the hotspot
    assert world["profile"] == ("reachy-mini-ap", "reachy-mini")
    assert world["joined"][:2] == ["reachy-mini-ap", HOME["ssid"]]
    # on the AP: lab WiFi first (fallback, no move), then the hotspot (forced move)
    wifi = [(ip, stdin) for ip, cmd, stdin in FakeRobot.log if "hubwifi" in cmd or "bash -c" in cmd
            if stdin]
    assert wifi == [(B.AP_ADDRESS, "root\nlabpass12\n"), (B.AP_ADDRESS, "root\nhotpass12\n")]
    # online: updated (1.2.11 is too old), named, then recorded under the real hardware_id
    assert (IP, "/update/start", None) in world["posted"]
    assert (IP, "/api/daemon/robot-name", {"name": "reachy4"}) in world["posted"]
    assert d["unit_id"] == HW and d["daemon"] == "1.11.0" and d["ble_pin"] == "97531"
    assert d["ip"] == IP and d["wifi_mac"] == MAC
    assert world["config"][:3] == (HW, "reachy4", "SN4")
    assert 'units."{}"]\n  display_name = "reachy4"'.format(HW) in B.EXAMPLE.read_text(encoding="utf-8")
    fleet = (tmp_path / "FLEET.md").read_text(encoding="utf-8")
    assert "## reachy4" in fleet and "97531" in fleet and "SN4" in fleet


def test_a_lost_reply_on_the_access_point_still_follows_the_robot(world, tmp_path):
    # reachy4, 2026-10-19: no reply, yet it had saved the hotspot and moved
    FakeRobot.silent_move = True
    ok, d = _run(tmp_path)
    assert ok and d["ip"] == IP
    assert world["joined"][:2] == ["reachy-mini-ap", HOME["ssid"]]
    assert d["hotspot"] == "Tomer Iphone (priority 0)"


def test_a_lost_reply_and_no_robot_on_the_hotspot_reads_why(world, tmp_path, monkeypatch):
    FakeRobot.silent_move = True
    monkeypatch.setattr(B, "sweep", lambda: {})
    clock = iter(range(0, 10 ** 6, 30))       # the 4-min search ends in a few laps
    monkeypatch.setattr(B.time, "monotonic", lambda: next(clock))
    with pytest.raises(RuntimeError, match="could not join"):
        _run(tmp_path)
    assert world["joined"][-1] == "reachy-mini-ap"


def test_no_reply_to_a_save_that_does_not_move_is_still_an_error(world, tmp_path, monkeypatch):
    world["on_hotspot"] = True
    world["version"] = "1.11.0"
    monkeypatch.setattr(FakeRobot, "run", lambda self, c, s=None, t=60.0: (0, ""))
    with pytest.raises(B.NoReply, match="no reply"):
        _run(tmp_path)


def test_the_pin_never_reaches_the_public_example(world, tmp_path):
    _run(tmp_path)
    text = B.EXAMPLE.read_text(encoding="utf-8")
    assert "97531" not in text and MAC not in text and "SN4" not in text


def test_a_robot_already_on_the_hotspot_skips_the_access_point(world, tmp_path):
    world["on_hotspot"] = True
    world["version"] = "1.11.0"
    ok, d = _run(tmp_path)
    assert ok and world["joined"] == []
    assert not any(p[1] == "/update/start" for p in world["posted"])
    moves = [cmd for _ip, cmd, stdin in FakeRobot.log if stdin]
    assert len(moves) == 2


def test_without_a_lab_wifi_only_the_hotspot_is_saved(world, tmp_path):
    ok, d = _run(tmp_path, lab=("", ""))
    assert ok and "lab_wifi" not in d
    assert [s for _ip, _c, s in FakeRobot.log if s] == ["root\nhotpass12\n"]


def test_a_robot_registered_under_another_name_is_refused(world, tmp_path, monkeypatch):
    world["on_hotspot"] = True
    world["version"] = "1.11.0"
    monkeypatch.setattr(B, "registered", lambda: {HW: "reachy2"})
    monkeypatch.setattr(B, "sweep", lambda: {})
    with pytest.raises(RuntimeError, match="already registered as reachy2"):
        _run(tmp_path, args=_args(tmp_path, host=IP))


def test_next_name_counts_every_list(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "registered", lambda: {"a": "reachy1", "b": "reachy3"})
    fleet = tmp_path / "FLEET.md"
    fleet.write_text("## reachy7 -- brought up\n", encoding="utf-8")
    assert B.next_name(fleet) == "reachy8"
    assert B.next_name(None) == "reachy4"
