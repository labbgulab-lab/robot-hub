"""Group conversation: each robot's own settings (2026-10-21).

Name, personality, voice provider and voice, writer, interrupting level,
gestures, camera and volume belong to each robot, change live, and the
table-wide settings of the same meaning are only the defaults."""

import asyncio
import random

from hub.group import conductor as c
from hub.group.services import Services


class Robot:
    def __init__(self, i):
        self.key, self.name, self.state = "k{}".format(i), "reachy{}".format(i), "CONNECTED"
        self.type_id = c.REACHY


class Registry:
    def __init__(self, n):
        self.robots = [Robot(i + 1) for i in range(n)]

    def all(self):
        return self.robots


class Keys:
    def __init__(self, providers=("openrouter", "gpt", "gemini", "elevenlabs")):
        self.providers = providers

    def all_secrets(self):
        return [{"provider": p, "key": "x"} for p in self.providers]


class Hub:
    def __init__(self, n=2):
        self.registry = Registry(n)
        self.keys = Keys()
        self.adapters = {}


def manager(tmp_path, monkeypatch, n=2, data=None):
    path = tmp_path / "group.json"
    if data is not None:
        import json
        path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(c, "CONFIG_FILE", path)
    gm = c.GroupManager(Hub(n))
    gm.publish = lambda event: None
    gm.publish_state = lambda: None
    return gm


def test_old_config_gets_the_table_settings_per_robot(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch, data={
        "seats": [{"key": "k1", "character": "Noa", "included": True}],
        "settings": {"interrupt_level": 4, "gestures": "calm", "vision": False,
                     "director_model": "openai/gpt-oss-120b", "voice_provider": "openai",
                     "voice_provider_v2": True}})
    noa = gm.seats()[0]
    assert noa["interrupt_level"] == 4 and noa["gestures"] == "calm" and noa["vision"] is False
    assert noa["writer"] == "openai/gpt-oss-120b" and noa["voice_provider"] == "openai"
    # A robot with no saved seat starts from the table's settings too.
    assert gm.seats()[1]["interrupt_level"] == 4
    assert gm.seats()[1]["default_voices"]["openai"]


def test_bad_values_are_refused_field_by_field():
    assert c.clean_seat_field("character", "   ", "Noa") == "Noa"
    assert c.clean_seat_field("character", "  Yael  Cohen ", "Noa") == "Yael Cohen"
    assert c.clean_seat_field("interrupt_level", 9, 3) == 5
    assert c.clean_seat_field("interrupt_level", "x", 3) == 3
    assert c.clean_seat_field("voice_provider", "bark", "auto") == "auto"
    assert c.clean_seat_field("openai_voice", "coral", "") == "coral"
    assert c.clean_seat_field("openai_voice", "bogus", "") == ""
    assert c.clean_seat_field("gemini_voice", "Kore", "") == "Kore"
    assert c.clean_seat_field("writer", "some/model", "") == c.DIRECTOR_MODEL
    assert c.clean_seat_field("gestures", "wild", "calm") == "lively"
    assert c.clean_seat_field("loudness", 400, 150) == 250


def test_while_talking_only_each_robots_own_settings_change(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch)
    gm.save_config({"seats": gm.seats()})
    order = [s["key"] for s in gm.cfg["seats"]]

    class Running:
        def done(self):
            return False
    gm._task = Running()                       # a conversation is on
    seats = [dict(s) for s in gm.seats()][::-1]   # reordered...
    seats[0].update(included=False, listen=False, persona="New one (he/him).",
                    interrupt_level=0, character="Avi")
    assert gm.save_config({"seats": seats})["ok"]
    saved = {s["key"]: s for s in gm.cfg["seats"]}
    k = seats[0]["key"]
    assert [s["key"] for s in gm.cfg["seats"]] == order     # ...but the order stays
    assert saved[k]["included"] is True and saved[k]["listen"] is True
    assert saved[k]["persona"] == "New one (he/him)." and saved[k]["character"] == "Avi"
    assert saved[k]["interrupt_level"] == 0


