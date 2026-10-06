"""Identical fingerprint capture for every lab robot.

Three subcommands:

    python profile_robot.py baseline
        Records the laptop itself: adapters, listening ports, audio devices.
        Run once. Tells us which ports are already taken before we allocate.

    python profile_robot.py sweep
        Finds every live host on the current /28-ish subnet plus everything
        advertising over mDNS. Fast. Run right after a robot powers on.

    python profile_robot.py profile --ip 172.20.10.5 --name reachy-mini-lite
        Deep fingerprint of one robot. Writes profiles/<name>.json and
        profiles/<name>.md. This is the per-robot record we design against.

Refuses to sweep anything larger than a /24 unless --cidr is passed
explicitly, so pointing it at campus WiFi by accident is not possible.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import ipaddress
import json
import platform
import re
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "profiles"

# Ports worth checking on every robot, with why-we-care notes.
CURATED_PORTS = {
    22: "ssh",
    23: "telnet",
    53: "dns",
    80: "http",
    443: "https",
    554: "rtsp",
    1883: "mqtt",
    3000: "node/dev-ui",
    5000: "flask/uvicorn",
    5001: "flask-alt",
    5555: "adb/misc",
    5900: "vnc",
    6379: "redis",
    7000: "misc-ui",
    8000: "uvicorn/fastapi",
    8001: "uvicorn-alt",
    8080: "http-alt / furhat web",
    8081: "http-alt2",
    8443: "https-alt",
    8554: "rtsp-alt",
    8888: "jupyter/http-alt",
    9000: "http-alt",
    9090: "rosbridge / prometheus",
    9559: "NAOqi",
    11311: "ROS1 master",
    50051: "grpc",
    50055: "grpc-alt",
    54321: "furhat remote api",
    55555: "misc",
}

WEB_PROBE_PATHS = ["/", "/health", "/status", "/info", "/api", "/docs", "/openapi.json"]

# Only prefixes we are actually confident about. Anything else reports raw.
OUI = {
    "B8:27:EB": "Raspberry Pi Foundation",
    "DC:A6:32": "Raspberry Pi Trading",
    "E4:5F:01": "Raspberry Pi Trading",
    "28:CD:C1": "Raspberry Pi Trading",
    "2C:CF:67": "Raspberry Pi Trading",
    "D8:3A:DD": "Raspberry Pi Trading",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run(cmd: list[str], timeout: int = 20) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return f"<failed: {exc}>"


# --------------------------------------------------------------------------
# network selection
# --------------------------------------------------------------------------

def local_ipv4s() -> list[dict]:
    """Every non-loopback IPv4 the laptop holds, with interface + prefix."""
    out = run(
        [
            "powershell", "-NoProfile", "-Command",
            "Get-NetIPAddress -AddressFamily IPv4 | "
            "Where-Object { $_.IPAddress -notlike '127.*' } | "
            "Select-Object IPAddress,InterfaceAlias,PrefixLength | ConvertTo-Json -Compress",
        ]
    )
    try:
        data = json.loads(out)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        data = [data]
    return data


def pick_network(explicit_cidr: str | None) -> ipaddress.IPv4Network:
    if explicit_cidr:
        return ipaddress.ip_network(explicit_cidr, strict=False)

    addrs = local_ipv4s()
    # Prefer the iPhone hotspot range, then any small subnet, never APIPA.
    def score(a: dict) -> tuple:
        ip = a.get("IPAddress", "")
        pfx = int(a.get("PrefixLength", 0))
        hotspot = ip.startswith("172.20.10.")
        apipa = ip.startswith("169.254.")
        return (0 if hotspot else 1, 1 if apipa else 0, -pfx)

    for a in sorted(addrs, key=score):
        ip = a.get("IPAddress", "")
        pfx = int(a.get("PrefixLength", 0))
        if ip.startswith("169.254."):
            continue
        net = ipaddress.ip_network(f"{ip}/{pfx}", strict=False)
        if net.num_addresses > 256:
            print(
                f"! skipping {a['InterfaceAlias']} {net} -- too large to sweep.\n"
                f"  Pass --cidr explicitly if you really mean it.",
                file=sys.stderr,
            )
            continue
        print(f"* sweeping {net} via {a['InterfaceAlias']} (laptop is {ip})")
        return net

    raise SystemExit(
        "No suitable subnet found. Connect to the hotspot, or pass --cidr 172.20.10.0/28."
    )


# --------------------------------------------------------------------------
# liveness + ports
# --------------------------------------------------------------------------

def tcp_open(ip: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


def icmp_alive(ip: str) -> bool:
    out = run(["ping", "-n", "1", "-w", "700", ip], timeout=6)
    return "TTL=" in out.upper()


def scan_ports(ip: str, ports: list[int], workers: int = 400) -> list[int]:
    found = []
    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        jobs = {ex.submit(tcp_open, ip, p): p for p in ports}
        for j in futures.as_completed(jobs):
            if j.result():
                found.append(jobs[j])
    return sorted(found)


def ping_stats(ip: str, count: int = 10) -> dict:
    out = run(["ping", "-n", str(count), ip], timeout=count * 2 + 10)
    times = [int(m) for m in re.findall(r"time[=<](\d+)ms", out)]
    loss = re.search(r"\((\d+)% loss\)", out)
    return {
        "replies": len(times),
        "sent": count,
        "loss_pct": int(loss.group(1)) if loss else None,
        "min_ms": min(times) if times else None,
        "avg_ms": round(sum(times) / len(times), 1) if times else None,
        "max_ms": max(times) if times else None,
        "raw_times_ms": times,
    }


def arp_table() -> dict[str, str]:
    table = {}
    for line in run(["arp", "-a"], timeout=15).splitlines():
        m = re.match(r"\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})\s", line)
        if m:
            table[m.group(1)] = m.group(2).upper().replace("-", ":")
    return table


def vendor_of(mac: str | None) -> str | None:
    if not mac:
        return None
    return OUI.get(mac[:8], "unknown (raw MAC recorded)")


def reverse_names(ip: str) -> dict:
    names = {}
    try:
        names["reverse_dns"] = socket.gethostbyaddr(ip)[0]
    except Exception:  # noqa: BLE001
        names["reverse_dns"] = None
    return names


def resolve_mdns_name(name: str) -> str | None:
    if not name.endswith(".local"):
        name = name + ".local"
    try:
        return socket.gethostbyname(name)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# banners + http
# --------------------------------------------------------------------------

def grab_banner(ip: str, port: int, timeout: float = 2.0) -> str | None:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as s:
            s.settimeout(timeout)
            data = s.recv(256)
            return data.decode("utf-8", "replace").strip() or None
    except Exception:  # noqa: BLE001
        return None


def http_probe(ip: str, port: int) -> dict | None:
    import requests

    try:
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:  # noqa: BLE001
        pass

    for scheme in ("http", "https"):
        base = f"{scheme}://{ip}:{port}"
        try:
            r = requests.get(base + "/", timeout=3, verify=False, allow_redirects=True)
        except Exception:  # noqa: BLE001
            continue

        title = None
        m = re.search(r"<title[^>]*>(.*?)</title>", r.text or "", re.I | re.S)
        if m:
            title = " ".join(m.group(1).split())[:120]

        paths = {}
        for path in WEB_PROBE_PATHS[1:]:
            try:
                pr = requests.get(base + path, timeout=2, verify=False)
                if pr.status_code < 500:
                    paths[path] = {
                        "status": pr.status_code,
                        "content_type": pr.headers.get("Content-Type"),
                        "snippet": (pr.text or "")[:300],
                    }
            except Exception:  # noqa: BLE001
                pass

        return {
            "scheme": scheme,
            "url": base,
            "status": r.status_code,
            "final_url": r.url,
            "server": r.headers.get("Server"),
            "content_type": r.headers.get("Content-Type"),
            "title": title,
            "headers": dict(r.headers),
            "body_snippet": (r.text or "")[:600],
            "extra_paths": paths,
        }
    return None


# --------------------------------------------------------------------------
# mDNS
# --------------------------------------------------------------------------

def mdns_browse(seconds: float = 6.0) -> list[dict]:
    try:
        from zeroconf import Zeroconf, ServiceBrowser, ZeroconfServiceTypes
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"zeroconf unavailable: {exc}"}]

    results: list[dict] = []
    zc = Zeroconf()
    try:
        types = list(ZeroconfServiceTypes.find(zc=zc, timeout=seconds / 2))

        class Listener:
            def add_service(self, zc_, type_, name):
                info = zc_.get_service_info(type_, name, timeout=2500)
                if not info:
                    results.append({"type": type_, "name": name, "info": None})
                    return
                results.append(
                    {
                        "type": type_,
                        "name": name,
                        "server": info.server,
                        "port": info.port,
                        "addresses": [
                            socket.inet_ntoa(a) for a in info.addresses if len(a) == 4
                        ],
                        "properties": {
                            k.decode("utf-8", "replace") if isinstance(k, bytes) else str(k):
                            (v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v))
                            for k, v in (info.properties or {}).items()
                        },
                    }
                )

            def update_service(self, *a):
                pass

            def remove_service(self, *a):
                pass

        browsers = [ServiceBrowser(zc, t, Listener()) for t in types]
        time.sleep(seconds / 2)
        for b in browsers:
            b.cancel()
    finally:
        zc.close()
    return results


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_baseline(args) -> None:
    print("== laptop baseline ==")
    data = {
        "captured_at": now(),
        "host": platform.node(),
        "os": platform.platform(),
        "adapters": local_ipv4s(),
        "listening_ports": run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-NetTCPConnection -State Listen | "
                "Select-Object LocalAddress,LocalPort,OwningProcess | "
                "Sort-Object LocalPort | ConvertTo-Json -Compress",
            ],
            timeout=40,
        ),
        "audio_devices": run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-PnpDevice -Class AudioEndpoint -Status OK | "
                "Select-Object FriendlyName,InstanceId | ConvertTo-Json -Compress",
            ],
            timeout=40,
        ),
    }
    PROFILES.mkdir(parents=True, exist_ok=True)
    out = PROFILES / "_laptop_baseline.json"
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"wrote {out}")


def cmd_sweep(args) -> None:
    net = pick_network(args.cidr)
    hosts = [str(h) for h in net.hosts()]
    print(f"* probing {len(hosts)} addresses...")

    # Liveness by ICMP or any curated port answering.
    probe_ports = [22, 80, 443, 8000, 8080, 9559, 54321]

    def alive(ip: str) -> bool:
        if icmp_alive(ip):
            return True
        return any(tcp_open(ip, p, timeout=0.4) for p in probe_ports)

    live = []
    with futures.ThreadPoolExecutor(max_workers=64) as ex:
        jobs = {ex.submit(alive, ip): ip for ip in hosts}
        for j in futures.as_completed(jobs):
            if j.result():
                live.append(jobs[j])
    live.sort(key=lambda x: tuple(int(p) for p in x.split(".")))

    arp = arp_table()
    print("\n== live hosts ==")
    for ip in live:
        mac = arp.get(ip)
        names = reverse_names(ip)
        quick = scan_ports(ip, list(CURATED_PORTS), workers=200)
        print(
            f"  {ip:<16} mac={mac or '?':<18} name={names['reverse_dns'] or '?':<28} "
            f"ports={quick or '-'}  vendor={vendor_of(mac)}"
        )

    print("\n== mDNS advertisements ==")
    for svc in mdns_browse(seconds=args.mdns_seconds):
        if "error" in svc:
            print(f"  {svc['error']}")
            continue
        print(
            f"  {svc.get('name')}  -> {svc.get('server')}:{svc.get('port')} "
            f"{svc.get('addresses')}"
        )
        if svc.get("properties"):
            print(f"      props: {svc['properties']}")

    print("\nNow deep-profile the one you just powered on, e.g.:")
    print("  python profile_robot.py profile --ip <ip> --name reachy-mini-lite")


def cmd_profile(args) -> None:
    ip = args.ip
    name = args.name
    print(f"== profiling {name} at {ip} ==")

    ports = list(CURATED_PORTS)
    if args.wide:
        print("* wide port sweep 1-10000 (this takes ~40s)")
        ports = sorted(set(ports) | set(range(1, 10001)))

    print("* scanning ports...")
    open_ports = scan_ports(ip, ports)
    print(f"  open: {open_ports}")

    print("* latency...")
    latency = ping_stats(ip, count=args.pings)
    print(f"  {latency['avg_ms']} ms avg, {latency['loss_pct']}% loss")

    mac = arp_table().get(ip)

    print("* banners + http fingerprints...")
    services = {}
    for p in open_ports:
        entry = {"purpose_guess": CURATED_PORTS.get(p), "banner": grab_banner(ip, p)}
        web = http_probe(ip, p)
        if web:
            entry["http"] = web
        services[str(p)] = entry

    print("* mDNS...")
    mdns_all = mdns_browse(seconds=args.mdns_seconds)
    mdns_mine = [s for s in mdns_all if ip in (s.get("addresses") or [])]

    profile = {
        "name": name,
        "captured_at": now(),
        "ip": ip,
        "mac": mac,
        "vendor_guess": vendor_of(mac),
        "names": reverse_names(ip),
        "mdns_hostname_resolves_to": resolve_mdns_name(args.mdns_name) if args.mdns_name else None,
        "latency": latency,
        "open_ports": open_ports,
        "wide_scan": bool(args.wide),
        "services": services,
        "mdns_records_for_this_ip": mdns_mine,
        "mdns_records_all": mdns_all,
        "laptop_adapters_at_capture": local_ipv4s(),
        "notes_to_fill_in_by_hand": {
            "has_onboard_mic": None,
            "has_onboard_speaker": None,
            "needs_laptop_audio_device": None,
            "existing_launcher_command": None,
            "existing_ui_url": None,
            "boot_time_seconds": None,
            "static_or_dhcp": None,
            "behaviour_on_wifi_drop": None,
        },
    }

    PROFILES.mkdir(parents=True, exist_ok=True)
    jpath = PROFILES / f"{name}.json"
    jpath.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    lines = [
        f"# {name}",
        "",
        f"- captured: {profile['captured_at']}",
        f"- ip: `{ip}`  mac: `{mac}`  vendor: {profile['vendor_guess']}",
        f"- reverse dns: {profile['names']['reverse_dns']}",
        f"- latency: avg {latency['avg_ms']} ms, loss {latency['loss_pct']}%",
        f"- open ports: {open_ports}",
        "",
        "## services",
    ]
    for p, s in services.items():
        lines.append(f"### port {p} ({s.get('purpose_guess') or 'unknown'})")
        if s.get("banner"):
            lines.append(f"- banner: `{s['banner']}`")
        if s.get("http"):
            h = s["http"]
            lines.append(f"- {h['scheme']} {h['status']} title={h.get('title')!r} server={h.get('server')}")
            lines.append(f"- url: {h['url']}")
            if h.get("extra_paths"):
                lines.append(f"- responds on: {list(h['extra_paths'])}")
        lines.append("")
    lines += ["## mDNS for this host", "```", json.dumps(mdns_mine, indent=2), "```"]

    mpath = PROFILES / f"{name}.md"
    mpath.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nwrote {jpath}")
    print(f"wrote {mpath}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="record the laptop's own ports/adapters/audio")
    b.set_defaults(func=cmd_baseline)

    s = sub.add_parser("sweep", help="find live hosts + mDNS on the current subnet")
    s.add_argument("--cidr", help="explicit subnet, e.g. 172.20.10.0/28")
    s.add_argument("--mdns-seconds", type=float, default=8.0)
    s.set_defaults(func=cmd_sweep)

    p = sub.add_parser("profile", help="deep fingerprint of one robot")
    p.add_argument("--ip", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--mdns-name", help="hostname to test, e.g. reachy.local")
    p.add_argument("--wide", action="store_true", help="scan ports 1-10000")
    p.add_argument("--pings", type=int, default=10)
    p.add_argument("--mdns-seconds", type=float, default=8.0)
    p.set_defaults(func=cmd_profile)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
