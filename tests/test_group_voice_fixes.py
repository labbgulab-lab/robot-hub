"""Group conversation fixes after the 2026-10-21 lab runs (2026-10-22).

- ElevenLabs MP3 is played as it arrives (it used to wait for the whole clip).
- At most 3 ElevenLabs requests at once; the interjection warm-up waits for
  the live lines, and only one warm-up runs.
- One refused or busy line no longer drops ElevenLabs for the session.
- Robot lines reach the log once spoken, with latency, cut and voice timings.
- The people's own mic on the laptop (a DJI Mic Mini for the 10-26 demo).
"""

import asyncio
import io
import json

import httpx
import numpy as np
import soundfile as sf

from hub.group import conductor as c
from hub.group import robots
from hub.group import services as sv
from hub.group.services import ElevenGate, ServiceError, Services, StreamDecoder, eleven_gone


def mp3_clip(seconds=3.0, rate=22050):
    t = np.arange(int(rate * seconds)) / rate
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, x, rate, format="MP3", subtype="MPEG_LAYER_III")
    return buf.getvalue()


# ------------------------------------------------------------ MP3 streaming
def test_mp3_is_decoded_while_it_arrives_and_matches_the_whole_clip():
    data = mp3_clip()
    dec = StreamDecoder()
    out, first_at = [], None
    for i in range(0, len(data), 700):
        pcm = dec.feed(data[i:i + 700])
        if pcm and first_at is None:
            first_at = i + 700
        out.append(pcm)
    out.append(dec.finish())
    streamed = np.frombuffer(b"".join(out), dtype=np.int16).astype(np.float32)
    whole = np.frombuffer(sv.decode_to_16k(data), dtype=np.int16).astype(np.float32)
    # Sound leaves long before the last byte arrived.
    assert first_at is not None and first_at < len(data) / 3
    assert abs(streamed.size - whole.size) <= 2
    n = min(streamed.size, whole.size)
    assert np.corrcoef(streamed[:n], whole[:n])[0, 1] > 0.99


def test_mp3_decoder_waits_for_a_whole_frame():
    dec = StreamDecoder()
    assert dec.feed(b"\xff\xfb" + b"\x00" * 10) == b""


# ------------------------------------------------------------ the gate
def test_live_lines_take_three_slots_and_the_warm_up_waits_for_them():
    async def run():
        gate = ElevenGate(3)
        order = []
        for _ in range(3):
            await gate.acquire(False)
        fourth = asyncio.ensure_future(gate.acquire(False))
        warm = asyncio.ensure_future(gate.acquire(True))
        await asyncio.sleep(0.01)
        assert not fourth.done() and not warm.done()
        gate.release(False)
        await asyncio.sleep(0.01)
        assert fourth.done() and not warm.done()        # live first
        for _ in range(3):
            gate.release(False)
        await asyncio.sleep(0.01)
        assert warm.done() and gate.busy == 1
        # A live line may still start beside the one warm-up request.
        await asyncio.wait_for(gate.acquire(False), 0.1)
        order.append("ok")
        return order
    assert asyncio.run(run()) == ["ok"]


def test_a_cancelled_wait_gives_its_place_back():
    async def run():
        gate = ElevenGate(1)
        await gate.acquire(False)
        waiting = asyncio.ensure_future(gate.acquire(False))
        await asyncio.sleep(0.01)
        waiting.cancel()
        await asyncio.sleep(0.01)
        gate.release(False)
        assert gate.live == 0 and gate.busy == 0
        await asyncio.wait_for(gate.acquire(True), 0.1)
    asyncio.run(run())


# ------------------------------------------------------------ refusals
def test_only_a_refusal_for_good_drops_elevenlabs():
    busy = '{"detail":{"code":"concurrent_limit_exceeded","message":"Too many concurrent requests"}}'
    assert not eleven_gone(ServiceError("x", 429, busy))
    assert not eleven_gone(ServiceError("x", 500, "oops"))
    assert not eleven_gone(ServiceError("x", 0, ""))
    assert eleven_gone(ServiceError("x", 401, "invalid api key"))
    assert eleven_gone(ServiceError("x", 401, '{"detail":{"status":"quota_exceeded"}}'))
    assert eleven_gone(ServiceError("x", 429, "system busy, too many requests"))


def test_speech_waits_out_too_many_requests_at_once(monkeypatch):
    data = mp3_clip(1.0)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(429, text='{"detail":{"code":"concurrent_limit_exceeded"}}')
        return httpx.Response(200, content=data)

    monkeypatch.setattr(sv, "ELEVEN_BUSY_WAITS", (0.01, 0.01))

    async def run():
        s = Services("", "e")
        s.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        pcm = b"".join([c async for c in s.speech("V", "hello")])
        assert s.eleven_gate.busy == 0 and s.eleven_gate.live == 0
        return pcm
    assert len(asyncio.run(run())) > 16000 and len(calls) == 2


def session(seats, note=None):
    class M:
        eleven_credits = None

        def note(self, text):
            (note if note is not None else []).append(text)
    services = Services("", "e", gemini_key="", openrouter_key="r")
    services.openai_ok = False
    return c.Session(M(), seats, {"voice_provider": "elevenlabs"}, services)


