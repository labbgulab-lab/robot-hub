# -*- coding: utf-8 -*-
"""Runs ON Pepper (Python 2.7.6, NAOqi 2.5): the robot half of the Pepper app.

Uploaded and started over SSH by the laptop (pepper_app/robot.py) at every
Launch, with the tablet page's files next to it (screen/). One TCP connection
to the laptop carries everything. Since 2026-11-05 the laptop opens it: a
student laptop may not listen on the network (no admin, no firewall rule), so

  * listen mode (normal): this agent LISTENS on robot port 8790 and the laptop
    connects out to it. The laptop speaks first: J {"ev": "hello", "token"};
    a wrong token is closed at once. One laptop at a time: a new connection
    with the right token replaces the old one (the same laptop reconnecting).
    The agent answers with its own J {"ev": "hello", "info", ...}.
  * connect-back mode (fallback, when the laptop could not reach port 8790):
    the agent connects to the laptop and sends J {"ev": "hello", "token", ...}
    first, as before 2026-11-05. Windows may then ask about the firewall.

Frames, both modes:

    laptop -> robot   J  {"id": n, "cmd": ...}      commands (no "id": no reply)
                      S  PCM16 24 kHz mono         speech to play
                      D  4-byte header length + JSON header + bytes
                                                   a slide file the tablet asked for
    robot -> laptop   J  {"ev": ...} / {"id": n, "ok": ...}
                      M  PCM16 16 kHz mono         front microphone
                      I  PNG                       camera frame (after a J "frame")

Frame = 1 byte type + 4 byte big-endian length + payload. The laptop pings
every few seconds; LINK_IDLE_S without a frame either way ends the link.

The tablet page is served HERE, on robot port 8791 (the tablet loads
http://198.18.0.1:8791/screen), in both modes:

    /screen, /screen/render.js, /screen/logo.png   the files uploaded at deploy
    /screen/state     the latest state the laptop pushed (cmd "screen_state");
                      each tablet poll is its heartbeat: J {"ev": "tablet"}
    /screen/tap       J {"ev": "tap", "v", "i"} to the laptop
    /screen/media/<deck>/<file>
                      J {"ev": "media", "rid", "deck", "file"} -> the laptop
                      answers with a D frame; cached in MEDIA_DIR
While no laptop is linked, /screen/state answers 503, so the tablet shows its
small red "lost" dot as before.

Standard library + naoqi only: the robot's root filesystem is read-only and
nothing can be installed (profiles/pepper.md H). Python 2.7.6 on the robot;
the code also imports under Python 3 so the laptop's tests can run it.

When the laptop has been gone for LAPTOP_GONE_S it gives the robot back: the
tablet page is hidden, the vendor app's dialog topics are reactivated, and it
exits. The laptop starts a fresh copy at the next Launch.

    python pepper_agent.py listen <port> <token_file> [<tablet_port>]
    python pepper_agent.py <laptop_ip> <laptop_port> <token_file> [<tablet_port>]
"""
from __future__ import print_function

import audioop
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

try:                                    # Python 2.7 on the robot
    import BaseHTTPServer as _http
    import SocketServer as _socketserver
    from urlparse import parse_qs, urlparse
except ImportError:                     # Python 3: the laptop's tests
    import http.server as _http
    import socketserver as _socketserver
    from urllib.parse import parse_qs, urlparse

from naoqi import ALBroker, ALModule, ALProxy

NAOQI_IP, NAOQI_PORT = "127.0.0.1", 9559
# Tests on the laptop bind 127.0.0.1 (a 0.0.0.0 listener makes Windows ask about the firewall).
BIND_HOST = os.environ.get("PEPPER_AGENT_HOST", "0.0.0.0")
TABLET_PORT = 8791
HERE = os.path.dirname(os.path.abspath(__file__))
SCREEN_DIR = os.path.join(HERE, "screen")
MEDIA_DIR = os.environ.get("PEPPER_AGENT_MEDIA", "/home/nao/.pepper_app/media")
MEDIA_CACHE_MAX = 200 * 1024 * 1024
MEDIA_WAIT_S = 20.0
LINK_IDLE_S = 20.0
HELLO_MAX = 64 * 1024
FRAME_MAX = 64 * 1024 * 1024
LAPTOP_GONE_S = 45.0
STATUS_EVERY_S = 3.0
VENDOR_TOPIC_PREFIX = "ht_cms"          # Humanizing Technologies app (ht_cms_1_5)
VENDOR_IDLE_TAG = "proactivemodetalk"   # its idle-talk rules (onProactive / onTwo / onThree)
VENDOR_IDLE_EVERY = 10                  # status loops between re-checks (~30 s)
CAMERA_RES = 1               # kQVGA, 320x240
CAMERA_SPACE = 11            # kRGBColorSpace
# Top camera field of view (Pepper 1.7), for drawing face boxes.
HFOV, VFOV = 1.0367, 0.8063

