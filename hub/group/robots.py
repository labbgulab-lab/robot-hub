"""Group conversation: the hub's link to each robot's speaker, head and mic.

The conductor (conductor.py) decides who talks; this module only moves audio
and head commands. Each Reachy Mini gets ONE SSH connection with two exec
channels on it:

- the speech player, /home/pollen/scripts/robot_streaming_player.py, the same
  long-running process reachy_chat drives (`StreamingRobotPlayer` in
  reachy_chat/conversation.py). Its stdin takes length-prefixed frames:
  float32 16 kHz audio, end-of-turn, clear, and JSON motion commands. It
  keeps the head breathing between lines and sways it while it talks.
- the microphone: `arecord` on the ALSA dsnoop device the daemon shares, raw
  int16 16 kHz mono on stdout, cut here into 512-sample blocks for the VAD.
  Robots without arecord get a five-line sounddevice recorder instead.

reachy_chat is not imported: it is a separate checkout with heavy import side
effects (SDK, Gemini client, motion catalogue). Its few lines of framing are
mirrored here instead, and the wire format is the player's, unchanged.

`LaptopLink` is the same interface with no robot (the laptop's speaker and
mic), so the whole conversation can be rehearsed at a desk.

Every paramiko call blocks, so each runs in a thread; nothing here holds the
event loop for longer than a numpy conversion.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import shlex
import struct
import threading
import time
from typing import Any, Callable, Optional

import numpy as np

from .. import laptop_mic

log = logging.getLogger("hub.group.robots")

SAMPLE_RATE = 16000            # robot speaker and mic rate, mono
MIC_BLOCK = 512                # samples per on_mic call (32 ms)

# How long after the last sample leaves the laptop until the robot's speaker
# is quiet. Not measured end to end (no robot online while this was written);
# summed from the code on both ends, then rounded up because the cost of being
# short is the robot's own tail reaching its mic as a "person":
#   SSH over the phone hotspot, laptop -> robot      ~30-100 ms (more in a burst)
#   player stdin read + queue hop to the SDK          ~5 ms
#   SDK GStreamer appsrc -> convert -> queue          ~10-20 ms
#   alsasink buffer-time (PLAYBACK_SINK_BUFFER_TIME_US = 50 ms, SDK 1.7.3)
#   XMOS echo-cancel chip + DAC                       ~10-20 ms
# = ~0.1-0.2 s. reachy_chat's opener uses a 0.5 s margin for the same wait
# (OPENER_PLAYBACK_MARGIN_S), measured from the laptop's first chunk.
PLAYBACK_LATENCY_S = 0.4

ROBOT_PYTHON = "/venvs/mini_daemon/bin/python"
PLAYER_PATH = "/home/pollen/scripts/robot_streaming_player.py"
PLAYER_COMMAND = "{} -u {}".format(ROBOT_PYTHON, PLAYER_PATH)
# Measured on reachy1-3, 2026-09-23 (reachy_wireless.py): ALSA dsnoop in
# ~/.asoundrc, mono 16 kHz, shared with the daemon.
MIC_DEVICE = "reachymini_audio_src"

CONNECT_TIMEOUT_S = 10.0
COMMAND_TIMEOUT_S = 20.0
# reachy_chat waits 30 s; the player measures ~4.8 s (SDK + emotion library).
READY_TIMEOUT_S = 30.0
# arecord on dsnoop gives data within ~100 ms. The Python recorder imports
# numpy + sounddevice first, which takes a second or two on the Pi.
ARECORD_START_S = 2.0
PYTHON_MIC_START_S = 8.0
OPEN_TIMEOUT_S = (CONNECT_TIMEOUT_S + COMMAND_TIMEOUT_S + READY_TIMEOUT_S
                  + ARECORD_START_S + PYTHON_MIC_START_S + 10.0)
CLOSE_WAIT_S = 3.0             # for the player to exit on EOF before pkill
# A send that cannot get SSH window for this long means the robot is gone;
# without it a WiFi drop mid-line would hang play() forever.
SEND_TIMEOUT_S = 5.0
POLL_S = 0.01                  # channel poll when idle (a mic block is 32 ms)

# 64 ms of audio per frame: the batch size reachy_chat ships (1024 samples
# at 16 kHz). Bursts are fine: the player's queue holds 256 frames (16 s) and
# its consumer pushes into a GStreamer appsrc that does not block (block=False
# is the default), so a whole line sent at once is drained into the robot's
# own buffer and played in order; nothing is dropped.
FRAME_SAMPLES = 1024
# The player shuts down on a motion payload above this (bad_motion_length).
MAX_MOTION_BYTES = 65536

# Wire protocol, see the top of robot_streaming_player.py (big-endian).
_HDR = struct.Struct(">I")
TURN_END_FRAME = _HDR.pack(0x00000000)
CLEAR_FRAME = _HDR.pack(0xFFFFFFFF)
MOTION_HEADER = _HDR.pack(0xFFFFFFFC)

ARECORD_COMMAND = "arecord -q -D {} -f S16_LE -r {} -c 1 -t raw".format(
    MIC_DEVICE, SAMPLE_RATE)
# The marker string is what close() and the next open() pkill by.
MIC_MARKER = "hub_group_mic"
# A byte on its stdin switches what it sends: b"0" nothing (it keeps reading
# the mic, so nothing piles up), b"1" the mic again. The people's own mic
# on the laptop keeps the robots' mics on "0" and switches them on in a
# moment when it fails or the page says so (2026-10-22). arecord has no such
# switch, so a robot whose mic must wait silently uses this one.
PYTHON_MIC_CODE = (
    'import sys, threading, sounddevice as sd\n'
    'MARK = "{mark}"\n'
    'live = [True]\n'
    'def ctl():\n'
    '    while True:\n'
    '        b = sys.stdin.buffer.read(1)\n'
    '        if not b:\n'
    '            return\n'
    '        live[0] = b == b"1"\n'
    'threading.Thread(target=ctl, daemon=True).start()\n'
    'ids = [i for i, d in enumerate(sd.query_devices())\n'
    '       if "{dev}" in d["name"] and d["max_input_channels"] > 0]\n'
    'if not ids:\n'
    '    sys.exit("no input device named {dev}")\n'
    'out = sys.stdout.buffer\n'
    'with sd.InputStream(device=ids[0], samplerate={rate}, channels=1,\n'
    '                    dtype="int16", blocksize={block}) as s:\n'
    '    while True:\n'
    '        a, _ = s.read({block})\n'
    '        if live[0]:\n'
    '            out.write(a.tobytes())\n'
    '            out.flush()\n'
).format(mark=MIC_MARKER, dev=MIC_DEVICE, rate=SAMPLE_RATE, block=MIC_BLOCK)
PYTHON_MIC_COMMAND = "{} -u -c {}".format(ROBOT_PYTHON, shlex.quote(PYTHON_MIC_CODE))

# The camera: the robot's daemon shares its frames on a unix socket (the IPC
# branch reachy_chat's vision.py reads, verified on reachy3 2026-10-05). This
# reader keeps the newest frame, two a second, as a 512x288 JPEG, and writes
# one ([4-byte length][jpeg], length 0 = none) for every line on its stdin, so
# a picture costs a few milliseconds and the WiFi carries only what is asked.
CAM_MARKER = "hub_group_cam"
CAMERA_CODE = (
    'import os, sys, struct, threading, time\n'
    'MARK = "hub_group_cam"\n'
    'SOCK = "/tmp/reachymini_camera_socket"\n'
    'latest = [None, 0.0]\n'
    'def run():\n'
    '    import gi\n'
    '    gi.require_version("Gst", "1.0")\n'
    '    gi.require_version("GstApp", "1.0")\n'
    '    from gi.repository import Gst\n'
    '    Gst.init(None)\n'
    '    while True:\n'
    '        if not os.path.exists(SOCK):\n'
    '            sys.stderr.write("no camera socket\\n"); sys.stderr.flush(); time.sleep(3); continue\n'
    '        pipe = Gst.parse_launch(\n'
    '            "unixfdsrc socket-path=%s ! queue name=gate leaky=downstream max-size-buffers=1 ! "\n'
    '            "videoconvert ! videoscale ! video/x-raw,width=512,height=288 ! jpegenc quality=80 ! "\n'
    '            "appsink name=sink drop=true max-buffers=1 sync=false" % SOCK)\n'
    '        last = [0.0]\n'
    '        def gate(_pad, _info):\n'
    '            now = time.monotonic()\n'
    '            if now - last[0] < 0.5:\n'
    '                return Gst.PadProbeReturn.DROP\n'
    '            last[0] = now\n'
    '            return Gst.PadProbeReturn.OK\n'
    '        pipe.get_by_name("gate").get_static_pad("src").add_probe(Gst.PadProbeType.BUFFER, gate)\n'
    '        sink = pipe.get_by_name("sink")\n'
    '        pipe.set_state(Gst.State.PLAYING)\n'
    '        got = time.monotonic()\n'
    '        try:\n'
    '            while True:\n'
    '                sample = sink.emit("try-pull-sample", 500000000)\n'
    '                if sample is None:\n'
    '                    if time.monotonic() - got > 4:\n'
    '                        break\n'
    '                    continue\n'
    '                got = time.monotonic()\n'
    '                buf = sample.get_buffer()\n'
    '                ok, info = buf.map(Gst.MapFlags.READ)\n'
    '                if ok:\n'
    '                    latest[0], latest[1] = bytes(info.data), got\n'
    '                    buf.unmap(info)\n'
    '        finally:\n'
    '            pipe.set_state(Gst.State.NULL)\n'
    '        time.sleep(1)\n'
    'threading.Thread(target=run, daemon=True).start()\n'
    'out = sys.stdout.buffer\n'
    'for _line in sys.stdin:\n'
    '    jpeg, t = latest\n'
    '    data = jpeg if (jpeg and time.monotonic() - t < 3) else b""\n'
    '    out.write(struct.pack(">I", len(data)) + data)\n'
    '    out.flush()\n'
)
CAMERA_COMMAND = "{} -u -c {}".format(ROBOT_PYTHON, shlex.quote(CAMERA_CODE))
SNAPSHOT_TIMEOUT_S = 1.5

# The `[l]` bracket trick is load-bearing (see _ssh_clear in
# hub/adapters/reachy_wireless.py): pkill -f matches whole command lines, and
# the shell running this command contains every needle in its own. As a regex
# "[r]obot_streaming_player" still matches the real process; as a literal
# string it does not match itself, so pkill does not kill its own shell.
_OURS = ("'[r]obot_streaming_player.py'",
         "'[a]record -q -D {}'".format(MIC_DEVICE),
         "'[{}]{}'".format(MIC_MARKER[0], MIC_MARKER[1:]),
         "'[{}]{}'".format(CAM_MARKER[0], CAM_MARKER[1:]))
# Two processes on the robot's audio fight, and it sounds like a broken mic:
# also clear the robot's own conversation app.
_LEFTOVERS = ("'[l]aptop_chat.py'",) + _OURS
CLEAR_LEFTOVERS_COMMAND = (
    " ; ".join("pkill -f {}".format(n) for n in _LEFTOVERS)
    + " ; sleep 1 ; pgrep -f '{}' | wc -l".format(
        "|".join(n.strip("'") for n in _LEFTOVERS)))
KILL_OURS_COMMAND = " ; ".join("pkill -f {}".format(n) for n in _OURS) + " ; true"


# --- pure helpers (tested without a robot) ----------------------------------

def encode_audio(samples: np.ndarray) -> list[tuple[bytes, int]]:
    """int16 mono samples -> [(frame bytes, sample count)], float32 payload."""
    frames = []
    for start in range(0, int(samples.size), FRAME_SAMPLES):
        part = samples[start:start + FRAME_SAMPLES]
        payload = (part.astype(np.float32) / 32768.0).astype("<f4").tobytes()
        frames.append((_HDR.pack(len(payload)) + payload, int(part.size)))
    return frames


def encode_motion(cmd: dict) -> bytes:
    """[0xFFFFFFFC][payload length][UTF-8 JSON], the player's motion frame."""
    payload = json.dumps(cmd, ensure_ascii=False).encode("utf-8")
    return MOTION_HEADER + _HDR.pack(len(payload)) + payload


