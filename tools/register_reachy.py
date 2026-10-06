#!/usr/bin/env python3
"""Find wireless Reachys on this network and record each one in config.toml.

Used once per robot at bring-up, after it has joined the laptop's WiFi. A
robot is keyed on the mDNS TXT `unit_id` (== daemon `hardware_id`), never on
its IP. The name is assigned here once and then permanent
(reachy_chat/docs/HUB-INTERFACE.md 3), so an existing entry is never
overwritten.

    python tools/register_reachy.py                          # list what is on the network
    python tools/register_reachy.py --name reachy2 --sn 1000...   # register the one unregistered robot
    python tools/register_reachy.py --unit 6563a10e4204345e --name reachy2 --sn ...

API keys are deliberately not written here: key assignment is a hub UI feature.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import paramiko
from zeroconf import ServiceBrowser, Zeroconf

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / "config.toml"
EXAMPLE = REPO_ROOT / "config.example.toml"
SERVICE = "_reachy-mini._tcp.local."
ANCHOR = "[robots.reachy_lite]"
SSH_USER, SSH_PASSWORD = "pollen", "root"


def browse(seconds: float) -> list[dict]:
    zc = Zeroconf()
    found: dict[str, dict] = {}

    class Listener:
        def add_service(self, z, t, n):
            info = z.get_service_info(t, n, 3000)
            if not info:
                return
            txt = {k.decode(): (v.decode() if v else "") for k, v in info.properties.items()}
            ipv4 = [a for a in info.parsed_addresses() if ":" not in a]
            if txt.get("unit_id"):
                found[txt["unit_id"]] = {**txt, "ip": ipv4[0] if ipv4 else txt.get("address", "")}

        update_service = add_service

        def remove_service(self, *a):
            pass

    ServiceBrowser(zc, SERVICE, Listener())
    time.sleep(seconds)
    zc.close()
    return list(found.values())


def ssh_identity(ip: str) -> dict:
    """Pi serial and WiFi MAC; empty on failure (the robot is still registrable)."""
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(ip, username=SSH_USER, password=SSH_PASSWORD, timeout=8,
                  look_for_keys=False, allow_agent=False)
        _, out, _ = c.exec_command(
            "grep Serial /proc/cpuinfo | awk '{print $3}'; cat /sys/class/net/wlan0/address")
        lines = out.read().decode().split()
        c.close()
        return {"pi_serial": lines[0] if lines else "", "mac": lines[1].upper() if len(lines) > 1 else ""}
    except Exception as exc:  # noqa: BLE001
        print(f"  (ssh to {ip} failed: {exc})")
        return {}


def registered() -> dict[str, str]:
    """unit_id -> display_name already in config.toml."""
    if not CONFIG.exists():
        return {}
    text = CONFIG.read_text(encoding="utf-8")
    pat = r'\[robots\.reachy_wireless\.units\."([0-9a-f]+)"\]\s*\n\s*display_name\s*=\s*"([^"]*)"'
    return dict(re.findall(pat, text))


def write_entry(unit: str, name: str, sn: str, ident: dict) -> None:
    if not CONFIG.exists():
        CONFIG.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    text = CONFIG.read_text(encoding="utf-8")
    if ANCHOR not in text:
        sys.exit(f"{CONFIG} has no {ANCHOR} section to insert before; add the entry by hand")
    notes = [f"Pollen SN {sn or '?'} (base sticker). Registered {dt.date.today()};",
             f"wifi mac {ident.get('mac') or '?'}, Pi serial {ident.get('pi_serial') or '?'}"]
    block = (f'  [robots.reachy_wireless.units."{unit}"]\n'
             f'  display_name = "{name}"\n'
             + "".join(f"  # {n}\n" for n in notes) + "\n")
    CONFIG.write_text(text.replace(ANCHOR, block + ANCHOR, 1), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--name", help="permanent name to assign, e.g. reachy2")
    ap.add_argument("--sn", default="", help="Pollen serial number from the base sticker")
    ap.add_argument("--unit", help="unit_id to register (needed if several are unregistered)")
    ap.add_argument("--seconds", type=float, default=5.0, help="mDNS listen time")
    args = ap.parse_args()

    known = registered()
    robots = browse(args.seconds)
    names = set(known.values())
    print(f"{len(robots)} wireless Reachy(s) on the network:")
    for r in robots:
        tag = known.get(r["unit_id"], "UNREGISTERED")
        print(f"  {r['unit_id']}  {r['ip']:<15}  v{r.get('version', '?'):<8}  {tag}")
    if known:
        print(f"{len(known)} registered in config.toml: {', '.join(sorted(names))}")

    if not args.name:
        return
    if args.name in names:
        sys.exit(f"the name {args.name!r} already belongs to another robot")
    pending = [r for r in robots if r["unit_id"] not in known]
    if args.unit:
        if args.unit in known:
            sys.exit(f"{args.unit} is already {known[args.unit]!r}; names are permanent")
        pending = [r for r in pending if r["unit_id"] == args.unit]
    if len(pending) != 1:
        sys.exit(f"{len(pending)} unregistered robots match; pass --unit to pick one"
                 if pending else "no unregistered robot found -- is it on and on this WiFi?")
    r = pending[0]
    ident = ssh_identity(r["ip"])
    write_entry(r["unit_id"], args.name, args.sn, ident)
    print(f"registered {r['unit_id']} as {args.name!r} (mac {ident.get('mac') or '?'}, "
          f"Pi serial {ident.get('pi_serial') or '?'}, SN {args.sn or '?'})")
    # The Reachy daemon has no TTS, so "I am <name>" must exist as a WAV.
    import subprocess
    subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "make_announcement_wavs.py")],
                   cwd=REPO_ROOT, check=False)


if __name__ == "__main__":
    main()
