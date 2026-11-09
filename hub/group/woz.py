"""The table's Wizard of Oz (2026-11-09): the operator fires pre-recorded cues
(a line with a gesture) at the robots, with no AI and no internet.

Until now the only Wizard of Oz lived inside one robot's own app (reachy_chat's
show player); a group conversation stops that app on every robot, so a Choir
demo had no safety net when the AI or the network failed. Here the hub plays
the lab's script through the same robot links the conversation uses:

  * the script is the reachy_chat checkout's show/cues.json (+ manifest.json
    and show/audio/*.wav, 24 kHz, resampled to the robots' 16 kHz here);
  * a cue whose WAV is missing, or whose manifest hash/text no longer matches
    the script, is voiced once with Gemini (the script's voice, model and
    style) and kept in <data>/woz_cache; the student app has no show/audio;
  * a cue that has audio plays with no network at all;
  * targets are what the conversation would have as speakers: a Choir is one
    target ("all"), otherwise each talking group is one and each robot in no
    talking group is its own; a group plays as one voice (GroupLink);
  * with a conversation running, a cue cuts the line being said, is written
    in the transcript as said by that speaker, and the conversation goes on;
  * one floor (2026-11-09 review): a cue with a voice holds it from the moment
    it is fired (before anything is cut) until it has played or is stopped,
    and no conversation line sends audio while it is held (Session.wait_floor,
    Conversation.speak); Stop also cancels a cue that is still being started;
  * the robots have no dances: a dance cue plays a stand-in emotion and says
    so (motion_of); Connect brings back only the robots that are missing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
import wave
from pathlib import Path
from typing import Any, Optional

from .. import config as hub_config
from . import moves
from .conductor import (DEFAULT_LOUDNESS, PLAY_LATENCY_S, REACHY, SEND_PIECE_BYTES,
                        AUDIO_LEAD_S, Line, clean_groups, loud, plan_groups, whole_table)
from .ears import rms_blocks
from .robots import GROUP_START_LEAD_S, GroupLink, SAMPLE_RATE
from .services import ServiceError, gemini_speech, resample_24k_16k

log = logging.getLogger("hub.group.woz")

SAY_MAX_CHARS = 600
VOICE_WAIT_S = 30.0          # a typed line's voice must arrive within this
SYNTH_WAIT_S = 90.0          # one cue's voice (Gemini)
CUT_WAIT_S = 5.0             # a conversation line gets this long to let go (it
                             # lets go at once; this is only the safety limit)
START_HOLD_S = 15.0          # the floor while a cue is being started (_cut's limits)
FLOOR_SPARE_S = 5.0          # the floor outlasts a cue's own length by this, no more
DEFAULT_VOICE = "Aoede"      # reachy_chat conversation.GEMINI_VOICE (build_show.py)
DEFAULT_TTS_MODEL = "gemini-3.1-flash-tts-preview"
NO_DANCE = "no dances on the robots"
# The robots have no dance library, so a dance cue plays the nearest move the
# emotions library has (2026-11-09 review): a nod is a nod, any other dance is
# the library's own dance1. A stand-in the robots lack makes the cue not ready.
DANCE_STAND_INS = {"yeah_nod": "yes1"}
DANCE_STAND_IN = "dance1"
STOP_HOLD_S = 4.0            # Stop keeps the floor while the robots are cleared


class _Stopped(Exception):
    """Stop was pressed while a cue was being started."""


class WozError(Exception):
    """A refusal with the contract's code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def text_hash(text: str, voice: str, style: str) -> str:
    """The manifest's hash of a cue (reachy_chat tools/build_show.py): changes
    when the line, the voice or the delivery style changes."""
    return hashlib.sha256("{}\x00{}\x00{}".format(voice, style, text).encode("utf-8")).hexdigest()[:16]


