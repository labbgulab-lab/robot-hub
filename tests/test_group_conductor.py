"""Group conversation: the pure parts of the conductor and the ears."""

import time

import numpy as np

from hub.group import conductor as c
from hub.group import moves
from hub.group.ears import Ears, rms_blocks


def test_leading_name_is_dropped():
    names = ["Dor", "Noa", "דור", "נועה"]
    assert c.strip_leading_name("Dor, that is nonsense.", names) == "That is nonsense."
    assert c.strip_leading_name("נועה, את טועה לגמרי.", names) == "את טועה לגמרי."
    # A name later in the line stays; so does a line that is only a name.
    assert c.strip_leading_name("I told Dor already.", names) == "I told Dor already."
    assert c.strip_leading_name("Dor!", names) == "Dor!"


def test_interjection_is_dropped_before_a_cached_one():
    assert c.strip_interjection("Wait, wait! You're skipping the best part.") == \
        "You're skipping the best part."
    assert c.strip_interjection("Oh, come on! Hold on, how can they vote at all?") == \
        "How can they vote at all?"
    assert c.strip_interjection("רגע, רגע! זה פשוט לא נכון בכלל.") == "זה פשוט לא נכון בכלל."
    # Too little left: keep it as it is.
    assert c.strip_interjection("No, no!") == "No, no!"
    assert c.strip_interjection("Robots cannot vote.") == "Robots cannot vote."


def test_robot_words_are_taken_out_of_the_person():
    robot = ["Imagine if every vote was this smart and speedy!"]
    said = "I think so. imagine if every vote was this smart and fast"
    assert c.strip_echo(said, robot) == "I think so. fast"
    assert c.strip_echo("nothing in common here", robot) == "nothing in common here"


def test_vision_words():
    assert c.wants_eyes("Tamar, what do you see?")
    assert c.wants_eyes("מה אני מחזיק ביד?")
    assert not c.wants_eyes("Robots should vote.")


def test_gesture_catalog():
    assert moves.EMOTIONS, "assets/group_moves.json is missing"
    cmd, dur = moves.command("laughing1")
    assert cmd == {"type": "emotion", "name": "laughing1"} and dur > 1
    assert moves.command("not-a-move") is None
    # Dances are off until the robots have the dance library (2026-10-25:
    # "dance ignored" on the robot, the head still for the dance's length).
    assert moves.command("yeah_nod") is None and "headbanger_combo" not in moves.menu()
    if moves.DANCES_ON_ROBOTS:
        assert moves.command("yeah_nod")[0]["type"] == "dance"
    assert moves.reaction_for("Dor") in moves.EMOTIONS
    assert moves.reaction_for("Someone", "approve") in moves.EMOTIONS


class FakeVAD:
    """Speech probability = 1 for anything loud: the ears' echo logic alone."""

    def reset(self):
        pass

    def prob(self, block):
        return 1.0 if np.abs(block).max() > 300 else 0.0


def tone(level, n=512):
    return (np.sin(np.arange(n) * 0.3) * level * 32768).astype(np.int16)


def test_ears_learn_the_echo_and_hear_a_person_over_it():
    ears = Ears(["a", "b"], min_level=0.0, barge_db=8.0, vad_factory=FakeVAD)
    ears.set_open(True)
    # Robot "a" plays at rms ~0.07 for 3 s; mic b hears it at 0.1x.
    played = tone(0.1, 512 * 100).tobytes()
    ears.add_reference("a", time.monotonic(), rms_blocks(played))
    for _ in range(60):
        ears.feed("b", tone(0.01))
        ears.feed("a", tone(0.05))
        assert not ears.capturing
    assert 0.05 < ears.coupling("b", "a") < 0.3
    # Mic b has learned only robot a: its guess for robot c is twice that, not "deaf".
    assert ears.coupling("b", "c") == 2 * ears.coupling("b", "a")
    assert ears.coupling("x", "x") > 1   # a robot at its own mic: deaf until learned
    # A person near b, much louder than the echo, takes the floor.
    for _ in range(8):
        ears.feed("b", tone(0.12))
    assert ears.capturing and ears.during_robot


def test_closed_ears_ignore_robot_time():
    ears = Ears(["a"], min_level=0.0, barge_db=None, vad_factory=FakeVAD)
    ears.set_open(True)
    ears.add_reference("a", time.monotonic(), rms_blocks(tone(0.1, 512 * 50).tobytes()))
    for _ in range(20):
        ears.feed("a", tone(0.3))
    assert not ears.capturing


def test_hebrew_pronunciation_for_the_voice():
    assert c.pronounce("הרובוטים צריכים להצביע") == "ha robotim צריכים להצביע"
    assert c.pronounce("רובוט אחד") == "robot אחד"
    assert c.pronounce("ולרובוט יש") == "ve le robot יש"
    assert c.pronounce("שלום לאבה לאב!") == "שלום Laba Lab!"
    assert c.pronounce("Robots vote") == "Robots vote"


def test_hedged_stream_races_a_hung_request():
    import asyncio
    calls = []

    def make():
        calls.append(1)
        n = len(calls)

        async def gen():
            if n == 1:
                await asyncio.sleep(30)          # the hung one
            for chunk in (b"a", b"b"):
                yield chunk
        return gen()

    async def run():
        out = []
        async for chunk in c.hedged_stream(make, 0.05):
            out.append(chunk)
        return out

    assert asyncio.run(asyncio.wait_for(run(), 3)) == [b"a", b"b"]
    assert len(calls) == 2


def test_compressed_voice_decodes_to_16k():
    from hub.group.services import compressed, decode_to_16k
    pcm = tone(0.2, 16000 * 2).tobytes()             # 2 s at 16 kHz
    _name, data, _mime = compressed(pcm)
    out = decode_to_16k(data)
    assert abs(len(out) / 32000 - 2.0) < 0.15


def test_hedged_stream_reports_refusals_at_once():
    import asyncio
    from hub.group.services import ServiceError

    def make():
        async def gen():
            raise ServiceError("no credits", 429, "insufficient_quota")
            yield b""                                  # noqa: unreachable, makes a generator
        return gen()

    async def run():
        async for _chunk in c.hedged_stream(make, 0.05):
            pass

    t0 = time.monotonic()
    try:
        asyncio.run(run())
    except ServiceError as exc:
        assert exc.status == 429
    assert time.monotonic() - t0 < 2
