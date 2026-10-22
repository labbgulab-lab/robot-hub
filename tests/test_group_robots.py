"""hub/group/robots.py without a robot, a network or an audio device.

SSH is a fake client whose channels answer by command, the way the robot
would: the player says "ready" on stderr, arecord streams raw bytes or is not
installed, and so on. sounddevice is a fake module for LaptopLink.
"""

from __future__ import annotations

import asyncio
import collections
import json
import re
import struct
import sys
import time
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.group import robots  # noqa: E402

READY_LINE = (b"2026-10-19 10:00:00,000 mono=1 INFO  reachy.robot.player "
              b"player.startup sdk_version=1.11 daemon_status=starting\n"
              b"2026-10-19 10:00:04,800 mono=2 INFO  reachy.robot.player rea")
READY_TAIL = b"dy\n"


# --- fakes ---------------------------------------------------------------------

class FakeChannel:
    def __init__(self, client: "FakeClient") -> None:
        self.client = client
        self.command = ""
        self.sent = bytearray()
        self.closed = False
        self.eof = False
        self.timeout = None
        self._out: collections.deque = collections.deque()
        self._err: collections.deque = collections.deque()
        self._status = None

    # paramiko.Channel surface used by robots.py
    def exec_command(self, command: str) -> None:
        self.command = command
        self.client.behave(self)

    def settimeout(self, t) -> None:
        self.timeout = t

    def recv_ready(self) -> bool:
        return bool(self._out)

    def recv_stderr_ready(self) -> bool:
        return bool(self._err)

    def recv(self, n: int) -> bytes:
        return self._pop(self._out, n)

    def recv_stderr(self, n: int) -> bytes:
        return self._pop(self._err, n)

    @staticmethod
    def _pop(q: collections.deque, n: int) -> bytes:
        if not q:
            return b""
        chunk = q.popleft()
        if len(chunk) > n:
            q.appendleft(chunk[n:])
            chunk = chunk[:n]
        return chunk

    def exit_status_ready(self) -> bool:
        return self._status is not None

    def recv_exit_status(self) -> int:
        return self._status

    def sendall(self, data: bytes) -> None:
        if self.closed or self.eof:
            raise OSError("Socket is closed")
        self.sent += data

    def shutdown_write(self) -> None:
        self.eof = True
        if self.command == robots.PLAYER_COMMAND:
            self._status = 0          # the player exits cleanly on EOF

    def close(self) -> None:
        self.closed = True

    # test helpers
    def out(self, *chunks: bytes) -> None:
        self._out.extend(chunks)

    def err(self, *chunks: bytes) -> None:
        self._err.extend(chunks)

    def exit(self, status: int) -> None:
        self._status = status


class FakeTransport:
    def __init__(self, client: "FakeClient") -> None:
        self.client = client

    def is_active(self) -> bool:
        return True

    def open_session(self, timeout=None) -> FakeChannel:
        ch = FakeChannel(self.client)
        self.client.channels.append(ch)
        return ch


MIC_BYTES = np.arange(1500, dtype="<i2").tobytes()   # 2 full blocks + 476 samples
MIC_CHUNKS = (MIC_BYTES[:301], MIC_BYTES[301:1300], MIC_BYTES[1300:])   # odd cuts