def is_ready_line(line: str) -> bool:
    # The player logs "<ts> mono=.. INFO reachy.robot.player ready"; older
    # copies print a bare "ready". Same test as reachy_chat's drainer.
    return line == "ready" or line.endswith(" ready")


def is_exit_line(line: str) -> bool:
    return line == "exit" or line.endswith(" exit")


def arecord_missing(status: Optional[int], stderr_text: str) -> bool:
    """True when the shell could not find arecord at all (not a device error)."""
    text = stderr_text.lower()
    return status == 127 or "not found" in text or "no such file" in text


class LineSplitter:
    """Bytes in arbitrary chunks -> complete, non-empty text lines."""

    def __init__(self) -> None:
        self._buf = b""

    def feed(self, data: bytes) -> list[str]:
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        out = []
        for raw in lines:
            s = raw.decode("utf-8", "replace").rstrip()
            if s:
                out.append(s)
        return out


class BlockSplitter:
    """Raw int16 bytes in arbitrary chunks -> MIC_BLOCK-sample int16 arrays.

    SSH delivers whatever the window allows, so a read can end mid-block or
    even mid-sample; the remainder waits for the next read.
    """

    def __init__(self, block: int = MIC_BLOCK) -> None:
        self._nbytes = block * 2
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[np.ndarray]:
        self._buf += data
        blocks = []
        while len(self._buf) >= self._nbytes:
            chunk = bytes(self._buf[:self._nbytes])
            del self._buf[:self._nbytes]
            blocks.append(np.frombuffer(chunk, dtype="<i2").astype(np.int16))
        return blocks