# ---------------------------------------------------------------- moves
# ONLY movements that ran on this Pepper on 2026-10-06, with the exact values
# that ran (session transcript; profiles/pepper.md C). Nothing else is offered:
# no other stock animation names, no tags, no Rest. Wheels only as "walk" (below).
#   wave       ALAnimationPlayer.run(Hey_1)                       4.4 s
# explain (Explain_1) and cheer were removed 2026-10-12: the user does not like them;
# explain was also the talking gesture played every 4 s while Pepper spoke.
#   yes / no   head pitch -0.40..+0.50 x3 / yaw +-0.90 x3          3.2 s / 4.1 s
#   arms       angleInterpolationWithSpeed(.., 0.35), breathing off, then
#              goToPosture("StandInit", 0.4)                       4.8 s
#   head       angleInterpolation([HeadYaw, HeadPitch], [+-0.5 / 0, -0.1], 1.5 s)
ANIMATIONS = {"wave": "animations/Stand/Gestures/Hey_1"}
R = ["RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll", "RWristYaw"]
L = ["LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll", "LWristYaw"]
R_UP, L_UP = [-1.4, -0.15, 1.2, 0.1, 0.0], [-1.4, 0.15, -1.2, -0.1, 0.0]
R_SIDE, L_SIDE = [0.0, -1.3, 1.2, 0.1, 0.0], [0.0, 1.3, -1.2, -0.1, 0.0]
ARM_POSES = {
    "right_arm_up": (R, R_UP),
    "left_arm_up": (L, L_UP),
    "arms_up": (R + L, R_UP + L_UP),
    "arms_wide": (R + L, R_SIDE + L_SIDE),
}
ARM_SPEED = 0.35
ARM_HOLD_S = 1.0
HEAD_YAW = {"left": 0.5, "center": 0.0, "right": -0.5}
YES_PITCH = [-0.40, 0.50] * 3 + [0.0]
NO_YAW = [0.9, -0.9] * 3 + [0.0]
# "walk": a short demo of the wheels (2026-10-12): 1 m forward, turn 180
# degrees, 1 m forward, turn 180 degrees -- back where it started, facing the
# same way. Slow, as tested on 2026-10-06 (profiles/pepper.md C, Base/wheels):
# Pepper keeps 0.40 m from obstacles and stops by itself; it will not drive
# while charging; basic awareness is paused so it does not turn the base.
WALK_LEGS = [(1.0, 0.0, 0.0), (0.0, 0.0, 3.14159), (1.0, 0.0, 0.0), (0.0, 0.0, 3.14159)]
WALK_CONFIG = [["MaxVelXY", 0.2], ["MaxAccXY", 0.2], ["MaxVelTheta", 0.6]]
WHEELS = ["WheelFL", "WheelFR", "WheelB"]
MOVES = sorted(list(ANIMATIONS) + list(ARM_POSES) + ["yes", "no", "hands", "walk"])


def walk_failed(why, leg):
    """Why Pepper refused a leg, for the operator (ALMotion/MoveFailed)."""
    reason = why[0] if why else "?"
    if reason == "Safety":
        try:
            x, y = why[2][0], why[2][1]
            where = " about %.1f m away" % ((x * x + y * y) ** 0.5)
        except Exception:
            where = ""
        return ("Walking stopped: something is in Pepper's way%s. Clear the floor around "
                "Pepper (it keeps 0.4 m from everything) and press Walking again." % where)
    if reason == "Rest":
        return "Walking stopped: Pepper's wheels were off. Press Walking again."
    return "Walking stopped at leg %d of %d (%s)." % (leg + 1, len(WALK_LEGS), reason)

def log(msg):
    print(time.strftime("%H:%M:%S"), msg)
    sys.stdout.flush()


def last_line(e):
    return (str(e).strip().splitlines() or ["?"])[-1][:200]


def png(width, height, rgb):
    """Raw RGB bytes -> PNG bytes, standard library only (no PIL on the robot)."""
    row = width * 3
    raw = b"".join(b"\x00" + rgb[y * row:(y + 1) * row] for y in range(height))

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 3))
            + chunk(b"IEND", b""))


# ---------------------------------------------------------------- the link
def same(a, b):
    """Constant-time string compare (hmac.compare_digest is 2.7.7+; the robot has 2.7.6)."""
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0


def close_sock(s):
    # shutdown first: a plain close() does not wake a recv() in another thread on Linux.
    try:
        s.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        s.close()
    except Exception:
        pass


def read_exact(s, n):
    buf = b""
    while len(buf) < n:
        part = s.recv(n - len(buf))
        if not part:
            raise IOError("laptop closed the connection")
        buf += part
    return buf


def read_frame(s, limit=FRAME_MAX):
    head = read_exact(s, 5)
    size = struct.unpack(">I", head[1:5])[0]
    if size > limit:
        raise IOError("frame of %d bytes is too big" % size)
    return head[0:1], read_exact(s, size)


def frame(kind, payload):
    return kind + struct.pack(">I", len(payload)) + payload


