"""The laptop end of the link to Pepper.

`agent/pepper_agent.py` runs on the robot (Python 2.7, NAOqi 2.5); see its
docstring for the frame format. This module

  * uploads and starts that agent over SSH (nao/nao), with the tablet page's
    files next to it, at start-up and again whenever it has been gone a while,
  * CONNECTS OUT to the agent on robot port 8790 (token-checked, one laptop at
    a time). A student laptop may not listen on the network: Windows asks
    about the firewall, and a student is not an admin (2026-11-05). So this is
    the normal way, and nothing here listens on anything but 127.0.0.1,
  * falls back to the old direction only when the outbound connect fails for
    OUTBOUND_WAIT_S: the agent is restarted in connect-back mode and this
    laptop listens on port 8782 (Windows may then ask about the firewall),
  * turns commands into awaitable calls, hands microphone audio and camera
    frames to whoever subscribed, and passes on the tablet's events (its
    heartbeat, taps, and requests for slide files, answered with `send_data`).

The chest tablet loads its page from the agent (http://198.18.0.1:8791/screen,
the head's address on Pepper's internal head-tablet network), in both modes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import struct
import time
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("pepper.robot")

HERE = Path(__file__).resolve().parent
AGENT = HERE / "agent" / "pepper_agent.py"
# The tablet page: uploaded next to the agent, which serves it on TABLET_PORT.
SCREEN_FILES = {"screen.html": HERE / "static" / "screen.html",
                "screen-render.js": HERE / "static" / "screen-render.js",
                "labalab-logo.png": HERE / "static" / "labalab-logo.png"}
REMOTE_DIR = "/home/nao/robothub"
REMOTE_AGENT = REMOTE_DIR + "/pepper_agent.py"
REMOTE_SCREEN = REMOTE_DIR + "/screen"
REMOTE_LOG = REMOTE_DIR + "/pepper_agent.log"
ROBOT_PYTHONPATHS = ["", "PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages:$PYTHONPATH "]
AGENT_PORT = 8790             # the agent listens here (on the robot)
TABLET_PORT = 8791            # the agent serves the tablet page here (on the robot)
BACK_PORT = 8782              # fallback only: this laptop listens here for the agent
TABLET_HOST = "198.18.0.1"    # Pepper's head, as its chest tablet sees it
OUTBOUND_WAIT_S = 15.0
CONNECT_WAIT_S = 60.0
REDEPLOY_AFTER_S = 20.0
CALL_TIMEOUT_S = 8.0
PING_EVERY_S = 5.0
LINK_IDLE_S = 20.0            # no frame from the agent this long: the link is dead
FRAME_MAX = 64 * 1024 * 1024
FALLBACK_NOTE = "fallback: Pepper connects back; Windows may ask about the firewall"


def laptop_ip_towards(robot_ip: str) -> str:
    """The address Pepper should use to reach this laptop (fallback mode only)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((robot_ip, 9559))
        return s.getsockname()[0]
    finally:
        s.close()


