"""Scripted experiences: every question, every screen and the meaning of every
reaction is written here; the AI only re-words a written reaction so it sounds
natural, and never decides what the visitor answered.

Why (Tomer, 2026-10-12, after live runs): it is a presentation, a closed flow
that must always look right. The wording is ours; Pepper sounds like a relaxed
researcher, not "thanks" and "you can tap or tell me" every turn; the screen
changes WITH the question. An AI-written reaction once answered a tap on "My
voice is... Just right" with "what a nice voice you have" -- so reactions are
written per option too, and the code (not the AI) decides which option was
meant. When it cannot tell, Pepper does not guess: it asks the person to tap
the answer, and waits. If the AI is slow or fails, Pepper says the written line.

One step:  screen changes as Pepper starts the question -> Pepper waits (one
re-ask after REASK_S) -> the answer (tap, speech, or the operator's Accept)
-> the reaction written for that option, still on that step's screen -> next.

Ears: ElevenLabs Scribe (Hebrew and English); the words are mapped to an
option in code (numbers, ordinals, Hebrew sound-alikes: "קואסיט" -> "כועסת").
Voice: the conversation's voice, all of it made ahead at the start.
The object has the same interface the dashboard uses on brain.Brain.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time
from typing import Any, Awaitable, Callable, Optional

from . import eleven
from .brain import real_answer
from .speech import is_hebrew

log = logging.getLogger("pepper.script")

REACT_MODEL = "gpt-4.1"        # most natural Hebrew of 4 tried, ~1 s warm (2026-10-12)
REACT_TIMEOUT_S = 3.0
REASK_S = 12.0
CHAT_URL = "https://api.openai.com/v1/chat/completions"

# The AI only re-words a reaction we wrote, for the option the code matched
# (2026-10-12: free AI reactions once answered a tap on "My voice is... Just
# right" with "what a nice voice you have").
PHRASE_RULES = (
    "You are Pepper, a friendly humanoid robot in a university robotics lab, running a short "
    "research demo with a visitor, in a warm, relaxed researcher's voice. You get the question "
    "you asked, the visitor's answer as already understood, and the reaction to give. Say that "
    "reaction in your own natural words, in at most 12 words. Keep exactly its meaning. Do not "
    "add any fact, compliment, opinion or claim that is not in the reaction; say nothing about "
    "the visitor themselves. No question, no 'thank you' unless the reaction has it, never "
    "announce what comes next, never mention the screen. Reply with the sentence only.")
PHRASE_LANG = {
    "he": "Write natural spoken Hebrew. Speak about yourself in the masculine form. Address the "
          "visitor in the plural (אתם) so you never assume their gender.",
    "en": "Write natural spoken English.",
}


def _choice(question: str, *options: tuple[str, str]) -> tuple[str, dict]:
    return ("show_choice", {"question": question,
                            "options": [{"label": l, "emoji": e} for l, e in options]})


def _message(text: str, emoji: str = "") -> tuple[str, dict]:
    return ("show_message", {"text": text, "emoji": emoji})


def _both(he: str, en: str) -> dict:
    return {"he": he, "en": en}


UNCLEAR = _both("לא בטוח ששמעתי טוב. אפשר לגעת בתשובה על המסך.",
                "I'm not sure I caught that. You can tap your answer on the screen.")
NOTED = _both("רשמתי, אעביר את זה לצוות.", "Noted, I'll pass it on to the team.")

# What visitors may say for each face, whatever order the faces are in. Native
# Hebrew speakers; their English is a second language, so simple and "wrong"
# English words are in too.
FACE_WORDS = {
    "😊": ["שמח", "שמחה", "שמחים", "מחייך", "מחייכת", "חיוך", "מאושר", "מאושרת", "צוחק", "צוחקת",
          "happy", "smile", "smiling", "laugh", "laughing", "glad", "joy", "fun"],
    "😢": ["עצוב", "עצובה", "עצובים", "בוכה", "בכי", "דמעה", "דמעות", "מבואס", "מבואסת",
          "sad", "cry", "crying", "tears", "unhappy"],
    "😲": ["מופתע", "מופתעת", "הפתעה", "מופתעים", "מבוהל", "מבוהלת", "בהלה", "בהלם", "המום",
          "המומה", "פה פתוח", "וואו", "surprised", "surprise", "surprising", "shock", "shocked",
          "wow", "scared", "open mouth"],
}

# A choice step: "reactions" and "words" line up with the screen's options;
# "extra" covers answers that are not on the screen (each with its own written
# reaction). A step without options matches "expect" words instead. In every
# match the longest phrase wins: "לא מהיר" (not fast) is Just right, not Too fast.
FEELINGS = [
    {"title": "Welcome", "gesture": "wave",
     "say": _both("היי, אני פפר. בואו נעשה יחד הדגמה קצרה של מחקר שהמעבדה שלנו יכולה להריץ: "
                  "כמה שאלות קטנות על רגשות, בלי תשובות נכונות או לא נכונות. מוכנים?",
                  "Hi, I'm Pepper. Let's try a short demo of a study our lab could run: a few "
                  "small questions about feelings, no right or wrong answers. Ready?"),
     "screen": {"he": _message("היום: שלום · בחירה · רגשות · סיפור · מבט · סיום", "👋"),
                "en": _message("Today: Hello · Choose · Feelings · Story · Look · Bye", "👋")},
     "expect": {"no": ["לא", "רגע", "חכה", "חכי", "שנייה", "שניה", "עוד לא", "לא עכשיו", "לא מוכן",
                       "לא מוכנה", "no", "wait", "not yet", "not ready", "moment", "later"]},
     "react": {"no": _both("אין לחץ, נתחיל לאט.", "No rush, we'll take it slow."),
               "other": _both("יופי, מתחילים.", "Great, let's start.")}},
    {"title": "Choice",
     "say": _both("קודם כל, איך הכי נוח לכם לענות? אפשר לגעת במסך, לדבר, או גם וגם.",
                  "First, how would you like to answer? You can touch my screen, talk, or both."),
     "screen": {"he": _choice("איך נוח לכם לענות?", ("לגעת", "👆"), ("לדבר", "💬"), ("גם וגם", "👍")),
                "en": _choice("How do you like to answer?", ("Tap", "👆"), ("Talk", "💬"), ("Both", "👍"))},
     "words": [["לגעת", "נגיעה", "נגיעות", "אגע", "לגעת במסך", "ללחוץ", "לחיצה", "לחיצות", "אלחץ",
                "בלחיצה", "להקיש", "הקשה", "אקיש", "מסך", "במסך", "המסך", "על המסך", "אצבע", "ביד",
                "touch", "touching", "tap", "tapping", "press", "pressing", "click", "clicking",
                "screen", "finger", "hand", "push"],
               ["לדבר", "דיבור", "אדבר", "בדיבור", "להגיד", "אגיד", "לומר", "אומר", "קול", "בקול",
                "לענות בקול", "לספר", "בעל פה", "talk", "talking", "speak", "speaking", "say",
                "saying", "voice", "tell", "telling", "words", "mouth", "speech"],
               ["גם וגם", "שניהם", "שתיהן", "שתיהם", "שני הדברים", "הכל", "הכול", "ככה וככה",
                "תלוי", "מה שבא", "מה שנוח", "לא משנה", "both", "all", "everything", "mix",
                "together", "any", "anything", "whatever", "doesn't matter", "dont care"]],
     "reactions": [_both("מעולה, אפשר פשוט לגעת במסך.", "Great, just tap the screen."),
                   _both("מעולה, אני מקשיב.", "Great, I'm listening."),
                   _both("מעולה, איך שנוח לכם.", "Great, whatever works for you.")]},
    {"title": "Comfort",
     "say": _both("ואיך הקול שלי? נעים, מהיר מדי, או חזק מדי?",
                  "And how's my voice? Just right, too fast, or too loud?"),
     "screen": {"he": _choice("הקול שלי...", ("נעים", "👍"), ("מהיר מדי", "🐢"), ("חזק מדי", "🔊")),
                "en": _choice("My voice is...", ("Just right", "👍"), ("Too fast", "🐢"), ("Too loud", "🔊"))},
     "words": [["נעים", "נעימה", "טוב", "בסדר", "בסדר גמור", "מעולה", "מצוין", "מושלם", "יפה", "אחלה",
                "סבבה", "בדיוק", "מתאים", "בדיוק מתאים", "נוח", "רגיל", "נורמלי", "נחמד", "ברור",
                "לא מהיר", "לא חזק", "לא מהר", "לא רועש",
                "just right", "right", "good", "fine", "ok", "okay", "nice", "perfect", "great",
                "normal", "comfortable", "pleasant", "cool", "clear", "beautiful", "not fast",
                "not loud", "not too"],
               ["מהיר", "מהירה", "מהר", "מהיר מדי", "מהר מדי", "מהיר מידי", "מדבר מהר", "מדבר מהר מדי",
                "יותר לאט", "לאט יותר", "תאט", "להאט", "לאט לאט",
                "fast", "too fast", "quick", "quickly", "too quick", "speed", "speedy", "rush",
                "slow down", "slower", "more slow"],
               ["חזק", "חזק מדי", "חזק מידי", "רועש", "רעש", "צועק", "צעקה", "קולני", "גבוה",
                "יותר בשקט", "בשקט יותר", "תנמיך", "להנמיך", "יותר חלש",
                "loud", "too loud", "noisy", "noise", "strong", "too strong", "high", "shouting",
                "shout", "quieter", "less loud", "lower"]],
     "extra": [{"means": "too slow",
                "words": ["איטי", "איטית", "לאט", "לאט מדי", "איטי מדי", "יותר מהר", "מהר יותר",
                          "slow", "too slow", "faster", "more fast"],
                "reaction": NOTED},
               {"means": "too quiet",
                "words": ["שקט", "שקט מדי", "חלש", "חלש מדי", "נמוך", "לא שומע", "לא שומעת",
                          "לא שומעים", "לא שמעתי", "יותר חזק", "חזק יותר", "תגביר", "להגביר",
                          "quiet", "too quiet", "soft", "too soft", "low", "too low", "weak",
                          "can't hear", "cant hear", "louder", "more loud", "volume up"],
                "reaction": NOTED}],
     "reactions": [_both("שמח לשמוע.", "Glad to hear it."), NOTED, NOTED]},
    {"title": "Faces: happy",
     "say": _both("עכשיו לרגשות. איזה מהפרצופים על המסך הוא השמח?",
                  "Now, feelings. Which of the faces on my screen is the happy one?"),
     "screen": {"he": _choice("איזה פרצוף שמח?", ("1", "😊"), ("2", "😢"), ("3", "😲")),
                "en": _choice("Which one is happy?", ("1", "😊"), ("2", "😢"), ("3", "😲"))},
     "reactions": [_both("נכון, זה הפרצוף השמח.", "Right, that's the happy face."),
                   _both("אני הייתי בוחר במספר אחת, הוא נראה לי הכי שמח.",
                         "I'd go with number one, it looks happiest to me."),
                   _both("אני הייתי בוחר במספר אחת, הוא נראה לי הכי שמח.",
                         "I'd go with number one, it looks happiest to me.")]},
    {"title": "Faces: surprised",
     "say": _both("ואיזה מהם מופתע?", "And which one is surprised?"),
     "screen": {"he": _choice("איזה פרצוף מופתע?", ("1", "😢"), ("2", "😲"), ("3", "😊")),
                "en": _choice("Which one is surprised?", ("1", "😢"), ("2", "😲"), ("3", "😊"))},
     "reactions": [_both("אני הייתי בוחר במספר שתיים, הוא נראה לי הכי מופתע.",
                         "I'd go with number two, it looks most surprised to me."),
                   _both("בדיוק, זה הפרצוף המופתע.", "Exactly, that's the surprised one."),
                   _both("אני הייתי בוחר במספר שתיים, הוא נראה לי הכי מופתע.",
                         "I'd go with number two, it looks most surprised to me.")]},
    {"title": "Story",
     "say": _both("סיפור קצר: דנה בנתה מגדל גבוה מקוביות, ואח שלה הקטן הפיל אותו. "
                  "איך לדעתכם דנה מרגישה?",
                  "A short story: Dana built a tall tower of blocks, and her little brother "
                  "knocked it down. How do you think Dana feels?"),
     "screen": {"he": _choice("איך דנה מרגישה?", ("עצובה", "😢"), ("כועסת", "😠"), ("שמחה", "😊")),
                "en": _choice("How does Dana feel?", ("Sad", "😢"), ("Angry", "😠"), ("Happy", "😊"))},
     "words": [["עצובה", "עצוב", "עצב", "עצובה מאוד", "בוכה", "בכי", "מבואסת", "מבואס", "באסה", "מבאס",
                "מאוכזבת", "מאוכזב", "אכזבה", "פגועה", "נפגעה", "נעלבת", "שבורה", "מדוכאת", "רע לה",
                "sad", "very sad", "cry", "crying", "upset", "disappointed", "unhappy", "bad", "down",
                "hurt", "sorry"],
               ["כועסת", "כועס", "כעס", "כועסת מאוד", "עצבנית", "עצבני", "עצבים", "מעוצבנת", "מתעצבנת",
                "זועמת", "זעם", "מתוסכלת", "תסכול", "מרוגזת", "רוגז",
                "angry", "very angry", "mad", "annoyed", "frustrated", "nervous", "furious", "rage",
                "pissed"],
               ["שמחה", "שמח", "מאושרת", "צוחקת", "מחייכת", "בסדר", "happy", "glad", "fine", "laughing"]],
     "extra": [{"means": "both sad and angry",
                "words": ["עצובה וכועסת", "כועסת ועצובה", "גם עצובה וגם כועסת", "גם וגם", "שניהם",
                          "sad and angry", "angry and sad", "both"],
                "reaction": _both("הגיוני, היא בטח גם עצובה וגם כועסת.",
                                  "Makes sense, she's probably both sad and angry.")}],
     "reactions": [_both("הגיוני, גם אני חושב שהיא עצובה.", "Makes sense, I think she's sad too."),
                   _both("הגיוני, גם אני הייתי כועס.", "Makes sense, I'd be angry too."),
                   _both("מעניין. אני חושב שהיא דווקא קצת עצובה.",
                         "Interesting. I think she'd be a bit sad.")]},
    {"title": "Look",
     "say": _both("עכשיו תסתכלו על המסך שלי. מה אתם רואים?",
                  "Now take a look at my screen. What do you see?"),
     "screen": {"he": _message("", "🎈"), "en": _message("", "🎈")},
     "expect": {"balloon": ["בלון", "בלונים", "בלונה", "בלון אדום", "balloon", "baloon", "ballon",
                            "balon", "balloons", "red balloon"]},
     "react": {"balloon": _both("נכון, בלון!", "Right, a balloon!"),
               "other": _both("אצלי על המסך יש בלון.", "On my screen there's a balloon.")}},
    {"title": "Feedback",
     "say": _both("ולסיום, איך היה לכם?", "Last one: how was this for you?"),
     "screen": {"he": _choice("איך היה?", ("קל", "😊"), ("בסדר", "😐"), ("קשה", "😟")),
                "en": _choice("How was it?", ("Easy", "😊"), ("OK", "😐"), ("Hard", "😟"))},
     "words": [["קל", "קלי קלות", "פשוט", "קליל", "כיף", "מהנה", "מעולה", "מצוין", "טוב", "טוב מאוד",
                "אחלה", "נהדר", "מדהים", "יופי", "נחמד מאוד", "לא קשה",
                "easy", "very easy", "simple", "fun", "good", "very good", "great", "nice", "cool",
                "excellent", "amazing", "perfect", "not hard", "not difficult"],
               ["בסדר", "סבבה", "אוקיי", "אוקי", "ככה ככה", "רגיל", "נחמד", "לא רע", "בינוני",
                "ok", "okay", "fine", "so so", "normal", "alright", "all right", "not bad", "medium"],
               ["קשה", "קשה מאוד", "מסובך", "מבלבל", "לא קל", "לא פשוט", "קשה לי", "לא הבנתי",
                "hard", "very hard", "difficult", "confusing", "complicated", "not easy",
                "not simple", "didn't understand"]],
     "reactions": [_both("איזה כיף לשמוע.", "Love to hear it."),
                   _both("טוב לדעת.", "Good to know."),
                   _both("תודה על הכנות, זה עוזר לנו.", "Thanks for being honest, that helps us.")]},
    {"title": "Bye", "gesture": "wave", "answer": False,
     "say": _both("זהו, סיימנו. תודה שהייתם איתי ולקחתם חלק! זו הייתה רק הדגמה קצרה של איך אני "
                  "מנהל שיחה. במחקר אמיתי השאלות יכולות להיות מורכבות יותר, לפי המשתתפים ומטרת "
                  "המחקר. רוצים לשמוע עוד? תשאלו את גיא, הוא ישמח להסביר.",
                  "That's it, we're done. Thanks for being here and taking part! This was just a "
                  "short demo of how I handle a conversation. In real research, the questions can "
                  "be more complex, depending on the participants and the research goal. Want to "
                  "know more? Ask Guy, he'd love to explain."),
     "screen": {"he": _message("סיימנו! תודה", "⭐"), "en": _message("All done! Thank you", "⭐")}},
]

SCRIPTS = {"feelings:script": FEELINGS}

# Spoken numbers and ordinals, Hebrew and English: "השני" / "שתיים" / "second" -> option 2.
NUMBERS = {
    0: {"1", "אחת", "אחד", "ראשון", "ראשונה", "one", "first"},
    1: {"2", "שתיים", "שתים", "שניים", "שני", "שנייה", "שניה", "two", "second"},
    2: {"3", "שלוש", "שלושה", "שלישי", "שלישית", "three", "third"},
    3: {"4", "ארבע", "ארבעה", "רביעי", "רביעית", "four", "fourth"},
}
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
PREFIXES = ("וה", "שה", "בה", "ה", "ו", "ב", "ל", "ש", "מ")
# Letters that sound alike in Hebrew, and final forms; vowel letters are dropped
# after the first letter, so a misheard "קואסיט" and "כועסת" both become "כשת".
SOUNDS = str.maketrans({"ק": "כ", "ט": "ת", "ע": "א", "ח": "כ", "ס": "ש", "ך": "כ", "ם": "מ",
                        "ן": "נ", "ף": "פ", "ץ": "צ"})


def _forms(word: str) -> set[str]:
    """A Hebrew word with and without its one-letter prefixes (ה, ו, ב, ...)."""
    out = {word}
    for p in PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= 2:
            out.add(word[len(p):])
    return out


def _skeleton(word: str) -> str:
    w = word.translate(SOUNDS)
    return w[:1] + "".join(c for c in w[1:] if c not in "אויה")


def _alike(a: str, b: str) -> float:
    r = difflib.SequenceMatcher(None, a, b).ratio()
    sa, sb = _skeleton(a), _skeleton(b)
    if len(sa) >= 2 and sa == sb:   # only identical sounds: "מספר" is not "מאושר"
        r = 1.0
    return r


def _norm(text: str) -> str:
    return " ".join(WORDS.findall((text or "").lower().replace("'", "")))


def _phrase_in(phrase: str, text: str, forms: set[str]) -> bool:
    """A dictionary phrase in the answer: a whole word (with or without a Hebrew
    prefix, or near-identical in sound) or, for several words, the words in order."""
    p = _norm(phrase)
    if not p:
        return False
    if " " in p:
        return (" " + p + " ") in (" " + text + " ")
    if p in forms:
        return True
    return len(p) > 3 and any(len(f) > 3 and _alike(f, p) >= 0.85 for f in forms)


def match_words(answer: str, groups: list[list[str]]) -> Optional[int]:
    """The group whose longest matching phrase is longest, or None."""
    text = _norm(answer)
    forms = {f for w in text.split() for f in _forms(w)}
    best, best_i = 0, None
    for i, phrases in enumerate(groups):
        for ph in phrases:
            n = len(_norm(ph))
            if n > best and _phrase_in(ph, text, forms):
                best, best_i = n, i
    return best_i


def match_option(answer: str, labels: list[str]) -> Optional[int]:
    """Which option the visitor most likely meant, from a tap label or misheard
    speech ("קואסיט" -> "כועסת", "בקצוף מספר שתיים" -> option 2), or None."""
    norm = [l.strip().lower() for l in labels]
    a = (answer or "").strip().lower().strip(".!?, ")
    if a in norm:
        return norm.index(a)
    words = [f for w in WORDS.findall(a) for f in _forms(w)]
    for w in words:                                      # a spoken number or ordinal
        for i, forms in NUMBERS.items():
            if i < len(labels) and w in forms:
                return i
    hits = [i for i, l in enumerate(norm) if l and not l.isdigit() and l in a]
    if hits:                                             # the label inside the sentence
        return max(hits, key=lambda i: len(norm[i]))
    best, best_i = 0.0, None                             # closest-sounding word
    for i, l in enumerate(norm):
        for lw in WORDS.findall(l):
            for w in words:
                r = _alike(w, lw)
                if r > best:
                    best, best_i = r, i
    return best_i if best >= 0.8 else None    # 0.6 took noise ("שומעים") for "נעים"


def match_expect(answer: str, expect: dict[str, list[str]]) -> str:
    """For a step without options: the "expect" key whose phrase matches (the
    longest wins), else "other"."""
    keys = list(expect)
    i = match_words(answer, [expect[k] for k in keys])
    return keys[i] if i is not None else "other"


def all_lines(steps: list[dict], lang: str) -> list[str]:
    """Everything a script can say in one language, to make the audio ahead."""
    out = [s["say"][lang] for s in steps] + [UNCLEAR[lang]]
    for s in steps:
        out += [r[lang] for r in s.get("reactions", [])]
        out += [r[lang] for r in s.get("react", {}).values()]
        out += [x["reaction"][lang] for x in s.get("extra", [])]
    return list(dict.fromkeys(out))


class ScriptRunner:
    """Runs one scripted experience. Same interface as brain.Brain for the dashboard."""

    def __init__(self, *, openai_key: str, eleven_key: str, play: Callable[[bytes], None],
                 flush: Callable[[], Awaitable[None]], tool: Callable[[str, dict], Any],
                 emit: Callable[[str, dict], None], speaking: Callable[[], bool],
                 synth: Callable[[str], Awaitable[bytes]],
                 voice: Callable[[], tuple[str, str]] = lambda: ("openai", "")) -> None:
        self.key, self.eleven_key = openai_key, eleven_key
        self._play, self._flush, self._tool, self._emit = play, flush, tool, emit
        self._speaking, self._synth, self._voice = speaking, synth, voice
        self.cfg: dict[str, Any] = {}
        self.engine = "script"
        self.running = self.paused = self.stuck = False
        self.history: list[tuple[str, str]] = []
        self.steps: list[dict] = FEELINGS
        self.index = 0
        self.step, self.step_title = 0, ""
        self.turns = 0
        self.turn = "off"                 # pepper | waiting | off
        self.waiting_since: Optional[float] = None
        self.reasked = False
        self.hearing = ""
        self.latency_ms: Optional[int] = None
        self.started_at = 0.0
        self.lang = "en"
        self.ears: Optional[eleven.ScribeEars] = None
        self._q: asyncio.Queue = asyncio.Queue()
        self._resume = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._warm_task: Optional[asyncio.Task] = None
        self._http = None                  # one kept-alive client: a new one cost ~1.5 s per line

    # ----------------------------------------------------------- lifecycle
    async def start(self, cfg: dict[str, Any], greet: bool = True) -> None:
        self.cfg = dict(cfg)
        if not self.eleven_key:
            raise RuntimeError("the scripted experience listens with ElevenLabs -- add an ElevenLabs key")
        self.steps = SCRIPTS.get(cfg.get("experience", ""), FEELINGS)
        language = cfg.get("language", "auto")
        if greet:
            self.index, self.turns = 0, 0
            self.lang = "he" if language == "he" else "en"
            self.started_at = time.time()
        self._q = asyncio.Queue()
        self._resume.set()
        self.ears = eleven.ScribeEars(self.eleven_key, language=language, on_partial=self._on_partial,
                                      on_final=self._on_final, on_error=self._lost)
        await self.ears.start()
        self.running, self.paused, self.stuck = True, False, False
        import httpx
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=REACT_TIMEOUT_S)
        self._warm_task = asyncio.create_task(self._warm(self.lang), name="script-warm")
        self._task = asyncio.create_task(self._run(), name="script-run")
        self._emit("ai", self.public())

    async def stop(self) -> None:
        self.running = False
        for t in (self._task, self._warm_task):
            if t is not None and not t.done():
                t.cancel()
        self._task = self._warm_task = None
        if self.ears is not None:
            await self.ears.stop()
            self.ears = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        self.turn, self.waiting_since, self.hearing = "off", None, ""
        self._emit("ai", self.public())

    async def update(self, cfg: dict[str, Any]) -> None:
        self.cfg.update(cfg)

    # ------------------------------------------------------------ the run
    async def _run(self) -> None:
        try:
            while self.index < len(self.steps):
                s = self.steps[self.index]
                self.step, self.step_title = self.index + 1, s["title"]
                self._drain()
                await self._ask(s)
                if s.get("answer", True):
                    await self._answer_and_react(s)
                self.index += 1
            self.turn = "waiting"
            self.waiting_since = time.monotonic()
            self._emit("log", {"level": "INFO", "msg": "script: finished"})
            self._emit("ai", self.public())
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("script stopped")
            self._lost("the script stopped: {}".format(exc))

    async def _ask(self, s: dict, again: bool = False) -> None:
        text = s["say"][self.lang]
        pcm = await self._synth(text)
        await self._resume.wait()
        name, args = s["screen"][self.lang]
        self._tool(name, args)                    # the screen changes as the question starts
        if s.get("gesture") and not again:
            self._tool("gesture", {"name": s["gesture"]})
        await self._say(text, pcm)

    async def _answer_and_react(self, s: dict) -> None:
        """Wait for an answer Pepper can place, then say its written reaction."""
        while True:
            kind, text, source = await self._wait_answer(s)
            if kind == "skip":
                return
            t0 = time.monotonic()
            reaction = self._reaction_for(s, text, source)
            if reaction is None:                  # not sure which option: ask for a tap
                await self._say_line(UNCLEAR[self.lang])
                continue
            line = await self._phrase(s, text, source, reaction)
            t_text = time.monotonic()
            await self._resume.wait()
            provider, voice_id = self._voice()
            if line != reaction and provider == "eleven" and self.eleven_key:
                await self._say_streamed(line, voice_id, t0, t_text)
            else:
                pcm = await self._synth(line)     # our own line: made ahead, plays at once
                self._log_latency(t0, t_text)
                await self._say(line, pcm)
            return

    async def _phrase(self, s: dict, answer: str, source: str, reaction: str) -> str:
        """The written reaction, re-worded by the AI so it sounds natural; the
        written line itself if the AI is slow or fails."""
        if self._http is None or not self.key:
            return reaction
        body = {"model": REACT_MODEL, "max_completion_tokens": 60, "temperature": 0.7,
                "messages": [
                    {"role": "system", "content": PHRASE_RULES + " " + PHRASE_LANG[self.lang]},
                    {"role": "user", "content": "You asked: {}\nThe visitor {}: {}\n"
                                                "Reaction to give: {}".format(
                                                    s["say"][self.lang],
                                                    "tapped" if source == "tap" else "answered",
                                                    self._understood(s, answer), reaction)}]}
        try:
            r = await self._http.post(CHAT_URL, headers={"Authorization": "Bearer " + self.key},
                                      json=body)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip().strip('"')
            if text:
                return text
        except Exception as exc:  # noqa: BLE001
            self._emit("log", {"level": "WARNING", "msg": "script: AI wording failed ({}); the "
                                                          "written line instead".format(exc)})
        return reaction

    def _understood(self, s: dict, answer: str) -> str:
        """The answer as the code understood it: the option's label, not the
        (possibly misheard) words."""
        if "reactions" in s:
            opts = s["screen"][self.lang][1]["options"]
            kind, i = self._place(s, answer)
            if kind == "option":
                return "{} {}".format(opts[i]["label"], opts[i].get("emoji", "")).strip()
            if kind == "extra":
                return s["extra"][i]["means"]
        return answer

    def _log_latency(self, t0: float, t_text: float) -> None:
        now = time.monotonic()
        self.latency_ms = int((now - t0) * 1000)
        self._emit("log", {"level": "INFO", "msg": "latency: {:.1f}s answer -> reaction sound "
                                                   "(AI {:.1f}s, voice {:.1f}s)".format(
                                                       now - t0, t_text - t0, now - t_text)})

    async def _say_streamed(self, text: str, voice_id: str, t0: float, t_text: float) -> None:
        """ElevenLabs audio plays as it is made: the first sound ~0.5-0.9 s after
        the text instead of after the whole clip (2-4.6 s, 2026-10-12)."""
        first = []

        def play(pcm: bytes) -> None:
            if not first:
                first.append(True)
                self._log_latency(t0, t_text)
            if not self.paused:
                self._play(pcm)

        self.turn = "pepper"
        self.history.append(("pepper", text))
        self._emit("chat", {"role": "pepper", "text": text})
        self._emit("ai", self.public())
        stream = eleven.VoiceStream(self.eleven_key, voice_id, play)
        try:
            await stream.text(text)
            await stream.finish()
            ok = await stream.wait()
        finally:
            await stream.close()
        if not ok and not first:
            self._emit("log", {"level": "WARNING", "msg": "script: streamed voice failed ({}); "
                                                          "trying again".format(stream.failed)})
            await self._say(text, await self._synth(text))
            return
        await asyncio.sleep(0.3)
        while self._speaking():
            await asyncio.sleep(0.1)

    def _place(self, s: dict, answer: str) -> tuple[Optional[str], int]:
        """("option", i), ("extra", j) or (None, -1): the step's word lists first
        (the longest phrase wins), then numbers, labels and sound-alikes."""
        name, args = s["screen"][self.lang]
        labels = [o["label"] for o in args["options"]]
        groups = s.get("words") or [FACE_WORDS.get(o.get("emoji", ""), []) for o in args["options"]]
        extras = s.get("extra", [])
        if answer.strip().lower() in [l.lower() for l in labels]:      # a tap
            return "option", [l.lower() for l in labels].index(answer.strip().lower())
        if all(l.isdigit() for l in labels):     # numbered options: a spoken number decides
            forms = [f for w in WORDS.findall(answer.lower()) for f in _forms(w)]
            for w in forms:
                for i, nums in NUMBERS.items():
                    if i < len(labels) and w in nums:
                        return "option", i
        k = match_words(answer, groups + [x["words"] for x in extras])
        if k is not None:
            return ("option", k) if k < len(groups) else ("extra", k - len(groups))
        i = match_option(answer, labels)
        return ("option", i) if i is not None else (None, -1)

    def _reaction_for(self, s: dict, answer: str, source: str) -> Optional[str]:
        if "reactions" in s:
            labels = [o["label"] for o in s["screen"][self.lang][1]["options"]]
            kind, i = self._place(s, answer)
            self._emit("log", {"level": "INFO", "msg": "script: {} '{}' -> {}".format(
                source, answer[:40], "option {} ({})".format(i + 1, labels[i]) if kind == "option"
                else "'{}' (not on the screen)".format(s["extra"][i]["means"]) if kind == "extra"
                else "not sure which option")})
            if kind is None:
                return None
            return s["reactions"][i][self.lang] if kind == "option" else s["extra"][i]["reaction"][self.lang]
        key = match_expect(answer, s.get("expect", {}))
        self._emit("log", {"level": "INFO", "msg": "script: {} '{}' -> {}".format(
            source, answer[:40], key)})
        return s["react"][key][self.lang]

    async def _wait_answer(self, s: dict) -> tuple[str, str, str]:
        self.reasked = False
        self._enter_waiting()
        while True:
            timeout = None if self.reasked else REASK_S
            try:
                item = await asyncio.wait_for(self._q.get(), timeout)
            except asyncio.TimeoutError:
                if self.paused or self.hearing:
                    continue
                self.reasked = True
                self._emit("log", {"level": "INFO", "msg": "turn: no answer, re-asking the question"})
                await self._ask(s, again=True)
                self._enter_waiting()
                continue
            kind = item[0]
            if kind == "repeat":
                self.reasked = True
                await self._ask(s, again=True)
                self._enter_waiting()
                continue
            if kind == "skip":
                return "skip", "", "operator"
            return item

    # ---------------------------------------------------------- speaking
    async def _say_line(self, text: str) -> None:
        await self._say(text, await self._synth(text))
        self._enter_waiting()

    async def _say(self, text: str, pcm: bytes) -> None:
        self.turn = "pepper"
        self.history.append(("pepper", text))
        self._emit("chat", {"role": "pepper", "text": text})
        self._emit("ai", self.public())
        self._play(pcm)
        await asyncio.sleep(min(0.5, len(pcm) / 48000.0))
        while self._speaking():
            await asyncio.sleep(0.1)

    async def _warm(self, lang: str) -> None:
        """Make every written line's audio now, and open the connection to
        OpenAI before the first reaction needs it."""
        try:
            await self._http.get("https://api.openai.com/v1/models/" + REACT_MODEL,
                                 headers={"Authorization": "Bearer " + self.key})
        except Exception:  # noqa: BLE001
            pass
        for text in all_lines(self.steps, lang):
            try:
                await self._synth(text)
            except Exception as exc:  # noqa: BLE001
                log.info("could not pre-make a line: %s", exc)
                return

    # ------------------------------------------------ the person's side
    def _enter_waiting(self) -> None:
        self.turn, self.waiting_since = "waiting", time.monotonic()
        if self.ears:
            self.ears.clear()
        self._emit("ai", self.public())

    def _drain(self) -> None:
        while not self._q.empty():
            self._q.get_nowait()

    def push_mic(self, pcm24: bytes) -> None:
        if self.running and not self.paused and self.turn == "waiting" and self.ears is not None:
            self.ears.push(pcm24)

    def _on_partial(self, text: str) -> None:
        self.hearing = text
        self._emit("hearing", {"text": text})

    async def _on_final(self, text: str, language: str) -> None:
        self.hearing = ""
        self._emit("hearing", {"text": ""})
        gap = self.ears.commit_gap_s if self.ears else None
        self._emit("log", {"level": "INFO", "msg": "ears: heard [{}] {}{}".format(
            language, text[:80], "" if gap is None else " ({:.1f}s after the last word)".format(gap))})
        if not real_answer(text):
            self._emit("heard", {"text": text, "why": "not an answer (noise or a filler)"})
            return
        if self.turn != "waiting" or self.paused:
            self._emit("heard", {"text": text, "why": "Pepper was not waiting for an answer"})
            return
        self._switch_language(text, language)
        self.turns += 1
        self.history.append(("person", text))
        self._emit("chat", {"role": "user", "text": text})
        self._q.put_nowait(("answer", text, "speech"))

    def _switch_language(self, text: str, language: str) -> None:
        if self.cfg.get("language", "auto") != "auto":
            return
        lang = "he" if (language == "he" or is_hebrew(text)) else "en" if language == "en" else self.lang
        if lang != self.lang:
            self.lang = lang
            self._emit("log", {"level": "INFO", "msg": "script: switching to {}".format(
                "Hebrew" if lang == "he" else "English")})
            self._warm_task = asyncio.create_task(self._warm(lang), name="script-warm")

    async def tap(self, label: str) -> None:
        if self.running and not self.paused:
            self.turns += 1
            self.history.append(("person", "[tap] " + label))
            self._q.put_nowait(("answer", label, "tap"))

    async def accept(self, text: str) -> None:
        if self.running and text:
            self.turns += 1
            self.history.append(("person", text))
            self._emit("chat", {"role": "user", "text": text})
            self._q.put_nowait(("answer", text, "operator"))

    async def repeat(self, auto: bool = False) -> None:
        if self.running:
            self._emit("log", {"level": "INFO", "msg": "turn: operator: repeat"})
            self._q.put_nowait(("repeat", "", "operator"))

    async def skip(self) -> None:
        if self.running:
            self._emit("log", {"level": "INFO", "msg": "turn: operator: skip to the next step"})
            self._q.put_nowait(("skip", "", "operator"))

    # ------------------------------------------------------------- control
    async def pause(self) -> None:
        if not self.running:
            return
        self.paused = True
        self._resume.clear()
        await self._flush()
        if self.ears:
            self.ears.clear()
        self._emit("ai", self.public())

    async def resume(self) -> None:
        if not self.running:
            return
        self.paused, self.stuck = False, False
        self._resume.set()
        if self.turn == "waiting":
            self._enter_waiting()
        self._emit("ai", self.public())

    async def cancel(self) -> None:
        await self._flush()

    async def note(self, text: str, tell: bool = True) -> None:
        if self.running:
            self.history.append(("pepper (operator)", text))

    def _lost(self, why: str) -> None:
        if self.running and not self.stuck:
            self.stuck = True
            self._emit("log", {"level": "ERROR", "msg": "ai: " + why})
            self._emit("ai", self.public())

    def public(self) -> dict:
        if not self.running:
            state = "off"
        elif self.paused:
            state = "paused"
        elif self.stuck:
            state = "stuck"
        elif self.turn == "waiting":
            state = "waiting"
        else:
            state = "speaking"
        return {"state": state, "running": self.running, "paused": self.paused, "stuck": self.stuck,
                "turn": self.turn, "engine": self.engine, "turns": self.turns,
                "step": self.step, "step_title": self.step_title, "steps": len(self.steps),
                "waiting_t": time.time() - (time.monotonic() - self.waiting_since)
                if self.turn == "waiting" and self.waiting_since else None,
                "expects": True, "reasked": self.reasked, "reask_s": REASK_S,
                "started_at": self.started_at if self.running else None,
                "latency_ms": self.latency_ms, "model": REACT_MODEL}
