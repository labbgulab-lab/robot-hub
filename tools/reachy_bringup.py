#!/usr/bin/env python3
"""Bring a freshly built Reachy Mini into the lab fleet, start to finish.

Runs on its own (the /reachy-set-up skill starts it detached), because for a
few minutes this laptop leaves its WiFi for the robot's own `reachy-mini-ap`
and anything that needs the internet -- Claude included -- goes quiet.

    python tools/reachy_bringup.py --next-name           # print the next free name
    python tools/reachy_bringup.py --name reachy4 --check  # preflight only, changes nothing
    python tools/reachy_bringup.py --name reachy4 --sn 1000909...  [--fleet-file F]

What it does:
  1. Finds the robot: already on this network (a unit not registered yet), or
     broadcasting `reachy-mini-ap` -- then the laptop joins that.
  2. On reachy-mini-ap (offline): reads the robot's identity, saves the lab
     WiFi as its fallback (priority -10) and this hotspot (priority 0), and
     sends it to the hotspot. The laptop goes back to the hotspot too.
  3. On the hotspot (online): finds it again by its WiFi MAC, updates the
     daemon when it is older than MIN_DAEMON, names it (mDNS), reads its
     Bluetooth PIN, installs reachy_chat onto it.
  4. Records it: config.toml (this laptop's hub), config.example.toml (the
     name only -- that file is public), the private fleet file, and a JSON
     report in logs/bringup/. Then a Windows notification.

Settings: the hotspot is config.toml [network] hotspot (the laptop must be on
it when this starts), its password HOTSPOT_PASSWORD in .env. The lab WiFi is config.toml [network]
lab_wifi, its password LAB_WIFI_PASSWORD in .env; without them that step is
skipped with a warning. Progress: logs/bringup/status.json and the log next to it.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from hub import reachy_wifi  # noqa: E402
from hub.adapters.reachy_wireless import (DEFAULT_SSH_PASSWORD,  # noqa: E402
                                          DEFAULT_SSH_USER, ROBOT_READY_CHECK,
                                          _ssh_run)
from hub.config import load_config  # noqa: E402
from hub.discovery.netscan import local_networks  # noqa: E402

OUT_DIR = REPO_ROOT / "logs" / "bringup"
STATUS = OUT_DIR / "status.json"
LOCK = OUT_DIR / "running.lock"
CONFIG = REPO_ROOT / "config.toml"
EXAMPLE = REPO_ROOT / "config.example.toml"

AP_PREFIX = "reachy-mini"            # the robot's own setup WiFi, e.g. reachy-mini-ap
AP_ADDRESS = "10.42.0.1"
DEFAULT_AP_PASSWORD = "reachy-mini"
DAEMON_PORT = 8000
MIN_DAEMON = (1, 11, 0)              # what reachy1-3 run; older lacks BLE provisioning
HOTSPOT_PRIORITY = 0                 # lab members' hotspots get 10, the lab WiFi -10
UPDATE_WAIT_S = 35 * 60
NAME_RE = re.compile(r"^reachy(\d+)$")

# ------------------------------------------------------------------ status
_state: dict[str, Any] = {"steps": []}
_log_file: Optional[Path] = None


def log(text: str) -> None:
    line = "{} {}".format(dt.datetime.now().strftime("%H:%M:%S"), text)
    print(line, flush=True)
    if _log_file:
        with _log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def status(phase: str, state: str = "running", message: str = "", **extra: Any) -> None:
    _state.update(phase=phase, state=state, message=message,
                  updated=dt.datetime.now().isoformat(timespec="seconds"), **extra)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(_state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, STATUS)
    log("[{}] {}".format(phase, message) if message else "[{}]".format(phase))


def step(name: str, ok: bool, detail: str = "") -> None:
    _state["steps"].append({"step": name, "ok": ok, "detail": detail})
    log("  {} {}{}".format("ok  " if ok else "WARN", name, (": " + detail) if detail else ""))


# ------------------------------------------------------------ fleet names
def registered() -> dict[str, str]:
    """unit_id -> name, from config.toml and the public example."""
    pat = r'\[robots\.reachy_wireless\.units\."([0-9a-f]+)"\]\s*\n\s*display_name\s*=\s*"([^"]*)"'
    out: dict[str, str] = {}
    for path in (EXAMPLE, CONFIG):
        if path.exists():
            out.update(re.findall(pat, path.read_text(encoding="utf-8")))
    return out


def next_name(fleet_file: Optional[Path]) -> str:
    names = set(registered().values())
    if fleet_file and fleet_file.exists():
        names.update(re.findall(r"\breachy\d+\b", fleet_file.read_text(encoding="utf-8")))
    numbers = [int(m.group(1)) for n in names if (m := NAME_RE.match(n))]
    return "reachy{}".format(max(numbers, default=0) + 1)


# ---------------------------------------------------------- laptop WiFi
def _netsh(*args: str, timeout: float = 20) -> str:
    done = subprocess.run(["netsh", "wlan", *args], capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace")
    return done.stdout + done.stderr


def wlan_now() -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in _netsh("show", "interfaces").splitlines():
        if " : " in line:
            k, _, v = line.partition(" : ")
            fields.setdefault(k.strip().lower(), v.strip())
    if fields.get("state", "").lower() != "connected":
        return {}
    return {"ssid": fields.get("ssid", ""), "profile": fields.get("profile", "")}


def wlan_visible() -> dict[str, str]:
    """ssid -> authentication, after asking Windows for a fresh list."""
    out: dict[str, str] = {}
    ssid = None
    for line in _netsh("show", "networks", "mode=bssid").splitlines():
        m = re.match(r"\s*SSID \d+ : (.*)$", line)
        if m:
            ssid = m.group(1).strip()
            continue
        m = re.match(r"\s*Authentication\s*: (.*)$", line)
        if m and ssid is not None:
            out[ssid] = m.group(1).strip()
    return out


def wlan_add_profile(ssid: str, password: Optional[str]) -> None:
    from xml.sax.saxutils import escape
    if password:
        security = ("<authEncryption><authentication>WPA2PSK</authentication>"
                    "<encryption>AES</encryption><useOneX>false</useOneX></authEncryption>"
                    "<sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
                    "<keyMaterial>{}</keyMaterial></sharedKey>".format(escape(password)))
    else:
        security = ("<authEncryption><authentication>open</authentication>"
                    "<encryption>none</encryption><useOneX>false</useOneX></authEncryption>")
    xml = ('<?xml version="1.0"?><WLANProfile xmlns="http://www.microsoft.com/networking/'
           'WLAN/profile/v1"><name>{n}</name><SSIDConfig><SSID><name>{n}</name></SSID>'
           '</SSIDConfig><connectionType>ESS</connectionType><connectionMode>manual'
           '</connectionMode><MSM><security>{s}</security></MSM></WLANProfile>').format(
               n=escape(ssid), s=security)
    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8") as f:
        f.write(xml)
        path = f.name
    try:
        _netsh("add", "profile", "filename={}".format(path), "user=current")
    finally:
        os.unlink(path)


def wlan_join(profile: str, ssid: str, wait_s: float = 40) -> bool:
    _netsh("connect", "name={}".format(profile), "ssid={}".format(ssid))
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        if wlan_now().get("ssid") == ssid:
            return True
        time.sleep(2)
    return False


# ------------------------------------------------------------ the robot
def daemon_status(ip: str, timeout: float = 3.0) -> Optional[dict]:
    import httpx
    try:
        r = httpx.get("http://{}:{}/api/daemon/status".format(ip, DAEMON_PORT), timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def sweep() -> dict[str, dict]:
    """ip -> daemon status for every Reachy daemon on this laptop's networks."""
    hosts: list[str] = []
    for network, own in local_networks():
        if network.num_addresses <= 256 and network.version == 4:
            hosts += [str(h) for h in network.hosts() if str(h) != own]
    found: dict[str, dict] = {}
    with cf.ThreadPoolExecutor(64) as pool:
        open_ = [h for h, up in zip(hosts, pool.map(_port_open, hosts)) if up]
        for ip, st in zip(open_, pool.map(lambda h: daemon_status(h, 3.0), open_)):
            if st:
                found[ip] = st
    return found


