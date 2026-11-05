"""Readable transcripts of every Reachy conversation, in <data>/transcripts/.

Research participants talk to these robots, so a conversation is saved by
default (Settings > Save transcripts, `save_transcripts`, default on) and the
Reachy app shows a small "Saving transcript" mark while it happens. With the
switch off nothing is written.

Two sources, one plain-text file each:

- **Group** (several Reachys, hub/group/conductor.py): one file per
  connection, from the conductor's own transcript. The conductor starts a new
  session log (`_log_path`) for every new connection; a new path means a new
  file here. Named `group-<date>_<time>-<robots>.txt`.
- **Talk** (one Reachy running reachy_chat): one file per conversation, from
  the `conversation.*` / `transcript.*` / `turn.aborted` events the hub relays
  from the robot (hub/reachy_proxy.py). Named `talk-<date>_<time>-<robot>.txt`.

Every write rewrites the whole file from what is known so far, so an event
seen twice (two tabs relaying the same robot) changes nothing.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter

log = logging.getLogger("hub.transcripts")


def _stamp(when: float) -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(when))


def _safe(text: str) -> str:
    """A robot name as part of a file name (letters, digits, - and _)."""
    out = re.sub(r"[^A-Za-z0-9_-]+", "-", str(text or "")).strip("-")
    return out[:40] or "robot"


def _clock(seconds: Any) -> str:
    try:
        s = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return ""
    return "{}:{:02d}".format(s // 60, s % 60)


def _free(path: Path) -> Path:
    """A file name nobody has used yet (two conversations in one second)."""
    if not path.exists():
        return path
    n = 2
    while path.with_name("{}-{}{}".format(path.stem, n, path.suffix)).exists():
        n += 1
    return path.with_name("{}-{}{}".format(path.stem, n, path.suffix))


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".transcript-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass
class _Talk:
    conv_id: str
    robot: str
    started: float
    backend: str = ""
    lines: dict[tuple, dict] = field(default_factory=dict)   # (turn, role) -> line
    order: list[tuple] = field(default_factory=list)
    ended: Optional[float] = None
    reason: str = ""
    path: Optional[Path] = None
    written: str = ""


class TranscriptStore:
    """Writes the transcripts; asks `enabled()` before every write."""

    def __init__(self, folder: Callable[[], Path], enabled: Callable[[], bool],
                 publish: Optional[Callable[[dict], None]] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._folder = folder
        self._enabled = enabled
        self._publish = publish
        self._clock = clock
        # Group: the conductor's session-log path -> our file, per connection.
        self._group_key: Any = None
        self._group_path: Optional[Path] = None
        self._group_written = ""
        self._group_running = False
        # Talk: robot key -> the conversation it is in (or last was in).
        self._talk: dict[str, _Talk] = {}
        self._last_status: Any = None

    # ------------------------------------------------------------ common
    def enabled(self) -> bool:
        try:
            return bool(self._enabled())
        except Exception:  # noqa: BLE001
            return False

    def folder(self) -> Path:
        return Path(self._folder())

    def status(self) -> dict[str, Any]:
        """What the Reachy app shows: whether a conversation is being saved now."""
        active: list[dict[str, Any]] = []
        on = self.enabled()
        if on and self._group_running and self._group_path is not None:
            active.append({"kind": "group", "key": "group", "file": self._group_path.name})
        if on:
            for key, talk in self._talk.items():
                if talk.ended is None and talk.path is not None:
                    active.append({"kind": "talk", "key": key, "file": talk.path.name})
        return {"enabled": on, "dir": str(self.folder()), "active": active}

    def _changed(self) -> None:
        """Tell the open pages when the "Saving transcript" mark changes."""
        if self._publish is None:
            return
        now = self.status()
        sig = (now["enabled"], tuple((a["kind"], a["key"], a["file"]) for a in now["active"]))
        if sig == self._last_status:
            return
        self._last_status = sig
        try:
            self._publish({"type": "transcripts", **now})
        except Exception:  # noqa: BLE001
            log.debug("could not publish the transcripts status", exc_info=True)

    def _save(self, path: Path, text: str) -> bool:
        try:
            _write_atomic(path, text)
            return True
        except OSError as exc:
            log.warning("could not save the transcript %s: %s", path.name, exc)
            return False

    # ------------------------------------------------------------- group
    def attach_group(self, group: Any) -> None:
        """Watch the group conversation: every event it publishes passes here
        too (no queue of our own, so nothing changes for the conductor)."""
        original = group.publish

        def publish(event: dict) -> None:
            original(event)
            try:
                self.group_event(group, event)
            except Exception:  # noqa: BLE001  (a transcript never stops a demo)
                log.exception("group transcript")

        group.publish = publish

    def group_event(self, group: Any, event: dict) -> None:
        kind = event.get("type")
        if kind not in ("group.turn", "group.state", "group.status"):
            return
        running = bool(getattr(group, "running", False))
        if running != self._group_running:
            self._group_running = running
            self._changed()
        if kind == "group.status":
            return
        connection = getattr(group, "_log_path", None)
        if connection is None:
            return
        if connection != self._group_key:
            self._group_key = connection
            self._group_path = None
            self._group_written = ""
        transcript = list(getattr(group, "transcript", []) or [])
        if not any(t.get("kind") in ("robot", "human") for t in transcript if isinstance(t, dict)):
            return       # a connection where nobody said anything yet
        if not self.enabled():
            self._changed()
            return
        seats = self._group_seats(group)
        if self._group_path is None:
            names = "-".join(_safe(name) for _key, name, _label in seats[:6]) or "robots"
            # The connection's own time, from the conductor's session log name
            # (group-YYYYmmdd-HHMMSS.jsonl), else now.
            m = re.search(r"(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})", Path(str(connection)).stem)
            when = ("{}-{}-{}_{}-{}-{}".format(*m.groups()) if m else _stamp(self._clock()))
            self._group_path = _free(self.folder() / "group-{}-{}.txt".format(when, names))
        text = self.render_group(transcript, seats, self._group_path)
        if text != self._group_written and self._save(self._group_path, text):
            self._group_written = text
        self._changed()

    @staticmethod
    def _group_seats(group: Any) -> list[tuple[str, str, str]]:
        """(key, robot name, label) of the robots in this connection."""
        session = getattr(group, "session", None)
        seats = list(getattr(session, "seats", []) or []) if session is not None else []
        out = []
        for s in seats:
            if not isinstance(s, dict):
                continue
            key = str(s.get("key") or "")
            name = str(s.get("name") or key)
            if key.startswith("sim:"):
                name = "laptop" + key[4:]
            out.append((key, name, str(s.get("character") or "")))
        return out

    @staticmethod
    def render_group(transcript: list[dict], seats: list[tuple[str, str, str]],
                     path: Optional[Path] = None) -> str:
        names = {}
        for key, name, _label in seats:
            names[key] = name
            names[name] = name
        robots = ", ".join("{} ({})".format(label, name) if label and label != name else name
                           for _key, name, label in seats)
        head = ["Group conversation" + (" " + path.stem if path is not None else ""),
                "Robots: " + (robots or "-"), ""]
        lines = []
        for t in transcript:
            if not isinstance(t, dict):
                continue
            when = _clock(t.get("t")) if t.get("t") is not None else ""
            text = str(t.get("text") or "").strip()
            kind = t.get("kind")
            if kind == "note":
                lines.append("{:>6}  -- {}".format(when, text))
                continue
            if kind == "human":
                if not text:
                    continue      # still listening
                lines.append("{:>6}  People: {}".format(when, text))
                continue
            if not text:
                continue          # a line not written yet
            who = str(t.get("who") or "")
            robot = names.get(who, who)
            label = str(t.get("character") or "") or robot or "Robot"
            speaker = label if not robot or robot == label else "{} ({})".format(label, robot)
            tags = []
            if t.get("move"):
                tags.append(str(t["move"]))
            if t.get("cut"):
                tags.append("cut off")
            tag = " [{}]".format(", ".join(tags)) if tags else ""
            lines.append("{:>6}  {}{}: {}".format(when, speaker, tag, text))
        return "\n".join(head + lines) + "\n"

    # -------------------------------------------------------------- talk
    def talk_event(self, key: str, robot: str, event: dict) -> None:
        """One event relayed from a robot's reachy_chat."""
        name = event.get("event")
        if name == "state.snapshot":
            conv = event.get("conversation") or {}
            if isinstance(conv, dict) and conv.get("id"):
                talk = self._talk_for(key, robot, str(conv["id"]), str(conv.get("backend") or ""))
                for entry in event.get("transcript") or []:
                    if isinstance(entry, dict):
                        self._add(talk, entry.get("role"), entry.get("turn_id"),
                                  entry.get("text"), entry.get("reason"))
                self._write_talk(talk)
            else:
                # The robot is not in a conversation: one we followed is over.
                talk = self._talk.get(key)
                if talk is not None and talk.ended is None:
                    talk.ended = self._clock()
                    talk.reason = talk.reason or "ended"
                    self._write_talk(talk)
            return
        if name == "conversation.started":
            talk = self._talk_for(key, robot, str(event.get("id") or ""),
                                  str(event.get("backend") or ""))
            self._write_talk(talk)
            return
        talk = self._talk.get(key)
        if talk is None:
            return
        if name in ("transcript.user", "transcript.robot"):
            self._add(talk, "user" if name == "transcript.user" else "robot",
                      event.get("turn_id"), event.get("text"))
        elif name == "turn.aborted":
            self._add(talk, "aborted", event.get("turn_id"), "", event.get("reason"))
        elif name == "conversation.ended":
            if talk.ended is None:
                talk.ended = self._clock()
            talk.reason = str(event.get("reason") or "")
        else:
            return
        self._write_talk(talk)

    def _talk_for(self, key: str, robot: str, conv_id: str, backend: str) -> _Talk:
        talk = self._talk.get(key)
        if talk is None or talk.conv_id != conv_id:
            talk = _Talk(conv_id=conv_id, robot=robot or key, started=self._clock())
            self._talk[key] = talk
        if backend and not talk.backend:
            talk.backend = backend
        return talk

    @staticmethod
    def _add(talk: _Talk, role: Any, turn: Any, text: Any, reason: Any = None) -> None:
        if role not in ("user", "robot", "aborted"):
            return
        slot = (turn, role)
        if slot not in talk.lines:
            talk.order.append(slot)
        talk.lines[slot] = {"turn": turn, "role": role, "text": str(text or ""),
                            "reason": str(reason or "")}

    def _write_talk(self, talk: _Talk) -> None:
        if not self.enabled():
            self._changed()
            return
        if talk.path is None:
            talk.path = _free(self.folder() / "talk-{}-{}.txt".format(_stamp(talk.started),
                                                                     _safe(talk.robot)))
        text = self.render_talk(talk)
        if text != talk.written and self._save(talk.path, text):
            talk.written = text
        self._changed()

    @staticmethod
    def render_talk(talk: _Talk) -> str:
        out = ["Talk with {}".format(talk.robot),
               "Started {}".format(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(talk.started))),
               "Conversation {}".format(talk.conv_id)]
        if talk.backend:
            out.append(talk.backend)
        out.append("")
        for slot in talk.order:
            line = talk.lines[slot]
            turn = line["turn"]
            if line["role"] == "aborted":
                out.append("[turn {}] -- aborted{}".format(
                    turn, " ({})".format(line["reason"]) if line["reason"] else ""))
                continue
            who = talk.robot if line["role"] == "robot" else "Person"
            out.append("[turn {}] {}: {}".format(turn, who, line["text"] or "(no transcript)"))
        if talk.ended is not None:
            out.append("")
            out.append("Ended {}{}".format(
                time.strftime("%H:%M:%S", time.localtime(talk.ended)),
                " ({})".format(talk.reason) if talk.reason else ""))
        return "\n".join(out) + "\n"


def make_router(store: TranscriptStore) -> APIRouter:
    router = APIRouter()

    @router.get("/api/transcripts/current")
    async def get_current() -> dict[str, Any]:
        """{enabled, dir, active: [{kind, key, file}]}: the "Saving transcript" mark."""
        return store.status()

    return router
