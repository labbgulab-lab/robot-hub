"""What Pepper's chest screen shows, and the presentations it can show.

The tablet loads `/screen` from this laptop (ALTabletService.showWebview) and
polls `/screen/state`; every poll is also its heartbeat, which is how the
dashboard knows the screen is really connected. Taps come back as
`/screen/tap`. The dashboard draws the same state with the same renderer
(static/screen-render.js), so its preview is what people see.

Screen items:
    {"kind": "welcome"}
    {"kind": "blank"}
    {"kind": "message", "text": str, "emoji"?: str}
    {"kind": "choice", "question": str, "options": [{"label", "emoji"?, "image"?}]}
    {"kind": "slide", "deck": id, "index": n, "image": url}
    {"kind": "emoji_test", "cells": [[n, emoji], ...]}

Emoji live only in an item's own `emoji` field, never inside text, and only
from the allowed list: Pepper's tablet is an old Android WebView that shows
newer emoji as empty boxes. The candidates below are Unicode 6.0/6.1, the
oldest set; the emoji test card on the robot (the day before a demo) decides
which of them really work, and the broken ones are removed in the dashboard.
An experience "words only" gets no emoji at all.

Presentations live in data/presentations/<id>/ (deck.json + one image per
slide), on this laptop only.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Optional

HEARTBEAT_LOST_S = 4.0
MAX_SLIDE_BYTES = 15 * 1024 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".gif": "image/gif", ".webp": "image/webp"}
# Pictographs, dingbats, arrows-as-emoji, flags, keycaps, skin tones,
# variation selectors and the zero-width joiner that glues emoji together.
EMOJI = re.compile("[\\U0001F000-\\U0001FAFF\\u2190-\\u21FF\\u2300-\\u23FF\\u2460-\\u24FF"
                   "\\u25A0-\\u27BF\\u2900-\\u297F\\u2B00-\\u2BFF\\u3030\\u303D\\u3297\\u3299"
                   "\\uFE00-\\uFE0F\\u200D\\u20E3\\U000E0000-\\U000E007F]")


def no_emoji(text: Any) -> str:
    return re.sub(r"\s{2,}", " ", EMOJI.sub("", str(text or ""))).strip()


# Unicode 6.0/6.1, one code point each: the most likely to draw on an old Android.
EMOJI_CANDIDATES = [
    "😊", "😀", "😢", "😠", "😲", "😐",
    "😟", "😮", "😴",                                    # faces
    "👍", "👎", "👋", "👏", "👆", "🙌",  # hands
    "🐶", "🐱", "🐰", "🐼", "🐟", "🐢",
    "🐘", "🐦",                                                  # animals
    "🍕", "🍦", "🍎", "🍌", "🍰", "🍓",  # food
    "🏠", "🌊", "🌴", "🗻", "🌞", "🌙",
    "🌈", "⭐",                                                      # places, sky
    "🎈", "🎁", "⚽", "🎵", "📚", "🚗",
    "💬", "🔊",                                                  # things
]


def _bare(e: str) -> str:
    return (e or "").replace("️", "").replace("︎", "").strip()


def _clean(item: dict[str, Any], emoji_ok: Optional[set[str]]) -> dict[str, Any]:
    """Text without emoji; an emoji field kept only when it is on the allowed list."""
    item = dict(item)

    def pick(e: Any) -> Optional[str]:
        e = _bare(str(e or ""))
        return e if emoji_ok and e in emoji_ok else None

    if "emoji" in item:
        e = pick(item.pop("emoji"))
        if e:
            item["emoji"] = e
    for key in ("text", "question", "title"):
        if key in item:
            item[key] = no_emoji(item[key])
    if "options" in item:
        opts = []
        for o in item["options"]:
            o = {k: v for k, v in o.items() if k in ("label", "image")} | (
                {"emoji": pick(o.get("emoji"))} if pick(o.get("emoji")) else {})
            o["label"] = no_emoji(o.get("label"))
            if o["label"] or o.get("image") or o.get("emoji"):
                opts.append(o)
        item["options"] = opts
    return item


class Screen:
    def __init__(self, data_dir: Path) -> None:
        self.dir = data_dir / "presentations"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.version = 1
        self.item: dict[str, Any] = {"kind": "welcome"}
        self.by = "start"
        self.picked: Optional[str] = None
        self.last_poll = 0.0
        self.tablet_ip = ""
        self.tablet_agent = ""
        self.last_tap: Optional[dict] = None

    # ---- what is shown
    def show(self, item: dict[str, Any], by: str,
             emoji_ok: Optional[set[str]] = None) -> dict[str, Any]:
        """`emoji_ok`: the emoji this experience may use; None = none at all."""
        if item.get("kind") != "emoji_test":
            item = _clean(item, emoji_ok)
        self.item, self.by, self.picked = item, by, None
        self.version += 1
        return self.state()

    def state(self) -> dict[str, Any]:
        return {"v": self.version, "item": self.item, "by": self.by, "picked": self.picked}

    def heartbeat(self, ip: str, agent: str) -> None:
        self.last_poll, self.tablet_ip, self.tablet_agent = time.time(), ip, agent

    @property
    def connected(self) -> bool:
        return time.time() - self.last_poll < HEARTBEAT_LOST_S

    def health(self) -> dict[str, Any]:
        return {"connected": self.connected, "ip": self.tablet_ip,
                "seen_s": round(time.time() - self.last_poll, 1) if self.last_poll else None}

    def tap(self, version: int, index: int) -> Optional[str]:
        """The label tapped, or None when the tap was for an older screen."""
        if version != self.version or self.item.get("kind") != "choice":
            return None
        options = self.item.get("options") or []
        if not 0 <= index < len(options):
            return None
        self.picked = options[index]["label"]
        self.version += 1
        self.last_tap = {"label": self.picked, "t": time.time()}
        return self.picked

    # ---- presentations
    def decks(self) -> list[dict[str, Any]]:
        out = []
        for path in sorted(self.dir.glob("*/deck.json")):
            try:
                out.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        out.sort(key=lambda d: d.get("created", 0))
        return out

    def deck(self, deck_id: str) -> dict[str, Any]:
        path = self._deck_dir(deck_id) / "deck.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise KeyError(deck_id) from None

    def _deck_dir(self, deck_id: str) -> Path:
        if not re.fullmatch(r"[a-z0-9]{8,32}", deck_id or ""):
            raise KeyError(deck_id)
        return self.dir / deck_id

    def _save(self, deck: dict[str, Any]) -> None:
        d = self._deck_dir(deck["id"])
        tmp = d / "deck.json.tmp"
        tmp.write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(d / "deck.json")

    def new_deck(self, name: str) -> dict[str, Any]:
        deck = {"id": secrets.token_hex(6), "name": (name or "Presentation").strip()[:80],
                "created": time.time(), "slides": []}
        self._deck_dir(deck["id"]).mkdir(parents=True)
        self._save(deck)
        return deck

    def add_slide(self, deck_id: str, filename: str, data: bytes) -> dict[str, Any]:
        deck = self.deck(deck_id)
        ext = Path(filename or "").suffix.lower()
        if ext not in IMAGE_TYPES:
            raise ValueError("slides are images (png, jpg, gif, webp); PDFs are turned "
                             "into images by the dashboard first")
        if len(data) > MAX_SLIDE_BYTES:
            raise ValueError("that image is over 15 MB")
        n = len(deck["slides"]) + 1
        file = "{:03d}{}".format(n, ext)
        (self._deck_dir(deck_id) / file).write_bytes(data)
        title = Path(filename).stem.replace("_", " ").strip()[:60] or "Slide {}".format(n)
        deck["slides"].append({"file": file, "title": title})
        self._save(deck)
        return deck

    def delete_deck(self, deck_id: str) -> None:
        shutil.rmtree(self._deck_dir(deck_id), ignore_errors=True)

    def slide_path(self, deck_id: str, file: str) -> Path:
        if not re.fullmatch(r"\d{3}\.(png|jpg|jpeg|gif|webp)", file or ""):
            raise KeyError(file)
        path = self._deck_dir(deck_id) / file
        if not path.is_file():
            raise KeyError(file)
        return path

    def slide_item(self, deck_id: str, index: int) -> dict[str, Any]:
        deck = self.deck(deck_id)
        slides = deck["slides"]
        if not slides:
            raise KeyError("empty presentation")
        index = max(0, min(index, len(slides) - 1))
        s = slides[index]
        return {"kind": "slide", "deck": deck_id, "index": index, "count": len(slides),
                "title": s["title"], "image": "/screen/media/{}/{}".format(deck_id, s["file"])}

    def images_by_name(self) -> dict[str, str]:
        """Every uploaded slide, by its title, for the AI's picture choices."""
        out: dict[str, str] = {}
        for deck in self.decks():
            for s in deck["slides"]:
                out.setdefault(s["title"].lower(), "/screen/media/{}/{}".format(deck["id"], s["file"]))
        return out
