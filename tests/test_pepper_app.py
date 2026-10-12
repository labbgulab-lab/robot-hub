"""pepper_app: the robot link, the chest screen, the AI's tools and the
laptop-only guard. No robot and no OpenAI here: a fake agent speaks the real
frame protocol over a real socket."""

import asyncio
import json
import struct

import pytest

from pepper_app.audio import Resampler
from pepper_app.brain import EXPERIENCES, instructions, tools
from pepper_app.robot import RobotLink
from pepper_app.screen import Screen
from pepper_app.speech import is_hebrew


# ------------------------------------------------------------ the link
async def _fake_agent(port, token, *, answer=True):
    r, w = await asyncio.open_connection("127.0.0.1", port)

    def frame(kind, payload):
        w.write(kind + struct.pack(">I", len(payload)) + payload)

    frame(b"J", json.dumps({"ev": "hello", "token": token, "info": {"name": "Pepper"},
                            "speaker_mode": "naoqi", "pid": 1}).encode())
    frame(b"J", json.dumps({"ev": "frame", "w": 320, "h": 240, "faces": [[1, 2, 3, 4]]}).encode())
    frame(b"I", b"\x89PNGfake")
    frame(b"M", b"\x01\x00" * 160)
    await w.drain()
    got = []
    while answer:
        head = await r.readexactly(5)
        body = await r.readexactly(struct.unpack(">I", head[1:])[0])
        got.append((head[:1], body))
        if head[:1] == b"J":
            msg = json.loads(body)
            ok = msg["cmd"] != "explode"
            frame(b"J", json.dumps({"id": msg["id"], "ok": ok, "did": msg["cmd"],
                                    **({} if ok else {"error": "boom"})}).encode())
            await w.drain()
            if msg["cmd"] == "bye":
                break
    w.close()
    return got


def test_the_link_carries_commands_audio_mic_and_camera():
    async def run():
        link = RobotLink("127.0.0.1", 0)
        await link.start(deploy=False)
        mic = []
        link.on_mic = mic.append
        agent = asyncio.create_task(_fake_agent(link.listen_port, link.token))
        for _ in range(100):
            if link.connected and mic:
                break
            await asyncio.sleep(0.02)
        assert link.connected and link.speaker_mode == "naoqi"
        assert link.info["name"] == "Pepper"
        assert mic == [b"\x01\x00" * 160]
        assert link.last_frame[1] == b"\x89PNGfake" and link.last_frame[0]["faces"] == [[1, 2, 3, 4]]
        assert (await link.call("move", name="wave"))["did"] == "move"
        with pytest.raises(RuntimeError, match="boom"):
            await link.call("explode")
        link.send_audio(b"\x00\x00" * 100)
        await link.call("bye")
        got = await agent
        assert (b"S", b"\x00\x00" * 100) in got
    asyncio.run(run())


def test_an_agent_with_the_wrong_token_is_refused():
    async def run():
        link = RobotLink("127.0.0.1", 0)
        await link.start(deploy=False)
        await _fake_agent(link.listen_port, "not-the-token", answer=False)
        await asyncio.sleep(0.1)
        assert not link.connected
    asyncio.run(run())


def test_a_call_fails_fast_when_pepper_is_not_connected():
    link = RobotLink("127.0.0.1", 0)
    with pytest.raises(ConnectionError):
        asyncio.run(link.call("say", text="hi"))


# ------------------------------------------------------------ the screen
def test_a_tap_counts_only_for_the_choice_on_screen(tmp_path):
    s = Screen(tmp_path)
    s.show({"kind": "choice", "question": "?", "options": [{"label": "Dog"}, {"label": "Cat"}]}, "ai")
    v = s.version
    assert s.tap(v - 1, 0) is None            # an older screen
    assert s.tap(v, 5) is None                # no such option
    assert s.tap(v, 1) == "Cat" and s.state()["picked"] == "Cat"
    s.show({"kind": "welcome"}, "you")
    assert s.tap(s.version, 0) is None