class Link(object):
    """The one TCP connection to the laptop, whichever side opened it."""

    def __init__(self, token):
        self.token = token
        self.sock = None
        self.wlock = threading.Lock()      # one frame at a time on the wire
        self.slock = threading.Lock()      # attach / detach
        self.gone_since = time.time()

    def attach(self, s):
        s.settimeout(LINK_IDLE_S)
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        with self.slock:
            old, self.sock = self.sock, s
            self.gone_since = None
        if old is not None and old is not s:
            close_sock(old)

    def detach(self, s):
        with self.slock:
            if self.sock is s:
                self.sock = None
                self.gone_since = time.time()
        close_sock(s)

    def send(self, kind, payload):
        s = self.sock
        if s is None:
            return False
        try:
            with self.wlock:
                s.sendall(frame(kind, payload))
            return True
        except Exception:
            self.detach(s)
            return False

    def send_json(self, obj):
        return self.send(b"J", json.dumps(obj).encode("utf-8"))

    def send_pair(self, meta, blob):
        """A J and the I that belongs to it, together (camera frames)."""
        s = self.sock
        if s is None:
            return False
        body = json.dumps(meta).encode("utf-8")
        try:
            with self.wlock:
                s.sendall(frame(b"J", body) + frame(b"I", blob))
            return True
        except Exception:
            self.detach(s)
            return False


# ------------------------------------------------------------ the tablet
MEDIA_DECK = re.compile(r"^[a-z0-9]{8,32}$")
MEDIA_FILE = re.compile(r"^\d{3}\.(png|jpg|jpeg|gif|webp)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
               "gif": "image/gif", "webp": "image/webp"}
SCREEN_FILES = {"/screen": ("screen.html", "text/html; charset=utf-8"),
                "/screen/": ("screen.html", "text/html; charset=utf-8"),
                "/screen/render.js": ("screen-render.js", "application/javascript; charset=utf-8"),
                "/screen/logo.png": ("labalab-logo.png", "image/png")}
WELCOME_STATE = b'{"v": 0, "item": {"kind": "welcome"}, "by": "start", "picked": null}'


