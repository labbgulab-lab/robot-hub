# -*- coding: utf-8 -*-
"""Pepper say-it dashboard: type text in a browser, Pepper speaks it.

    cd ~/Desktop/job/pepper/dashboard
    sh start.sh                 # finds Pepper by itself
    sh start.sh 172.20.10.2     # or pin an IP

Then open http://localhost:8780

A stop-gap for simple use until the real app (hub card) exists. Python 2.7 +
pynaoqi, standard library only, so it runs through naoqi/run_naoqi.sh with
nothing to install. It listens on 127.0.0.1 only.

Finding Pepper, in order:
  1. an IP given on the command line or chosen in the page ("Connect"),
  2. every address Pepper was ever found at (known_addresses.json, newest
     first) -- each success is recorded there with the WiFi name,
  3. `Pepper.local` over mDNS,
  4. a sweep of the laptop's own networks for port 9559 (at most a /24 per
     network, so campus WiFi is never swept wholesale), plus the iPhone
     hotspot range. Only a robot whose body type is Juliette counts, so NAO
     on the same network is ignored.
"""
from __future__ import print_function

import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from Queue import Queue
from SocketServer import ThreadingMixIn

from naoqi import ALProxy

PORT = 8780
NAOQI = 9559
HOTSPOT = ["172.20.10.%d" % i for i in range(1, 15)]
HERE = os.path.dirname(os.path.abspath(__file__))
KNOWN_FILE = os.path.join(HERE, "known_addresses.json")
AUTO_SCAN_EVERY = 30  # seconds between automatic sweeps while Pepper is missing


def log(msg):
    print(time.strftime("%H:%M:%S"), msg)
    sys.stdout.flush()


def last_line(e):
    return (str(e).strip().splitlines() or ["?"])[-1][:160]


# ---- network helpers ---------------------------------------------------
def port_open(ip, port=NAOQI, timeout=0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        return s.connect_ex((ip, port)) == 0
    except Exception:
        return False
    finally:
        s.close()


def robot_name(ip):
    try:
        return ALProxy("ALSystem", ip, NAOQI).robotName()
    except Exception:
        return None


def is_pepper(ip):
    try:
        return ALProxy("ALMemory", ip, NAOQI).getData("RobotConfig/Body/Type") == "Juliette"
    except Exception:
        return False


def current_ssid():
    try:
        out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"])
        m = re.search(r"^\s+SSID\s+:\s(.+)$", out, re.M)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def _ip2int(ip):
    return struct.unpack("!I", socket.inet_aton(ip))[0]


def _int2ip(n):
    return socket.inet_ntoa(struct.pack("!I", n))


def laptop_networks():
    """[(laptop_ip, [hosts to sweep])] from ipconfig. Skips link-local,
    Tailscale/VPN /32s and loopback; caps each network at its /24."""
    try:
        out = subprocess.check_output(["ipconfig"])
    except Exception:
        return []
    pairs = re.findall(r"IPv4 Address[ .]*:\s*([\d.]+).*?Subnet Mask[ .]*:\s*([\d.]+)", out, re.S)
    nets = []
    for ip, mask in pairs:
        if ip.startswith(("169.254.", "127.")) or mask == "255.255.255.255":
            continue
        m = _ip2int(mask)
        if bin(m).count("1") < 24:
            m = _ip2int("255.255.255.0")
        base, size = _ip2int(ip) & m, (~m & 0xFFFFFFFF) + 1
        hosts = [_int2ip(base + i) for i in range(1, size - 1) if _int2ip(base + i) != ip]
        nets.append((ip, hosts))
    return nets


def sweep(hosts, workers=64):
    """Hosts with 9559 open that are a Pepper."""
    q, found, lock = Queue(), [], threading.Lock()
    for h in hosts:
        q.put(h)

    def work():
        while True:
            try:
                h = q.get_nowait()
            except Exception:
                return
            if port_open(h, timeout=0.5) and is_pepper(h):
                with lock:
                    found.append(h)

    ts = [threading.Thread(target=work) for _ in range(min(workers, len(hosts) or 1))]
    for t in ts:
        t.daemon = True
        t.start()
    for t in ts:
        t.join()
    return sorted(found)


# ---- known addresses ---------------------------------------------------
class Known(object):
    def __init__(self, path):
        self.path, self.lock = path, threading.Lock()
        try:
            with open(path) as f:
                self.items = json.load(f)
        except Exception:
            self.items = []

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.items, f, indent=2)
        if os.path.exists(self.path):
            os.remove(self.path)
        os.rename(tmp, self.path)

    def ordered(self):
        with self.lock:
            return sorted(self.items, key=lambda x: x.get("last_seen") or "", reverse=True)

    def add(self, ip, seen=False, note=None, robot=None):
        with self.lock:
            item = next((x for x in self.items if x["ip"] == ip), None)
            if item is None:
                item = {"ip": ip, "robot": None, "network": None, "last_seen": None, "note": note or ""}
                self.items.append(item)
            if seen:
                item["last_seen"] = time.strftime("%Y-%m-%d %H:%M")
                item["network"] = current_ssid() or item.get("network")
            if robot:
                item["robot"] = robot
            self._save()

    def forget(self, ip):
        with self.lock:
            self.items = [x for x in self.items if x["ip"] != ip]
            self._save()