class FakeClient:
    def __init__(self, player="ready", arecord="stream", python="stream") -> None:
        self.player = player
        self.arecord = arecord
        self.python = python
        self.channels: list[FakeChannel] = []
        self.connect_kwargs: dict = {}
        self.closed = False

    def connect(self, host, **kwargs) -> None:
        self.connect_kwargs = dict(kwargs, host=host)

    def get_transport(self) -> FakeTransport:
        return FakeTransport(self)

    def close(self) -> None:
        self.closed = True

    def channel(self, command: str) -> FakeChannel:
        return next(c for c in self.channels if c.command == command)

    def behave(self, ch: FakeChannel) -> None:
        cmd = ch.command
        if cmd == robots.CLEAR_LEFTOVERS_COMMAND:
            ch.out(b"0\n")
            ch.exit(0)
        elif cmd == robots.KILL_OURS_COMMAND:
            ch.exit(0)
        elif cmd == robots.PLAYER_COMMAND:
            if self.player == "ready":
                ch.err(READY_LINE, READY_TAIL)
            elif self.player == "missing":
                ch.err(b"/venvs/mini_daemon/bin/python: can't open file "
                       b"'/home/pollen/scripts/robot_streaming_player.py': "
                       b"[Errno 2] No such file or directory\n")
                ch.exit(2)
        elif cmd == robots.ARECORD_COMMAND:
            self._mic(ch, self.arecord)
        elif cmd == robots.PYTHON_MIC_COMMAND:
            self._mic(ch, self.python)

    @staticmethod
    def _mic(ch: FakeChannel, how: str) -> None:
        if how == "stream":
            ch.out(*MIC_CHUNKS)
        elif how == "missing":
            ch.err(b"bash: line 1: arecord: command not found\n")
            ch.exit(127)
        elif how == "busy":
            ch.err(b"arecord: main:850: audio open error: Device or resource busy\n")
            ch.exit(1)
        elif how == "fail":
            ch.err(b"no input device named reachymini_audio_src\n")
            ch.exit(1)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(robots, "POLL_S", 0.001)
    monkeypatch.setattr(robots, "READY_TIMEOUT_S", 2.0)
    monkeypatch.setattr(robots, "ARECORD_START_S", 0.5)
    monkeypatch.setattr(robots, "PYTHON_MIC_START_S", 0.5)
    monkeypatch.setattr(robots, "CLOSE_WAIT_S", 0.2)


def _link(monkeypatch, client: FakeClient, listen=True) -> robots.RobotLink:
    monkeypatch.setattr(robots, "_new_ssh_client", lambda: client)
    return robots.RobotLink("reachy_wireless:abc", "reachy2", "172.20.10.2",
                            "pollen", "root", listen=listen)


def _bare_link() -> tuple[robots.RobotLink, FakeChannel]:
    """A link whose player channel is a fake, without going through open()."""
    link = robots.RobotLink("k", "reachy2", "h", "u", "p", listen=False)
    ch = FakeChannel(FakeClient())
    ch.command = robots.PLAYER_COMMAND
    link._player = ch
    return link, ch


def _frames(data: bytes) -> list[tuple[int, bytes]]:
    """Parse the player's wire format back into (header, payload) pairs."""
    out, i = [], 0
    while i < len(data):
        (n,) = struct.unpack(">I", data[i:i + 4])
        i += 4
        if n in (0, 0xFFFFFFFF):
            out.append((n, b""))
        elif n == 0xFFFFFFFC:
            (plen,) = struct.unpack(">I", data[i:i + 4])
            out.append((n, data[i + 4:i + 4 + plen]))
            i += 4 + plen
        else:
            out.append((n, data[i:i + n]))
            i += n
    return out


