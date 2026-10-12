"""Wizard-of-Oz speech: text the operator typed, spoken by Pepper.

Two voices:
  * "ai"     -- the conversation's own voice, played through the audio route:
               OpenAI text-to-speech with engine A, the ElevenLabs voice with
               engine B. Hebrew and English. Needs the network.
  * "pepper" -- Pepper's own NAOqi voice. English only (no Hebrew voice on
               this robot), but it runs on the robot and needs no internet.

The quick phrases are synthesised ahead of time and kept on disk, so in a demo
where the network has just died they still play at once. English text falls
back to Pepper's own voice when OpenAI does not answer.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from . import eleven

log = logging.getLogger("pepper.speech")

TTS_URL = "https://api.openai.com/v1/audio/speech"
TTS_MODEL = "gpt-4o-mini-tts"
TTS_TIMEOUT_S = 6.0
HEBREW = re.compile(r"[֐-׿]")

QUICK_PHRASES = [
    "Sorry, I didn't catch that. Can you say it again?",
    "Let me think about that for a second…",
    "Please look at my screen and choose one.",
    "Great choice!",
    "Thank you so much for talking with me!",
    "Hello! I am Pepper. Nice to meet you.",
    "שלום! אני פפר, נעים להכיר.",
    "סליחה, לא שמעתי. אפשר לחזור על זה?",
    "תסתכלו על המסך ובחרו אחד.",
    "תודה רבה ולהתראות!",
]


def is_hebrew(text: str) -> bool:
    return bool(HEBREW.search(text or ""))


class Speech:
    def __init__(self, cache_dir: Path, key: Optional[str], eleven_key: Optional[str] = None) -> None:
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.key = key
        self.eleven_key = eleven_key

    def _path(self, provider: str, voice: str, text: str) -> Path:
        model = eleven.TTS_MODEL if provider == "eleven" else TTS_MODEL
        h = hashlib.sha1("{}|{}|{}".format(model, voice, text).encode("utf-8")).hexdigest()
        return self.cache / (h[:20] + ".pcm")

    def cached(self, voice: str, text: str, provider: str = "openai") -> bool:
        return self._path(provider, voice, text).is_file()

    async def synth(self, text: str, voice: str, provider: str = "openai") -> bytes:
        """24 kHz mono PCM16 for `text`, from the cache, OpenAI or ElevenLabs."""
        path = self._path(provider, voice, text)
        if path.is_file():
            return path.read_bytes()
        if provider == "eleven":
            if not self.eleven_key:
                raise RuntimeError("no ElevenLabs key -- add one in the hub")
            pcm = await asyncio.wait_for(eleven.synth(self.eleven_key, voice, text), 20)
            self._store(path, pcm)
            return pcm
        if not self.key:
            raise RuntimeError("no OpenAI key -- add a GPT key in the hub")
        import httpx
        async with httpx.AsyncClient(timeout=TTS_TIMEOUT_S) as client:
            r = await client.post(TTS_URL, headers={"Authorization": "Bearer " + self.key},
                                  json={"model": TTS_MODEL, "voice": voice, "input": text,
                                        "response_format": "pcm",
                                        "instructions": "Speak warmly and clearly, like a friendly robot "
                                                        "talking to visitors. Natural pace."})
        if r.status_code != 200:
            raise RuntimeError("OpenAI speech failed: HTTP {} {}".format(r.status_code, r.text[:160]))
        pcm = r.content[: len(r.content) & ~1]
        self._store(path, pcm)
        return pcm

    @staticmethod
    def _store(path: Path, pcm: bytes) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(pcm)
        tmp.replace(path)

    async def warm(self, voice: str, phrases: list[str], provider: str = "openai") -> int:
        """Pre-make the quick phrases. Returns how many are ready."""
        ready = 0
        for p in phrases:
            try:
                await self.synth(p, voice, provider)
                ready += 1
            except Exception as exc:  # noqa: BLE001
                log.info("could not pre-make a quick phrase: %s", exc)
                break
            await asyncio.sleep(0)
        return ready