KNOWN = Known(KNOWN_FILE)


# ---- the robot ---------------------------------------------------------
class Robot(object):
    """Holds the proxies; finds and reconnects to Pepper in the background."""

    def __init__(self, pinned=None):
        self.lock = threading.Lock()
        self.ip = None
        self.want = pinned          # an IP the user asked for explicitly
        self.p = {}
        self.last_scan = 0
        self.last_wifi_scan = 0
        self.scan = {"running": False, "found": [], "when": None, "swept": 0}
        self.status = {"connected": False, "ip": None, "battery": None,
                       "charging": None, "volume": None, "network": None,
                       "note": "searching..."}
        t = threading.Thread(target=self._watch)
        t.daemon = True
        t.start()

    # discovery -----------------------------------------------------------
    def run_scan(self):
        if self.scan["running"]:
            return
        self.scan["running"] = True
        try:
            hosts = []
            for _, hs in laptop_networks():
                hosts += hs
            hosts += [h for h in HOTSPOT if h not in hosts]
            found = sweep(hosts)
            for ip in found:
                KNOWN.add(ip, seen=True, robot=robot_name(ip))
            self.scan.update({"found": found, "when": time.strftime("%H:%M:%S"), "swept": len(hosts)})
            log("scan: %d hosts swept, Pepper at %s" % (len(hosts), found or "none"))
            return found
        finally:
            self.last_scan = time.time()
            self.scan["running"] = False

    def _find(self):
        if self.want:
            return self.want if port_open(self.want) and is_pepper(self.want) else None
        for item in KNOWN.ordered():
            if port_open(item["ip"]) and is_pepper(item["ip"]):
                return item["ip"]
        try:
            ip = socket.getaddrinfo("Pepper.local", NAOQI, socket.AF_INET)[0][4][0]
            if port_open(ip) and is_pepper(ip):
                return ip
        except Exception:
            pass
        if time.time() - self.last_scan > AUTO_SCAN_EVERY:
            self.status["note"] = "scanning this network for Pepper..."
            found = self.run_scan()
            if found:
                return found[0]
        return None

    def _connect(self, ip):
        p = {}
        for name in ["ALTextToSpeech", "ALAnimatedSpeech", "ALAnimationPlayer",
                     "ALMotion", "ALBasicAwareness", "ALBattery", "ALMemory",
                     "ALAudioDevice", "ALSystem", "ALConnectionManager"]:
            p[name] = ALProxy(name, ip, NAOQI)
        name = p["ALSystem"].robotName()
        with self.lock:
            self.ip, self.p = ip, p
        KNOWN.add(ip, seen=True, robot=name)
        log("connected to %s at %s" % (name, ip))

    def _drop(self):
        with self.lock:
            self.ip, self.p = None, {}
        self.status.update({"connected": False, "ip": None})

    def connect_to(self, ip):
        """User picked an address: drop the current link and try that one."""
        socket.inet_aton(ip)  # raises on garbage
        self.want = ip
        self._drop()
        self.status["note"] = "connecting to %s..." % ip
        log("user asked for %s" % ip)

    def auto(self):
        self.want = None
        self._drop()
        self.status["note"] = "searching..."

    def _watch(self):
        while True:
            try:
                if not self.ip:
                    ip = self._find()
                    if ip:
                        self._connect(ip)
                    else:
                        self.status["note"] = ("%s does not answer as Pepper" % self.want if self.want
                                               else "Pepper not found on this network, retrying...")
                if self.ip:
                    cur = self.p["ALMemory"].getData("Device/SubDeviceList/Battery/Current/Sensor/Value")
                    self.status.update({
                        "connected": True, "ip": self.ip,
                        "battery": self.p["ALBattery"].getBatteryCharge(),
                        "charging": cur > 0.5,
                        "volume": self.p["ALAudioDevice"].getOutputVolume(),
                        "note": ""})
            except Exception as e:
                if self.ip:
                    log("lost Pepper (%s)" % last_line(e))
                self._drop()
            self.status["network"] = current_ssid()
            time.sleep(5)

    def proxy(self, name):
        with self.lock:
            if not self.ip:
                raise RuntimeError("Pepper is not connected")
            return self.p[name]

    def wifi_networks(self):
        """Pepper's WiFi list as connman sees it: saved ones (Favorite) and
        any currently in range. Saved networks that are out of range are not
        listed by connman, so they cannot be shown."""
        con = self.proxy("ALConnectionManager")
        if time.time() - self.last_wifi_scan > 60:
            self.last_wifi_scan = time.time()
            try:
                con.scan()
                time.sleep(3)
            except Exception:
                pass
        out = []
        for svc in con.services():
            d = dict((k, v) for k, v in svc)
            if d.get("Type") != "wifi":
                continue
            ipv4 = dict((k, v) for k, v in (d.get("IPv4") or []))
            out.append({"name": d.get("Name") or "(hidden network)",
                        "saved": bool(d.get("Favorite")),
                        "autoconnect": bool(d.get("AutoConnect", d.get("Autoconnect"))),
                        "state": d.get("State"),
                        "strength": d.get("Strength"),
                        "security": d.get("Security"),
                        "ip": ipv4.get("Address")})
        out.sort(key=lambda n: (not n["saved"], n["state"] not in ("online", "ready"), -(n["strength"] or 0)))
        return out

    # actions ---------------------------------------------------------------
    def say(self, text, gestures):
        text = text.strip()[:500]
        if not text:
            return
        data = text.encode("utf-8")
        if gestures:
            self.proxy("ALAnimatedSpeech").post.say(data, {"bodyLanguageMode": "contextual"})
        else:
            self.proxy("ALTextToSpeech").post.say(data)
        log("say%s: %s" % (" +gestures" if gestures else "", data))

    def stop(self):
        self.proxy("ALTextToSpeech").stopAll()
        log("stop speaking")

    def volume(self, v):
        v = max(0, min(100, int(v)))
        self.proxy("ALAudioDevice").setOutputVolume(v)
        self.status["volume"] = v
        log("volume %d" % v)

    def wave(self):
        self.proxy("ALAnimationPlayer").post.run("animations/Stand/Gestures/Hey_1")
        log("wave")

    def head(self, kind):
        mot, aw = self.proxy("ALMotion"), self.proxy("ALBasicAwareness")

        def run():
            was = aw.isEnabled()
            try:
                aw.setEnabled(False)
                time.sleep(0.3)
                mot.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], [0.6, 0.6], True)
                if kind == "yes":
                    seq = [-0.40, 0.50] * 2 + [0.0]
                    mot.angleInterpolation("HeadPitch", seq, [0.45 * (i + 1) for i in range(len(seq))], True)
                else:
                    seq = [0.9, -0.9] * 2 + [0.0]
                    mot.angleInterpolation("HeadYaw", seq, [0.5 + 0.6 * i for i in range(len(seq))], True)
            finally:
                aw.setEnabled(was)
        t = threading.Thread(target=run)
        t.daemon = True
        t.start()
        log("head " + kind)


