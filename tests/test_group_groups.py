"""Robot groups (2026-11-03): robots that talk as one (the same line at the
same moment), move as one (every gesture of one on all), or both -- "Choir"
on the page is one group of every robot doing both."""

import asyncio

from hub.group import conductor as c
from hub.group import robots as robots_mod
from test_group_per_robot import session

FOUR = [{"key": k, "name": "reachy" + k, "character": "Reachy Mini " + k} for k in "1234"]


def test_a_robot_is_in_one_group_at_most():
    groups = c.clean_groups([{"name": "A", "members": ["1", "2", "2"]},
                             {"name": "B", "members": ["2", "3"], "talk": False},
                             "junk"])
    assert [g["members"] for g in groups] == [["1", "2"], ["3"]]
    assert groups[0]["talk"] and groups[0]["move"], "both by default"
    assert not groups[1]["talk"] and groups[1]["move"]
    assert c.clean_groups(None) == []


def test_a_talking_group_is_one_speaker_named_after_the_group():
    seats = [dict(s) for s in FOUR]
    groups = c.clean_groups([{"name": "Choir", "members": ["2", "1"]},
                             {"name": "Dancers", "members": ["3", "4"], "talk": False}])
    speakers, together, mirror = c.plan_groups(seats, groups)
    assert [s["key"] for s in speakers] == ["1", "3", "4"]
    assert speakers[0]["character"] == "Choir" and speakers[0]["members"] == ["1", "2"]
    assert seats[0]["character"] == "Reachy Mini 1", "the robot's own seat is untouched"
    assert together == {"1": ["1", "2"]}
    assert mirror["2"] == ["1", "2"] and mirror["4"] == ["3", "4"]


def test_a_group_needs_two_robots_at_the_table():
    seats = [dict(s) for s in FOUR[:2]]
    groups = c.clean_groups([{"name": "G", "members": ["2", "9"]}])
    speakers, together, mirror = c.plan_groups(seats, groups)
    assert [s["key"] for s in speakers] == ["1", "2"] and not together and not mirror


def test_an_unnamed_group_speaks_under_its_first_robots_label():
    seats = [dict(s) for s in FOUR[:2]]
    speakers, _t, _m = c.plan_groups(seats, c.clean_groups([{"members": ["1", "2"]}]))
    assert speakers[0]["character"] == "Reachy Mini 1"


