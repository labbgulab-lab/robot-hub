"""Group conversation with one Reachy, and robots that are robots (Tomer,
2026-10-25, the day before the demo).

- The page's + adds a robot that talks through the laptop's speaker (a fresh
  one each time; the first plays a seated robot that is not here), X takes it
  away again.
- No human names: labels "Reachy Mini N", each robot its own male voice."""

from hub.group import conductor as c
from test_group_per_robot import manager


def demo_table():
    return {"seats": [{"key": "k1", "character": "Reachy Mini 1", "included": True,
                       "voice_id": "LIAM"},
                      {"key": "k2", "character": "Reachy Mini 2", "included": True,
                       "voice_id": "GEORGE", "persona": "Against."}],
            "settings": {"voice_provider_v2": True}}


def laptop(gm):
    return [s for s in gm.seats() if c.is_laptop_seat(s)]


def test_one_reachy_alone_has_no_laptop_robot(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch, n=1, data=demo_table())
    assert [s["key"] for s in gm.seats()] == ["k1"]


def test_old_tick_box_still_means_one_laptop_robot(tmp_path, monkeypatch):
    data = demo_table()
    data["settings"]["laptop_robot"] = True
    gm = manager(tmp_path, monkeypatch, n=1, data=data)
    assert [s["key"] for s in laptop(gm)] == [c.SIM_KEYS[0]]


def test_first_laptop_robot_plays_the_missing_robot(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch, n=1, data=demo_table())
    gm.save_config({"settings": {"laptop_seats": ["sim:1"]}})
    seats = {s["key"]: s for s in gm.seats()}
    assert set(seats) == {"k1", "sim:1"}
    two = seats["sim:1"]
    assert two["character"] == "Reachy Mini 2" and two["voice_id"] == "GEORGE"
    assert two["persona"] == "Against." and two["included"] and not two["listen"]


def test_more_robots_get_new_labels_and_voices(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch, n=1, data=demo_table())
    gm.save_config({"settings": {"laptop_seats": ["sim:1", "sim:2", "sim:3"]}})
    seats = gm.seats()
    labels = [s["character"] for s in seats]
    voices = [s["voice_id"] for s in seats]
    assert len(set(labels)) == len(labels) == 4
    assert len(set(voices)) == 4
    assert all(l.startswith("Reachy Mini ") for l in labels)


def test_x_removes_and_plus_starts_fresh(tmp_path, monkeypatch):
    gm = manager(tmp_path, monkeypatch, n=1, data=demo_table())
    gm.save_config({"settings": {"laptop_seats": ["sim:1"]}})
    seats = gm.seats()
    for s in seats:
        if c.is_laptop_seat(s):
            s["persona"] = "Edited."
    gm.save_config({"seats": seats})
    assert laptop(gm)[0]["persona"] == "Edited."
    # X: the page sends the list without it (and may still send its card).
    gm.save_config({"seats": seats, "settings": {"laptop_seats": []}})
    assert laptop(gm) == [] and all(s["key"] != "sim:1" for s in gm.cfg["seats"])
    gm.save_config({"settings": {"laptop_seats": ["sim:1"]}})
    assert laptop(gm)[0]["persona"] == "Against."


def test_two_robots_with_one_label_are_refused(tmp_path, monkeypatch):
    import asyncio
    data = demo_table()
    data["seats"][1]["character"] = "reachy mini 1"
    gm = manager(tmp_path, monkeypatch, n=2, data=data)
    out = asyncio.run(gm._ensure_session())
    assert out["ok"] is False and "called" in out["error"]


def test_prompts_say_they_are_robots_without_names(tmp_path, monkeypatch):
    rules = c.COMMON_RULES
    assert "Reachy Mini" in rules and "not humans" in rules and "NO NAMES" in rules
    assert all(d["character"].startswith("Reachy Mini") for d in c.DEFAULT_CHARACTERS)
    assert c.strip_leading_name("Reachy Mini 2, that is not how music works.",
                                ["Reachy Mini 2", "Reachy Mini"]) == "That is not how music works."


# ------------------------------------------------- after the home run, 2026-10-25
from test_group_per_robot import talk  # noqa: E402