def test_on_auto_one_busy_line_gets_a_stand_in_and_elevenlabs_stays(monkeypatch):
    seat = {"key": "a", "name": "r1", "character": "Dor", "voice_provider": "auto",
            "voice_id": "X"}
    notes = []
    s = session([seat], notes)

    async def refused(voice, text, background=False):
        raise ServiceError("ElevenLabs answered 503: busy", 503, "busy")
        yield b""

    async def stand_in(*a, **k):
        yield b"\x01\x00" * 800
    s.services.speech = refused
    monkeypatch.setattr(c, "openrouter_speech", stand_in)

    async def run():
        line = c.Line(seat=seat, move="", text="hi", final=False, nudge="", director_s=1.2)
        await s.voice(line)
        return line
    line = asyncio.run(run())
    assert line.audio.chunks and line.audio.error is None
    assert s.eleven_down is False and line.voice_used == "OpenRouter"
    assert not notes
    assert s.voice_backend(seat) == "eleven"


def test_on_auto_a_refusal_for_good_moves_the_session_and_says_where(monkeypatch):
    seat = {"key": "a", "name": "r1", "character": "Dor", "voice_provider": "auto",
            "voice_id": "X"}
    notes = []
    s = session([seat], notes)

    async def refused(voice, text, background=False):
        raise ServiceError("ElevenLabs answered 401: bad key", 401, "invalid_api_key")
        yield b""

    async def stand_in(*a, **k):
        yield b"\x01\x00" * 800
    s.services.speech = refused
    monkeypatch.setattr(c, "openrouter_speech", stand_in)

    async def run():
        line = c.Line(seat=seat, move="", text="hi", final=False, nudge="", director_s=0.0)
        await s.voice(line)
    asyncio.run(run())
    assert s.eleven_down is True
    # It names the voices the robots really move to (it said "OpenAI" on
    # 2026-10-21, with OpenAI out of credits).
    assert notes and "OpenRouter voices" in notes[0]


LOCKED = {"key": "a", "name": "r1", "character": "Dor", "voice_provider": "elevenlabs",
          "voice_id": "X"}


def locked_run(monkeypatch, speech):
    notes = []
    s = session([dict(LOCKED)], notes)
    s.services.speech = speech
    used = []

    async def stand_in(*a, **k):
        used.append("other")
        yield b"\x01\x00" * 800
    monkeypatch.setattr(c, "openrouter_speech", stand_in)
    monkeypatch.setattr(c, "openai_speech", stand_in)
    monkeypatch.setattr(c, "gemini_speech", stand_in)
    monkeypatch.setattr(c, "ELEVEN_HEDGE_S", 0.05)
    monkeypatch.setattr(c, "FIRST_AUDIO_S", 0.2)

    async def run():
        line = c.Line(seat=s.seats[0], move="", text="hi", final=False, nudge="", director_s=0)
        await s.voice(line)
        return line
    return s, asyncio.run(run()), notes, used


def test_elevenlabs_robot_retries_its_own_voice_and_never_swaps(monkeypatch):
    calls = []

    async def flaky(voice, text, background=False):
        calls.append(voice)
        if len(calls) < 3:
            raise ServiceError("ElevenLabs answered 503: busy", 503, "busy")
        yield b"\x02\x00" * 800
    s, line, notes, used = locked_run(monkeypatch, flaky)
    assert line.audio.chunks and line.audio.error is None and not used
    assert set(calls) == {"X"} and line.voice_used == "ElevenLabs"


def test_elevenlabs_robot_skips_a_line_rather_than_change_voice(monkeypatch):
    async def down(voice, text, background=False):
        raise ServiceError("ElevenLabs answered 401: bad key", 401, "invalid_api_key")
        yield b""
    s, line, notes, used = locked_run(monkeypatch, down)
    assert not line.audio.chunks and line.audio.error and not used
    assert s.voice_backend(s.seats[0]) == "eleven"
    assert notes and "never swapped" in notes[0]


# ------------------------------------------------------------ playback pace
def test_playback_waits_until_the_download_can_keep_up():
    a = c.Audio()
    a.chunks, a.first_at = [b"\x00" * 16000], 100.0        # 0.5 s of audio in 1 s
    # 6 s line arriving at half speed: needs ~5.5 * (2 - 1) * 1.25 buffered.
    assert not a.can_start(6.0, now=101.0)
    a.chunks = [b"\x00" * 32000 * 4]                        # 4 s in 1 s: fast
    assert a.can_start(6.0, now=101.0)
    a.chunks = [b"\x00" * 16000]
    assert a.can_start(0.6, now=101.0)                      # almost all of it is in
    a.done = True
    assert a.can_start(60.0, now=101.0)


def test_playback_needs_a_second_before_the_rate_is_known():
    a = c.Audio()
    a.chunks, a.first_at = [b"\x00" * 16000], 100.0
    assert not a.can_start(5.0, now=100.1)
    a.chunks = [b"\x00" * 32000]
    assert a.can_start(5.0, now=100.1)
    # An interjection already playing in front counts.
    a.chunks = [b"\x00" * 16000]
    assert a.can_start(5.0, head_s=0.6, now=100.1)