class _ThreadedHTTP(_socketserver.ThreadingMixIn, _http.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TabletHandler(_http.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json", cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        t = self.server.tablet
        url = urlparse(self.path)
        path = url.path
        if path in SCREEN_FILES:
            name, ctype = SCREEN_FILES[path]
            try:
                with open(os.path.join(t.files_dir, name), "rb") as f:
                    body = f.read()
            except (IOError, OSError):
                return self._send(404, b'{"error": "missing"}')
            return self._send(200, body, ctype, cache=name.endswith(".png"))
        if path == "/screen/state":
            if not t.link_up():
                return self._send(503, b'{"error": "the laptop is not linked"}')
            if "tablet" in parse_qs(url.query):
                t.heartbeat(self.client_address[0], self.headers.get("User-Agent") or "")
            return self._send(200, t.state)
        if path.startswith("/screen/media/"):
            parts = path.split("/")
            if len(parts) == 5:
                data = t.media(parts[3], parts[4])
                if data is not None:
                    return self._send(200, data, MEDIA_TYPES[parts[4].rsplit(".", 1)[1]], cache=True)
            return self._send(404, b'{"error": "no such slide"}')
        return self._send(404, b'{"error": "not here"}')

    def do_POST(self):
        t = self.server.tablet
        if urlparse(self.path).path != "/screen/tap":
            return self._send(404, b'{"error": "not here"}')
        try:
            n = min(int(self.headers.get("Content-Length") or 0), 4096)
            d = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            v, i = int(d.get("v", -1)), int(d.get("i", -1))
        except Exception:
            return self._send(400, b'{"ok": false}')
        if not t.tap(v, i):
            return self._send(503, b'{"ok": false}')
        return self._send(200, b'{"ok": true}')


class Tablet(object):
    """The chest tablet's page, served from the robot; state, taps and
    slides travel over the laptop link."""

    def __init__(self, port, link, files_dir=SCREEN_DIR, cache_dir=MEDIA_DIR):
        self.port, self.link = port, link
        self.files_dir, self.cache_dir = files_dir, cache_dir
        self.state = WELCOME_STATE
        self.lock = threading.Lock()
        self.rid = 0
        self.waiting = {}
        self.httpd = None

    def start(self):
        self.httpd = _ThreadedHTTP((BIND_HOST, self.port), TabletHandler)
        self.httpd.tablet = self
        self.port = self.httpd.server_address[1]
        t = threading.Thread(target=self.httpd.serve_forever)
        t.daemon = True
        t.start()
        return self.port

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()

    def link_up(self):
        return self.link.sock is not None

    def set_state(self, state):
        self.state = json.dumps(state).encode("utf-8")

    def heartbeat(self, ip, agent):
        self.link.send_json({"ev": "tablet", "ip": ip, "ua": agent[:120]})

    def tap(self, v, i):
        return self.link.send_json({"ev": "tap", "v": v, "i": i})

    def media(self, deck, name):
        """The slide's bytes: from the cache on the robot, else from the laptop."""
        if not MEDIA_DECK.match(deck or "") or not MEDIA_FILE.match(name or ""):
            return None
        path = os.path.join(self.cache_dir, deck, name)
        if os.path.isfile(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except (IOError, OSError):
                pass
        ev = threading.Event()
        with self.lock:
            self.rid += 1
            rid = self.rid
            self.waiting[rid] = [ev, None]
        if self.link.send_json({"ev": "media", "rid": rid, "deck": deck, "file": name}):
            ev.wait(MEDIA_WAIT_S)
        with self.lock:
            slot = self.waiting.pop(rid, None)
        data = slot[1] if slot else None
        if data is not None:
            self._store(path, data)
        return data

    def media_in(self, payload):
        """A D frame from the laptop: the answer to one media request."""
        n = struct.unpack(">I", payload[:4])[0]
        head = json.loads(payload[4:4 + n].decode("utf-8"))
        with self.lock:
            slot = self.waiting.get(head.get("rid"))
        if slot is not None:
            slot[1] = payload[4 + n:] if head.get("ok") else None
            slot[0].set()

    def _store(self, path, data):
        try:
            d = os.path.dirname(path)
            if not os.path.isdir(d):
                os.makedirs(d)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.rename(tmp, path)
            self._prune()
        except Exception as e:
            log("media cache: %s" % last_line(e))

    def _prune(self):
        files = []
        for root, _dirs, names in os.walk(self.cache_dir):
            for name in names:
                p = os.path.join(root, name)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, p))
        total = sum(f[1] for f in files)
        for _mtime, size, p in sorted(files):
            if total <= MEDIA_CACHE_MAX:
                break
            try:
                os.remove(p)
                total -= size
            except OSError:
                pass


# ---------------------------------------------------------------- speaker
class Speaker(object):
    """Plays the laptop's 24 kHz speech on Pepper's loudspeakers.

    ALAudioDevice.sendRemoteBufferToOutput (48 kHz stereo) first; if this
    NAOqi will not take a buffer from Python, `aplay` reading raw PCM on
    stdin. Which one works is reported to the laptop as `speaker_mode`.
    """

    CHUNK_S = 0.10
    LEAD_S = 0.25            # how far ahead of real time we may queue

    def __init__(self, audio):
        self.audio = audio
        self.q = []
        self.lock = threading.Condition()
        self.gen = 0          # bumped by flush(): queued audio is dropped
        self.playing = False
        self.on_playing = None
        self.mode = None
        self.proc = None
        self.rate_state = None   # ratecv state, kept across chunks (no clicks)
        t = threading.Thread(target=self._run)
        t.daemon = True
        t.start()

    def detect(self):
        silence = b"\x00\x00" * 2 * 480          # 10 ms of 48 kHz stereo
        try:
            if self.audio.sendRemoteBufferToOutput(480, silence):
                self.mode = "naoqi"
                return self.mode
        except Exception as e:
            log("speaker: sendRemoteBufferToOutput refused (%s)" % last_line(e))
        for cmd in (["aplay", "-q", "-t", "raw", "-f", "S16_LE", "-r", "24000", "-c", "1", "-"],
                    ["paplay", "--raw", "--rate=24000", "--channels=1", "--format=s16le"]):
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                time.sleep(0.3)
                if p.poll() is None:
                    self.proc, self.mode = p, cmd[0]
                    return self.mode
            except Exception as e:
                log("speaker: %s not usable (%s)" % (cmd[0], last_line(e)))
        self.mode = "none"
        return self.mode

    def push(self, pcm24):
        with self.lock:
            self.q.append((self.gen, pcm24))
            self.lock.notify()

    def flush(self):
        with self.lock:
            self.gen += 1
            self.q = []
            self.rate_state = None
            self.lock.notify()
        if self.proc is not None:            # aplay holds its own buffer: restart it
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
            self.detect()

    def _set_playing(self, on):
        if on != self.playing:
            self.playing = on
            if self.on_playing:
                self.on_playing(on)

    def _run(self):
        t0, played = None, 0.0
        while True:
            with self.lock:
                if not self.q:
                    self.lock.wait(0.15)
                if not self.q:
                    if t0 is not None and time.time() > t0 + played:
                        t0, played = None, 0.0
                        self._set_playing(False)
                    continue
                gen, pcm = self.q.pop(0)
                if gen != self.gen:
                    continue
            if t0 is None:
                t0, played = time.time(), 0.0
                self._set_playing(True)
            secs = len(pcm) / 48000.0
            try:
                if self.mode == "naoqi":
                    up, self.rate_state = audioop.ratecv(pcm, 2, 1, 24000, 48000, self.rate_state)
                    stereo = audioop.tostereo(up, 2, 1, 1)
                    step = int(48000 * self.CHUNK_S) * 4
                    for i in range(0, len(stereo), step):
                        if gen != self.gen:
                            break
                        part = stereo[i:i + step]
                        self.audio.sendRemoteBufferToOutput(len(part) // 4, part)
                elif self.proc is not None:
                    self.proc.stdin.write(pcm)
                    self.proc.stdin.flush()
            except Exception as e:
                log("speaker: %s" % last_line(e))
            played += secs
            ahead = t0 + played - time.time() - self.LEAD_S
            if ahead > 0:
                time.sleep(ahead)


# ------------------------------------------------------------- microphone
class MicModule(ALModule):
    """Pepper's front microphone at 16 kHz, forwarded while the laptop asks."""

    def __init__(self, name):
        ALModule.__init__(self, name)
        self.link = None
        self.on = False

    def processRemote(self, nbOfChannels, nbOfSamplesByChannel, timeStamp, inputBuffer):
        """ALAudioDevice callback: one buffer of int16 samples."""
        if self.on and self.link is not None:
            self.link.send(b"M", bytes(inputBuffer))


# ------------------------------------------------------------------ agent
class Agent(object):
    def __init__(self, link):
        self.link = link
        p = {}
        for name in ["ALTextToSpeech", "ALAnimatedSpeech", "ALAnimationPlayer", "ALMotion",
                     "ALBasicAwareness", "ALBattery", "ALMemory", "ALAudioDevice",
                     "ALSystem", "ALRobotPosture", "ALVideoDevice", "ALTabletService",
                     "ALDialog", "ALFaceDetection"]:
            try:
                p[name] = ALProxy(name, NAOQI_IP, NAOQI_PORT)
            except Exception as e:
                log("no %s (%s)" % (name, last_line(e)))
        self.p = p
        self.speaker = Speaker(p["ALAudioDevice"])
        self.speaker.on_playing = lambda on: self.link.send_json({"ev": "playing", "on": on})
        self.motion_busy_until = 0.0
        self.anim_id = None
        self.cam = None
        self.cam_index = 0
        self.cam_fps = 2.0
        self.vendor_topics = None
        self.vendor_idle_err = None
        self.walking = False
        self.walk_stop = False
        self.webview_url = None
        self.tablet = None
        self.tablet_error = None

    def hello(self, mode, token=None):
        h = {"ev": "hello", "info": info(self.p), "speaker_mode": self.speaker.mode,
             "pid": os.getpid(), "mode": mode,
             "tablet_port": self.tablet.port if self.tablet else None,
             "tablet_error": self.tablet_error}
        if token is not None:
            h["token"] = token
        return h

    def mic_off(self):
        if MicSink is not None:
            MicSink.on = False

    # ---- helpers
    def _anim(self, name):
        self.anim_id = self.p["ALAnimationPlayer"].post.run(ANIMATIONS[name])
        return ANIMATIONS[name]

    def _in_thread(self, fn):
        t = threading.Thread(target=fn)
        t.daemon = True
        t.start()

    def _with_awareness_paused(self, fn):
        """Face tracking would pull the head back, so it is paused around a head
        move and restored afterwards -- exactly as tested."""
        aw = self.p["ALBasicAwareness"]
        was = aw.isEnabled()
        try:
            aw.setEnabled(False)
            time.sleep(0.3)
            fn()
        finally:
            aw.setEnabled(was)

    def _nod(self, kind):
        mot = self.p["ALMotion"]

        def run():
            mot.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], [0.6, 0.6], True)
            if kind == "yes":
                mot.angleInterpolation("HeadPitch", YES_PITCH,
                                       [0.45 * (i + 1) for i in range(len(YES_PITCH))], True)
            else:
                mot.angleInterpolation("HeadYaw", NO_YAW,
                                       [0.5] + [0.5 + 0.6 * (i + 1) for i in range(len(NO_YAW) - 1)], True)
        self._in_thread(lambda: self._with_awareness_paused(run))

    def _walk(self):
        """Drive the walk legs in a thread. Refuses while charging; stops the
        whole walk when a leg fails (an obstacle) or Stop is pressed."""
        p = self.p
        try:
            charging = p["ALMemory"].getData("Device/SubDeviceList/Battery/Current/Sensor/Value") > 0.5
        except Exception:
            charging = False
        if charging:
            raise RuntimeError("Pepper is charging. Unplug the charger and close the flap, "
                               "then press Walking again.")
        if self.walking:
            raise RuntimeError("Pepper is already walking")
        mot = p["ALMotion"]
        self.walking, self.walk_stop = True, False
        self.motion_busy_until = time.time() + 60.0

        def run():
            try:
                mot.wakeUp()
                mot.moveInit()
                # Face tracking is paused for the walk, which froze the head wherever it
                # was looking (up and to the side, 2026-10-12): look straight ahead first.
                mot.angleInterpolation(["HeadYaw", "HeadPitch"], [0.0, 0.0], [1.0, 1.0], True)
                for i, (x, y, theta) in enumerate(WALK_LEGS):
                    if self.walk_stop:
                        self._tell("INFO", "Walking: stopped (Stop pressed)")
                        return
                    # Pepper rests idle wheels after ~5 s; a leg started on resting
                    # wheels was refused with "Rest" (2026-10-12).
                    mot.setStiffnesses(WHEELS, 1.0)
                    if not mot.moveTo(x, y, theta, WALK_CONFIG):
                        try:
                            why = p["ALMemory"].getData("ALMotion/MoveFailed")
                        except Exception:
                            why = None
                        self._tell("WARNING", walk_failed(why, i))
                        return
                self._tell("INFO", "Walking: done")
            except Exception as e:
                log("walk: %s" % last_line(e))
            finally:
                self.walking = False
                self.motion_busy_until = time.time() + 1.0
        self._in_thread(lambda: self._with_awareness_paused(run))
        return "walk (1 m, turn, 1 m, turn)"

    def _tell(self, level, text):
        """A line for the dashboard log (and the robot's own log)."""
        log(text)
        try:
            self.link.send_json({"ev": "log", "level": level, "msg": text})
        except Exception:
            pass

    def _arms(self, name):
        mot, pos = self.p["ALMotion"], self.p["ALRobotPosture"]

        def run():
            breath = mot.getBreathEnabled("Arms")
            mot.setBreathEnabled("Arms", False)
            try:
                if name == "hands":
                    for side in ("R", "L"):
                        for _ in range(2):
                            mot.angleInterpolationWithSpeed(side + "Hand", 1.0, 0.6)
                            mot.angleInterpolationWithSpeed(side + "Hand", 0.1, 0.6)
                        mot.angleInterpolationWithSpeed(side + "Hand", 0.6, 0.6)
                else:
                    names, angles = ARM_POSES[name]
                    mot.angleInterpolationWithSpeed(names, angles, ARM_SPEED)
                    time.sleep(ARM_HOLD_S)
            finally:
                pos.goToPosture("StandInit", 0.4)
                mot.setBreathEnabled("Arms", breath)
        self._in_thread(run)

    # ---- commands
    def handle(self, msg):
        cmd = msg.get("cmd")
        fn = getattr(self, "cmd_" + str(cmd), None)
        if fn is None:
            raise RuntimeError("unknown command %r" % cmd)
        return fn(msg) or {}

    def cmd_ping(self, m):
        return {"t": time.time()}

    def cmd_say(self, m):
        text = (m.get("text") or u"").strip()[:500].encode("utf-8")
        if m.get("gestures", True):
            self.p["ALAnimatedSpeech"].post.say(text, {"bodyLanguageMode": "contextual"})
        else:
            self.p["ALTextToSpeech"].post.say(text)

    def cmd_stop_speech(self, m):
        self.speaker.flush()
        try:
            self.p["ALTextToSpeech"].stopAll()
        except Exception:
            pass

    def cmd_mic(self, m):
        if MicSink is not None:
            MicSink.on = bool(m.get("on"))

    def cmd_screen_state(self, m):
        """What the chest tablet shows now (pushed by the laptop on every change)."""
        if self.tablet is None:
            raise RuntimeError("the tablet page server is not running: %s" % self.tablet_error)
        self.tablet.set_state(m.get("state") or {})

    def cmd_move(self, m):
        name = m.get("name")
        if name not in MOVES:
            raise RuntimeError("%r is not one of the movements tested on this robot" % name)
        if name == "walk":
            return {"did": self._walk()}
        self.motion_busy_until = time.time() + 5.0
        if name in ANIMATIONS:
            return {"did": self._anim(name)}
        if name in ("yes", "no"):
            self._nod(name)
        else:
            self._arms(name)
        return {"did": name}

    def cmd_head(self, m):
        d = m.get("dir")
        if d not in HEAD_YAW:
            raise RuntimeError("head moves are left, center and right")
        mot = self.p["ALMotion"]
        self._in_thread(lambda: self._with_awareness_paused(
            lambda: mot.angleInterpolation(["HeadYaw", "HeadPitch"], [HEAD_YAW[d], -0.1], [1.5, 1.5], True)))
        return {"yaw": HEAD_YAW[d]}

    def cmd_face_tracking(self, m):
        on = bool(m.get("on"))
        self.p["ALBasicAwareness"].setEnabled(on)
        return {"on": on}

    def cmd_posture(self, m):
        if m.get("name") != "stand":
            raise RuntimeError("only Stand was tested on this robot")
        self.p["ALRobotPosture"].post.goToPosture("StandInit", 0.4)

    def cmd_stop_motion(self, m):
        self.walk_stop = True
        if self.anim_id is not None:
            try:
                self.p["ALAnimationPlayer"].stop(self.anim_id)
            except Exception:
                pass
        try:
            self.p["ALMotion"].stopMove()
        except Exception:
            pass

    def cmd_stop_all(self, m):
        self.cmd_stop_speech(m)
        self.cmd_stop_motion(m)

    def cmd_volume(self, m):
        self.p["ALAudioDevice"].setOutputVolume(max(0, min(100, int(m.get("value", 50)))))

    def cmd_camera(self, m):
        self.cam_index = 1 if m.get("index") == 1 else 0
        self.cam_fps = max(0.0, min(5.0, float(m.get("fps", self.cam_fps))))
        if self.cam is not None:
            try:
                self.p["ALVideoDevice"].setActiveCamera(self.cam, self.cam_index)
            except Exception:
                self._cam_close()

    def cmd_tablet_show(self, m):
        url = str(m.get("url"))
        tab = self.p["ALTabletService"]
        self.webview_url = url
        ok = tab.showWebview(url)
        return {"ok_tablet": bool(ok)}

    def cmd_tablet_hide(self, m):
        self.webview_url = None
        self.p["ALTabletService"].hideWebview()

    def cmd_vendor_quiet(self, m):
        """While our conversation runs, the vendor app's dialog must not answer
        people too (profiles/pepper.md C, Listening)."""
        dlg = self.p["ALDialog"]
        if m.get("on"):
            if self.vendor_topics is None:
                self.vendor_topics = list(dlg.getActivatedTopics())
                for t in self.vendor_topics:
                    try:
                        dlg.deactivateTopic(t)
                    except Exception as e:
                        log("could not pause topic %s (%s)" % (t, last_line(e)))
            return {"paused": self.vendor_topics}
        self._vendor_restore()

    def _vendor_restore(self):
        if self.vendor_topics is None:
            return
        dlg = self.p["ALDialog"]
        for t in self.vendor_topics:
            try:
                dlg.activateTopic(t)
            except Exception as e:
                log("could not restore topic %s (%s)" % (t, last_line(e)))
        self.vendor_topics = None
        self.vendor_idle_talk(False)

    def vendor_idle_talk(self, on):
        """The vendor app talks by itself when nobody is talking to it ("Want to
        see how the feedback feature works?" every ~60 s, plus attraction and
        solitary lines). All of those dialog rules carry one tag; it is off while
        the dashboard runs (tested on Pepper 2026-10-12: onProactive went silent)."""
        dlg = self.p["ALDialog"]
        try:
            topics = [t for t in dlg.getAllLoadedTopics() if t.startswith(VENDOR_TOPIC_PREFIX)]
        except Exception as e:
            topics, err = [], "no dialog topics (%s)" % last_line(e)
        else:
            err = None
        for t in topics:
            try:
                (dlg.activateTag if on else dlg.deactivateTag)(VENDOR_IDLE_TAG, t)
            except Exception as e:
                err = "vendor idle talk %s in %s: %s" % ("on" if on else "off", t, last_line(e))
        if err and err != self.vendor_idle_err:
            log(err)
        self.vendor_idle_err = err

    # ---- background loops
    def status(self):
        p, s = self.p, {}
        for key, fn in (("battery", lambda: p["ALBattery"].getBatteryCharge()),
                        ("charging", lambda: p["ALMemory"].getData(
                            "Device/SubDeviceList/Battery/Current/Sensor/Value") > 0.5),
                        ("volume", lambda: p["ALAudioDevice"].getOutputVolume()),
                        ("posture", lambda: p["ALRobotPosture"].getPostureFamily()),
                        ("awake", lambda: p["ALMotion"].robotIsWakeUp()),
                        ("awareness", lambda: p["ALBasicAwareness"].isEnabled())):
            try:
                s[key] = fn()
            except Exception:
                s[key] = None
        s["speaker_mode"] = self.speaker.mode
        s["playing"] = self.speaker.playing
        return s

    def status_loop(self):
        n = 0
        while True:
            self.link.send_json({"ev": "status", "status": self.status()})
            if n % VENDOR_IDLE_EVERY == 0:      # the vendor app may switch it back on
                self.vendor_idle_talk(False)
            n += 1
            time.sleep(STATUS_EVERY_S)

    def _cam_close(self):
        if self.cam is not None:
            try:
                self.p["ALVideoDevice"].unsubscribe(self.cam)
            except Exception:
                pass
        self.cam = None

    def faces(self, w, h):
        try:
            data = self.p["ALMemory"].getData("FaceDetected")
            if not data or len(data) < 2:
                return []
            out = []
            for face in data[1][:-1]:
                shape = face[0]
                alpha, beta, sx, sy = shape[1], shape[2], shape[3], shape[4]
                cx, cy = w * (0.5 - alpha / HFOV), h * (0.5 + beta / VFOV)
                fw, fh = w * sx / HFOV, h * sy / VFOV
                out.append([int(cx - fw / 2), int(cy - fh / 2), int(fw), int(fh)])
            return out
        except Exception:
            return []

    def camera_loop(self):
        vd = self.p["ALVideoDevice"]
        try:
            self.p["ALFaceDetection"].subscribe("HubAgentFaces", 500, 0.0)
        except Exception:
            pass
        while True:
            if self.cam_fps <= 0 or self.link.sock is None:
                self._cam_close()
                time.sleep(0.5)
                continue
            t0 = time.time()
            try:
                if self.cam is None:
                    self.cam = vd.subscribeCamera("HubAgentCam", self.cam_index, CAMERA_RES, CAMERA_SPACE, 5)
                img = vd.getImageRemote(self.cam)
                if img:
                    w, h, data = img[0], img[1], img[6]
                    meta = {"ev": "frame", "w": w, "h": h, "cam": self.cam_index, "faces": self.faces(w, h)}
                    self.link.send_pair(meta, png(w, h, bytes(data)))   # the J and the I stay together
            except Exception as e:
                log("camera: %s" % last_line(e))
                self._cam_close()
                time.sleep(2)
            time.sleep(max(0.05, 1.0 / max(self.cam_fps, 0.2) - (time.time() - t0)))

    def give_back(self):
        """The laptop is gone: leave Pepper as the vendor app expects it."""
        log("laptop gone: hiding the tablet page, restoring the vendor dialog")
        self.mic_off()
        self.speaker.flush()
        self._vendor_restore()
        self.vendor_idle_talk(True)
        try:
            if self.webview_url:
                self.p["ALTabletService"].hideWebview()
        except Exception:
            pass
        self._cam_close()
        try:
            self.p["ALFaceDetection"].unsubscribe("HubAgentFaces")
        except Exception:
            pass
        try:
            self.p["ALAudioDevice"].unsubscribe("MicSink")
        except Exception:
            pass