TWO = [{"key": "1", "name": "reachy1", "character": "Reachy Mini 1"},
       {"key": "2", "name": "laptop", "character": "Reachy Mini 2"}]


def group():
    t = talk(c.GroupTalk, [dict(s) for s in TWO])
    t.m.transcript = []
    return t


def robot(t, who, text, **kw):
    t.m.transcript.append({"kind": "robot", "who": who, "character": who, "text": text,
                           "move": kw.pop("move", "build"), **kw})


def test_a_robot_does_not_repeat_its_move_until_two_others():
    t = group()
    robot(t, "reachy1", "a", gesture="headbanger_combo")
    robot(t, "reachy1", "b", gesture="success1")
    for _ in range(20):
        line = t.make_line({"speaker": "Reachy Mini 1", "text": "Real point.",
                            "gesture": "headbanger_combo"}, voice=False)
        assert line.gesture not in ("headbanger_combo", "success1")
    line = t.make_line({"speaker": "Reachy Mini 1", "text": "x", "gesture": "yes1"}, voice=False)
    assert line.gesture == "yes1"


def test_questions_to_the_room_are_not_asked_again():
    t = group()
    robot(t, "reachy1", "Raise your hand if you listened to an AI track today.", move="people")
    _system, user = t.prompt(False, False, "")
    assert "Already asked to the people" in user and "Raise your hand" in user


def test_a_line_cut_by_a_noise_is_picked_up_again():
    t = group()
    robot(t, "laptop", "Can your weights and biases break a string?", spoken="Can your weights and...",
          cut=True, cut_noise=True)
    system, user = t.prompt(False, False, "")
    assert "[cut off by a noise; nobody spoke]" in user and "picks its point up again" in user
    assert "SUBSTANCE FIRST" in system and "Never invent facts" in system


def test_the_page_sees_the_words_while_the_person_talks():
    import asyncio
    t = group()
    shown = []
    t.m.live_people = shown.append

    class Ears:
        capturing = True
    t.s.ears = Ears()

    async def transcribe(pcm, prompt="", language=""):
        return "I think a person plays guitar better", "en"
    t.services.transcribe = transcribe
    asyncio.run(t.live_words(b"\0" * 32000))
    assert shown == ["I think a person plays guitar better"]
    Ears.capturing = False                       # the turn is over: nothing late
    asyncio.run(t.live_words(b"\0" * 32000))
    assert len(shown) == 1


def test_stop_lets_every_robot_close_then_ends():
    import asyncio
    t = group()
    t.m.publish_state = lambda: None
    t.m.add_turn = t.m.log_turn = lambda entry, **kw: None

    class Ears:
        capturing = False

        def reset_capture(self):
            pass
    t.s.ears = Ears()
    t.last_robot = "1"
    written, spoken = [], []

    async def prepare(opening=False, final=False, extra_human=None, speaker=None):
        written.append((speaker["character"], final, list(t.closing_said)))
        return c.Line(seat=speaker, move="wrap", text="Last word of " + speaker["character"],
                      final=True, nudge="", director_s=0.0)

    async def speak(line, entry, cut_by_people):
        spoken.append((line.seat["character"], cut_by_people, entry.get("closing")))
        return True
    t.prepare, t.speak = prepare, speak
    asyncio.run(t.close_round())
    # Whoever did not speak last goes first; nobody is cut off by the people.
    assert spoken == [("Reachy Mini 2", False, True), ("Reachy Mini 1", False, True)]
    assert all(f for _, f, _ in written)
    assert written[1][2] == ["Last word of Reachy Mini 2"]


def test_plus_one_adds_a_minute_to_the_running_conversation_only(tmp_path, monkeypatch):
    import asyncio
    gm = manager(tmp_path, monkeypatch, n=1, data=demo_table())
    assert gm.more_time(60)["ok"] is False                 # nothing running
    t = group()
    gm.convo = t
    monkeypatch.setattr(c.GroupManager, "running", property(lambda self: True))
    before = t.limit()
    out = gm.more_time(60)
    assert out["ok"] and t.limit() == before + 60 and out["limit_s"] == round(before + 60)
    assert gm.cfg["settings"].get("minutes", 5) == c.DEFAULT_SETTINGS["minutes"]
    out = asyncio.run(gm.finish())                          # Stop: the closing round
    assert out == {"ok": True, "closing": True} and t.closing
    assert gm.more_time(60)["ok"] is False                  # too late to add time


