"""Demo readiness (Tomer, 2026-10-22, for the 2026-10-26 demo).

- The hub finds the DJI mic itself; the group conversation and reachy_chat
  start with it. The robots' mics wait silently behind it, and one button
  (or the DJI going dead or away) switches to them at once.
- Every service is checked with a real request before Start, and the first
  line of each mode is made ahead, so Start speaks at once.
"""

import asyncio
import time

import numpy as np

from hub import laptop_mic
from hub.group import conductor as c
from hub.group import robots
from hub.group.ears import Ears

DJI = {"index": 7, "name": "Microphone (DJI MIC MINI)", "channels": 2}
BUILTIN = {"index": 1, "name": "Microphone Array (Intel Smart", "channels": 4}


class FakeVAD:
    def prob(self, block):
        return 1.0 if np.abs(block).max() > 1000 else 0.0

    def reset(self):
        pass


def voice(level=8000):
    t = np.arange(512) / 16000
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


# ------------------------------------------------------------ the watcher
def test_watcher_finds_the_dji_and_reports_changes(monkeypatch):
    seen = []
    lists = [[BUILTIN], [BUILTIN, DJI], [BUILTIN]]
    monkeypatch.setattr(laptop_mic, "list_inputs", lambda refresh=False: lists.pop(0))
    w = laptop_mic.MicWatch()
    w.on_change = seen.append
    w.scan()
    assert w.dji() is None
    w.scan()
    assert w.dji()["name"] == DJI["name"] and w.find("auto")["index"] == 7
    w.scan()
    assert seen == [DJI, None]          # plugged in, then gone (no call for "still none")


def test_portaudio_is_not_restarted_under_an_open_stream(monkeypatch):
    calls = []

    class SD:
        def _terminate(self):
            calls.append("terminate")

        def _initialize(self):
            calls.append("init")

        def query_devices(self):
            return []

        def query_hostapis(self):
            return [{"name": "MME"}]
    import sys
    monkeypatch.setitem(sys.modules, "sounddevice", SD())
    laptop_mic.stream_opened()
    try:
        laptop_mic.list_inputs(refresh=True)
        assert calls == []
    finally:
        laptop_mic.stream_closed()
    laptop_mic.list_inputs(refresh=True)
    assert calls == ["terminate", "init"]


# ------------------------------------------------------------ mic health
def test_people_mic_health_reads_stalls_and_flat_silence():
    mic = robots.PeopleMic(DJI, lambda k, b: None)
    assert mic.health() == "closed"
    mic._stream = object()
    now = time.monotonic()
    mic.last_data = mic.last_sound = now
    assert mic.health(now) == "ok"
    mic._callback(np.zeros((512, 2), np.int16), 512, None, None)
    mic.last_sound = now                          # zeros do not count as sound
    mic.last_data = now + robots.PEOPLE_MIC_FLAT_S - 1.2   # data keeps coming, all zeros
    assert mic.health(now + robots.PEOPLE_MIC_FLAT_S - 1) == "ok"
    mic.last_data = now + robots.PEOPLE_MIC_FLAT_S + 0.5
    assert mic.health(now + robots.PEOPLE_MIC_FLAT_S + 1) == "flat"
    assert mic.health(now + robots.PEOPLE_MIC_FLAT_S + 0.6 + robots.PEOPLE_MIC_STALL_S) == "stalled"


# ------------------------------------------------------------ ears switch
def test_ears_hear_only_the_active_mics_and_switch_at_once():
    ears = Ears(["r1", "r2", robots.PEOPLE_MIC_KEY], vad_factory=FakeVAD)
    ears.set_open(True)
    ears.set_active([robots.PEOPLE_MIC_KEY])
    for _ in range(5):
        ears.feed("r1", voice())
    assert not ears.capturing                      # a robot's mic is not heard
    assert ears.levels["r1"] > 0                   # but its level still shows
    for _ in range(5):
        ears.feed(robots.PEOPLE_MIC_KEY, voice())
    assert ears.capturing
    ears.set_active(["r1", "r2"])                  # the button
    assert not ears.capturing
    for _ in range(5):
        ears.feed(robots.PEOPLE_MIC_KEY, voice())
    assert not ears.capturing
    for _ in range(5):
        ears.feed("r2", voice())
    assert ears.capturing and ears.best_key() == "r2"


# ------------------------------------------------------------ session switch
class FakeLink:
    def __init__(self, name):
        self.name = name
        self.live = []
        self.mic_source = "python"

    async def set_mic_live(self, live):
        self.live.append(live)
        return True


def mic_session():
    notes = []

    class M:
        eleven_credits = None

        def note(self, text):
            notes.append(text)

        def publish_state(self):
            pass
    seats = [{"key": "r1", "name": "reachy1", "character": "Dor", "listen": True},
             {"key": "r3", "name": "reachy3", "character": "Eli", "listen": True}]
    s = c.Session(M(), seats, {}, c.Services("", "e", openrouter_key="r"))
    s.links = {"r1": FakeLink("reachy1"), "r3": FakeLink("reachy3")}
    s.ears = Ears(["r1", "r3", robots.PEOPLE_MIC_KEY], vad_factory=FakeVAD)
    s.ears.set_active([robots.PEOPLE_MIC_KEY])
    s.mic_in_use = "people"
    return s, notes


