"""Reachy "Add WiFi...": a lab member's hotspot over SSH, the lab WiFi as the
fallback (hub/reachy_wifi.py). The robot-side script itself was run against
fake nmcli / sudo / setsid in bash; these cover the hub side."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import reachy_wifi as W  # noqa: E402
from hub import wifi  # noqa: E402


class Robot:
    """Scripted SSH: the first call answers the save, later ones the watch."""

    def __init__(self, save_output, results=(), status=0):
        self.save = (status, save_output)
        self.results = list(results)
        self.calls = []

    def __call__(self, command, stdin_text, timeout_s):
        self.calls.append((command, stdin_text))
        if len(self.calls) == 1:
            return self.save
        nxt = self.results.pop(0) if self.results else ConnectionError("gone")
        if isinstance(nxt, Exception):
            raise nxt
        return 0, nxt


def _teach(robot, ssid="Dana Phone", lab=False):
    clock = iter(range(0, 10_000, 5))
    return W.teach(robot, "root", ssid, "secretpass1", lab, "reachy2",
                   sleep=lambda s: None, clock=lambda: next(clock))


SAVED_MOVE = "CURRENT Lab Net\nSEEN yes\nACTION saved\nMOVE yes\n"


def test_secrets_travel_on_stdin_never_in_the_command():
    robot = Robot(SAVED_MOVE)
    _teach(robot)
    command, stdin = robot.calls[0]
    assert stdin == "root\nsecretpass1\n"
    assert "secretpass1" not in command and "root\n" not in command
    assert "'Dana Phone' 10 1" in command


def test_a_hotspot_wins_and_the_lab_wifi_never_does():
    assert W.command("Dana Phone", lab=False).endswith("'Dana Phone' 10 1")
    assert W.command("Lab Net", lab=True).endswith("'Lab Net' -10 0")


def test_gone_after_the_move_means_it_joined():
    msg = _teach(Robot(SAVED_MOVE, results=["", ConnectionError("away")]))
    assert "moved to “Dana Phone”" in msg and "Connect this laptop" in msg


def test_back_with_fail_means_wrong_password_and_where_it_is():
    with pytest.raises(RuntimeError, match="could not join .*forgot it again.*“Lab Net”"):
        _teach(Robot(SAVED_MOVE, results=[ConnectionError("away"), "fail\n"]))


def test_an_updated_profile_is_kept_after_a_failed_move():
    robot = Robot(SAVED_MOVE.replace("saved", "updated"), results=["fail"])
    with pytest.raises(RuntimeError) as err:
        _teach(robot)
    assert "forgot" not in str(err.value)


def test_out_of_range_is_saved_not_moved():
    msg = _teach(Robot("CURRENT Lab Net\nSEEN no\nACTION saved\nMOVE no\n"))
    assert "cannot see it right now" in msg and "stays on “Lab Net”" in msg


def test_the_lab_wifi_is_saved_without_moving():
    robot = Robot("CURRENT Tomer Iphone\nSEEN yes\nACTION saved\nMOVE no\n")
    msg = _teach(robot, ssid="Lab Net", lab=True)
    assert "as the lab WiFi" in msg and "stays on “Tomer Iphone”" in msg
    assert len(robot.calls) == 1            # nothing to watch


def test_the_robots_own_error_is_shown():
    with pytest.raises(RuntimeError, match="no WiFi device"):
        _teach(Robot("ERR this robot has no WiFi device\n", status=3))


def test_sudo_refused_names_the_setting():
    with pytest.raises(RuntimeError, match="REACHY_SSH_PASSWORD"):
        _teach(Robot("sudo: 1 incorrect password attempt\n", status=1))


@pytest.mark.parametrize("ssid,password,why", [
    ("", "secretpass1", "1 to 32"),
    ("x" * 33, "secretpass1", "1 to 32"),
    ("Dana Phone", "short", "8 to 63"),
    ("reachy-mini-ap", "secretpass1", "setup network"),
    ("Dana Phone", "two\nlines1", "line break"),
])
def test_bad_input_never_reaches_the_robot(ssid, password, why):
    robot = Robot(SAVED_MOVE)
    with pytest.raises(RuntimeError, match=why):
        W.teach(robot, "root", ssid, password)
    assert robot.calls == []


def test_the_network_panel_accepts_the_lab_wifi(monkeypatch):
    monkeypatch.setattr(wifi.sys, "platform", "win32")
    monkeypatch.setattr(wifi, "_run", lambda argv, timeout=8.0: (
        "    SSID                   : Lab Net\n    Band                   : 5 GHz\n"
        "    Channel                : 36\n"))
    info = wifi.status(["10.0.0.5/24"], lab_wifi="Lab Net")
    assert info["hotspot"] == "lab" and info["ok"]
    assert wifi.status(["10.0.0.5/24"])["hotspot"] == "no"