def test_a_stray_word_is_not_an_answer():
    t = group()
    # After a question to the room: real one-word answers count...
    for word in ("Yes.", "Nope", "Definitely!", "Two", "Sure"):
        assert not t.junk(word, True), word
    # ...words made out of a noise do not (home run 3: "Adrian", "close").
    for word in ("Adrian", "close", "airway", "hushed"):
        assert t.junk(word, True), word
    assert not t.junk("I didn't", True) and not t.junk("No, I wouldn't.", False)


def test_a_sentence_cut_by_a_pause_waits_for_the_rest():
    for text in ("When I think", "I think that", "Because the...", "Well, I would say"):
        assert c.unfinished(text), text
    for text in ("I don't think so.", "Yes", "No, I wouldn't.", "Really?",
                 "I would like an AI to make my music, it's very convenient",
                 "When I think about it, no."):
        assert not c.unfinished(text), text


def test_the_robots_wait_while_the_person_finishes_the_sentence():
    import asyncio
    t = group()
    t.m.set_status = lambda st: None
    turns = []
    t.m.add_turn = lambda entry, **kw: turns.append(entry)
    t.m.log_turn = lambda entry, **kw: None
    t.m.live_people = lambda text: None

    async def look(_seat):
        pass
    t.s.look = look

    class Ears:
        capturing = False
        takes = 0

        def finished(self):
            return True

        def silence(self):
            return 0.0

        def take(self, keep=False):
            Ears.takes += 1
            Ears.capturing = False
            return b"\0" * 16000, "1", 1.0, c.time.monotonic()
    t.s.ears = Ears()

    async def respond(pcm, key, prefix=""):
        if not prefix:
            return "When I think", None
        return prefix + " about my favourite band, AI could never write that.", None
    t.respond = respond

    async def go():
        async def resume():                 # the person goes on after 0.5 s
            await asyncio.sleep(0.5)
            Ears.capturing = True
        asyncio.ensure_future(resume())
        return await t.hear_people()
    spoke, _answer = asyncio.run(go())
    said = [e["text"] for e in turns if e["kind"] == "human"]
    assert spoke and said == ["When I think about my favourite band, AI could never write that."]


def test_free_talk_has_no_topic_and_no_sides():
    seats = [{"key": "1", "name": "reachy1", "character": "Reachy Mini 1",
              "persona": "Argues FOR: AI will replace artists."},
             {"key": "2", "name": "laptop", "character": "Reachy Mini 2",
              "persona": "Argues AGAINST: AI can never replace artists."}]
    t = talk(c.FreeTalk, seats, topic="AI and music")
    t.m.transcript = []
    system, user = t.prompt(True, False, "")
    assert "no set topic" in system and "AI and music" not in system
    assert "Argues FOR" not in system and c.FREE_PERSONAS[0] in system
    assert "something fun and surprising" in user
    _system, user = t.prompt(False, True, "", speaker=seats[0])
    assert "warm or funny last word" in user
    # Group talk keeps the topic and the sides.
    g = talk(c.GroupTalk, seats, topic="AI and music")
    g.m.transcript = []
    system, _user = g.prompt(False, False, "")
    assert "AI and music" in system and "Argues FOR" in system
    assert c.MODE_CLASS["free"] is c.FreeTalk and "free" in c.MODES


# ------------------------------------------- motion through the whole line, 2026-10-25
from hub.group import moves  # noqa: E402
from hub.group import robots as robots_mod  # noqa: E402


def test_follow_up_moves_fit_the_speech_that_is_left():
    import random
    random.seed(3)
    # Plenty left: one more of the same feeling first...
    first = moves.filler("enthusiastic1", [], 6.0)
    group = next(n for _l, n in moves.GROUPS if "enthusiastic1" in n)
    assert first in group and first != "enthusiastic1"
    # ...then quieter talking moves, never longer than what is left (+ slack).
    nxt = moves.filler("enthusiastic1", [first], 3.0)
    assert nxt in moves.TALKING and moves.duration(nxt) <= 3.0 + moves.FIT_SLACK_S
    assert moves.filler("enthusiastic1", [first], 1.0) is None       # the sway carries the end
    # Calm robots: one follow-up at most, and none without a gesture.
    assert moves.filler("", [], 6.0, calm=True) is None
    assert moves.filler("yes1", ["x"], 6.0, calm=True) is None


