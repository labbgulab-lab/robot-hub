"""Pepper without Pepper: rehearse a session's flow on this laptop.

    .venv\\Scripts\\python.exe -m pepper_app.sim            # opens http://127.0.0.1:8780/sim
    .venv\\Scripts\\python.exe -m pepper_app.sim --mute     # Pepper's lines as text only

The real pepper_app runs unchanged, against a stand-in for the robot agent
(agent/pepper_agent.py) on 127.0.0.1. The stand-in answers every command as
the robot would, plays Pepper's speech on this laptop's speakers, and reports
playing on/off, so the strict turn-taking runs as it does on the robot.

What the visitor would *say* is typed on /sim and enters the conversation as
a finished spoken sentence: fillers and anything said while Pepper still talks
are ignored there exactly as with Pepper's microphone. Taps go through the
same tablet page Pepper shows (/screen). Not simulated: the microphone itself,
the camera (no picture, so Vision has nothing to see), and the movements
(they are listed on /sim instead).

Keys come from the environment or from the hub's Keys panel (keys.local.json).
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import struct
import threading
import time
import wave
import webbrowser
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import robot as robot_mod
from .audio import RATE

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SIM_INFO = {"name": "Simulated Pepper", "naoqi": "simulator", "body": "none"}
# OpenAI sends a reply's audio ~5x faster than it plays (measured 2026-10-11, Hebrew
# and English), so the laptop waits for a pause in arrivals and plays the lot in one
# go: each winsound call reopens the device, and short pieces stutter.
SETTLE_S = 0.3
MAX_SETTLE_S = 3.0


def load_keys() -> None:
    """GPT and ElevenLabs keys from the hub's key store, unless already set."""
    want = {"gpt": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}
    try:
        stored = json.loads((REPO / "keys.local.json").read_text(encoding="utf-8")).get("keys") or []
    except (OSError, ValueError):
        stored = []
    for provider, env in want.items():
        if os.environ.get(env, "").strip():
            continue
        key = next((k.get("key") for k in stored if k.get("provider") == provider and k.get("key")), "")
        if key:
            os.environ[env] = key


class Speaker:
    """Pepper's loudspeaker, on this laptop: 24 kHz PCM16 chunks, played in
    order; `on_playing` reports start and end like the robot's agent does."""

    def __init__(self, mute: bool) -> None:
        self.mute = mute
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.playing = False
        self.last_push = 0.0
        self.on_playing = None
        threading.Thread(target=self._run, daemon=True).start()

    def push(self, pcm: bytes) -> None:
        with self.lock:
            self.buf.extend(pcm)
            self.last_push = time.monotonic()
        self.wake.set()

    def flush(self) -> None:
        with self.lock:
            self.buf.clear()
        if not self.mute:
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception:  # noqa: BLE001
                pass

    def _set(self, on: bool) -> None:
        if on != self.playing:
            self.playing = on
            if self.on_playing:
                self.on_playing(on)

    def _run(self) -> None:
        while True:
            self.wake.wait()
            self.wake.clear()
            while True:
                start = time.monotonic()
                while (time.monotonic() - self.last_push < SETTLE_S
                       and time.monotonic() - start < MAX_SETTLE_S):
                    time.sleep(0.05)
                with self.lock:
                    chunk = bytes(self.buf)
                    self.buf.clear()
                if not chunk:
                    break
                self._set(True)
                self._play(chunk)
            self._set(False)

    def _play(self, pcm: bytes) -> None:
        seconds = len(pcm) / (RATE * 2)
        if self.mute:
            time.sleep(seconds)
            return
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)
        try:
            import winsound
            winsound.PlaySound(out.getvalue(), winsound.SND_MEMORY)
        except Exception:  # noqa: BLE001  (not Windows: keep the timing only)
            time.sleep(seconds)


