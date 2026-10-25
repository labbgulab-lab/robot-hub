"""Lines the writer gets wrong are written again once (Tomer, 2026-10-25
evening run): openings that echo the other robot, "raise your hand", the
same "If..., my circuits" joke, the same feelings argument again."""

import asyncio

from hub.group import conductor as c
from test_group_per_robot import seats3, talk

TOPIC = "AI and music: can AI robots and LLMs replace human artists in the real world?"


def test_echo_opening():
    prev = "Licensing deals are how labels will solve it."
    assert c.echo_opening("Licensing deals just pay the lawyers.", prev, TOPIC) == "licensing deals"
    assert c.echo_opening("Lawyers get paid, artists do not.", prev, TOPIC) == ""
    # The topic's own words are not an echo.
    assert c.echo_opening("Music made by AI is still music.", "AI music is fine.", TOPIC) == ""


def test_problems():
    assert any("raise hands" in p for p in c.line_problems(
        "Raise your hand if you streamed an AI song.", "", [], TOPIC))
    own_if = ["If servers are rock stars, my power supply is ready."]
    assert any('"If"' in p for p in c.line_problems(
        "If bots form a band, I am in.", "Bands need people.", own_if, TOPIC))
    assert any("own parts" in p for p in c.line_problems(
        "Cheap beats make my circuits dance.", "Beats are cheap.", own_if, TOPIC))
    feel = ["It never felt heartbreak.", "No soul in a loop."]
    assert any("feelings" in p for p in c.line_problems(
        "A machine cannot feel the blues.", "The blues are a formula.", feel, TOPIC))
    life = ["Real art carries the weight of a messy human life.",
            "Great songs come from the genuine struggles of their creators."]
    assert any("feelings" in p for p in c.line_problems(
        "Nothing beats an artist pouring personal trauma into a guitar.", "Charts love loops.",
        life, TOPIC))
    # Answering the people: no second try for the feelings rule.
    assert c.line_problems("A machine cannot feel the blues.", "", feel, TOPIC) == []
    assert c.line_problems("Royalties go to labels, not composers.",
                           "Streaming numbers prove listeners want speed.", feel, TOPIC) == []


def test_a_bad_line_is_written_again_once():
    t = talk(c.GroupTalk, seats3(3, 3)[:2], topic=TOPIC)
    t.s.voice = lambda line: asyncio.sleep(0)
    t.m.transcript = [{"kind": "robot", "character": "Noa", "who": "reachy1",
                       "text": "Licensing deals are how labels will solve it.", "move": "build"}]
    tries = []

    async def ask(system, user, image=None, model=""):
        tries.append(user)
        if len(tries) == 1:
            return {"speaker": "Dor", "text": "Licensing deals just pay the lawyers."}
        return {"speaker": "Dor", "text": "Lawyers get paid while composers lose their jobs."}
    t.ask = ask
    line = asyncio.run(t.prepare())
    assert len(tries) == 2 and "A first try was" in tries[1]
    assert line.text == "Lawyers get paid while composers lose their jobs."