def _port_open(ip: str, timeout: float = 0.8) -> bool:
    import socket
    try:
        with socket.create_connection((ip, DAEMON_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def arp_macs() -> dict[str, str]:
    out = subprocess.run(["arp", "-a"], capture_output=True, text=True).stdout
    return {m.group(1): m.group(2).replace("-", ":").upper()
            for m in re.finditer(r"(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F-]{17})", out)}


class Robot:
    def __init__(self, ip: str, user: str, password: str) -> None:
        self.ip, self.user, self.password = ip, user, password

    def run(self, command: str, stdin_text: Optional[str] = None,
            timeout_s: float = 60.0) -> tuple[int, str]:
        return _ssh_run(self.ip, self.user, self.password, command, timeout_s, stdin_text)

    def identity(self) -> dict[str, str]:
        script = r"""
echo "wifi_mac=$(cat /sys/class/net/wlan0/address 2>/dev/null)"
echo "bt_mac=$(timeout 5 bluetoothctl list 2>/dev/null | awk '{print $2; exit}')"
echo "pi_serial=$(awk '/^Serial/{print $3}' /proc/cpuinfo)"
echo "pi_model=$(tr -d '\0' </proc/device-tree/model 2>/dev/null)"
echo "machine_id=$(cat /etc/machine-id 2>/dev/null)"
echo "os=$(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
echo "kernel=$(uname -r)"
echo "disk_free=$(df -h / | awk 'NR==2{print $4}')"
"""
        _rc, out = self.run("bash -c {}".format(_quote(script)), timeout_s=30)
        info = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        if info.get("wifi_mac"):
            info["wifi_mac"] = info["wifi_mac"].upper()
        if info.get("bt_mac"):
            info["bt_mac"] = info["bt_mac"].upper()
        return {k: v.strip() for k, v in info.items()}

    def pin(self) -> str:
        code = ("import glob,sys; p=glob.glob('/venvs/mini_daemon/lib/python3*/site-packages/"
                "reachy_mini/daemon/app/services/bluetooth'); sys.path.insert(0,p[0]); "
                "import bluetooth_service as b; print(b.get_pin())")
        for py in ("python3", "/venvs/mini_daemon/bin/python"):
            rc, out = self.run("{} -c {}".format(py, _quote(code)), timeout_s=30)
            lines = out.strip().splitlines()
            if rc == 0 and lines and re.fullmatch(r"\S{4,8}", lines[-1]):
                return lines[-1]
        return ""


def _quote(text: str) -> str:
    import shlex
    return shlex.quote(text)


def post(ip: str, path: str, body: Optional[dict] = None, timeout: float = 15) -> Any:
    import httpx
    r = httpx.post("http://{}:{}{}".format(ip, DAEMON_PORT, path), json=body, timeout=timeout)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return r.text


def get(ip: str, path: str, timeout: float = 15) -> Any:
    import httpx
    r = httpx.get("http://{}:{}{}".format(ip, DAEMON_PORT, path), timeout=timeout)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------- records
def write_config(unit: str, name: str, sn: str, d: dict) -> None:
    from register_reachy import write_entry
    if unit in registered():
        return
    write_entry(unit, name, sn, {"mac": d.get("wifi_mac", ""), "pi_serial": d.get("pi_serial", "")})


def write_example(unit: str, name: str) -> bool:
    text = EXAMPLE.read_text(encoding="utf-8")
    if '"{}"'.format(unit) in text:
        return False
    anchor = "  [robots.reachy_wireless.settings]"
    if anchor not in text:
        return False
    block = '  [robots.reachy_wireless.units."{}"]\n  display_name = "{}"\n'.format(unit, name)
    EXAMPLE.write_text(text.replace(anchor, block + anchor, 1), encoding="utf-8")
    return True


FLEET_FIELDS = [("unit_id", "Unit id (hardware_id)"), ("pollen_sn", "Pollen SN (base sticker)"),
                ("ble_pin", "Bluetooth PIN"), ("wifi_mac", "WiFi MAC"), ("bt_mac", "Bluetooth MAC"),
                ("pi_serial", "Pi serial"), ("pi_model", "Pi model"), ("machine_id", "machine-id"),
                ("daemon_first", "Daemon as shipped"), ("daemon", "Daemon now"), ("os", "OS"),
                ("kernel", "Kernel"), ("disk_free", "Disk free"), ("hotspot", "Hotspot saved"),
                ("lab_wifi", "Lab WiFi saved"), ("ip", "Address on the hotspot"),
                ("reachy_chat", "reachy_chat installed")]


def write_fleet(fleet_file: Path, name: str, d: dict) -> None:
    if not fleet_file.exists():
        fleet_file.write_text("# Reachy Mini fleet\n\nOne section per robot, written by "
                              "robot-hub/tools/reachy_bringup.py (/reachy-set-up).\n",
                              encoding="utf-8")
    text = fleet_file.read_text(encoding="utf-8")
    if re.search(r"^## {}\b".format(re.escape(name)), text, re.M):
        return
    lines = ["", "## {} -- brought up {}".format(name, dt.date.today().isoformat()), ""]
    lines += ["- **{}:** {}".format(label, d.get(key) or "?") for key, label in FLEET_FIELDS]
    fleet_file.write_text(text.rstrip("\n") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")


def notify(title: str, body: str) -> None:
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
          "ContentType = WindowsRuntime] > $null; "
          "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
          "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
          "$x = $t.GetElementsByTagName('text'); "
          "$x.Item(0).AppendChild($t.CreateTextNode($env:BU_TITLE)) > $null; "
          "$x.Item(1).AppendChild($t.CreateTextNode($env:BU_BODY)) > $null; "
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
          "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe')"
          ".Show([Windows.UI.Notifications.ToastNotification]::new($t))")
    env = {**os.environ, "BU_TITLE": title, "BU_BODY": body}
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], env=env,
                       timeout=20, capture_output=True)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------- run
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--name", help="the robot's permanent name, e.g. reachy4")
    ap.add_argument("--sn", default="", help="Pollen serial from the base sticker")
    ap.add_argument("--fleet-file", type=Path, help="the private fleet list (FLEET.md)")
    ap.add_argument("--host", help="the robot's address, when it is already on this network")
    ap.add_argument("--next-name", action="store_true", help="print the next free name and exit")
    ap.add_argument("--check", action="store_true", help="preflight only; changes nothing")
    ap.add_argument("--skip-update", action="store_true", help="leave the daemon version alone")
    ap.add_argument("--skip-app", action="store_true", help="do not install reachy_chat")
    args = ap.parse_args()

    if args.next_name:
        print(next_name(args.fleet_file))
        return 0
    if not args.name or not NAME_RE.match(args.name):
        sys.exit("--name reachyN is required")

    config = load_config()
    settings = config.robot("reachy_wireless").settings
    user = str(settings.get("ssh_user") or DEFAULT_SSH_USER)
    login = str(settings.get("ssh_password") or config.secret("REACHY_SSH_PASSWORD")
                or DEFAULT_SSH_PASSWORD)
    hot_ssid = config.network.hotspot
    lab_ssid = config.network.lab_wifi
    lab_pass = config.secret("LAB_WIFI_PASSWORD")
    hot_pass = config.secret("HOTSPOT_PASSWORD")
    chat_root = config.path("reachy_wireless", "reachy_chat_path")
    chat_py = None
    if chat_root:
        chat_py = chat_root / (".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python")

    # ---- preflight: everything that can be checked before leaving the WiFi
    problems, notes = [], []
    here = wlan_now() if sys.platform == "win32" else {}
    if sys.platform != "win32":
        problems.append("this script switches WiFi with netsh: Windows only")
    elif not hot_ssid:
        problems.append('set [network] hotspot in config.toml to the hotspot robots are '
                        'set up on (e.g. "Tomer Iphone")')
    elif here.get("ssid") != hot_ssid:
        problems.append('this laptop is on "{}", not "{}" -- connect it to the hotspot '
                        'first'.format(here.get("ssid") or "no WiFi", hot_ssid))
    known = registered()
    if args.name in known.values():
        notes.append("{} is already registered (unit {}): a re-run finishes its setup".format(
            args.name, next(k for k, v in known.items() if v == args.name)))
    if not hot_pass:
        problems.append('HOTSPOT_PASSWORD is not in robot-hub/.env (the password of "{}")'.format(
            hot_ssid or "your hotspot"))
    if not lab_ssid or not lab_pass:
        notes.append("lab WiFi not set ([network] lab_wifi in config.toml + LAB_WIFI_PASSWORD "
                     "in .env): the robot will not learn it now")
    if not args.skip_app and not (chat_py and chat_py.exists()):
        problems.append("reachy_chat's venv python not found at {} -- set reachy_chat_path "
                        "or use --skip-app".format(chat_py))
    if args.fleet_file is None:
        notes.append("no --fleet-file: details go only to the JSON report")
    if LOCK.exists():
        problems.append("another bring-up is running ({}); delete it if that is "
                        "stale".format(LOCK))
    print("Hotspot: {}   (this laptop is on: {})".format(hot_ssid or "(not set)",
                                                        here.get("ssid") or "no WiFi"))
    print("Lab WiFi: {}".format(lab_ssid or "(not set)"))
    for n in notes:
        print("note: " + n)
    for p in problems:
        print("PROBLEM: " + p)
    if problems:
        return 2
    if args.check:
        print("Preflight OK -- {} can be brought up.".format(args.name))
        return 0

    global _log_file
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = OUT_DIR / "{}-{}.log".format(args.name, dt.datetime.now().strftime("%Y%m%d-%H%M"))
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    _state.update(name=args.name, log=str(_log_file), started=dt.datetime.now().isoformat(timespec="seconds"))
    details: dict[str, Any] = {"name": args.name, "pollen_sn": args.sn, "hotspot": here["ssid"]}
    home = here
    try:
        ok = bring_up(args, details, home, user, login, lab_ssid, lab_pass, hot_pass, chat_root, chat_py)
    except Exception as exc:  # noqa: BLE001
        log(traceback.format_exc())
        ok = False
        _state["message"] = str(exc) or type(exc).__name__
    finally:
        if sys.platform == "win32" and wlan_now().get("ssid") != home["ssid"]:
            log("putting this laptop back on “{}”".format(home["ssid"]))
            wlan_join(home["profile"], home["ssid"])
        try:
            LOCK.unlink()
        except OSError:
            pass

    report = OUT_DIR / "{}.json".format(args.name)
    report.write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    warns = [s["step"] for s in _state["steps"] if not s["ok"]]
    if ok:
        msg = "{} is ready on “{}”.".format(args.name, home["ssid"]) + (
            " Check: " + ", ".join(warns) if warns else "")
        status("done", "done", msg, report=str(report))
        notify("Reachy set-up: {} ready".format(args.name), msg)
    else:
        msg = _state.get("message") or "stopped"
        status("failed", "failed", msg, report=str(report))
        notify("Reachy set-up: {} needs you".format(args.name), msg)
    return 0 if ok else 1


