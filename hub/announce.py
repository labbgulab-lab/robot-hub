"""The connection announcement (PLAN.md 8).

On connect the robot says a sentence out loud -- voice proof that the link is
real and not just a green dot.

Two of the four robots can do that from text alone (Furhat's `ActionSpeech`,
NAO's `ALTextToSpeech`). Both Reachys cannot: the Pollen daemon exposes no TTS
endpoint anywhere in its 98 paths, so their announcement is a pre-rendered WAV
uploaded to the robot. This module owns the naming of those files, because the
filename has to be derived from the *text* -- change the sentence in
config.toml and the old recording must not be played by mistake.

`hub/core.py` already owns the "connected, but could not speak" downgrade, so
nothing here decides policy. It only turns a failure into a sentence a human
can act on (13.5).
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Any, Optional

ANNOUNCE_TIMEOUT_S = 15.0
ASSETS_SUBDIR = ("assets", "announcements")


def _slug(text: str, limit: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "phrase"


def wav_filename(text: str) -> str:
    """A stable, collision-free name for one sentence.

    The hash is over the exact text, so editing the sentence changes the file
    and the daemon's idempotent upload check (`GET /api/media/sounds`) then
    correctly sees it as new rather than reusing the previous recording.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return "announce-{}-{}.wav".format(_slug(text), digest)


def announcements_dir(config: Any) -> Path:
    root = Path(getattr(config, "repo_root", Path.cwd()))
    return root.joinpath(*ASSETS_SUBDIR)


def wav_path(config: Any, text: str) -> Path:
    return announcements_dir(config) / wav_filename(text)


def missing_wav_message(path: Path) -> str:
    return (
        "the announcement recording {} has not been generated yet -- run "
        "`python tools/make_announcement_wavs.py` (the Reachy daemon has no "
        "text-to-speech of its own)".format(path.name)
    )


async def speak(adapter: Any, text: str,
                timeout_s: float = ANNOUNCE_TIMEOUT_S,
                name: Optional[str] = None) -> str:
    """Announce `text` on `adapter`. Returns "" on success, else a sentence.

    Never raises: the caller decides what a silent robot means.
    """
    who = name or getattr(adapter, "display_name", "") or "the robot"
    try:
        await asyncio.wait_for(adapter.announce(text), timeout_s)
        return ""
    except asyncio.TimeoutError:
        return ("{} did not finish speaking within {:.0f} s -- it may be "
                "connected but not producing audio".format(who, timeout_s))
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip() or type(exc).__name__
        return "{} could not speak: {}".format(who, detail)