def _wait_for(cond, timeout=2.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "condition never came true"
        time.sleep(0.005)


# --- frames ----------------------------------------------------------------------

def test_play_sends_float32_frames_with_length_prefix():
    link, ch = _bare_link()
    pcm = np.full(1500, 16384, dtype="<i2").tobytes()     # 0.5 full scale
    asyncio.run(link.play(pcm))
    frames = _frames(bytes(ch.sent))
    assert [n for n, _ in frames] == [1024 * 4, 476 * 4]
    for _n, payload in frames:
        samples = np.frombuffer(payload, dtype="<f4")
        assert np.allclose(samples, 0.5)


def test_play_carries_an_odd_byte_to_the_next_chunk():
    link, ch = _bare_link()
    pcm = np.array([16384, -16384], dtype="<i2").tobytes()

    async def go():
        await link.play(pcm[:3])     # TTS chunk split mid-sample
        await link.play(pcm[3:])

    asyncio.run(go())
    frames = _frames(bytes(ch.sent))
    assert [n for n, _ in frames] == [4, 4]
    got = np.concatenate([np.frombuffer(p, dtype="<f4") for _n, p in frames])
    assert np.allclose(got, [0.5, -0.5])


def test_end_line_stop_and_motion_frames():
    link, ch = _bare_link()

    async def go():
        await link.end_line()
        await link.stop_audio()
        await link.motion({"type": "head", "direction": "left"})

    asyncio.run(go())
    data = bytes(ch.sent)
    assert data[:4] == b"\x00\x00\x00\x00"
    assert data[4:8] == b"\xff\xff\xff\xff"
    assert data[8:12] == b"\xff\xff\xff\xfc"
    (plen,) = struct.unpack(">I", data[12:16])
    assert json.loads(data[16:16 + plen]) == {"type": "head", "direction": "left"}
    assert len(data) == 16 + plen


def test_stop_audio_drops_the_rest_of_a_line_in_flight():
    link, ch = _bare_link()
    frames = robots.encode_audio(np.zeros(4096, dtype=np.int16))
    stale = link._gen
    asyncio.run(link.stop_audio())
    ch.sent.clear()
    link._send_audio(frames, stale)      # the old play() thread resumes
    assert bytes(ch.sent) == b""
    assert link.seconds_left() == 0.0


def test_motion_too_long_is_not_sent():
    link, ch = _bare_link()
    asyncio.run(link.motion({"type": "emotion", "name": "x" * 70000}))
    assert bytes(ch.sent) == b""


# --- the play clock -------------------------------------------------------------

def test_play_clock_queues_behind_audio_still_playing():
    link, _ch = _bare_link()
    lat = robots.PLAYBACK_LATENCY_S
    link._account(16000, now=100.0)                  # 1 s from idle
    assert link._play_until == pytest.approx(101.0)
    link._account(8000, now=100.2)                   # queued behind it
    assert link._play_until == pytest.approx(101.5)
    assert link.seconds_left(now=101.0) == pytest.approx(0.5 + lat)
    assert link.seconds_left(now=200.0) == 0.0
    link._account(1600, now=200.0)                   # idle again: from now
    assert link._play_until == pytest.approx(200.1)
    link._reset_clock()
    assert link.seconds_left(now=200.0) == 0.0


def test_wait_done_sleeps_until_audio_plus_latency(monkeypatch):
    monkeypatch.setattr(robots, "PLAYBACK_LATENCY_S", 0.05)
    link, _ch = _bare_link()

    t0 = time.monotonic()
    asyncio.run(link.wait_done())                    # nothing sent: at once
    assert time.monotonic() - t0 < 0.05

    asyncio.run(link.play(np.zeros(1600, dtype="<i2").tobytes()))   # 0.1 s
    t0 = time.monotonic()
    asyncio.run(link.wait_done())
    assert 0.1 <= time.monotonic() - t0 < 0.5


def test_stop_audio_ends_wait_done_early():
    link, _ch = _bare_link()

    async def go():
        await link.play(np.zeros(32000, dtype="<i2").tobytes())      # 2 s
        waiter = asyncio.ensure_future(link.wait_done())
        await asyncio.sleep(0.05)
        await link.stop_audio()
        await asyncio.wait_for(waiter, 0.5)

    asyncio.run(go())


# --- stderr / mic parsing -------------------------------------------------------

def test_ready_line_detection():
    assert robots.is_ready_line("ready")
    assert robots.is_ready_line(
        "2026-10-19 10:00:04,800 mono=2 INFO  reachy.robot.player ready")
    assert not robots.is_ready_line("loading the emotions library")
    assert robots.is_exit_line("2026-10-19 10:00:09,000 mono=3 INFO  x exit")


def test_line_splitter_handles_partial_reads():
    s = robots.LineSplitter()
    assert s.feed(b"first li") == []
    assert s.feed(b"ne\n\nsec") == ["first line"]
    assert s.feed(b"ond\r\n") == ["second"]


def test_mic_bytes_become_512_sample_blocks_across_partial_reads():
    s = robots.BlockSplitter()
    blocks = []
    for chunk in MIC_CHUNKS:
        blocks += s.feed(chunk)
    assert len(blocks) == 2
    assert all(b.dtype == np.int16 and b.shape == (512,) for b in blocks)
    assert np.array_equal(np.concatenate(blocks), np.arange(1024, dtype=np.int16))
    # the 476-sample remainder completes with the next read
    more = s.feed(np.arange(1500, 1536, dtype="<i2").tobytes())
    assert len(more) == 1 and np.array_equal(more[0], np.arange(1024, 1536))


def test_arecord_missing_decision():
    assert robots.arecord_missing(127, "")
    assert robots.arecord_missing(1, "sh: 1: arecord: not found")
    assert robots.arecord_missing(None, "bash: line 1: arecord: command not found")
    assert not robots.arecord_missing(
        1, "arecord: main:850: audio open error: Device or resource busy")


def test_cleanup_commands_never_match_their_own_shell():
    """The bracket trick from reachy_wireless._ssh_clear: pkill -f sees the
    shell's own command line, which holds every needle as literal text."""
    pattern = robots.CLEAR_LEFTOVERS_COMMAND.split("pgrep -f '")[1].split("'")[0]
    for needle in pattern.split("|"):
        assert re.search(needle, robots.CLEAR_LEFTOVERS_COMMAND) is None, needle
        assert re.search(needle, robots.KILL_OURS_COMMAND) is None, needle
    real = ["/venvs/mini_daemon/bin/python -u " + robots.PLAYER_PATH,
            robots.ARECORD_COMMAND, robots.PYTHON_MIC_COMMAND,
            "/venvs/mini_daemon/bin/python laptop_chat.py --local-robot"]
    for line in real:
        assert re.search(pattern, line), line


def test_python_recorder_compiles():
    compile(robots.PYTHON_MIC_CODE, "mic", "exec")


# --- open / close against the fake robot ----------------------------------------

def test_open_clears_starts_player_and_streams_mic(monkeypatch, fast):
    client = FakeClient()
    link = _link(monkeypatch, client)
    got = []
    link.on_mic = lambda key, block: got.append((key, block))

    async def go():
        await link.open()
        assert link.connected
        _wait_for(lambda: len(got) == 2)
        await link.play(np.zeros(100, dtype="<i2").tobytes())
        await link.close()

    asyncio.run(go())
    assert client.connect_kwargs["look_for_keys"] is False
    assert client.connect_kwargs["allow_agent"] is False
    assert client.channels[0].command == robots.CLEAR_LEFTOVERS_COMMAND
    player = client.channel(robots.PLAYER_COMMAND)
    assert player.timeout == robots.SEND_TIMEOUT_S
    assert _frames(bytes(player.sent)) == [(400, bytes(400))]
    assert player.eof and player.closed
    assert link.mic_source == "" and not link.connected
    assert {k for k, _b in got} == {"reachy_wireless:abc"}
    assert np.array_equal(np.concatenate([b for _k, b in got]),
                          np.arange(1024, dtype=np.int16))
    assert client.channel(robots.KILL_OURS_COMMAND)
    assert client.channel(robots.ARECORD_COMMAND).closed
    assert client.closed
    assert link.last_error == ""


def test_missing_arecord_falls_back_to_python_recorder(monkeypatch, fast):
    client = FakeClient(arecord="missing")
    link = _link(monkeypatch, client)
    got = []
    link.on_mic = lambda key, block: got.append(block)

    async def go():
        await link.open()
        assert link.mic_source == "python"
        _wait_for(lambda: len(got) == 2)
        await link.close()

    asyncio.run(go())
    commands = [c.command for c in client.channels]
    assert commands.index(robots.ARECORD_COMMAND) < commands.index(robots.PYTHON_MIC_COMMAND)
    assert link.last_error == ""


def test_mic_failure_still_lets_the_robot_speak(monkeypatch, fast):
    client = FakeClient(arecord="busy", python="fail")
    link = _link(monkeypatch, client)

    async def go():
        await link.open()                     # no raise: speech still works
        await link.play(np.zeros(10, dtype="<i2").tobytes())
        await link.close()

    asyncio.run(go())
    assert "microphone did not start" in link.last_error
    assert "Device or resource busy" in link.last_error
    assert _frames(bytes(client.channel(robots.PLAYER_COMMAND).sent)) == [(40, bytes(40))]


def test_listen_false_starts_no_recorder(monkeypatch, fast):
    client = FakeClient()
    link = _link(monkeypatch, client, listen=False)

    async def go():
        await link.open()
        await link.close()

    asyncio.run(go())
    commands = [c.command for c in client.channels]
    assert robots.ARECORD_COMMAND not in commands
    assert robots.PYTHON_MIC_COMMAND not in commands


def test_missing_player_is_a_readable_error(monkeypatch, fast):
    client = FakeClient(player="missing")
    link = _link(monkeypatch, client)
    with pytest.raises(RuntimeError) as err:
        asyncio.run(link.open())
    text = str(err.value)
    assert text.startswith("reachy2's speech player stopped before it was ready")
    assert "deploy_robot_player.py" in text
    assert link.last_error == text
    assert not link.connected
    assert client.closed


def test_player_that_never_says_ready_times_out(monkeypatch, fast):
    monkeypatch.setattr(robots, "READY_TIMEOUT_S", 0.2)
    client = FakeClient(player="silent")
    link = _link(monkeypatch, client)
    with pytest.raises(RuntimeError, match="did not say it was ready within"):
        asyncio.run(link.open())


def test_unreachable_robot_is_a_readable_error(monkeypatch, fast):
    client = FakeClient()

    def refuse(host, **kw):
        raise TimeoutError("timed out")

    client.connect = refuse
    link = _link(monkeypatch, client)
    with pytest.raises(RuntimeError, match=r"Could not connect to reachy2 at "
                                           r"172\.20\.10\.2 over SSH \(timed out\)"):
        asyncio.run(link.open())


def test_lost_connection_mid_line_does_not_raise(monkeypatch, fast):
    link, ch = _bare_link()
    ch.closed = True
    asyncio.run(link.play(np.zeros(100, dtype="<i2").tobytes()))
    assert "Lost the connection to reachy2" in link.last_error
    assert link.seconds_left() == 0.0


# --- LaptopLink ------------------------------------------------------------------

class _FakeStream:
    def __init__(self, kind, **kw) -> None:
        self.kind = kind
        self.kw = kw
        self.callback = kw["callback"]
        self.latency = 0.08
        self.started = self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        pass


@pytest.fixture
def fake_sd(monkeypatch):
    made = []
    sd = types.ModuleType("sounddevice")
    sd.OutputStream = lambda **kw: made.append(_FakeStream("out", **kw)) or made[-1]
    sd.InputStream = lambda **kw: made.append(_FakeStream("in", **kw)) or made[-1]
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(robots, "_LAPTOP_SPEAKER", robots._LaptopSpeaker())
    monkeypatch.setattr(robots, "_LAPTOP_MIC", robots._LaptopMic())
    return made


def test_laptop_links_share_one_speaker_and_one_mic(fake_sd):
    a = robots.LaptopLink("sim:a", "Noa")
    b = robots.LaptopLink("sim:b", "Dan")
    deaf = robots.LaptopLink("sim:c", "Eli", listen=False)
    heard = collections.defaultdict(list)
    for link in (a, b, deaf):
        link.on_mic = lambda key, block: heard[key].append(block)

    async def go():
        for link in (a, b, deaf):
            await link.open()
        assert [s.kind for s in fake_sd] == ["out", "in"]
        out, mic = fake_sd

        await a.play(np.full(4, 1000, dtype="<i2").tobytes())
        await b.play(np.full(2, 500, dtype="<i2").tobytes())
        buf = np.zeros((4, 1), dtype=np.int16)
        out.callback(buf, 4, None, None)
        assert buf[:, 0].tolist() == [1500, 1500, 1000, 1000]   # mixed

        await a.play(np.full(4, 7, dtype="<i2").tobytes())
        await a.stop_audio()                                     # only a's audio
        await b.play(np.full(2, 3, dtype="<i2").tobytes())
        out.callback(buf, 4, None, None)
        assert buf[:, 0].tolist() == [3, 3, 0, 0]
        assert a.seconds_left() == 0.0 and b.seconds_left() > 0.0

        mic.callback(np.arange(512, dtype=np.int16).reshape(-1, 1), 512, None, None)
        await a.motion({"type": "head", "direction": "left"})   # logged only
        for link in (a, b, deaf):
            await link.close()
        assert out.stopped and mic.stopped

    asyncio.run(go())
    assert set(heard) == {"sim:a", "sim:b"}
    assert all(np.array_equal(v[0], np.arange(512)) for v in heard.values())