def bring_up(args, details, home, user, login, lab_ssid, lab_pass, hot_pass,
             chat_root, chat_py) -> bool:
    known = registered()

    # ---- 1. find it: on this network already, or on its own setup WiFi
    status("find", message="looking for the robot on “{}” and for reachy-mini-ap".format(home["ssid"]))
    robot_ip = args.host
    if not robot_ip:
        fresh = {ip: st for ip, st in sweep().items()
                 if st.get("hardware_id") not in known or known.get(st.get("hardware_id")) == args.name}
        if len(fresh) > 1:
            raise RuntimeError("{} unregistered Reachys on this network ({}) -- power the "
                               "others off or pass --host".format(len(fresh), ", ".join(fresh)))
        robot_ip = next(iter(fresh), None)

    if robot_ip:
        step("found on the hotspot", True, robot_ip)
        robot = Robot(robot_ip, user, login)
        st = daemon_status(robot_ip) or {}
        details["daemon_first"] = st.get("version", "")
        details.update(robot.identity())
        save_wifi(robot, login, home["ssid"], hot_pass, HOTSPOT_PRIORITY, "0", details, "hotspot")
        if lab_ssid and lab_pass:
            save_wifi(robot, login, lab_ssid, lab_pass, reachy_wifi.LAB_PRIORITY, "0", details, "lab_wifi")
    else:
        robot_ip = via_access_point(args, details, home, user, login, lab_ssid, lab_pass, hot_pass)
        robot = Robot(robot_ip, user, login)

    details["ip"] = robot_ip

    # ---- 3. online: update, name, PIN, app
    st = daemon_status(robot_ip) or {}
    if st.get("hardware_id"):
        details["unit_id"] = st["hardware_id"]
    other = known.get(details.get("unit_id", ""))
    if other and other != args.name:
        raise RuntimeError("this robot is already registered as {} -- names are permanent; "
                           "re-run with --name {}".format(other, other))
    details["daemon"] = st.get("version", "")
    if args.skip_update:
        step("daemon update", True, "skipped (--skip-update), on {}".format(details["daemon"]))
    elif version_tuple(details["daemon"]) >= MIN_DAEMON:
        step("daemon update", True, "not needed, on {}".format(details["daemon"]))
    else:
        update_daemon(robot_ip, details)
        st = daemon_status(robot_ip) or {}
        details["unit_id"] = st.get("hardware_id") or details.get("unit_id", "")

    if not details.get("unit_id"):
        raise RuntimeError("the daemon reports no hardware_id, so the robot cannot be "
                           "registered (daemon {})".format(details.get("daemon")))

    status("name", message="naming it {}".format(args.name))
    try:
        post(robot_ip, "/api/daemon/robot-name", {"name": args.name})
        step("mDNS name", True, args.name)
    except Exception as exc:  # noqa: BLE001
        step("mDNS name", False, "could not set it ({}); two unnamed Reachys collide on "
                                 "mDNS".format(exc))

    details["ble_pin"] = robot.pin()
    step("Bluetooth PIN", bool(details["ble_pin"]), details["ble_pin"] or "not readable on this daemon")

    if args.skip_app:
        step("reachy_chat", True, "skipped (--skip-app)")
    else:
        status("app", message="installing reachy_chat onto it (a few minutes)")
        done = subprocess.run([str(chat_py), str(chat_root / "tools" / "deploy_robot_app.py"),
                               "--robot-host", robot_ip], cwd=str(chat_root),
                              capture_output=True, text=True, timeout=900,
                              encoding="utf-8", errors="replace")
        log(done.stdout[-3000:] + done.stderr[-2000:])
        rc, _ = robot.run(ROBOT_READY_CHECK, timeout_s=60)
        details["reachy_chat"] = "yes" if rc == 0 else "no"
        step("reachy_chat", rc == 0, "installed and passes its check" if rc == 0
             else "deploy exit {}, check failed -- see the log".format(done.returncode))

    # ---- 4. records
    status("records", message="recording {}".format(args.name))
    write_config(details["unit_id"], args.name, args.sn, details)
    step("config.toml", True)
    step("config.example.toml", True, "added (commit it)" if write_example(details["unit_id"], args.name)
         else "already there")
    subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "make_announcement_wavs.py")],
                   cwd=str(REPO_ROOT), capture_output=True, timeout=300)
    if args.fleet_file:
        write_fleet(args.fleet_file, args.name, details)
        step("fleet file", True, str(args.fleet_file))
    return True


