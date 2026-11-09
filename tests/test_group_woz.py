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
        {"id": "nod", "hotkey": "3", "label": "Nod", "motion": {"type": "head", "direction": "front"}}]}]}


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


def make_show(tmp_path, with_audio=("greet", "other"), stale=()):
    show = tmp_path / "show"
    show.mkdir()
    (show / "cues.json").write_text(json.dumps(CUES), encoding="utf-8")
    manifest = {"voice": VOICE, "model": "m1", "cues": {}}
    for s in CUES["sections"]:
        for cue in s["cues"]:
            if cue["id"] in with_audio:
                write_audio(show / "audio" / (cue["id"] + ".wav"))
                h = text_hash(cue["text"], VOICE, STYLE)
                manifest["cues"][cue["id"]] = {
                    "hash": "0" * 16 if cue["id"] in stale else h, "duration_s": 0.3,
                    "file": "audio/{}.wav".format(cue["id"]), "text": cue["text"]}
    (show / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return show


def setup(tmp_path, monkeypatch, n=3, groups=None, with_audio=("greet", "other"), stale=(),
          dead=()):
    gm = manager(tmp_path, monkeypatch, n=n)
    gm.cfg["settings"]["groups"] = groups or []
    seats = [s for s in gm.seats() if s.get("included")]
    session = c.Session(gm, seats, {"simulate": False}, gm.shared_services(), lite=True)
    session.links = {s["key"]: Link(s["key"]) for s in seats}
    for k in dead:
        session.links[k].connected = False
    session.clock_offsets = {k: 0.0 for k in session.links}
    gm.session = session
    show = make_show(tmp_path, with_audio, stale)
    gm.woz = TableWoz(gm, show_dir=show, cache_dir=tmp_path / "cache")
    return gm, session


def run(coro):
    return asyncio.run(coro)


async def settle(gm):
    task = gm.woz._task
    if task is not None:
        await task


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
    # A dropped link: connecting again opens them again.
    gm.session.links["k2"].connected = False

    async def no_close():
        gm.session = None
    gm._disconnect = no_close
    r = run(gm.woz.connect())
    assert len(opened) == 2 and r["connected"] == ["k1", "k2", "k3"]
