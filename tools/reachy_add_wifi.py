#!/usr/bin/env python3
"""Hand a Reachy Mini your hotspot from the command line -- the same thing as
"Add WiFi..." on its hub card (hub/reachy_wifi.py), without the hub.

In the lab: connect this laptop to the lab WiFi (no internet needed), power
the robot on, turn your hotspot on, then

    python tools/reachy_add_wifi.py --ssid "Dana Phone"
    python tools/reachy_add_wifi.py --host 10.0.0.23 --ssid "Dana Phone"

The robot moves to your hotspot now and remembers it; it prefers it from then
on and falls back to the lab WiFi when it is off. Once per robot, Tomer saves
the lab WiFi itself as that fallback (it does not move the robot):

    python tools/reachy_add_wifi.py --ssid "<lab WiFi>" --lab

The WiFi password is asked for, or read from REACHY_WIFI_PASSWORD for a
script. The robot's SSH login is Pollen's factory one unless REACHY_SSH_PASSWORD
(.env) or [robots.reachy_wireless.settings] ssh_user / ssh_password say otherwise.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from hub import reachy_wifi  # noqa: E402
from hub.adapters.reachy_wireless import (DEFAULT_SSH_PASSWORD,  # noqa: E402
                                          DEFAULT_SSH_USER, _ssh_run)
from hub.config import load_config  # noqa: E402


def plain(text: str) -> str:
    """Straight quotes: a Windows console mangles the card's curly ones."""
    return text.replace("“", '"').replace("”", '"')


def find_one(names: dict[str, str]) -> tuple[str, str]:
    from register_reachy import browse
    print("Looking for Reachys on this network (5 s)...")
    found = browse(5.0)
    if not found:
        sys.exit("No Reachy answered. Is it powered on and on the same WiFi as "
                 "this laptop? Or give its address with --host.")
    if len(found) > 1:
        print("More than one Reachy is here -- pick one with --host:")
        for r in found:
            print("  {:<10} {}".format(names.get(r["unit_id"], r["unit_id"]), r["ip"]))
        sys.exit(2)
    r = found[0]
    return r["ip"], names.get(r["unit_id"], "The robot")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ssid", required=True, help="the WiFi's exact name")
    ap.add_argument("--host", help="the robot's address (default: find it over mDNS)")
    ap.add_argument("--lab", action="store_true",
                    help="save it as the lab WiFi: the fallback, never preferred; no move")
    args = ap.parse_args()

    config = load_config()
    robot = config.robot("reachy_wireless")
    names = {k: u.display_name for k, u in robot.units.items() if u.display_name}
    if args.host:
        host, name = args.host, "The robot"
    else:
        host, name = find_one(names)
    lab = args.lab or (bool(config.network.lab_wifi) and args.ssid == config.network.lab_wifi)

    user = str(robot.settings.get("ssh_user") or DEFAULT_SSH_USER)
    login = str(robot.settings.get("ssh_password") or config.secret("REACHY_SSH_PASSWORD")
                or DEFAULT_SSH_PASSWORD)
    password = os.environ.get("REACHY_WIFI_PASSWORD") or getpass.getpass(
        'Password for "{}": '.format(args.ssid))

    def run(command, stdin_text, timeout_s):
        return _ssh_run(host, user, login, command, timeout_s, stdin_text)

    print('{} at {}: {} "{}"{}'.format(
        name, host, "saving the lab WiFi" if lab else "joining", args.ssid,
        "" if lab else " (up to a minute; keep that hotspot on)"), flush=True)
    try:
        print(plain(reachy_wifi.teach(run, login, args.ssid, password, lab, name)))
    except Exception as exc:  # noqa: BLE001
        print(plain("Failed: {}".format(exc)), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
