"""A person's name is said at most once per conversation (Tomer, 2026-10-25:
after a guest gave their name, ~every robot line opened with "<name>, ...")."""

from hub import laptop_mic
from hub.group.conductor import people_names, says_name, strip_person_name

GUEST = ("Hello, my name is Dana. I work in the lab next door and I came to "
       "hear what the robots think.")


def test_name_from_intro():
    assert people_names([GUEST], []) == {"Dana"}
    assert people_names(["My name's Dana and I like jazz."], []) == {"Dana"}


def test_capitalised_word_counts_only_when_a_robot_called_them_by_it():
    said = ["I heard Spotify pays nothing, this is Noam."]
    assert people_names(said, []) == set()
    assert people_names(said, ["Noam, that is not true."]) == {"Noam"}
    assert people_names(said, ["Spotify pays pennies."]) == set()


def test_not_names():
    assert people_names(["yes I think AI is good"], ["AI, music is ..."]) == set()


def test_strip_vocatives():
    assert strip_person_name("Dana, would you pay ten dollars for it?", "Dana") == \
        "Would you pay ten dollars for it?"
    assert strip_person_name("That money cannot pay the rent, Dana.", "Dana") == \
        "That money cannot pay the rent."
    assert strip_person_name("Hello Dana, we are your table robots.", "Dana") == \
        "Hello, we are your table robots."
    assert strip_person_name("Saving money means nothing, Dana, if artists starve.", "Dana") == \
        "Saving money means nothing, if artists starve."
    assert strip_person_name("Dana's job is safe from robots.", "Dana") == "Dana's job is safe from robots."


def test_says_name():
    assert says_name("Hello Dana, hi.", "Dana")
    assert not says_name("Mayday is not a name.", "Dana")


def test_dji_receiver_is_auto():
    devices = [{"index": 1, "name": "Microphone Array (Realtek(R) Audio)", "channels": 2},
               {"index": 2, "name": "Microphone (Wireless Mic Rx)", "channels": 2}]
    assert laptop_mic.find("auto", devices)["index"] == 2