def test_live_edits_reach_the_robots_at_the_table(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch)

    class Session:
        def __init__(self, seats):
            self.seats = seats
            self.settings = {}
            self.ears = None
            self.links = {}
            self.services = Services("", "", gemini_key="g", openrouter_key="r")
    gm.session = Session([dict(s) for s in gm.seats()])
    seats = gm.seats()
    seats[1].update(writer="openai/gpt-oss-120b", gestures="calm", openai_voice="ash")
    seats[0].update(writer="gpt-4.1-mini")
    gm.save_config({"seats": seats})
    live = {s["key"]: s for s in gm.session.seats}
    assert live["k2"]["writer"] == "openai/gpt-oss-120b" and live["k2"]["gestures"] == "calm"
    assert live["k2"]["openai_voice"] == "ash"
    # The table's writer (races, hearing) is the first robot's.
    assert gm.session.services.director_model == "gpt-4.1-mini"


def session(seats, **keys):
    class M:
        eleven_credits = None

        def note(self, text):
            pass
    services = Services(keys.get("openai", "o"), keys.get("eleven", "e"),
                        gemini_key=keys.get("gemini", "g"), openrouter_key=keys.get("router", "r"))
    return c.Session(M(), seats, {"voice_provider": "auto"}, services)


def test_each_robot_speaks_with_its_own_provider_and_voice():
    noa = {"key": "a", "name": "r1", "character": "Noa", "voice_provider": "gemini", "gemini_voice": "Kore"}
    dor = {"key": "b", "name": "r2", "character": "Dor", "voice_provider": "openai", "openai_voice": "onyx"}
    eli = {"key": "c", "name": "r3", "character": "Eli", "voice_provider": "openrouter", "openai_voice": "onyx"}
    maya = {"key": "d", "name": "r4", "character": "Maya", "voice_provider": "elevenlabs", "voice_id": "X1"}
    s = session([noa, dor, eli, maya])
    assert s.voice_backend(noa) == "gemini" and s.gemini_voice(noa) == "Kore"
    assert s.voice_backend(dor) == "openai" and s.openai_voice(dor) == "onyx"
    # OpenRouter's voice has no onyx: that robot falls back to its default.
    assert s.voice_backend(eli) == "openrouter" and s.router_voice(eli) == "echo"
    assert s.voice_backend(maya) == "eleven" and s.voice_key(maya) == "el:X1"
    # Default voices when none was picked.
    assert s.openai_voice({"key": "a", "character": "Reachy Mini 1"}) == "ash"
    # ElevenLabs refused: a robot set to ElevenLabs keeps it (2026-10-22: never
    # a voice change mid-conversation); a robot on Auto moves on.
    s.eleven_down = True
    assert s.voice_backend(maya) == "eleven" and s.voice_backend(noa) == "gemini"
    assert s.voice_backend({**maya, "voice_provider": "auto"}) == "openai"


def test_auto_leaves_elevenlabs_when_credits_are_low_but_a_chosen_one_stays():
    auto = {"key": "a", "name": "r1", "character": "Noa", "voice_provider": "auto"}
    chosen = {"key": "b", "name": "r2", "character": "Dor", "voice_provider": "elevenlabs"}
    s = session([auto, chosen])
    s.m.eleven_credits = 200
    assert s.voice_backend(auto) == "openai"
    assert s.voice_backend(chosen) == "eleven"


def talk(cls, seats, **settings):
    class M:
        transcript = []
        pending_nudge = ""
        status = {}

        def note(self, text):
            pass
    sess = session(seats)
    sess.settings.update(settings)
    convo = cls.__new__(cls)
    c.Conversation.__init__(convo, M(), sess)
    if cls is c.InterruptTalk:
        convo.partial, convo.openers, convo.stands, convo.interrupters = [], [], {}, []
    return convo


def seats3(*levels):
    return [{"key": k, "name": "reachy" + k, "character": n, "interrupt_level": lv}
            for k, n, lv in zip("123", ("Noa", "Dor", "Maya"), levels)]


def test_all_at_one_level_keeps_the_old_pace():
    t = talk(c.InterruptTalk, seats3(3, 3, 3))
    random.seed(1)
    gaps = [t.next_due() - c.time.monotonic() for _ in range(400)]
    mean = sum(gaps) / len(gaps)
    assert 4.0 < mean < 7.0                     # INTERRUPT_AFTER_S[3] = 5 s x lognormal
    assert t.level() == 3


def test_pushier_robots_cut_in_more_and_level_zero_never():
    t = talk(c.InterruptTalk, seats3(5, 1, 0))
    random.seed(2)
    picks = [t.interrupter()["character"] for _ in range(600)]
    assert "Maya" not in picks
    assert picks.count("Noa") > 3 * picks.count("Dor")
    assert t.level() == 5
    assert talk(c.InterruptTalk, seats3(0, 0, 0)).next_due() == float("inf")