class RobotLink:
    def __init__(self, robot_ip: str, agent_port: int = AGENT_PORT, *,
                 back_port: int = BACK_PORT, tablet_port: int = TABLET_PORT,
                 back_host: str = "0.0.0.0",
                 ssh_user: str = "nao", ssh_password: str = "nao") -> None:
        self.robot_ip = robot_ip
        self.agent_port = agent_port
        self.back_port = back_port
        self.back_host = back_host
        self.tablet_port = tablet_port
        self.ssh_user, self.ssh_password = ssh_user, ssh_password
        self.token = secrets.token_hex(16)
        self.writer: Optional[asyncio.StreamWriter] = None
        self.info: dict[str, Any] = {}
        self.status: dict[str, Any] = {}
        self.speaker_mode: Optional[str] = None
        self.playing = False
        self.state = "starting"          # starting | deploying | connected | lost | failed
        self.detail = ""
        self.mode = "direct"             # direct (laptop connects out) | connect_back (fallback)
        self.last_frame: Optional[tuple[dict, bytes]] = None
        self.frame_no = 0
        self._ids = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._frame_meta: Optional[dict] = None
        self._lost_at: Optional[float] = None
        self._deploying = False
        self.on_mic: Optional[Callable[[bytes], None]] = None
        self.on_event: Optional[Callable[[str, dict], None]] = None
        self._server: Optional[asyncio.base_events.Server] = None

    @property
    def connected(self) -> bool:
        return self.writer is not None

    @property
    def tablet_url(self) -> str:
        return "http://{}:{}/screen".format(TABLET_HOST, self.tablet_port)

    # ------------------------------------------------------------ lifecycle
    async def start(self, deploy: bool = True) -> None:
        if deploy:
            asyncio.create_task(self._watch(), name="pepper-link-watch")

    async def listen_back(self) -> None:
        """Fallback only: accept the agent's connection on back_port."""
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._accept, self.back_host, self.back_port)
        if self.back_port == 0:      # tests: the OS picked one
            self.back_port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
        if self._server is not None:
            self._server.close()
            self._server = None

    async def _watch(self) -> None:
        """Deploy now; reconnect when the link drops; redeploy when the agent stays away."""
        await self.deploy()
        last_ping = 0.0
        while True:
            await asyncio.sleep(1)
            if self.connected:
                if time.monotonic() - last_ping >= PING_EVERY_S:
                    last_ping = time.monotonic()
                    self.notify("ping")
                continue
            if self._deploying or self._lost_at is None:
                continue
            if time.monotonic() - self._lost_at > REDEPLOY_AFTER_S:
                await self.deploy()
            elif self.mode == "direct" and self.state == "lost":
                # The agent keeps listening for 45 s after the laptop goes: try again now.
                await self.connect_out(3.0)

    def _emit(self, kind: str, data: dict) -> None:
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:  # noqa: BLE001
                log.exception("robot event handler failed")

    def _set(self, state: str, detail: str) -> None:
        self.state, self.detail = state, detail
        self._emit("link", {})

    async def deploy(self) -> None:
        self._deploying = True
        try:
            self.mode = "direct"
            self._set("deploying", "starting the agent on Pepper over SSH")
            out = await asyncio.wait_for(asyncio.to_thread(self._deploy_blocking, None), 60)
            log.info("agent started on Pepper (%s); connecting to %s:%d",
                     out or "ok", self.robot_ip, self.agent_port)
            if await self.connect_out(OUTBOUND_WAIT_S):
                return
            # Fallback: the agent connects back, as before 2026-11-05.
            log.warning("could not reach Pepper's agent on port %d within %.0f s -- %s",
                        self.agent_port, OUTBOUND_WAIT_S, FALLBACK_NOTE)
            self.mode = "connect_back"
            self._set("deploying", FALLBACK_NOTE)
            await self.listen_back()
            laptop = laptop_ip_towards(self.robot_ip)
            await asyncio.wait_for(asyncio.to_thread(self._deploy_blocking, laptop), 60)
            deadline = time.monotonic() + CONNECT_WAIT_S
            while time.monotonic() < deadline and not self.connected:
                await asyncio.sleep(0.5)
            if not self.connected:
                tail = await asyncio.to_thread(self._robot_log_tail)
                raise RuntimeError(
                    "the agent never called back on port {}. Is Windows Firewall blocking "
                    "Python on this network? Robot log: {}".format(self.back_port, tail or "(empty)"))
        except Exception as exc:  # noqa: BLE001
            self._lost_at = time.monotonic()
            log.warning("Pepper agent: %s", str(exc) or type(exc).__name__)
            self._set("failed", str(exc) or type(exc).__name__)
        finally:
            self._deploying = False

    async def connect_out(self, wait_s: float) -> bool:
        """Connect to the agent's port (retrying while it starts up) and say hello."""
        deadline = time.monotonic() + wait_s
        last_err: Optional[BaseException] = None
        while time.monotonic() < deadline and not self.connected:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.robot_ip, self.agent_port), 3)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                await asyncio.sleep(0.5)
                continue
            try:
                self._write_to(writer, b"J", json.dumps({"ev": "hello", "token": self.token}).encode("utf-8"))
                kind, payload = await asyncio.wait_for(self._read(reader), 10)
                hello = json.loads(payload) if kind == b"J" else {}
                if hello.get("ev") != "hello":
                    raise ConnectionError("the agent did not say hello")
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                writer.close()
                await asyncio.sleep(0.5)
                continue
            self._attach(writer, hello, self.robot_ip)
            asyncio.create_task(self._serve(reader, writer), name="pepper-link")
            return True
        if not self.connected and last_err is not None:
            log.info("connect to Pepper's agent: %s", last_err or type(last_err).__name__)
        return self.connected

    def _deploy_blocking(self, laptop_ip: Optional[str]) -> str:
        """Upload and start the agent: listen mode (laptop_ip None) or connect-back."""
        c = self._ssh()
        try:
            self._run(c, "pkill -f '[p]epper_agent.py'; mkdir -p " + REMOTE_SCREEN)
            sftp = c.open_sftp()
            try:
                sftp.put(str(AGENT), REMOTE_AGENT)
                for name, local in SCREEN_FILES.items():
                    sftp.put(str(local), REMOTE_SCREEN + "/" + name)
                token_file = "{}/token-{}".format(REMOTE_DIR, os.getpid())
                with sftp.open(token_file, "w") as f:
                    f.write(self.token)
                sftp.chmod(token_file, 0o600)
            finally:
                sftp.close()
            for prefix in ROBOT_PYTHONPATHS:
                ok = self._run(c, "bash -lc '{}python -c \"import naoqi\" && echo NAOQI_OK'".format(prefix))
                if "NAOQI_OK" in ok:
                    break
            else:
                raise RuntimeError("Pepper's python cannot import naoqi: " + ok[-200:])
            if laptop_ip is None:
                args = "listen {} {} {}".format(self.agent_port, token_file, self.tablet_port)
            else:
                args = "{} {} {} {}".format(laptop_ip, self.back_port, token_file, self.tablet_port)
            self._run(c, "bash -lc '{}nohup python -u {} {} > {} 2>&1 &'".format(
                prefix, REMOTE_AGENT, args, REMOTE_LOG))
            return "python on the robot, " + ("listening" if laptop_ip is None else "connecting back")
        finally:
            c.close()

    def _ssh(self):
        import paramiko
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(self.robot_ip, username=self.ssh_user, password=self.ssh_password,
                  timeout=10, look_for_keys=False, allow_agent=False)
        return c

    @staticmethod
    def _run(c, cmd: str) -> str:
        _, out, err = c.exec_command(cmd, timeout=30)
        return (out.read() + err.read()).decode("utf-8", "replace").strip()

    def _robot_log_tail(self) -> str:
        try:
            c = self._ssh()
            try:
                return self._run(c, "tail -n 8 " + REMOTE_LOG)[-600:]
            finally:
                c.close()
        except Exception as exc:  # noqa: BLE001
            return "could not read it ({})".format(exc)

    async def stop_agent(self) -> None:
        """Graceful end: the agent gives the robot back when the link drops."""
        try:
            await asyncio.wait_for(asyncio.to_thread(self._stop_blocking), 15)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not stop the agent: %s", exc)

    def _stop_blocking(self) -> None:
        c = self._ssh()
        try:
            # SIGTERM skips the agent's own clean-up, so do the visible part here.
            self._run(c, "pkill -f '[p]epper_agent.py'")
        finally:
            c.close()

    # ------------------------------------------------------------ the socket
    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Fallback mode: the agent connected to us and must name the token first."""
        peer = writer.get_extra_info("peername")
        try:
            kind, payload = await asyncio.wait_for(self._read(reader, 64 * 1024), 10)
            hello = json.loads(payload) if kind == b"J" else {}
            if hello.get("ev") != "hello" or not secrets.compare_digest(
                    str(hello.get("token", "")), self.token):
                log.warning("refused a connection from %s (bad hello)", peer)
                writer.close()
                return
        except Exception:  # noqa: BLE001
            writer.close()
            return
        await self._session(reader, writer, hello, peer[0] if peer else "?")

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                       hello: dict, peer: str) -> None:
        self._attach(writer, hello, peer)
        await self._serve(reader, writer)

    def _attach(self, writer: asyncio.StreamWriter, hello: dict, peer: str) -> None:
        if self.writer is not None:
            self.writer.close()
        self.writer = writer
        self.info = hello.get("info") or {}
        self.speaker_mode = hello.get("speaker_mode")
        if hello.get("tablet_port"):
            self.tablet_port = int(hello["tablet_port"])
        self._lost_at = None
        how = "laptop connected out" if self.mode == "direct" else FALLBACK_NOTE
        log.info("Pepper agent linked (%s): %s, speaker via %s", how, self.info, self.speaker_mode)
        if hello.get("tablet_error"):
            log.error("Pepper's tablet page server did not start: %s", hello["tablet_error"])
        self._set("connected", "agent pid {} on {} ({})".format(hello.get("pid"), peer, how))

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                kind, payload = await asyncio.wait_for(self._read(reader), LINK_IDLE_S)
                if kind == b"M":
                    if self.on_mic:
                        self.on_mic(payload)
                elif kind == b"I":
                    if self._frame_meta is not None:
                        self.last_frame = (self._frame_meta, payload)
                        self.frame_no += 1
                        self._frame_meta = None
                elif kind == b"J":
                    self._on_json(json.loads(payload))
        except Exception as exc:  # noqa: BLE001
            why = "no frame for {:.0f} s".format(LINK_IDLE_S) if isinstance(exc, asyncio.TimeoutError) else exc
            log.warning("Pepper agent link closed: %s", why or type(exc).__name__)
        finally:
            if self.writer is writer:
                self.writer = None
                self.playing = False
                self._lost_at = time.monotonic()
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Pepper disconnected"))
                self._pending.clear()
                self._set("lost", "the agent's connection dropped")
            writer.close()

    @staticmethod
    async def _read(reader: asyncio.StreamReader, limit: int = FRAME_MAX) -> tuple[bytes, bytes]:
        head = await reader.readexactly(5)
        size = struct.unpack(">I", head[1:5])[0]
        if size > limit:
            raise ConnectionError("a frame of {} bytes is too big".format(size))
        return head[0:1], await reader.readexactly(size)

    def _on_json(self, msg: dict) -> None:
        if "id" in msg and msg.get("id") in self._pending:
            fut = self._pending.pop(msg["id"])
            if not fut.done():
                fut.set_result(msg)
            return
        ev = msg.get("ev")
        if ev == "frame":
            self._frame_meta = msg
        elif ev == "status":
            self.status = msg.get("status") or {}
            self.speaker_mode = self.status.get("speaker_mode") or self.speaker_mode
            self.playing = bool(self.status.get("playing"))
            self._emit("status", self.status)
        elif ev == "playing":
            self.playing = bool(msg.get("on"))
            self._emit("playing", {"on": self.playing})
        elif ev == "log":
            self._emit("log", {"level": msg.get("level") or "INFO", "msg": msg.get("msg") or ""})
        elif ev in ("tablet", "tap", "media"):
            self._emit(ev, msg)

    @staticmethod
    def _write_to(writer: asyncio.StreamWriter, kind: bytes, payload: bytes) -> None:
        writer.write(kind + struct.pack(">I", len(payload)) + payload)

    def _write(self, kind: bytes, payload: bytes) -> None:
        if self.writer is None:
            raise ConnectionError("Pepper is not connected")
        self._write_to(self.writer, kind, payload)

    async def call(self, cmd: str, timeout: float = CALL_TIMEOUT_S, **kw: Any) -> dict:
        self._ids += 1
        mid = self._ids
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        self._write(b"J", json.dumps({"id": mid, "cmd": cmd, **kw}).encode("utf-8"))
        try:
            reply = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)
        if not reply.get("ok"):
            raise RuntimeError(reply.get("error") or "Pepper refused " + cmd)
        return reply

    def notify(self, cmd: str, **kw: Any) -> bool:
        """A command with no reply (screen state, ping). False when not connected."""
        try:
            self._write(b"J", json.dumps({"cmd": cmd, **kw}).encode("utf-8"))
            return True
        except ConnectionError:
            return False

    def send_data(self, header: dict, data: bytes) -> bool:
        """A D frame: the answer to the tablet's request for a slide file."""
        head = json.dumps(header).encode("utf-8")
        try:
            self._write(b"D", struct.pack(">I", len(head)) + head + data)
            return True
        except ConnectionError:
            return False

    def send_audio(self, pcm24: bytes) -> None:
        """Queue 24 kHz mono PCM16 on Pepper's speaker."""
        self._write(b"S", pcm24)
        self.playing = True      # the agent confirms (and later clears) it