def info(p):
    out = {}
    for key, fn in (("name", lambda: p["ALSystem"].robotName()),
                    ("naoqi", lambda: p["ALSystem"].systemVersion()),
                    ("head_id", lambda: p["ALMemory"].getData("RobotConfig/Head/FullHeadId"))):
        try:
            out[key] = fn()
        except Exception:
            out[key] = None
    return out


def serve(link, agent, s):
    """Frames from the laptop on socket `s`, until it closes or goes quiet."""
    while True:
        kind, payload = read_frame(s)
        if kind == b"S":
            agent.speaker.push(payload)
        elif kind == b"D":
            if agent.tablet is not None:
                agent.tablet.media_in(payload)
        elif kind == b"J":
            msg = json.loads(payload.decode("utf-8"))
            reply = {"id": msg.get("id")}
            try:
                reply.update(agent.handle(msg))
                reply["ok"] = True
            except Exception as e:
                reply.update({"ok": False, "error": last_line(e)})
                log("%s failed: %s" % (msg.get("cmd"), reply["error"]))
            if msg.get("id") is not None:
                link.send_json(reply)


def welcome(link, agent, conn, addr):
    """Listen mode: one laptop's connection. It must name the token first."""
    try:
        conn.settimeout(10)
        kind, payload = read_frame(conn, HELLO_MAX)
        hello = json.loads(payload.decode("utf-8")) if kind == b"J" else {}
        if hello.get("ev") != "hello" or not same(str(hello.get("token", "")), link.token):
            log("refused a connection from %s (bad hello)" % addr[0])
            close_sock(conn)
            return
        conn.sendall(frame(b"J", json.dumps(agent.hello("listen")).encode("utf-8")))
    except Exception as e:
        log("a connection from %s failed: %s" % (addr[0], last_line(e)))
        close_sock(conn)
        return
    link.attach(conn)
    log("laptop %s linked" % addr[0])
    try:
        serve(link, agent, conn)
    except Exception as e:
        log("laptop link closed (%s)" % last_line(e))
    finally:
        link.detach(conn)
        if link.sock is None:
            agent.mic_off()