# ------------------------------------------------------------ male voices
def test_only_male_voices_are_offered(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)
    opts = gm.state()["voice_options"]
    labels = [o["label"] for lst in opts.values() for o in lst]
    assert labels and all("(male" in l for l in labels)


# ------------------------------------------------------------ the log
def test_robot_lines_are_logged_once_spoken_with_their_timings(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)
    gm._log_path = tmp_path / "group.jsonl"
    human = {"id": 1, "kind": "human", "text": "hi"}
    robot = {"id": 2, "kind": "robot", "text": "hello", "latency_ms": None, "cut": False}
    gm.log_turn(human)
    gm.log_turn(robot, hold=True)
    assert len(gm._log_path.read_text(encoding="utf-8").splitlines()) == 1
    robot["latency_ms"] = 640
    robot["cut"] = True
    gm.log_turn(robot)
    gm.flush_log()                      # already written: not again
    rows = [json.loads(l) for l in gm._log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[1]["latency_ms"] == 640 and rows[1]["cut"] is True


def test_a_stop_writes_the_lines_it_cut_short(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)
    gm._log_path = tmp_path / "group.jsonl"
    gm.log_turn({"id": 3, "kind": "robot", "text": "b"}, hold=True)
    gm.log_turn({"id": 2, "kind": "robot", "text": "a"}, hold=True)
    asyncio.run(gm._stop_conversation())
    rows = [json.loads(l) for l in gm._log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == [2, 3]


def test_finish_entry_adds_writer_and_voice_timings():
    seat = {"key": "a", "name": "r1", "character": "Dor"}
    logged = []

    class M:
        def log_turn(self, entry, hold=False):
            logged.append(dict(entry))
    convo = c.Conversation.__new__(c.Conversation)
    convo.m = M()
    line = c.Line(seat=seat, move="", text="hi", final=False, nudge="", director_s=1.25)
    line.voice_used, line.voice_t0 = "ElevenLabs", 100.0
    line.audio.first_at = 100.4
    convo.finish_entry(line, {"id": 1, "kind": "robot"})
    assert logged == [{"id": 1, "kind": "robot", "writer_ms": 1250, "voice": "ElevenLabs",
                       "voice_first_ms": 400}]


# ------------------------------------------------------------ the people's mic
DEVICES = [{"index": 1, "name": "Microphone Array (Intel Smart", "channels": 4},
           {"index": 7, "name": "Microphone (DJI MIC MINI)", "channels": 2}]


def test_auto_finds_the_dji_mic_and_names_match():
    assert robots.find_people_mic("auto", DEVICES)["index"] == 7
    assert robots.find_people_mic("auto", DEVICES[:1]) is None
    assert robots.find_people_mic("robots", DEVICES) is None
    assert robots.find_people_mic("", DEVICES) is None
    assert robots.find_people_mic("Microphone Array (Intel Smart", DEVICES)["index"] == 1
    assert robots.find_people_mic("dji mic", DEVICES)["index"] == 7
    assert robots.find_people_mic("Yeti", DEVICES) is None


def test_people_mic_resamples_to_16k_blocks_and_takes_the_louder_channel():
    got = []
    mic = robots.PeopleMic(DEVICES[1], lambda key, block: got.append((key, block)))
    mic._rate = 48000
    t = np.arange(48000) / 48000
    loud = (8000 * np.sin(2 * np.pi * 300 * t)).astype(np.int16)
    quiet = (loud // 50).astype(np.int16)
    stereo = np.stack([quiet, loud], axis=1)
    for i in range(0, 48000, 1536):            # one second in driver-sized pieces
        mic._callback(stereo[i:i + 1536], 1536, None, None)
    assert got and all(k == robots.PEOPLE_MIC_KEY and b.size == 512 for k, b in got)
    samples = sum(b.size for _, b in got)
    assert 16000 - 1024 <= samples <= 16000
    y = np.concatenate([b for _, b in got]).astype(np.float32)
    assert np.sqrt(np.mean(y * y)) > 4000          # the loud channel, not the quiet one


def test_the_mic_choice_reconnects_the_robots():
    seats = [{"key": "a", "listen": True}]
    assert (c.Session.make_signature(seats, {"people_mic": "auto"})
            != c.Session.make_signature(seats, {"people_mic": "robots"}))
    assert (c.Session.make_signature(seats, {})
            == c.Session.make_signature(seats, {"people_mic": "auto"}))


def test_people_mic_setting_is_saved_and_cleaned(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)
    assert gm.cfg["settings"]["people_mic"] == "auto"
    gm.save_config({"settings": {"people_mic": "  Microphone (DJI MIC MINI) "}})
    assert gm.cfg["settings"]["people_mic"] == "Microphone (DJI MIC MINI)"
    gm.save_config({"settings": {"people_mic": ""}})
    assert gm.cfg["settings"]["people_mic"] == "auto"
