"""Which WiFi this laptop is on, and whether the robots can join it.

Every lab member brings their own phone hotspot, and the robots only see a
hotspot that offers **2.4 GHz** (Furhat, NAO and Reachy were all measured on
2.4 GHz; an iPhone uses 5 GHz unless *Maximize Compatibility* is on). The
laptop's own link tells us the band: if the laptop is on the hotspot at
5 GHz, so is the hotspot, and the robots will not find it.

Blocking (runs a system command); call it through a thread.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
from typing import Any, Optional

# iOS Personal Hotspot always hands out 172.20.10.0/28 (measured; also why
# it only fits ~13 devices). Android hotspots use 192.168.43.x on older
# phones and a random private /24 on newer ones, so the SSID is the hint there.
IPHONE_NET = ipaddress.ip_network("172.20.10.0/28")
ANDROID_NETS = (ipaddress.ip_network("192.168.43.0/24"),)
PHONE_WORDS = re.compile(r"(?i)iphone|android|galaxy|pixel|xiaomi|redmi|oneplus|"
                         r"huawei|oppo|motorola|moto |hotspot|\bap\b")


def _run(argv: list[str], timeout: float = 8.0) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return ""
    for enc in ("utf-8", "mbcs" if sys.platform == "win32" else "latin-1"):
        try:
            return out.stdout.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return out.stdout.decode("utf-8", "replace")


def _band_from_channel(channel: Optional[int]) -> Optional[str]:
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4 GHz"
    if 32 <= channel <= 177:
        return "5 GHz"
    return None


def _windows() -> dict[str, Any]:
    text = _run(["netsh", "wlan", "show", "interfaces"])
    info: dict[str, Any] = {"ssid": None, "band": None, "channel": None}
    if not text:
        return info
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if " : " in line:
            name, _, value = line.partition(" : ")
            fields.setdefault(name.strip().lower(), value.strip())
    state = fields.get("state", "")
    if state and state.lower() != "connected":
        return info
    info["ssid"] = fields.get("ssid") or None
    try:
        info["channel"] = int(fields.get("channel", ""))
    except ValueError:
        pass
    band = fields.get("band", "")          # Windows 11: "2.4 GHz" / "5 GHz"
    m = re.search(r"(2\.4|5|6)\s*GHz", band)
    info["band"] = "{} GHz".format(m.group(1)) if m else _band_from_channel(info["channel"])
    return info


def _macos() -> dict[str, Any]:
    info: dict[str, Any] = {"ssid": None, "band": None, "channel": None}
    text = _run(["system_profiler", "SPAirPortDataType", "-json"], timeout=15)
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        data = {}
    for item in data.get("SPAirPortDataType", []):
        for iface in item.get("spairport_airport_interfaces", []):
            current = iface.get("spairport_current_network_information")
            if not current:
                continue
            ssid = current.get("_name")
            # macOS 14+ redacts the name for apps without Location access.
            info["ssid"] = None if not ssid or "redacted" in ssid.lower() else ssid
            channel = str(current.get("spairport_network_channel", ""))  # "6 (2GHz, 20MHz)"
            m = re.match(r"\s*(\d+)", channel)
            if m:
                info["channel"] = int(m.group(1))
            if "2GHz" in channel:
                info["band"] = "2.4 GHz"
            elif "5GHz" in channel:
                info["band"] = "5 GHz"
            elif "6GHz" in channel:
                info["band"] = "6 GHz"
            else:
                info["band"] = _band_from_channel(info["channel"])
            return info
    return info


def _linux() -> dict[str, Any]:
    info: dict[str, Any] = {"ssid": None, "band": None, "channel": None}
    text = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,CHAN", "dev", "wifi"])
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[0] == "yes":
            info["ssid"] = parts[1] or None
            try:
                info["channel"] = int(parts[2])
            except ValueError:
                pass
            info["band"] = _band_from_channel(info["channel"])
    return info


def status(addresses: list[str]) -> dict[str, Any]:
    """{ssid, band, channel, hotspot: iphone|android|phone|no|unknown,
    ok: bool, problem: sentence or None}. `addresses` are this laptop's
    IPv4 interfaces ("172.20.10.4/28")."""
    if sys.platform == "win32":
        info = _windows()
    elif sys.platform == "darwin":
        info = _macos()
    else:
        info = _linux()

    ips = []
    for a in addresses:
        try:
            ips.append(ipaddress.ip_interface(a).ip)
        except ValueError:
            pass
    ssid = info.get("ssid") or ""
    if any(ip in IPHONE_NET for ip in ips):
        hotspot = "iphone"
    elif any(ip in net for net in ANDROID_NETS for ip in ips):
        hotspot = "android"
    elif ssid and PHONE_WORDS.search(ssid):
        hotspot = "phone"
    elif info.get("band") is None and not ssid:
        hotspot = "unknown"
    else:
        hotspot = "no"

    problem = None
    if info.get("band") is None and not ssid and not ips:
        problem = "This laptop is not on any network."
    elif info.get("band") in ("5 GHz", "6 GHz") and hotspot != "no":
        problem = ("Your hotspot is on {} — the robots cannot see it. Turn on 2.4 GHz "
                   "(iPhone: Maximize Compatibility; Android: AP band 2.4 GHz), then "
                   "reconnect this laptop to it.".format(info["band"]))
    elif hotspot == "no":
        problem = ("This laptop is on {}, which does not look like a phone hotspot. "
                   "The robots join your phone's hotspot — connect the laptop to it "
                   "too.".format("“{}”".format(ssid) if ssid else "a wired or unknown network"))
    info.update({"hotspot": hotspot, "ok": problem is None, "problem": problem,
                 "platform": sys.platform})
    return info