class NoReply(RuntimeError):
    """The robot said nothing at all: not even an ERR line. A refusal always
    says why, so silence may mean the session died while the robot moved."""


def save_wifi(robot: Robot, login: str, ssid: str, password: str, priority: int,
              move: str, details: dict, key: str) -> dict:
    try:
        rc, out = robot.run(reachy_wifi.command(ssid, lab=False, priority=priority, move=move),
                            "{}\n{}\n".format(login, password), 60.0)
    except Exception as exc:  # noqa: BLE001 -- the SSH session itself broke
        raise NoReply("the robot stopped answering while saving “{}” ({})".format(ssid, exc))
    if not out.strip():
        raise NoReply("the robot gave no reply while saving “{}” (exit {})".format(ssid, rc))
    info = reachy_wifi.parse(out)
    good = rc == 0 and "ACTION" in info
    details[key] = "{} (priority {})".format(ssid, priority) if good else "no"
    step("saved WiFi “{}”".format(ssid), good,
         "priority {}".format(priority) if good else (info.get("ERR") or out.strip()[-200:]))
    if not good:
        raise RuntimeError("the robot would not save “{}”: {}".format(
            ssid, info.get("ERR") or out.strip()[-200:]))
    return info


def via_access_point(args, details, home, user, login, lab_ssid, lab_pass, hot_pass) -> str:
    # ---- 2. offline on reachy-mini-ap
    status("ap", message="waiting for the robot's own WiFi (reachy-mini-ap), up to 4 min")
    ap_ssid, auth = None, ""
    end = time.monotonic() + 240
    while time.monotonic() < end and not ap_ssid:
        for ssid, a in wlan_visible().items():
            if ssid.lower().startswith(AP_PREFIX):
                ap_ssid, auth = ssid, a
        if not ap_ssid:
            time.sleep(8)
    if not ap_ssid:
        raise RuntimeError("no robot found: not on “{}” and no reachy-mini-ap in range. "
                           "Is it powered on? A robot that knows no WiFi opens "
                           "reachy-mini-ap about a minute after boot".format(home["ssid"]))
    step("robot's setup WiFi", True, "{} ({})".format(ap_ssid, auth))

    ap_pass = None if auth.lower().startswith("open") else (
        os.environ.get("REACHY_AP_PASSWORD") or DEFAULT_AP_PASSWORD)
    wlan_add_profile(ap_ssid, ap_pass)
    status("ap", message="this laptop is joining {} -- offline for a few minutes".format(ap_ssid))
    if not wlan_join(ap_ssid, ap_ssid):
        raise RuntimeError("this laptop could not join {} (password not '{}'? set "
                           "REACHY_AP_PASSWORD)".format(ap_ssid, ap_pass))
    end = time.monotonic() + 120
    st = None
    while time.monotonic() < end and not st:
        st = daemon_status(AP_ADDRESS)
        if not st:
            if wlan_now().get("ssid") != ap_ssid:     # Windows wandered back
                wlan_join(ap_ssid, ap_ssid)
            time.sleep(4)
    if not st:
        raise RuntimeError("joined {} but the robot's daemon at {} never answered".format(
            ap_ssid, AP_ADDRESS))
    details["daemon_first"] = st.get("version", "")
    if st.get("hardware_id"):
        details["unit_id"] = st["hardware_id"]
    robot = Robot(AP_ADDRESS, user, login)
    details.update(robot.identity())
    step("identity", bool(details.get("wifi_mac")), "MAC {}, daemon {}".format(
        details.get("wifi_mac", "?"), details["daemon_first"]))

    if lab_ssid and lab_pass:
        save_wifi(robot, login, lab_ssid, lab_pass, reachy_wifi.LAB_PRIORITY, "0", details, "lab_wifi")
    lost_reply = False
    try:
        info = save_wifi(robot, login, home["ssid"], hot_pass, HOTSPOT_PRIORITY, "2", details,
                         "hotspot")
    except NoReply as exc:
        # reachy4, 2026-10-19: no reply at all, yet the robot had saved the
        # hotspot and moved to it. Follow it; if it never shows up there, the
        # check at the end rejoins reachy-mini-ap and reads why.
        log("  {} -- following it to “{}” anyway".format(exc, home["ssid"]))
        info, lost_reply = {"MOVE": "yes"}, True
    if info.get("MOVE") != "yes":
        raise RuntimeError("the robot saved “{}” but did not start moving to it".format(home["ssid"]))

    status("hotspot", message="robot is moving to “{}”; laptop follows".format(home["ssid"]))
    time.sleep(3)
    wlan_join(home["profile"], home["ssid"])

    # ---- find it again by its WiFi MAC (its daemon may not report a hardware_id yet)
    mac = details.get("wifi_mac", "")
    end = time.monotonic() + 240
    while time.monotonic() < end:
        found = sweep()
        macs = arp_macs()
        for ip, st in found.items():
            if (mac and macs.get(ip) == mac) or (details.get("unit_id")
                                                 and st.get("hardware_id") == details["unit_id"]):
                if lost_reply:
                    details["hotspot"] = "{} (priority {})".format(home["ssid"], HOTSPOT_PRIORITY)
                    step("saved WiFi “{}”".format(home["ssid"]), True,
                         "no reply, but it joined it")
                step("back on the hotspot", True, ip)
                return ip
        time.sleep(6)

    # Not there: it may have failed to join and gone back to reachy-mini-ap.
    if wlan_join(ap_ssid, ap_ssid) and daemon_status(AP_ADDRESS):
        _rc, why = Robot(AP_ADDRESS, user, login).run(
            "cat {} /tmp/hub-wifi.log 2>/dev/null".format(reachy_wifi.RESULT_FILE), timeout_s=20)
        raise RuntimeError("the robot could not join “{}” and went back to {} (wrong "
                           "HOTSPOT_PASSWORD? 5 GHz?): {}".format(home["ssid"], ap_ssid,
                                                                  why.strip()[-300:]))
    raise RuntimeError("the robot left reachy-mini-ap but never showed up on “{}”".format(home["ssid"]))


def update_daemon(ip: str, details: dict) -> None:
    status("update", message="updating the daemon from {} (10-30 min over a hotspot)".format(
        details["daemon"]))
    try:
        avail = get(ip, "/update/available")
        log("update/available: {}".format(avail))
        post(ip, "/update/start", timeout=30)
    except Exception as exc:  # noqa: BLE001
        step("daemon update", False, "could not start ({}) -- update it with Pollen's "
                                     "desktop app".format(exc))
        return
    # Poll the version, never /update/info: after the restart the new daemon
    # no longer knows the job, so a watcher on it never sees "done".
    # 1.8.3 -> 1.12.0 over the iPhone hotspot took 19m54s (reachy4, 2026-10-19).
    end = time.monotonic() + UPDATE_WAIT_S
    old = details["daemon"]
    while time.monotonic() < end:
        time.sleep(15)
        st = daemon_status(ip, 5)
        if st and st.get("version") and st["version"] != old:
            details["daemon"] = st["version"]
            step("daemon update", True, "{} -> {}".format(old, st["version"]))
            return
    step("daemon update", False, "still on {} after {} min".format(old, UPDATE_WAIT_S // 60))


if __name__ == "__main__":
    sys.exit(main())