ROBOT = Robot(sys.argv[1] if len(sys.argv) > 1 else None)


# ---- HTTP ----------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body)
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if self.path == "/api/wifi":
            try:
                return self._send(200, {"ok": True, "networks": ROBOT.wifi_networks()})
            except Exception as e:
                return self._send(503, {"ok": False, "error": last_line(e)})
        if self.path == "/api/status":
            s = dict(ROBOT.status)
            s.update({"known": KNOWN.ordered(), "scan": ROBOT.scan, "pinned": ROBOT.want})
            return self._send(200, s)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.getheader("content-length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or "{}")
        except ValueError:
            return self._send(400, {"error": "bad json"})
        try:
            path = self.path
            if path == "/api/say":
                ROBOT.say(data.get("text", u""), bool(data.get("gestures")))
            elif path == "/api/stop":
                ROBOT.stop()
            elif path == "/api/volume":
                ROBOT.volume(data.get("volume", 50))
            elif path == "/api/wave":
                ROBOT.wave()
            elif path == "/api/head":
                ROBOT.head("yes" if data.get("kind") == "yes" else "no")
            elif path == "/api/scan":
                t = threading.Thread(target=ROBOT.run_scan)
                t.daemon = True
                t.start()
            elif path == "/api/known/add":
                ip = str(data.get("ip", "")).strip()
                socket.inet_aton(ip)
                KNOWN.add(ip, note="added by hand")
            elif path == "/api/known/forget":
                KNOWN.forget(str(data.get("ip", "")))
            elif path == "/api/connect":
                ROBOT.connect_to(str(data.get("ip", "")).strip())
            elif path == "/api/auto":
                ROBOT.auto()
            else:
                return self._send(404, {"error": "not found"})
            self._send(200, {"ok": True})
        except socket.error:
            self._send(400, {"ok": False, "error": "not a valid IPv4 address"})
        except Exception as e:
            self._send(503, {"ok": False, "error": last_line(e)})


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    log("dashboard on http://localhost:%d  (Ctrl+C to stop)" % PORT)
    Server(("127.0.0.1", PORT), Handler).serve_forever()