def test_robots_with_different_writers_get_their_own(monkeypatch):
    seats = seats3(3, 3, 3)
    seats[0]["writer"], seats[1]["writer"], seats[2]["writer"] = (
        "google/gemini-3.5-flash", "openai/gpt-oss-120b", "google/gemini-3.5-flash")
    t = talk(c.GroupTalk, seats)
    assert t.one_writer() is None
    asked = []

    async def ask(system, user, image=None, model=""):
        asked.append((model, user))
        return {"speaker": "Noa", "text": "Not true at all."}
    t.ask = ask
    t.last_robot = "1"
    t.s.voice = lambda line: asyncio.sleep(0)
    random.seed(3)

    async def go():
        return await t.prepare()
    line = asyncio.run(go())
    model, user = asked[0]
    # The conductor chose the speaker (not the one who just spoke) and that
    # robot's writer wrote the line, whatever the writer said back.
    assert line.seat["key"] != "1"
    assert model == line.seat["writer"]
    assert "The next speaker is {}".format(line.seat["character"]) in user


def test_one_writer_lets_the_director_choose():
    seats = seats3(3, 3, 3)
    for s in seats:
        s["writer"] = "openai/gpt-oss-120b"
    t = talk(c.GroupTalk, seats)
    assert t.one_writer() == "openai/gpt-oss-120b"


def test_gesture_rule_is_per_robot():
    seats = seats3(3, 3, 3)
    seats[1]["gestures"] = "calm"
    rule = talk(c.GroupTalk, seats).common()["gesture_rule"]
    assert "calm robots (Dor)" in rule and "Noa" in rule
    seats[0]["gestures"] = seats[2]["gestures"] = "calm"
    assert "about half" in talk(c.GroupTalk, seats).common()["gesture_rule"]


def test_camera_off_for_one_robot_only():
    seats = seats3(3, 3, 3)
    seats[0]["vision"] = False
    t = talk(c.GroupTalk, seats)

    class Link:
        async def snapshot(self):
            return b"jpeg"
    t.s.links = {"1": Link(), "2": Link()}

    async def go():
        return await t.s.snapshot("1"), await t.s.snapshot("2")
    assert asyncio.run(go()) == (None, b"jpeg")


def test_a_robot_never_saved_keeps_its_default_voice(tmp_path, monkeypatch):
    """Review 2026-10-21: apply_live() put the empty default voice over the
    one seats() gave an unsaved robot, so every robot spoke as Laura."""
    gm = manager(tmp_path, monkeypatch)

    class Session:
        def __init__(self, seats):
            self.seats = seats
            self.settings = {}
            self.ears = None
            self.links = {}
            self.services = Services("", "", gemini_key="g", openrouter_key="r")
    gm.session = Session([dict(s) for s in gm.seats()])
    before = [s["voice_id"] for s in gm.session.seats]
    assert len(set(before)) == 2 and all(before)
    gm.apply_live()
    assert [s["voice_id"] for s in gm.session.seats] == before


def test_the_named_robot_answers_in_interrupt_mode_with_mixed_writers():
    seats = seats3(3, 3, 3)
    seats[1]["writer"] = "openai/gpt-oss-120b"
    t = talk(c.InterruptTalk, seats)
    asked = []

    async def ask(system, user, image=None, model=""):
        asked.append(model)
        return {"speaker": "Noa", "text": "You are wrong about that one."}
    t.ask = ask
    t.s.voice = lambda line: asyncio.sleep(0)
    line = asyncio.run(t.line_for("The person finished.", person_now="Dor, what do you think?"))
    assert line.seat["character"] == "Dor" and asked == ["openai/gpt-oss-120b"]


def test_a_level_zero_fan_does_not_block_defending():
    seats = [{"key": "1", "name": "r1", "character": "Reachy Mini 5", "interrupt_level": 0},
             {"key": "2", "name": "r2", "character": "Reachy Mini 1", "interrupt_level": 5},
             {"key": "3", "name": "r3", "character": "Reachy Mini 2", "interrupt_level": 5}]
    t = talk(c.InterruptTalk, seats)
    line = c.Line(seat=seats[2], move="oppose", text="No.", final=False, nudge="",
                  director_s=0.0, stance="oppose")
    random.seed(4)
    picks = [t.defender_for(line) for _ in range(300)]
    assert any(p is not None and p["character"] == "Reachy Mini 1" for p in picks)
    assert not any(p is not None and p["character"] == "Reachy Mini 5" for p in picks)
