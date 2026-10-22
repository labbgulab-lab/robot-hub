"""Voice every interjection of the interrupt mode ahead of time.

    .venv\\Scripts\\python.exe tools\\group_warm_phrases.py [--eleven]

A session voices the missing ones in the background when it connects, but
200 phrases take a few minutes; run this once on a laptop (or after changing
characters) and interruptions start with their interjection from the first
one. OpenRouter voices by default (--voices openrouter,openai,gemini,elevenlabs
for others; ElevenLabs costs about 6,000 characters of credit).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from hub.group.conductor import (DEFAULT_CHARACTERS, OPENAI_VOICES, Session,  # noqa: E402
                                 tone_words)
from hub.group.services import GEMINI_VOICES, gemini_speech  # noqa: E402
from hub.group.phrases import Phrases  # noqa: E402
from hub.group.services import Services, openai_speech, openrouter_speech  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", default="openrouter",
                    help="comma list of openrouter, openai, gemini, elevenlabs")
    ap.add_argument("--langs", default="he,en")
    ap.add_argument("--seats", action="store_true",
                    help="the robots ticked Included on the group page (group.local.json), "
                         "with their own ElevenLabs voices, instead of the default characters")
    args = ap.parse_args()
    keys = json.loads((ROOT / "keys.local.json").read_text(encoding="utf-8"))["keys"]
    oa = next((k["key"] for k in keys if k["provider"] == "gpt"), "")
    el = next((k["key"] for k in keys if k["provider"] == "elevenlabs"), "")
    orr = next((k["key"] for k in keys if k["provider"] == "openrouter"), "")
    services = Services(oa, el, gemini_key=[k["key"] for k in keys if k["provider"] == "gemini"],
                        openrouter_key=orr)
    want = set(args.voices.split(","))
    gm = services.gemini_key
    by_key = {}
    characters = DEFAULT_CHARACTERS
    if args.seats:
        # The demo's own robots (2026-10-22: Max and Leo), voiced exactly as a
        # session voices them, so it finds them on disk ("el:<voice id>").
        cfg = json.loads((ROOT / "group.local.json").read_text(encoding="utf-8"))
        characters = [s for s in cfg.get("seats", []) if s.get("included") and s.get("voice_id")]
        want = {"elevenlabs"}
        print("seats:", ", ".join("{} ({})".format(s["character"], s["voice_id"]) for s in characters))
    for ch in characters:
        seat = {"character": ch["character"], "voice_id": ch["voice_id"], "persona": ch["persona"]}
        if "openrouter" in want and orr:
            by_key["or:{}:{}".format(OPENAI_VOICES[ch["character"]], ch["character"])] = seat
        if "openai" in want and oa:
            by_key["oa:{}:{}".format(OPENAI_VOICES[ch["character"]], ch["character"])] = seat
        if "gemini" in want and gm:
            by_key["gm:{}:{}".format(GEMINI_VOICES[ch["character"]], ch["character"])] = seat
        if "elevenlabs" in want and el:
            by_key["el:" + ch["voice_id"]] = seat

    async def synth(voice_key: str, text: str, tone: str) -> bytes:
        seat = by_key[voice_key]
        out = []
        if voice_key.startswith("el:"):
            async for c in services.speech(voice_key[3:], text, background=True):
                out.append(c)
        elif voice_key.startswith("or:"):
            async for c in openrouter_speech(services.http, orr, OPENAI_VOICES[seat["character"]],
                                             text, Session.voice_style(seat, tone)):
                out.append(c)
        elif voice_key.startswith("gm:"):
            await asyncio.sleep(3.5)        # Gemini's voice allows a few a minute per key
            key, model = services.gemini_tts()
            try:
                async for c in gemini_speech(services.http, key, GEMINI_VOICES[seat["character"]],
                                             text, tone_words(tone), model):
                    out.append(c)
            except Exception as exc:
                services.gemini_tts_refused(key, model, getattr(exc, "status", 0),
                                            getattr(exc, "body", ""))
                raise
        else:
            async for c in openai_speech(services.http, oa, OPENAI_VOICES[seat["character"]], text,
                                         Session.voice_style(seat, tone)):
                out.append(c)
        return b"".join(out)

    phrases = Phrases()
    total = 0
    for attempt in range(20):
        try:
            made = await phrases.warm([(k, v["character"]) for k, v in by_key.items()],
                                       args.langs.split(","), synth)
        except httpx.HTTPError as exc:
            print("network trouble ({}); again".format(type(exc).__name__))
            continue
        total += made
        langs = args.langs.split(",")
        missing = sum(len(phrases.texts(lang, v["character"])) - phrases.ready(k, lang, v["character"])
                      for k, v in by_key.items() for lang in langs)
        if not missing:
            break
        print("{} still missing; waiting out the per-minute limit".format(missing))
        await asyncio.sleep(30 if any(k.startswith("gm:") for k in by_key) else 2)
    for k in by_key:
        print("{:32} he {:2}  en {:2}".format(k, phrases.ready(k, "he", by_key[k]["character"]),
                                             phrases.ready(k, "en", by_key[k]["character"])))
    print("voiced now:", total)
    await services.close()


if __name__ == "__main__":
    asyncio.run(main())
