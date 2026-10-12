"""Pepper's operator dashboard and screen server.

One HTTP server on 0.0.0.0:8780:
  /            /api/*      the operator dashboard -- this laptop only (127.0.0.1)
  /screen      /screen/*   the page on Pepper's chest tablet, and its taps

The tablet must reach the laptop over the hotspot, which is why this is not
bound to 127.0.0.1 like the old Say-It page. Everything that controls Pepper is
refused unless the request comes from this laptop and names it as the host.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response

from . import eleven
from .audio import AudioRouter
from .brain import DEFAULT_EXPERIENCE, ENGINES, EXPERIENCES, MODEL, NOT_FOR_DEMO, VOICES, Brain, experience
from .script import REACT_MODEL, SCRIPTS, ScriptRunner
from .robot import RobotLink, laptop_ip_towards
from .screen import EMOJI_CANDIDATES, IMAGE_TYPES, Screen
from .speech import QUICK_PHRASES, Speech, is_hebrew

log = logging.getLogger("pepper.app")
HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
# Said right before the Walking move (Tomer, 2026-10-12).
WALK_LINES = {"he": "אני צריך למתוח קצת את הרגליים, יוצא להליכה.",
              "en": "I need to stretch my legs, going for a walk."}
TABLET_RESHOW_S = 20.0
# A fresh laptop gets the setup tested on the robot on 2026-10-12: the scripted
# demo, Hebrew, ElevenLabs ears and voice ("Laura", a premade ElevenLabs voice).
DEFAULTS = {"experience": DEFAULT_EXPERIENCE, "engine": "eleven", "language": "he",
            "voice": "marin", "el_voice": "FGY2WhTYpPnrIDTdsKH5", "vision": False, "ai_screen": True,
            "gestures": True, "camera": 0, "deck": None,
            "pause_ai": True, "tell_ai": True, "emoji_broken": []}


class PepperApp:
    def __init__(self, robot_ip: str, port: int, agent_port: int, data_dir: Path) -> None:
        self.robot_ip, self.port = robot_ip, port
        self.data = data_dir
        self.data.mkdir(parents=True, exist_ok=True)
        self.key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.eleven_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        self.el_voices: list[dict] = []
        self.robot = RobotLink(robot_ip, agent_port,
                               ssh_user=os.environ.get("PEPPER_SSH_USER", "nao"),
                               ssh_password=os.environ.get("PEPPER_SSH_PASSWORD", "nao"))
        self.router = AudioRouter(self.robot)
        self.screen = Screen(self.data)
        self.speech = Speech(self.data / "tts-cache", self.key, self.eleven_key)
        self.cfg = dict(DEFAULTS)
        self._load_cfg()
        self.brain: Optional[Brain] = None
        self.clients: set[WebSocket] = set()
        self.logs: collections.deque = collections.deque(maxlen=600)
        self.chat: collections.deque = collections.deque(maxlen=200)
        self.tablet_shown_at = 0.0
        self.tablet_url = ""
        self.phrases_ready = 0
        self.robot.on_event = self._on_robot
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------ settings
    def _cfg_path(self) -> Path:
        return self.data / "settings.json"

    def _load_cfg(self) -> None:
        try:
            saved = json.loads(self._cfg_path().read_text(encoding="utf-8"))
            self.cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
            if self.cfg["experience"] not in EXPERIENCES or self.cfg["experience"] in NOT_FOR_DEMO:
                self.cfg["experience"] = DEFAULT_EXPERIENCE
        except (OSError, ValueError):
            pass

    def _save_cfg(self) -> None:
        try:
            self._cfg_path().write_text(json.dumps(self.cfg, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------- push to pages
    def broadcast(self, kind: str, data: Any) -> None:
        text = json.dumps({"type": kind, "data": data}, ensure_ascii=False)
        loop = self.loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        for ws in list(self.clients):
            if running is loop:
                asyncio.ensure_future(self._send_ws(ws, text))
            else:   # a log line from a worker thread
                asyncio.run_coroutine_threadsafe(self._send_ws(ws, text), loop)

    async def _send_ws(self, ws: WebSocket, text: str) -> None:
        try:
            await ws.send_text(text)
        except Exception:  # noqa: BLE001
            self.clients.discard(ws)

    def log(self, level: str, msg: str) -> None:
        line = {"t": time.time(), "level": level, "msg": msg}
        self.logs.append(line)
        line_out = "{} {:7} {}".format(time.strftime("%H:%M:%S"), level, msg)
        try:
            print(line_out, flush=True)
        except UnicodeEncodeError:  # a cp1252 console and an emoji: never let it end the session
            print(line_out.encode("ascii", "replace").decode("ascii"), flush=True)
        self.broadcast("log", line)

    def add_chat(self, role: str, text: str, **extra: Any) -> None:
        entry = {"role": role, "text": text, "t": time.time(), **extra}
        if extra.get("id") and role == "pepper":
            # a streaming reply: replace the partial entry with the same id
            for i, e in enumerate(self.chat):
                if e.get("id") == extra["id"] and e["role"] == "pepper":
                    self.chat[i] = entry
                    break
            else:
                self.chat.append(entry)
        else:
            self.chat.append(entry)
        self.broadcast("chat", entry)

    def snapshot(self) -> dict:
        return {"cfg": self.cfg, "health": self.health(), "logs": list(self.logs),
                "chat": list(self.chat), "screen": self.screen.state(),
                "ai": self.brain.public() if self.brain else {"state": "off", "model": MODEL},
                "decks": self.screen.decks(), "experiences": {k: v[0] for k, v in EXPERIENCES.items()},
                "experiences_off": sorted(NOT_FOR_DEMO),
                "engines": ENGINES, "voices": VOICES, "el_voices": self.el_voices,
                "emoji_candidates": EMOJI_CANDIDATES, "phrases": QUICK_PHRASES,
                "has_key": bool(self.key), "has_eleven": bool(self.eleven_key)}

    def health(self) -> dict:
        r = self.robot
        return {"robot": {"state": r.state, "detail": r.detail, "ip": self.robot_ip,
                          "info": r.info, "status": r.status, "speaker_mode": r.speaker_mode},
                "screen": self.screen.health(), "speaking": self.router.speaking,
                "mic_level": self.router.mic_level, "mic_on": self.router.mic_on,
                "frame": self.robot.frame_no,
                "phrases_ready": self.phrases_ready}

    # ------------------------------------------------------------- robot
    def _on_robot(self, kind: str, data: dict) -> None:
        if kind == "link":
            r = self.robot
            level = {"connected": "INFO", "deploying": "INFO"}.get(r.state, "ERROR")
            self.log(level, "pepper: {} -- {}".format(r.state, r.detail))
            if r.connected:
                asyncio.ensure_future(self._robot_ready())
        self.broadcast("health", self.health())

    async def _robot_ready(self) -> None:
        r = self.robot
        try:
            await r.call("camera", index=self.cfg["camera"], fps=self.camera_fps())
            if self.router.mic_on:
                await r.call("mic", on=True)
            await self.show_tablet()
            # The vendor app's dialog stays paused for as long as the dashboard
            # runs: it heard Pepper's own Wizard of Oz audio and its ChatGPT bot
            # answered ("No worries, how can I assist you today", 2026-10-12).
            await r.call("vendor_quiet", on=True)
        except Exception as exc:  # noqa: BLE001
            self.log("WARNING", "pepper: setup after connect: {}".format(exc))
        if r.speaker_mode in (None, "none"):
            self.log("ERROR", "pepper: no way to play audio on Pepper's speaker -- the AI "
                              "cannot talk; Wizard of Oz with Pepper's own voice still works (English)")
        else:
            self.log("INFO", "pepper: speaker via {}".format(r.speaker_mode))

    async def show_tablet(self) -> None:
        laptop = laptop_ip_towards(self.robot_ip)
        self.tablet_url = "http://{}:{}/screen".format(laptop, self.port)
        self.tablet_shown_at = time.monotonic()
        res = await self.robot.call("tablet_show", url=self.tablet_url, timeout=15)
        self.log("INFO", "screen: asked Pepper's tablet to open {} ({})".format(
            self.tablet_url, "ok" if res.get("ok_tablet") else "tablet said no"))

    async def ticker(self) -> None:
        """Health to the pages every second; camera frames as they come; the
        tablet re-opened when it stops calling in."""
        last_frame, was_screen = 0, None
        n = 0
        while True:
            await asyncio.sleep(0.25)
            n += 1
            r = self.robot
            if r.frame_no != last_frame and r.last_frame is not None:
                last_frame = r.frame_no
                meta = r.last_frame[0]
                self.broadcast("frame", {"n": last_frame, "w": meta.get("w"), "h": meta.get("h"),
                                         "faces": meta.get("faces") or [], "cam": meta.get("cam")})
            if n % 4:
                continue
            on = self.screen.connected
            if on != was_screen and was_screen is not None:
                self.log("INFO" if on else "ERROR",
                         "screen: tablet {}".format("calling in again" if on else "stopped calling in"))
            was_screen = on
            if (r.connected and not on and time.monotonic() - self.tablet_shown_at > TABLET_RESHOW_S):
                try:
                    await self.show_tablet()
                except Exception as exc:  # noqa: BLE001
                    self.log("WARNING", "screen: could not re-open the tablet page: {}".format(exc))
            self.broadcast("health", self.health())

    # ------------------------------------------------------- emoji, voices
    def emoji_ok(self) -> list[str]:
        broken = set(self.cfg.get("emoji_broken") or [])
        return [e for e in EMOJI_CANDIDATES if e not in broken]

    def screen_emoji(self) -> Optional[set[str]]:
        """The emoji the current experience may put on the screen (None: words only)."""
        return set(self.emoji_ok()) if experience(self.cfg["experience"])[3] else None

    async def _synth_now(self, text: str) -> bytes:
        """The conversation's voice, through the on-disk speech cache."""
        provider, voice = self.voice_now()
        return await self.speech.synth(text, voice, provider)

    def camera_fps(self) -> float:
        """Each frame is a ~170 KB PNG on the phone hotspot, sharing the link with
        Pepper's mic: at 2 fps it congested the hotspot (2026-10-12, pings 280 ms).
        Full rate only while the AI looks through the camera."""
        return 2.0 if self.cfg.get("vision") else 0.5

    def voice_now(self) -> tuple[str, str]:
        """(provider, voice) the conversation speaks with -- Wizard of Oz uses the same."""
        if self.cfg["engine"] == "eleven" and self.cfg.get("el_voice") and self.eleven_key:
            return "eleven", self.cfg["el_voice"]
        return "openai", self.cfg["voice"]

    async def load_el_voices(self) -> None:
        if not self.eleven_key:
            return
        try:
            self.el_voices = await eleven.list_voices(self.eleven_key)
        except Exception as exc:  # noqa: BLE001
            self.log("WARNING", "elevenlabs: could not list voices: {}".format(exc))
            return
        ids = {v["id"] for v in self.el_voices}
        if self.cfg.get("el_voice") not in ids and self.el_voices:
            self.cfg["el_voice"] = self.el_voices[0]["id"]
            self._save_cfg()
        self.log("INFO", "elevenlabs: {} voices".format(len(self.el_voices)))
        self.broadcast("el_voices", self.el_voices)
        self.broadcast("cfg", self.cfg)

    # ------------------------------------------------------------ the AI
    def _brain_event(self, kind: str, data: dict) -> None:
        if kind == "chat":
            self.add_chat(data["role"], data["text"], id=data.get("id"), partial=data.get("partial", False))
        elif kind == "log":
            self.log(data["level"], data["msg"])
        elif kind == "ai":
            self.broadcast("ai", data)
        elif kind == "vision":
            self.broadcast("vision", data)
        elif kind == "heard":
            self.add_chat("heard", data["text"], why=data.get("why", ""))
        elif kind == "hearing":
            self.broadcast("hearing", data)

    def _frame_png(self) -> Optional[bytes]:
        if self.robot.connected and self.robot.last_frame is not None:
            return self.robot.last_frame[1]
        return None

    async def _flush_speech(self) -> None:
        # Awaited, not fire-and-forget: the agent runs commands in arrival order,
        # and a stop sent after the next say cancelled it (Wizard of Oz silent).
        self.router.flush()
        if self.robot.connected:
            await self._quiet_call("stop_speech")

    async def _quiet_call(self, cmd: str, **kw: Any) -> None:
        try:
            await self.robot.call(cmd, **kw)
        except Exception as exc:  # noqa: BLE001
            self.log("WARNING", "pepper: {} failed: {}".format(cmd, exc))

    def _tool(self, name: str, args: dict) -> str:
        if name == "gesture":
            move = str(args.get("name", ""))
            if self.cfg["gestures"] and self.robot.connected:
                asyncio.ensure_future(self._quiet_call("move", name=move))
            self.add_chat("event", "AI gesture: {}".format(move))
            return "ok"
        if name == "show_choice":
            pics = self.screen.images_by_name()
            options = []
            for o in (args.get("options") or [])[:4]:
                label = str(o.get("label") or "").strip()[:40]
                if not label:
                    continue
                opt = {"label": label, "emoji": str(o.get("emoji") or "")}
                img = str(o.get("image") or "").strip().lower()
                if img and img in pics:
                    opt["image"] = pics[img]
                options.append(opt)
            if len(options) < 2:
                return "failed: a choice needs at least two options"
            item = {"kind": "choice", "question": str(args.get("question") or "")[:120], "options": options}
            self.set_screen(item, "ai")
            return "shown; say the question out loud, then wait for the person to tap or say their answer"
        if name == "show_message":
            self.set_screen({"kind": "message", "text": str(args.get("text") or "")[:300],
                             "emoji": str(args.get("emoji") or "")}, "ai")
            return "shown"
        if name == "show_slide":
            if not self.cfg.get("deck"):
                return "failed: no presentation is selected"
            try:
                item = self.screen.slide_item(self.cfg["deck"], int(args.get("number") or 1) - 1)
            except (KeyError, ValueError):
                return "failed: no such slide"
            self.set_screen(item, "ai")
            return "showing slide {} of {}: {}".format(item["index"] + 1, item["count"], item["title"])
        if name == "clear_screen":
            self.set_screen({"kind": "welcome"}, "ai")
            return "cleared"
        return "failed: unknown tool"

    def set_screen(self, item: dict, by: str) -> None:
        state = self.screen.show(item, by, self.screen_emoji())
        self.broadcast("screen", state)
        what = {"choice": "choice: " + " / ".join(o["label"] for o in item.get("options", [])),
                "message": "message", "slide": "slide {}".format(item.get("index", 0) + 1),
                "welcome": "welcome", "blank": "blank",
                "emoji_test": "the emoji test card"}.get(item["kind"], item["kind"])
        self.add_chat("event", "{} put {} on the screen".format("AI" if by == "ai" else "You", what))
        self.log("INFO", "screen: {} ({})".format(what, by))

    def _brain_cfg(self) -> dict:
        deck = None
        if self.cfg.get("deck"):
            try:
                deck = self.screen.deck(self.cfg["deck"])
            except KeyError:
                deck = None
        return {**self.cfg, "pictures": sorted(self.screen.images_by_name()), "deck": deck,
                "emoji_ok": self.emoji_ok()}

    async def start_conversation(self) -> None:
        if self.brain and self.brain.running:
            return
        if not self.robot.connected:
            raise HTTPException(409, "Pepper isn't connected yet -- wait for the Robot pill to turn green")
        scripted = self.cfg["experience"] in SCRIPTS
        if scripted and not isinstance(self.brain, ScriptRunner):
            self.brain = ScriptRunner(openai_key=self.key, eleven_key=self.eleven_key,
                                      play=self.router.play, flush=self._flush_speech, tool=self._tool,
                                      emit=self._brain_event, speaking=lambda: self.router.speaking,
                                      synth=self._synth_now, voice=self.voice_now)
        elif not scripted and not isinstance(self.brain, Brain):
            self.brain = Brain(openai_key=self.key, eleven_key=self.eleven_key,
                               play=self.router.play, flush=self._flush_speech, tool=self._tool,
                               emit=self._brain_event, frame=self._frame_png,
                               speaking=lambda: self.router.speaking,
                               choice_open=self._choice_open, fallback=self._fallback_voice)
        else:
            self.brain.history.clear()
        self.router.listener = self.brain.push_mic
        try:
            await self.router.set_mic(True)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, "could not open the microphone: {}".format(exc)) from exc
        if self.robot.connected:
            await self._quiet_call("vendor_quiet", on=True)
        self.set_screen({"kind": "welcome"}, "ai")
        try:
            await self.brain.start(self._brain_cfg())
        except Exception as exc:  # noqa: BLE001
            await self.router.set_mic(False)
            raise HTTPException(502, str(exc)) from exc
        self.add_chat("event", "Conversation started")
        provider, voice = self.voice_now()
        self.log("INFO", "conversation: start · {} · engine={} · {} · lang={} · voice={}:{} · "
                 "vision={}".format(
                     self.cfg["experience"], self.cfg["engine"], REACT_MODEL if scripted else MODEL,
                     self.cfg["language"],
                     provider, self._voice_name(voice), "on" if self.cfg["vision"] else "off"))

    def _choice_open(self) -> bool:
        return self.screen.item.get("kind") == "choice" and not self.screen.picked

    async def _fallback_voice(self, text: str) -> None:
        pcm = await self.speech.synth(text, self.cfg["voice"], "openai")
        self.router.play(pcm)

    async def stop_conversation(self) -> None:
        if self.brain:
            await self.brain.stop()
        await self.router.set_mic(False)
        await self._flush_speech()
        self.add_chat("event", "Conversation ended")
        self.log("INFO", "conversation: end")
        self.broadcast("ai", self.brain.public() if self.brain else {"state": "off"})

    def _voice_name(self, voice: str) -> str:
        return next((v["name"] for v in self.el_voices if v["id"] == voice), voice)

    async def restart_ai(self) -> None:
        if not self.brain:
            return
        await self.brain.stop()
        self.log("INFO", "ai: restarting the session (keeps the conversation so far)")
        await self.brain.start(self._brain_cfg(), greet=False)

    async def woz_say(self, text: str, pause_ai: bool, tell_ai: bool) -> str:
        """Always the conversation's voice, Hebrew or English (2026-10-12: the
        operator never picks a voice). Pepper's own voice only as an English
        fallback when the AI voice fails."""
        text = text.strip()[:600]
        if not text:
            raise HTTPException(400, "nothing to say")
        b = self.brain
        if b and b.running:
            if pause_ai:
                await b.pause()
            else:
                await b.cancel()
        await self._flush_speech()
        provider, voice_id = self.voice_now()
        if not self.robot.connected:
            raise HTTPException(503, "Pepper is not connected")
        try:
            pcm = await self.speech.synth(text, voice_id, provider)
            self.router.play(pcm)
            how = "{} voice".format("ElevenLabs" if provider == "eleven" else "OpenAI")
        except Exception as exc:  # noqa: BLE001
            if is_hebrew(text) or not self.robot.connected:
                raise HTTPException(502, "could not speak it: {}".format(exc)) from exc
            self.log("WARNING", "woz: AI voice failed ({}); Pepper's own voice instead".format(exc))
            await self._say_on_robot(text)
            how = "pepper voice (fallback)"
        if b and b.running:
            await b.note(text, tell=tell_ai)
        self.add_chat("woz", text)
        self.log("WARNING", "woz: say “{}” via {}{}".format(
            text[:60] + ("…" if len(text) > 60 else ""), how,
            " · AI paused" if b and b.paused else ""))
        return how

    async def _say_on_robot(self, text: str) -> None:
        try:
            await self.robot.call("say", text=text, gestures=self.cfg["gestures"])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, "Pepper could not say it: {}".format(exc)) from exc

    async def say_before_walk(self) -> None:
        """Pepper announces its walk in the conversation's voice (Pepper's own
        voice has no Hebrew), then walks. Nothing is said while it is charging:
        the agent refuses the walk then."""
        if (self.robot.status or {}).get("charging"):
            raise HTTPException(409, "Pepper is charging: unplug the charger and close the flap, "
                                     "then press Walking again")
        text = WALK_LINES["en" if self.cfg.get("language") == "en" else "he"]
        try:
            provider, voice = self.voice_now()
            pcm = await self.speech.synth(text, voice, provider)
        except Exception as exc:  # noqa: BLE001
            self.log("WARNING", "motion: could not say the walk line ({}); walking anyway".format(exc))
            return
        self.router.play(pcm)
        self.add_chat("woz", text)
        await asyncio.sleep(len(pcm) / (24000 * 2))      # walk once the line is said

    async def warm_phrases(self) -> None:
        provider, voice = self.voice_now()
        if not (self.eleven_key if provider == "eleven" else self.key):
            return
        self.phrases_ready = await self.speech.warm(voice, QUICK_PHRASES, provider)
        await self.speech.warm(voice, list(WALK_LINES.values()), provider)
        self.log("INFO", "woz: {} of {} quick phrases ready offline ({}: {})".format(
            self.phrases_ready, len(QUICK_PHRASES), provider, self._voice_name(voice)))

    async def shutdown(self) -> None:
        if self.brain and self.brain.running:
            await self.brain.stop()
        if self.robot.connected:
            await self._quiet_call("vendor_quiet", on=False)
            await self._quiet_call("tablet_hide")
            await self._quiet_call("stop_all")
        if self.robot_ip:
            await self.robot.stop_agent()