def test_presentations_store_slides_and_name_pictures(tmp_path):
    s = Screen(tmp_path)
    deck = s.new_deck("Animals")
    s.add_slide(deck["id"], "golden_dog.png", b"png1")
    s.add_slide(deck["id"], "Cat.JPG", b"jpg2")
    with pytest.raises(ValueError):
        s.add_slide(deck["id"], "notes.pptx", b"x")
    item = s.slide_item(deck["id"], 1)
    assert item["kind"] == "slide" and item["count"] == 2 and item["title"] == "Cat"
    assert s.slide_path(deck["id"], "002.jpg").read_bytes() == b"jpg2"
    assert s.images_by_name() == {"golden dog": item["image"].replace("002.jpg", "001.png"), "cat": item["image"]}
    with pytest.raises(KeyError):
        s.slide_path(deck["id"], "../deck.json")
    with pytest.raises(KeyError):
        s.deck("../../etc")
    s.delete_deck(deck["id"])
    assert s.decks() == []


# ------------------------------------------------------------ the AI's setup
def test_screen_tools_are_offered_only_when_the_ai_drives_the_screen():
    names = lambda ts: {t["name"] for t in ts}
    assert names(tools(False, False)) == {"gesture"}
    assert {"show_choice", "show_message", "show_slide", "clear_screen"} <= names(tools(True, False))
    assert "set_step" in names(tools(True, True))


def test_instructions_carry_language_pictures_slides_and_turn_rules():
    text = instructions("feelings:emoji", "he", True, True, ["dog", "cat"],
                        {"name": "Lab", "slides": [{"title": "Welcome"}, {"title": "Robots"}]})
    assert "Hebrew" in text and "dog, cat" in text and "1. Welcome; 2. Robots" in text
    assert "STRICTLY turn-based" in text and "Never use emoji" in text
    assert "camera" not in instructions("free", "en", False, False, [], None)
    with_emoji = instructions("feelings:emoji", "auto", False, True, [], None, ["😊", "😢"])
    assert "ONLY from this list" in with_emoji and "😊 😢" in with_emoji


def test_demo_experience_list_is_short():
    """Tomer, 2026-10-12: only the scripted demo, the AI-led Feelings Together and
    free conversation stay; lab tour, dog-or-cat and words-only were removed."""
    from pepper_app.brain import DEFAULT_EXPERIENCE, EXPERIENCES
    assert set(EXPERIENCES) == {"feelings:script", "feelings:emoji", "free"}
    assert DEFAULT_EXPERIENCE == "feelings:script"


def test_resampler_turns_pepper_16k_into_24k():
    up = Resampler(16000, 24000)
    total = sum(len(up(b"\x10\x00" * 1600)) for _ in range(10)) // 2
    assert abs(total - 24000) < 4


def test_hebrew_is_detected():
    assert is_hebrew("שלום Pepper") and not is_hebrew("Hello")


# ------------------------------------------------------------ the guard
def test_controls_answer_this_laptop_only_but_the_tablet_reaches_the_screen(tmp_path):
    from fastapi.testclient import TestClient

    from pepper_app.server import create_app
    app = create_app("", 0, 0, tmp_path)
    local = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000))
    tablet = TestClient(app, base_url="http://172.20.10.4:8780", client=("172.20.10.3", 5000))
    rebind = TestClient(app, base_url="http://evil.example", client=("127.0.0.1", 5000))
    assert local.get("/api/status").status_code == 200
    assert tablet.get("/api/status").status_code == 403
    assert tablet.post("/api/say", json={"text": "hi"}).status_code == 403
    assert rebind.get("/api/status").status_code == 403
    assert tablet.get("/screen/state?tablet=1").json()["item"]["kind"] == "welcome"
    assert app.state.pepper.screen.health()["connected"]
    assert tablet.post("/screen/tap", json={"v": 1, "i": 0}).json() == {"ok": False}