def wav_to_16k(path: Path) -> bytes:
    """A WAV file -> int16 mono 16 kHz bytes (24 kHz is what the lab's script
    is built at; anything else is interpolated)."""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
        frames = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError("{} is not 16-bit audio".format(path.name))
    x = np.frombuffer(frames[: len(frames) - len(frames) % (2 * channels)], dtype="<i2")
    if channels > 1:
        x = x.reshape(-1, channels)[:, 0]
    data = x.astype("<i2").tobytes()
    if rate == SAMPLE_RATE:
        return data
    if rate == 24000:
        return resample_24k_16k(data, b"")[0]
    f = x.astype(np.float32)
    n = int(round(f.size * SAMPLE_RATE / rate))
    if n <= 0:
        return b""
    y = np.interp(np.linspace(0, f.size - 1, n), np.arange(f.size), f)
    return np.clip(y, -32768, 32767).astype("<i2").tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    """int16 mono 16 kHz bytes -> a WAV file (written whole, then renamed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    tmp.replace(path)


class TableWoz:
    def __init__(self, manager: Any, show_dir: Optional[Path] = None,
                 cache_dir: Optional[Path] = None) -> None:
        self.m = manager
        self._show_dir = show_dir            # tests; normally from reachy_chat_path
        self._cache_dir = cache_dir
        self._script: Optional[dict] = None
        self._script_sig: Any = None
        # cue id -> (file, (mtime, size), 16 kHz audio): a rebuilt WAV is read again
        self._pcm: dict[str, tuple[Path, Optional[tuple], bytes]] = {}
        self._prep: Optional[asyncio.Task] = None
        self._task: Optional[asyncio.Task] = None        # the cue being played
        self._moves: set = set()                          # motion-only cues being sent
        self._playing: Optional[dict] = None
        # Who holds the floor -> until when (monotonic): a cue with a voice,
        # from the moment it is fired until it has played (never longer than
        # its own length + FLOOR_SPARE_S, so a stuck robot cannot keep it).
        self._floor: dict[object, float] = {}
        self._gen = 0                                     # bumped by Stop
        self._last_target: Optional[str] = None
        self._lock = asyncio.Lock()
        self.last_error = ""                              # why audio could not be made

    # ------------------------------------------------------------ script
    def show_dir(self) -> Optional[Path]:
        if self._show_dir is not None:
            return self._show_dir
        config = getattr(self.m.hub, "config", None)
        try:
            root = config.path(REACHY, "reachy_chat_path") if config is not None else None
        except Exception:  # noqa: BLE001
            root = None
        if root is None or not (root / "show").is_dir():
            return None
        return root / "show"

    def cache_dir(self) -> Path:
        return self._cache_dir if self._cache_dir is not None else hub_config.DATA_DIR / "woz_cache"

    def load_script(self) -> dict:
        """{"voice","model","style","sections","cues","manifest","error"}; read
        again only when the script or its manifest changed on disk."""
        show = self.show_dir()
        empty = {"voice": "", "model": DEFAULT_TTS_MODEL, "style": "", "sections": [],
                 "cues": {}, "manifest": {}, "error": ""}
        if show is None:
            return {**empty, "error": "no cue script: set reachy_chat_path in config.toml to "
                                      "your reachy_chat checkout (it has show/cues.json)"}
        cues_path, manifest_path = show / "cues.json", show / "manifest.json"
        try:
            sig = (cues_path.stat().st_mtime_ns,
                   manifest_path.stat().st_mtime_ns if manifest_path.is_file() else 0)
        except OSError:
            return {**empty, "error": "no cue script at {}".format(cues_path.name)}
        if self._script is not None and self._script_sig == (show, sig):
            return self._script
        try:
            data = json.loads(cues_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as exc:
            return {**empty, "error": "the cue script could not be read: {}".format(exc)}
        manifest: dict = {}
        if manifest_path.is_file():
            try:
                manifest = (json.loads(manifest_path.read_text(encoding="utf-8")).get("cues")
                            or {})
            except (OSError, ValueError, AttributeError):
                log.warning("woz: manifest unreadable; durations and audio come from the cache")
        # Hashed exactly as reachy_chat tools/build_show.py does (its default
        # voice, the text as written), or the lab's WAVs would never match.
        voice = data.get("voice", DEFAULT_VOICE)
        style = data.get("style", "")
        sections, cues = [], {}
        for section in data.get("sections") or []:
            if not isinstance(section, dict):
                continue
            entries = []
            for cue in section.get("cues") or []:
                if not isinstance(cue, dict) or not cue.get("id"):
                    continue
                cid = str(cue["id"])
                motion = cue.get("motion") if isinstance(cue.get("motion"), dict) else None
                raw = cue.get("text") or ""
                text = str(raw).strip()
                item = {"id": cid, "hotkey": cue.get("hotkey"),
                        "label": str(cue.get("label") or cid), "text": text, "raw": raw,
                        "motion": motion, "hash": text_hash(raw, voice, style) if text else ""}
                cues[cid] = item
                entries.append(item)
            sections.append({"id": str(section.get("id") or ""),
                             "title": str(section.get("title") or ""), "cues": entries})
        script = {"voice": str(voice or ""), "style": str(style or ""), "sections": sections,
                  "cues": cues,
                  "model": str(data.get("tts_model") or DEFAULT_TTS_MODEL),
                  "manifest": manifest, "error": ""}
        self._script, self._script_sig = script, (show, sig)
        return script

    def audio_file(self, cue: dict, script: Optional[dict] = None) -> Optional[Path]:
        """The WAV a cue plays: the lab's own when the manifest vouches for it
        (same hash and text), else the one made here; None when there is none."""
        script = script or self.load_script()
        show = self.show_dir()
        entry = script["manifest"].get(cue["id"])
        if show is not None and isinstance(entry, dict) and entry.get("hash") == cue["hash"] \
                and entry.get("text") == cue["raw"]:
            path = show / str(entry.get("file") or "audio/{}.wav".format(cue["id"]))
            try:
                path.resolve().relative_to(show.resolve())
            except ValueError:
                path = None         # a manifest pointing outside the show folder
            if path is not None and path.is_file():
                return path
        made = self.cache_dir() / "{}-{}.wav".format(cue["id"], cue["hash"])
        return made if made.is_file() else None

    def is_ready(self, cue: dict, script: dict) -> bool:
        """It can be fired now: its audio is here, or (no words) its motion
        is one the robots can do."""
        if not cue["text"]:
            return self.motion_of(cue)[0] is not None
        return self.audio_file(cue, script) is not None

    @staticmethod
    def _file_sig(path: Optional[Path]) -> Optional[tuple]:
        try:
            st = path.stat() if path is not None else None
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size) if st is not None else None

    def _cached(self, cue: dict, path: Optional[Path]) -> Optional[bytes]:
        """The audio read before, if it is still the same file (a rebuilt show
        writes show/audio/<id>.wav again at the same path)."""
        got = self._pcm.get(cue["id"])
        if got is None or path is None or got[0] != path or got[1] != self._file_sig(path):
            return None
        return got[2]

    def duration_of(self, cue: dict, script: dict) -> Optional[float]:
        if not cue["text"]:
            return 0.0
        entry = script["manifest"].get(cue["id"]) or {}
        got = self._cached(cue, self.audio_file(cue, script))
        if got is not None:
            return round(len(got) / (2.0 * SAMPLE_RATE), 2)
        if entry.get("hash") == cue["hash"] and isinstance(entry.get("duration_s"), (int, float)):
            return float(entry["duration_s"])
        return None

    async def pcm_of(self, cue: dict) -> bytes:
        """A ready cue's audio, 16 kHz (kept in memory after the first read)."""
        script = self.load_script()
        path = self.audio_file(cue, script)
        if path is None:
            return b""
        got = self._cached(cue, path)
        if got is not None:
            return got
        sig = self._file_sig(path)
        pcm = await asyncio.to_thread(wav_to_16k, path)
        self._pcm[cue["id"]] = (path, sig, pcm)
        return pcm

    # --------------------------------------------------------- preparing
    def prepare_soon(self) -> None:
        """Voice what is missing and load every cue's audio, in the background
        (at connect and at Get ready; never while firing)."""
        if self._prep is not None and not self._prep.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._prep = asyncio.ensure_future(self._prepare())
        self.publish_state()

    async def _prepare(self) -> None:
        try:
            script = self.load_script()
            for cue in script["cues"].values():
                if not cue["text"] or self.audio_file(cue, script) is not None:
                    continue
                try:
                    pcm = await self.synthesize(cue, script)
                    await asyncio.to_thread(
                        write_wav, self.cache_dir() / "{}-{}.wav".format(cue["id"], cue["hash"]),
                        pcm)
                    self.last_error = ""
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    # Offline or no key: the cues that have audio still fire.
                    self.last_error = "could not voice {!r}: {}".format(cue["id"], exc)
                    log.info("woz: %s", self.last_error)
                    if isinstance(exc, WozError) or not isinstance(exc, ServiceError):
                        break       # nothing else will work now either
                self.publish_state()
            for cue in script["cues"].values():
                if cue["text"] and self.audio_file(cue, script) is not None:
                    try:
                        await self.pcm_of(cue)
                    except Exception as exc:  # noqa: BLE001
                        log.info("woz: %s: %s", cue["id"], exc)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("woz: preparing the cues failed")
        finally:
            self._prep = None
            self.publish_state()

    async def synthesize(self, cue: dict, script: dict) -> bytes:
        """One cue's voice from Gemini: the script's voice, model and style."""
        services = self.m.shared_services()
        prompt = "{}\n\n{}".format(script["style"], cue["text"]) if script["style"] else cue["text"]
        last: Optional[Exception] = None
        for _attempt in range(2):
            key, default_model = services.gemini_tts()
            if not key:
                raise WozError("NO_AUDIO", "no Gemini key to voice it")
            model = script["model"] or default_model

            async def collect() -> bytes:
                chunks = []
                async for c in gemini_speech(services.http, key, script["voice"] or "Aoede",
                                             prompt, "", model):
                    chunks.append(c)
                return b"".join(chunks)

            try:
                pcm = await asyncio.wait_for(collect(), SYNTH_WAIT_S)
            except ServiceError as exc:
                services.gemini_tts_refused(key, model, exc.status, exc.body)
                services.gemini_refused(key, exc.status)
                last = exc
                continue
            if not pcm:
                raise WozError("NO_AUDIO", "the voice sent no audio")
            return pcm
        raise last or WozError("NO_AUDIO", "the voice failed")

    # ----------------------------------------------------------- targets
    def _seats(self) -> list[dict]:
        """A conversation's (or Get ready's) own seats; a Wizard of Oz
        connection's are every included robot, so one that did not join or
        dropped out stays in the targets, not connected, and the page offers
        Connect for it (connect() opens the robots again)."""
        session = self.m.session
        if session is not None and (self.m.running or not getattr(session, "lite", False)):
            return list(session.seats)
        # The union: the robots this connection holds links to, plus included
        # robots it does not have yet. m.seats() alone drops a robot whose
        # health probe failed once (registry ERROR) although its audio link is
        # fine, and a Choir then plays without it (review, 2026-11-09).
        held = list(session.seats) if session is not None else []
        keys = {s["key"] for s in held}
        return held + [s for s in self.m.seats() if s.get("included") and s["key"] not in keys]

    def plan(self) -> dict:
        """The targets for the seats now: {"targets": [{id, name, members,
        seat}], "choir": bool, "mirror": {...}, "all": [keys], "names": {...}}."""
        seats = self._seats()
        groups = clean_groups(self.m.cfg["settings"].get("groups"))
        speakers, together, mirror = plan_groups(seats, groups)
        order = [s["key"] for s in seats]
        names = {s["key"]: s.get("name") or s["key"] for s in seats}
        listed = {k for g in groups if not whole_table(g) for k in g.get("members", [])}
        choir = any(whole_table(g) and g.get("talk", True)
                    and len([k for k in order if k not in listed]) >= 2 for g in groups)
        targets = []
        if choir and order:
            lead = next((sp for sp in speakers if sp["key"] in together
                         and set(together[sp["key"]]) >= {k for k in order if k not in listed}),
                        None) or (speakers[0] if speakers else seats[0])
            targets.append({"id": "all", "name": lead.get("group_name") or "All robots",
                            "members": list(order), "seat": lead})
        else:
            for sp in speakers:
                members = list(together.get(sp["key"], [sp["key"]]))
                name = sp.get("group_name") or (names[sp["key"]] if len(members) == 1 else
                                                " + ".join(names.get(k, k) for k in members))
                targets.append({"id": sp["key"], "name": name, "members": members, "seat": sp})
        return {"targets": targets, "choir": choir, "mirror": mirror, "names": names,
                "all": list(order), "seats": seats, "speakers": speakers}

    def alive(self) -> list[str]:
        session = self.m.session
        if session is None:
            return []
        return [k for k, link in session.links.items() if getattr(link, "connected", True)]

    def missing(self) -> list[str]:
        """Included robots with no live link (dropped out, or never joined)."""
        try:
            alive = set(self.alive())
            return [s["key"] for s in self.m.seats() if s.get("included")
                    and s["key"] not in alive]
        except Exception:  # noqa: BLE001 - a half-built seat list must not break the page
            log.exception("woz: listing the missing robots failed")
            return []

    def choose(self, plan: dict, wanted: str) -> dict:
        targets = plan["targets"]
        wanted = str(wanted or "auto")
        if wanted == "all":
            pick = next((t for t in targets if t["id"] == "all"), None)
            if pick is None and plan["all"]:
                lead = plan["seats"][0]
                pick = {"id": "all", "name": "All robots", "members": list(plan["all"]),
                        "seat": lead}
        elif wanted in ("auto", "random"):
            if plan["choir"] and targets:
                pick = targets[0]
            elif targets:
                # Only targets that can play it now (a robot off the WiFi
                # stays in the seats until the next connect).
                alive = set(self.alive())
                live = [t for t in targets if alive & set(t["members"])] or targets
                pool = [t for t in live if t["id"] != self._last_target] or live
                pick = random.choice(pool)
            else:
                pick = None
        else:
            pick = next((t for t in targets if t["id"] == wanted), None)
        if pick is None:
            raise WozError("NO_TARGET", "no such target: {}".format(wanted))
        return pick

    # ------------------------------------------------------------- state
    def active(self) -> bool:
        """A cue with a voice holds the floor: no conversation line may send
        audio (Session.wait_floor, Conversation.speak)."""
        now = time.monotonic()
        return any(until > now for until in self._floor.values())

    def sending(self) -> bool:
        """A cue's audio is going to the robots now."""
        return self._task is not None and not self._task.done()

    @staticmethod
    def motion_of(cue: dict) -> tuple[Optional[dict], str]:
        """(the motion the robots can do, a note): the robots have no dance
        library (moves.DANCES_ON_ROBOTS), and reachy_chat's own show player
        sends dances to the same player, which ignores them; so a dance plays
        its stand-in emotion (DANCE_STAND_INS), or is left out, and the note
        says which rather than pretending."""
        motion = cue.get("motion")
        if motion and motion.get("type") == "dance" and not moves.DANCES_ON_ROBOTS:
            name = DANCE_STAND_INS.get(str(motion.get("name") or ""), DANCE_STAND_IN)
            if name in moves.EMOTIONS:
                return ({"type": "emotion", "name": name},
                        "played as {} ({})".format(name, NO_DANCE))
            return None, NO_DANCE
        return motion, ""

    def state(self) -> dict:
        script = self.load_script()
        sections = []
        for section in script["sections"]:
            cues = []
            for c in section["cues"]:
                item = {"id": c["id"], "hotkey": c["hotkey"], "label": c["label"],
                        "text": c["text"], "motion": c["motion"],
                        "duration_s": self.duration_of(c, script),
                        "ready": self.is_ready(c, script)}
                note = self.motion_of(c)[1]
                if note:
                    item["note"] = note
                cues.append(item)
            sections.append({"id": section["id"], "title": section["title"], "cues": cues})
        try:
            plan = self.plan()
        except Exception:  # noqa: BLE001 - a half-built seat list must not break the page
            log.exception("woz: planning the targets failed")
            plan = {"targets": [], "choir": False}
        body = {"ok": True, "script": {"sections": sections},
                "targets": [{"id": t["id"], "name": t["name"], "members": t["members"]}
                            for t in plan["targets"]],
                "choir": plan["choir"], "connected": self.alive(),
                "missing": self.missing(),
                "preparing": self._prep is not None and not self._prep.done(),
                "playing": dict(self._playing) if self._playing else None}
        if script["error"]:
            body["error"] = script["error"]
        elif self.last_error:
            body["note"] = self.last_error
        return body

    def publish_state(self) -> None:
        try:
            self.m.publish({"type": "group.woz", "state": self.state()})
        except Exception:  # noqa: BLE001
            log.exception("woz: could not publish the state")

    def _publish_playing(self) -> None:
        self.m.publish({"type": "group.woz",
                        "playing": dict(self._playing) if self._playing else None})

    def halt(self) -> list:
        """Everything the Wizard of Oz has going ends now, at once: the cue
        playing, motion-only cues, and a fire or a typed line still being
        started (it sees the generation change and gives up). The floor is
        free. Returns the tasks that were cancelled (Stop waits for them)."""
        self._gen += 1
        tasks = [t for t in [self._task, *self._moves] if t is not None and not t.done()]
        self._task = None
        for task in tasks:
            task.cancel()
        self._floor.clear()
        if self._playing is not None:
            self._playing = None
            self._publish_playing()
        return tasks

    def busy(self) -> bool:
        """Something is playing or being started."""
        return bool(self._floor) or self._playing is not None or self.sending() or any(
            not t.done() for t in self._moves)

    def session_closed(self) -> None:
        """The robots were released: whatever was playing is over."""
        self.halt()
        self.publish_state()

    # ----------------------------------------------------------- connect
    async def connect(self) -> dict:
        """Connect the robots for the Wizard of Oz, without the AI: nothing but
        their links. Runs again to bring back robots that dropped out or did
        not join: on a Wizard of Oz connection only those are opened again,
        the others keep playing; a conversation's, or one Get ready opened,
        is never touched for one robot (they are named in "missing")."""
        m = self.m
        async with m._lock:
            session = m.session
            if m.running and session is not None:
                pass            # the conversation has them
            else:
                connecting = m._connecting is not None and not m._connecting.done()
                gone = False
                if session is not None and not connecting:
                    linked = {k for k, l in session.links.items()
                              if getattr(l, "connected", True)}
                    dead = [s for s in m.seats() if s.get("included") and s["key"] not in linked]
                    if not linked:
                        gone = True             # nothing left to keep: open them again
                    elif dead and getattr(session, "lite", False):
                        try:
                            await session.open_lite(dead)
                        except Exception:  # noqa: BLE001 - the robots that are on stay on
                            log.exception("woz: bringing back %s failed",
                                          ", ".join(s["key"] for s in dead))
                if gone:
                    await m._disconnect()       # lost the WiFi: open them again
                    session = None
                if session is None:
                    seats = [s for s in m.seats() if s.get("included")]
                    if not seats:
                        raise WozError("NO_ROBOTS", "no robot is included: tick a Reachy first")
                    why = await m.open_lite(seats)
                    if why is not None:
                        raise WozError("NO_ROBOTS", "no robot could be reached: {}".format(why))
        alive = self.alive()
        if not alive:
            raise WozError("NO_ROBOTS", "no robot is connected")
        self.prepare_soon()
        self.publish_state()
        # Every included robot that has no live link: dropped out, or never
        # joined (the session's own seats leave those out).
        names = {s["key"]: s.get("name") or s["key"] for s in m.seats()}
        missing = [names.get(k, k) for k in self.missing()]
        return {"ok": True, "connected": alive, "missing": missing}

    # ------------------------------------------------------------ firing
    def _session(self) -> Any:
        session = self.m.session
        if session is None:
            raise WozError("NOT_CONNECTED", "the robots are not connected: press Connect")
        if self.m._connecting is not None and not self.m._connecting.done():
            raise WozError("NOT_CONNECTED", "the robots are still connecting")
        return session

    def _links_of(self, session: Any, target: dict, plan: dict) -> tuple[list, list[str]]:
        """(live links of the target, names of its robots that are not)."""
        alive = set(self.alive())
        live = [session.links[k] for k in target["members"] if k in alive]
        missing = [plan["names"].get(k, k) for k in target["members"] if k not in alive]
        if not live:
            raise WozError("NO_ROBOTS", "none of {} can be reached (the robots' WiFi?)".format(
                target["name"]))
        return live, missing

    def _movers(self, session: Any, target: dict, plan: dict, live: list) -> list:
        """Every live robot that does the cue's motion: the target's own and
        the ones that move with them (a moving group copies its speaker)."""
        alive = set(self.alive())
        keys = [l.key for l in live]
        for k in list(keys):
            for other in plan["mirror"].get(k, []):
                if other not in keys and other in alive:
                    keys.append(other)
        return [session.links[k] for k in keys]

    def _check(self, gen: int) -> None:
        if gen != self._gen:
            raise _Stopped()

    async def _cut(self, session: Any, gen: int) -> None:
        """Silence whatever is playing: the last cue, and the conversation's
        current line (cut_seq was bumped when the cue was fired; its speaker
        stops before it sends anything more and lets go, then the robots are
        cleared). Gives up at once when Stop is pressed meanwhile."""
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=2.0)
        self._check(gen)
        t0 = time.monotonic()
        while session.speaking_key and time.monotonic() - t0 < CUT_WAIT_S:
            await asyncio.sleep(0.02)
            self._check(gen)
        if session.speaking_key:
            log.warning("woz: the conversation line did not let go in %.0f s", CUT_WAIT_S)
        sends = [asyncio.wait_for(l.stop_audio(), 3.0) for l in session.links.values()]
        await asyncio.gather(*sends, return_exceptions=True)
        self._check(gen)

    def _record(self, session: Any, target: dict, text: str, cue_id: Optional[str]) -> None:
        """With a conversation running, the line is in its transcript as said
        by the target's speaker, so the writer knows it was said (a cue with
        no words is not a line)."""
        convo = self.m.convo
        if not self.m.running or convo is None or not text:
            return
        seat = target["seat"]
        entry = convo.turn(kind="robot", who=seat.get("name"), character=seat.get("character"),
                           text=text, move="", gesture="", woz=True, cue=cue_id)
        self.m.log_turn(entry)

    async def fire(self, cue_id: str, wanted: str = "auto") -> dict:
        script = self.load_script()
        cue = script["cues"].get(str(cue_id))
        if cue is None:
            raise WozError("NO_CUE", "no cue {!r} in the script".format(cue_id))
        gen = self._gen
        session = self._session()
        motion, note = self.motion_of(cue)
        if not cue["text"] and motion is None:
            raise WozError("NO_MOTION", "{!r}: {}".format(cue["id"], note or "nothing to do"))
        pcm = b""
        if cue["text"]:
            pcm = await self.pcm_of(cue)
            if not pcm:
                raise WozError("NO_AUDIO", "{!r} has no audio yet{}".format(
                    cue["id"], " ({})".format(self.last_error) if self.last_error else ""))
        out = await self._start(session, gen, wanted, text=cue["text"], pcm=pcm, motion=motion,
                                cue_id=cue["id"])
        if note and out.get("ok") and not out.get("stopped"):
            out["note"] = note
        return out

    async def say(self, text: str, wanted: str = "auto") -> dict:
        """A typed line in the target speaker's conversation voice (needs the
        internet and a voice key). Stop while it is being voiced drops it."""
        text = " ".join(str(text or "").split())[:SAY_MAX_CHARS]
        if not text:
            raise WozError("NO_CUE", "nothing to say")
        gen = self._gen
        session = self._session()
        plan = self.plan()
        target = self.choose(plan, wanted)
        self._links_of(session, target, plan)        # fail fast before the voice is made
        line = Line(seat=target["seat"], move="", text=text, final=False, nudge="",
                    director_s=0.0)
        task = session.start_voice(line)
        deadline = time.monotonic() + VOICE_WAIT_S
        try:
            while not task.done():
                if gen != self._gen:
                    task.cancel()
                    return {"ok": True, "stopped": True}
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError()
                await asyncio.wait({task}, timeout=0.1)
            if task.cancelled():
                raise RuntimeError("the voice was cancelled")
            task.result()
        except asyncio.CancelledError:
            task.cancel()
            raise
        except Exception as exc:  # noqa: BLE001
            task.cancel()
            raise WozError("NO_VOICE", "the voice is not available: {}".format(
                str(exc) or type(exc).__name__)[:160]) from exc
        pcm = b"".join(line.audio.chunks)
        if not pcm:
            raise WozError("NO_VOICE", "the voice sent no audio{}".format(
                ": {}".format(line.audio.error[:120]) if line.audio.error else ""))
        return await self._start(session, gen, target["id"], text=text, pcm=pcm, motion=None,
                                 cue_id=None)

    async def _start(self, session: Any, gen: int, wanted: str, *, text: str, pcm: bytes,
                     motion: Optional[dict], cue_id: Optional[str]) -> dict:
        """Play a cue. One with a voice takes the floor before anything else
        (so no conversation line can start meanwhile), cuts the line being
        said and the last cue, then plays; a motion-only cue cuts nothing.
        Stop pressed at any point before it plays drops it ({"stopped"})."""
        if gen != self._gen:
            return {"ok": True, "stopped": True}
        plan = self.plan()
        target = self.choose(plan, wanted)
        live, missing = self._links_of(session, target, plan)
        movers = self._movers(session, target, plan, live) if motion else []
        self._last_target = target["id"]
        if not pcm:
            return self._move_only(session, target, movers, motion, missing)
        token = object()
        self._floor[token] = time.monotonic() + START_HOLD_S
        # The line being said stops before it sends another piece (speak()
        # compares cut_seq before every send, the first one too).
        session.cut_seq += 1
        handed = False
        try:
            async with self._lock:
                self._check(gen)
                await self._cut(session, gen)
                link: Any = live[0]
                lead_s = 0.0
                if len(live) > 1:
                    link = GroupLink(live, session.group_offset([l.key for l in live]))
                    lead_s = GROUP_START_LEAD_S if link.synced else 0.0
                duration = len(pcm) / (2.0 * SAMPLE_RATE)
                until = time.time() + lead_s + duration
                now = time.monotonic()
                # The heads are left alone for the cue and for its gesture,
                # whichever is longer (an emotion outlasts a short line).
                hold = max(duration, self._motion_s(motion))
                for key in {l.key for l in [*live, *movers]}:
                    session.busy_until[key] = max(session.busy_until.get(key, 0.0),
                                                  now + lead_s + hold)
                self._record(session, target, text, cue_id)
                playing = {"cue_id": cue_id, "text": text, "target_id": target["id"],
                           "target_name": target["name"], "until": round(until, 2)}
                self._playing = playing
                self._publish_playing()
                self._floor[token] = now + lead_s + duration + FLOOR_SPARE_S
                task = asyncio.ensure_future(self._play(
                    session, playing, link, [l.key for l in live], movers, pcm, motion, lead_s,
                    target["seat"]))
                self._task = task
                handed = True
                task.add_done_callback(lambda _t: self._floor.pop(token, None))
                task.add_done_callback(self._ended)
        except _Stopped:
            return {"ok": True, "stopped": True}
        finally:
            if not handed:
                self._floor.pop(token, None)
        return {"ok": True, "target_id": target["id"], "target_name": target["name"],
                "duration_s": round(duration, 2), "missing": missing}

    @staticmethod
    def _motion_s(motion: Optional[dict]) -> float:
        """How long a cue's motion keeps the head busy (moves.duration)."""
        if not motion:
            return 0.0
        if motion.get("type") in ("emotion", "dance"):
            return moves.duration(str(motion.get("name") or "")) or 3.0
        return 2.0

    def _ended(self, task: asyncio.Task) -> None:
        if self._task is task:
            self._task = None

    def _move_only(self, session: Any, target: dict, movers: list, motion: Optional[dict],
                   missing: list) -> dict:
        """A cue with no words: its motion, now, on top of whatever plays (it
        cuts nothing and is no line in the transcript)."""
        now = time.monotonic()
        hold = self._motion_s(motion)
        for l in movers:
            session.busy_until[l.key] = max(session.busy_until.get(l.key, 0.0), now + hold)
        task = asyncio.ensure_future(asyncio.gather(
            *(l.motion(motion) for l in movers), return_exceptions=True))
        self._moves.add(task)
        task.add_done_callback(self._moves.discard)
        return {"ok": True, "target_id": target["id"], "target_name": target["name"],
                "duration_s": 0.0, "missing": missing}

    async def _play(self, session: Any, playing: dict, link: Any, voices: list[str],
                    movers: list, pcm: bytes, motion: Optional[dict], lead_s: float,
                    seat: dict) -> None:
        async def move() -> None:
            if lead_s:
                await asyncio.sleep(lead_s)
            await asyncio.gather(*(l.motion(motion) for l in movers), return_exceptions=True)

        mover = asyncio.ensure_future(move()) if motion else None
        try:
            if pcm:
                pcm = loud(pcm, seat.get("loudness", DEFAULT_LOUDNESS))
                ears = session.ears
                play_end = time.monotonic()
                first = True
                for i in range(0, len(pcm), SEND_PIECE_BYTES):
                    piece = pcm[i:i + SEND_PIECE_BYTES]
                    while not first and link.seconds_left() > AUDIO_LEAD_S:
                        await asyncio.sleep(0.02)
                    now = time.monotonic()
                    start = max(now + (lead_s if first else 0.0), play_end)
                    play_end = start + len(piece) / (2.0 * SAMPLE_RATE)
                    if ears is not None:
                        # The robots' own mics must not take the cue for a person.
                        try:
                            levels = rms_blocks(piece)
                            for k in voices:
                                ears.add_reference(k, start + PLAY_LATENCY_S, levels)
                        except Exception:  # noqa: BLE001
                            pass
                    first = False
                    await link.play(piece)
                while link.seconds_left() > 0:
                    await asyncio.sleep(0.03)
                await link.end_line()
            if mover is not None:
                await mover
        except asyncio.CancelledError:
            if mover is not None:
                mover.cancel()
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("woz: playing failed: %s", exc)
        finally:
            if self._playing is playing:
                self._playing = None
                self._publish_playing()

    async def stop(self, cut_line: bool = True) -> dict:
        """The panic button: silences the robots at once. The cue playing,
        a cue or typed line still being started, and (`cut_line`) the line
        the conversation is saying; the conversation then goes on. Heads go
        back to breathing when a cue was on. The Group tab's Finish passes
        cut_line=False: the robot talking finishes its line."""
        session = self.m.session
        voiced = bool(self._floor) or self.sending()
        was = (voiced or self.busy()) if cut_line else voiced
        tasks = self.halt()
        if session is not None and cut_line:
            session.cut_seq += 1
        if session is not None and (was or cut_line):
            # The floor stays taken until the robots are cleared, so a line
            # that waited for the cue cannot send a first piece the clear
            # then flushes (halt() freed the cue's own hold).
            token = object()
            self._floor[token] = time.monotonic() + STOP_HOLD_S
            sends = []
            for link in session.links.values():
                sends.append(asyncio.wait_for(link.stop_audio(), 3.0))
                if was:
                    sends.append(asyncio.wait_for(link.motion({"type": "stop"}), 3.0))
            try:
                await asyncio.gather(*sends, return_exceptions=True)
            finally:
                self._floor.pop(token, None)
        if tasks:
            await asyncio.wait(tasks, timeout=2.0)
        return {"ok": True}
