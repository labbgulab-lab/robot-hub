"""2026-10-26: a group conversation hung for 22 minutes with nothing in any
log (run group-20261026-111944, on the choked hotspot uplink). The guards:
a line's audio always ends, the speaker never waits for it forever, and a
conversation with no sign of life for HANG_S is stopped with a stack report
in the hub log. Also the lab intro started without Get ready (it awaited
None and fell back to the plain opener)."""

import asyncio
import logging
import time
import types

from hub.group import conductor as c
from test_group_per_robot import seats3, talk


def test_playable_gives_up_when_no_voice_comes():
    async def go():
        audio = c.Audio()
        t0 = time.monotonic()
        await audio.playable(5.0, limit_s=0.2)
        return audio, time.monotonic() - t0
    audio, took = asyncio.run(go())
    assert took < 1.0
    assert audio.done and "no audio" in audio.error


def test_stream_ends_when_the_voice_stalls_mid_line():
    async def go():
        audio = c.Audio()
        audio.add(b"\0\0" * 100)
        got = []
        async for chunk in audio.stream(gap_s=0.2):
            got.append(chunk)
        return audio, got
    audio, got = asyncio.run(go())
    assert len(got) == 1
    assert audio.done and "stalled" in audio.error


def test_a_voice_cancelled_before_it_ran_still_ends_the_audio():
    t = talk(c.GroupTalk, seats3(3, 3)[:2])

    async def never(line):
        raise AssertionError("must not run")
    t.s.voice = never

    async def go():
        line = c.Line(seat=t.seats[0], move="", text="hello there", final=False,
                      nudge="", director_s=0.0)
        task = t.s.start_voice(line)
        task.cancel()               # before it ever ran: voice()'s handlers never run
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return line
    line = asyncio.run(go())
    assert line.audio.done and line.audio.error == "cancelled"


class _Manager:
    def __init__(self):
        self.notes = []
        self.error = None

    def note(self, text):
        self.notes.append(text)


class _StuckConvo:
    def __init__(self):
        self.alive_at = time.monotonic()
        self.cancelled = False

    async def run(self):
        try:
            await asyncio.Event().wait()        # waits forever, no sign of life
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def test_watch_stops_a_stuck_conversation_and_logs_where_it_waits(caplog):
    m = _Manager()
    convo = _StuckConvo()
    caplog.set_level(logging.WARNING, logger=c.log.name)

    async def go():
        await asyncio.wait_for(c.GroupManager._watch(m, convo, hang_s=0.4), 5)
    asyncio.run(go())
    assert convo.cancelled
    assert m.error and "stuck" in m.error and m.notes == [m.error]
    report = "\n".join(r.getMessage() for r in caplog.records)
    assert "stuck for" in report and "_StuckConvo.run" in report


def test_watch_leaves_a_live_conversation_alone():
    m = _Manager()

    class Busy:
        alive_at = time.monotonic()

        async def run(self):
            for _ in range(10):
                self.alive_at = time.monotonic()
                await asyncio.sleep(0.1)       # 1 s in all, beating all along
    asyncio.run(c.GroupManager._watch(m, Busy(), hang_s=0.4))
    assert m.error is None and m.notes == []


def test_watch_passes_a_failure_on():
    class Broken:
        alive_at = time.monotonic()

        async def run(self):
            raise RuntimeError("the director failed three times in a row")
    try:
        asyncio.run(c.GroupManager._watch(_Manager(), Broken(), hang_s=5))
    except RuntimeError as exc:
        assert "three times" in str(exc)
    else:
        raise AssertionError("the failure was swallowed")


def test_lab_intro_without_get_ready_hands_over_to_the_second_robot():
    """As run() does it: opener(), then say_intro() takes the intro task
    before the opener task has started."""
    t = talk(c.GroupTalk, seats3(3, 3)[:2], topic="AI and music")
    t.s.voice = lambda line: asyncio.sleep(0)
    t.s.ears = types.SimpleNamespace(reset_capture=lambda: None)
    t.s.links = {s["key"]: object() for s in t.seats}
    t.turn = lambda **fields: dict(fields)
    t.note = lambda text: None
    spoken = []

    async def speak(line, entry, cut_by_people):
        spoken.append(line.seat["character"])
        return True
    t.speak = speak

    async def ask(system, user, image=None, model=""):
        if "lab intro: exactly" in user:
            return {"lines": [{"speaker": "Noa", "text": "Welcome to Laba Lab."},
                              {"speaker": "Dor", "text": "The lab studies people and robots."}],
                    "handover": "Well, let's get into it."}
        return {"speaker": "Noa", "text": "AI will never replace a real songwriter."}
    t.ask = ask

    async def go():
        opener = t.opener()
        await t.say_intro()
        return await opener
    line = asyncio.run(go())
    assert spoken == ["Noa", "Dor", "Noa"]
    assert line.seat["character"] == "Dor"      # not the plain opener's pick