def test_screen_emoji_only_from_the_allowed_list_and_never_inside_text(tmp_path):
    s = Screen(tmp_path)
    dog, robot, star = "🐶", "🤖", "⭐️"
    choice = {"kind": "choice", "question": "Which? " + dog,
              "options": [{"label": "Dog " + dog, "emoji": dog}, {"label": "Robot", "emoji": robot},
                          {"label": dog}]}
    s.show(choice, "ai", {dog, "⭐"})                  # an experience "with emoji"
    item = s.state()["item"]
    assert item["question"] == "Which?"
    assert item["options"] == [{"label": "Dog", "emoji": dog}, {"label": "Robot"}]
    s.show({"kind": "message", "text": "All done!", "emoji": star}, "ai", {"⭐"})
    assert s.state()["item"]["emoji"] == "⭐"           # the variation selector is dropped
    s.show(choice, "ai", None)                             # "words only"
    assert all("emoji" not in o for o in s.state()["item"]["options"])


def test_the_ai_gets_emoji_fields_only_in_emoji_experiences():
    assert '"emoji"' not in json.dumps(tools(True, True, emoji=False))
    assert '"emoji"' in json.dumps(tools(True, True, emoji=True))


# ------------------------------------------------------------ turn-taking
def test_noise_and_fillers_are_not_answers():
    from pepper_app.brain import real_answer
    for noise in ("", "hmm", "Um... uh", "אה", "...", "  "):
        assert not real_answer(noise), noise
    for answer in ("yes", "no", "כן", "לא", "Dog", "7", "I think sad", "אני חושבת עצוב"):
        assert real_answer(answer), answer


class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


async def _no_flush():
    pass


def _brain(speaking=lambda: False, choice=lambda: False):
    from pepper_app.brain import Brain
    events = []
    b = Brain(openai_key="k", eleven_key="", play=lambda pcm: None, flush=_no_flush,
              tool=lambda n, a: "ok", emit=lambda k, d: events.append((k, d)), frame=lambda: None,
              speaking=speaking, choice_open=choice, fallback=None)
    b.ws, b.running, b.cfg = _WS(), True, {"experience": "feelings:emoji"}
    return b, events


def _types(b):
    return [m["type"] for m in b.ws.sent]


def test_a_filler_is_ignored_and_a_real_answer_starts_peppers_turn():
    async def run():
        b, events = _brain()
        b._enter_waiting(expects=True)
        await b._on_answer("hmm", item_id="item_1")
        assert _types(b) == ["conversation.item.delete"]            # noise leaves no trace
        assert any(k == "heard" for k, _ in events) and b.turn == "waiting"
        await b._on_answer("Sad", item_id="item_2")
        assert _types(b)[-1] == "response.create" and b.turn == "pepper"
    asyncio.run(run())


def test_speech_while_pepper_talks_is_dropped_but_a_tap_waits_its_turn():
    async def run():
        playing = {"on": True}
        b, events = _brain(speaking=lambda: playing["on"])
        b.turn, b._reply_done = "pepper", True
        await b._on_answer("my answer", item_id="item_3")
        assert "response.create" not in _types(b)
        await b.tap("Happy")
        assert b._queued_answers == ["[screen tap] Happy"]
        playing["on"] = False                    # Pepper finishes speaking
        b.tasks = [asyncio.create_task(b._watchdog())]
        await asyncio.sleep(0.6)
        b.tasks[0].cancel()
        sent = b.ws.sent
        assert sent[-2]["item"]["content"][0]["text"] == "[screen tap] Happy"
        assert sent[-1]["type"] == "response.create"
    asyncio.run(run())


def test_no_answer_means_one_reask_then_waiting(monkeypatch):
    import pepper_app.brain as B

    async def run():
        monkeypatch.setattr(B, "REASK_S", 0.2)
        b, _ = _brain()
        b._last_pepper_text = "How does Dana feel?"
        b.turn, b._reply_done = "pepper", True
        task = asyncio.create_task(b._watchdog())
        await asyncio.sleep(1.0)
        assert _types(b).count("response.create") == 1          # the one re-ask
        b._last_pepper_text = "How does Dana feel?"
        b._reply_done = True                                     # the re-ask was spoken
        await asyncio.sleep(1.5)
        assert b.turn == "waiting" and b.reasked
        assert _types(b).count("response.create") == 1          # and then it just waits
        await b._on_answer("Sad")                                # an answer resets it
        assert _types(b).count("response.create") == 2 and not b._reask_turn
        task.cancel()
    asyncio.run(run())