class PacedLink(robots_mod._Link):
    """A robot link with a real playback clock that records what arrives when."""

    def __init__(self):
        super().__init__("1", "reachy1", True)
        self.sent, self.ended_at, self.motions = [], None, []

    def _latency_s(self):
        return 0.0

    async def play(self, pcm):
        samples = self._samples(pcm)
        self.sent.append((c.time.monotonic(), samples.size))
        self._account(samples.size)

    async def end_line(self):
        self.ended_at = c.time.monotonic()

    async def stop_audio(self):
        self._reset_clock()

    async def motion(self, cmd):
        self.motions.append(cmd)


def test_audio_is_paced_and_the_line_ends_when_the_speech_does():
    import asyncio
    t = group()
    t.m.set_status = lambda st: None
    t.m.add_turn = t.m.log_turn = lambda entry, **kw: None
    link = PacedLink()
    t.s.links = {"1": link}

    class Ears:
        capturing = False

        def add_reference(self, *a):
            pass

        def drop_reference(self, *a):
            pass
    t.s.ears = Ears()
    gestures = []

    async def gesture(key, name):
        gestures.append((c.time.monotonic(), name))
        return True
    t.s.gesture = gesture
    seat = t.seats[0]
    seat["gestures"] = "lively"
    line = c.Line(seat=seat, move="build", text="x" * 30, final=False, nudge="",
                  director_s=0.0, gesture="enthusiastic1")
    line.audio.add(b"\0\0" * 16000 * 6)            # 6 s of speech, all downloaded at once
    line.audio.finish()

    async def go():
        t0 = c.time.monotonic()
        await t.speak(line, {"id": 1}, cut_by_people=False)
        return t0
    t0 = asyncio.run(go())
    first_sent, last_sent = link.sent[0][0] - t0, link.sent[-1][0] - t0
    # Not all at once: the last piece left about AUDIO_LEAD_S before the end.
    assert last_sent > 6.0 - c.AUDIO_LEAD_S - 0.3 and first_sent < 0.2
    assert sum(n for _t, n in link.sent) == 16000 * 6
    # "Line finished" only once the speech is over (it stops the sway).
    assert link.ended_at - t0 >= 5.9
    # The line's own move first, then another before the end.
    assert gestures[0][1] == "enthusiastic1" and len(gestures) >= 2


def test_no_dances_and_fillers_are_all_real_moves():
    assert "chicken_peck" not in moves.menu() and moves.command("headbanger_combo") is None
    for left in (2.0, 3.0, 5.0, 8.0):
        for g in ("enthusiastic1", "displeased1", ""):
            pick = moves.filler(g, [], left)
            assert pick is None or moves.command(pick)[0]["type"] == "emotion"


def test_the_camera_only_when_someone_asks_a_robot_to_look():
    asks = ["What do you see?", "Can you see me?", "Look at this!", "What am I holding?",
            "How many fingers am I holding up?", "What color is my shirt?", "What's this?",
            "Describe the room.", "Use your camera, what is in my hand?",
            "Reachy, what do you see on the table?", "Do you two see the cup?",
            "מה אתה רואה?", "מה אני מחזיק ביד?", "תסתכל על זה", "איזה צבע החולצה שלי?"]
    for text in asks:
        assert c.wants_eyes(text), text
    # Said in passing (the 2026-10-25 runs): no picture.
    passing = ["A human being on stage sweating is much more enjoying to see as the audience.",
               "A robotic arm playing the guitar on the stage could be a nice show.",
               "It seems AI music is everywhere.", "I watch concerts every week.",
               "You see, the thing is that people want soul.", "Let's see what happens.",
               "I swear robots will never play like that.", "Robots should vote.",
               "I'd love to see AI fail at jazz.", "He showed me a playlist yesterday.",
               "אני רוצה לראות הופעה חיה", "זה נראה לי טוב"]
    for text in passing:
        assert not c.wants_eyes(text), text