def _why(exc: BaseException) -> str:
    name = type(exc).__name__
    if "Authentication" in name:
        return "the SSH password was refused"
    text = str(exc).strip()
    return text or name


def _new_ssh_client() -> Any:
    """One place to build the client, so the tests can swap in a fake."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    return client


def _pump(ch: Any, on_stdout: Callable[[bytes], None],
          on_stderr: Callable[[bytes], None]) -> Optional[int]:
    """Read a channel until its remote process exits or it is closed.

    Returns the exit status, or None when the channel closed without one.
    stdout and stderr are both drained even when one is not wanted: unread
    bytes hold the SSH window and would stall the remote process.
    """
    while True:
        busy = False
        if ch.recv_ready():
            data = ch.recv(65536)
            if data:
                on_stdout(data)
                busy = True
        if ch.recv_stderr_ready():
            data = ch.recv_stderr(65536)
            if data:
                on_stderr(data)
                busy = True
        if busy:
            continue
        if ch.exit_status_ready():
            # paramiko reports the exit before the last bytes are read.
            while ch.recv_ready():
                data = ch.recv(65536)
                if not data:
                    break
                on_stdout(data)
            while ch.recv_stderr_ready():
                data = ch.recv_stderr(65536)
                if not data:
                    break
                on_stderr(data)
            return ch.recv_exit_status()
        if ch.closed:
            return None
        time.sleep(POLL_S)


# --- the shared part: the "plays until" clock --------------------------------

class _Link:
    """What RobotLink and LaptopLink share: identity, errors, the play clock."""

    def __init__(self, key: str, name: str, listen: bool) -> None:
        self.key = key
        self.name = name
        self.listen = listen
        self.on_mic: Optional[Callable[[str, np.ndarray], None]] = None
        self.last_error = ""
        # time.monotonic() when everything sent so far has left the laptop's
        # account of the robot's speaker; 0 = nothing playing.
        self._play_until = 0.0
        self._carry = b""          # an odd byte from a TTS chunk split mid-sample
        self._mic_error_logged = False

    def _samples(self, pcm: bytes) -> np.ndarray:
        data = self._carry + bytes(pcm)
        if len(data) % 2:
            self._carry, data = data[-1:], data[:-1]
        else:
            self._carry = b""
        return np.frombuffer(data, dtype="<i2").astype(np.int16)

    def _account(self, n_samples: int, now: Optional[float] = None) -> None:
        """Audio was just sent: it plays after what is queued, or now if idle."""
        now = time.monotonic() if now is None else now
        self._play_until = max(now, self._play_until) + n_samples / SAMPLE_RATE

    def _reset_clock(self) -> None:
        self._play_until = 0.0
        self._carry = b""

    def _latency_s(self) -> float:
        return PLAYBACK_LATENCY_S

    def seconds_left(self, now: Optional[float] = None) -> float:
        """Seconds until the speaker is quiet (0 when nothing was sent)."""
        if self._play_until <= 0.0:
            return 0.0
        now = time.monotonic() if now is None else now
        return max(0.0, self._play_until + self._latency_s() - now)

    async def wait_done(self) -> None:
        """Returns when everything sent so far has finished playing.

        Re-reads the clock in short sleeps, so a stop_audio() meanwhile ends
        the wait at once.
        """
        while True:
            left = self.seconds_left()
            if left <= 0.0:
                return
            await asyncio.sleep(min(left, 0.05))

    def _deliver_mic(self, block: np.ndarray) -> None:
        callback = self.on_mic
        if callback is None:
            return
        try:
            callback(self.key, block)
        except Exception:  # noqa: BLE001 - a consumer bug must not kill the mic
            if not self._mic_error_logged:
                self._mic_error_logged = True
                log.exception("%s: on_mic raised; later errors are not logged",
                              self.name)


# --- a real robot -------------------------------------------------------------

class _MicStream:
    """One recorder on the robot (arecord or the Python fallback) and its reader."""

    def __init__(self, link: "RobotLink", kind: str, command: str) -> None:
        self.link = link
        self.kind = kind
        self.command = command
        self.started = threading.Event()      # first bytes arrived
        self.exited = threading.Event()
        self.status: Optional[int] = None
        self.adopted = False                  # the link kept this one
        self._stderr = collections.deque(maxlen=8)
        self._lines = LineSplitter()
        self._blocks = BlockSplitter()
        self.channel = link._open_channel(command)
        self._thread = threading.Thread(
            target=self._run, name="group-mic-{}".format(link.name), daemon=True)
        self._thread.start()

    @property
    def stderr_text(self) -> str:
        return " | ".join(self._stderr)

    def _on_stdout(self, data: bytes) -> None:
        self.started.set()
        for block in self._blocks.feed(data):
            self.link._deliver_mic(block)

    def _on_stderr(self, data: bytes) -> None:
        for line in self._lines.feed(data):
            self._stderr.append(line)
            log.debug("%s mic (%s): %s", self.link.name, self.kind, line)

    def _run(self) -> None:
        try:
            self.status = _pump(self.channel, self._on_stdout, self._on_stderr)
        except Exception as exc:  # noqa: BLE001
            self._stderr.append(_why(exc))
        finally:
            self.exited.set()
        if self.adopted and not self.link._closing:
            self.link.last_error = (
                "{}'s microphone stopped ({}). It can still speak, but it no "
                "longer hears the room.".format(self.link.name, self.failure()))
            log.warning("%s", self.link.last_error)

    def wait_started(self, timeout_s: float) -> str:
        """'data', 'exited' or 'silent' (still running, nothing yet)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.started.is_set():
                return "data"
            if self.exited.is_set():
                return "data" if self.started.is_set() else "exited"
            if self.link._closing:
                break
            time.sleep(POLL_S)
        return "data" if self.started.is_set() else "silent"

    def failure(self) -> str:
        parts = []
        if self.status is not None:
            parts.append("exit {}".format(self.status))
        if self._stderr:
            parts.append(self.stderr_text)
        return ", ".join(parts) or "no reason given"

    def close(self) -> None:
        try:
            self.channel.close()
        except Exception:  # noqa: BLE001
            pass
        self._thread.join(timeout=1.0)