# ------------------------------------------------------------ movements
def test_only_movements_tested_on_this_pepper_are_offered(monkeypatch):
    # 2026-10-06 on the robot: Hey_1, Explain_1, big yes/no, the arm poses, hands,
    # head left/center/right, StandInit. Nothing else (no Rest, no wheels, no guessed animations).
    import importlib.util
    import sys
    import types
    fake = types.ModuleType("naoqi")
    fake.ALBroker = fake.ALModule = fake.ALProxy = object
    monkeypatch.setitem(sys.modules, "naoqi", fake)
    spec = importlib.util.spec_from_file_location(
        "pepper_agent", "pepper_app/agent/pepper_agent.py")
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    assert set(agent.MOVES) == {"wave", "yes", "no", "arms_up", "arms_wide",
                                "right_arm_up", "left_arm_up", "hands", "walk"}
    assert agent.ANIMATIONS == {"wave": "animations/Stand/Gestures/Hey_1"}
    from pepper_app.brain import MOVES as AI_MOVES
    assert set(AI_MOVES) <= set(agent.MOVES)


# ------------------------------------------------- scripted experience
def test_script_runs_screen_with_question_then_reaction(monkeypatch):
    """Each step: the screen changes, then the question is said; an answer gets
    one reaction on the same screen; the next step's screen comes after it."""
    from pepper_app import script

    class FakeEars:
        def __init__(self, *a, **k):
            self.commit_gap_s = None
        async def start(self):
            pass
        async def stop(self):
            pass
        def push(self, pcm):
            pass
        def clear(self):
            pass

    monkeypatch.setattr(script.eleven, "ScribeEars", FakeEars)
    monkeypatch.setattr(script, "REASK_S", 30.0)
    events = []

    async def synth(text):
        return b"\x00\x00" * 10

    async def flush():
        pass

    def tool(name, args):
        events.append(("screen" if name.startswith("show") else name, args.get("question") or args.get("text") or args.get("name")))
        return "ok"

    def emit(kind, data):
        if kind == "chat" and data["role"] == "pepper":
            events.append(("say", data["text"]))

    r = script.ScriptRunner(openai_key="k", eleven_key="e", play=lambda pcm: None, flush=flush,
                            tool=tool, emit=emit, speaking=lambda: False, synth=synth)

    async def phrase(s, answer, source, reaction):
        return "REACT " + reaction
    monkeypatch.setattr(r, "_phrase", phrase)

    async def run():
        await r.start({"experience": "feelings:script", "language": "he"})
        for _ in range(len(script.FEELINGS) - 1):
            for _ in range(200):
                if r.turn == "waiting":
                    break
                await asyncio.sleep(0.01)
            await r.tap("1")
            await asyncio.sleep(0.05)
        for _ in range(200):
            if r.index >= len(script.FEELINGS):
                break
            await asyncio.sleep(0.01)
        await r.stop()

    asyncio.run(run())
    says = [e for e in events if e[0] == "say"]
    # Every step's question, in Hebrew, each followed by one reaction (except the goodbye).
    questions = [s["say"]["he"] for s in script.FEELINGS]
    assert [t for k, t in says if not t.startswith("REACT")] == questions
    assert sum(1 for k, t in says if t.startswith("REACT")) == len(questions) - 1
    # The screen for a step comes right before its question, never during the reaction.
    for i, (k, t) in enumerate(events):
        if k == "say" and t in questions:
            j = i - 1
            while events[j][0] == "gesture":
                j -= 1
            assert events[j][0] == "screen", (t, events[j])