class FakeAgent:
    """What agent/pepper_agent.py does on the robot, minus the robot."""

    def __init__(self, port: int, token: str, mute: bool, on_move) -> None:
        self.port, self.token = port, token
        self.speaker = Speaker(mute)
        self.on_move = on_move
        self.writer = None
        self.loop = None

    def _send(self, kind: bytes, payload: bytes) -> None:
        if self.writer is not None:
            self.writer.write(kind + struct.pack(">I", len(payload)) + payload)

    def send_json(self, msg: dict) -> None:
        data = json.dumps(msg).encode("utf-8")
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._send, b"J", data)

    def status(self) -> dict:
        return {"speaker_mode": "this laptop (simulator)", "playing": self.speaker.playing,
                "battery": 100, "awake": True, "awareness": True}

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.speaker.on_playing = lambda on: self.send_json({"ev": "playing", "on": on})
        reader, self.writer = await asyncio.open_connection("127.0.0.1", self.port)
        self.send_json({"ev": "hello", "token": self.token, "info": SIM_INFO,
                        "speaker_mode": "this laptop (simulator)", "pid": os.getpid()})
        asyncio.create_task(self._status_loop())
        while True:
            head = await reader.readexactly(5)
            payload = await reader.readexactly(struct.unpack(">I", head[1:5])[0])
            if head[0:1] == b"S":
                self.speaker.push(payload)
            elif head[0:1] == b"J":
                msg = json.loads(payload)
                reply = {"id": msg.get("id"), "ok": True, **self._handle(msg)}
                self.send_json(reply)

    async def _status_loop(self) -> None:
        while True:
            self.send_json({"ev": "status", "status": self.status()})
            await asyncio.sleep(3)

    def _handle(self, msg: dict) -> dict:
        cmd = msg.get("cmd")
        if cmd == "stop_speech" or cmd == "stop_all":
            self.speaker.flush()
        if cmd == "tablet_show":
            return {"ok_tablet": True}
        if cmd == "move":
            self.on_move("move: " + str(msg.get("name")))
            return {"did": msg.get("name")}
        if cmd in ("head", "posture", "face_tracking"):
            self.on_move("{}: {}".format(cmd, msg.get("dir") or msg.get("name") or msg.get("on")))
        if cmd == "say":
            self.on_move("Pepper's own voice says: " + str(msg.get("text")))
        return {}


def install(mute: bool) -> list:
    """Point RobotLink at the stand-in instead of SSH. Returns the move log."""
    moves: list = []

    def on_move(text: str) -> None:
        moves.append({"t": time.time(), "text": text})
        del moves[:-30]

    async def deploy(self) -> None:
        self.state, self.detail = "deploying", "starting the simulated Pepper"
        self._emit("link", {})
        asyncio.create_task(FakeAgent(self.listen_port, self.token, mute, on_move).run())
        for _ in range(40):
            if self.connected:
                return
            await asyncio.sleep(0.25)
        self.state, self.detail = "failed", "the simulated Pepper did not connect"
        self._emit("link", {})

    async def stop_agent(self) -> None:
        return None

    robot_mod.RobotLink.deploy = deploy
    robot_mod.RobotLink.stop_agent = stop_agent
    return moves


def add_routes(app, moves: list) -> None:
    P = app.state.pepper

    @app.get("/sim")
    async def sim_page():
        return HTMLResponse((HERE / "static" / "sim.html").read_text(encoding="utf-8"),
                            headers={"Cache-Control": "no-store"})

    @app.post("/sim/say")
    async def sim_say(request: Request):
        try:
            text = str((await request.json()).get("text") or "").strip()[:400]
        except Exception:  # noqa: BLE001
            text = ""
        b = P.brain
        if not text:
            return JSONResponse({"error": "type what the visitor says"}, 400)
        if not b or not b.running:
            return JSONResponse({"error": "start a conversation first"}, 409)
        P.log("INFO", "sim: visitor says “{}”".format(text[:60]))
        b._answered_at = time.monotonic()
        await b._on_answer(text, source="speech")
        return {"ok": True, "used": b.turn != "waiting"}

    @app.get("/sim/state")
    async def sim_state():
        return {"ai": P.brain.public() if P.brain else {"state": "off"},
                "speaking": P.router.speaking, "moves": moves[-12:],
                "chat": list(P.chat)[-60:], "cfg": P.cfg}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mute", action="store_true", help="no sound: Pepper's lines as text only")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    load_keys()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("No GPT key: add one in the hub's Keys panel, or set OPENAI_API_KEY")
    moves = install(args.mute)

    import uvicorn

    from .server import create_app
    data = HERE / "data"
    app = create_app("127.0.0.1", args.port, 8782, data)
    add_routes(app, moves)
    url = "http://127.0.0.1:{}/sim".format(args.port)
    print("Simulated Pepper: {}  (operator dashboard: http://127.0.0.1:{}/)".format(url, args.port))
    if not args.no_browser:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
