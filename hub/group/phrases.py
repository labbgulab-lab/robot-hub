"""Interjections: the instant first words of an interruption.

An interruption has to land while the person is still talking. Writing the
line (~1 s) and voicing it (first audio 0.6 s on ElevenLabs, 1.2-1.8 s on
OpenAI, measured 2026-10-21) is too slow for that alone, so the robot first
blurts a short ready-made phrase ("Wait, wait, wait!", "רגע רגע רגע!") from a
cache on disk, and the written line follows straight after it. The director
is told the interjection is added, so the line does not start with another.

Each phrase is voiced once per voice and kept in cache/group_phrases/ as raw
16 kHz int16, so a session starts with them ready (`warm` fills the gaps in
the background).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from ..config import REPO_ROOT

log = logging.getLogger("hub.group.phrases")

CACHE_DIR = REPO_ROOT / "cache" / "group_phrases"

PHRASES = {
    "en": {
        "oppose": ["Wait!", "No!", "Oh, come on!", "Hold on!", "Excuse me?!", "Whoa.", "Nope.",
                   "That's not true!", "Are you kidding me?", "Stop right there.", "No way.",
                   "Ugh.", "I don't think so.", "Wrong!", "Absolutely not."],
        "approve": ["Exactly!", "Finally, someone said it!", "Thank you!", "Yes!",
                    "Oh, I love this.", "Preach!", "That's what I've been saying!", "Totally!",
                    "Ooh, nice!"],
        "mock": ["Ha! Seriously?", "Oh, please.", "Here we go.", "Cute.", "Wow.",
                 "Oh, this is gonna be good.", "Sure.", "Pfft.", "Here comes the speech."],
        "correct": ["Actually...", "Not exactly.", "Technically...", "Small correction.",
                    "Well...", "That's not quite right.", "In fact..."],
        "cut": ["Okay...", "Can I just say something?", "Sorry...", "Let me stop you there.",
                "Quick question.", "Yeah, but...", "Hold that thought.", "Me first!",
                "One second."],
        "defend": ["Let them finish!", "Guys, let them talk!", "Shh.", "Be nice!"],
    },
    "he": {
        "oppose": ["רגע!", "לא!", "נו באמת!", "מה פתאום!", "סליחה?!", "וואו.", "ממש לא.",
                   "זה לא נכון!", "אתה רציני?", "עצור.", "אין מצב.", "אוף.", "לא נראה לי.",
                   "טעות!", "בשום אופן לא."],
        "approve": ["בדיוק!", "הנה, מישהו אמר את זה!", "תודה!", "כן!",
                    "וואי, איזה כיף לשמוע.", "נכון מאוד!", "זה בדיוק מה שאמרתי!", "לגמרי!",
                    "יאללה!"],
        "mock": ["חה! ברצינות?", "אוי, בחייך.", "הנה זה מתחיל.", "חמוד.", "מרשים מאוד.",
                 "אוי, זה הולך להיות טוב.", "כן, בטח.", "פחחח.", "הנה מגיע הנאום."],
        "correct": ["בעצם...", "לא בדיוק.", "טכנית...", "תיקון קטן.", "למעשה...",
                    "זה לא מדויק.", "האמת היא ש..."],
        "cut": ["אוקיי...", "אפשר להגיד משהו?", "סליחה...", "רגע, תן לי.", "שאלה קטנה.",
                "כן, אבל...", "תחזיק את המחשבה הזאת.", "אני קודם!", "שנייה אחת."],
        "defend": ["תנו לו לסיים!", "חבר'ה, תנו לדבר!", "שקט רגע.", "היי, בעדינות!"],
    },
}

# Each character's own ways of cutting in, on top of the shared bank.
CHARACTER = {
    "en": {
        "Noa": [("approve", "Ooh, I love it!"), ("cut", "What if..."),
                ("oppose", "No, but imagine...")],
        "Dor": [("oppose", "Give me a break."), ("mock", "Oh, not this again."),
                ("oppose", "Where's the proof?")],
        "Maya": [("correct", "Statistically, no."), ("correct", "Let me fix that."),
                 ("cut", "Point of order!")],
        "Eli": [("mock", "Is this about food?"), ("mock", "Ha! Good one."),
                ("cut", "Anyone else hungry?")],
        "Tamar": [("defend", "Let's listen a moment."), ("cut", "How do you feel about that?"),
                  ("approve", "That's beautiful.")],
    },
    "he": {
        "Noa": [("approve", "אני מתה על זה!"), ("cut", "ומה אם..."),
                ("oppose", "לא, אבל תדמיין...")],
        "Dor": [("oppose", "תעשה לי טובה."), ("mock", "שוב מתחילים."),
                ("oppose", "איפה ההוכחות?")],
        "Maya": [("correct", "סטטיסטית, לא."), ("correct", "אני מתקנת."),
                 ("cut", "הערה לסדר!")],
        "Eli": [("mock", "זה על אוכל?"), ("mock", "חה! טובה."),
                ("cut", "עוד מישהו רעב?")],
        "Tamar": [("defend", "רגע, בואו נקשיב."), ("cut", "איך אתה מרגיש עם זה?"),
                  ("approve", "זה כל כך יפה.")],
    },
}
STANCES = tuple(PHRASES["en"])
RECENT = 14          # interjections not reused within this many interruptions
TONE = {
    "oppose": "Loud, indignant, cutting someone off mid-sentence.",
    "approve": "Loud, delighted, cheering someone on.",
    "mock": "Sarcastic and amused, a short laugh in the voice.",
    "correct": "Know-it-all, cutting in to correct someone.",
    "cut": "Pushy, grabbing the floor, talking over someone.",
    "defend": "Firm and warm, telling the others to stop interrupting.",
}

Synth = Callable[[str, str, str], Awaitable[bytes]]   # (voice key, text, tone) -> pcm


def _path(voice_key: str, text: str) -> Path:
    h = hashlib.sha1("{}|{}".format(voice_key, text).encode("utf-8")).hexdigest()[:20]
    return CACHE_DIR / "{}.pcm".format(h)


class Phrases:
    def __init__(self) -> None:
        self._mem: dict[tuple[str, str], bytes] = {}
        self._last: dict[str, str] = {}
        self._recent: list[str] = []          # across robots: no echoing each other

    def get(self, voice_key: str, lang: str, stance: str,
            character: str = "") -> Optional[tuple[str, bytes]]:
        """(text, pcm) of a cached interjection: from the stance's bank and the
        character's own lines, the least recently used first (nothing heard in
        the last RECENT interruptions, by any robot, if anything else is left)."""
        options = list(PHRASES.get(lang, PHRASES["en"]).get(stance) or PHRASES["en"]["oppose"])
        options += [t for st, t in CHARACTER.get(lang, {}).get(character, []) if st == stance]
        random.shuffle(options)
        options.sort(key=lambda t: (t in self._recent, t == self._last.get(voice_key)))
        for text in options:
            pcm = self._mem.get((voice_key, text))
            if pcm is None:
                path = _path(voice_key, text)
                if path.is_file():
                    try:
                        pcm = path.read_bytes()
                        self._mem[(voice_key, text)] = pcm
                    except OSError:
                        pcm = None
            if pcm:
                self._last[voice_key] = text
                self._recent = (self._recent + [text])[-RECENT:]
                return text, pcm
        return None

    def audio(self, voice_key: str, text: str) -> bytes:
        """The recording of one opener in one voice, b"" when there is none."""
        pcm = self._mem.get((voice_key, text))
        if pcm is None:
            path = _path(voice_key, text)
            if path.is_file():
                try:
                    pcm = path.read_bytes()
                    self._mem[(voice_key, text)] = pcm
                except OSError:
                    pcm = b""
        return pcm or b""

    def used(self, text: str) -> None:
        self._recent = (self._recent + [text])[-RECENT:]

    def recent(self) -> list[str]:
        return list(self._recent)

    @staticmethod
    def texts(lang: str, character: str = "") -> list[tuple[str, str]]:
        """Every (stance, text) a robot playing `character` may say in `lang`."""
        out = [(st, t) for st, ts in PHRASES.get(lang, {}).items() for t in ts]
        return out + list(CHARACTER.get(lang, {}).get(character, []))

    def ready(self, voice_key: str, lang: str, character: str = "") -> int:
        return sum(1 for _st, t in self.texts(lang, character)
                   if (voice_key, t) in self._mem or _path(voice_key, t).is_file())

    async def warm(self, voices: list, langs: list[str], synth: Synth) -> int:
        """Voice every missing phrase; returns how many were made. `voices` are
        voice keys, or (voice key, character) for the character's own lines.
        The voices are voiced side by side (2026-10-22: two voices one after
        the other took minutes at Get ready); each voice's phrases in turn."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        async def one(item: Any) -> int:
            voice_key, character = item if isinstance(item, tuple) else (item, "")
            made = 0
            for lang in langs:
                for stance, text in self.texts(lang, character):
                    path = _path(voice_key, text)
                    if path.is_file():
                        continue
                    try:
                        pcm = await synth(voice_key, text, TONE[stance])
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        log.info("could not voice %r for %s: %s", text, voice_key, exc)
                        return made
                    if pcm:
                        path.write_bytes(pcm)
                        self._mem[(voice_key, text)] = pcm
                        made += 1
            return made
        return sum(await asyncio.gather(*(one(item) for item in voices)))
