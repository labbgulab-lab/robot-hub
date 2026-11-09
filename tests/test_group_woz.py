"""The table's Wizard of Oz (2026-11-09): pre-recorded cues through the group
conductor's robot links, with and without a conversation, with and without AI."""

import asyncio
import json
import wave

import pytest

from hub.group import conductor as c
from hub.group import woz as woz_mod
from hub.group.woz import TableWoz, WozError, text_hash
from test_group_groups import Link as BaseLink
from test_group_per_robot import manager

VOICE, STYLE = "Aoede", "warm"
CUES = {"voice": VOICE, "tts_model": "m1", "style": STYLE, "sections": [
    {"id": "s1", "title": "One", "cues": [
        {"id": "greet", "hotkey": "1", "label": "Greeting", "text": "hello there",
         "motion": {"type": "emotion", "name": "welcoming1"}},
        {"id": "other", "hotkey": "2", "label": "Other", "text": "second line",
         "motion": {"type": "dance", "name": "yeah_nod"}}]},
    {"id": "s2", "title": "Two", "cues": [
        {"id": "nod", "hotkey": "3", "label": "Nod", "motion": {"type": "head", "direction": "front"}},
        {"id": "sway", "hotkey": "4", "label": "Sway",
         "motion": {"type": "dance", "name": "side_to_side_sway"}},
        {"id": "think", "hotkey": "5", "label": "Think",
         "motion": {"type": "emotion", "name": "thoughtful1"}}]}]}


class Link(BaseLink):
    def __init__(self, key, features=("clock", "start_at")):
        super().__init__(key, features)
        self.connected = True
        self.stops = 0
        self.ended = 0

    async def stop_audio(self):
        self.stops += 1
        self._reset_clock()

    async def end_line(self):
        self.ended += 1


def write_audio(path, seconds=0.3, rate=24000):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(rate * seconds))