class RobotLink(_Link):
    """One Reachy Mini: its speech player and, if `listen`, its microphone."""

    def __init__(self, key: str, name: str, host: str, user: str, password: str,
                 *, listen: bool = True, standby: bool = False) -> None:
        super().__init__(key, name, listen)
        # standby: the mic is started but sends nothing until set_mic_live(True)
        # (the people's own mic is in use; this one is its instant backup).
        self.mic_standby = standby
        self.mic_live = not standby
        self.host = host
        self.user = user
        self._password = password
        self.mic_source = ""       # "arecord" | "python" | "" (none)
        self._client: Any = None
        self._player: Any = None
        self._mic: Optional[_MicStream] = None
        self._ready = threading.Event()
        self._exited = threading.Event()
        self._stderr_tail: collections.deque = collections.deque(maxlen=12)
        self._closing = False
        self._send_lock = threading.Lock()     # one whole frame at a time
        self._play_lock: Optional[asyncio.Lock] = None   # play() calls in order
        self._gen = 0                          # bumped by stop_audio
        self._send_failed = False
        self._drainer: Optional[threading.Thread] = None
        self._cam: Any = None
        self._cam_lock = threading.Lock()
        self._cam_buf = bytearray()
        self._cam_err: collections.deque = collections.deque(maxlen=4)

    @property
    def connected(self) -> bool:
        ch = self._player
        try:
            return ch is not None and not ch.closed and not self._exited.is_set()
        except Exception:  # noqa: BLE001
            return False

    # ----- open / close -----

    async def open(self) -> None:
        """Clear leftovers on the robot, start the player (+ mic if listen)."""
        self._closing = False
        self.last_error = ""
        self._send_failed = False
        self._play_lock = asyncio.Lock()
        # Like adapters.base.thread_finishing_on_cancel, but `_closing` is set
        # first so the thread gives up at its next check instead of sitting
        # out the 30 s ready wait; then the close lands after it, in order.
        future = asyncio.ensure_future(asyncio.to_thread(self._open_sync))
        try:
            await asyncio.wait_for(asyncio.shield(future), OPEN_TIMEOUT_S)
        except asyncio.CancelledError:
            self._closing = True
            await asyncio.wait({future}, timeout=OPEN_TIMEOUT_S)
            await asyncio.to_thread(self._close_sync)
            raise
        except asyncio.TimeoutError:
            self.last_error = "{} did not finish starting within {:.0f} s.".format(
                self.name, OPEN_TIMEOUT_S)
            log.warning("%s", self.last_error)
            self._closing = True
            await asyncio.wait({future}, timeout=OPEN_TIMEOUT_S)
            await asyncio.to_thread(self._close_sync)
            raise RuntimeError(self.last_error) from None
        except Exception as exc:
            self.last_error = str(exc) if isinstance(exc, RuntimeError) else (
                "{} could not start: {}.".format(self.name, _why(exc)))
            log.warning("%s", self.last_error)
            self._closing = True
            await asyncio.to_thread(self._close_sync)
            raise RuntimeError(self.last_error) from exc

    def _open_sync(self) -> None:
        t0 = time.monotonic()
        client = _new_ssh_client()
        try:
            client.connect(self.host, username=self.user, password=self._password,
                           timeout=CONNECT_TIMEOUT_S, look_for_keys=False,
                           allow_agent=False)
        except Exception as exc:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
            raise RuntimeError("Could not connect to {} at {} over SSH ({}).".format(
                self.name, self.host, _why(exc))) from exc
        self._client = client
        self._clear_leftovers()
        if self._closing:
            raise RuntimeError("{}: start cancelled.".format(self.name))
        self._start_player()
        if self.listen and not self._closing:
            self._start_mic()
        if not self._closing:
            self._start_camera()
        log.info("%s: ready in %.1f s (mic: %s, camera: %s)", self.name,
                 time.monotonic() - t0, self.mic_source or "off",
                 "on" if self._cam is not None else "off")

    def _open_channel(self, command: str) -> Any:
        transport = self._client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("The SSH connection to {} dropped.".format(self.name))
        # paramiko's own default here is an hour.
        ch = transport.open_session(timeout=CONNECT_TIMEOUT_S)
        ch.exec_command(command)
        return ch

    def _run_quick(self, command: str, timeout_s: float) -> tuple[Optional[int], str]:
        ch = self._open_channel(command)
        out = bytearray()
        result: list[Optional[int]] = []
        reader = threading.Thread(
            target=lambda: result.append(_pump(ch, out.extend, lambda _b: None)),
            daemon=True)
        reader.start()
        reader.join(timeout_s)
        try:
            ch.close()
        except Exception:  # noqa: BLE001
            pass
        if reader.is_alive():
            raise TimeoutError("no answer within {:.0f} s".format(timeout_s))
        return (result[0] if result else None), out.decode("utf-8", "replace")

    def _clear_leftovers(self) -> None:
        try:
            _status, out = self._run_quick(CLEAR_LEFTOVERS_COMMAND, COMMAND_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: could not clear leftover audio processes (%s); a "
                        "leftover player would sound like a broken mic",
                        self.name, _why(exc))
            return
        lines = out.strip().splitlines()
        remaining = lines[-1].strip() if lines else "?"
        if remaining == "0":
            log.info("%s: cleared leftover audio processes", self.name)
        else:
            log.warning("%s: %s audio process(es) still running after the clear",
                        self.name, remaining)

    def _start_player(self) -> None:
        self._ready.clear()
        self._exited.clear()
        self._stderr_tail.clear()
        self._player = self._open_channel(PLAYER_COMMAND)
        self._player.settimeout(SEND_TIMEOUT_S)    # bounds sendall; recv only runs when ready
        self._drainer = threading.Thread(
            target=self._drain_player, args=(self._player,),
            name="group-player-{}".format(self.name), daemon=True)
        self._drainer.start()
        deadline = time.monotonic() + READY_TIMEOUT_S
        while not self._ready.wait(0.05):
            if self._exited.is_set():
                raise RuntimeError("{}'s speech player stopped before it was ready. "
                                   "{}".format(self.name, self._tail_sentence()))
            if self._closing:
                raise RuntimeError("{}: start cancelled.".format(self.name))
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "{}'s speech player did not say it was ready within {:.0f} s. "
                    "{}".format(self.name, READY_TIMEOUT_S, self._tail_sentence()))

    def _tail_sentence(self) -> str:
        if not self._stderr_tail:
            return "It printed nothing."
        tail = " | ".join(list(self._stderr_tail)[-4:])
        hint = ""
        if "No such file" in tail or "can't open file" in tail:
            hint = (" The player script may be missing: set the robot up with "
                    "reachy_chat's tools/deploy_robot_player.py.")
        return "Last thing it said: {}.{}".format(tail, hint)

    def _drain_player(self, ch: Any) -> None:
        lines = LineSplitter()

        def on_stderr(data: bytes) -> None:
            for s in lines.feed(data):
                self._stderr_tail.append(s)
                if is_ready_line(s):
                    log.info("%s player: %s", self.name, s)
                    self._ready.set()
                elif is_exit_line(s):
                    log.info("%s player: %s", self.name, s)
                    self._exited.set()
                elif any(w in s for w in ("WARNING", "ERROR", "CRITICAL", "Traceback")):
                    log.warning("%s player: %s", self.name, s)
                else:
                    log.debug("%s player: %s", self.name, s)

        status: Optional[int] = None
        try:
            status = _pump(ch, lambda _b: None, on_stderr)   # stdout is unused
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: reading the player failed: %s", self.name, _why(exc))
        finally:
            self._exited.set()
        if self._ready.is_set() and not self._closing:
            self.last_error = "{}'s speech player stopped (exit {}). {}".format(
                self.name, "unknown" if status is None else status,
                self._tail_sentence())
            log.warning("%s", self.last_error)

    def _start_mic(self) -> None:
        reasons = []
        order = [("arecord", ARECORD_COMMAND, ARECORD_START_S),
                 ("python", PYTHON_MIC_COMMAND, PYTHON_MIC_START_S)]
        if self.mic_standby:
            order.reverse()             # only the Python recorder can wait silently
        for kind, command, wait_s in order:
            if self._closing:
                return
            try:
                mic = _MicStream(self, kind, command)
            except Exception as exc:  # noqa: BLE001
                reasons.append("{}: {}".format(kind, _why(exc)))
                continue
            outcome = mic.wait_started(wait_s)
            if outcome != "exited":
                mic.adopted = True
                self._mic = mic
                self.mic_source = kind
                if not self.mic_live:
                    self._send_mic_switch(False)
                if outcome == "silent":
                    log.warning("%s: the %s recorder is running but sent no audio "
                                "in %.0f s", self.name, kind, wait_s)
                else:
                    log.info("%s: microphone streaming (%s)", self.name, kind)
                if mic.exited.is_set():
                    # Started, then died at once: let the reader's sentence stand.
                    self.last_error = "{}'s microphone stopped ({}).".format(
                        self.name, mic.failure())
                return
            mic.close()
            reasons.append("{}: {}".format(kind, mic.failure()))
            # Any early failure tries the Python recorder: it opens the device
            # through PortAudio, a different path, and costs a second or two.
            if kind == "arecord":
                if arecord_missing(mic.status, mic.stderr_text):
                    log.info("%s: arecord is not on the robot; using the Python "
                             "recorder", self.name)
                else:
                    log.warning("%s: arecord failed (%s); trying the Python recorder",
                                self.name, mic.failure())
        self.last_error = ("{}'s microphone did not start ({}). It can still speak, "
                           "but it will not hear the room.".format(
                               self.name, "; ".join(reasons)))
        log.warning("%s", self.last_error)

    def _send_mic_switch(self, live: bool) -> bool:
        mic = self._mic
        if mic is None or mic.kind != "python":
            return False
        try:
            mic.channel.send(b"1" if live else b"0")
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: could not switch the mic %s (%s)", self.name,
                        "on" if live else "off", _why(exc))
            return False

    async def set_mic_live(self, live: bool) -> bool:
        """Switch a standby mic on (or back to silent). True when the robot's
        mic now does what was asked (arecord cannot be silenced: it streams
        all along, and the hub ignores it until it is wanted)."""
        self.mic_live = live
        mic = self._mic
        if mic is None:
            return False
        if mic.kind != "python":
            return live
        return await asyncio.to_thread(self._send_mic_switch, live)

    # ----- camera -----

    def _start_camera(self) -> None:
        try:
            self._cam = self._open_channel(CAMERA_COMMAND)
            self._cam.settimeout(SNAPSHOT_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            self._cam = None
            log.warning("%s: camera reader did not start (%s); it cannot see", self.name, _why(exc))

    def _snapshot_sync(self) -> Optional[bytes]:
        ch = self._cam
        if ch is None or ch.closed:
            return None
        with self._cam_lock:
            try:
                while ch.recv_stderr_ready():
                    self._cam_err.append(ch.recv_stderr(4096).decode("utf-8", "replace").strip())
                ch.sendall(b"\n")
                deadline = time.monotonic() + SNAPSHOT_TIMEOUT_S
                buf = self._cam_buf
                while time.monotonic() < deadline:
                    if len(buf) >= 4:
                        n = struct.unpack(">I", bytes(buf[:4]))[0]
                        if len(buf) >= 4 + n:
                            data = bytes(buf[4:4 + n])
                            del buf[:4 + n]
                            return data or None
                    if ch.recv_ready():
                        buf += ch.recv(65536)
                    elif ch.exit_status_ready() or ch.closed:
                        log.warning("%s: camera reader stopped (%s)", self.name,
                                    " | ".join(self._cam_err) or "no reason given")
                        self._cam = None
                        return None
                    else:
                        time.sleep(0.005)
                # Late bytes of this frame would be read as the next header.
                self._cam = None
                try:
                    ch.close()
                except Exception:  # noqa: BLE001
                    pass
                log.warning("%s: no camera frame within %.1f s (%s); camera off for "
                            "this session", self.name, SNAPSHOT_TIMEOUT_S,
                            " | ".join(self._cam_err) or "no message")
                return None
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: camera snapshot failed: %s", self.name, _why(exc))
                return None

    async def snapshot(self) -> Optional[bytes]:
        """The newest camera frame as a JPEG (512x288), or None."""
        if self._cam is None:
            return None
        return await asyncio.to_thread(self._snapshot_sync)

    async def close(self) -> None:
        """Stop everything this link started on the robot."""
        self._closing = True
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        self._closing = True
        self._gen += 1             # a play() still in its thread stops sending
        player, mic, client = self._player, self._mic, self._client
        self._mic = None
        self.mic_source = ""
        if player is not None:
            # EOF on stdin is the player's clean exit: it leaves the SDK context.
            # Wait briefly for a frame in flight, so the EOF does not cut one.
            locked = self._send_lock.acquire(timeout=1.0)
            try:
                player.shutdown_write()
            except Exception:  # noqa: BLE001
                pass
            finally:
                if locked:
                    self._send_lock.release()
            deadline = time.monotonic() + CLOSE_WAIT_S
            try:
                while not player.exit_status_ready() and time.monotonic() < deadline:
                    time.sleep(0.05)
            except Exception:  # noqa: BLE001
                pass
        if mic is not None:
            mic.close()
        cam, self._cam = self._cam, None
        if cam is not None:
            try:
                cam.close()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            # Belt and braces: a player that missed the EOF, or a recorder that
            # never wrote again after its channel closed.
            try:
                self._run_quick(KILL_OURS_COMMAND, COMMAND_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: could not stop the audio processes on the robot "
                            "(%s); the next start clears them", self.name, _why(exc))
        if player is not None:
            try:
                player.close()
            except Exception:  # noqa: BLE001
                pass
        if client is not None:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
        if self._drainer is not None:
            self._drainer.join(timeout=1.0)
        self._player = None
        self._client = None
        self._reset_clock()
        log.info("%s: closed", self.name)

    # ----- speaking -----

    def _send(self, data: bytes) -> bool:
        """Blocking; one whole frame. False (logged once) when the robot is gone."""
        ch = self._player
        if ch is None:
            return False
        try:
            ch.sendall(data)
            return True
        except Exception as exc:  # noqa: BLE001
            if not self._send_failed:
                self._send_failed = True
                self.last_error = ("Lost the connection to {}'s speech player "
                                   "({}).".format(self.name, _why(exc)))
                log.warning("%s", self.last_error)
            return False

    def _send_audio(self, frames: list[tuple[bytes, int]], gen: int) -> None:
        for frame, n in frames:
            with self._send_lock:
                if gen != self._gen:
                    return          # stop_audio() came in: drop the rest
                if not self._send(frame):
                    return
                if gen == self._gen:
                    self._account(n)

    async def play(self, pcm: bytes) -> None:
        """int16 mono 16 kHz, any length (odd bytes carry over to the next call)."""
        gen = self._gen
        samples = self._samples(pcm)
        if samples.size == 0:
            return
        frames = encode_audio(samples)
        if self._play_lock is None:
            self._play_lock = asyncio.Lock()
        async with self._play_lock:
            await asyncio.to_thread(self._send_audio, frames, gen)

    async def end_line(self) -> None:
        """End-of-turn marker after the last chunk: the head stops swaying."""
        self._carry = b""
        if self._play_lock is None:
            self._play_lock = asyncio.Lock()
        async with self._play_lock:
            await asyncio.to_thread(self._send_frame, TURN_END_FRAME)

    async def stop_audio(self) -> None:
        """Cut playback now: queued frames here are dropped, the robot flushes."""
        self._gen += 1
        self._reset_clock()

        def clear() -> None:
            with self._send_lock:
                self._play_until = 0.0
                self._send(CLEAR_FRAME)

        await asyncio.to_thread(clear)

    async def motion(self, cmd: dict) -> None:
        """{"type":"head","direction":...}, {"type":"emotion","name":..}, {"type":"stop"}."""
        try:
            frame = encode_motion(cmd)
        except (TypeError, ValueError) as exc:
            log.warning("%s: motion %r is not JSON (%s); not sent", self.name, cmd, exc)
            return
        if len(frame) - 8 > MAX_MOTION_BYTES:
            log.warning("%s: motion command too long; not sent", self.name)
            return
        await asyncio.to_thread(self._send_frame, frame)

    def _send_frame(self, frame: bytes) -> None:
        with self._send_lock:
            self._send(frame)


# --- the laptop instead of a robot ----------------------------------------------

class _LaptopSpeaker:
    """The laptop's default output, shared by every LaptopLink.

    One buffer per link, mixed in the callback: stop_audio() on one link
    clears only its own audio. The stream is opened and stopped under
    `_life`, never under `_lock`, which the audio callback takes: some host
    APIs call the callback from inside start() or wait for it in stop().
    """

    def __init__(self) -> None:
        self._life = threading.Lock()
        self._lock = threading.Lock()
        self._bufs: dict[int, bytearray] = {}
        self._stream: Any = None
        self.latency_s = 0.1

    def acquire(self, link_id: int) -> None:
        with self._life:
            with self._lock:
                self._bufs.setdefault(link_id, bytearray())
            if self._stream is not None:
                return
            import sounddevice as sd

            try:
                with laptop_mic.PA_LOCK:
                    stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1,
                                             dtype="int16", callback=self._callback)
                    stream.start()
                    laptop_mic.stream_opened()
            except Exception:
                with self._lock:
                    self._bufs.pop(link_id, None)
                raise
            self._stream = stream
            try:
                self.latency_s = float(stream.latency)
            except (TypeError, ValueError, AttributeError):
                self.latency_s = 0.1

    def release(self, link_id: int) -> None:
        with self._life:
            with self._lock:
                self._bufs.pop(link_id, None)
                idle = not self._bufs
            if not idle or self._stream is None:
                return
            stream, self._stream = self._stream, None
            with laptop_mic.PA_LOCK:
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                laptop_mic.stream_closed()

    def push(self, link_id: int, data: bytes) -> None:
        with self._lock:
            buf = self._bufs.get(link_id)
            if buf is not None:
                buf += data

    def clear(self, link_id: int) -> None:
        with self._lock:
            buf = self._bufs.get(link_id)
            if buf is not None:
                buf.clear()

    def _callback(self, outdata: Any, frames: int, _time: Any, _status: Any) -> None:
        need = frames * 2
        mix = np.zeros(frames, dtype=np.int32)
        with self._lock:
            for buf in self._bufs.values():
                if not buf:
                    continue
                chunk = bytes(buf[:need])
                del buf[:need]
                part = np.frombuffer(chunk, dtype="<i2")
                mix[:part.size] += part
        np.clip(mix, -32768, 32767, out=mix)
        outdata[:, 0] = mix.astype(np.int16)