def gone_too_long(link):
    since = link.gone_since
    return link.sock is None and since is not None and time.time() - since > LAPTOP_GONE_S


def listen_loop(link, agent, port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND_HOST, port))
    srv.listen(4)
    srv.settimeout(1.0)
    log("waiting for the laptop on port %d" % port)
    while True:
        try:
            conn, addr = srv.accept()
        except socket.timeout:
            conn = None
        except Exception as e:
            log("accept: %s" % last_line(e))
            conn = None
            time.sleep(1)
        if conn is not None:
            t = threading.Thread(target=welcome, args=(link, agent, conn, addr))
            t.daemon = True
            t.start()
        if gone_too_long(link):
            agent.give_back()
            os._exit(0)


def connect_back_loop(link, agent, host, port):
    """Fallback: the agent connects to the laptop (as before 2026-11-05)."""
    told = False
    while True:
        s = None
        try:
            s = socket.create_connection((host, port), timeout=5)
            s.sendall(frame(b"J", json.dumps(agent.hello("connect_back", link.token)).encode("utf-8")))
            link.attach(s)
            log("connected to the laptop at %s:%d" % (host, port))
            told = False
            serve(link, agent, s)
        except Exception as e:
            if s is not None:
                link.detach(s)
            agent.mic_off()
            if not told:
                told = True
                log("no laptop (%s); retrying" % last_line(e))
        if gone_too_long(link):
            agent.give_back()
            os._exit(0)
        time.sleep(2)


