"""One network state for the whole app (STUDENT-APP-PLAN 7, 7c).

    {"state": "ok" | "searching" | "no_network" | "wrong_network" |
              "hotspot_5ghz" | "vpn_on" | "isolated",
     "ssid", "band", "kind": "lab" | "hotspot" | "other" | "none",
     "ranges": ["10.0.4.0/24", ...],
     "hotspot": {"devices": n, "limit": 5},
     "robots_network": {"ssid", "last_seen"},
     "vpn": [adapter names], "detail": short sentence}

`compute()` is pure, so every rule is tested without a network. The hub
(hub/core.py) feeds it the WiFi reading (hub/wifi.py), the VPN adapters,
the sweep's stats and the robots it can see, and pushes the result as the
`network` event.

The rules, first match wins:
  - robots are here               -> ok (whatever else is odd, it works)
  - no address and no WiFi        -> no_network
  - a VPN or Tailscale adapter up -> vpn_on
  - a phone hotspot on 5/6 GHz    -> hotspot_5ghz (robots only see 2.4 GHz)
  - on SSID X, robots expected on Y -> wrong_network. Y is where robots were
    last seen (remembered in settings.json, so this works from a cold start),
    else the lab WiFi. A phone hotspot is never "wrong" against the lab WiFi:
    that is how a demo outside the lab runs.
  - the sweep ran twice on the lab WiFi (or another non-hotspot network)
    and saw no other device at all -> isolated
  - the sweep has not finished twice yet -> searching
  - otherwise                      -> ok (no robot is on yet)
An unknown WiFi name (netsh failed, or Location is off) never raises a
warning by itself.
"""

from __future__ import annotations

from typing import Any, Optional

HOTSPOT_LIMIT = 5
# Pepper's chest tablet joins the WiFi on its own, so Pepper takes two spots.
HOTSPOT_SPOTS = {"pepper": 2}
# A USB robot (the Lite) is not on the WiFi at all.
NOT_ON_WIFI = {"reachy_lite"}

DETAILS = {
    "ok": "",
    "searching": "Looking for robots.",
    "no_network": "This laptop is not on any network.",
    "wrong_network": "This laptop is on {ssid}. The robots are on {expected}.",
    "hotspot_5ghz": "Your hotspot is on {band}. Robots only see 2.4 GHz.",
    "vpn_on": "A VPN is on. Robots may not show up until you turn it off.",
    "isolated": "This WiFi keeps devices apart. Robots can't be reached on it.",
}


def hotspot_devices(robots: list[dict[str, Any]]) -> int:
    """This laptop plus every robot on the WiFi (Pepper counts 2)."""
    return 1 + sum(HOTSPOT_SPOTS.get(r.get("type_id", ""), 1) for r in robots
                   if r.get("type_id") not in NOT_ON_WIFI)


def compute(*, wifi: dict[str, Any], interfaces: list[str], vpn: list[str],
            robots: list[dict[str, Any]], robots_network: Optional[dict[str, Any]],
            lab_wifi: str = "", sweeps: int = 0, alive: int = 0,
            ranges: Optional[list[str]] = None,
            hotspot_limit: int = HOTSPOT_LIMIT) -> dict[str, Any]:
    """`robots`: the robots present now, as {type_id, address}."""
    ssid = wifi.get("ssid") or None
    band = wifi.get("band") or None
    kind = wifi.get("kind")
    if kind is None:
        kind = "lab" if lab_wifi and ssid == lab_wifi else (
            "hotspot" if wifi.get("hotspot") in ("iphone", "android", "phone") else
            ("other" if (ssid or interfaces) else "none"))
    if not interfaces and not ssid:
        kind = "none"
    on_wifi = [r for r in robots if r.get("type_id") not in NOT_ON_WIFI]
    remembered = dict(robots_network or {})
    expected = (remembered.get("ssid") or lab_wifi or None)

    if on_wifi:
        state = "ok"
    elif kind == "none":
        state = "no_network"
    elif vpn:
        state = "vpn_on"
    elif kind == "hotspot" and band in ("5 GHz", "6 GHz"):
        state = "hotspot_5ghz"
    elif (ssid and expected and ssid != expected
          and not (kind == "hotspot" and expected == lab_wifi)):
        state = "wrong_network"
    elif sweeps >= 2 and alive == 0 and kind in ("lab", "other") and ranges:
        state = "isolated"
    elif sweeps < 2:
        state = "searching"
    else:
        state = "ok"

    detail = DETAILS[state].format(ssid="“{}”".format(ssid) if ssid else "another network",
                                   expected="“{}”".format(expected) if expected else "",
                                   band=band or "5 GHz")
    return {
        "state": state,
        "ssid": ssid,
        "band": band,
        "kind": kind,
        "ranges": list(ranges or []),
        "hotspot": {"devices": hotspot_devices(on_wifi), "limit": hotspot_limit},
        "robots_network": {"ssid": remembered.get("ssid") or None,
                           "last_seen": remembered.get("last_seen")},
        "vpn": list(vpn),
        "detail": detail,
        "expected": expected,
    }