def test_script_reaction_is_ours_and_unclear_asks_for_a_tap():
    """The code decides the option; the reaction is the one written for it. An
    answer it cannot place gets 'please tap', never a guess (2026-10-12: a free
    AI reaction praised the visitor's voice for 'My voice is... Just right')."""
    from pepper_app import script
    r = script.ScriptRunner(openai_key="", eleven_key="e", play=lambda p: None, flush=None,
                            tool=lambda *a: "ok", emit=lambda *a: None, speaking=lambda: False,
                            synth=None)
    r.lang = "he"
    comfort = next(s for s in script.FEELINGS if s["title"] == "Comfort")
    assert r._reaction_for(comfort, "נעים", "tap") == comfort["reactions"][0]["he"]
    assert r._reaction_for(comfort, "שומעים את זה?", "speech") is None
    story = next(s for s in script.FEELINGS if s["title"] == "Story")
    assert r._reaction_for(story, "קואסיט.", "speech") == story["reactions"][1]["he"]
    look = next(s for s in script.FEELINGS if s["title"] == "Look")
    assert r._reaction_for(look, "בלון.", "speech") == look["react"]["balloon"]["he"]
    assert r._reaction_for(look, "כוכב", "speech") == look["react"]["other"]["he"]


@pytest.mark.parametrize("step,answer,expected", [
    ("Choice", "touch", "לגעת"), ("Choice", "I want tapping", "לגעת"), ("Choice", "בלחיצה על המסך", "לגעת"),
    ("Choice", "speak", "לדבר"), ("Choice", "שניהם", "גם וגם"), ("Choice", "השני", "לדבר"),
    ("Comfort", "fast", "מהיר מדי"), ("Comfort", "לא מהיר", "נעים"), ("Comfort", "יותר לאט בבקשה", "מהיר מדי"),
    ("Comfort", "יותר חזק", "too quiet"), ("Comfort", "slow", "too slow"), ("Comfort", "loud", "חזק מדי"),
    ("Comfort", "perfect", "נעים"), ("Comfort", "נאים", "נעים"), ("Comfort", "שומעים את זה?", None),
    ("Faces: happy", "בקצוף מספר אחת", "1"), ("Faces: happy", "the smiling one", "1"),
    ("Faces: surprised", "בקצוף מספר שתיים.", "2"), ("Faces: surprised", "wow", "2"),
    ("Story", "קואסיט.", "כועסת"), ("Story", "nervous", "כועסת"), ("Story", "עצובה וכועסת", "both sad and angry"),
    ("Story", "upset", "עצובה"), ("Feedback", "היה מצוין.", "קל"), ("Feedback", "לא קל", "קשה"),
    ("Feedback", "not bad", "בסדר"),
])
def test_script_places_what_hebrew_speakers_say(step, answer, expected):
    """Each option has a word list in Hebrew and simple English; the longest
    phrase wins ("לא מהיר" is Just right); numbers decide on numbered screens;
    noise asks for a tap (expected None)."""
    from pepper_app import script
    r = script.ScriptRunner(openai_key="", eleven_key="e", play=None, flush=None, tool=None,
                            emit=lambda *a: None, speaking=None, synth=None)
    r.lang = "he"
    s = next(x for x in script.FEELINGS if x["title"] == step)
    labels = [o["label"] for o in s["screen"]["he"][1]["options"]]
    kind, i = r._place(s, answer)
    got = labels[i] if kind == "option" else s["extra"][i]["means"] if kind == "extra" else None
    assert got == expected


def test_free_conversation_is_bare():
    """Free talk: no turn rules, no screen, no gestures, no tools; one short line."""
    from pepper_app.brain import Brain
    text = instructions("free", "he", True, True, ["dog"], None)
    assert "ONE short sentence" in text
    assert "STRICTLY turn-based" not in text and "touch screen on your chest" in text
    assert "show_choice" not in text and "gesture" not in text
    b = Brain(openai_key="k", eleven_key="", play=lambda pcm: None, flush=_no_flush,
              tool=lambda n, a: "ok", emit=lambda k, d: None, frame=lambda: None,
              speaking=lambda: False, choice_open=lambda: False, fallback=None)
    b.cfg = {"experience": "free", "language": "he", "ai_screen": True}
    s = b._session()
    assert s["tools"] == [] and s["tool_choice"] == "none"
    assert s["audio"]["input"]["turn_detection"]["eagerness"] == "medium"