def create_app(robot_ip: str, port: int, agent_port: int, data_dir: Path) -> FastAPI:
    P = PepperApp(robot_ip, port, agent_port, data_dir)

    class ToApp(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.INFO:
                P.log(record.levelname, "{}: {}".format(record.name.split(".")[-1], record.getMessage()))
    logging.getLogger("pepper").addHandler(ToApp())
    logging.getLogger("pepper").setLevel(logging.INFO)
    logging.getLogger("pepper").propagate = False

    async def lifespan(_app):
        P.loop = asyncio.get_running_loop()
        if robot_ip:
            await P.robot.start()
        else:
            P.robot.state, P.robot.detail = "failed", "started without a robot address"
        async def voices_then_phrases():
            await P.load_el_voices()
            await P.warm_phrases()
        tasks = [asyncio.create_task(P.ticker()), asyncio.create_task(voices_then_phrases())]
        P.log("INFO", "dashboard on http://127.0.0.1:{}/ · Pepper {} · OpenAI key {} · ElevenLabs key {}".format(
            port, robot_ip or "(none)", "found" if P.key else "MISSING",
            "found" if P.eleven_key else "missing"))
        yield
        for t in tasks:
            t.cancel()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.pepper = P

    @app.middleware("http")
    async def only_this_laptop(request: Request, call_next):
        path = request.url.path
        if not path.startswith("/screen"):
            host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
            client = request.client.host if request.client else ""
            if client not in LOCAL_HOSTS or host not in LOCAL_HOSTS:
                return JSONResponse({"error": "the operator dashboard is only open on this laptop"}, 403)
        return await call_next(request)

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}

    async def robot_call(cmd: str, **kw: Any) -> dict:
        try:
            return await P.robot.call(cmd, **kw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, str(exc) or "Pepper did not answer") from exc

    # ------------------------------------------------------------ pages
    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/static/{name}")
    async def static(name: str):
        path = STATIC / name
        if "/" in name or "\\" in name or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    async def status():
        return {"ok": True, **P.health(), "ai": P.brain.public() if P.brain else {"state": "off"}}

    @app.websocket("/api/ws")
    async def ws(sock: WebSocket):
        host = (sock.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if (sock.client.host if sock.client else "") not in LOCAL_HOSTS or host not in LOCAL_HOSTS:
            await sock.close(code=1008)
            return
        await sock.accept()
        P.clients.add(sock)
        await sock.send_text(json.dumps({"type": "snapshot", "data": P.snapshot()}, ensure_ascii=False))
        try:
            while True:
                await sock.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            P.clients.discard(sock)

    # ------------------------------------------------------ conversation
    @app.post("/api/options")
    async def options(request: Request):
        data = await body(request)
        if data.get("experience") in NOT_FOR_DEMO:
            data.pop("experience")
        changed = {k: v for k, v in data.items() if k in DEFAULTS and v != P.cfg.get(k)}
        P.cfg.update(changed)
        P._save_cfg()
        if set(changed) & {"camera", "vision"} and P.robot.connected:
            await P._quiet_call("camera", index=P.cfg["camera"], fps=P.camera_fps())
        if set(changed) & {"voice", "el_voice", "engine"}:
            asyncio.ensure_future(P.warm_phrases())
        if P.brain and P.brain.running and set(changed) & {"vision", "ai_screen", "deck", "emoji_broken"}:
            await P.brain.update(P._brain_cfg())
        if changed:
            P.log("INFO", "options: " + ", ".join("{}={}".format(k, v) for k, v in changed.items()))
        P.broadcast("cfg", P.cfg)
        return {"ok": True, "cfg": P.cfg}

    @app.post("/api/conversation/start")
    async def conv_start():
        await P.start_conversation()
        return {"ok": True}

    @app.post("/api/conversation/stop")
    async def conv_stop():
        await P.stop_conversation()
        return {"ok": True}

    @app.post("/api/ai/{what}")
    async def ai(what: str):
        b = P.brain
        if not b or not b.running:
            raise HTTPException(409, "no conversation is running")
        if what == "pause":
            await b.pause()
        elif what == "resume":
            await b.resume()
        elif what == "restart":
            try:
                await P.restart_ai()
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(502, str(exc)) from exc
        else:
            raise HTTPException(404)
        P.log("INFO", "ai: " + what)
        return {"ok": True}

    @app.post("/api/turn/{what}")
    async def turn(what: str, request: Request):
        b = P.brain
        if not b or not b.running:
            raise HTTPException(409, "no conversation is running")
        if what == "repeat":
            await b.repeat()
        elif what == "skip":
            await b.skip()
        elif what == "accept":
            text = str((await body(request)).get("text") or "").strip()
            if not text:
                raise HTTPException(400, "nothing to accept")
            P.log("INFO", "turn: operator accepted \u201c{}\u201d as the answer".format(text[:60]))
            await b.accept(text)
        else:
            raise HTTPException(404)
        return {"ok": True}

    # ------------------------------------------------------ wizard of oz
    @app.post("/api/say")
    async def say(request: Request):
        d = await body(request)
        how = await P.woz_say(str(d.get("text") or ""),
                              bool(d.get("pause_ai", True)), bool(d.get("tell_ai", True)))
        return {"ok": True, "how": how}

    @app.post("/api/stop_speech")
    async def stop_speech():
        if P.brain and P.brain.running:
            await P.brain.cancel()
        await P._flush_speech()
        P.log("INFO", "woz: stop talking")
        return {"ok": True}

    @app.post("/api/move")
    async def move(request: Request):
        name = str((await body(request)).get("name", ""))
        if name == "walk":
            await P.say_before_walk()
        res = await robot_call("move", name=name)
        P.add_chat("event", "Gesture: {}".format(name))
        P.log("INFO", "motion: {} ({})".format(name, res.get("did", "")))
        return {"ok": True}

    @app.post("/api/head")
    async def head(request: Request):
        d = str((await body(request)).get("dir", ""))
        await robot_call("head", dir=d)
        P.log("INFO", "motion: head {}".format(d))
        return {"ok": True}

    @app.post("/api/posture")
    async def posture(request: Request):
        name = str((await body(request)).get("name", ""))
        await robot_call("posture", name=name, timeout=20)
        P.log("INFO", "motion: posture {}".format(name))
        return {"ok": True}

    @app.post("/api/face_tracking")
    async def face_tracking(request: Request):
        on = bool((await body(request)).get("on"))
        await robot_call("face_tracking", on=on)
        P.log("INFO", "motion: face tracking {}".format("on" if on else "off"))
        return {"ok": True, "on": on}

    @app.post("/api/stop_motion")
    async def stop_motion():
        await robot_call("stop_motion")
        P.log("INFO", "motion: stop")
        return {"ok": True}

    @app.post("/api/stop_all")
    async def stop_all():
        if P.brain and P.brain.running:
            await P.stop_conversation()
        await P._flush_speech()
        if P.robot.connected:
            await P._quiet_call("stop_all")
        P.log("ERROR", "STOP EVERYTHING: speech, motion and AI stopped")
        return {"ok": True}

    @app.post("/api/volume")
    async def volume(request: Request):
        v = int((await body(request)).get("value", 50))
        await robot_call("volume", value=v)
        return {"ok": True}

    @app.get("/api/camera.png")
    async def camera():
        f = P.robot.last_frame
        if f is None:
            raise HTTPException(404, "no camera frame yet")
        return Response(f[1], media_type="image/png", headers={"Cache-Control": "no-store"})

    # ------------------------------------------------------------ screen
    @app.post("/api/screen")
    async def screen_show(request: Request):
        d = await body(request)
        kind = d.get("kind")
        if kind == "slide":
            try:
                item = P.screen.slide_item(str(d.get("deck")), int(d.get("index", 0)))
            except (KeyError, ValueError) as exc:
                raise HTTPException(404, "no such slide") from exc
        elif kind in ("welcome", "blank"):
            item = {"kind": kind}
        elif kind == "emoji_test":
            item = {"kind": "emoji_test", "cells": [[i + 1, e] for i, e in enumerate(EMOJI_CANDIDATES)]}
        elif kind == "message":
            item = {"kind": "message", "text": str(d.get("text", ""))[:300]}
        elif kind == "choice":
            opts = [{"label": str(o.get("label", ""))[:40]}
                    for o in (d.get("options") or [])[:4] if isinstance(o, dict) and o.get("label")]
            if len(opts) < 2:
                raise HTTPException(400, "a choice needs at least two options")
            item = {"kind": "choice", "question": str(d.get("question", ""))[:120], "options": opts}
        else:
            raise HTTPException(400, "unknown screen item")
        P.set_screen(item, "you")
        return {"ok": True}

    @app.post("/api/emoji/broken")
    async def emoji_broken(request: Request):
        nums = (await body(request)).get("numbers") or []
        try:
            broken = sorted({EMOJI_CANDIDATES[int(n) - 1] for n in nums
                             if 1 <= int(n) <= len(EMOJI_CANDIDATES)}, key=EMOJI_CANDIDATES.index)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "numbers from the emoji test card, e.g. [3, 17]") from exc
        P.cfg["emoji_broken"] = broken
        P._save_cfg()
        if P.brain and P.brain.running:
            await P.brain.update(P._brain_cfg())
        P.log("INFO", "emoji: {} of {} allowed on Pepper's screen ({} marked broken)".format(
            len(P.emoji_ok()), len(EMOJI_CANDIDATES), len(broken)))
        P.broadcast("cfg", P.cfg)
        return {"ok": True, "allowed": len(P.emoji_ok())}

    @app.post("/api/screen/reload")
    async def screen_reload():
        try:
            await P.show_tablet()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, str(exc)) from exc
        return {"ok": True}

    @app.get("/api/decks")
    async def decks():
        return P.screen.decks()

    @app.post("/api/decks")
    async def deck_new(request: Request):
        deck = P.screen.new_deck(str((await body(request)).get("name", "")))
        return deck

    @app.put("/api/decks/{deck_id}/slides")
    async def deck_slide(deck_id: str, request: Request, name: str = "slide.png"):
        data = await request.body()
        try:
            deck = P.screen.add_slide(deck_id, name, data)
        except KeyError as exc:
            raise HTTPException(404, "no such presentation") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return deck

    @app.post("/api/decks/{deck_id}/done")
    async def deck_done(deck_id: str):
        try:
            deck = P.screen.deck(deck_id)
        except KeyError as exc:
            raise HTTPException(404, "no such presentation") from exc
        P.log("INFO", "presentation: “{}” uploaded, {} slides".format(deck["name"], len(deck["slides"])))
        P.cfg["deck"] = deck_id
        P._save_cfg()
        if P.brain and P.brain.running:
            await P.brain.update(P._brain_cfg())
        P.broadcast("decks", P.screen.decks())
        P.broadcast("cfg", P.cfg)
        return {"ok": True}

    @app.delete("/api/decks/{deck_id}")
    async def deck_delete(deck_id: str):
        try:
            P.screen.delete_deck(deck_id)
        except KeyError as exc:
            raise HTTPException(404) from exc
        if P.cfg.get("deck") == deck_id:
            P.cfg["deck"] = None
            P._save_cfg()
        P.broadcast("decks", P.screen.decks())
        P.broadcast("cfg", P.cfg)
        return {"ok": True}

    @app.post("/api/shutdown")
    async def shutdown():
        await P.shutdown()
        return {"ok": True}

    # ------------------------------------------------- the tablet's side
    @app.get("/screen")
    async def screen_page():
        return FileResponse(STATIC / "screen.html", headers={"Cache-Control": "no-store"})

    @app.get("/screen/render.js")
    async def screen_render():
        return FileResponse(STATIC / "screen-render.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-store"})

    @app.get("/screen/logo.png")
    async def screen_logo():
        # Under /screen: the tablet may only load /screen/* (see the guard above).
        return FileResponse(STATIC / "labalab-logo.png", media_type="image/png")

    @app.get("/screen/state")
    async def screen_state(request: Request):
        if request.query_params.get("tablet"):
            P.screen.heartbeat(request.client.host if request.client else "",
                               request.headers.get("user-agent", "")[:120])
        return JSONResponse(P.screen.state(), headers={"Cache-Control": "no-store"})

    @app.post("/screen/tap")
    async def screen_tap(request: Request):
        d = await body(request)
        try:
            label = P.screen.tap(int(d.get("v", -1)), int(d.get("i", -1)))
        except (TypeError, ValueError):
            label = None
        if label is None:
            return {"ok": False}
        P.broadcast("screen", P.screen.state())
        P.add_chat("tap", label)
        P.log("INFO", "screen: tap “{}”{}".format(label, " -> sent to AI" if P.brain and P.brain.running else ""))
        if P.brain and P.brain.running:
            await P.brain.tap(label)
        return {"ok": True}

    @app.get("/screen/media/{deck_id}/{file}")
    async def screen_media(deck_id: str, file: str):
        try:
            path = P.screen.slide_path(deck_id, file)
        except KeyError as exc:
            raise HTTPException(404) from exc
        return FileResponse(path, media_type=IMAGE_TYPES.get(path.suffix.lower(), "image/png"))

    return app
