"""Group talk opens with a lab intro (Tomer, 2026-10-25): every robot one
line about Laba Lab and Guy Laban's work, in seat order, then the first
robot's second line is the usual opener on the topic. The robots answer
questions about the lab from Pepper's lab facts."""

import asyncio

from hub.group import conductor as c
from test_group_per_robot import seats3, talk


def two_robots():
    return seats3(3, 3)[:2]


def test_lab_facts_come_from_peppers_file():
    facts = c.lab_facts()
    assert facts.startswith("## The lab")
    assert "Guy Laban" in facts and "Pepper may use" not in facts
    # General only (Tomer): no joining/contact, no people list, no room.
    assert "@" not in facts and "## People" not in facts and "room" not in facts
    assert "## Projects" in facts


def test_every_prompt_has_the_lab():
    t = talk(c.GroupTalk, two_robots(), topic="AI and music")
    system, _user = t.prompt(False, False, "")
    assert "LAB FACTS" in system and "Guy Laban" in system and "Laba Lab" in system


def test_intro_then_first_robot_opens_the_topic():
    t = talk(c.GroupTalk, two_robots(), topic="AI and music")
    t.s.voice = lambda line: asyncio.sleep(0)
    asked = []

    async def ask(system, user, image=None, model=""):
        asked.append(user)
        if "lab intro: exactly" in user:
            return {"lines": [
                {"speaker": "Noa", "text": "Welcome to Laba Lab, led by Dr. Guy Laban at Ben-Gurion University."},
                {"speaker": "Dor", "text": "The lab studies how people talk with and feel about robots like us."}],
                "handover": "Well, let's get into it. I understand you want to talk about AI and music today, so let's get to it."}
        return {"speaker": "Dor", "text": "AI will never replace a real songwriter, and here is why."}
    t.ask = ask

    async def go():
        opener = t.opener()
        return await t.intro_task, await opener
    intro, opener = asyncio.run(go())
    # Noa, Dor, then Noa's hand-over to the topic...
    assert [ln.seat["character"] for ln in intro] == ["Noa", "Dor", "Noa"]
    assert all(ln.move == "intro" for ln in intro)
    assert intro[-1].text.startswith("Well, let's get into it")
    # ...and Dor starts the debate, whatever the writer said, knowing the intro.
    assert opener.seat["character"] == "Dor"
    assert "The lab intro and the hand-over" in asked[-1] and "Welcome to Laba Lab" in asked[-1]


def test_no_intro_when_off_or_in_free_talk():
    off = talk(c.GroupTalk, two_robots(), lab_intro=False)
    assert not off.wants_intro()
    assert not talk(c.FreeTalk, two_robots()).wants_intro()
    assert talk(c.GroupTalk, two_robots()).wants_intro()


def test_intro_failure_falls_back_to_the_plain_opener():
    t = talk(c.GroupTalk, two_robots(), topic="AI and music")
    t.s.voice = lambda line: asyncio.sleep(0)

    async def ask(system, user, image=None, model=""):
        if "lab intro: exactly" in user:
            return {"lines": []}
        return {"speaker": "Dor", "text": "Machines do not feel the blues."}
    t.ask = ask

    async def go():
        return await t.opener()
    line = asyncio.run(go())
    assert line.text == "Machines do not feel the blues."


def test_questions_about_guy_or_the_lab_get_the_reminder():
    assert c.lab_question_note("Who is Guy Laban?") == c.GUY_NOTE
    assert c.lab_question_note("how can I join the lab") == c.LAB_NOTE
    assert c.lab_question_note("AI will never write a good song") == ""
    t = talk(c.GroupTalk, two_robots(), topic="AI and music")
    _system, user = t.prompt(False, False, "", extra_human=("Who is Guy Laban?", None))
    assert "real respect" in user


def test_labalab_is_spoken_as_two_words():
    t = talk(c.GroupTalk, two_robots())
    line = t.make_line({"speaker": "Noa", "text": "Dr Guy Laban leads LabaLab at BGU."},
                       voice=False)
    assert line.text == "Dr Guy Laban leads Laba Lab at BGU."
