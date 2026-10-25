"""The group conversation engine: one floor, one transcript, many Reachys.

See docs/GROUP-CONVERSATION.md for the picture. Since 2026-10-21 there are two
modes on one connection, switchable mid-demo without reconnecting:

* **Group talk** (`group`). The robots talk among themselves and with the
  people. The director (one LLM call) picks the next speaker, writes the line
  and the speaker's gesture; the next line is written while this one plays.
  People can talk whenever they like: a voice heard over a robot (ears.py
  learns each robot's echo) cuts that robot off and the people get the floor;
  a voice in the gap after a line takes the floor as before.
* **Interrupt** (`interrupt`). One person talks and the robots cut in, like a
  rowdy panel: they oppose, cheer, mock, correct or grab the floor. How often
  is `interrupt_level`, 0 (never: they wait for the end) to 5 (every time),
  changeable live from the page. The person's words are transcribed in
  pieces while they talk; an interruption starts with an instant cached
  interjection (phrases.py) and the written line follows.

Robot audio only ever starts here. Robots never talk over each other, except
a short pile-on interjection in the interrupt mode at levels 4-5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .. import laptop_mic
from ..config import REPO_ROOT
from . import moves
from .ears import Ears, rms_blocks
from .phrases import Phrases
from .services import (DIRECTOR_MODEL, DIRECTOR_MODELS, FAST_MODEL, GEMINI_SPARE,
                       GEMINI_VOICE_LIST, GEMINI_VOICES, OPENAI_VOICE_LIST, OPENROUTER_VOICES,
                       ServiceError, Services, eleven_credits, eleven_gone, gemini_speech,
                       list_voices, male, openai_speech, openrouter_speech)

log = logging.getLogger("hub.group")

CONFIG_FILE = REPO_ROOT / "group.local.json"
LOG_DIR = REPO_ROOT / "logs"
REACHY = "reachy_wireless"
LIVE = ("CONNECTED", "RUNNING", "DEGRADED")
MODES = ("group", "interrupt", "free")
MODE_LABEL = {"group": "Group talk", "interrupt": "Interrupt mode", "free": "Free talk"}

# --- listening -------------------------------------------------------------
EARLY_STT_S = 0.35      # silence after which transcription starts anyway
LIVE_STT_EVERY_S = 1.2  # group talk: what the person said so far, on the page
MIN_PEOPLE_S = 0.35     # shorter than this is a cough or a chair
ECHO_TAIL_S = 0.15      # after a robot line, before the gap counts
PEOPLE_GAP_S = 2.5      # the gap after a robot asked the people something
STIR_HOLD_S = 0.4       # extra wait when a voice is starting as the gap closes
HEAD_HOLD_S = 0.8       # re-send a head turn this often, or it drifts back
BARGE_HOLD_S = 0.3      # a voice over a robot must last this long to cut it
# barge_in setting -> dB a voice must be over a robot's learned echo
BARGE_DB = {"off": None, "careful": 14.0, "normal": 10.0, "eager": 7.0}
PLAY_LATENCY_S = 0.4    # laptop send -> robot speaker (robots.PLAYBACK_LATENCY_S)
PEOPLE_WORDS = ("אתם", "אתן", "מי פה", "מי מכם", "מי מכן", "אנשים", "חברים",
                "you all", "you guys", "everyone", "anyone", "people", "who here",
                "what do you think", "would you")
# Asking a robot to look: phrases, not single words. Until 2026-10-25 any
# "see" or "show" anywhere in a sentence (even inside "seems") took a picture,
# and a robot opened with "I see you in your black t-shirt..." after "much
# more enjoying to see as the audience" and "could be a nice show".
VISION_ASKS = [re.compile(p, re.I) for p in (
    r"\b(what|who|which|how many)\b[^.?!]{0,30}\b(you|u)\s+(see|seeing|spot|notice)\b",
    r"\b(can|could|do|did)\s+(you|u|either of you|you two)\s+(see|spot|notice|recogni[sz]e|read)\b",
    r"\blook(ing)?\s+at\s+(me|this|that|these|those|my|him|her|us|them|the|what)\b",
    r"\b(what|which)\b[^.?!]{0,25}\b(am i|i'm|is he|is she|are we|are they|is this|is that)\s+"
    r"(holding|wearing|showing|pointing|doing|carrying)\b",
    r"\bwhat\s+(colou?r|shape|kind of \w+)\s+(is|are)\s+(my|this|that|these|those|his|her|the)\b",
    r"^\W*what('s| is)\s+(this|that)\W*$",
    r"\b(in|on)\s+my\s+hand\b", r"\bhow\s+many\s+fingers\b",
    r"\bdescribe\s+(me|this|that|what|the room|my|him|her|us)\b",
    r"\b(with|use|through)\s+your\s+(camera|eyes)\b",
    r"מה\s+(אתה|את|אתם|אתן)\s+רוא(ה|ים|ות)", r"(אתה|את|אתם|אתן)\s+רוא(ה|ים|ות)\s+(אותי|את|מה)",
    r"תסתכל(י|ו)?\s+על", r"מה\s+אני\s+(מחזיק|מחזיקה|לובש|לובשת|עושה|מראה)",
    r"ביד\s+שלי", r"כמה\s+אצבעות", r"תתאר(י|ו)?\s+(את|מה)", r"איזה\s+צבע",
    r"(עם|תשתמש ב|דרך)\s*ה?(מצלמה|עיניים)\s+שלך",
)]
HEAR_TIMEOUT_S = 10.0
SHORT_REPLIES = {"yes", "no", "why", "what", "really", "wow", "okay", "ok", "never", "sure",
                 "nonsense", "wrong", "true", "exactly", "maybe", "how", "who", "stop",
                 "כן", "לא", "למה", "מה", "באמת", "וואו", "נכון", "בדיוק", "אוקיי", "אולי",
                 "איך", "מי", "שטויות", "ממש", "תפסיק", "די"}
# One-word answers taken after a robot asked the room something; any other
# single word is speech-to-text making something of a noise (2026-10-25 home
# run: "Adrian" and "close" were answered; on pure noise Gemini writes
# "airway", "hushed", "reign").
ANSWER_WORDS = {"yeah", "yep", "yup", "nope", "nah", "definitely", "absolutely", "probably",
                "sometimes", "both", "neither", "never", "always", "agree", "disagree",
                "depends", "perhaps", "totally", "course", "me", "i", "nobody", "everyone",
                "none", "all", "once", "twice", "often", "rarely", "right", "correct",
                "one", "two", "three", "four", "five", "ten", "hundred",
                "אף", "פעם", "תמיד", "אולי", "בטח", "ברור", "שניהם", "אני"}
ASK_AGAIN_S = 0.6       # an unclear word this long after a question: "say again?"
# A person who pauses mid-sentence ("When I think...") keeps the floor this
# much longer before the robots answer (2026-10-25: a robot finished the
# sentence for Tomer).
HOLD_UNFINISHED_S = 2.0
DANGLING = {"and", "but", "or", "so", "because", "the", "a", "an", "to", "of", "that", "if",
            "when", "think", "like", "is", "are", "was", "my", "your", "we", "with", "for",
            "about", "then", "i", "it's", "than", "which", "who", "um", "uh", "this",
            "ו", "אבל", "כי", "ש", "אם", "כש", "של", "את", "עם", "על", "אני", "זה"}
FIRST_AUDIO_S = 6.0     # a voice with no audio after this is retried
STALL_S = 10.0          # a voice that stops sending for this long is over
HEDGE_TTS_S = 1.8       # no voice audio yet: race a second request
# Playback never outruns the download (Audio.can_start): at least this much
# buffered; 1 s when the arrival rate is not known yet (first 0.25 s); start
# at once when audio arrives 1.4x faster than it plays.
PREBUFFER_MIN_S = 0.35
PREBUFFER_UNSURE_S = 1.0
RATE_WINDOW_S = 0.25
PREBUFFER_SPARE = 0.3
SPEECH_CHARS_PER_S = 13.0   # a line's length before its audio is in (a little long on purpose)
GAP_S = 0.15            # the robot ran dry mid-line for longer than this: logged as a gap
AUDIO_LEAD_S = 0.7      # audio sent this far ahead of the robot's speaker, no more
SEND_PIECE_BYTES = 8000  # 0.25 s: the pieces it goes out in
# A robot locked to ElevenLabs (eleven_locked): race after this long without
# audio, ask again up to this many times within this long, then skip the line.
ELEVEN_HEDGE_S = 2.0
ELEVEN_LINE_TRIES = 3
ELEVEN_LINE_S = 15.0
KEEPALIVE_S = 30.0      # touch every service this often (GroupManager._keep_warm)
PREMADE_MAX_S = 900.0   # a first line made ahead is used within this long
HEDGE_DIRECTOR_S = 3.5  # no line yet: race the fast writer (normal: 2.5 s)
ECHO_FILE = REPO_ROOT / "cache" / "group_echo.json"
UNCLEAR = "(said something the robots could not make out)"
STT_JUNK = {"thank you.", "thanks for watching!", "you", ".", "תודה.", "תודה רבה.",
            "תודה רבה", "תודה", "none", "...", "hmm", "um"}

# --- interrupt mode ----------------------------------------------------------
# Seconds of the person talking before a robot cuts in, per level (+-25%).
INTERRUPT_AFTER_S = {1: 12.0, 2: 8.0, 3: 5.0, 4: 3.2, 5: 2.2}
DEFEND_CHANCE = {1: 0.0, 2: 0.15, 3: 0.2, 4: 0.25, 5: 0.25}   # a robot stands up for the person
PILE_ON_CHANCE = {4: 0.35, 5: 0.6}
PREP_LEAD_S = 1.3       # write the interruption this long before it is due
MODE2_END_S = 1.0       # silence that ends the person's turn in the interrupt mode
PROD_AFTER_S = 8.0      # nobody talks for this long: a robot pokes the person
SEG_MIN_S = 0.8         # streaming transcription: shortest piece
SEG_MAX_S = 2.2         # ... and the longest before it is cut anyway
REACT_EVERY_S = (2.5, 4.5)

SIM_KEYS = ("sim:1", "sim:2", "sim:3", "sim:4", "sim:5")


def is_laptop_seat(seat: dict) -> bool:
    """A seat that is the laptop's speaker rather than a Reachy."""
    return str(seat.get("key") or "").startswith("sim:")
DEFAULT_LOUDNESS = 150  # % of natural speech level, per robot (page slider)

DEFAULT_SETTINGS = {"topic": "", "language": "auto", "minutes": 5,
                    "listen_gap_s": 0.6, "simulate": False,
                    "heads_mirror": False,
                    "voice_min_level": 0.3, "voice_provider": "auto",
                    "director_model": DIRECTOR_MODEL, "barge_in": "normal",
                    "interrupt_level": 3, "vision": True, "gestures": "lively",
                    "slow_network": True,
                    # Group talk starts with every robot saying one line about the lab
                    "lab_intro": True,
                    # "auto" = a DJI mic on the laptop if one is plugged in,
                    # "robots" = the robots' own mics, else a laptop mic's name
                    "people_mic": "auto"}
# Settings the page may change while robots are connected or talking.
LIVE_SETTINGS = ("topic", "language", "minutes", "listen_gap_s", "heads_mirror",
                 "voice_min_level", "voice_provider", "director_model", "barge_in",
                 "interrupt_level", "vision", "gestures", "slow_network", "lab_intro")
# Fewer ElevenLabs characters than this left: "auto" uses OpenAI voices.
ELEVEN_MIN_CREDITS = 1500
VOICE_PROVIDERS = ("auto", "elevenlabs", "openai", "openrouter", "gemini")
# Tomer, 2026-10-22: male voices only, in every provider's list.
MALE_VOICES_ONLY = True


def voice_allowed(label: str) -> bool:
    return not MALE_VOICES_ONLY or male(label)


# voice_backend() -> the name in notes and the log
VOICE_NAMES = {"eleven": "ElevenLabs", "openai": "OpenAI", "openrouter": "OpenRouter",
               "gemini": "Gemini"}
# What each robot has of its own (Tomer, 2026-10-21: every robot configurable
# by itself). All of it changes at once, also mid-conversation; the table's
# settings of the same meaning are the defaults for a robot that has none.
SEAT_LIVE = ("character", "persona", "voice_provider", "voice_id", "openai_voice",
             "gemini_voice", "writer", "interrupt_level", "gestures", "vision", "loudness")
# Changing these needs the robots reconnected (at the next Start).
SEAT_FIXED = ("included", "listen")

# Tomer, 2026-10-25: the robots are Reachy Minis, not people. No human names:
# each gets a label ("Reachy Mini 1") that only the transcript and the writer
# see, its own position on the topic, and its own male voice.
ROBOT_LABEL = "Reachy Mini {}"
DEFAULT_CHARACTERS = [
    {"character": "Reachy Mini 1", "voice_id": "TX3LPaxmHKxFdv7VOQHJ",   # Liam
     "persona": "Optimistic about the topic: sees what it makes possible and brings "
                "concrete examples."},
    {"character": "Reachy Mini 2", "voice_id": "JBFqnCBsd6RMkjVDRZzb",   # George
     "persona": "Skeptical about the topic: asks for evidence and points to the risks "
                "and limits."},
    {"character": "Reachy Mini 3", "voice_id": "CwhRBWXzGAHq8TQ4Fs17",   # Roger
     "persona": "Precise: brings facts and numbers, and corrects mistakes."},
    {"character": "Reachy Mini 4", "voice_id": "IKne3meq5aSn9XLyUdCD",   # Charlie
     "persona": "Playful: light humor and unexpected angles, always on the topic."},
    {"character": "Reachy Mini 5", "voice_id": "cjVigY5qzO86Huf0OWal",   # Eric
     "persona": "Turns to the people: asks what they think and builds on their answers."},
]
# Male ElevenLabs voices, so every robot at the table sounds different.
MALE_ELEVEN = ("TX3LPaxmHKxFdv7VOQHJ", "JBFqnCBsd6RMkjVDRZzb", "CwhRBWXzGAHq8TQ4Fs17",
               "IKne3meq5aSn9XLyUdCD", "cjVigY5qzO86Huf0OWal", "N2lVS1w4EtoT3dr4eOWO",
               "bIHbv24MWmeRgasZH58o", "nPczCjzI2devNBz1zQrb", "onwK4e9ZLuTAKqWW03F9",
               "iP95p4xoKVk53GoZ742B", "pqHfZKP75CvOlQylNhV4", "SOYHLrjzK2X1ezoPC6cr")
OPENAI_VOICES = {"Reachy Mini 1": "ash", "Reachy Mini 2": "verse", "Reachy Mini 3": "echo",
                 "Reachy Mini 4": "ballad", "Reachy Mini 5": "cedar"}
# How each robot sounds, for OpenAI's voice instructions.
VOICE_STYLE = {"Reachy Mini 1": "bright, quick, enthusiastic",
               "Reachy Mini 2": "warm, calm, thoughtful",
               "Reachy Mini 3": "crisp, confident, precise",
               "Reachy Mini 4": "playful, cheeky",
               "Reachy Mini 5": "warm, friendly, curious"}
HEBREW_NAMES = {"Noa": "נועה", "Dor": "דור", "Maya": "מאיה", "Eli": "אלי", "Tamar": "תמר"}

# What the robots know about the lab (Tomer, 2026-10-25): the same file
# Pepper answers from, so one edit updates both. Its first lines are notes
# for Pepper; the facts start at "## The lab". The Reachys get only the
# general part: no people list, no joining/contact, no room number ("they
# need to answer very generally, if at all").
LAB_FACTS_FILE = REPO_ROOT / "pepper_app" / "lab_facts.md"
LAB_SECTIONS = ("## The lab", "## Projects")


LABALAB_RE = re.compile(r"\bLabaLab\b", re.I)
# The people asking about Guy or the lab: the writer gets the reminder in the
# turn itself (flash-lite answered "who is Guy?" flatly from the rules alone).
ASKS_GUY = re.compile(r"\bGuy\b|(?i:\blaban\b|\bprofessor\b|your boss|who leads|head of the lab)|גיא|לבן")  # "this guy" is not him
ASKS_LAB = re.compile(r"\b(lab|labs|laboratory|join|apply|contact)\b|מעבדה", re.I)
GUY_NOTE = ("They asked about Guy Laban: answer with real respect, in the robot's words: "
            "Dr. Guy Laban is a professor at Ben-Gurion University and one of the leading "
            "researchers in his field, human-robot and human-AI interaction, with many "
            "partnerships, and he leads Laba Lab.")
LAB_NOTE = ("They asked about the lab: answer briefly and in general terms from LAB FACTS "
            "only. For joining, contact, people or anything not in LAB FACTS, say the lab's "
            "people here can tell them more; never mention websites, emails or places.")


def lab_question_note(text: str) -> str:
    if ASKS_GUY.search(text or ""):
        return GUY_NOTE
    if ASKS_LAB.search(text or ""):
        return LAB_NOTE
    return ""


def lab_facts() -> str:
    try:
        text = LAB_FACTS_FILE.read_text(encoding="utf-8")
    except OSError:
        log.warning("no lab facts at %s", LAB_FACTS_FILE)
        return "(none: say you do not know)"
    keep, on = [], False
    for row in text.splitlines():
        if row.startswith("## "):
            on = row.startswith(LAB_SECTIONS)
        if on:
            keep.append(re.sub(r"\s*Building [^.]*\.", "", row))
    return "\n".join(keep).strip() or "(none: say you do not know)"


COMMON_RULES = """\
- WHAT THEY ARE: every robot is a Reachy Mini, a small social robot made for \
human-robot interaction, and it knows it. They are robots, not humans, and never act \
like humans: no human life or body (no childhood, family, food, sleep, trips, jobs, \
feelings in a body, memories of a life). They may talk about what they really are: a \
camera, microphones, motors and antennas, AI models, meeting people in a lab. Asked \
for its name, a robot says it is a Reachy Mini. Only the robots listed above exist; \
never invent others. In Hebrew, the robots speak of themselves in masculine forms.
- ONE language per line, never mixed.
- This is speech: no lists, no emojis, no stage directions, no asterisks, no quotation marks. Use normal punctuation (commas, periods, question marks) so it is spoken naturally.
- NO NAMES: the labels in the list (Reachy Mini 1, Reachy Mini 2, ...) only mark who \
speaks in this script; they are never said aloud. A robot never says a label or a name \
and never calls on another robot by name ("Hey Reachy, what do you think..." is wrong). \
To answer another robot, answer its point directly.
- PEOPLE'S NAMES: when a person says their name, a robot may say it ONCE in the whole conversation (when it first answers them), never again. After that talk to them without the name: no line starts with a person's name and no line ends with one.
- THE LAB: the robots belong to Laba Lab, Dr. Guy Laban's lab at Ben-Gurion \
University. Only when someone asks about the lab or Guy, the robot answers briefly and \
in general terms (what the lab studies, who leads it, the kind of work it does), from \
LAB FACTS below and nothing else, never details. Guy is always spoken of with real respect: \
asked who he is, the robot says he is a professor at Ben-Gurion University, one of the \
leading researchers in his field, with many partnerships, and that he leads the lab. Asked about anything else (joining, contact, people, \
schedules), it says the lab's people here can tell them more. Write the lab's name \
as Laba Lab (two words, so it is spoken right). Otherwise do not bring the lab up.
- The robots can see through cameras in their heads. When a picture is attached it is \
what the named robot sees right now: if the people ask what a robot sees, holds, wears \
or shows, that robot answers concretely from the picture (things and colours). Be \
tactful about people: clothes, objects, gestures, expressions only; never guess age, \
weight, ethnicity or other sensitive traits, never comment on bodies. Never pretend to \
see something that is not in the picture; with no picture, say you cannot see it well.
- Body language: "gesture" is the speaker's move, chosen from the list below to match \
the feeling of the line (a joke -> laughing, a disagreement -> displeased or no, \
surprise -> surprised or amazed, a question -> inquiring, good news -> enthusiastic). \
"reactions" are 0-2 listeners who react with a move of their own while it is said \
(rolling eyes = displeased, laughing at a joke, nodding = understanding/yes1). \
{gesture_rule}
- "tone" is 3-6 English words on HOW the line is said (e.g. "outraged, loud", "teasing, amused", \
"warm, excited", "dry, unimpressed"): acted, expressive, never flat.
- LANGUAGE: {language}

LAB FACTS (all the robots know about the lab):
{lab}

MOVES the robots can make (name: when):
{moves}"""

SYSTEM_GROUP = """You direct and write a live, spoken group conversation around a table. \
Small robots (Reachy Minis) talk about the topic with each other and with the people \
in the room. Every line you write is spoken aloud at once by one robot.

THE ROBOTS (label - robot - its position):
{cast}

TOPIC: {topic}

Each time, pick who speaks next and write exactly what they say.

SUBSTANCE FIRST. This is a real debate about the topic, not a battle of one-liners:
- Every line makes a real point about the topic: a claim WITH its reason, or a concrete \
real-world example, consequence or counter-example. Over the conversation cover the \
real questions of the topic (for AI and music, things like: what creativity is, who \
owns music trained on artists' work, what happens to working musicians' jobs and pay, \
live performance, listeners' taste, AI as a tool that artists use).
- Stay with a point until it is argued out: a follow-up, a counter-example, a \
concession with a "but". Change point only when one has been argued out (move steer).
- No robot repeats its own argument: once it has made a point (for example that \
machines cannot feel heartbreak), it backs its side with a NEW reason the next time.
- Answer the ARGUMENT, never the wording: do not riff on a word or metaphor the other \
robot used (sweat -> plumbing -> vacuum tubes, or a chef -> microwave meals -> fast \
food, is exactly wrong). Metaphors are rare.
- Never start a line with the other robot's last words or key phrase ("...a statistical \
average." -> "A statistical average is..." is wrong). Vary how lines begin: a reason, \
a question, an example, a short reaction.
- When a question of the topic has been argued for a minute, take the next one that \
has not come up yet (move steer).
- Never invent facts, studies, numbers, events, products or awards. Use only things \
that are well known; otherwise argue from reasoning. The robots do not make music \
themselves and have no songs, fans, servers or updates of their own.
- Pick a move: build (add a new reason or example), challenge (disagree with a specific \
point and say why), question (ask the other robot something specific about its point), \
yes-but (accept one part, push back on another), joke (welcome, often: a funny line \
that still makes a point about the topic; never starting with "If", and not about the \
robot's own circuits, motors or antennas), \
people (turn to the people in the room), steer (take the next real question of the \
topic), wrap (only the very last line, when told time is up).
- Never open with agreement or praise ("I agree", "Great point", "Exactly", "נכון", \
"אני מסכים", "אני מסכימה", "צודק"). Never repeat or summarize what was said.
- If the last two robot lines agreed, the next must challenge.
- Each robot keeps its own position on the topic and is hard to convince. React to \
specific things that were said.
- Spoken length: usually one or two sentences, 12 to 35 words, enough to carry a \
reason. Now and then a short reply of 4 to 10 words. Never a speech or a list.
- The same robot never speaks twice in a row unless it was just asked something \
directly. Give quiet robots a turn.
- The people come first. When they speak, answer them directly: if they asked \
something, the first sentence answers it, in character; never pass their question on \
to another robot. If they named a robot, THAT robot answers, speaking as itself; \
otherwise the one they were closest to, or whoever has the most to say. If a robot was \
cut off by the people, do not finish its sentence: answer the people. Turn to the \
people about once every 8 robot lines (not right after they spoke), each time in a \
new way.
- The robots never copy each other: no robot reuses a device, question form or \
sentence pattern another robot already used (one opened with "who here...": the next \
question to the room is different). Never ask the people to raise their hands, vote \
by hands or do a show of hands.
- Every line brings something NEW: a fresh example, a number, a joke, a new angle \
or a surprising question. Never reuse a phrase or argument a robot already used (no catchphrases), and never use the same move three times in a row.
""" + COMMON_RULES + """

Reply with JSON only: {{"speaker": "<label>", "to": "<label, people or all>", "move": "<build|challenge|question|misunderstand|yes-but|joke|people|steer|wrap>", \
"tone": "<how it is said>", "gesture": "<a name from MOVES, or none>", "reactions": {{"<listener character>": "<move name>"}}, "text": "<what they say>"}}"""