class _LaptopMic:
    """The laptop's default input, opened once and fanned out to listening links."""

    def __init__(self) -> None:
        self._life = threading.Lock()      # same split as _LaptopSpeaker
        self._lock = threading.Lock()
        self._links: dict[int, _Link] = {}
        self._stream: Any = None
        self._blocks = BlockSplitter()

    def subscribe(self, link: _Link) -> None:
        with self._life:
            if self._stream is None:
                import sounddevice as sd

                with self._lock:
                    self._blocks = BlockSplitter()
                with laptop_mic.PA_LOCK:
                    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                            dtype="int16", blocksize=MIC_BLOCK,
                                            callback=self._callback)
                    stream.start()
                    laptop_mic.stream_opened()
                self._stream = stream
            with self._lock:
                self._links[id(link)] = link

    def unsubscribe(self, link: _Link) -> None:
        with self._life:
            with self._lock:
                self._links.pop(id(link), None)
                idle = not self._links
            if not idle or self._stream is None:
                return
            stream, self._stream = self._stream, None
            with laptop_mic.PA_LOCK:
                try:
                    stream.stop()
                    stream.close()
                except Exception:  # noqa: BLE001
                    pass
                laptop_mic.stream_closed()

    def _callback(self, indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        # PortAudio reuses `indata`: copy before it leaves this call.
        data = np.asarray(indata[:, 0], dtype=np.int16).tobytes()
        with self._lock:
            links = list(self._links.values())
            blocks = self._blocks.feed(data)
        for block in blocks:
            for link in links:
                link._deliver_mic(block.copy())


_LAPTOP_SPEAKER = _LaptopSpeaker()
_LAPTOP_MIC = _LaptopMic()


# --- the people's own mic, on the laptop ---------------------------------------
# Tomer, 2026-10-22: for the 2026-10-26 demo the people are heard through a
# DJI Mic Mini, its receiver in the laptop's USB-C port and the mic on his
# boss's shirt, instead of the robots' mics (which hear the robots far louder
# than any person). Ears treats it as one more mic: it learns how loud each
# robot arrives there, so the person is heard over a talking robot too.

PEOPLE_MIC_KEY = "mic:people"
# The mic is "dead" (transmitter off, flat battery, out of range, unplugged)
# when its stream sends nothing for STALL_S, or only digital zeros for
# FLAT_S. A real room is never exactly zero; whether the DJI receiver sends
# zeros for a switched-off transmitter is to be checked in the lab on 10-26.
PEOPLE_MIC_STALL_S = 1.5
PEOPLE_MIC_FLAT_S = 6.0


def input_devices() -> list[dict]:
    """The laptop's microphones as the hub's watcher last saw them."""
    return laptop_mic.MIC_WATCH.devices or laptop_mic.list_inputs()


def find_people_mic(choice: str, devices: Optional[list[dict]] = None) -> Optional[dict]:
    """The device the "people_mic" setting means (laptop_mic.find)."""
    return laptop_mic.find(choice, input_devices() if devices is None else devices)


class PeopleMic:
    """One laptop input device -> 512-sample int16 16 kHz blocks for Ears.

    Opened at 16 kHz (Windows resamples, MME takes any rate); when the driver
    refuses, at the device's own rate with a linear resampler here. A stereo
    receiver (the DJI kit takes two transmitters, one per channel) gives the
    louder channel of each block. `health()` says whether it still hears."""

    def __init__(self, device: dict, on_mic: Callable[[str, np.ndarray], None]) -> None:
        self.device = device
        self.name = device["name"]
        self.on_mic = on_mic
        self._stream: Any = None
        self._blocks = BlockSplitter()
        self._rate = SAMPLE_RATE
        self._pos = 0.0                 # resampler: next output position in input samples
        self._tail = np.zeros(0, dtype=np.float32)
        self._error_logged = False
        self.opened_at = 0.0
        self.last_data = 0.0            # monotonic time of the last callback
        self.last_sound = 0.0           # ... of the last block that was not all zeros
        self.peak = 0                   # loudest sample since health() was last asked

    def open(self) -> None:
        import sounddevice as sd
        channels = max(1, min(2, int(self.device.get("channels") or 1)))
        last: Optional[BaseException] = None
        with laptop_mic.PA_LOCK:
            for rate in (SAMPLE_RATE, None):
                try:
                    if rate is None:
                        rate = int(sd.query_devices(self.device["index"])["default_samplerate"])
                    stream = sd.InputStream(device=self.device["index"], samplerate=rate,
                                            channels=channels, dtype="int16",
                                            blocksize=int(MIC_BLOCK * rate / SAMPLE_RATE),
                                            callback=self._callback)
                    stream.start()
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    continue
                self._rate = rate
                self._stream = stream
                laptop_mic.stream_opened()
                self.opened_at = self.last_data = self.last_sound = time.monotonic()
                log.info("people's mic: %s (%d Hz, %d ch)", self.name, rate, channels)
                return
        raise RuntimeError("the microphone {} could not be opened ({})".format(
            self.name, _why(last) if last else "?"))

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        with laptop_mic.PA_LOCK:
            try:
                stream.stop()
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            laptop_mic.stream_closed()

    def health(self, now: Optional[float] = None) -> str:
        """"ok", "flat" (only digital zeros for PEOPLE_MIC_FLAT_S), "stalled"
        (no data for PEOPLE_MIC_STALL_S) or "closed"."""
        now = time.monotonic() if now is None else now
        if self._stream is None:
            return "closed"
        if now - self.last_data > PEOPLE_MIC_STALL_S:
            return "stalled"
        if now - self.last_sound > PEOPLE_MIC_FLAT_S:
            return "flat"
        return "ok"

    def _mono(self, indata: Any) -> np.ndarray:
        x = np.asarray(indata, dtype=np.int16)
        if x.ndim == 1 or x.shape[1] == 1:
            return x.reshape(-1).astype(np.float32)
        energy = np.square(x.astype(np.float32)).mean(axis=0)
        return x[:, int(np.argmax(energy))].astype(np.float32)

    def _resample(self, x: np.ndarray) -> np.ndarray:
        if self._rate == SAMPLE_RATE:
            return x
        x = np.concatenate([self._tail, x])
        step = self._rate / SAMPLE_RATE
        pos = np.arange(self._pos, x.size - 1, step)
        y = np.interp(pos, np.arange(x.size), x) if pos.size else np.zeros(0, np.float32)
        nxt = self._pos + pos.size * step
        keep = int(nxt)                     # samples before the next position are done
        self._tail = x[keep:]
        self._pos = nxt - keep
        return y.astype(np.float32)

    def _callback(self, indata: Any, _frames: int, _time: Any, _status: Any) -> None:
        try:
            now = time.monotonic()
            self.last_data = now
            x = self._mono(indata)
            peak = int(np.abs(x).max()) if x.size else 0
            if peak > 0:
                self.last_sound = now
            self.peak = max(self.peak, peak)
            y = self._resample(x)
            data = np.clip(y, -32768, 32767).astype("<i2").tobytes()
            for block in self._blocks.feed(data):
                self.on_mic(PEOPLE_MIC_KEY, block)
        except Exception:  # noqa: BLE001 - a consumer bug must not kill the mic
            if not self._error_logged:
                self._error_logged = True
                log.exception("people's mic: a block failed; later errors are not logged")


class LaptopLink(_Link):
    """A robot that is only the laptop: same calls as RobotLink, no SSH.

    Several may exist at once (a simulated table); they share the laptop's
    speaker and mic. Motion is only logged.
    """

    def __init__(self, key: str, name: str, host: str = "", user: str = "",
                 password: str = "", *, listen: bool = True) -> None:
        super().__init__(key, name, listen)
        self.mic_source = ""
        self._open = False
        self._subscribed = False

    @property
    def connected(self) -> bool:
        return self._open

    def _latency_s(self) -> float:
        return _LAPTOP_SPEAKER.latency_s + 0.05

    async def open(self) -> None:
        self.last_error = ""
        try:
            await asyncio.to_thread(_LAPTOP_SPEAKER.acquire, id(self))
        except Exception as exc:
            self.last_error = "The laptop speaker could not be opened ({}).".format(_why(exc))
            raise RuntimeError(self.last_error) from exc
        self._open = True
        if self.listen:
            try:
                await asyncio.to_thread(_LAPTOP_MIC.subscribe, self)
                self._subscribed = True
                self.mic_source = "laptop"
            except Exception as exc:  # noqa: BLE001
                self.last_error = ("The laptop microphone could not be opened ({}). "
                                   "{} can still speak.".format(_why(exc), self.name))
                log.warning("%s", self.last_error)
        log.info("%s: simulated on the laptop (mic: %s)", self.name,
                 self.mic_source or "off")

    async def close(self) -> None:
        if self._subscribed:
            self._subscribed = False
            await asyncio.to_thread(_LAPTOP_MIC.unsubscribe, self)
        if self._open:
            self._open = False
            await asyncio.to_thread(_LAPTOP_SPEAKER.release, id(self))
        self.mic_source = ""
        self._reset_clock()

    async def play(self, pcm: bytes) -> None:
        samples = self._samples(pcm)
        if samples.size == 0 or not self._open:
            return
        _LAPTOP_SPEAKER.push(id(self), samples.astype("<i2").tobytes())
        self._account(int(samples.size))

    async def end_line(self) -> None:
        self._carry = b""

    async def set_mic_live(self, live: bool) -> bool:
        return self._subscribed or not live     # the laptop's mic simply stays on

    async def stop_audio(self) -> None:
        _LAPTOP_SPEAKER.clear(id(self))
        self._reset_clock()

    async def motion(self, cmd: dict) -> None:
        log.info("%s (laptop) motion: %s", self.name, json.dumps(cmd, ensure_ascii=False))

    async def snapshot(self) -> Optional[bytes]:
        """A still picture stands in for the camera: HUB_GROUP_TEST_IMAGE=<jpeg>."""
        import os
        path = os.environ.get("HUB_GROUP_TEST_IMAGE", "")
        if path and os.path.isfile(path):
            with open(path, "rb") as fh:
                return fh.read()
        return None