def test_the_button_switches_to_the_robots_mics_at_once():
    s, notes = mic_session()
    assert asyncio.run(s.use_robot_mics("switched by hand"))
    assert s.mic_in_use == "robots" and s.ears.active == {"r1", "r3"}
    assert all(l.live == [True] for l in s.links.values())
    assert "robots' mics listen now" in notes[-1]


def test_a_dead_dji_switches_by_itself():
    s, notes = mic_session()

    class DeadMic:
        name = DJI["name"]

        def health(self):
            return "flat"

        def close(self):
            pass
    s.people_mic = DeadMic()

    async def run():
        guard = asyncio.create_task(s.guard_people_mic())
        await asyncio.sleep(0.4)
        guard.cancel()
    asyncio.run(run())
    assert s.mic_in_use == "robots" and s.ears.active == {"r1", "r3"}
    assert "gone silent" in notes[-1]


def test_back_to_the_dji_mutes_the_robots_again():
    s, notes = mic_session()

    class GoodMic:
        name = DJI["name"]

        def health(self):
            return "ok"
    s.people_mic = GoodMic()
    asyncio.run(s.use_robot_mics("test"))
    assert asyncio.run(s.use_people_mic())
    assert s.mic_in_use == "people" and s.ears.active == {robots.PEOPLE_MIC_KEY}
    assert all(l.live == [True, False] for l in s.links.values())


def test_the_robot_recorder_can_wait_silently():
    code = robots.PYTHON_MIC_CODE
    assert "sys.stdin.buffer.read(1)" in code and "if live[0]:" in code
    compile(code, "<robot mic>", "exec")


# ------------------------------------------------------------ reachy_chat
def test_reachy_chat_follows_the_dji(monkeypatch):
    from hub.adapters import reachy_wireless as rw
    a = rw.ReachyWirelessAdapter.__new__(rw.ReachyWirelessAdapter)
    a.settings = {"mic_mode": "auto"}
    a._launched_mode = ""
    a._mic_name = None
    a.notes = []
    monkeypatch.setattr(laptop_mic.MIC_WATCH, "devices", [BUILTIN, DJI])
    assert a._mic_mode() == "laptop" and a._laptop_mic_device() == DJI["name"]
    monkeypatch.setattr(laptop_mic.MIC_WATCH, "devices", [BUILTIN])
    assert a._mic_mode() == "robot"
    a._launched_mode = "laptop"                    # a running app keeps its mode
    assert a._mic_mode() == "laptop"
    a.settings = {"mic_mode": "robot"}
    a._launched_mode = ""
    monkeypatch.setattr(laptop_mic.MIC_WATCH, "devices", [BUILTIN, DJI])
    assert a._mic_mode() == "robot"


# ------------------------------------------------------------ warm-up
def test_warm_up_checks_every_service_the_robots_use(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)
    gm.cfg["settings"]["simulate"] = True           # no Silero in this test
    for s in gm.cfg["seats"] or []:
        s["included"] = True
    seats = gm.seats()
    seats[0].update(included=True, voice_provider="elevenlabs", voice_id="V1",
                    writer="google/gemini-3.5-flash", character="Dor")
    seats[1].update(included=True, voice_provider="elevenlabs", voice_id="V2",
                    writer="google/gemini-3.5-flash", character="Eli")
    gm.save_config({"seats": seats})
    asked = []
    svc = gm.shared_services()

    async def writer(model):
        asked.append(("writer", model))

    async def voice_ping(v):
        asked.append(("voice", v))
        if v == "V2":
            raise c.ServiceError("ElevenLabs answered 401", 401, "bad")
        return 100

    async def hearing(lang=""):
        asked.append(("hearing", lang))
        return ""

    async def warm():
        asked.append(("openai",))
    svc.ping_writer, svc.ping_voice, svc.ping_hearing, svc.warm = writer, voice_ping, hearing, warm
    asyncio.run(gm.warm_up(full=True))
    checks = gm.warm_state()["checks"]
    assert ("voice", "V1") in asked and ("voice", "V2") in asked
    writers = [a[1] for a in asked if a[0] == "writer"]
    assert writers[0] == "google/gemini-3.5-flash" and c.FAST_MODEL in writers
    assert checks["Voice of Dor"]["ok"] is True and checks["Voice of Eli"]["ok"] is False
    assert gm.shared_services() is svc            # the same warm connections next time


def test_a_premade_first_line_is_used_only_while_it_fits(tmp_path, monkeypatch):
    from test_group_per_robot import manager
    gm = manager(tmp_path, monkeypatch)

    class S:
        seats = [{"key": "k1", "character": "Dor"}]
    gm.session = S()

    async def run():
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        done.set_result("line")

        class Convo:
            premade = None
        g, i = Convo(), Convo()
        gm._premade = {"sig": gm.premade_sig(), "at": time.monotonic(),
                       "modes": {"group": (g, done), "interrupt": (i, loop.create_future())}}
        assert gm.take_premade("group") is g and g.premade is done
        assert gm._premade is None
        # Settings changed since: not used.
        gm._premade = {"sig": "old", "at": time.monotonic(), "modes": {"group": (g, done)}}
        assert gm.take_premade("group") is None
        # Too old: not used.
        gm._premade = {"sig": gm.premade_sig(), "at": time.monotonic() - c.PREMADE_MAX_S - 1,
                       "modes": {"group": (g, done)}}
        assert gm.take_premade("group") is None
    asyncio.run(run())