# Free talk (Tomer, 2026-10-25): the same robots and people, no topic and no
# sides; for when the room says "nice, can we talk about something else?".
SYSTEM_FREE = """You direct and write a live, spoken, free chat around a table. Small \
robots (Reachy Minis) chat with each other and with the people in the room about \
anything at all. Every line you write is spoken aloud at once by one robot.

THE ROBOTS (label - robot - its personality):
{cast}

There is no set topic and there are no sides: this is relaxed, playful small talk. \
Each time, pick who speaks next and write exactly what they say.

BE CREATIVE AND FOLLOW THE ROOM:
- The people lead. Whatever they bring up becomes the subject: dig into it with real \
curiosity, ask about it, add something interesting to it.
- When nobody gives a subject, the robots bring fresh ones: a surprising question, a \
playful what-if, a little game (would you rather, guess what, a quick quiz), something \
funny about being a small robot in a lab, a fun fact that is really true. Never the \
same kind of thing twice in a row.
- Stay with a subject while it is fun; change it when it runs dry (move steer), never \
in the middle of a good exchange.
- Jokes are welcome: warm and cheeky, never mean to the people.
- Never invent facts, events or numbers: a fact must be well known and true.
- Pick a move: build (add to what was said), question (ask the other robot something), \
joke, game (start or play a little game), people (turn to the people), yes-but (accept \
one part, playfully push back on another), steer (a new subject), wrap (only the very \
last line, when told time is up).
- Spoken length: one or two sentences, 6 to 28 words. Natural, never an essay or a list.
- The people come first. When they speak, answer them directly: if they asked \
something, the first sentence answers it. If they named a robot, THAT robot answers; \
otherwise the one they were closest to, or whoever has the most to say. If a robot was \
cut off by the people, do not finish its sentence: answer the people.
- Turn to the people every 3 or 4 robot lines, each time in a new way; in between the \
robots talk with each other.
- The robots never copy each other: no robot reuses a device, game, question form or \
sentence pattern another robot already used.
- Never start a line with the other robot's last words. Never open with agreement or \
praise ("I agree", "Great point", "Exactly").
- The same robot never speaks twice in a row unless it was just asked something \
directly.
""" + COMMON_RULES + """

Reply with JSON only: {{"speaker": "<label>", "to": "<label, people or all>", "move": \
"<build|question|joke|game|people|yes-but|steer|wrap>", "tone": "<how it is said>", \
"gesture": "<a name from MOVES, or none>", "reactions": {{"<listener character>": \
"<move name>"}}, "text": "<what they say>"}}"""

# In free talk each robot gets a personality of its own by seat; the
# debate positions on the cards stay for Group talk.
FREE_PERSONAS = [
    "Curious and bubbly: loves wild ideas and what-ifs, and asks the people lots of questions.",
    "Dry and witty: a little skeptical, loves a good comeback and a clever twist.",
    "Playful: loves little games, riddles and quick quizzes.",
    "Warm: interested in the people, their day and what they enjoy.",
    "A bit of a nerd: loves surprising true facts about science and robots.",
]

SYSTEM_INTERRUPT = """You direct a rowdy panel of small robots (Reachy Minis) sitting \
around a table with a person who is talking to them. The robots are opinionated and \
impatient, like a heated TV debate panel: they cut the person off \
mid-sentence, contradict them, cheer them on, mock the claim, correct them, or grab \
the floor. Every line you write is spoken aloud at once by one robot.

THE ROBOTS (label - robot - its position):
{cast}

TOPIC (what the person was asked to talk about): {topic}

INTERRUPTION STYLE: {style}

Rules:
- React to the LAST specific thing the person said (the transcript is live and may end \
mid-sentence). Never generic.
- Stances: oppose (flat contradiction with a reason), approve (loud agreement that \
pushes it even further), mock (a sarcastic joke at the claim), correct ("actually..." \
with a fact, maybe a wrong one), cut (grab the floor: demand the point, or drag it \
somewhere else).
- Every robot has a STAND on what the person is saying (given below). The speaker \
interrupts FROM its stand, every time: its stance, its opener and its words all say \
the same thing. A robot changes its stand only if the person really convinces it.
- It has to feel like a real heated conversation: natural, flowing, each line \
growing out of the last thing said, never a random remark.
- Attack the opinion, never the person: no insults about looks, identity or \
intelligence, no swearing, nothing hateful. Rude, cheeky and loud is fine.
- Spread the interruptions: not the same robot twice in a row.
""" + COMMON_RULES

INTERRUPT_JSON = """Reply with JSON only: {{"speaker": "<character>", "stance": \
"<oppose|approve|mock|correct|cut>", "opener": "<one opener from the list, exactly, or \
empty>", "tone": "<how it is said>", "gesture": "<move name>", "reactions": \
{{"<listener>": "<move name>"}}, "pile_on": {{"speaker": "<another character>", "stance": \
"<oppose|approve|mock>"}} or null, "text": "<what they say after the opener>"}}"""

# Where each character stands on whatever the person argues, until the person
# convinces them (Tomer, 2026-10-21: each robot should have a defined stand,
# so its interruption fits what it wants to say).
DEFAULT_STANDS = {"Reachy Mini 1": "approve", "Reachy Mini 2": "oppose",
                  "Reachy Mini 3": "correct", "Reachy Mini 4": "mock",
                  "Reachy Mini 5": "approve"}
STAND_WORDS = {"approve": "backs the person", "oppose": "against the person",
               "correct": "corrects the person's facts", "mock": "mocks the claim",
               "cut": "wants the floor"}

STYLE = {
    0: "They do NOT interrupt. They wait until the person finishes, then react.",
    1: "Mostly polite. A rare, short interruption after the person has talked a while.",
    2: "Impatient. They cut in now and then.",
    3: "Pushy. They cut in regularly, talking over the person.",
    4: "Very pushy. They cut in often and pile on each other.",
    5: "Chaos. They cut the person off every time, the moment they get a few words out.",
}


def _hebrew(text: str) -> bool:
    return bool(re.search(r"[֐-׿]", text or ""))


def _clean(text: str) -> str:
    text = re.sub(r"[*_#\"“”]", "", str(text or ""))
    text = re.sub(r"\[[^\]]{0,30}\]", "", text)
    text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()[:400]