class Link(robots_mod._Link):
    """A link that records audio, motions and start times."""

    def __init__(self, key, features=("clock", "start_at")):
        super().__init__(key, "reachy" + key, True)
        self.features = set(features)
        self.played, self.motions, self.starts = [], [], []

    async def play(self, pcm):
        self.played.append(len(pcm))
        self._account(len(pcm) // 2)

    async def end_line(self):
        pass

    async def stop_audio(self):
        self._reset_clock()

    async def motion(self, cmd):
        self.motions.append(cmd)

    async def start_at(self, robot_time, start_mono):
        self.starts.append(robot_time)
        self._play_until = max(self._play_until, start_mono)


def test_a_group_line_starts_on_every_robot_at_one_moment():
    a, b = Link("1"), Link("2")
    g = robots_mod.GroupLink([a, b], offset=2.5)
    assert g.synced and g.keys == ["1", "2"]
    asyncio.run(g.play(b"\0\0" * 1600))
    asyncio.run(g.play(b"\0\0" * 1600))
    assert len(a.starts) == 1 and a.starts == b.starts, "one start time, sent once"
    assert abs(a.starts[0] - (c.time.time() + 2.5 + robots_mod.GROUP_START_LEAD_S)) < 0.5
    assert a.played == b.played == [3200, 3200]
    assert g.seconds_left() >= robots_mod.GROUP_START_LEAD_S


def test_an_old_player_in_the_group_means_no_start_time():
    a, b = Link("1"), Link("2", features=())
    g = robots_mod.GroupLink([a, b], offset=0.0)
    asyncio.run(g.play(b"\0\0" * 160))
    assert not g.synced and not a.starts and a.played == b.played


def test_the_session_uses_one_clock_figure_for_a_group():
    s = session([dict(x) for x in FOUR[:3]])
    s.clock_offsets = {"1": 1.000, "2": 1.004, "3": 0.998}
    assert abs(s.group_offset(["1", "2", "3"]) - 1.000) < 1e-9
    assert s.group_offset(["1", "9"]) is None


def test_a_moving_group_does_every_gesture_together():
    s = session([dict(x) for x in FOUR[:3]])
    s.links = {k: Link(k) for k in "123"}
    s.mirror = {"1": ["1", "2"], "2": ["1", "2"]}
    name = c.moves.TALKING[0]
    assert asyncio.run(s.gesture("2", name))
    assert s.links["1"].motions and s.links["1"].motions == s.links["2"].motions
    assert not s.links["3"].motions
    assert s.busy_until["1"] > c.time.monotonic()


def test_a_talking_group_speaks_one_line_on_all_its_robots():
    class M:
        transcript = []
        pending_nudge = ""
        status = {}
        cfg = {"settings": {"groups": [{"name": "Choir", "members": ["1", "2"]}]}}

        def note(self, text):
            pass

        def set_status(self, st):
            pass

        def add_turn(self, entry, **kw):
            pass

        log_turn = add_turn

    seats = [dict(x) for x in FOUR[:2]]
    sess = session(seats)
    sess.links = {"1": Link("1", features=()), "2": Link("2", features=())}

    class Ears:
        capturing = False
        refs = []

        def add_reference(self, key, *a):
            self.refs.append(key)

        def drop_reference(self, *a):
            pass
    sess.ears = Ears()
    convo = c.GroupTalk.__new__(c.GroupTalk)
    c.Conversation.__init__(convo, M(), sess)
    assert [s["character"] for s in convo.seats] == ["Choir"]
    seats[0]["loudness"] = 90                      # changed on the page mid-conversation
    assert convo.seats[0]["loudness"] == 90 and convo.seats[0]["character"] == "Choir"

    line = c.Line(seat=convo.seats[0], move="build", text="hello together", final=False,
                  nudge="", director_s=0.0, gesture="")
    line.audio.add(b"\0\0" * 8000)
    line.audio.finish()
    asyncio.run(convo.speak(line, {"id": 1}, cut_by_people=False))
    assert sess.links["1"].played and sess.links["1"].played == sess.links["2"].played
    assert set(sess.ears.refs) == {"1", "2"}, "each robot's mic knows the line is ours"


SIX = [{"key": k, "name": "reachy" + k, "character": "Reachy Mini " + k} for k in "123456"]


def test_a_choir_takes_robots_ticked_after_it_was_switched_on():
    """2026-11-03: Choir saved its members when pressed; reachy1 and reachy3,
    ticked later, would have sat outside it. The page's Choir (id "choir",
    also the old saved ones with no flag) is every robot at the table."""
    saved = [{"id": "choir", "name": "Choir", "members": ["2", "3"], "talk": True, "move": True}]
    seats = [dict(s) for s in SIX[:4]]          # 1 and 4 ticked after Choir was on
    speakers, together, mirror = c.plan_groups(seats, c.clean_groups(saved))
    assert [s["character"] for s in speakers] == ["Choir"]
    assert together == {"1": ["1", "2", "3", "4"]}
    assert mirror["4"] == ["1", "2", "3", "4"]


def test_a_choir_shrinks_to_the_robots_at_the_table():
    saved = [{"id": "choir", "name": "Choir", "members": list("123456"),
              "talk": True, "move": True, "whole_table": True}]
    seats = [dict(s) for s in SIX[:2]]
    speakers, together, _ = c.plan_groups(seats, c.clean_groups(saved))
    assert together == {"1": ["1", "2"]} and len(speakers) == 1


def test_a_choir_leaves_robots_of_other_groups_alone():
    groups = c.clean_groups([
        {"id": "choir", "name": "Choir", "members": list("1234"), "whole_table": True},
        {"id": "g2", "name": "Pair", "members": ["3", "4"]}])
    assert groups[0]["members"] == ["1", "2"] and groups[1]["members"] == ["3", "4"]
    seats = [dict(s) for s in SIX]
    speakers, together, _ = c.plan_groups(seats, groups)
    assert together == {"1": ["1", "2", "5", "6"], "3": ["3", "4"]}
    assert [s["character"] for s in speakers] == ["Choir", "Pair"]


def test_a_choir_edited_by_hand_is_an_ordinary_group():
    groups = c.clean_groups([{"id": "choir", "name": "Choir", "members": ["1", "2"],
                              "whole_table": False}])
    seats = [dict(s) for s in SIX[:3]]
    _, together, _ = c.plan_groups(seats, groups)
    assert together == {"1": ["1", "2"]}, "robot 3 stays on its own"
    assert c.clean_groups([{"id": "g1", "members": ["1", "2"]}])[0]["whole_table"] is False