def make_show(tmp_path, with_audio=("greet", "other"), stale=(), seconds=0.3):
    show = tmp_path / "show"
    show.mkdir()
    (show / "cues.json").write_text(json.dumps(CUES), encoding="utf-8")
    manifest = {"voice": VOICE, "model": "m1", "cues": {}}
    for s in CUES["sections"]:
        for cue in s["cues"]:
            if cue["id"] in with_audio:
                write_audio(show / "audio" / (cue["id"] + ".wav"), seconds)
                h = text_hash(cue["text"], VOICE, STYLE)
                manifest["cues"][cue["id"]] = {
                    "hash": "0" * 16 if cue["id"] in stale else h, "duration_s": 0.3,
                    "file": "audio/{}.wav".format(cue["id"]), "text": cue["text"]}
    (show / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return show


def setup(tmp_path, monkeypatch, n=3, groups=None, with_audio=("greet", "other"), stale=(),
          dead=(), seconds=0.3):
    gm = manager(tmp_path, monkeypatch, n=n)
    gm.cfg["settings"]["groups"] = groups or []
    seats = [s for s in gm.seats() if s.get("included")]
    session = c.Session(gm, seats, {"simulate": False}, gm.shared_services(), lite=True)
    session.links = {s["key"]: Link(s["key"]) for s in seats}
    for k in dead:
        session.links[k].connected = False
    session.clock_offsets = {k: 0.0 for k in session.links}
    gm.session = session
    show = make_show(tmp_path, with_audio, stale, seconds)
    gm.woz = TableWoz(gm, show_dir=show, cache_dir=tmp_path / "cache")
    return gm, session


def run(coro):
    return asyncio.run(coro)


async def settle(gm):
    task = gm.woz._task
    if task is not None:
        await task
    for t in list(gm.woz._moves):
        await t


CHOIR = [{"id": "choir", "name": "Choir", "members": [], "whole_table": True, "talk": True,
          "move": True}]


def test_script_and_manifest_are_loaded(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch, stale=("other",))
    body = gm.woz.state()
    cues = {c_["id"]: c_ for s in body["script"]["sections"] for c_ in s["cues"]}
    assert cues["greet"]["ready"] and cues["greet"]["duration_s"] == 0.3
    assert cues["greet"]["hotkey"] == "1" and cues["greet"]["motion"]["name"] == "welcoming1"
    assert not cues["other"]["ready"], "a stale manifest hash means the WAV is not trusted"
    assert cues["nod"]["ready"], "a motion-only cue needs no audio"
    assert body["ok"] and body["connected"] == ["k1", "k2", "k3"] and not body["preparing"]
    assert body["playing"] is None


def test_no_script_is_reported_not_raised(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch)
    gm.woz = TableWoz(gm, show_dir=None)
    body = gm.woz.state()
    assert body["ok"] and body["script"] == {"sections": []} and body["error"]


def test_the_wav_is_resampled_to_16k(tmp_path):
    write_audio(tmp_path / "a.wav", 0.3, 24000)
    assert len(woz_mod.wav_to_16k(tmp_path / "a.wav")) == 4800 * 2
    write_audio(tmp_path / "b.wav", 0.3, 16000)
    assert len(woz_mod.wav_to_16k(tmp_path / "b.wav")) == 4800 * 2


def fake_tts(calls):
    async def speech(http, key, voice, text, tone="", model=""):
        calls.append((voice, text, model))
        yield b"\x05\x00" * 3200
    return speech


def test_missing_audio_is_voiced_once_and_cached(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch, with_audio=("greet",))
    calls = []
    monkeypatch.setattr(woz_mod, "gemini_speech", fake_tts(calls))

    async def go():
        gm.woz.prepare_soon()
        await gm.woz._prep
        assert gm.woz.state()["script"]["sections"][0]["cues"][1]["ready"]
        gm.woz.prepare_soon()
        await gm.woz._prep

    run(go())
    assert len(calls) == 1, "only the cue with no audio is voiced, and only once"
    voice, text, model = calls[0]
    assert voice == VOICE and model == "m1" and text == STYLE + "\n\nsecond line"
    h = text_hash("second line", VOICE, STYLE)
    assert (tmp_path / "cache" / "other-{}.wav".format(h)).is_file()
    # A fresh process finds the cached file with no voice at all.
    fresh = TableWoz(gm, show_dir=gm.woz.show_dir(), cache_dir=tmp_path / "cache")
    assert fresh.audio_file(fresh.load_script()["cues"]["other"]) is not None


def test_offline_still_fires_cues_that_have_audio(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch, with_audio=("greet",))

    async def broken(*a, **k):
        raise OSError("no internet")
        yield b""
    monkeypatch.setattr(woz_mod, "gemini_speech", broken)

    async def go():
        gm.woz.prepare_soon()
        await gm.woz._prep
        ok = await gm.woz.fire("greet", "k1")
        await settle(gm)
        with pytest.raises(WozError) as e:
            await gm.woz.fire("other", "k1")
        return ok, e.value.code

    ok, code = run(go())
    assert ok["ok"] and code == "NO_AUDIO"
    assert gm.session.links["k1"].played, "the cue with audio played"
    cues = gm.woz.state()["script"]["sections"][0]["cues"]
    assert cues[0]["ready"] and not cues[1]["ready"]


def test_choir_is_one_target_for_every_robot(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch, groups=CHOIR)
    body = gm.woz.state()
    assert body["choir"] is True
    assert body["targets"] == [{"id": "all", "name": "Choir", "members": ["k1", "k2", "k3"]}]


def test_groups_make_units_and_loose_robots_are_their_own(tmp_path, monkeypatch):
    groups = [{"id": "g1", "name": "Pair", "members": ["k1", "k2"], "talk": True, "move": True}]
    gm, _ = setup(tmp_path, monkeypatch, groups=groups)
    body = gm.woz.state()
    assert body["choir"] is False
    assert [(t["id"], t["members"]) for t in body["targets"]] == [("k1", ["k1", "k2"]),
                                                                    ("k3", ["k3"])]
    assert body["targets"][0]["name"] == "Pair" and body["targets"][1]["name"] == "reachy3"
    quiet = [{"id": "g1", "name": "Dancers", "members": ["k1", "k2"], "talk": False}]
    gm.cfg["settings"]["groups"] = quiet
    assert [t["id"] for t in gm.woz.state()["targets"]] == ["k1", "k2", "k3"]


def test_random_never_repeats_and_auto_follows_the_choir(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch)
    w = gm.woz

    async def go():
        got = []
        for _ in range(30):
            r = await w.fire("greet", "random")
            got.append(r["target_id"])
            await w.stop()
        return got

    got = run(go())
    assert all(a != b for a, b in zip(got, got[1:])) and len(set(got)) == 3
    gm.cfg["settings"]["groups"] = CHOIR
    assert run(w.fire("greet", "auto"))["target_id"] == "all"


def test_a_choir_cue_plays_on_every_robot_at_one_moment(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, groups=CHOIR)

    async def go():
        r = await gm.woz.fire("greet", "auto")
        playing = gm.woz.state()["playing"]
        await settle(gm)
        return r, playing

    r, playing = run(go())
    assert r["target_id"] == "all" and r["missing"] == [] and r["duration_s"] == pytest.approx(0.3)
    assert playing["cue_id"] == "greet" and playing["target_id"] == "all"
    for link in session.links.values():
        assert link.played and len(link.starts) == 1, "scheduled start on every robot"
        assert link.motions == [{"type": "emotion", "name": "welcoming1"}]
        assert link.ended == 1
    assert len({round(l.starts[0], 3) for l in session.links.values()}) == 1
    assert gm.woz.state()["playing"] is None


def test_a_dead_link_is_skipped_and_named(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, groups=CHOIR, dead=("k2",))

    async def go():
        r = await gm.woz.fire("greet", "all")
        await settle(gm)
        return r

    r = run(go())
    assert r["ok"] and r["missing"] == ["reachy2"]
    assert session.links["k1"].played and session.links["k3"].played
    assert not session.links["k2"].played and not session.links["k2"].motions


def test_every_link_dead_is_no_robots_and_recovers(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, dead=("k1", "k2", "k3"))

    async def go():
        with pytest.raises(WozError) as e:
            await gm.woz.fire("greet", "k1")
        for l in session.links.values():
            l.connected = True
        ok = await gm.woz.fire("greet", "k1")
        await settle(gm)
        return e.value.code, ok

    code, ok = run(go())
    assert code == "NO_ROBOTS" and ok["ok"]


def test_refusal_codes(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, with_audio=())

    async def code_of(coro):
        with pytest.raises(WozError) as e:
            await coro
        return e.value.code

    async def go():
        out = [await code_of(gm.woz.fire("nope", "auto")),
               await code_of(gm.woz.fire("greet", "k1")),
               await code_of(gm.woz.fire("nod", "zzz"))]
        gm.session = None
        out.append(await code_of(gm.woz.fire("nod", "auto")))
        return out

    assert run(go()) == ["NO_CUE", "NO_AUDIO", "NO_TARGET", "NOT_CONNECTED"]


def test_a_motion_only_cue_does_not_cut_the_speech(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)

    async def go():
        r = await gm.woz.fire("nod", "k1")
        await settle(gm)
        return r

    r = run(go())
    assert r["duration_s"] == 0.0
    assert session.links["k1"].motions == [{"type": "head", "direction": "front"}]
    assert session.links["k1"].stops == 0 and not session.links["k1"].played


class Convo:
    def __init__(self, gm):
        self.gm = gm

    def turn(self, **fields):
        entry = {"id": len(self.gm.transcript) + 1, **fields}
        self.gm.transcript.append(entry)
        return entry


def test_a_cue_during_a_conversation_cuts_the_line_and_is_recorded(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)

    class Running:
        def done(self):
            return False
    gm._task, gm.convo = Running(), Convo(gm)
    session.speaking_key = "k1"
    seen = []

    async def speaker():
        # What Conversation.speak does: sees the bump, stops, lets go of the floor.
        while session.cut_seq == 0:
            await asyncio.sleep(0.01)
        seen.append(session.cut_seq)
        await asyncio.sleep(0.05)
        session.speaking_key = None

    async def go():
        sp = asyncio.ensure_future(speaker())
        r = await gm.woz.fire("greet", "k2")
        await sp
        floor_waits = []

        async def talk():
            await session.wait_floor()
            floor_waits.append(gm.woz.active())
        await talk()
        await settle(gm)
        return r, floor_waits

    r, waits = run(go())
    assert seen == [1] and r["target_id"] == "k2"
    assert all(l.stops >= 1 for l in session.links.values()), "every robot was cleared"
    entry = gm.transcript[-1]
    assert entry["who"] == "reachy2" and entry["text"] == "hello there" and entry["woz"] is True
    assert session.links["k2"].played, "the cue played; the conversation goes on after it"


def test_the_conversation_waits_while_a_cue_plays(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)

    async def go():
        await gm.woz.fire("greet", "k1")
        t0 = asyncio.get_running_loop().time()
        await session.wait_floor()
        waited = asyncio.get_running_loop().time() - t0
        return waited

    assert run(go()) > 0.1
    assert not gm.woz.active()


def test_typed_line_uses_the_conversation_voice_or_says_no_voice(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)

    def good(line):
        async def fill():
            line.audio.add(b"\x07\x00" * 4800)
            line.audio.finish()
        line.tts = asyncio.ensure_future(fill())
        return line.tts

    def bad(line):
        async def fill():
            line.audio.finish("ServiceError: no internet")
        line.tts = asyncio.ensure_future(fill())
        return line.tts

    async def go():
        session.start_voice = good
        ok = await gm.woz.say("good evening", "k3")
        await settle(gm)
        session.start_voice = bad
        with pytest.raises(WozError) as e:
            await gm.woz.say("again", "k3")
        return ok, e.value

    ok, err = run(go())
    assert ok["target_id"] == "k3" and ok["duration_s"] == pytest.approx(0.3)
    assert session.links["k3"].played
    assert err.code == "NO_VOICE" and "no internet" in err.message


def test_stop_silences_and_clears_playing(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    events = []
    gm.publish = events.append

    async def go():
        await gm.woz.fire("greet", "k1")
        await gm.woz.stop()

    run(go())
    assert gm.woz.state()["playing"] is None
    assert session.links["k1"].stops >= 1
    assert {"type": "group.woz", "playing": None} in events
    assert any(e.get("playing") for e in events if e.get("type") == "group.woz")


def test_connect_opens_only_the_links(tmp_path, monkeypatch):
    gm, _ = setup(tmp_path, monkeypatch)
    gm.session = None
    opened = []

    async def open_lite(seats):
        opened.append([s["key"] for s in seats])
        s = c.Session(gm, seats, {"simulate": False}, gm.shared_services(), lite=True)
        s.links = {x["key"]: Link(x["key"]) for x in seats}
        gm.session = s
        return None

    gm.open_lite = open_lite
    monkeypatch.setattr(gm.woz, "prepare_soon", lambda: None)
    r = run(gm.woz.connect())
    assert r == {"ok": True, "connected": ["k1", "k2", "k3"], "missing": []}
    assert opened == [["k1", "k2", "k3"]]
    # A dropped link: connecting again opens only that robot again.
    gm.session.links["k2"].connected = False
    reopened = []

    async def reopen(more):
        reopened.append([s["key"] for s in more])
        gm.session.links["k2"] = Link("k2")
    gm.session.open_lite = reopen
    r = run(gm.woz.connect())
    assert len(opened) == 1 and reopened == [["k2"]]
    assert r["connected"] == ["k1", "k2", "k3"] and r["missing"] == []
    # Every link dead (the WiFi went): the whole connection is opened again.
    for link in gm.session.links.values():
        link.connected = False

    async def no_close():
        gm.session = None
    gm._disconnect = no_close
    r = run(gm.woz.connect())
    assert len(opened) == 2 and r["connected"] == ["k1", "k2", "k3"]


# ------------------------------------------------- the 2026-11-09 review
class Running:
    def done(self):
        return False

    def cancel(self):
        pass


class Ears:
    capturing = False
    during_robot = False

    def __init__(self):
        self.refs, self.dropped = [], []

    def add_reference(self, key, *a):
        self.refs.append(key)

    def drop_reference(self, key, *a):
        self.dropped.append(key)


def talking(tmp_path, monkeypatch, **kw):
    """A manager with a GroupTalk running on the fake links (speak() is real)."""
    gm, session = setup(tmp_path, monkeypatch, **kw)
    session.ears = Ears()
    convo = c.GroupTalk.__new__(c.GroupTalk)
    c.Conversation.__init__(convo, gm, session)
    gm._task, gm.convo = Running(), convo
    return gm, session, convo


def a_line(convo, key, text="a line from the conversation"):
    seat = next(s for s in convo.seats if s["key"] == key)
    line = c.Line(seat=seat, move="", text=text, final=False, nudge="", director_s=0.0)
    entry = convo.turn(kind="robot", who=seat["name"], character=seat["character"], text=text)
    return line, entry


def test_a_line_still_waiting_for_its_voice_lets_go_at_once_and_sends_nothing(
        tmp_path, monkeypatch):
    gm, session, convo = talking(tmp_path, monkeypatch)

    async def go():
        line, entry = a_line(convo, "k1")
        sp = asyncio.ensure_future(convo.speak(line, entry, cut_by_people=False))
        await asyncio.sleep(0.2)                    # waiting for its voice
        assert session.speaking_key == "k1"
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        await gm.woz.fire("greet", "k2")
        took = loop.time() - t0
        line.audio.add(b"\x01\x00" * 16000)        # the voice comes late
        line.audio.finish()
        finished = await sp
        await settle(gm)
        return finished, entry, took

    finished, entry, took = run(go())
    k1 = session.links["k1"]
    assert finished is False and took < 1.0, "the cue did not wait out a safety limit"
    assert not k1.played, "not a piece of the line went out"
    assert k1.stops == 1, "only the cue's own clear: the line did not flush the cue"
    assert not session.ears.dropped, "the cue's echo references are kept"
    assert entry["unspoken"] and entry["cut_woz"] and not entry.get("cut")
    assert session.links["k2"].played


def test_the_floor_is_held_from_the_moment_a_cue_is_fired(tmp_path, monkeypatch):
    """Back to back cues: a waiting line must not slip in while the second
    one cuts the first (the floor used to be free during the cut)."""
    gm, session, convo = talking(tmp_path, monkeypatch, seconds=1.0)
    seen = []
    times = {"line": [], "cue_done": None}
    k3 = session.links["k3"]
    plain_play = k3.play

    async def timed_play(pcm):
        times["line"].append(asyncio.get_running_loop().time())
        await plain_play(pcm)
    k3.play = timed_play
    for link in session.links.values():
        async def slow_stop(plain_stop=link.stop_audio):
            seen.append(gm.woz.active())
            await asyncio.sleep(0.2)
            await plain_stop()
        link.stop_audio = slow_stop

    async def go():
        await gm.woz.fire("greet", "k1")
        line, entry = a_line(convo, "k3")
        line.audio.add(b"\x01\x00" * 3200)
        line.audio.finish()
        sp = asyncio.ensure_future(convo.speak(line, entry, cut_by_people=False))
        await asyncio.sleep(0.15)
        await gm.woz.fire("other", "k1")
        await gm.woz._task
        times["cue_done"] = asyncio.get_running_loop().time()
        await sp

    run(go())
    assert seen and all(seen), "the floor was held all through the cut"
    assert times["line"] and min(times["line"]) >= times["cue_done"] - 0.05, \
        "the line played only after the cue"


def test_group_stop_stops_a_playing_cue(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, seconds=3.0)

    async def go():
        await gm.woz.fire("greet", "k1")
        await asyncio.sleep(0.1)
        await gm.stop()
        sent = len(session.links["k1"].played)
        await asyncio.sleep(0.4)
        return sent

    sent = run(go())
    assert len(session.links["k1"].played) == sent, "nothing more of the cue went out"
    assert gm.woz._task is None and not gm.woz.active() and gm.woz.state()["playing"] is None


def test_finish_stops_the_cue_but_not_the_line(tmp_path, monkeypatch):
    gm, session, convo = talking(tmp_path, monkeypatch, seconds=3.0)

    async def go():
        await gm.woz.fire("greet", "k1")
        seq = session.cut_seq
        r = await gm.finish()
        return r, seq

    r, seq = run(go())
    assert r["closing"] and convo.closing
    assert session.cut_seq == seq, "the robot talking finishes its line"
    assert gm.woz._task is None and not gm.woz.active()


def test_a_motion_only_cue_after_a_cue_cuts_nothing_and_writes_nothing(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    gm._task, gm.convo = Running(), Convo(gm)

    async def go():
        await gm.woz.fire("greet", "k1")
        await settle(gm)
        assert gm.woz._task is None, "a finished cue is not left behind"
        before = (session.cut_seq, [l.stops for l in session.links.values()], len(gm.transcript))
        await gm.woz.fire("think", "k2")
        await settle(gm)
        return before

    seq, stops, lines = run(go())
    assert session.cut_seq == seq and [l.stops for l in session.links.values()] == stops
    assert len(gm.transcript) == lines, "no empty line in the transcript"
    assert session.links["k2"].motions[-1] == {"type": "emotion", "name": "thoughtful1"}
    left = session.busy_until["k2"] - c.time.monotonic()
    assert left > 4.0, "the head is left alone for the whole emotion (5.9 s)"


def test_a_gesture_outlasting_its_line_keeps_the_head(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    run(gm.woz.fire("greet", "k1"))
    assert session.busy_until["k1"] - c.time.monotonic() > 2.0, "welcoming1 is 3.5 s"


def test_stop_drops_a_typed_line_still_being_voiced(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    gm._task, gm.convo = Running(), Convo(gm)

    def slow(line):
        async def fill():
            await asyncio.sleep(0.5)
            line.audio.add(b"\x07\x00" * 4800)
            line.audio.finish()
        line.tts = asyncio.ensure_future(fill())
        return line.tts
    session.start_voice = slow

    async def go():
        say = asyncio.ensure_future(gm.woz.say("hold on", "k3"))
        await asyncio.sleep(0.1)
        await gm.woz.stop()
        r = await say
        await asyncio.sleep(0.6)
        return r

    r = run(go())
    assert r == {"ok": True, "stopped": True}
    assert not session.links["k3"].played and not gm.transcript


def test_stop_during_the_cut_drops_the_cue(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    gm._task, gm.convo = Running(), Convo(gm)
    session.speaking_key = "k1"                     # a line that is slow to let go

    async def go():
        fire = asyncio.ensure_future(gm.woz.fire("greet", "k2"))
        await asyncio.sleep(0.1)
        await gm.woz.stop()
        r = await fire
        await settle(gm)
        return r

    r = run(go())
    assert r == {"ok": True, "stopped": True}
    assert not session.links["k2"].played and not gm.transcript
    assert not gm.woz.active() and gm.woz.state()["playing"] is None


def test_woz_stop_also_cuts_the_conversation_line(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    gm._task = Running()
    seq = session.cut_seq
    run(gm.woz.stop())
    assert session.cut_seq == seq + 1 and all(l.stops for l in session.links.values())


@pytest.mark.parametrize("with_cue,cut_line", [(True, False), (True, True), (False, True)])
def test_stop_keeps_the_floor_until_the_robots_are_cleared(tmp_path, monkeypatch, with_cue,
                                                           cut_line):
    # Finish or Esc during a cue: a line that waited for it must not send its
    # first piece while the clears are still going out (it would be flushed).
    gm, session = setup(tmp_path, monkeypatch, seconds=2.0)
    seen = []

    async def go():
        if with_cue:
            await gm.woz.fire("greet", "k1")
        for link in session.links.values():
            async def stop_audio():
                seen.append(session.floor_taken())
                await asyncio.sleep(0.05)
            link.stop_audio = stop_audio
        await gm.woz.stop(cut_line=cut_line)
        return session.floor_taken(), gm.woz.busy()

    taken, busy = run(go())
    assert seen and all(seen), "held while the robots are cleared"
    assert not taken and not busy, "and free once they are"


def test_pile_on_and_defend_keep_off_a_cue(tmp_path, monkeypatch):
    from types import SimpleNamespace
    gm, session = setup(tmp_path, monkeypatch, seconds=2.0)
    session.ears = Ears()
    monkeypatch.setattr(c.random, "uniform", lambda a, b: 0.0)

    async def go():
        await gm.woz.fire("greet", "k1")
        seat = session.seats[1]
        talk = SimpleNamespace(s=session, lang="en")
        await c.InterruptTalk.pile_on(talk, seat, "approve", 0.0)
        line = c.Line(seat=session.seats[2], move="", text="you are wrong", final=False,
                      nudge="", director_s=0.0)
        line.playing = True
        speaking = asyncio.ensure_future(asyncio.sleep(5))
        talk = SimpleNamespace(s=session, lang="en", current=(line, {"text": line.text}),
                               speaking=speaking, discard=c.Conversation.discard,
                               ready=c.Conversation.ready, ears=session.ears)
        await c.InterruptTalk.defend(talk, line, seat)
        cancelled = speaking.cancelled()
        speaking.cancel()
        await gm.woz.stop()
        return cancelled

    stops = session.links["k3"].stops
    cancelled = run(go())
    assert not session.links["k2"].played, "no pile-on over the cue"
    assert not cancelled and not session.ears.dropped, "no defending over the cue"
    assert session.links["k3"].stops == stops + 2, "only the cue's clear and the Stop"


def test_a_woz_cut_is_not_the_people_in_the_writers_history(tmp_path, monkeypatch):
    gm, session, convo = talking(tmp_path, monkeypatch)
    _, entry = a_line(convo, "k1", "we were saying")
    entry.update(cut=True, cut_woz=True, spoken="we were...")
    assert convo.history()[-1].endswith("we were... [cut off]")


def test_stop_while_waiting_for_the_floor_is_not_logged_as_said(tmp_path, monkeypatch):
    gm, session, convo = talking(tmp_path, monkeypatch, seconds=2.0)

    async def go():
        await gm.woz.fire("greet", "k1")
        line, entry = a_line(convo, "k2")
        line.audio.add(b"\x01\x00" * 3200)
        line.audio.finish()
        sp = asyncio.ensure_future(convo.speak(line, entry, cut_by_people=False))
        await asyncio.sleep(0.1)
        sp.cancel()
        await asyncio.wait({sp})
        await gm.woz.stop()
        return entry

    entry = run(go())
    assert entry["unspoken"] and not session.links["k2"].played


def test_waiting_for_the_floor_feeds_the_hang_watchdog(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, seconds=0.5)
    beats = []

    class Alive:
        def beat(self):
            beats.append(1)

    async def go():
        await gm.woz.fire("greet", "k1")
        await session.wait_floor(Alive())

    run(go())
    assert beats


def test_random_never_picks_a_robot_that_is_off(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, dead=("k2",))

    async def go():
        got = []
        for _ in range(20):
            got.append((await gm.woz.fire("greet", "random"))["target_id"])
            await gm.woz.stop()
        return got

    assert "k2" not in run(go())


def test_a_rebuilt_show_plays_the_new_recording(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    cue = gm.woz.load_script()["cues"]["greet"]
    first = run(gm.woz.pcm_of(cue))
    write_audio(gm.woz.show_dir() / "audio" / "greet.wav", 0.6)
    again = run(gm.woz.pcm_of(cue))
    assert len(again) == 2 * len(first)
    assert gm.woz.duration_of(cue, gm.woz.load_script()) == pytest.approx(0.6)


def test_manifest_matches_build_show_exactly(tmp_path, monkeypatch):
    """No "voice" in the script (build_show uses Aoede) and a line with a
    trailing space (build_show hashes it as written)."""
    gm, session = setup(tmp_path, monkeypatch)
    show = gm.woz.show_dir()
    data = json.loads((show / "cues.json").read_text(encoding="utf-8"))
    data.pop("voice")
    data["sections"][0]["cues"][0]["text"] = "hello there "
    (show / "cues.json").write_text(json.dumps(data), encoding="utf-8")
    manifest = json.loads((show / "manifest.json").read_text(encoding="utf-8"))
    manifest["cues"]["greet"].update(hash=text_hash("hello there ", "Aoede", STYLE),
                                     text="hello there ")
    (show / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    gm.woz._script = None
    cue = gm.woz.load_script()["cues"]["greet"]
    assert cue["text"] == "hello there" and gm.woz.audio_file(cue) is not None


def test_dances_play_their_stand_in_and_say_so(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    cues = {c_["id"]: c_ for s in gm.woz.state()["script"]["sections"] for c_ in s["cues"]}
    assert "yes1" in cues["other"]["note"] and "dance1" in cues["sway"]["note"]
    assert "note" not in cues["greet"]
    assert cues["sway"]["ready"], "a dance with a stand-in can be fired"

    async def go():
        r1 = await gm.woz.fire("other", "k1")
        await settle(gm)
        r2 = await gm.woz.fire("sway", "k1")
        await settle(gm)
        return r1, r2

    r1, r2 = run(go())
    assert r1["note"] and r2["note"] and session.links["k1"].played
    assert session.links["k1"].motions == [{"type": "emotion", "name": "yes1"},
                                           {"type": "emotion", "name": "dance1"}]
    assert session.busy_until["k1"] > 0


def test_a_dance_with_no_stand_in_is_not_ready(tmp_path, monkeypatch):
    # The page must not offer a reaction key that moves nothing (review #16).
    gm, session = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(woz_mod, "DANCE_STAND_IN", "no_such_move")
    cues = {c_["id"]: c_ for s in gm.woz.state()["script"]["sections"] for c_ in s["cues"]}
    assert not cues["sway"]["ready"] and cues["sway"]["note"]
    assert cues["nod"]["ready"] and cues["think"]["ready"]
    assert cues["other"]["ready"], "a line still plays; its nod is a nod"

    async def go():
        with pytest.raises(WozError) as e:
            await gm.woz.fire("sway", "k1")
        return e.value.code

    assert run(go()) == "NO_MOTION" and not session.links["k1"].motions


def test_connect_keeps_a_get_ready_connection_and_names_the_missing(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch, dead=("k2",))
    session.lite = False                            # opened by Get ready
    closed = []

    async def no_close():
        closed.append(1)
    gm._disconnect = no_close
    monkeypatch.setattr(gm.woz, "prepare_soon", lambda: None)
    r = run(gm.woz.connect())
    assert not closed and gm.session is session
    assert r["connected"] == ["k1", "k3"] and r["missing"] == ["reachy2"]


def test_connect_brings_back_a_robot_that_did_not_join(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    del session.links["k3"]                         # it did not join the last time
    session.seats = [s for s in session.seats if s["key"] != "k3"]
    kept = dict(session.links)
    opened, torn = [], []

    async def reopen(more):
        opened.append([s["key"] for s in more])     # still off: it stays out

    async def no_close():
        torn.append(1)
    session.open_lite, gm._disconnect = reopen, no_close
    monkeypatch.setattr(gm.woz, "prepare_soon", lambda: None)
    # The page sees it: a target, not connected, and named in missing.
    body = gm.woz.state()
    assert "k3" in [k for t in body["targets"] for k in t["members"]]
    assert body["missing"] == ["k3"] and "k3" not in body["connected"]
    r = run(gm.woz.connect())
    assert opened == [["k3"]], "only the one that is missing is opened again"
    assert not torn and gm.session is session and all(session.links[k] is l
                                                      for k, l in kept.items())
    assert r["missing"] == ["reachy3"], "and still says who is missing"


def test_a_lite_connection_adds_the_robots_it_reopens(tmp_path, monkeypatch):
    # Session.open_lite(more): the dead link is closed, the robot opened again,
    # the robots that are on are not touched.
    from hub.group import robots as robots_mod
    gm, session = setup(tmp_path, monkeypatch, dead=("k2",))
    session.settings["simulate"] = True
    del session.links["k3"]
    session.seats = [s for s in session.seats if s["key"] != "k3"]
    dead, k1 = session.links["k2"], session.links["k1"]
    closed = []

    async def close():
        closed.append(1)
    dead.close = close

    class Fresh(Link):
        def __init__(self, key, name, listen=False):
            super().__init__(key)
            self.opened = False

        async def open(self):
            if self.key == "k3":
                raise RuntimeError("off the WiFi")
            self.opened = True

    async def no_clocks():
        pass
    monkeypatch.setattr(robots_mod, "LaptopLink", Fresh)
    session.measure_clocks = no_clocks
    more = [s for s in gm.seats() if s["key"] in ("k2", "k3")]
    run(session.open_lite(more))
    assert closed and session.links["k1"] is k1
    assert session.links["k2"] is not dead and session.links["k2"].opened
    assert "k3" not in session.links, "one that could not join stays out"
    assert [s["key"] for s in session.seats] == ["k1", "k2"]


def test_settings_on_a_woz_connection_start_no_paid_warm_up(tmp_path, monkeypatch):
    gm, session = setup(tmp_path, monkeypatch)
    warmed = []
    session.rewarm = lambda: warmed.append(1)
    gm.apply_live()
    assert not warmed


def test_a_wizard_of_oz_connection_keeps_a_robot_whose_health_probe_failed(tmp_path, monkeypatch):
    # Review of round 2: on a WoZ-only connection the targets came from
    # m.seats() alone, which drops a robot the registry marks ERROR after one
    # failed health probe, although its audio link is fine: Choir then played
    # without it. The targets are the robots held plus the included rest.
    gm, session = setup(tmp_path, monkeypatch, groups=CHOIR)
    full = gm.seats()
    monkeypatch.setattr(gm, "seats", lambda: [s for s in full if s["key"] != "k2"])
    plan = gm.woz.plan()
    assert plan["choir"] and plan["all"] == ["k1", "k2", "k3"]
    assert sorted(plan["targets"][0]["members"]) == ["k1", "k2", "k3"]
    # A robot included but not held yet is still a target (Connect opens it).
    session.seats = [s for s in session.seats if s["key"] != "k3"]
    monkeypatch.setattr(gm, "seats", lambda: full)
    assert gm.woz.plan()["all"] == ["k1", "k2", "k3"]