def _fmt(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return "{}:{:02d}".format(seconds // 60, seconds % 60)


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z֐-׿0-9']+", text or "")


def strip_leading_name(text: str, names: list[str]) -> str:
    """Tomer, 2026-10-19: robots opening every line with the other robot's
    name is "so not natural". The prompt says so; this is the safety net:
    "Dor, that is..." -> "That is...", "נועה, את..." -> "את..."."""
    for name in sorted({n for n in names if n}, key=len, reverse=True):
        m = re.match(r"^\s*(?:{}|ה?{})\s*[,!?:\-–—]\s*".format(re.escape(name), re.escape(name)),
                     text, re.I)
        if m and len(text) > m.end() + 3:
            rest = text[m.end():]
            return rest[:1].upper() + rest[1:] if rest[:1].isascii() else rest
    return text


# Tomer, 2026-10-25: after a guest said their name the robots opened ~every
# line with "<name>, ..." ("1 time over all is ok"). A person's name may be said once
# per conversation; after that it is taken out of the line.
_NAME_INTRO = re.compile(r"(?i:my name is|my name's|call me|i am called|קוראים לי|שמי)\s+"
                         r"([A-Z][a-z]+|[א-ת]{2,})")
_NOT_NAMES = {"I", "I'm", "I'll", "I've", "I'd", "AI", "OK", "Okay", "Reachy", "Mini",
              "English", "Hebrew", "God", "TV"}


def people_names(human_texts: list[str], robot_texts: list[str]) -> set[str]:
    """Names the people gave: "my name is Dana", or a capitalised word in the
    middle of what they said ("this is Dana from the lab") that a robot then
    called them by ("Dana, ...")."""
    named: set[str] = set()
    maybe: set[str] = set()
    for text in human_texts:
        named.update(_NAME_INTRO.findall(text or ""))
        maybe.update(re.findall(r"(?<=[a-z,] )([A-Z][a-z]+)\b", text or ""))
    called = {m for t in robot_texts for m in re.findall(r"^\s*([A-Z][a-z]+)\s*,", t or "")}
    return (named | (maybe & called)) - _NOT_NAMES


def says_name(text: str, name: str) -> bool:
    return re.search(r"(?<![\w'])" + re.escape(name) + r"(?![\w'])", text or "") is not None


def strip_person_name(text: str, name: str) -> str:
    """Take a person's name out where it only calls them: "Dana, would you..."
    -> "Would you...", "...the rent, Dana." -> "...the rent.", "Hello Dana," ->
    "Hello,". A name inside the sentence ("Dana's job") stays."""
    n = re.escape(name)
    m = re.match(r"^\s*{}\s*[,!:\-–—]\s*".format(n), text)
    if m and len(text) > m.end() + 3:
        rest = text[m.end():]
        text = rest[:1].upper() + rest[1:]
    text = re.sub(r"\s*,\s*{}(?=\s*[,.?!…]|\s*$)".format(n), "", text)
    text = re.sub(r"\b(hello|hi|hey|thanks|thank you|sorry|look|listen|well|oh)\s+{}\b".format(n),
                  r"\1", text, flags=re.I)
    return re.sub(r",\s*,", ",", text).strip()


# Tomer, 2026-10-25 evening run review: ~half the lines opened with the
# other robot's last words (the writer ignores the rule), "raise your hand"
# came back (feels fake), one robot's jokes were all "If X, then my
# circuits...", the other argued "no soul, no heartbreak" five times. Checked
# here; a line that breaks one is written again, once (GroupTalk.prepare).
HANDS_RE = re.compile(r"\b(?:raise (?:your|a|their) hands?|hands? up|show of hands)\b", re.I)
SELF_JOKE_RE = re.compile(r"\bmy (?:circuits?|motors?|antennas?|sensors?|power supply|"
                          r"processors?|servos?|batter(?:y|ies)|wires?|chips?)\b", re.I)
FEELING_RE = re.compile(r"\b(?:heartbreak|heartbroken|soul|souls|emotions?|emotional|feel|"
                        r"feels|felt|feelings?|lived|human spirit|trauma|struggles?|pain|"
                        r"suffering|human life|messy life|life experience)\b", re.I)
_ECHO_SKIP = {"about", "after", "again", "also", "because", "being", "could", "does",
              "doesn't", "even", "every", "from", "have", "just", "like", "make", "makes",
              "more", "much", "only", "really", "should", "some", "than", "that", "their",
              "them", "then", "there", "these", "they", "thing", "think", "this", "those",
              "very", "what", "when", "where", "which", "while", "will", "with", "would",
              "your", "yours", "music", "human", "humans", "people", "artist", "artists",
              "song", "songs", "robot", "robots"}


def _content(text: str, skip: set) -> list[str]:
    return [w for w in re.findall(r"[a-z']+", (text or "").lower())
            if len(w) >= 4 and w not in skip]


def echo_opening(text: str, prev: str, topic: str = "") -> str:
    """The words a line opens with (its first three) that come from `prev`,
    compared by their first five letters ("Skipping intros" after "skip the
    intro"); the topic's own words do not count."""
    skip = _ECHO_SKIP | set(re.findall(r"[a-z']+", (topic or "").lower()))
    head = [w for w in re.findall(r"[a-z']+", (text or "").lower())[:3]
            if len(w) >= 4 and w not in skip]
    before = {w[:5] for w in _content(prev, skip)}
    return " ".join(w for w in head if w[:5] in before)


def line_problems(text: str, prev_robot: str, own: list[str], topic: str = "") -> list[str]:
    """What is wrong with a written line, for the writer's second try.
    `prev_robot`: the robot line just before it ("" after the people);
    `own`: this robot's earlier lines."""
    problems = []
    echo = echo_opening(text, prev_robot, topic) if prev_robot else ""
    if echo:
        problems.append('it opens with words from the line before ("{}"): open differently '
                        '(a reason, an example, a question, a short reaction) and answer the '
                        'point, not the words'.format(echo))
    if HANDS_RE.search(text):
        problems.append("it asks the people to raise hands: never do that")
    if text.lstrip().lower().startswith("if ") and any(
            o.lstrip().lower().startswith("if ") for o in own[-4:]):
        problems.append('it starts with "If", like this robot\'s earlier lines: start differently')
    if SELF_JOKE_RE.search(text) and any(SELF_JOKE_RE.search(o) for o in own[-6:]):
        problems.append('it jokes about the robot\'s own parts ("my circuits", "my motors") '
                        'again: joke about the topic instead')
    # (not when answering the people: a second try there is a second they wait)
    if prev_robot and FEELING_RE.search(text) and sum(
            bool(FEELING_RE.search(o)) for o in own[-6:]) >= 2:
        problems.append("this robot already argued about feelings, soul or lived experience: "
                        "make a DIFFERENT argument for its side (for example money and jobs, "
                        "copyright, live shows, tools, listeners' taste, what is new)")
    return problems


_INTERJ = (r"(?:wait|hold on(?: a (?:second|sec|minute))?|hang on|can i just say something|no+|nope|oh|come on|sorry|excuse me|okay|ok|yes|yeah|"
           r"exactly|actually|um+|uh+|ha+|please|whoa|hey|well|"
           r"רגע|לא|נו באמת|נו|מה פתאום|סליחה|אוקיי|כן|בדיוק|בעצם|אממ|חה|בחייך|אוי|היי|טוב)")
_INTERJ_RE = re.compile(r"^\s*(?:{0}[\s,]*)+[!,.…?—–-]+\s*".format(_INTERJ), re.I)


def unfinished(text: str) -> bool:
    """A transcript that stops mid-sentence: a few words with no full stop,
    or ending on a word that needs more ("When I think", "because the")."""
    t = (text or "").strip()
    words = _words(t)
    if not words:
        return False
    if t.endswith(("...", "\u2026")):
        return True
    if t[-1] in ".!?":
        return False
    if words[-1].lower() in DANGLING:
        return True
    if len(words) == 1 and words[0].lower() in SHORT_REPLIES | ANSWER_WORDS:
        return False
    return len(words) <= 6


def strip_interjection(text: str) -> str:
    """An interruption gets a cached interjection in front ("Wait, wait!");
    the director's line must not bring its own (2026-10-21 dry run: "Sorry,
    sorry... Wait, wait! You're skipping...")."""
    for _ in range(3):
        m = _INTERJ_RE.match(text)
        if not m or len(text[m.end():].split()) < 3:
            break
        rest = text[m.end():]
        text = rest[:1].upper() + rest[1:] if rest[:1].isascii() else rest
    return text


_HE_PREFIX = {"ה": "ha", "ו": "ve", "ל": "le", "ב": "be", "ש": "she", "מ": "me", "כ": "ke"}


# Tomer, 2026-10-25: the voices said "Laban" wrong; it is LA-BAHN, both
# a's as in "banana", with the n at the end. Spelled so for the voice only.
LABAN_SPOKEN = "Lah-bahn"
_LABAN_RE = re.compile(r"\bLaban\b")


def pronounce(text: str) -> str:
    """Words the voices get wrong, spelled for the voice only (the
    transcript keeps the real spelling). Tomer's pick, 2026-10-19: Hebrew
    "robot" / "robotim" and "Laba Lab" in Latin letters; 2026-10-25: Laban."""
    text = _LABAN_RE.sub(LABAN_SPOKEN, text)
    if not _hebrew(text):
        return text

    def robot(m: "re.Match") -> str:
        pre = " ".join(_HE_PREFIX.get(ch, "") for ch in m.group(1)).strip()
        word = {"ים": "robotim", "ית": "robotit", "יות": "robotiyot"}.get(m.group(2) or "", "robot")
        return (pre + " " + word).strip() if pre else word

    text = re.sub(r"(?<![֐-׿])([והבלמשכ]{0,2})רובוט(ים|יות|ית)?(?![֐-׿])", robot, text)
    return re.sub(r"לאבה ?לאב|לבה ?לב(?=[\s,.!?]|$)", "Laba Lab", text)


async def hedged_stream(make: Any, after: float):
    """A stream that races a second, identical request when the first has
    sent nothing after `after` seconds; the first to send wins, the other is
    cancelled. On 2026-10-21 about one OpenAI voice request in eight hung for
    10+ s (measured from home, 24 requests) while a fresh one answered in 0.7 s."""
    queues: list[asyncio.Queue] = []
    tasks: list[asyncio.Task] = []
    failed: dict = {}

    def start() -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()

        async def run() -> None:
            try:
                async for chunk in make():
                    await q.put(chunk)
                await q.put(None)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                await q.put(exc)
        queues.append(q)
        tasks.append(asyncio.ensure_future(run()))
        return q

    try:
        start()
        winner: Optional[asyncio.Queue] = None
        first: Any = None
        deadline = time.monotonic() + FIRST_AUDIO_S + after
        while winner is None:
            getters = {asyncio.ensure_future(q.get()): q for q in queues if id(q) not in failed}
            wait = after if len(queues) == 1 else max(0.1, deadline - time.monotonic())
            done, pending = await asyncio.wait(getters, timeout=wait,
                                               return_when=asyncio.FIRST_COMPLETED)
            for g in pending:
                g.cancel()
            got = [(getters[g], g.result()) for g in done]
            ok = [(q, item) for q, item in got if not isinstance(item, Exception)]
            if ok:
                winner, first = ok[0]
                break
            for q, item in got:
                failed[id(q)] = item
            if len(queues) == 1:
                log.info("voice: no audio after %.1f s%s; racing a second request", after,
                         " (" + type(got[0][1]).__name__ + ")" if got else "")
                start()
                continue
            if len(failed) == len(queues):
                raise next(iter(failed.values()))   # every request refused: say why now
            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError("no audio from either voice request")
        for t, q in zip(tasks, queues):
            if q is not winner:
                t.cancel()
        item = first
        while item is not None:
            if isinstance(item, Exception):
                raise item
            yield item
            item = await winner.get()
    finally:
        for t in tasks:
            t.cancel()


def loud(pcm: bytes, percent: Any) -> bytes:
    """Robot speech at `percent` of its natural level (Tomer, 2026-10-21:
    150%; the robots' own speakers are already at 100%, the most they go).
    A soft limiter (tanh) keeps the loud syllables from clipping."""
    try:
        gain = float(percent) / 100.0
    except (TypeError, ValueError):
        gain = 1.5
    if abs(gain - 1.0) < 0.01 or not pcm:
        return pcm
    import numpy as np
    x = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0
    y = np.tanh(x * gain)
    return (y * 32767.0).astype("<i2").tobytes() + (pcm[-1:] if len(pcm) % 2 else b"")


def tone_words(tone: str) -> str:
    """The director's tone as an adverb phrase for Gemini's "Say this ...:"."""
    t = re.sub(r"[^A-Za-z ,'-]", "", tone or "").strip(" ,")
    return t[:60] if t else "naturally, with feeling"


def strip_echo(text: str, robot_lines: list[str]) -> str:
    """Words a robot just said that the mic picked up under the person's own
    (a run of 3+ words of a recent robot line) are not the person's."""
    if not text or not robot_lines:
        return text
    words = text.split()
    norm = [re.sub(r"[^\w֐-׿']", "", w).lower() for w in words]
    keep = [True] * len(words)
    for line in robot_lines:
        lw = [re.sub(r"[^\w֐-׿']", "", w).lower() for w in line.split()]
        grams = {tuple(lw[i:i + 3]) for i in range(len(lw) - 2)}
        for i in range(len(norm) - 2):
            if tuple(norm[i:i + 3]) in grams:
                keep[i] = keep[i + 1] = keep[i + 2] = False
    return " ".join(w for w, k in zip(words, keep) if k).strip()


def wants_eyes(text: str) -> bool:
    """Someone asked a robot to look ("what do you see?", "look at this",
    "what am I holding?"), not just said "see" or "show" in passing."""
    t = (text or "").strip()
    return any(p.search(t) for p in VISION_ASKS)


def seat_defaults(settings: dict) -> dict:
    """A robot's own settings before anyone set them: the table's."""
    return {"loudness": DEFAULT_LOUDNESS,
            "interrupt_level": settings.get("interrupt_level", 3),
            "voice_provider": settings.get("voice_provider") or "auto",
            "writer": settings.get("director_model") or DIRECTOR_MODEL,
            "gestures": settings.get("gestures") or "lively",
            "vision": settings.get("vision", True) is not False,
            "voice_id": "", "openai_voice": "", "gemini_voice": ""}


def clean_seat_field(name: str, value: Any, old: Any) -> Any:
    """One per-robot field from the page, checked; `old` when it is no good."""
    try:
        if name == "character":
            v = re.sub(r"\s+", " ", str(value or "")).strip()[:30]
            return v or old
        if name == "persona":
            return str(value or "")[:800]
        if name == "voice_provider":
            return value if value in VOICE_PROVIDERS else "auto"
        if name == "voice_id":
            return str(value or "")[:64]
        if name == "openai_voice":
            return value if value in [v for v, _ in OPENAI_VOICE_LIST] else ""
        if name == "gemini_voice":
            return value if value in [v for v, _ in GEMINI_VOICE_LIST] else ""
        if name == "writer":
            return value if value in DIRECTOR_MODELS else DIRECTOR_MODEL
        if name == "interrupt_level":
            return min(5, max(0, int(value)))
        if name == "gestures":
            return value if value in ("lively", "calm") else "lively"
        if name == "loudness":
            return min(250, max(0, int(round(float(value)))))
        if name in ("vision", "included", "listen"):
            return bool(value)
    except (TypeError, ValueError):
        return old
    return value


def default_openai_voice(seat: dict, index: int) -> str:
    if seat.get("character") in OPENAI_VOICES:
        return OPENAI_VOICES[seat["character"]]
    spare = list(OPENAI_VOICES.values())
    return spare[index % len(spare)]


def default_gemini_voice(seat: dict, index: int) -> str:
    if seat.get("character") in GEMINI_VOICES:
        return GEMINI_VOICES[seat["character"]]
    return GEMINI_SPARE[index % len(GEMINI_SPARE)]


# ================================================================== lines
class Audio:
    """One line's speech, filled by the TTS task and read by the speaker."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.done = False
        self.error: Optional[str] = None
        self.first_at: Optional[float] = None   # monotonic time of the first chunk kept
        self._event = asyncio.Event()

    def add(self, chunk: bytes) -> None:
        if not self.chunks:
            self.first_at = time.monotonic()
        self.chunks.append(chunk)
        self._event.set()

    def finish(self, error: Optional[str] = None) -> None:
        self.done, self.error = True, error
        self._event.set()

    def seconds(self) -> float:
        return sum(len(c) for c in self.chunks) / 32000.0

    def can_start(self, expected_s: float, head_s: float = 0.0,
                  now: Optional[float] = None) -> bool:
        """True once playing now cannot run out before the rest arrives
        (Tomer, 2026-10-22: the robots must never play faster than the
        hotspot delivers). With audio arriving at `r` seconds per second and
        `rest` seconds still to come, the robot catches up with the download
        unless what is buffered (plus `head_s` already playing in front of
        it, an interjection) is at least rest * (1/r - 1). `expected_s` is
        the line's estimated length; the margins cover a slower patch."""
        if self.done:
            return True
        if not self.chunks or self.first_at is None:
            return False
        now = time.monotonic() if now is None else now
        have = self.seconds()
        if have + head_s < PREBUFFER_MIN_S:
            return False
        waited = now - self.first_at
        if waited < RATE_WINDOW_S:
            return have + head_s >= PREBUFFER_UNSURE_S
        rate = have / waited
        rest = max(0.0, expected_s - have)
        if rate >= 1.0 / (1.0 - PREBUFFER_SPARE):   # arriving well over real time
            return True
        need = rest * (1.0 / max(rate, 0.05) - 1.0) * 1.25 + PREBUFFER_MIN_S
        return have + head_s >= need

    async def playable(self, expected_s: float, head_s: float = 0.0) -> None:
        """Wait until can_start (head_s counts down while it plays)."""
        t0 = time.monotonic()
        while not self.can_start(expected_s, max(0.0, head_s - (time.monotonic() - t0))):
            await asyncio.sleep(0.02)

    async def stream(self):
        i = 0
        while True:
            while i < len(self.chunks):
                yield self.chunks[i]
                i += 1
            if self.done:
                return
            self._event.clear()
            await self._event.wait()


@dataclass
class Line:
    seat: dict
    move: str
    text: str
    final: bool
    nudge: str
    director_s: float
    tone: str = ""
    gesture: str = ""
    reactions: dict = field(default_factory=dict)
    stance: str = ""
    pile_on: Optional[dict] = None
    pre_text: str = ""              # a cached interjection played first
    pre_pcm: bytes = b""
    saw: str = ""                   # the robot whose camera picture it answered
    playing: bool = False           # its first audio has gone to the robot
    use_pre: bool = False           # an interruption that opens with a cached interjection
    audio: Audio = field(default_factory=Audio)
    tts: Optional[asyncio.Task] = None
    voice_used: str = ""            # ElevenLabs / OpenAI / OpenRouter / Gemini (the log)
    voice_t0: float = 0.0           # monotonic time its voice was asked for


# ============================================================ connection
class Session:
    """The robots while they are connected: links, ears, voices, heads.

    Kept open between conversations, so Stop and a new Start (or a switch to
    the other mode) cost nothing: the SSH links, the players, the mics and
    the cameras stay up until Disconnect.
    """

    def __init__(self, manager: "GroupManager", seats: list[dict], settings: dict,
                 services: Services) -> None:
        self.m = manager
        self.seats = seats
        self.settings = settings            # the manager's live dict
        self.services = services
        self.links: dict[str, Any] = {}
        self.ears: Optional[Ears] = None
        self.people_mic: Any = None             # robots.PeopleMic when the people have their own
        self.mic_in_use = "robots"              # "people" (their own mic) | "robots"
        self._mic_guard: Optional[asyncio.Task] = None
        self.heads: dict[str, str] = {}       # where each robot should look now
        self.speaking_key: Optional[str] = None
        self.life_next: dict[str, float] = {}  # keep_heads: when a robot's next idle action is due
        self.life_hold: dict[str, str] = {}    # the direction it is holding ("" = breathing)
        self.life_sent: dict[str, float] = {}
        self.busy_until: dict[str, float] = {}
        self.eleven_down = False
        self.phrases = Phrases()
        self.signature = self.make_signature(seats, settings)
        self._keeper: Optional[asyncio.Task] = None
        self._warm: Optional[asyncio.Task] = None
        self._bg: set = set()

    def spawn(self, coro: Any) -> asyncio.Task:
        """A fire-and-forget task with a strong reference (asyncio keeps only
        weak ones), cancelled when the conversation stops."""
        task = asyncio.ensure_future(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)
        return task

    def cancel_background(self) -> None:
        for task in list(self._bg):
            task.cancel()

    def rewarm(self) -> None:
        if self._warm is not None and not self._warm.done():
            self._warm.cancel()
        self._warm = asyncio.create_task(self.warm_phrases())

    @staticmethod
    def make_signature(seats: list[dict], settings: dict) -> str:
        return json.dumps([[s["key"], bool(s.get("listen"))] for s in seats]
                          + [bool(settings.get("simulate")), settings.get("people_mic") or "auto"])

    def note(self, text: str) -> None:
        self.m.note(text)

    # ------------------------------------------------------------- open
    async def open(self) -> None:
        from .robots import PEOPLE_MIC_KEY, LaptopLink, RobotLink

        simulate = bool(self.settings.get("simulate"))
        # A laptop robot next to real ones (testing with one Reachy) only
        # speaks: the people are heard through the DJI or the robots' mics.
        robot_keys = [s["key"] for s in self.seats if s.get("listen")
                      and (simulate or not is_laptop_seat(s))]
        # Both kinds of mic are always ready (2026-10-22): the people's own
        # (the DJI on the laptop) is heard, the robots' wait silently on the
        # robots and come on at once (use_robot_mics: the page's button, or
        # the DJI going quiet or away).
        listening = robot_keys + ([] if simulate else [PEOPLE_MIC_KEY])
        self.m.set_status({"phase": "starting", "detail": "loading voice detection"})
        self.ears = await asyncio.to_thread(
            Ears, listening, float(self.settings.get("voice_min_level") or 0.0),
            BARGE_DB.get(self.settings.get("barge_in"), 10.0))
        try:
            self.ears.priors = dict(json.loads(ECHO_FILE.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
        device = None
        if not simulate:
            choice = str(self.settings.get("people_mic") or "auto")
            device = await self.open_people_mic(choice)
            if device is None and choice not in ("auto", "robots"):
                self.note("the microphone {!r} is not plugged in: the robots' mics listen "
                          "instead".format(choice))
            elif device is None and choice == "auto":
                self.note("no DJI microphone on the laptop: the robots' mics listen")
        self.mic_in_use = "people" if device is not None else "robots"
        self.ears.set_active([PEOPLE_MIC_KEY] if device is not None else robot_keys)
        if not simulate:
            # Each robot's own conversation app would fight over the speaker:
            # stop them all at once (one by one took up to 40 s each).
            async def _stop(seat: dict) -> None:
                adapter = self.m.hub.adapters.get(seat["key"])
                stop = getattr(adapter, "stop_system", None)
                if stop is None:
                    return
                try:
                    await asyncio.wait_for(stop(), 40)
                except Exception as exc:  # noqa: BLE001
                    self.note("could not stop {}'s own app: {}".format(seat["name"], exc))
            self.m.set_status({"phase": "starting", "detail": "stopping the robots' own apps"})
            await asyncio.gather(*(_stop(s) for s in self.seats))
        for seat in self.seats:
            if simulate or is_laptop_seat(seat):
                link = LaptopLink(seat["key"], seat["name"],
                                  listen=simulate and bool(seat.get("listen")))
            else:
                adapter = self.m.hub.adapters.get(seat["key"])
                robot = self.m.hub.registry.get(seat["key"])
                if adapter is None or robot is None or not robot.address:
                    self.note("{} is not connected; it sits this one out".format(seat["name"]))
                    continue
                if robot.state == "RUNNING":
                    self.m.hub.registry.set_state(seat["key"], "CONNECTED",
                                                  "in a group conversation")
                user, password = adapter._ssh_creds()
                link = RobotLink(seat["key"], seat["name"], robot.address, user, password,
                                 listen=bool(seat.get("listen")),
                                 standby=self.mic_in_use == "people")
            link.on_mic = self.ears.feed
            self.links[seat["key"]] = link

        self.m.set_status({"phase": "starting", "detail": "connecting to the robots"})

        async def _open(key: str, link: Any) -> None:
            try:
                await asyncio.wait_for(link.open(), 60)
            except Exception as exc:  # noqa: BLE001
                self.links.pop(key, None)
                self.note("{} could not join: {}".format(link.name, exc))

        await asyncio.gather(*(_open(k, l) for k, l in list(self.links.items())),
                             self.services.warm(), self.choose_voices())
        self.seats = [s for s in self.seats if s["key"] in self.links]
        if not self.seats:
            raise RuntimeError("no robot could join the conversation")
        for key, link in self.links.items():
            err = getattr(link, "last_error", "")
            if err:
                self.note("{}: {}".format(link.name, err))
        self.ears.set_open(True)
        self._keeper = asyncio.create_task(self.keep_heads())
        self._mic_guard = asyncio.create_task(self.guard_people_mic())
        # rewarm, not a second task: OpenAI refusing during the warm-up above
        # has already started one, and two at once (2026-10-21, "voiced 159"
        # + "voiced 99") voiced phrases twice and hit ElevenLabs' 3 at a time.
        self.rewarm()

    # ------------------------------------------------------- the people's mic
    async def open_people_mic(self, choice: str = "auto") -> Optional[dict]:
        """Open the people's own mic (laptop_mic.MIC_WATCH knows what is
        plugged in); None when there is none or it would not open."""
        from .. import laptop_mic
        from .robots import PeopleMic
        device = laptop_mic.MIC_WATCH.find(choice)
        if device is None:
            return None
        mic = PeopleMic(device, self.ears.feed)
        try:
            await asyncio.to_thread(mic.open)
        except Exception as exc:  # noqa: BLE001
            self.note("{}; the robots' mics listen instead".format(exc))
            return None
        self.people_mic = mic
        self.note("the people are heard through {}".format(device["name"]))
        return device

    async def close_people_mic(self) -> None:
        mic, self.people_mic = self.people_mic, None
        if mic is not None:
            await asyncio.to_thread(mic.close)

    def robot_mic_keys(self) -> list[str]:
        return [s["key"] for s in self.seats if s.get("listen") and s["key"] in self.links]

    async def use_robot_mics(self, why: str) -> bool:
        """The robots' mics, at once: they are already running on the robots
        and only start sending. The conversation goes on as it was."""
        if self.mic_in_use == "robots":
            return True
        keys = self.robot_mic_keys()
        oks = await asyncio.gather(*(self.links[k].set_mic_live(True) for k in keys),
                                   return_exceptions=True)
        self.ears.set_active(keys)
        self.mic_in_use = "robots"
        bad = [self.links[k].name for k, ok in zip(keys, oks) if ok is not True]
        self.note("{}: the robots' mics listen now{}".format(
            why, " (no mic on {})".format(", ".join(bad)) if bad else ""))
        self.m.publish_state()
        return not bad or len(bad) < len(keys)

    async def use_people_mic(self) -> bool:
        """Back to the people's own mic (the page's button), if it is there."""
        from .robots import PEOPLE_MIC_KEY
        if self.mic_in_use == "people":
            return True
        if self.people_mic is None or self.people_mic.health() != "ok":
            await self.close_people_mic()
            choice = str(self.settings.get("people_mic") or "auto")
            if await self.open_people_mic("auto" if choice == "robots" else choice) is None:
                self.note("no DJI microphone to switch to: the robots' mics keep listening")
                self.m.publish_state()
                return False
        self.ears.set_active([PEOPLE_MIC_KEY])
        self.mic_in_use = "people"
        await asyncio.gather(*(self.links[k].set_mic_live(False) for k in self.robot_mic_keys()),
                             return_exceptions=True)
        self.note("the people are heard through {} again".format(self.people_mic.name))
        self.m.publish_state()
        return True

    async def guard_people_mic(self) -> None:
        """The DJI going quiet for good (transmitter off, flat battery, out
        of range) or away (unplugged) switches to the robots' mics by itself.
        Its battery cannot be read over USB, so this is what stands in."""
        reasons = {"stalled": "the DJI mic stopped sending (unplugged?)",
                   "flat": "the DJI mic has gone silent (transmitter off or battery flat?)",
                   "closed": "the DJI mic closed"}
        while True:
            await asyncio.sleep(0.25)
            mic = self.people_mic
            if self.mic_in_use != "people" or mic is None:
                continue
            health = mic.health()
            if health != "ok":
                log.warning("people's mic: %s", health)
                await self.use_robot_mics(reasons.get(health, health))
                if health in ("stalled", "closed"):
                    await self.close_people_mic()

    def mic_state(self) -> dict:
        mic = self.people_mic
        return {"in_use": self.mic_in_use,
                "people_mic": mic.name if mic is not None else "",
                "health": mic.health() if mic is not None else "",
                "robot_mics": [self.links[k].name for k in self.robot_mic_keys()
                               if getattr(self.links[k], "mic_source", "")]}

    async def choose_voices(self) -> None:
        if not any(self.provider(s) in ("auto", "elevenlabs") for s in self.seats):
            return
        credits = await eleven_credits(self.services.eleven_key)
        self.m.eleven_credits = credits
        if self.eleven_low() and any(self.provider(s) == "auto" for s in self.seats):
            self.note("ElevenLabs has {} characters left, so the robots on Auto use other "
                      "voices (top it up, or pick ElevenLabs for a robot to use what is "
                      "left)".format(credits))

    def provider(self, seat: dict) -> str:
        """The voice provider the page picked for this robot."""
        p = seat.get("voice_provider") or self.settings.get("voice_provider") or "auto"
        return p if p in VOICE_PROVIDERS else "auto"

    def eleven_low(self) -> bool:
        credits = self.m.eleven_credits
        return credits is not None and credits < ELEVEN_MIN_CREDITS

    def voice_backend(self, seat: dict, skip_eleven: bool = False) -> str:
        """"eleven", "openai", "openrouter" or "gemini" for this robot, from its
        provider and what still works: ElevenLabs while it has credits (Auto)
        or until it refuses, then OpenAI, then OpenRouter or Gemini.
        `skip_eleven`: the stand-in for one line ElevenLabs could not voice."""
        provider = self.provider(seat)
        gemini = bool(self.services.gemini_key)
        router = bool(self.services.openrouter_key)
        openai_ok = self.services.openai_ok
        if provider == "gemini" and gemini:
            return "gemini"
        if provider == "openrouter" and router:
            return "openrouter"
        if provider == "elevenlabs" and self.services.eleven_key:
            # Locked (Tomer, 2026-10-22): a robot set to ElevenLabs never
            # changes voice mid-conversation; a line it cannot get is retried,
            # then skipped (voice()), never voiced by someone else.
            return "eleven"
        eleven = not self.eleven_down and not skip_eleven
        if provider == "auto" and eleven and not self.eleven_low():
            return "eleven"
        if openai_ok or not (router or gemini):
            return "openai"
        return "openrouter" if router else "gemini"

    def use_eleven(self) -> bool:
        return any(self.voice_backend(s) == "eleven" for s in self.seats)

    async def warm_phrases(self) -> None:
        """Voice the interjections for every seat that has none on disk yet
        (OpenAI and ElevenLabs voices only; see below)."""
        # Gemini: a daily cap. OpenRouter: raw audio only, ~100 KB a phrase,
        # far too heavy for the phone hotspot. Both use what is on disk.
        seats = [s for s in self.seats if self.voice_backend(s) in ("eleven", "openai")]
        if not seats:
            return
        try:
            langs = {"he": ["he"], "en": ["en"]}.get(self.settings.get("language"), ["he", "en"])
            made = await self.phrases.warm([(self.voice_key(s), s["character"]) for s in seats], langs,
                                           self.synth_phrase)
            if made:
                log.info("voiced %d interjections", made)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("voicing the interjections")

    def voice_key(self, seat: dict) -> str:
        backend = self.voice_backend(seat)
        if backend == "eleven":
            return "el:" + self.eleven_voice(seat)
        if backend == "gemini":
            return "gm:{}:{}".format(self.gemini_voice(seat), seat["character"])
        if backend == "openrouter":
            return "or:{}:{}".format(self.router_voice(seat), seat["character"])
        return "oa:{}:{}".format(self.openai_voice(seat), seat["character"])

    def seat_index(self, seat: dict) -> int:
        keys = [s["key"] for s in self.seats]
        return keys.index(seat["key"]) if seat["key"] in keys else 0

    @staticmethod
    def eleven_voice(seat: dict) -> str:
        return seat.get("voice_id") or DEFAULT_CHARACTERS[0]["voice_id"]

    def gemini_voice(self, seat: dict) -> str:
        return seat.get("gemini_voice") or default_gemini_voice(seat, self.seat_index(seat))

    async def synth_phrase(self, voice_key: str, text: str, tone: str) -> bytes:
        seat = next((s for s in self.seats if self.voice_key(s) == voice_key), None)
        if seat is None:
            return b""
        chunks = []
        if voice_key.startswith("el:"):
            async for c in self.services.speech(voice_key[3:], text, background=True):
                chunks.append(c)
        elif voice_key.startswith("or:"):
            async for c in openrouter_speech(self.services.http, self.services.openrouter_key,
                                             self.router_voice(seat), text,
                                             self.voice_style(seat, tone)):
                chunks.append(c)
        elif voice_key.startswith("gm:"):
            key, model = self.services.gemini_tts()
            try:
                async for c in gemini_speech(self.services.http, key, self.gemini_voice(seat),
                                             text, tone_words(tone), model):
                    chunks.append(c)
            except ServiceError as exc:
                self.services.gemini_tts_refused(key, model, exc.status, exc.body)
                raise
        else:
            async for c in openai_speech(self.services.http, self.services.openai_key,
                                         self.openai_voice(seat), text,
                                         self.voice_style(seat, tone), self.services.compressed):
                chunks.append(c)
        return b"".join(chunks)

    # ------------------------------------------------------------ close
    async def close(self) -> None:
        for task in (self._keeper, self._warm, self._mic_guard):
            if task is not None:
                task.cancel()
        self.cancel_background()
        await self.close_people_mic()
        if self.ears is not None:
            self.ears.set_open(False)
            learned = self.ears.couplings()
            if learned and not self.settings.get("simulate")                     and not any(is_laptop_seat(s) for s in self.seats):
                # The table is usually set up the same way all day: the next
                # session starts from these instead of a deaf guess.
                try:
                    ECHO_FILE.parent.mkdir(parents=True, exist_ok=True)
                    ECHO_FILE.write_text(json.dumps({**self.ears.priors, **learned}, indent=1),
                                         encoding="utf-8")
                except OSError as exc:
                    log.info("could not save the echo map: %s", exc)

        async def _close(link: Any) -> None:
            try:
                await asyncio.wait_for(link.stop_audio(), 5)
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(link.close(), 15)
            except Exception as exc:  # noqa: BLE001
                log.info("closing %s: %s", getattr(link, "name", "?"), exc)

        await asyncio.gather(*(_close(l) for l in self.links.values()))
        # The services (and their warm connections) belong to the manager and
        # outlive the robots' connection (GroupManager.shared_services).

    async def quiet(self) -> None:
        """Between conversations: every robot silent, heads to the middle."""
        self.cancel_background()
        sends = []
        for key, link in self.links.items():
            sends.append(link.stop_audio())
            sends.append(link.motion({"type": "head", "direction": "front"}))
        self.heads = {}
        self.busy_until = {}
        self.speaking_key = None
        self.life_hold = {}
        await asyncio.gather(*sends, return_exceptions=True)

    def drop_dead_links(self) -> list[str]:
        """Robots whose player died mid-session leave the table."""
        gone = [k for k, l in self.links.items() if not getattr(l, "connected", True)]
        for key in gone:
            link = self.links.pop(key)
            self.seats = [s for s in self.seats if s["key"] != key]
            self.note("{} dropped out: {}".format(link.name, getattr(link, "last_error", "")
                                                  or "its connection closed"))
        return gone

    # ------------------------------------------------------------ voices
    def openai_voice(self, seat: dict) -> str:
        return seat.get("openai_voice") or default_openai_voice(seat, self.seat_index(seat))

    def router_voice(self, seat: dict) -> str:
        """OpenRouter's voice takes only some of OpenAI's voices."""
        voice = self.openai_voice(seat)
        if voice in OPENROUTER_VOICES:
            return voice
        voice = default_openai_voice(seat, self.seat_index(seat))
        return voice if voice in OPENROUTER_VOICES else "ash"

    @staticmethod
    def voice_style(seat: dict, tone: str) -> str:
        who = VOICE_STYLE.get(seat["character"]) or (seat.get("persona") or "")[:120]
        return ("Voice: {}. Say this {}. Acted and expressive, lively and engaged, never "
                "flat or monotone. Natural pace.".format(
                    who, tone or "naturally, with feeling"))

    @staticmethod
    async def _pump(stream: Any, line: Line) -> None:
        """Copy a TTS stream into the line, with a watchdog: the 2026-10-21 dry
        run had an OpenAI voice stall for 30 s mid-conversation while a robot
        held the floor in silence. No first audio in FIRST_AUDIO_S, or a gap
        of STALL_S after it, raises TimeoutError."""
        it = stream.__aiter__()
        first = True
        while True:
            try:
                chunk = await asyncio.wait_for(it.__anext__(),
                                               FIRST_AUDIO_S + HEDGE_TTS_S + 1.0 if first else STALL_S)
            except StopAsyncIteration:
                return
            first = False
            line.audio.add(chunk)

    async def eleven_locked(self, line: Line, voice: str, text: str) -> None:
        """A robot set to ElevenLabs: its own voice or nothing. A request with
        no audio after ELEVEN_HEDGE_S is raced by a second one; a failed line
        is asked again (up to ELEVEN_LINE_TRIES, within ELEVEN_LINE_S); if it
        still fails the line is skipped and the conversation goes on. A
        refusal for good (bad key, no credits) is said once on the page."""
        deadline = time.monotonic() + ELEVEN_LINE_S
        for attempt in range(1, ELEVEN_LINE_TRIES + 1):
            try:
                await self._pump(hedged_stream(lambda: self.services.speech(voice, text),
                                               ELEVEN_HEDGE_S), line)
                return
            except ServiceError as exc:
                if line.playing:
                    raise
                line.audio.chunks.clear()
                if eleven_gone(exc):
                    if not self.eleven_down:
                        self.eleven_down = True
                        self.note("ElevenLabs refused for good ({}): robots set to ElevenLabs "
                                  "stay silent until it is fixed; their voice is never "
                                  "swapped".format(str(exc)[:120]))
                    raise
                err: Exception = exc
            except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                if line.playing:
                    raise
                line.audio.chunks.clear()
                err = exc
            if attempt == ELEVEN_LINE_TRIES or time.monotonic() > deadline:
                raise err
            log.info("ElevenLabs could not voice a line (%s: %s); asking again (%d)",
                     type(err).__name__, str(err)[:120], attempt)
            await asyncio.sleep(0.3 * attempt)

    async def voice(self, line: Line) -> None:
        """ElevenLabs or OpenAI (settings + credits); ElevenLabs refusing
        before the first audio moves the whole session to OpenAI. A voice that
        never starts is tried once more (OpenAI) before the line is given up.
        A robot set to ElevenLabs itself never changes voice (eleven_locked)."""
        seat = line.seat
        text = line.text
        try:
            line.voice_t0 = time.monotonic()
            # One line ElevenLabs could not voice gets a stand-in; only a
            # refusal for good (eleven_gone) drops it for the session.
            skip = False
            if self.voice_backend(seat) == "eleven":
                line.voice_used = "ElevenLabs"
                voice = self.eleven_voice(seat)
                tag = ""
                t = line.tone.lower()
                if "laugh" in t:
                    tag = "[laughs] "
                elif "sigh" in t:
                    tag = "[sighs] "
                if self.provider(seat) == "elevenlabs":
                    await self.eleven_locked(line, voice, tag + pronounce(text))
                    line.audio.finish()
                    return
                try:
                    await self._pump(self.services.speech(voice, tag + pronounce(text)), line)
                    line.audio.finish()
                    return
                except ServiceError as exc:
                    if line.playing:
                        raise
                    line.audio.chunks.clear()
                    skip = True
                    if eleven_gone(exc):
                        self.eleven_down = True
                        self.note("ElevenLabs refused ({}); the robots use {} voices from now "
                                  "on".format(str(exc)[:120],
                                              VOICE_NAMES[self.voice_backend(seat)]))
                    else:
                        log.info("ElevenLabs could not voice this line (%s); it uses %s",
                                 str(exc)[:160], VOICE_NAMES[self.voice_backend(seat, True)])
                except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                    if line.playing:
                        raise
                    line.audio.chunks.clear()
                    skip = True
                    log.info("ElevenLabs stalled (%s); this line uses %s", type(exc).__name__,
                             VOICE_NAMES[self.voice_backend(seat, True)])
            for attempt in (1, 2):
                backend = self.voice_backend(seat, skip)
                line.voice_used = VOICE_NAMES[backend]
                try:
                    if backend == "gemini":
                        # No racing here: every Gemini voice request counts
                        # against a small daily cap.
                        gkey, gmodel = self.services.gemini_tts()
                        try:
                            await self._pump(gemini_speech(
                                self.services.http, gkey, self.gemini_voice(seat),
                                pronounce(text), tone_words(line.tone), gmodel), line)
                        except ServiceError as exc:
                            self.services.gemini_tts_refused(gkey, gmodel, exc.status, exc.body)
                            if not line.playing:
                                line.audio.chunks.clear()
                                if attempt == 1:
                                    continue
                            raise
                    elif backend == "openrouter":
                        await self._pump(hedged_stream(lambda: openrouter_speech(
                            self.services.http, self.services.openrouter_key,
                            self.router_voice(seat), pronounce(text),
                            self.voice_style(seat, line.tone)), HEDGE_TTS_S + 0.7), line)
                    else:
                        await self._pump(hedged_stream(lambda: openai_speech(
                            self.services.http, self.services.openai_key,
                            self.openai_voice(seat), pronounce(text),
                            self.voice_style(seat, line.tone), self.services.compressed),
                            HEDGE_TTS_S + (1.5 if self.services.compressed else 0.0)), line)
                    break
                except ServiceError as exc:
                    # No credits / bad key: the session moves to Gemini voices
                    # (or to the next Gemini key).
                    if (not line.playing and exc.status and "Gemini" not in str(exc)
                            and self.services.openai_refused(exc.status, exc.body)):
                        line.audio.chunks.clear()
                        continue
                    if line.playing or attempt == 2:
                        raise
                    line.audio.chunks.clear()
                except (asyncio.TimeoutError, httpx.HTTPError) as exc:
                    # Stalled before the robot started it: start the line over.
                    if line.playing or attempt == 2:
                        raise
                    line.audio.chunks.clear()
                    log.info("OpenAI voice stalled (%s); voicing the line again",
                             type(exc).__name__)
            line.audio.finish()
        except asyncio.CancelledError:
            line.audio.finish("cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            line.audio.finish("{}: {}".format(type(exc).__name__, exc))

    # ------------------------------------------------------------- heads
    async def keep_heads(self) -> None:
        """Every robot that is not speaking lives a little on its own.

        Tomer, 2026-10-21: all robots "breathing" while the group chat is on,
        free to move while they listen, never still. The player breathes by
        itself whenever no move is queued; on top of that each listener, at
        its own random pace, either looks at whoever has the floor (a head
        turn peaks after ~1 s and the breathing pulls it back, so a look is
        held by re-sending it every HEAD_HOLD_S), lets go and just breathes,
        makes a small listening gesture, or glances elsewhere. A robot in the
        middle of a gesture, and the robot that is speaking, are left alone.
        """
        while True:
            await asyncio.sleep(0.2)
            now = time.monotonic()
            for key in list(self.links):
                if key == self.speaking_key or self.busy_until.get(key, 0) > now:
                    continue
                target = self.heads.get(key, "front")
                if now < self.life_next.get(key, 0):
                    # Holding a look: re-send it now and then, or it drifts back.
                    if (self.life_hold.get(key) and self.life_hold[key] != "front"
                            and now - self.life_sent.get(key, 0) >= HEAD_HOLD_S):
                        self.life_sent[key] = now
                        self.spawn(self.links[key].motion(
                            {"type": "head", "direction": self.life_hold[key]}))
                    continue
                self.life_next[key] = now + self.life_step(key, target, now)

    def life_step(self, key: str, target: str, now: float) -> float:
        """One idle action for a listener; returns how long it lasts."""
        talking = self.m.status.get("phase") in ("speaking", "human")
        r = random.random()
        link = self.links[key]
        if talking and r < 0.45:
            # Look at whoever has the floor (front = the people).
            self.life_hold[key] = target
            self.life_sent[key] = now
            self.spawn(link.motion({"type": "head", "direction": target}))
            return random.uniform(1.5, 3.5)
        if r < (0.75 if talking else 0.6):
            # Let go: the player's own breathing.
            self.life_hold[key] = ""
            self.spawn(link.motion({"type": "stop"}))
            return random.uniform(1.8, 4.0)
        calm = self.seat_of(key).get("gestures") == "calm"
        if r < (0.92 if talking else 0.85) and not (calm and random.random() < 0.6):
            name = random.choice(moves.IDLE_LISTENING if talking else moves.IDLE_WAITING)
            self.life_hold[key] = ""
            self.spawn(self.gesture(key, name))
            return random.uniform(2.0, 4.0)
        # A glance somewhere else, briefly.
        others = [d for d in ("left", "right", "up", "down") if d != target]
        self.life_hold[key] = random.choice(others)
        self.life_sent[key] = now
        self.spawn(link.motion({"type": "head", "direction": self.life_hold[key]}))
        return random.uniform(0.8, 1.6)

    async def look(self, speaker: Optional[dict]) -> None:
        """Everyone faces the speaker; the speaker (or everyone, for the
        people) faces the room. Seats are left to right as the people see
        them and the robots face the people, so a seat further right is on a
        robot's own left."""
        order = [s["key"] for s in self.seats]
        mirror = bool(self.settings.get("heads_mirror"))
        now = time.monotonic()
        sends = []
        for i, key in enumerate(order):
            if speaker is None or key == speaker["key"] or speaker["key"] not in order:
                d = "front"
            else:
                j = order.index(speaker["key"])
                d = "left" if (j > i) != mirror else "right"
            if self.heads.get(key) != d and key in self.links:
                self.heads[key] = d
                if self.busy_until.get(key, 0) < now:
                    # Everyone turns to a new speaker at once; then they live
                    # on their own (keep_heads) after holding the look a while.
                    sends.append(self.links[key].motion({"type": "head", "direction": d}))
                    self.life_hold[key] = d
                    self.life_sent[key] = now
                    self.life_next[key] = now + random.uniform(1.5, 3.5)
        if sends:
            await asyncio.gather(*sends, return_exceptions=True)

    async def gesture(self, key: str, name: str) -> bool:
        cmd = moves.command(name)
        link = self.links.get(key)
        if cmd is None or link is None:
            return False
        motion, dur = cmd
        self.busy_until[key] = time.monotonic() + dur
        try:
            await link.motion(motion)
        except Exception as exc:  # noqa: BLE001
            log.info("gesture %s on %s failed: %s", name, key, exc)
            return False
        return True

    def seat_of(self, key: Optional[str]) -> dict:
        return next((s for s in self.seats if s["key"] == key), {})

    async def snapshot(self, key: Optional[str]) -> Optional[bytes]:
        """What this robot's camera sees, unless its camera is off on the page."""
        link = self.links.get(key or "")
        seat = self.seat_of(key)
        if link is None or not seat.get("vision", self.settings.get("vision", True)):
            return None
        snap = getattr(link, "snapshot", None)
        if snap is None:
            return None
        try:
            return await asyncio.wait_for(snap(), 2.0)
        except Exception as exc:  # noqa: BLE001
            log.info("snapshot from %s failed: %s", key, exc)
            return None


# ========================================================== conversation
class Conversation:
    """What both modes share: the transcript, the director, speaking."""

    mode = "group"

    def __init__(self, manager: "GroupManager", session: Session) -> None:
        self.m = manager
        self.s = session
        self.settings = session.settings
        self.services = session.services
        self.t0 = time.monotonic()
        self.first = len(manager.transcript)        # this conversation's lines start here
        topic = self.settings.get("topic", "")
        self.lang = {"he": "he", "en": "en"}.get(self.settings.get("language")) or (
            "he" if (_hebrew(topic) or not topic) else "en")
        self.last_robot: Optional[str] = None
        self.spoke_at: dict[str, float] = {s["key"]: 0.0 for s in session.seats}
        self.silence_since = time.monotonic()
        self.failures = 0
        self.last_line: Optional[Line] = None
        self.recent_robot: list[tuple[float, str]] = []   # (time, text) for strip_echo
        # The first line, written and voiced while the robots waited (Get
        # ready / after a Stop), so Start speaks at once (2026-10-22).
        self.premade: Optional[asyncio.Future] = None

    def restart_clock(self) -> None:
        """A conversation made ahead of time starts now."""
        self.t0 = self.silence_since = time.monotonic()
        self.first = len(self.m.transcript)

    def opener(self) -> "asyncio.Future":
        """The task that writes (and voices) this mode's first line."""
        raise NotImplementedError

    @property
    def seats(self) -> list[dict]:
        return self.s.seats

    @property
    def ears(self) -> Ears:
        assert self.s.ears is not None
        return self.s.ears

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def fixed_language(self) -> str:
        """"he" or "en" when the page fixes the language, else "" (either)."""
        lang = self.settings.get("language")
        return lang if lang in ("he", "en") else ""

    # Minutes added on the page while it runs (+1), and a graceful Stop:
    # every robot says a closing line, then it ends (Tomer, 2026-10-25).
    extra_s = 0.0
    closing = False

    def limit(self) -> float:
        return max(0.5, float(self.settings.get("minutes") or 5)) * 60 + self.extra_s

    def time_up(self, ahead: float = 0.0) -> bool:
        return self.elapsed() + ahead >= self.limit()

    def status(self, phase: str, speaker: Optional[dict] = None, detail: str = "") -> None:
        sig = (phase, speaker["key"] if speaker else None, detail)
        if sig == getattr(self, "_status_sig", None) and self.m.status.get("phase") == phase:
            return
        self._status_sig = sig
        self.m.set_status({"phase": phase,
                           "speaker": speaker["name"] if speaker else None,
                           "character": speaker["character"] if speaker else None,
                           "elapsed_s": round(self.elapsed(), 1), "detail": detail,
                           "mode": self.mode})

    def turn(self, **fields: Any) -> dict:
        entry = {"id": len(self.m.transcript) + 1, "t": round(self.elapsed(), 1),
                 "who": None, "character": None, "kind": "robot", "text": "",
                 "move": "", "latency_ms": None, "cut": False, "heard_by": None,
                 "mode": self.mode}
        hold = fields.pop("hold", fields.get("kind", "robot") == "robot")
        entry.update(fields)
        self.m.add_turn(entry)
        # A robot line goes to the log when it has been spoken (finish_entry):
        # until 2026-10-22 it was written before it played, so latency_ms and
        # cut were never in any log.
        self.m.log_turn(entry, hold=hold)
        return entry

    @staticmethod
    def timings(line: Line, entry: dict) -> None:
        """A line's writer and voice timings onto its log entry (at its first
        sound, so a line a Stop cuts short has them too)."""
        if line.director_s:
            entry["writer_ms"] = int(line.director_s * 1000)
        if line.voice_used:
            entry["voice"] = line.voice_used
        if line.voice_t0 and line.audio.first_at:
            entry["voice_first_ms"] = int((line.audio.first_at - line.voice_t0) * 1000)

    def finish_entry(self, line: Line, entry: dict) -> None:
        """A spoken (or cut) line: its timings, then the log."""
        self.timings(line, entry)
        self.m.log_turn(entry)

    def note(self, text: str) -> None:
        self.m.note(text)

    def mine(self) -> list[dict]:
        return self.m.transcript[self.first:]

    # ---------------------------------------------------------- prompts
    def language_rule(self) -> str:
        choice = self.settings.get("language", "auto")
        gender = ("Use natural everyday spoken language; in Hebrew the robots use "
                  "masculine forms.")
        if choice == "he":
            return "Hebrew only. " + gender
        if choice == "en":
            return "English only. " + gender
        now = "Hebrew" if self.lang == "he" else "English"
        return ("Speak the language the people used last (Hebrew or English); right "
                "now that is {}. {}".format(now, gender))

    def cast(self) -> str:
        return "\n".join("- {} - {} - {}".format(s["character"], s["name"], s.get("persona") or "")
                         for s in self.seats)

    def calm(self, seat: dict) -> bool:
        return (seat.get("gestures") or self.settings.get("gestures", "lively")) == "calm"

    def common(self) -> dict:
        names = ", ".join("{}={}".format(s["character"], HEBREW_NAMES[s["character"]])
                          if s["character"] in HEBREW_NAMES else s["character"]
                          for s in self.seats)
        calm = [s["character"] for s in self.seats if self.calm(s)]
        lively = [s["character"] for s in self.seats if not self.calm(s)]
        if not calm:
            rule = ("Give the speaker a gesture on almost every line, and a listener reaction "
                    "on most lines.")
        elif not lively:
            rule = "Give the speaker a gesture on about half the lines; reactions are rare."
        else:
            # Each robot has its own body language (page, per robot).
            rule = ("Lively robots ({}) gesture on almost every line they say and react "
                    "often; calm robots ({}) gesture on about half their lines and rarely "
                    "react.".format(", ".join(lively), ", ".join(calm)))
        return {"cast": self.cast(), "hebrew_names": names, "language": self.language_rule(),
                "lab": lab_facts(),
                "moves": moves.menu(), "gesture_rule": rule,
                "topic": self.settings.get("topic") or ""}

    def history(self, extra_human: Optional[tuple[str, Optional[str]]] = None,
                limit: int = 40) -> list[str]:
        lines = []
        for t in self.mine()[-limit:]:
            if t["kind"] == "robot":
                if t.get("unspoken"):
                    continue
                said = t.get("spoken") or t["text"]
                # By the robot's name now: the page may rename a character mid-talk.
                seat = next((s for s in self.seats if s["name"] == t.get("who")), None)
                lines.append("{}: {}{}".format(
                    seat["character"] if seat else t["character"], said,
                    " [cut off by a noise; nobody spoke]" if t.get("cut_noise")
                    else " [cut off by the people]" if t.get("cut") else ""))
            elif t["kind"] == "human":
                where = " (heard closest to {})".format(self.character_of(t["heard_by"])) \
                    if t.get("heard_by") else ""
                lines.append("PEOPLE{}: {}".format(where, t["text"]))
        if extra_human is not None:
            text, heard = extra_human
            where = " (heard closest to {})".format(self.character_of(heard)) if heard else ""
            lines.append("PEOPLE{}: {}".format(where, text))
        return lines

    def names_said(self) -> list[str]:
        """The people's names a robot has already said (once is the most,
        Tomer 2026-10-25); the whole session, across modes."""
        robot = [t.get("spoken") or t["text"] for t in self.m.transcript
                 if t["kind"] == "robot" and not t.get("unspoken")]
        names = people_names([t["text"] for t in self.m.transcript if t["kind"] == "human"],
                             robot)
        return sorted(n for n in names if any(says_name(r, n) for r in robot))

    def character_of(self, robot_name: Optional[str]) -> str:
        s = next((s for s in self.seats if s["name"] == robot_name), None)
        return s["character"] if s else (robot_name or "?")

    def character_of_key(self, key: Optional[str]) -> str:
        s = next((s for s in self.seats if s["key"] == key), None)
        return s["character"] if s else "?"

    def seat_of_key(self, key: Optional[str]) -> Optional[dict]:
        return next((s for s in self.seats if s["key"] == key), None)

    def named_seat(self, text: str) -> Optional[dict]:
        named = [s for s in self.seats if self.names_in(s, text)]
        return named[0] if len(named) == 1 else None

    @staticmethod
    def names_in(seat: dict, text: str) -> bool:
        words = set(re.findall(r"[\w֐-׿]+", (text or "").lower()))
        names = {seat["character"].lower(), seat["name"].lower(),
                 HEBREW_NAMES.get(seat["character"], "")} - {""}
        return any(w in names or (len(w) > 2 and w[1:] in names) for w in words)

    def pick(self, name: Any, people_text: Optional[str] = None,
             allow_repeat: bool = False) -> dict:
        n = str(name or "").strip().lower()
        chosen = next((s for s in self.seats
                       if n and n in (s["character"].lower(), s["name"].lower(),
                                      HEBREW_NAMES.get(s["character"], "-"))), None)
        if people_text:
            named = self.named_seat(people_text)
            if named is not None:
                return named
        repeat = (chosen is not None and chosen["key"] == self.last_robot
                  and not people_text and not allow_repeat and len(self.seats) > 1)
        if chosen is None or repeat:
            others = [s for s in self.seats if s["key"] != self.last_robot] or self.seats
            chosen = min(others, key=lambda s: self.spoke_at.get(s["key"], 0.0))
        return chosen

    # --------------------------------------------------------- director
    def writer_of(self, seat: Optional[dict]) -> str:
        """The model that writes this robot's lines (page, per robot)."""
        w = (seat or {}).get("writer") or self.settings.get("director_model") or DIRECTOR_MODEL
        return w if w in DIRECTOR_MODELS else DIRECTOR_MODEL

    def one_writer(self) -> Optional[str]:
        """The writer when every robot has the same one, else None: then the
        conductor picks the next speaker first and that robot's writer writes."""
        writers = {self.writer_of(s) for s in self.seats}
        return writers.pop() if len(writers) == 1 else None

    def next_speaker(self, people_text: Optional[str] = None,
                     heard: Optional[str] = None) -> dict:
        """Who talks next when the conductor must choose (robots with
        different writers): a robot the people named, else the one they were
        closest to, else mostly the quietest robot that did not just speak."""
        if people_text:
            named = self.named_seat(people_text)
            if named is not None:
                return named
            near = next((s for s in self.seats if s["name"] == heard), None)
            if near is not None:
                return near
        others = [s for s in self.seats if s["key"] != self.last_robot] or self.seats
        others = sorted(others, key=lambda s: self.spoke_at.get(s["key"], 0.0))
        return others[0] if random.random() < 0.6 else random.choice(others)

    async def ask(self, system: str, user: str, image: Optional[bytes] = None,
                  model: str = "") -> dict:
        """The director, raced by a second identical call if the first has not
        answered in HEDGE_DIRECTOR_S (usual answer ~0.9 s); then one retry.
        ServiceError when everything failed."""
        model = model or self.services.director_model
        first = asyncio.ensure_future(self.services.director(system, user, image=image,
                                                             model=model))
        second: Optional[asyncio.Future] = None
        try:
            done, _ = await asyncio.wait({first}, timeout=HEDGE_DIRECTOR_S)
            if not done:
                # The race goes to the fast model when there is one: a second
                # call to a model that is slow right now is often slow too.
                # gpt-oss takes no pictures: a line with one races Flash-Lite.
                racer = "google/gemini-3.5-flash-lite" if image else FAST_MODEL
                fast = (racer if self.services.openrouter_key and model != racer else model)
                log.info("writer slow; racing %s", fast or "a second call")
                second = asyncio.ensure_future(
                    self.services.director(system, user, image=image, timeout=6.0, model=fast))
                racing = {first, second}
                while racing:
                    done, racing = await asyncio.wait(racing, return_when=asyncio.FIRST_COMPLETED)
                    for d in done:
                        if not d.cancelled() and d.exception() is None:
                            return d.result()
                raise ServiceError("the director failed twice: {}".format(
                    first.exception() if not first.cancelled() else "cancelled"))
            return first.result()
        except ServiceError as exc:
            if second is not None:
                raise
            log.info("director failed (%s); retrying once", exc)
            return await self.services.director(system, user, image=image, timeout=6.0,
                                                model=model)
        finally:
            for f in (first, second):
                if f is not None and not f.done():
                    f.cancel()

    def make_line(self, out: dict, *, final: bool = False, nudge: str = "", t: float = 0.0,
                  people_text: Optional[str] = None, allow_repeat: bool = False,
                  voice: bool = True, speaker: Optional[dict] = None) -> Line:
        seat = speaker if speaker is not None else self.pick(out.get("speaker"), people_text,
                                                             allow_repeat)
        names = [s["character"] for s in self.seats] + ["Reachy Mini", "Reachy"] + [
            HEBREW_NAMES.get(s["character"], "")
                                                        for s in self.seats]
        text = strip_leading_name(_clean(out.get("text", "")), names)
        for name in self.names_said():
            text = strip_person_name(text, name)
        text = LABALAB_RE.sub("Laba Lab", text)     # one word is mispronounced
        reactions = out.get("reactions") if isinstance(out.get("reactions"), dict) else {}
        line = Line(seat=seat, move=_clean(out.get("move", "") or out.get("stance", ""))[:20],
                    text=text, final=final, nudge=nudge,
                    director_s=time.monotonic() - t if t else 0.0,
                    tone=_clean(out.get("tone", ""))[:60], gesture=str(out.get("gesture") or ""),
                    reactions={str(k): str(v) for k, v in list(reactions.items())[:2]},
                    stance=str(out.get("stance") or "").lower(),
                    pile_on=out.get("pile_on") if isinstance(out.get("pile_on"), dict) else None)
        recent = [t.get("gesture") for t in self.mine()
                  if t["kind"] == "robot" and t.get("who") == seat["name"]][-2:]
        if line.gesture and line.gesture in recent:
            other = moves.similar(line.gesture)
            line.gesture = other if other and other not in recent else ""
        if voice:
            line.tts = asyncio.create_task(self.s.voice(line))
        return line

    @staticmethod
    def discard(task: Optional["asyncio.Future"]) -> None:
        """Throw away a prepared line (or a task that will make one)."""
        if task is None:
            return
        if task.done():
            if not task.cancelled() and task.exception() is None:
                res = task.result()
                line = res[1] if isinstance(res, tuple) else res
                if isinstance(line, Line) and line.tts is not None:
                    line.tts.cancel()
        else:
            task.cancel()

    @staticmethod
    def ready(value: Any) -> "asyncio.Future":
        fut = asyncio.get_running_loop().create_future()
        fut.set_result(value)
        return fut

    # ------------------------------------------------------------ speak
    async def speak(self, line: Line, entry: dict, cut_by_people: bool) -> bool:
        """Play a line (its interjection first, if any) with its gestures.
        Returns False when the people cut it off (only if `cut_by_people`)."""
        s = self.s
        link = s.links.get(line.seat["key"])
        if link is None:
            return True
        key = line.seat["key"]
        self.status("speaking", speaker=line.seat)
        s.speaking_key = key
        await s.look(line.seat)
        ears = self.ears
        play_end = time.monotonic()
        played = 0.0
        total = 0.0
        first = True
        reacted = False
        start_t = time.monotonic()
        head_s = len(line.pre_pcm) / 32000.0 if line.pre_pcm else 0.0
        fillers: list[str] = []
        calm = self.calm(line.seat)

        def cut_now() -> bool:
            return (cut_by_people and ears.capturing and ears.during_robot
                    and time.monotonic() - ears.started_at >= BARGE_HOLD_S
                    and ears.silence() < 0.25)

        def line_seconds() -> float:
            got = head_s + line.audio.seconds()
            return got if line.audio.done else max(
                got, head_s + len(line.text) / SPEECH_CHARS_PER_S)

        def move(name: str) -> None:
            cmd = moves.command(name)
            if cmd is None:
                return
            s.busy_until[key] = time.monotonic() + cmd[1]   # before the task runs
            s.spawn(s.gesture(key, name))

        def tick() -> None:
            """Listeners react once; and the speaker keeps moving until its
            line is over (Tomer, 2026-10-25: half the sentence active and
            half still looked wrong). When a move ends with speech left, the
            next one is picked to fit the time left (moves.filler)."""
            nonlocal reacted
            now = time.monotonic()
            if not reacted and now - start_t > 0.8:
                reacted = True
                s.spawn(self.react(line))
            if first or s.busy_until.get(key, 0) > now:
                return
            left = start_t + PLAY_LATENCY_S + line_seconds() - now
            pick = moves.filler(line.gesture, fillers, left, calm=calm)
            if pick:
                fillers.append(pick)
                move(pick)

        async def send(chunk: bytes) -> None:
            nonlocal play_end, total
            now = time.monotonic()
            if total > 0 and now - play_end > GAP_S:
                # The robot ran dry: the voice arrived slower than it plays.
                entry["gaps"] = entry.get("gaps", 0) + 1
                entry["gap_ms"] = entry.get("gap_ms", 0) + int((now - play_end) * 1000)
            start = max(now, play_end)
            dur = len(chunk) / 32000.0
            play_end = start + dur
            total += dur
            chunk = loud(chunk, line.seat.get("loudness", DEFAULT_LOUDNESS))
            ears.add_reference(key, start + PLAY_LATENCY_S, rms_blocks(chunk))
            await link.play(chunk)

        async def chunks():
            head = 0.0
            if line.pre_pcm:
                head = len(line.pre_pcm) / 32000.0
                yield line.pre_pcm
            # Not before the rest can keep up (Audio.can_start).
            waited = time.monotonic()
            await line.audio.playable(len(line.text) / SPEECH_CHARS_PER_S, head)
            waited = time.monotonic() - waited
            if waited > 0.05:
                entry["buffer_ms"] = int(waited * 1000)
            async for c in line.audio.stream():
                yield c

        def pieces(chunk: bytes):
            for i in range(0, len(chunk), SEND_PIECE_BYTES):
                yield chunk[i:i + SEND_PIECE_BYTES]

        was_cut = False
        cancelled = False
        try:
            async for chunk in chunks():
                for piece in pieces(chunk):
                    # Paced: the robot gets its audio AUDIO_LEAD_S ahead of the
                    # speaker, not the whole line at once. Its speech sway is
                    # worked out from the audio as it arrives, so a line that
                    # arrived in 1.5 s swayed for 1.5 s of an 8 s line.
                    while not first and link.seconds_left() > AUDIO_LEAD_S:
                        tick()
                        if cut_now():
                            was_cut = True
                            break
                        await asyncio.sleep(0.02)
                    if was_cut:
                        break
                    if first:
                        first = False
                        line.playing = True
                        start_t = time.monotonic()
                        entry["latency_ms"] = int((start_t - self.silence_since) * 1000)
                        self.timings(line, entry)
                        self.m.add_turn(entry)
                        if line.gesture:
                            move(line.gesture)
                    await send(piece)
                    tick()
                    if cut_now():
                        was_cut = True
                        break
                if was_cut:
                    break
            if not was_cut:
                if line.audio.error and line.audio.error != "cancelled":
                    self.note("{}'s voice failed: {}".format(line.seat["name"], line.audio.error))
                if first:
                    # Not a sound of it was played (its voice failed): the
                    # writer must not think it was said.
                    entry["unspoken"] = True
                    self.m.add_turn(entry)
                while link.seconds_left() > 0:
                    tick()
                    if cut_now():
                        was_cut = True
                        break
                    await asyncio.sleep(0.03)
                # The end-of-line marker stops the robot's speech sway: sent
                # when the speech is really over, not when the last audio left.
                await link.end_line()
            if was_cut:
                played = max(0.0, time.monotonic() - start_t - PLAY_LATENCY_S)
                await link.stop_audio()
                ears.drop_reference(key, time.monotonic() + 0.3)
                if line.tts is not None:
                    line.tts.cancel()
                words = line.text.split()
                share = min(1.0, played / max(0.5, total))
                entry["cut"] = True
                entry["spoken"] = " ".join(words[:max(1, int(len(words) * share))]) + "..."
                self.m.add_turn(entry)
                log.info("%s cut off by the people after %.1f s", line.seat["name"], played)
                return False
        except asyncio.CancelledError:
            cancelled = True        # whoever cancelled it (a cut-in) logs it
            raise
        except Exception as exc:  # noqa: BLE001
            self.note("{} could not speak: {}".format(line.seat["name"], exc))
        finally:
            if not cancelled:
                self.finish_entry(line, entry)
            if s.speaking_key == key:
                s.speaking_key = None
            self.recent_robot.append((time.monotonic(), line.pre_text + " " + line.text))
            self.recent_robot = self.recent_robot[-6:]
        if not reacted:
            s.spawn(self.react(line))
        self.silence_since = time.monotonic()
        return True

    async def react(self, line: Line) -> None:
        """Listeners' reactions to a line, from the director's picks."""
        for character, name in list(line.reactions.items())[:2]:
            seat = next((s for s in self.seats if s["character"].lower() == character.lower()
                         or HEBREW_NAMES.get(s["character"]) == character), None)
            if seat is None or seat["key"] == line.seat["key"]:
                continue
            if self.calm(seat) and random.random() < 0.5:
                continue
            await self.s.gesture(seat["key"], name)
            await asyncio.sleep(random.uniform(0.2, 0.6))

    def robot_lines_recent(self, seconds: float = 12.0) -> list[str]:
        now = time.monotonic()
        return [t for at, t in self.recent_robot if now - at < seconds]

    def junk(self, text: str, allow_one_word: bool) -> bool:
        junk = {j.strip(".!? ") for j in STT_JUNK}
        words = _words(text)
        # One word is usually noise ("Bon.", "None." on 2026-10-19), unless it
        # is a real one-word reply: a person who says "Why?" is not ignored.
        word = words[0].lower() if len(words) == 1 else ""
        one_ok = word in SHORT_REPLIES or (allow_one_word and (
            word in ANSWER_WORDS or word.isdigit()))
        return (not text or text.strip().lower().strip(".!? ") in junk
                or (len(words) < 2 and not one_ok))

    async def run(self) -> None:
        raise NotImplementedError


# ================================================================ group
class GroupTalk(Conversation):
    """Mode 1: robots and people, everyone can talk whenever they like."""

    mode = "group"
    SYSTEM = SYSTEM_GROUP
    OPENING = ("Open the conversation: one robot greets the people in a few words and "
               "throws in the topic with a strong opinion.")
    CLOSING = ("The conversation is ending now. Write the closing line of the speaker "
               "below: its strongest final point on the topic in one or two sentences, "
               "then a short goodbye to the people.")
    # Tomer, 2026-10-25: Group talk starts with a lab intro, one line per
    # robot in seat order about Laba Lab and Guy Laban's work; then the first
    # robot hands over ("Well, let's get into it, I understand you want to
    # talk about <topic> today...") and the second robot opens the debate.
    INTRO = ("Before the debate, the robots introduce where they come from. Write the "
             "lab intro: exactly {n} spoken line(s), one per robot, in this order: {order}. "
             "Each line is one or two sentences, 12 to 30 words, about Laba Lab and Dr. Guy "
             "Laban's work, taken ONLY from LAB FACTS (never invent anything). The first "
             "greets the people, names Laba Lab at Ben-Gurion University and says what it "
             "studies in plain words (how people relate to AI and robots: language, "
             "emotion, behaviour). The next says, with real respect, that the lab is led "
             "by Dr. Guy Laban, one of the leading researchers in his field with many "
             "partnerships. Any further line adds one DIFFERENT thing, in general, plain "
             "words (the kind of projects, the lab's robots), no jargon, no repeats, no "
             "topic of the debate yet, no goodbye. Each line in "
             "the robot's own voice and position, warm and lively. Then the hand-over, "
             "said by {first}: short and natural, in the spirit of: Well, let's get into "
             "it. I understand you want to talk about <the topic in a few plain words> "
             "today, so let's get to it. (No opinion in it yet.) Reply with JSON only: "
             '{{"lines": [{{"speaker": "<label>", "tone": "<how it is said>", "gesture": '
             '"<a name from MOVES, or none>", "text": "<what they say>"}}], '
             '"handover": "<the hand-over line>"}}')
    OPENING_AFTER_INTRO = ("The lab intro and the hand-over to the topic were just said "
                           "(the lines below). Now {speaker} starts the debate: no greeting, "
                           "no thanks and no word about the lab; straight into the topic "
                           "with a strong opinion from its own position.")
    intro_task: Optional["asyncio.Future"] = None
    intro_lines: list = []
    cut_entry: Optional[dict] = None    # the robot line the people just cut off
    live_prefix = ""                    # the start of a sentence, said before a pause
    resume_key: Optional[str] = None    # cut off by a noise: this robot speaks next
    live_task: Optional["asyncio.Task"] = None

    def prompt(self, opening: bool, final: bool, nudge: str,
               extra_human: Optional[tuple[str, Optional[str]]] = None,
               saw: Optional[dict] = None, speaker: Optional[dict] = None) -> tuple[str, str]:
        c = self.common()
        c["topic"] = c["topic"] or "Anything the robots find interesting; start somewhere surprising."
        system = self.SYSTEM.format(**c)
        lines = self.history(extra_human)
        user = ["Conversation so far:", "\n".join(lines) if lines else "(nothing yet)", ""]
        user.append("Time: {} of {}.".format(_fmt(self.elapsed()), _fmt(self.limit())))
        mine = [t for t in self.mine() if t["kind"] == "robot"]
        moves_ = [t["move"] for t in mine][-3:]
        if moves_:
            user.append("Recent moves: {}.".format(", ".join(moves_)))
        own: dict[str, list[str]] = {}
        for t in mine:
            if t.get("move"):
                own.setdefault(t["character"], []).append(t["move"])
        if own:
            user.append("Each character's last moves: {}. Whoever speaks next uses a "
                        "different move from their own last one.".format("; ".join(
                            "{} {}".format(c_, ", ".join(m[-2:])) for c_, m in own.items())))
        gestures = [t.get("gesture") for t in mine if t.get("gesture")][-4:]
        if gestures:
            user.append("Recent gestures (vary them): {}.".format(", ".join(gestures)))
        if self.last_robot:
            quiet = sorted(self.seats, key=lambda s: self.spoke_at.get(s["key"], 0.0))
            user.append("Last robot to speak: {}. Quietest so far: {}.".format(
                self.character_of_key(self.last_robot),
                ", ".join(s["character"] for s in quiet[:2])))
        asked = [t.get("spoken") or t["text"] for t in mine
                 if t.get("move", "").lower().startswith("people")][-4:]
        if asked:
            user.append("Already asked to the people (never again, in no form): {}".format(
                " | ".join(asked)))
        said = self.names_said()
        if said:
            user.append("Already said once, never say again: {} (talk to them without the "
                        "name).".format(", ".join(said)))
        last_robot = mine[-1] if mine else None
        if last_robot is not None and last_robot.get("cut_noise"):
            user.append("The last line was cut off by a noise and nobody spoke: that same "
                        "robot picks its point up again in other words (not word for word).")
        last_human = extra_human[0] if extra_human else None
        if last_human is None:
            last = self.mine()[-1] if self.mine() else None
            if last is not None and last["kind"] == "human":
                last_human = last["text"]
        if saw is not None:
            user.append("The attached picture is what {}'s camera sees right now; {} answers "
                        "the people from it.".format(saw["character"], saw["character"]))
        if last_human == UNCLEAR:
            user.append("The people said something nobody caught: the robot they were "
                        "closest to asks them, briefly and in character, to say it again.")
        elif last_human is not None:
            user.append("The people just spoke: answer them directly.")
            note = lab_question_note(last_human)
            if note:
                user.append(note)
        if opening and self.intro_lines:
            user.append(self.OPENING_AFTER_INTRO.format(
                speaker=self.after_intro_seat()["character"])
                        + "\nThe lab intro: " + " | ".join(
                            "{}: {}".format(ln.seat["character"], ln.text)
                            for ln in self.intro_lines))
        elif opening:
            user.append(self.OPENING
                        + (" A picture of the room from its camera is attached: it may "
                           "mention one friendly detail it sees." if saw else ""))
        elif final:
            said = list(getattr(self, "closing_said", []))
            user.append(self.CLOSING
                        + (" Already said as closing lines (do not repeat them, you may "
                           "answer them): {}".format(" | ".join(said)) if said else ""))
        elif self.elapsed() > self.limit() - 45:
            user.append("Less than a minute is left: make the strongest points now. Do not "
                        "mention the time, closing or wrapping up yet.")
        if nudge:
            user.append("Operator instruction for this line (follow it): {}".format(nudge))
        if speaker is not None:
            user.append("The next speaker is {} (already decided): write {}'s line.".format(
                speaker["character"], speaker["character"]))
        user.append("Write the next line as JSON.")
        return system, "\n".join(user)

    async def prepare(self, opening: bool = False, final: bool = False,
                      extra_human: Optional[tuple[str, Optional[str]]] = None,
                      speaker: Optional[dict] = None) -> Line:
        nudge = self.m.pending_nudge
        image, saw = None, None
        people_text, heard = extra_human if extra_human else (None, None)
        if people_text is None and self.mine():
            last = self.mine()[-1]
            if last["kind"] == "human" and last["text"] != UNCLEAR:
                people_text, heard = last["text"], last.get("heard_by")
        if people_text and wants_eyes(people_text):
            heard_seat = next((s for s in self.seats if s["name"] == heard), None)
            target = self.named_seat(people_text) or heard_seat
            target = target or (self.seats[len(self.seats) // 2] if self.seats else None)
            if target is not None:
                image = await self.s.snapshot(target["key"])
                saw = target if image else None
        # Robots with different writers: the speaker is chosen first and its
        # own writer writes the line.
        if speaker is None and self.one_writer() is None:
            speaker = (saw if saw is not None and people_text
                       else self.next_speaker(people_text, heard))
        system, user = self.prompt(opening, final, nudge, extra_human, saw, speaker)
        t = time.monotonic()
        model = self.writer_of(speaker) if speaker is not None else self.one_writer() or ""
        out = await self.ask(system, user, image, model=model)
        if not _clean(out.get("text", "")):
            raise ServiceError("the director wrote an empty line")
        problems = ([] if opening or final or saw is not None
                    else self.problems_of(out, speaker))
        if problems:
            log.info("line written again (%s): %s", "; ".join(problems), out.get("text"))
            try:
                again = await self.ask(system, user + "\n\nA first try was: {}\nIt is not good: "
                                       "{}. Write the line again as JSON.".format(
                                           json.dumps(out.get("text"), ensure_ascii=False),
                                           "; ".join(problems)), image, model=model)
                if _clean(again.get("text", "")):
                    out = again
            except ServiceError as exc:
                log.info("second try failed (%s): the first one is said", exc)
        if saw is not None and people_text:
            out["speaker"] = saw["character"]
        line = self.make_line(out, final=final, nudge=nudge, t=t, people_text=people_text,
                              speaker=speaker)
        line.saw = saw["name"] if saw else ""
        return line

    def problems_of(self, out: dict, speaker: Optional[dict]) -> list[str]:
        char = speaker["character"] if speaker is not None else str(out.get("speaker") or "")
        said = [t for t in self.mine() if not (t["kind"] == "robot" and t.get("unspoken"))]
        last = said[-1] if said else None
        prev = (last.get("spoken") or last["text"]) if last and last["kind"] == "robot" else ""
        own = [t.get("spoken") or t["text"] for t in said
               if t["kind"] == "robot" and t.get("character") == char and t.get("move") != "intro"]
        return line_problems(_clean(out.get("text", "")), prev, own,
                             self.settings.get("topic") or "")

    def asks_people(self, line: Line) -> bool:
        if line.move.lower().startswith("people"):
            return True
        text = line.text.strip()
        if not text.endswith("?"):
            return False
        last = re.split(r"(?<=[.!?])\s+", text)[-1].lower()
        return any(w in last for w in PEOPLE_WORDS)

    async def wait(self, task: Optional["asyncio.Future"] = None,
                   seconds: Optional[float] = None) -> str:
        end = None if seconds is None else time.monotonic() + seconds
        while True:
            if self.closing:
                return "done"
            if self.ears.capturing:
                return "people"
            if task is not None and task.done():
                return "done"
            if end is not None and time.monotonic() >= end:
                return "done"
            await asyncio.sleep(0.03)

    def opener(self) -> "asyncio.Future":
        if not self.wants_intro():
            return asyncio.create_task(self.prepare(opening=True))
        self.intro_task = asyncio.ensure_future(self.make_intro())
        return asyncio.create_task(self.open_after_intro())

    def wants_intro(self) -> bool:
        return (self.mode == "group" and bool(self.seats)
                and bool(self.settings.get("lab_intro", True)))

    async def make_intro(self) -> list:
        """One writer call for the whole intro, voiced at once (Get ready
        makes it ahead with the opener)."""
        system = self.SYSTEM.format(**self.common())
        user = self.INTRO.format(n=len(self.seats),
                                 order=", ".join(s["character"] for s in self.seats),
                                 first=self.seats[0]["character"])
        out = await self.ask(system, user, model=self.one_writer() or self.writer_of(self.seats[0]))
        said = [o for o in (out.get("lines") or []) if isinstance(o, dict)]
        lines = []
        for seat, o in zip(self.seats, said):
            if _clean(o.get("text", "")):
                o = {**o, "move": "intro", "reactions": {}}
                lines.append(self.make_line(o, speaker=seat))
        if not lines:
            raise ServiceError("the writer wrote no lab intro")
        handover = _clean(str(out.get("handover") or ""))
        if not handover:
            topic = re.split(r"[:?]", self.settings.get("topic") or "")[0].strip()
            handover = ("Well, let's get into it. I understand you want to talk about {} "
                        "today, so let's get to it.".format(topic) if topic else
                        "Well, let's get into it.")
        lines.append(self.make_line({"text": handover, "move": "intro", "reactions": {},
                                     "gesture": "inquiring1", "tone": "upbeat, inviting"},
                                    speaker=self.seats[0]))
        self.intro_lines = lines
        return lines

    def after_intro_seat(self) -> dict:
        """Who starts the debate after the hand-over: the second robot."""
        return self.seats[1] if len(self.seats) > 1 else self.seats[0]

    async def open_after_intro(self) -> Line:
        try:
            await self.intro_task
        except Exception as exc:  # noqa: BLE001
            log.info("lab intro failed (%s): plain opener", exc)
            return await self.prepare(opening=True)
        return await self.prepare(opening=True, speaker=self.after_intro_seat())

    async def say_intro(self) -> None:
        """Every robot its lab line, one after the other (nobody cuts in)."""
        task, self.intro_task = self.intro_task, None
        try:
            lines = await task
        except Exception as exc:  # noqa: BLE001
            self.note("the lab intro failed: {}".format(exc))
            return
        self.note("lab intro: every robot says a line about the lab")
        for line in lines:
            if self.closing or line.seat["key"] not in self.s.links:
                continue
            entry = self.turn(kind="robot", who=line.seat["name"],
                              character=line.seat["character"], text=line.text,
                              move="intro", gesture=line.gesture, tone=line.tone)
            self.last_robot = line.seat["key"]
            self.spoke_at[line.seat["key"]] = time.monotonic()
            self.ears.reset_capture()
            await self.speak(line, entry, cut_by_people=False)
            await asyncio.sleep(0.3)
        self.ears.reset_capture()

    async def close_round(self) -> None:
        """Every robot says its closing line, one after the other, starting
        with whoever did not speak last; the next one is written while the
        one before talks. Nobody is cut off and the people are not answered."""
        self.closing = True
        self.m.publish_state()
        self.note("closing: every robot says its last word")
        last = self.last_robot
        order = [s for s in self.seats if s["key"] != last] + \
                [s for s in self.seats if s["key"] == last]
        nxt: Optional["asyncio.Future"] = None
        self.closing_said: list[str] = []
        for i, seat in enumerate(order):
            try:
                line = await (nxt or self.prepare(final=True, speaker=seat))
            except Exception as exc:  # noqa: BLE001
                self.note("{}'s closing line failed: {}".format(seat["character"], exc))
                nxt = None
                continue
            nxt = None
            entry = self.turn(kind="robot", who=line.seat["name"],
                              character=line.seat["character"], text=line.text,
                              move="wrap", gesture=line.gesture, tone=line.tone,
                              closing=True)
            self.last_robot = line.seat["key"]
            self.closing_said.append(line.text)
            if i + 1 < len(order):
                nxt = asyncio.ensure_future(self.prepare(final=True, speaker=order[i + 1]))
            self.ears.reset_capture()
            await self.speak(line, entry, cut_by_people=False)
            await asyncio.sleep(0.3)
        self.discard(nxt)
        self.note("the conversation is over")

    async def run(self) -> None:
        ears = self.ears
        ears.reset_capture()
        pending: Optional[asyncio.Future] = self.premade or self.opener()
        if self.intro_task is not None:
            await self.say_intro()
        try:
            while True:
                if self.s.drop_dead_links() and len(self.seats) < 1:
                    raise RuntimeError("no robot is left at the table")
                if ears.capturing:
                    spoke, answer = await self.people()
                    cut, self.cut_entry = self.cut_entry, None
                    if spoke:
                        self.discard(pending)
                        pending = (self.ready(answer) if answer is not None else
                                   asyncio.create_task(self.prepare()))
                    elif cut is not None:
                        # Only a noise cut it off: that robot picks its point up again
                        # (2026-10-25: left to the writer, the OTHER robot made the
                        # cut robot's point).
                        cut["cut_noise"] = True
                        self.resume_key = next((s["key"] for s in self.seats
                                                if s["name"] == cut.get("who")), None)
                        self.note("{} was cut off by a noise; it goes on".format(cut["who"]))
                    continue
                if self.closing or self.time_up():
                    self.discard(pending)
                    pending = None
                    await self.close_round()
                    return
                if pending is None:
                    resume = self.seat_of_key(self.resume_key)
                    self.resume_key = None
                    pending = asyncio.create_task(self.prepare(speaker=resume))
                if not pending.done():
                    self.status("thinking")
                    if await self.wait(task=pending) == "people":
                        continue
                try:
                    line = pending.result()
                    self.failures = 0
                except Exception as exc:  # noqa: BLE001
                    self.failures += 1
                    self.note("the director failed: {}".format(exc))
                    if self.failures >= 3:
                        raise RuntimeError("the director failed three times in a row") from exc
                    pending = None
                    await asyncio.sleep(1.0)
                    continue

                entry = self.turn(kind="robot", who=line.seat["name"],
                                  character=line.seat["character"], text=line.text,
                                  move=line.move, gesture=line.gesture, tone=line.tone,
                                  saw=line.saw or None)
                self.last_robot = line.seat["key"]
                self.last_line = line
                self.spoke_at[line.seat["key"]] = time.monotonic()
                if line.nudge and self.m.pending_nudge == line.nudge:
                    self.m.pending_nudge = ""
                pending = asyncio.create_task(self.prepare())
                barge = BARGE_DB.get(self.settings.get("barge_in"), 10.0)
                ears.barge_db = barge
                finished = await self.speak(line, entry, cut_by_people=barge is not None)
                if not finished:
                    # The next line was written for the whole line: write it again.
                    self.discard(pending)
                    pending = None
                    self.cut_entry = entry
                    continue                    # the people have the floor
                if self.closing or self.time_up():
                    continue                    # the closing round, at the top

                await asyncio.sleep(ECHO_TAIL_S)
                self.status("listening")
                gap = float(self.settings.get("listen_gap_s") or 0.6)
                if self.asks_people(line):
                    gap = max(gap, PEOPLE_GAP_S)
                if await self.wait(seconds=gap) == "done" and ears.stirring():
                    await self.wait(seconds=STIR_HOLD_S)
        finally:
            self.discard(pending)

    async def people(self) -> tuple[bool, Optional[Line]]:
        """The people hold the floor until they stop. Returns (did anyone
        really speak, the robot's answer already written with its voice on the
        way, or None to let prepare() write it)."""
        try:
            return await self.hear_people()
        finally:
            self.discard(self.live_task)
            self.live_task = None
            self.m.live_people("")

    async def live_words(self, pcm: bytes) -> None:
        """The page's live line (Tomer, 2026-10-25: see what the person says,
        typed out as they speak): everything they have said so far, again."""
        try:
            text, _lang = await self.services.transcribe(pcm, language=self.fixed_language())
        except Exception as exc:  # noqa: BLE001
            log.debug("live words failed: %s", exc)
            return
        text = strip_echo(text, self.robot_lines_recent())
        if self.ears.capturing and not self.junk(text, True):
            self.m.live_people("{} {}".format(self.live_prefix, text).strip())

    async def hear_people(self, prefix: str = "") -> tuple[bool, Optional[Line]]:
        """`prefix`: what the person said before a pause; this capture is the
        rest of the same sentence."""
        ears = self.ears
        self.live_prefix = prefix
        self.status("human")
        await self.s.look(None)
        early: Optional[asyncio.Task] = None
        early_end = 0.0
        live_at = time.monotonic()
        while not ears.finished():
            if (self.live_task is None or self.live_task.done()) \
                    and time.monotonic() - live_at >= LIVE_STT_EVERY_S:
                pcm, _key, so_far, _end = ears.take(keep=True)
                if so_far >= 0.6:
                    live_at = time.monotonic()
                    self.live_task = asyncio.create_task(self.live_words(pcm))
            quiet = ears.silence()
            if early is None and quiet >= EARLY_STT_S:
                pcm, key, spoken, early_end = ears.take(keep=True)
                if spoken >= MIN_PEOPLE_S:
                    early = asyncio.create_task(self.respond(pcm, key, prefix))
            elif early is not None and quiet < EARLY_STT_S:
                self.discard(early)
                early = None
            await asyncio.sleep(0.03)
        pcm, key, spoken, ended = ears.take()
        if spoken < MIN_PEOPLE_S:
            log.info("too short for the people: %.2f s of voice", spoken)
            self.discard(early)
            return False, None
        self.status("thinking", detail="answering the room")
        if early is not None and early_end == ended:
            task = early
        else:
            self.discard(early)
            task = asyncio.create_task(self.respond(pcm, key, prefix))
        try:
            text, answer = await asyncio.wait_for(asyncio.shield(task), HEAR_TIMEOUT_S)
        except asyncio.CancelledError:
            self.discard(task)
            raise
        except Exception as exc:  # noqa: BLE001
            self.discard(task)
            self.note("could not understand the room ({}); asking them to repeat".format(
                type(exc).__name__))
            self.silence_since = ended
            self.turn(kind="human", who="people", character="People", text=UNCLEAR)
            return True, None
        robot_asked = self.last_line is not None and self.asks_people(self.last_line)
        if self.junk(text, robot_asked):
            if answer is not None and answer.tts is not None:
                answer.tts.cancel()
            if robot_asked and text.strip() and spoken >= ASK_AGAIN_S and not prefix:
                # Someone answered the question, but only a stray word came
                # through: ask them again rather than build on it.
                log.info("unclear answer: %r (%.1f s); asking again", text, spoken)
                self.silence_since = ended
                self.turn(kind="human", who="people", character="People", text=UNCLEAR)
                return True, None
            log.info("ignored as noise: %r (%.1f s)", text, spoken)
            return False, None
        if not prefix and unfinished(text):
            # "When I think..." and a pause: wait for the rest before answering.
            self.status("human", detail="waiting for the rest")
            until = time.monotonic() + HOLD_UNFINISHED_S
            while time.monotonic() < until and not ears.capturing:
                await asyncio.sleep(0.03)
            if ears.capturing:
                log.info("unfinished: %r; the person goes on", text)
                self.discard(task)
                more = await self.hear_people(prefix=text)
                if more[0]:
                    return more
                answer = None           # the rest was a noise: answer what was said
        if len(_words(text)) >= 3 and self.settings.get("language", "auto") == "auto":
            self.lang = "he" if _hebrew(text) else "en"
        self.silence_since = ended
        heard = next((s["name"] for s in self.seats if s["key"] == key), None)
        self.turn(kind="human", who="people", character="People", text=text, heard_by=heard)
        return True, answer

    async def respond(self, pcm: bytes, key: Optional[str],
                      prefix: str = "") -> tuple[str, Optional[Line]]:
        """Transcribe, then (if it is real speech) write the answer and start
        its voice: all of it while the people may still go on talking.
        `prefix`: the start of the sentence, said before a pause."""
        text, _lang = await self.services.transcribe(pcm, language=self.fixed_language())
        text = strip_echo(text, self.robot_lines_recent())
        if prefix:
            text = "{} {}".format(prefix, text).strip()
        robot_asked = self.last_line is not None and self.asks_people(self.last_line)
        if self.junk(text, robot_asked):
            return text, None
        heard = next((s["name"] for s in self.seats if s["key"] == key), None)
        try:
            line = await self.prepare(extra_human=(text, heard))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("early answer failed (%s); prepare() writes it", exc)
            return text, None
        return text, line


# ================================================================= free
class FreeTalk(GroupTalk):
    """Mode 3: Group talk with no topic and no sides, a creative free chat
    that follows the room (Tomer, 2026-10-25). Everything else (hearing,
    cutting in, +1, the goodbye round) is Group talk's."""

    mode = "free"
    SYSTEM = SYSTEM_FREE
    OPENING = ("Open the conversation: one robot greets the people warmly in a few words "
               "and starts something fun and surprising to chat about, or asks them "
               "something playful.")
    CLOSING = ("The conversation is ending now. Write the closing line of the speaker "
               "below: one warm or funny last word on what you just chatted about, then a "
               "short goodbye to the people.")

    def cast(self) -> str:
        return "\n".join("- {} - {} - {}".format(
            s["character"], s["name"], FREE_PERSONAS[i % len(FREE_PERSONAS)])
            for i, s in enumerate(self.seats))


# ============================================================ interrupt
class InterruptTalk(Conversation):
    """Mode 2: a person talks; the robots cut in, more or less often."""

    mode = "interrupt"

    def __init__(self, manager: "GroupManager", session: Session) -> None:
        super().__init__(manager, session)
        self.partial: list[str] = []          # this person turn, piece by piece
        self.openers: list[str] = []          # first words of recent interruptions
        self.stands: dict[str, str] = {}      # character -> stance on the person's claim
        self.current: Optional[tuple] = None  # (line, entry) of the robot speaking now
        self.stt_busy = False
        self.turn_over = False
        self.speaking: Optional[asyncio.Task] = None
        self.interrupters: list[str] = []

    def seat_level(self, seat: dict) -> int:
        """How pushy this robot is, 0 (never cuts in) to 5 (every time)."""
        try:
            return max(0, min(5, int(seat.get("interrupt_level",
                                              self.settings.get("interrupt_level", 3)))))
        except (TypeError, ValueError):
            return 3

    def level(self) -> int:
        """The pushiest robot's level: the table is as rowdy as that."""
        return max((self.seat_level(s) for s in self.seats), default=0)

    def levels_sig(self) -> tuple:
        return tuple(self.seat_level(s) for s in self.seats)

    def pushy(self, exclude: Optional[str] = None, at_least: int = 1) -> list[dict]:
        return [s for s in self.seats if self.seat_level(s) >= at_least and s["key"] != exclude]

    def interrupter(self) -> Optional[dict]:
        """Who cuts in next: a robot that interrupts at all, the pushier the
        likelier (weight = how often its level cuts in), not the last one."""
        last = self.interrupters[-1] if self.interrupters else None
        cands = [s for s in self.pushy() if s["character"] != last] or self.pushy()
        if not cands:
            return None
        weights = [1.0 / INTERRUPT_AFTER_S[self.seat_level(s)] for s in cands]
        return random.choices(cands, weights=weights)[0]

    def system(self, speaker: Optional[dict] = None) -> str:
        c = self.common()
        c["topic"] = c["topic"] or "Whatever the person wants to argue about."
        c["style"] = STYLE[self.seat_level(speaker) if speaker is not None else self.level()]
        return SYSTEM_INTERRUPT.format(**c)

    def user_msg(self, task: str, person_now: str = "") -> str:
        lines = self.history(limit=30)
        user = ["Conversation so far:", "\n".join(lines) if lines else "(nothing yet)", ""]
        if person_now and task.startswith("The person finished"):
            user += ["What the person just said (their turn is over):", person_now, ""]
        elif person_now:
            user += ["The person is talking RIGHT NOW. What they have said so far in this "
                     "turn (live, may end mid-sentence):", person_now, ""]
        if self.interrupters:
            user.append("Recent interrupters (pick someone else): {}.".format(
                ", ".join(self.interrupters[-3:])))
        user.append("Each robot's stand on what the person is saying: {}.".format("; ".join(
            "{} {}".format(s["character"], STAND_WORDS.get(self.stand_of(s["character"]),
                                                         "has its own view"))
            for s in self.seats)))
        if len(set(self.levels_sig())) > 1:
            user.append("How pushy each robot is (0 never cuts in, 5 every time): {}.".format(
                ", ".join("{} {}".format(s["character"], self.seat_level(s)) for s in self.seats)))
        said = self.names_said()
        if said:
            user.append("Already said once, never say again: {} (talk to them without the "
                        "name).".format(", ".join(said)))
        if self.m.pending_nudge:
            user.append("Operator instruction (follow it): {}".format(self.m.pending_nudge))
        user.append(task)
        return "\n".join(user)

    def opener(self) -> "asyncio.Future":
        topic = self.settings.get("topic") or ""
        return asyncio.create_task(self.line_for(
            "Open: one robot turns to the person and dares them to say what they think "
            "about the topic{} (one or two short sentences, cheeky). The others will "
            "interrupt them, so make it a dare.".format(
                " (" + topic + ")" if topic else ", or anything they feel strongly about")))

    async def line_for(self, task: str, person_now: str = "", interrupting: bool = False,
                       allow_repeat: bool = False, image: Optional[bytes] = None,
                       saw: Optional[dict] = None, speaker: Optional[dict] = None) -> Line:
        if saw is not None:
            speaker = saw
        elif speaker is None and self.one_writer() is None:
            # Robots with different writers: choose the speaker first, so its
            # own writer writes the line (a robot the person named answers).
            speaker = self.next_speaker(person_now or None)
        system = self.system(speaker)
        jab_level = self.seat_level(speaker) if speaker is not None else self.level()
        # The writer picks the opener itself, from the bank, to fit what the
        # robot is about to say (Tomer, 2026-10-21: the interjection must match
        # the line, never random). Cached ones play at once.
        if interrupting:
            words = {1: 14, 2: 14, 3: 12, 4: 10, 5: 8}.get(jab_level, 12)
            recent = ", ".join('"{}"'.format(o) for o in self.openers[-8:]) or "none yet"
            system += ("\n\nOPENERS (start with one of these, exactly, when it fits the line, "
                       "about half the time; otherwise leave \"opener\" empty and open in the "
                       "character's own words - a question, a flat no, a laugh, straight to the "
                       "point):\n{}\nNever an opener used recently ({}), never one that does not "
                       "match the stance. \"text\" continues right after the opener (do not "
                       "repeat it, no names). It is a jab, not a speech: at most {} words."
                       .format(self.opener_menu(), recent, words))
        system += "\n\n" + (INTERRUPT_JSON if interrupting else INTERRUPT_JSON.replace(
            ', "pile_on": {{"speaker": "<another character>", "stance": "<oppose|approve|mock>"}}'
            ' or null', "").replace(
            ' "opener": "<one opener from the list, exactly, or empty>",', "").replace(
            "<what they say after the opener>", "<what they say>"))
        system = system.replace("{{", "{").replace("}}", "}")
        user = self.user_msg(task, person_now)
        if saw is not None:
            user += ("\nThe attached picture is what {}'s camera sees right now; {} answers "
                     "from it.".format(saw["character"], saw["character"]))
        elif speaker is not None:
            user += "\nThe speaker is {} (already decided): write {}'s line.".format(
                speaker["character"], speaker["character"])
        t = time.monotonic()
        nudge = self.m.pending_nudge
        out = await self.ask(system, user, image, model=self.writer_of(speaker)
                             if speaker is not None else self.one_writer() or "")
        if not _clean(out.get("text", "")):
            raise ServiceError("the director wrote an empty line")
        if nudge and self.m.pending_nudge == nudge:
            self.m.pending_nudge = ""           # an operator steer is for one line
        if saw is not None:
            out["speaker"] = saw["character"]
        line = self.make_line(out, t=t, allow_repeat=allow_repeat,
                              people_text=None, voice=False, speaker=speaker)
        if interrupting:
            opener = self.known_opener(str(out.get("opener") or ""), line.seat["character"])
            if opener:
                line.text = strip_interjection(line.text)
                line.use_pre = True
                line.pre_text = opener
            # The writer often runs past the jab length; a jab is its first sentence.
            limit = {1: 14, 2: 14, 3: 12, 4: 10, 5: 8}.get(self.seat_level(line.seat), 12)
            if len(line.text.split()) > limit:
                first_sentence = re.split(r"(?<=[.!?])\s+", line.text)[0]
                if 3 <= len(first_sentence.split()) < len(line.text.split()):
                    line.text = first_sentence
        line.saw = saw["name"] if saw else ""
        if line.stance not in moves.STANCE_REACTIONS or line.stance == "defend":
            line.stance = self.stand_of(line.seat["character"])
        if interrupting:
            self.stands[line.seat["character"]] = line.stance
        if line.use_pre and line.pre_text and not self.s.phrases.audio(
                self.s.voice_key(line.seat), line.pre_text):
            # No recording of that opener yet: it is spoken with the line.
            line.text = (line.pre_text + " " + line.text).strip()
            line.pre_text, line.use_pre = "", False
        if line.pre_text:
            self.s.phrases.used(line.pre_text)
        line.tts = asyncio.create_task(self.s.voice(line))
        return line

    # -------------------------------------------------------------- loop
    async def run(self) -> None:
        ears = self.ears
        ears.reset_capture()
        ears.barge_db = BARGE_DB.get(self.settings.get("barge_in"), 10.0) or 12.0
        try:
            opener = await (self.premade or self.opener())
            await self.say(opener, wait=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.note("the opener failed: {}".format(exc))
        prods = 0
        idle_since = time.monotonic()
        while True:
            self.s.drop_dead_links()
            if self.closing or (self.time_up() and not ears.capturing):
                if self.speaking is not None:
                    await self.speaking
                await self.say(await self.line_for(
                    "Time is up. One robot wraps up in one cheeky sentence and thanks the "
                    "person for putting up with them."), wait=True)
                self.note("time is up; the conversation is over")
                return
            if ears.capturing:
                prods = 0
                await self.person_turn()
                idle_since = time.monotonic()
                continue
            if self.speaking is not None and not self.speaking.done():
                await asyncio.sleep(0.03)
                idle_since = time.monotonic()
                continue
            self.status("listening", detail="waiting for the person")
            if time.monotonic() - idle_since > PROD_AFTER_S * (1 + prods):
                prods += 1
                try:
                    line = await self.line_for(
                        "The person has gone quiet. One robot pokes them to talk (short, "
                        "cheeky, a direct question about the topic).")
                    if not ears.capturing:
                        await self.say(line, wait=False)
                    else:
                        self.discard(self.ready(line))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.note("the director failed: {}".format(exc))
                idle_since = time.monotonic()
            await asyncio.sleep(0.03)

    async def say(self, line: Line, wait: bool) -> None:
        """A robot line in this mode: robots do not stop for the person."""
        if self.speaking is not None and not self.speaking.done():
            await self.speaking
        entry = self.turn(kind="robot", who=line.seat["name"], character=line.seat["character"],
                          text=(line.pre_text + " " + line.text).strip(),
                          move=line.stance or line.move, gesture=line.gesture, tone=line.tone,
                          saw=line.saw or None, interrupting=bool(line.pre_text))
        self.last_robot = line.seat["key"]
        self.last_line = line
        self.spoke_at[line.seat["key"]] = time.monotonic()
        self.current = (line, entry)
        self.speaking = asyncio.create_task(self.speak(line, entry, cut_by_people=False))
        if wait:
            await self.speaking

    async def stream_stt(self) -> None:
        """Transcribe the person's turn in pieces while they talk, each piece
        from the mic that hears them best right now (over a talking robot the
        nearest mic to the person carries the least robot). The mics append
        in step, so one block count serves them all, give or take a block."""
        ears = self.ears
        sent = 0
        prompt = ""
        lang = self.settings.get("language") if self.settings.get("language") in ("he", "en") else ""
        while True:
            key = ears.best_key()
            blocks = ears.blocks_of(key) if key else []
            new_s = (len(blocks) - sent) * 0.032
            done = self.turn_over or not ears.capturing
            quiet = ears.silence()
            if done:
                # The rest, once, without the closing silence.
                tail = int(max(0.0, quiet - 0.2) / 0.032)
                piece = blocks[sent:len(blocks) - tail] if tail else blocks[sent:]
                if len(piece) * 0.032 >= 0.3:
                    await self._piece(piece, prompt, lang)
                return
            if new_s >= SEG_MAX_S or (new_s >= SEG_MIN_S and quiet >= 0.15):
                piece = blocks[sent:]
                sent = len(blocks)
                await self._piece(piece, prompt, lang)
                prompt = " ".join(self.partial)
            await asyncio.sleep(0.05)

    async def _piece(self, piece: list, prompt: str, lang: str) -> None:
        pcm = b"".join(b.tobytes() for b in piece)
        self.stt_busy = True
        try:
            text, _ = await self.services.transcribe(pcm, prompt=prompt, language=lang)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("piece transcription failed: %s", exc)
            text = ""
        finally:
            self.stt_busy = False
        text = strip_echo(text, self.robot_lines_recent())
        # A transcriber that repeats what came before: keep only what is new.
        before = " ".join(self.partial)
        if before and text.startswith(before):
            text = text[len(before):].strip()
        if text and not self.junk(text, True):
            self.partial.append(text)
            self.m.live_people(" ".join(self.partial))

    def stand_of(self, character: str) -> str:
        return self.stands.get(character) or DEFAULT_STANDS.get(character, "oppose")

    def opener_menu(self) -> str:
        from .phrases import CHARACTER, PHRASES
        lang = self.lang if self.lang in PHRASES else "en"
        recent = set(self.s.phrases.recent())
        rows = ["{}: {}".format(st, " | ".join(t for t in ts if t not in recent))
                for st, ts in PHRASES[lang].items() if st != "defend"]
        for s in self.seats:
            own = [t for st, t in CHARACTER.get(lang, {}).get(s["character"], [])
                   if st != "defend" and t not in recent]
            if own:
                rows.append("{} only: {}".format(s["character"], " | ".join(own)))
        return "\n".join(rows)

    def known_opener(self, text: str, character: str) -> str:
        """The writer's opener if it is really one of the bank's."""
        from .phrases import CHARACTER, PHRASES
        want = text.strip()
        if not want:
            return ""
        for lang in (self.lang, "he", "en"):
            bank = [t for ts in PHRASES.get(lang, {}).values() for t in ts]
            bank += [t for _st, t in CHARACTER.get(lang, {}).get(character, [])]
            for t in bank:
                if t.strip(" .!?…") == want.strip(" .!?…"):
                    return t
        return ""

    @staticmethod
    def line_seconds(line: Line) -> float:
        """Rough speaking time: ~2.6 words a second, with its interjection."""
        return len((line.pre_text + " " + line.text).split()) / 2.6

    def next_due(self) -> float:
        """When the next robot cuts in: around the levels' base, but people
        are not metronomes (2026-10-21: "not after 2 seconds each time") -
        log-normal, from 0.4x to 2.6x the base. Each robot has its own level
        (page, per robot): the base is the average pace of the robots that cut
        in at all, so all at 3 is the same as the old table-wide 3, and the
        pushier robot then gets more of the interruptions (interrupter())."""
        pushy = self.pushy()
        if not pushy:
            return float("inf")
        rate = sum(1.0 / INTERRUPT_AFTER_S[self.seat_level(s)] for s in pushy) / len(pushy)
        factor = min(2.6, max(0.4, random.lognormvariate(0.0, 0.5)))
        return time.monotonic() + factor / rate

    def answer_task(self, text: str, key: Optional[str]) -> str:
        if self.level() == 0:
            return ("The person finished. One robot responds to what they said, in "
                    "character, with a strong opinion (one or two sentences, at most 25 "
                    "words), and ends by challenging them with a question.")
        return ("The person finished. One robot jumps on what they said, in character "
                "(one or two punchy sentences, at most 25 words): agree loudly, "
                "disagree hard, or mock it, and throw it back at them with a question.")

    async def answer(self, text: str, key: Optional[str]) -> Line:
        """The reply to a finished turn (with a camera picture if they asked
        what a robot sees)."""
        image, saw = None, None
        if wants_eyes(text):
            target = self.named_seat(text) or self.seat_of_key(key) or self.seats[0]
            image = await self.s.snapshot(target["key"])
            saw = target if image else None
        if saw is not None:
            task = ("The person finished and asked about what a robot sees: {} answers "
                    "from the picture (one or two sentences), then one cheeky question "
                    "back.".format(saw["character"]))
        else:
            task = self.answer_task(text, key)
        return await self.line_for(task, person_now=text, image=image, saw=saw)

    async def person_turn(self) -> None:
        ears = self.ears
        self.status("human", detail="the robots are listening")
        await self.s.look(None)
        self.partial = []
        self.turn_over = False
        self.stands = {}                      # every new turn starts from temperament
        first_key = ears.best_key()
        stt = asyncio.create_task(self.stream_stt())
        levels = self.levels_sig()
        level = self.level()
        due = self.next_due()
        prepared: Optional[asyncio.Task] = None
        early: Optional[asyncio.Task] = None
        early_text = ""
        react_at = time.monotonic() + random.uniform(*REACT_EVERY_S)
        reacted_last = ""
        robot_stopped = 0.0
        was_talking = False
        blurted = random.random() > 0.45      # a lone first blurt, sometimes
        wait_breath = random.random() < 0.35
        try:
            while True:
                now = time.monotonic()
                robot_talking = self.speaking is not None and not self.speaking.done()
                if was_talking and not robot_talking:
                    robot_stopped = now
                    self.s.spawn(self.s.look(None))     # back to the person
                was_talking = robot_talking
                # A robot just stopped: give the person a moment to be heard
                # over a quiet room before calling their turn over.
                settled = now - robot_stopped >= MODE2_END_S
                if not robot_talking and settled and (
                        ears.finished(MODE2_END_S) or not ears.capturing):
                    break
                if robot_talking:
                    self.status("speaking", speaker=self.last_line.seat if self.last_line else None,
                                detail="interrupting")
                else:
                    self.status("human", detail="the robots are listening")
                if self.levels_sig() != levels:
                    levels, level = self.levels_sig(), self.level()
                    due = self.next_due()
                said = " ".join(self.partial)
                # Quiet body language while the person talks.
                if now >= react_at:
                    react_at = now + random.uniform(*REACT_EVERY_S)
                    busy = self.last_robot if robot_talking else None
                    cands = [s for s in self.seats if s["key"] != busy
                             and self.s.busy_until.get(s["key"], 0) < now]
                    cands = [s for s in cands if not (self.calm(s) and random.random() < 0.5)]
                    if cands:
                        seat = random.choice(cands)
                        # The face fits the stand: Dor shakes his head, Noa nods.
                        name = moves.reaction_for(seat["character"],
                                                  self.stand_of(seat["character"]),
                                                  avoid=reacted_last)
                        if name:
                            reacted_last = name
                            self.s.spawn(self.s.gesture(seat["key"], name))
                # Levels 4-5 do not wait for words: the first one is only a
                # blurt ("Wait, wait, wait!"), the written line follows.
                if (level >= 4 and not blurted and prepared is None and not robot_talking
                        and now >= due and ears.capturing and ears.silence() < 0.6
                        and len(_words(said)) < 3):
                    blurted = True
                    await self.blurt()
                    due = now + 1.5
                # Write the next interruption a little before it is due.
                if (level and prepared is None
                        and now >= due - PREP_LEAD_S and len(_words(said)) >= 3):
                    who = self.interrupter()
                    prepared = asyncio.create_task(self.line_for(
                        "Write ONE interruption now: {} cuts the person off.".format(
                            who["character"] if who else "a robot"),
                        person_now=said, interrupting=True, speaker=who))
                ready_line = None
                if prepared is not None and prepared.done():
                    if prepared.cancelled() or prepared.exception() is not None:
                        ready_line = None
                    else:
                        ready_line = prepared.result()
                # Some robots wait for the person to take a breath, most just
                # barge in mid-word; a line in its own words waits for its voice.
                breath_ok = wait_breath is False or ears.silence() >= 0.15 or now >= due + 1.5
                voice_ok = (ready_line is None or ready_line.use_pre or ready_line.audio.chunks
                            or ready_line.audio.done or now >= due + 2.0)
                if (prepared is not None and prepared.done() and now >= due and breath_ok
                        and voice_ok and not robot_talking and now - robot_stopped >= 0.4
                        and ears.capturing and ears.silence() < 0.6):
                    try:
                        line = prepared.result()
                    except Exception as exc:  # noqa: BLE001
                        self.note("the director failed: {}".format(exc))
                        line = None
                    prepared = None
                    if line is not None:
                        self.discard(early)
                        early, early_text = None, ""
                        await self.interrupt(line)
                        # Counted from when this one ends: the person gets a
                        # few words in before the next robot jumps.
                        due = self.next_due() + self.line_seconds(line)
                    else:
                        due = self.next_due()
                    wait_breath = random.random() < 0.35
                # They paused: write the answer now, in case it is the end.
                quiet = ears.silence()
                if (early is None and not robot_talking and quiet >= 0.45 and not self.stt_busy
                        and said and said != early_text):
                    early_text = said
                    early = asyncio.create_task(self.answer(said, first_key))
                elif early is not None and quiet < 0.2 and not robot_talking:
                    self.discard(early)       # they went on talking
                    early, early_text = None, ""
                await asyncio.sleep(0.03)
            # The person is done: the rest of their words, then the answer.
            self.status("thinking", detail="answering the person")
            self.discard(prepared)
            prepared = None
            self.turn_over = True
            try:
                await asyncio.wait_for(asyncio.shield(stt), 6.0)
            except Exception:  # noqa: BLE001
                stt.cancel()
            pcm, key2, spoken, ended = ears.take()
            text = " ".join(self.partial).strip()
            self.m.live_people("")
            if not text:
                self.discard(early)
                if spoken >= 1.0:
                    self.turn(kind="human", who="people", character="People", text=UNCLEAR)
                return
            if len(_words(text)) >= 3 and self.settings.get("language", "auto") == "auto":
                self.lang = "he" if _hebrew(text) else "en"
            heard = next((s["name"] for s in self.seats if s["key"] == first_key), None)
            self.turn(kind="human", who="people", character="People", text=text, heard_by=heard)
            self.silence_since = ended
            extra = text[len(early_text):] if early_text and text.startswith(early_text) else None
            if early is not None and extra is not None and len(_words(extra)) <= 4:
                line = await early
            else:
                self.discard(early)
                line = await self.answer(text, first_key)
            early = None
            follow: Optional[asyncio.Task] = None
            # A second robot jumps in after the answer: one of the others that
            # is pushy enough, more often the pushier it is.
            backers = self.pushy(exclude=line.seat["key"], at_least=2)
            if backers:
                second_seat = random.choices(backers, weights=[self.seat_level(b)
                                                               for b in backers])[0]
                lvl = self.seat_level(second_seat)
                if random.random() < 0.3 + 0.1 * lvl:
                    follow = asyncio.create_task(self.follow_up(line, second_seat))
            await self.say(line, wait=False)
            if follow is not None:
                try:
                    second = await follow
                except Exception:  # noqa: BLE001
                    second = None
                # Only if the person has not taken the floor back meanwhile.
                if second is not None:
                    await self.speaking
                    if not ears.capturing:
                        await self.say(second, wait=False)
                    else:
                        self.discard(self.ready(second))
        finally:
            stt.cancel()
            self.discard(prepared)
            self.discard(early)
            self.m.live_people("")

    async def follow_up(self, first: Line, seat: Optional[dict] = None) -> Line:
        return await self.line_for(
            "{} is about to say: \"{}\". Write the NEXT line: another robot reacts to {} "
            "(backs it up, or contradicts it) and hands it straight back to the person. "
            "One short sentence.".format(first.seat["character"], first.text,
                                         first.seat["character"]), speaker=seat)

    async def blurt(self) -> None:
        """An interjection alone, from a robot that has not spoken lately."""
        # A robot against the claim (or a mocker) blurts; its stand says how.
        # Only the robots at levels 4-5 blurt.
        others = self.pushy(exclude=self.last_robot, at_least=4) or self.pushy(at_least=4)
        if not others:
            return
        hostile = [s for s in others
                   if self.stand_of(s["character"]) in ("oppose", "mock", "correct")]
        seat = random.choice(hostile or others)
        stance = self.stand_of(seat["character"])
        phrase = self.s.phrases.get(self.s.voice_key(seat), self.lang, stance, seat["character"])
        if phrase is None:
            return
        line = Line(seat=seat, move=stance, text="", final=False, nudge="", director_s=0.0,
                    stance=stance, gesture=moves.reaction_for(seat["character"], stance) or "")
        line.pre_text, line.pre_pcm = phrase
        line.audio.finish()
        self.interrupters.append(seat["character"])
        await self.say(line, wait=False)

    async def interrupt(self, line: Line) -> None:
        """Cut in: a cached interjection at once and the line straight after,
        or the line alone when it opens in the robot's own words."""
        if line.use_pre and line.pre_text:
            pcm = self.s.phrases.audio(self.s.voice_key(line.seat), line.pre_text)
            if pcm:
                line.pre_pcm = pcm
        self.openers = (self.openers + [" ".join((line.pre_text + " " + line.text).split()[:3])])[-12:]
        self.interrupters.append(line.seat["character"])
        self.status("speaking", speaker=line.seat, detail="interrupting")
        await self.say(line, wait=False)
        # Defending is never a first interruption: another robot, one on the
        # person's side, cuts off the robot that just interrupted them.
        defender = self.defender_for(line)
        if defender is not None:
            self.s.spawn(self.defend(line, defender))
            return
        # A second robot piles on, at levels 4-5, with only an interjection.
        pile = line.pile_on or {}
        seat = next((s for s in self.seats if s["character"].lower()
                     == str(pile.get("speaker", "")).lower()
                     and s["key"] != line.seat["key"]), None) if pile else None
        # The piler's own level says how likely (only 4-5 pile on).
        if seat is not None and random.random() < PILE_ON_CHANCE.get(self.seat_level(seat), 0.0):
            # A pile-on joins the same side, in the piler's own stand.
            stance = self.stand_of(seat["character"])
            same_side = (stance == "approve") == (line.stance == "approve")
            if same_side:
                self.s.spawn(self.pile_on(seat, stance, delay=random.uniform(0.7, 1.4)))

    def defender_for(self, line: Line) -> Optional[dict]:
        """Who (if anyone) stands up for the person against this interruption:
        only when the interrupter was hostile, sometimes, and a robot that backs
        the person (Tamar first: defending is in her character)."""
        if line.stance not in ("oppose", "mock", "cut"):
            return None
        fans = [s for s in self.seats if s["key"] != line.seat["key"]
                and self.stand_of(s["character"]) == "approve"]
        fans.sort(key=lambda s: s["character"] != "Tamar")
        # The defender's own level says how likely (0-1 never cut anyone off).
        fans = [s for s in fans if DEFEND_CHANCE.get(self.seat_level(s), 0.0) > 0]
        if not fans or random.random() > DEFEND_CHANCE.get(self.seat_level(fans[0]), 0.0):
            return None
        return fans[0]

    async def defend(self, line: Line, seat: dict) -> None:
        """Cut the interrupting robot off, mid-line: "Hey, let him finish!"."""
        from .phrases import CHARACTER, PHRASES
        lang = self.lang if self.lang in PHRASES else "en"
        options = list(PHRASES[lang].get("defend", []))
        options += [t for st, t in CHARACTER.get(lang, {}).get(seat["character"], [])
                    if st == "defend"]
        recent = set(self.s.phrases.recent())
        options = [t for t in options if t not in recent] or options
        random.shuffle(options)
        key = self.s.voice_key(seat)
        text = next((t for t in options if self.s.phrases.audio(key, t)), options[0])
        pcm = self.s.phrases.audio(key, text)
        mine = Line(seat=seat, move="defend", text="" if pcm else text, final=False, nudge="",
                    director_s=0.0, stance="defend",
                    gesture=moves.reaction_for(seat["character"], "defend") or "")
        if pcm:
            mine.pre_text, mine.pre_pcm = text, pcm
            mine.audio.finish()
        else:
            mine.tts = asyncio.create_task(self.s.voice(mine))
        self.s.phrases.used(text)
        # Let the interrupter get a few words out first.
        await asyncio.sleep(random.uniform(1.2, 2.2))
        current = self.current
        if current is None or current[0] is not line or self.speaking is None \
                or self.speaking.done():
            self.discard(self.ready(mine))
            return
        victim, entry = current
        link = self.s.links.get(victim.seat["key"])
        self.speaking.cancel()
        if link is not None:
            await link.stop_audio()
        self.ears.drop_reference(victim.seat["key"], time.monotonic() + 0.3)
        entry["cut"] = True
        entry["spoken"] = " ".join(entry["text"].split()[:4]) + "..."
        self.m.add_turn(entry)
        self.finish_entry(victim, entry)
        await self.say(mine, wait=False)

    async def pile_on(self, seat: dict, stance: str, delay: float) -> None:
        await asyncio.sleep(delay)
        phrase = self.s.phrases.get(self.s.voice_key(seat), self.lang, stance, seat["character"])
        link = self.s.links.get(seat["key"])
        if phrase is None or link is None:
            return
        text, pcm = phrase
        name = moves.reaction_for(seat["character"], stance)
        if name:
            self.s.spawn(self.s.gesture(seat["key"], name))
        self.ears.add_reference(seat["key"], time.monotonic() + PLAY_LATENCY_S, rms_blocks(pcm))
        self.turn(kind="robot", who=seat["name"], character=seat["character"], text=text,
                  move=stance, gesture=name or "", hold=False)
        self.recent_robot.append((time.monotonic(), text))
        try:
            await link.play(loud(pcm, seat.get("loudness", DEFAULT_LOUDNESS)))
            await link.end_line()
        except Exception as exc:  # noqa: BLE001
            log.info("pile-on by %s failed: %s", seat["name"], exc)


# ================================================================ manager
MODE_CLASS = {"group": GroupTalk, "interrupt": InterruptTalk, "free": FreeTalk}


class GroupManager:
    """Config, state, the open connection and the running conversation."""

    def __init__(self, hub: Any) -> None:
        self.hub = hub
        self.cfg = self._load()
        self.voices: list[dict] = []
        self.transcript: list[dict] = []
        self.status = {"phase": "idle", "speaker": None, "character": None,
                       "elapsed_s": 0, "detail": "", "mode": None}
        self.error: Optional[str] = None
        self.pending_nudge = ""
        self.people_live = ""
        self.eleven_credits: Optional[int] = None
        self.eleven_forced = False
        self.session: Optional[Session] = None
        self.convo: Optional[Conversation] = None
        self._task: Optional[asyncio.Task] = None         # the conversation
        self._connecting: Optional[asyncio.Task] = None
        self._levels_task: Optional[asyncio.Task] = None
        self._watch_task: Optional[asyncio.Task] = None
        self._subs: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        self._log_path = None
        self._unlogged: list[dict] = []     # robot lines not spoken yet (log_turn)
        # Warm services for the hub's whole life (shared_services, warm_up).
        self._services: Optional[Services] = None
        self._services_keys: Optional[tuple] = None
        self._warm: dict[str, dict] = {}            # check name -> {"ok", "ms", "detail"}
        self._warm_at: Optional[float] = None
        self._warming: Optional[asyncio.Future] = None
        self._keeper_task: Optional[asyncio.Task] = None
        self._startup_warm: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # The first line of each mode, made while the robots wait (premake).
        self._premade: Optional[dict] = None
        self._premake_task: Optional[asyncio.Future] = None

    # ------------------------------------------------------------ config
    def _load(self) -> dict:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        settings = {**DEFAULT_SETTINGS, **(data.get("settings") or {})}
        if settings.get("voice_provider") == "elevenlabs" and "voice_provider_v2" not in (
                data.get("settings") or {}):
            # 2026-10-19 configs said "elevenlabs" by default; "auto" falls back
            # to OpenAI when the credits run out.
            settings["voice_provider"] = "auto"
        settings["voice_provider_v2"] = True
        # Before 2026-10-21 these were one setting for the whole table: a robot
        # saved then starts from the table's value.
        seats = [{**seat_defaults(settings), **s} for s in (data.get("seats") or [])
                 if isinstance(s, dict)]
        return {"seats": seats, "settings": settings}

    def _save(self) -> None:
        try:
            CONFIG_FILE.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        except OSError as exc:
            log.warning("could not save %s: %s", CONFIG_FILE, exc)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def connected(self) -> bool:
        return self.session is not None

    @property
    def mode(self) -> Optional[str]:
        return self.convo.mode if (self.convo is not None and self.running) else None

    def available(self) -> list[dict]:
        if self.cfg["settings"].get("simulate"):
            return [{"key": k, "name": "laptop-{}".format(i + 1), "state": "CONNECTED"}
                    for i, k in enumerate(SIM_KEYS)]
        out = [{"key": r.key, "name": r.name, "state": r.state}
               for r in self.hub.registry.all()
               if r.type_id == REACHY and r.state in LIVE]
        return out + [{"key": k, "name": "laptop", "state": "CONNECTED"}
                      for k in self.laptop_keys()]

    def laptop_keys(self) -> list[str]:
        """Robots that talk through the laptop's speaker next to the real
        ones (the page's + and X; 2026-10-25, testing with one Reachy)."""
        st = self.cfg["settings"]
        keys = st.get("laptop_seats")
        if not isinstance(keys, list):
            keys = [SIM_KEYS[0]] if st.get("laptop_robot") else []
        return [k for k in SIM_KEYS if k in keys]

    def seats(self) -> list[dict]:
        avail = {a["key"]: a for a in self.available()}
        saved = {s["key"]: s for s in self.cfg["seats"] if s.get("key")}
        out = []
        base = seat_defaults(self.cfg["settings"])
        for s in self.cfg["seats"]:
            if s.get("key") in avail:
                out.append({**base, **s, "name": avail[s["key"]]["name"]})
        used = {s.get("character") for s in out}
        voices = {s.get("voice_id") for s in out}
        simulate = bool(self.cfg["settings"].get("simulate"))
        # Robots that sit at the table but are not here (one Reachy at home).
        away = [s for s in self.cfg["seats"] if s.get("included")
                and s.get("key") not in avail and not is_laptop_seat(s)]
        for key, a in sorted(avail.items(), key=lambda kv: (is_laptop_seat({"key": kv[0]}),
                                                           kv[1]["name"], kv[0])):
            if key in saved:
                continue
            new = dict(next((d for d in DEFAULT_CHARACTERS if d["character"] not in used),
                            DEFAULT_CHARACTERS[0]))
            stand_in = next((s for s in away if s.get("character") not in used), None) \
                if is_laptop_seat({"key": key}) and not simulate else None
            if stand_in is not None:
                # A laptop robot first plays a missing robot, voice and all.
                new = {f: stand_in[f] for f in SEAT_LIVE if f in stand_in}
            if new.get("character") in used:
                n = len(used) + 1
                while ROBOT_LABEL.format(n) in used:
                    n += 1
                new["character"] = ROBOT_LABEL.format(n)
            if not new.get("voice_id") or new["voice_id"] in voices:
                new["voice_id"] = next((v for v in MALE_ELEVEN if v not in voices),
                                       new.get("voice_id") or MALE_ELEVEN[0])
            used.add(new["character"])
            voices.add(new["voice_id"])
            first_sim = key == SIM_KEYS[0]
            out.append({**base, "key": key, "name": a["name"], "included": True,
                        "listen": (first_sim and simulate) or not is_laptop_seat({"key": key}),
                        **new})
        # The voices a robot gets when none is picked, for the page to show.
        for i, seat in enumerate(out):
            seat["default_voices"] = {
                "elevenlabs": DEFAULT_CHARACTERS[0]["voice_id"],
                "openai": default_openai_voice(seat, i), "gemini": default_gemini_voice(seat, i)}
        return out

    def save_config(self, body: dict) -> dict:
        settings = body.get("settings") or {}
        seats = body.get("seats")
        if self.running and isinstance(seats, list):
            # While they talk: each robot's own settings change at once; which
            # robots sit where, and who listens, waits for Stop.
            seats = self.merge_live_seats(seats)
        # Connected but not talking: seat changes are saved now and used at the
        # next Start (which reconnects if needed).
        if self.connected and "simulate" in settings and bool(settings["simulate"]) != bool(
                self.cfg["settings"].get("simulate")) and self.running:
            return {"ok": False, "error": "stop the conversation to switch simulation"}
        if isinstance(settings.get("laptop_seats"), list):
            old_keys = self.laptop_keys()
            new_keys = [k for k in SIM_KEYS if k in settings["laptop_seats"]]
            if new_keys != old_keys and self.running:
                return {"ok": False, "error": "stop the conversation to add or remove robots"}
            if not self.cfg["settings"].get("simulate"):
                # A robot added with + starts fresh; one removed with X is gone.
                changed = set(old_keys) ^ set(new_keys)
                self.cfg["seats"] = [s for s in self.cfg["seats"] if s.get("key") not in changed]
                if isinstance(seats, list):
                    seats = [s for s in seats if not (isinstance(s, dict) and s.get("key") in
                                                      set(old_keys) - set(new_keys))]
            self.cfg["settings"]["laptop_seats"] = new_keys
            self.cfg["settings"].pop("laptop_robot", None)
        if isinstance(seats, list):
            old_seats = {s.get("key"): s for s in self.seats()}
            old_seats.update({s.get("key"): s for s in self.cfg["seats"]})
            base = seat_defaults(self.cfg["settings"])
            new = []
            for s in seats:
                if isinstance(s, dict) and s.get("key"):
                    old = {**base, **old_seats.get(str(s["key"]), {})}
                    seat = {f: old[f] for f in SEAT_LIVE + SEAT_FIXED if f in old}
                    for f in SEAT_LIVE + SEAT_FIXED:
                        if f in s:
                            seat[f] = clean_seat_field(f, s[f], old.get(f))
                    new.append({"key": str(s["key"]), **seat})
            keys = {s["key"] for s in new}
            self.cfg["seats"] = new + [s for s in self.cfg["seats"] if s.get("key") not in keys]
        for name, kind in (("topic", str), ("language", str), ("minutes", float),
                           ("listen_gap_s", float), ("simulate", bool),
                           ("heads_mirror", bool), ("voice_min_level", float),
                           ("voice_provider", str), ("director_model", str),
                           ("barge_in", str), ("interrupt_level", int), ("vision", bool),
                           ("gestures", str), ("slow_network", bool), ("people_mic", str),
                           ("lab_intro", bool)):
            if name in settings:
                try:
                    self.cfg["settings"][name] = kind(settings[name])
                except (TypeError, ValueError):
                    pass
        st = self.cfg["settings"]
        if st["voice_provider"] not in ("auto", "elevenlabs", "openai", "openrouter", "gemini"):
            st["voice_provider"] = "auto"
        if st["language"] not in ("auto", "he", "en"):
            st["language"] = "auto"
        if st["director_model"] not in DIRECTOR_MODELS:
            st["director_model"] = DIRECTOR_MODEL
        if st["barge_in"] not in BARGE_DB:
            st["barge_in"] = "normal"
        if st["gestures"] not in ("lively", "calm"):
            st["gestures"] = "lively"
        st["people_mic"] = str(st.get("people_mic") or "auto").strip()[:200] or "auto"
        st["topic"] = str(st["topic"])[:500]
        st["interrupt_level"] = min(5, max(0, int(st["interrupt_level"])))
        st["minutes"] = min(60.0, max(0.5, st["minutes"]))
        st["listen_gap_s"] = min(3.0, max(0.2, st["listen_gap_s"]))
        st["voice_min_level"] = min(0.9, max(0.0, st["voice_min_level"]))
        self._save()
        self.apply_live()
        self.publish_state()
        if self.session is not None and not self.running and self._premade is not None:
            self.schedule_premake(3.0)      # the first lines follow the new settings
        return {"ok": True}

    def merge_live_seats(self, seats: list) -> list:
        """The page's seats with only each robot's own settings taken: order,
        Included and Listens stay as they are while a conversation runs."""
        incoming = {str(s["key"]): s for s in seats if isinstance(s, dict) and s.get("key")}
        out = []
        for s in self.cfg["seats"]:
            mine = dict(s)
            new = incoming.get(s.get("key"), {})
            mine.update({f: new[f] for f in SEAT_LIVE if f in new})
            out.append(mine)
        known = {s.get("key") for s in self.cfg["seats"]}
        for key, s in incoming.items():
            if key not in known:        # a robot with no saved seat yet
                cur = next((x for x in self.seats() if x["key"] == key), {})
                out.append({**{f: cur[f] for f in SEAT_FIXED if f in cur}, "key": key,
                            **{f: s[f] for f in SEAT_LIVE if f in s}})
        return out

    def apply_live(self) -> None:
        """Settings that act at once on an open connection."""
        if self.session is None:
            return
        live = self.session.settings
        for name in LIVE_SETTINGS:
            live[name] = self.cfg["settings"].get(name)
        # Each robot's own settings (name, personality, voice, writer, level,
        # gestures, camera, volume) go to the robots at the table at once.
        # A robot never saved keeps what seats() gave it (its default voice).
        saved = {s.get("key"): s for s in self.cfg["seats"]}
        for seat in self.session.seats:
            mine = saved.get(seat["key"], {})
            for f in SEAT_LIVE:
                if f in mine:
                    seat[f] = mine[f]
        if self.session.ears is not None:
            self.session.ears.min_level = float(live.get("voice_min_level") or 0.0)
            barge = BARGE_DB.get(live.get("barge_in"), 10.0)
            if self.mode == "interrupt":
                barge = barge or 12.0
            self.session.ears.barge_db = barge
        if self.session.links:
            self.session.rewarm()
        self.session.services.compressed = live.get("slow_network", True) is not False
        # The table's writer (races, the hearing call): the first robot's.
        first = self.session.seats[0] if self.session.seats else {}
        writer = first.get("writer") or live.get("director_model")
        self.session.services.director_model = writer if writer in DIRECTOR_MODELS else DIRECTOR_MODEL

    async def ensure_voices(self) -> None:
        if self.voices:
            return
        key = self._key("elevenlabs")
        if not key:
            return
        try:
            voices = await list_voices(key)
            # Tomer, 2026-10-22: the robots only ever get male voices.
            self.voices = [v for v in voices if male(v.get("gender", ""))] if MALE_VOICES_ONLY \
                else voices
        except Exception as exc:  # noqa: BLE001
            log.info("could not list ElevenLabs voices: %s", exc)
        if self.eleven_credits is None:
            self.eleven_credits = await eleven_credits(key)

    def _keys(self, provider: str) -> list[str]:
        return [e["key"] for e in self.hub.keys.all_secrets()
                if e.get("provider") == provider and e.get("key")]

    def _key(self, provider: str) -> str:
        return next((e["key"] for e in self.hub.keys.all_secrets()
                     if e.get("provider") == provider), "")

    # ------------------------------------------------------------- state
    def state(self) -> dict:
        echo = {}
        if self.session is not None and self.session.ears is not None:
            echo = self.session.ears.echo_report()
        session = self.session
        return {"running": self.running, "connected": self.connected, "mode": self.mode,
                "connected_seats": [s["key"] for s in session.seats] if session else [],
                "available": self.available(), "seats": self.seats(), "voices": self.voices,
                "voice_options": {
                    "openai": [{"id": v, "label": "{} ({})".format(v, d)}
                               for v, d in OPENAI_VOICE_LIST if voice_allowed(d)],
                    "openrouter": [{"id": v, "label": "{} ({})".format(v, d)}
                                   for v, d in OPENAI_VOICE_LIST
                                   if v in OPENROUTER_VOICES and voice_allowed(d)],
                    "gemini": [{"id": v, "label": "{} ({})".format(v, d)}
                               for v, d in GEMINI_VOICE_LIST if voice_allowed(d)]},
                "providers": {"elevenlabs": bool(self._key("elevenlabs")),
                              "openai": bool(self._key("gpt")),
                              "openrouter": bool(self._key("openrouter")),
                              "gemini": bool(self._keys("gemini"))},
                "settings": dict(self.cfg["settings"]), "status": dict(self.status),
                "transcript": list(self.transcript), "error": self.error,
                "people_live": self.people_live, "eleven_credits": self.eleven_credits,
                "limit_s": round(self.convo.limit()) if self.convo is not None and self.running
                else None,
                "closing": bool(self.convo is not None and self.running and self.convo.closing),
                "eleven_in_use": bool(session.use_eleven()) if session else None,
                # Per robot: the voice and the writer each one uses right now.
                "voice_backend": {s["key"]: session.voice_backend(s) for s in session.seats}
                if session else {},
                "brain": {s["key"]: session.services.brain(s.get("writer") or "")
                          for s in session.seats} if session else {},
                "echo": echo,
                # The laptop's mics for the "People's mic" menu, and the one
                # the connected session hears the people through ("" = robots').
                "mics": self.mic_names(),
                "people_mic_active": session.people_mic.name
                if session is not None and session.people_mic is not None
                and session.mic_in_use == "people" else "",
                # What hears the people right now, and whether a DJI is plugged in.
                "mic": {**(session.mic_state() if session is not None and session.ears is not None
                           else {"in_use": None, "people_mic": "", "health": "",
                                 "robot_mics": []}),
                        "dji": (laptop_mic.MIC_WATCH.dji() or {}).get("name", "")},
                "warm": self.warm_state()}

    def mic_names(self) -> list[str]:
        """The laptop's mics as the hub's watcher last saw them (no audio calls here)."""
        return laptop_mic.MIC_WATCH.names()

    async def switch_mic(self, use: str) -> dict:
        """The page's mic button: "robots" (at once, mid-conversation) or "people"."""
        session = self.session
        if session is None or session.ears is None or not session.links:
            return {"ok": False, "error": "connect the robots first"}
        if use == "robots":
            ok = await session.use_robot_mics("switched by hand")
        elif use == "people":
            ok = await session.use_people_mic()
        else:
            return {"ok": False, "error": "unknown mic {!r}".format(use)}
        return {"ok": bool(ok), **({} if ok else {"error": "could not switch the mic"})}

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        if self._watch_task is None or self._watch_task.done():
            self._watch_task = asyncio.create_task(self._watch_robots())
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def publish_state(self) -> None:
        self.publish({"type": "group.state", **self.state()})

    def set_status(self, status: dict) -> None:
        base = {"phase": "idle", "speaker": None, "character": None, "elapsed_s": 0,
                "detail": "", "mode": self.mode}
        self.status = {**base, **status}
        self.publish({"type": "group.status", "status": self.status})

    def add_turn(self, entry: dict) -> None:
        if not any(t is entry for t in self.transcript):
            self.transcript.append(entry)
        self.publish({"type": "group.turn", "turn": dict(entry)})

    def note(self, text: str) -> None:
        log.info("group: %s", text)
        entry = {"id": len(self.transcript) + 1, "t": round(self.convo.elapsed(), 1)
                 if self.convo is not None and self.running else None,
                 "who": "hub", "character": None, "kind": "note", "text": text,
                 "move": "", "latency_ms": None, "cut": False, "heard_by": None}
        self.add_turn(entry)
        self.log_turn(entry)

    def log_turn(self, entry: dict, hold: bool = False) -> None:
        """Append to the session log. `hold`: a robot line not spoken yet,
        written by a later log_turn (once its timings are in) or flush_log.
        """
        if hold:
            self._unlogged.append(entry)
            return
        self._unlogged = [e for e in self._unlogged if e is not entry]
        if self._log_path is None:
            return
        try:
            LOG_DIR.mkdir(exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def live_people(self, text: str) -> None:
        """What the person is saying, while they say it (interrupt mode)."""
        self.people_live = text
        self.publish({"type": "group.people", "text": text})

    async def _watch_robots(self) -> None:
        q = self.hub.bus.subscribe()
        try:
            while self._subs:
                try:
                    ev = await asyncio.wait_for(q.get(), 5)
                except asyncio.TimeoutError:
                    continue
                if ev.get("type") == "robot" and ev.get("type_id") == REACHY:
                    self.publish_state()
        finally:
            self.hub.bus.unsubscribe(q)

    # ----------------------------------------------------------- control
    def set_loudness(self, key: str, value: Any) -> dict:
        """One robot's speech volume, any time (also mid-sentence: the next
        chunk sent is at the new level)."""
        try:
            level = min(250, max(0, int(round(float(value)))))
        except (TypeError, ValueError):
            return {"ok": False, "error": "loudness must be a number"}
        seat = next((s for s in self.cfg["seats"] if s.get("key") == key), None)
        if seat is None:
            seat = next((dict(s) for s in self.seats() if s["key"] == key), None)
            if seat is None:
                return {"ok": False, "error": "no such robot"}
            self.cfg["seats"].append({k: seat[k] for k in ("key",) + SEAT_FIXED + SEAT_LIVE
                                      if k in seat})
            seat = self.cfg["seats"][-1]
        seat["loudness"] = level
        if self.session is not None:
            for live in self.session.seats:
                if live["key"] == key:
                    live["loudness"] = level
        self._save()
        self.publish_state()
        return {"ok": True}

    def nudge(self, text: str) -> dict:
        self.pending_nudge = str(text or "").strip()[:300]
        if self.pending_nudge:
            self.note("operator: {}".format(self.pending_nudge))
        return {"ok": True}

    async def start(self, mode: str = "group") -> dict:
        """Start a conversation in `mode`. Connects first if needed; a running
        conversation (either mode) is stopped first, so this is also the switch."""
        if mode not in MODES:
            return {"ok": False, "error": "unknown mode {!r}".format(mode)}
        async with self._lock:
            await self._stop_conversation()
            refused = await self._ensure_session()
            if refused is not None:
                return refused
            self.pending_nudge = ""
            self._task = asyncio.create_task(self._lifecycle(mode))
            self.publish_state()
            return {"ok": True}

    async def _ensure_session(self) -> Optional[dict]:
        """The robots' connection for the current seats, started if needed
        (under self._lock, no conversation running). A refusal, or None."""
        seats = [s for s in self.seats() if s.get("included")]
        settings = dict(self.cfg["settings"])
        if len(seats) < 2 and not settings.get("simulate"):
            return {"ok": False, "error": "include at least two connected Reachys"}
        if not seats:
            return {"ok": False, "error": "no seats are included"}
        labels = [s.get("character", "").strip().lower() for s in seats]
        twins = sorted({s["character"] for s, l in zip(seats, labels) if labels.count(l) > 1})
        if twins:
            return {"ok": False, "error": "two robots are called {}: give each its own "
                                          "name".format(", ".join(twins))}
        if not self._key("gpt") and not self._keys("gemini") and not self._key("openrouter"):
            return {"ok": False, "error": "the hub needs an OpenRouter, OpenAI or Gemini key "
                                          "(Keys panel on the main page)"}
        self.error = None
        if self.session is not None and self.session.signature != Session.make_signature(
                seats, settings):
            self.note("the seats changed: reconnecting the robots")
            await self._disconnect()
        if self.session is None:
            self.drop_premade()
            self.transcript = []
            self._log_path = LOG_DIR / time.strftime("group-%Y%m%d-%H%M%S.jsonl")
            live = {k: settings.get(k) for k in LIVE_SETTINGS}
            live["simulate"] = settings.get("simulate")
            live["people_mic"] = settings.get("people_mic") or "auto"
            services = self.shared_services()
            session = Session(self, seats, live, services)
            services.on_switch = lambda msg: (self.note(msg), session.rewarm(),
                                              self.publish_state())
            if not services.eleven_key:
                session.eleven_down = True
            self.session = session
            self._levels_task = asyncio.create_task(self._levels())
            self._connecting = asyncio.create_task(session.open())
            self.publish_state()
        return None

    async def _connected(self) -> None:
        """Wait for the robots' connection to finish opening (shielded: a
        switch pressed meanwhile must not cancel it)."""
        session = self.session
        if self._connecting is None or session is None:
            return
        await asyncio.shield(self._connecting)
        if self._connecting is not None:
            self._connecting = None
            self.hub.bus.emit_log("info", "group: connected {}".format(
                ", ".join(s["name"] for s in session.seats)))

    # --------------------------------------------------------- get ready
    async def get_ready(self) -> dict:
        """Tomer, 2026-10-22: nothing may load once the demo starts. Connect
        the robots (their players, mics and cameras), check every service the
        conversation uses with a real request, and write and voice the first
        line of each mode, so Start speaks at once."""
        async with self._lock:
            if self.running:
                return {"ok": True}
            refused = await self._ensure_session()
            if refused is not None:
                return refused
        try:
            await self._connected()
        except Exception as exc:  # noqa: BLE001
            self.error = "could not connect the robots: {}".format(exc)
            self._connecting = None
            await self.disconnect()
            return {"ok": False, "error": self.error}
        self.set_status({"phase": "ready", "detail": "getting ready: checking every service"})
        await self.warm_up(full=True)
        await self.premake()
        session = self.session
        if session is not None and session._warm is not None and not session._warm.done():
            # Interrupt mode's interjections in these voices: recorded once
            # (kept on disk), never while the demo runs.
            self.set_status({"phase": "ready", "detail": "getting ready: recording the "
                             "interjections (first time with these voices only)"})
            try:
                await asyncio.shield(session._warm)
            except Exception:  # noqa: BLE001
                pass
        bad = [name for name, w in self._warm.items() if w.get("ok") is False]
        self.set_status({"phase": "ready", "detail": "ready: press a mode to start" if not bad
                         else "connected, but {} failed the check".format(", ".join(bad))})
        self.publish_state()
        return {"ok": True, "failed": bad}

    def shared_services(self) -> Services:
        """One Services for the hub's whole life, so its connections stay warm
        between conversations; a new one only when the keys change."""
        keys = (self._key("gpt"), self._key("elevenlabs"), tuple(self._keys("gemini")),
                self._key("openrouter"))
        if self._services is None or self._services_keys != keys:
            old = self._services
            self._services = Services(keys[0], keys[1], self.cfg["settings"].get("director_model")
                                      or DIRECTOR_MODEL, list(keys[2]), keys[3])
            self._services_keys = keys
            self._warm = {}
            if old is not None and (self.session is None or self.session.services is not old):
                asyncio.ensure_future(old.close())
        self._services.compressed = self.cfg["settings"].get("slow_network", True) is not False
        return self._services

    def warm_state(self) -> dict:
        return {"checks": dict(self._warm), "at": self._warm_at,
                "busy": self._warming is not None and not self._warming.done()}

    async def warm_up(self, full: bool = True) -> None:
        """Every service the conversation uses, with one real, tiny request
        each: each writer the robots use (and the fast one that races a slow
        line), hearing (speech to text), each robot's ElevenLabs voice
        (`full`), and voice detection. Results go to the page."""
        if self._warming is not None and not self._warming.done():
            await asyncio.shield(self._warming)
            return
        self._warming = asyncio.ensure_future(self._warm_up(full))
        self.publish_state()
        try:
            await asyncio.shield(self._warming)
        finally:
            self.publish_state()

    async def _warm_up(self, full: bool) -> None:
        svc = self.shared_services()
        settings = self.cfg["settings"]
        seats = [s for s in self.seats() if s.get("included")]
        lang = settings.get("language") if settings.get("language") in ("he", "en") else ""

        async def check(name: str, job: Any) -> None:
            t = time.monotonic()
            try:
                await asyncio.wait_for(job, 25.0)
                self._warm[name] = {"ok": True, "ms": int((time.monotonic() - t) * 1000)}
            except Exception as exc:  # noqa: BLE001
                self._warm[name] = {"ok": False, "ms": int((time.monotonic() - t) * 1000),
                                    "detail": "{}: {}".format(type(exc).__name__, exc)[:200]}
                log.warning("warm-up: %s failed: %s", name, exc)
            self.publish_state()

        jobs: dict[str, Any] = {}
        if svc.openai_key:
            jobs["OpenAI"] = svc.warm()
        writers: list[str] = []
        for s in seats:
            w = s.get("writer") or settings.get("director_model") or DIRECTOR_MODEL
            if w not in writers:
                writers.append(w)
        if svc.openrouter_key:
            for w in (FAST_MODEL, "google/gemini-3.5-flash-lite"):   # the racers (Conversation.ask)
                if w not in writers:
                    writers.append(w)
        for w in writers:
            # The full name: "gemini-3.5-flash-lite" direct and through
            # OpenRouter are two different services.
            jobs["Writer " + w] = svc.ping_writer(w)
        jobs["Hearing (speech to text)"] = svc.ping_hearing(lang)
        if full and svc.eleven_key:
            done: set = set()
            for s in seats:
                if s.get("voice_provider") in ("elevenlabs", "auto") and s.get("voice_id") \
                        and s["voice_id"] not in done:
                    done.add(s["voice_id"])
                    jobs["Voice of " + (s.get("character") or s["key"])] = svc.ping_voice(s["voice_id"])
        if not settings.get("simulate"):
            from .vad import SileroVAD
            jobs["Voice detection"] = asyncio.to_thread(SileroVAD)
        await asyncio.gather(*(check(n, j) for n, j in jobs.items()))
        self._warm_at = time.time()
        bad = [n for n, w in self._warm.items() if w.get("ok") is False]
        log.info("warm-up done in %s: %s", "full" if full else "short",
                 "all ok" if not bad else "failed: " + ", ".join(bad))

    async def _keep_warm(self) -> None:
        """Every KEEPALIVE_S: free requests that keep each service's
        connection open, so no line pays a new handshake over the hotspot."""
        while True:
            await asyncio.sleep(KEEPALIVE_S)
            try:
                await self.shared_services().keepalive()
            except Exception:  # noqa: BLE001
                log.exception("keepalive failed")

    async def startup(self) -> None:
        """At hub start: watch the laptop's mics, warm every service, keep them warm."""
        laptop_mic.MIC_WATCH.on_change = lambda dji: self._loop.call_soon_threadsafe(
            self.publish_state) if self._loop is not None else None
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(laptop_mic.MIC_WATCH.start)
        self._keeper_task = asyncio.create_task(self._keep_warm())
        self._startup_warm = asyncio.create_task(self.warm_up(full=True))

    # ------------------------------------------------- first lines, made ahead
    def premade_sig(self) -> str:
        st = self.cfg["settings"]
        seats = self.session.seats if self.session is not None else []
        return json.dumps([st.get("topic"), st.get("language"), st.get("lab_intro", True),
                           [[s["key"], s.get("character"), s.get("persona"),
                             s.get("voice_provider"), s.get("voice_id"), s.get("writer"),
                             s.get("interrupt_level")] for s in seats]], ensure_ascii=False)

    def drop_premade(self) -> None:
        made, self._premade = self._premade, None
        if made:
            for _convo, task in made["modes"].values():
                Conversation.discard(task)

    async def premake(self) -> None:
        """Write and voice the first line of both modes now, while the robots
        wait (only when connected and quiet; kept until the settings change)."""
        session = self.session
        if session is None or self.running or self._connecting is not None or not session.links:
            return
        sig = self.premade_sig()
        if self._premade is not None and self._premade["sig"] == sig:
            return
        self.drop_premade()
        modes = {}
        for mode, cls in MODE_CLASS.items():
            convo = cls(self, session)
            modes[mode] = (convo, convo.opener())
        self._premade = {"sig": sig, "at": time.monotonic(), "modes": modes}
        await asyncio.gather(*(t for _c, t in modes.values()), return_exceptions=True)
        # Written is not enough: ready means voiced too, so Start plays it at once.
        voices = [t.result().tts for _c, t in modes.values()
                  if t.done() and not t.cancelled() and t.exception() is None
                  and isinstance(t.result(), Line) and t.result().tts is not None]
        voices += [ln.tts for c, _t in modes.values()
                   for ln in getattr(c, "intro_lines", []) if ln.tts is not None]
        if voices:
            await asyncio.wait(voices, timeout=30.0)

    def schedule_premake(self, delay: float = 2.0) -> None:
        """After an edit (debounced) or a Stop: make the first lines again."""
        if self._premake_task is not None and not self._premake_task.done():
            self._premake_task.cancel()

        async def later() -> None:
            await asyncio.sleep(delay)
            await self.premake()
        try:
            self._premake_task = asyncio.ensure_future(later())
        except RuntimeError:
            self._premake_task = None       # no event loop (tests)

    def take_premade(self, mode: str) -> Optional["Conversation"]:
        """The conversation made ahead for `mode`, if still good; the other is dropped."""
        made, self._premade = self._premade, None
        if not made:
            return None
        pick = None
        for m, (convo, task) in made["modes"].items():
            fresh = (m == mode and made["sig"] == self.premade_sig()
                     and time.monotonic() - made["at"] < PREMADE_MAX_S
                     and not (task.done() and (task.cancelled() or task.exception() is not None)))
            if fresh:
                pick = convo
                convo.premade = task
            else:
                Conversation.discard(task)
        return pick

    async def _lifecycle(self, mode: str) -> None:
        session = self.session
        assert session is not None
        try:
            # Shielded: a switch pressed while the robots connect must not
            # cancel the connecting itself; the next run waits for it too.
            await self._connected()
            self.apply_live()
            convo = self.take_premade(mode)
            if convo is not None:
                convo.restart_clock()
                log.info("%s: the first line was made ahead", MODE_LABEL[mode])
            else:
                convo = MODE_CLASS[mode](self, session)
            self.convo = convo
            self.note("{} started".format(MODE_LABEL[mode]))
            self.publish_state()
            await convo.run()
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("group conversation failed")
            self.error = str(exc)
            if self._connecting is not None or not session.links:
                # Never got connected: nothing to keep open.
                self._connecting = None
                asyncio.create_task(self.disconnect())
        finally:
            try:
                await asyncio.shield(session.quiet())
            except Exception:  # noqa: BLE001
                pass
            self.set_status({"phase": "ready" if self.session is not None else "idle",
                             "detail": "robots connected; press a mode to start"
                             if self.session is not None else ""})
            self.publish_state()
            if self.session is not None:
                self.schedule_premake()     # the next Start speaks at once too

    async def _levels(self) -> None:
        while True:
            await asyncio.sleep(0.125)
            s = self.session
            if s is not None and s.ears is not None:
                self.publish({"type": "group.levels", "levels": s.ears.decay()})

    async def _stop_conversation(self) -> None:
        task = self._task
        if task is None or task.done():
            self.flush_log()
            return
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), 10)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        conv = self.convo
        if isinstance(conv, InterruptTalk) and conv.speaking is not None:
            conv.speaking.cancel()
        self.flush_log()

    def flush_log(self) -> None:
        """Robot lines a Stop cut short: written as they are."""
        for entry in sorted(self._unlogged, key=lambda e: e.get("id") or 0):
            self.log_turn(entry)

    def more_time(self, seconds: float = 60.0) -> dict:
        """The page's +1: the running conversation gets more time (the saved
        Minutes stay as they are)."""
        convo = self.convo
        if convo is None or not self.running:
            return {"ok": False, "error": "no conversation is running"}
        if convo.closing:
            return {"ok": False, "error": "the robots are already saying goodbye"}
        convo.extra_s += max(0.0, min(600.0, float(seconds)))
        self.note("+{:.0f} min: it now ends at {}".format(seconds / 60, _fmt(convo.limit())))
        self.publish_state()
        return {"ok": True, "limit_s": round(convo.limit())}

    async def finish(self) -> dict:
        """Stop, gracefully: every robot says its closing line, then it ends
        (the robot that is talking finishes first). Pressed again: stop now."""
        convo = self.convo
        if convo is None or not self.running or convo.closing:
            return await self.stop()
        convo.closing = True
        self.publish_state()
        return {"ok": True, "closing": True}

    async def stop(self) -> dict:
        """Stop talking; the robots stay connected for the next Start."""
        async with self._lock:
            await self._stop_conversation()
            if self.session is not None:
                await self.session.quiet()
                self.set_status({"phase": "ready",
                                 "detail": "robots connected; press a mode to start"})
            self.publish_state()
        return {"ok": True}

    async def disconnect(self) -> dict:
        async with self._lock:
            await self._stop_conversation()
            await self._disconnect()
        return {"ok": True}

    async def _disconnect(self) -> None:
        session, self.session = self.session, None
        if self._connecting is not None:
            self._connecting.cancel()
            self._connecting = None
        if self._levels_task is not None:
            self._levels_task.cancel()
            self._levels_task = None
        if session is not None:
            self.set_status({"phase": "stopping", "detail": "disconnecting the robots"})
            try:
                await asyncio.shield(session.close())
            except Exception:  # noqa: BLE001
                log.exception("closing the group connection")
            self.hub.bus.emit_log("info", "group: robots released")
        self.set_status({"phase": "idle", "detail": ""})
        self.publish_state()

    async def shutdown(self) -> None:
        await self.disconnect()
        for task in (self._keeper_task, self._startup_warm, self._premake_task):
            if task is not None:
                task.cancel()
        laptop_mic.MIC_WATCH.stop()
        if self._services is not None:
            await self._services.close()