def main(argv):
    if len(argv) >= 4 and argv[1] == "listen":
        mode, host, port, token_file = "listen", None, int(argv[2]), argv[3]
    else:
        mode, host, port, token_file = "connect_back", argv[1], int(argv[2]), argv[3]
    tablet_port = int(argv[4]) if len(argv) > 4 else TABLET_PORT
    with open(token_file) as f:
        token = f.read().strip()
    try:
        os.remove(token_file)
    except Exception:
        pass

    global MicSink
    broker = ALBroker("HubAgentBroker", "0.0.0.0", 0, NAOQI_IP, NAOQI_PORT)  # noqa: F841 (kept alive)
    MicSink = MicModule("MicSink")
    link = Link(token)
    MicSink.link = link
    agent = Agent(link)
    tablet = Tablet(tablet_port, link)
    try:
        tablet.start()
        agent.tablet = tablet
        log("tablet page on port %d" % tablet.port)
    except Exception as e:
        agent.tablet_error = last_line(e)
        log("tablet page server failed: %s" % agent.tablet_error)
    log("speaker mode: %s" % agent.speaker.detect())
    audio = agent.p["ALAudioDevice"]
    audio.setClientPreferences("MicSink", 16000, 3, 0)   # front mic, 16 kHz, deinterleaved
    audio.subscribe("MicSink")

    for loop in (agent.status_loop, agent.camera_loop):
        t = threading.Thread(target=loop)
        t.daemon = True
        t.start()

    if mode == "listen":
        listen_loop(link, agent, port)
    else:
        connect_back_loop(link, agent, host, port)


MicSink = None

if __name__ == "__main__":
    main(sys.argv)
