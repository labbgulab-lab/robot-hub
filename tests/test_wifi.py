"""The Network setup check: reading the laptop's WiFi on Windows and macOS,
and telling a lab member when the robots cannot join their hotspot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hub import wifi  # noqa: E402

NETSH = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Lab Hotspot
    BSSID                  : 4a:00:00:00:00:01
    Network type           : Infrastructure
    Radio type             : 802.11ax
    Band                   : 5 GHz
    Channel                : 149
"""

MAC = {"SPAirPortDataType": [{"spairport_airport_interfaces": [
    {"_name": "en0", "spairport_current_network_information": {
        "_name": "Dana Phone", "spairport_network_channel": "6 (2GHz, 20MHz)"}}]}]}


def _on(monkeypatch, platform, text):
    monkeypatch.setattr(wifi.sys, "platform", platform)
    monkeypatch.setattr(wifi, "_run", lambda argv, timeout=8.0: text)


def test_an_iphone_hotspot_on_5ghz_is_flagged(monkeypatch):
    _on(monkeypatch, "win32", NETSH)
    info = wifi.status(["172.20.10.4/28"])
    assert info["ssid"] == "Lab Hotspot" and info["band"] == "5 GHz"
    assert info["hotspot"] == "iphone" and not info["ok"]
    assert "Maximize Compatibility" in info["problem"]


def test_a_2_4ghz_hotspot_on_a_mac_is_fine(monkeypatch):
    _on(monkeypatch, "darwin", json.dumps(MAC))
    info = wifi.status(["172.20.10.6/28"])
    assert (info["ssid"], info["band"], info["channel"]) == ("Dana Phone", "2.4 GHz", 6)
    assert info["ok"] and info["problem"] is None


def test_campus_wifi_is_not_a_hotspot(monkeypatch):
    _on(monkeypatch, "win32", NETSH.replace("Lab Hotspot", "eduroam").replace("5 GHz", "2.4 GHz"))
    info = wifi.status(["10.12.0.55/16"])
    assert info["hotspot"] == "no" and not info["ok"]
    assert "eduroam" in info["problem"]


def test_an_android_hotspot_is_known_by_its_name(monkeypatch):
    _on(monkeypatch, "win32", NETSH.replace("Lab Hotspot", "Galaxy S24").replace("Band                   : 5 GHz\n", "")
        .replace("149", "11"))
    info = wifi.status(["192.168.89.20/24"])
    assert info["hotspot"] == "phone" and info["band"] == "2.4 GHz" and info["ok"]


def test_a_redacted_mac_name_still_reports_the_band(monkeypatch):
    redacted = json.loads(json.dumps(MAC))
    redacted["SPAirPortDataType"][0]["spairport_airport_interfaces"][0][
        "spairport_current_network_information"]["_name"] = "<redacted>"
    _on(monkeypatch, "darwin", json.dumps(redacted))
    info = wifi.status(["172.20.10.6/28"])
    assert info["ssid"] is None and info["band"] == "2.4 GHz" and info["ok"]
