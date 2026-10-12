# -*- coding: utf-8 -*-
"""Runs ON Pepper (Python 2.7.6, NAOqi 2.5): the robot half of the Pepper app.

Uploaded and started over SSH by the laptop (pepper_app/robot.py) at every
Launch. It connects OUT to the laptop -- the direction Pepper's head and tablet
already reached the laptop on 2026-10-06 (profiles/pepper.md, section D) -- and
keeps one TCP connection carrying everything:

    laptop -> robot   J  {"id": n, "cmd": ...}      commands
                      S  PCM16 24 kHz mono         speech to play
    robot -> laptop   J  {"ev": ...} / {"id": n, "ok": ...}
                      M  PCM16 16 kHz mono         front microphone
                      I  PNG                       camera frame (after a J "frame")

Frame = 1 byte type + 4 byte big-endian length + payload.

Standard library + naoqi only: the robot's root filesystem is read-only and
nothing can be installed (profiles/pepper.md H).

When the laptop has been gone for LAPTOP_GONE_S it gives the robot back: the
tablet page is hidden, the vendor app's dialog topics are reactivated, and it
exits. The laptop starts a fresh copy at the next Launch.

    python pepper_agent.py <laptop_ip> <laptop_port> <token_file>
"""
from __future__ import print_function

import audioop
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import zlib

from naoqi import ALBroker, ALModule, ALProxy

NAOQI_IP, NAOQI_PORT = "127.0.0.1", 9559
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
# explain (Explain_1) and cheer were removed 2026-10-12: Tomer does not like them;
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
# "walk": a short demo of the wheels (Tomer, 2026-10-12): 1 m forward, turn 180
# degrees, 1 m forward, turn 180 degrees -- back where it started, facing the
# same way. Slow, as tested on 2026-10-06 (profiles/pepper.md C, Base/wheels):
# Pepper keeps 0.40 m from obstacles and stops by itself; it will not drive
# while charging; basic awareness is paused so it does not turn the base.
WALK_LEGS = [(1.0, 0.0, 0.0), (0.0, 0.0, 3.14159), (1.0, 0.0, 0.0), (0.0, 0.0, 3.14159)]
WALK_CONFIG = [["MaxVelXY", 0.2], ["MaxAccXY", 0.2], ["MaxVelTheta", 0.6]]
MOVES = sorted(list(ANIMATIONS) + list(ARM_POSES) + ["yes", "no", "hands", "walk"])

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
class Link(object):
    def __init__(self, host, port, token):
        self.host, self.port, self.token = host, port, token
        self.sock = None
        self.wlock = threading.Lock()
        self.last_ok = time.time()

    def connect(self):
        s = socket.create_connection((self.host, self.port), timeout=5)
        s.settimeout(None)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = s
        self.last_ok = time.time()

    def send(self, kind, payload):
        s = self.sock
        if s is None:
            return False
        try:
            with self.wlock:
                s.sendall(kind + struct.pack(">I", len(payload)) + payload)
            return True
        except Exception:
            self.close()
            return False

    def send_json(self, obj):
        return self.send(b"J", json.dumps(obj).encode("utf-8"))

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            part = self.sock.recv(n - len(buf))
            if not part:
                raise IOError("laptop closed the connection")
            buf += part
        return buf

    def recv(self):
        head = self._read(5)
        kind, size = head[0:1], struct.unpack(">I", head[1:5])[0]
        return kind, self._read(size)

    def close(self):
        s, self.sock = self.sock, None
        if s is not None:
            try:
                s.close()
            except Exception:
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
            raise RuntimeError("Pepper is charging: unplug the charger and close the flap, "
                               "then press Walking again")
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
                        log("walk: stopped by the operator before leg %d" % (i + 1))
                        return
                    if not mot.moveTo(x, y, theta, WALK_CONFIG):
                        try:
                            why = p["ALMemory"].getData("ALMotion/MoveFailed")
                        except Exception:
                            why = "?"
                        log("walk: leg %d of %d did not finish (%s); stopping the walk"
                            % (i + 1, len(WALK_LEGS), why))
                        return
                log("walk: done")
            except Exception as e:
                log("walk: %s" % last_line(e))
            finally:
                self.walking = False
                self.motion_busy_until = time.time() + 1.0
        self._in_thread(lambda: self._with_awareness_paused(run))
        return "walk (1 m, turn, 1 m, turn)"

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
        MicSink.on = bool(m.get("on"))

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
                    blob = png(w, h, bytes(data))
                    with self.link.wlock:     # the J and the I must stay together
                        s = self.link.sock
                        if s is not None:
                            body = json.dumps(meta).encode("utf-8")
                            s.sendall(b"J" + struct.pack(">I", len(body)) + body
                                      + b"I" + struct.pack(">I", len(blob)) + blob)
            except Exception as e:
                log("camera: %s" % last_line(e))
                self._cam_close()
                time.sleep(2)
            time.sleep(max(0.05, 1.0 / max(self.cam_fps, 0.2) - (time.time() - t0)))

    def give_back(self):
        """The laptop is gone: leave Pepper as the vendor app expects it."""
        log("laptop gone: hiding the tablet page, restoring the vendor dialog")
        MicSink.on = False
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


def main():
    host, port, token_file = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    with open(token_file) as f:
        token = f.read().strip()
    try:
        os.remove(token_file)
    except Exception:
        pass

    global MicSink
    broker = ALBroker("HubAgentBroker", "0.0.0.0", 0, NAOQI_IP, NAOQI_PORT)  # noqa: F841 (kept alive)
    MicSink = MicModule("MicSink")
    link = Link(host, port, token)
    MicSink.link = link
    agent = Agent(link)
    log("speaker mode: %s" % agent.speaker.detect())
    audio = agent.p["ALAudioDevice"]
    audio.setClientPreferences("MicSink", 16000, 3, 0)   # front mic, 16 kHz, deinterleaved
    audio.subscribe("MicSink")

    for loop in (agent.status_loop, agent.camera_loop):
        t = threading.Thread(target=loop)
        t.daemon = True
        t.start()

    gone_since = None
    while True:
        try:
            link.connect()
            link.send_json({"ev": "hello", "token": token, "info": info(agent.p),
                            "speaker_mode": agent.speaker.mode, "pid": os.getpid()})
            log("connected to the laptop at %s:%d" % (host, port))
            gone_since = None
            while True:
                kind, payload = link.recv()
                link.last_ok = time.time()
                if kind == b"S":
                    agent.speaker.push(payload)
                elif kind == b"J":
                    msg = json.loads(payload.decode("utf-8"))
                    reply = {"id": msg.get("id")}
                    try:
                        reply.update(agent.handle(msg))
                        reply["ok"] = True
                    except Exception as e:
                        reply.update({"ok": False, "error": last_line(e)})
                        log("%s failed: %s" % (msg.get("cmd"), reply["error"]))
                    link.send_json(reply)
        except Exception as e:
            link.close()
            MicSink.on = False
            if gone_since is None:
                gone_since = time.time()
                log("no laptop (%s); retrying" % last_line(e))
            if time.time() - gone_since > LAPTOP_GONE_S:
                agent.give_back()
                os._exit(0)
            time.sleep(2)


MicSink = None

if __name__ == "__main__":
    main()
