"""The laptop end of the link to Pepper.

`agent/pepper_agent.py` runs on the robot (Python 2.7, NAOqi 2.5) and connects
out to this laptop; see its docstring for the frame format. This module

  * uploads and starts that agent over SSH (nao/nao), at start-up and again
    whenever it has been gone for a while,
  * accepts its connection (one at a time, token-checked),
  * turns commands into awaitable calls, and hands microphone audio and
    camera frames to whoever subscribed.

Pepper's own address comes from the hub (argv). The laptop's address on
Pepper's network is the source address the OS picks to reach Pepper.
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

AGENT = Path(__file__).resolve().parent / "agent" / "pepper_agent.py"
REMOTE_DIR = "/home/nao/robothub"
REMOTE_AGENT = REMOTE_DIR + "/pepper_agent.py"
REMOTE_LOG = REMOTE_DIR + "/pepper_agent.log"
ROBOT_PYTHONPATHS = ["", "PYTHONPATH=/opt/aldebaran/lib/python2.7/site-packages:$PYTHONPATH "]
CONNECT_WAIT_S = 60.0
REDEPLOY_AFTER_S = 20.0
CALL_TIMEOUT_S = 8.0


def laptop_ip_towards(robot_ip: str) -> str:
    """The address Pepper should use to reach this laptop."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((robot_ip, 9559))
        return s.getsockname()[0]
    finally:
        s.close()


class RobotLink:
    def __init__(self, robot_ip: str, listen_port: int, *,
                 ssh_user: str = "nao", ssh_password: str = "nao") -> None:
        self.robot_ip = robot_ip
        self.listen_port = listen_port
        self.ssh_user, self.ssh_password = ssh_user, ssh_password
        self.token = secrets.token_hex(16)
        self.writer: Optional[asyncio.StreamWriter] = None
        self.info: dict[str, Any] = {}
        self.status: dict[str, Any] = {}
        self.speaker_mode: Optional[str] = None
        self.playing = False
        self.state = "starting"          # starting | deploying | connected | lost | failed
        self.detail = ""
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

    # ------------------------------------------------------------ lifecycle
    async def start(self, deploy: bool = True) -> None:
        self._server = await asyncio.start_server(self._accept, "0.0.0.0", self.listen_port)
        if self.listen_port == 0:      # tests: the OS picked one
            self.listen_port = self._server.sockets[0].getsockname()[1]
        if deploy:
            asyncio.create_task(self._watch(), name="pepper-link-watch")

    async def _watch(self) -> None:
        """Deploy now; redeploy whenever the agent stays away."""
        await self.deploy()
        while True:
            await asyncio.sleep(3)
            if self.connected or self._deploying:
                continue
            if self._lost_at is not None and time.monotonic() - self._lost_at > REDEPLOY_AFTER_S:
                await self.deploy()

    def _emit(self, kind: str, data: dict) -> None:
        if self.on_event:
            try:
                self.on_event(kind, data)
            except Exception:  # noqa: BLE001
                log.exception("robot event handler failed")

    async def deploy(self) -> None:
        self._deploying = True
        self.state, self.detail = "deploying", "starting the agent on Pepper over SSH"
        self._emit("link", {})
        try:
            laptop = laptop_ip_towards(self.robot_ip)
            out = await asyncio.wait_for(asyncio.to_thread(self._deploy_blocking, laptop), 60)
            log.info("agent started on Pepper (%s), waiting for it to call %s:%d",
                     out or "ok", laptop, self.listen_port)
            deadline = time.monotonic() + CONNECT_WAIT_S
            while time.monotonic() < deadline and not self.connected:
                await asyncio.sleep(0.5)
            if not self.connected:
                tail = await asyncio.to_thread(self._robot_log_tail)
                raise RuntimeError(
                    "the agent never connected back to {}:{} -- is Windows Firewall "
                    "blocking Python on this network? Robot log: {}".format(
                        laptop, self.listen_port, tail or "(empty)"))
        except Exception as exc:  # noqa: BLE001
            self.state, self.detail = "failed", str(exc) or type(exc).__name__
            self._lost_at = time.monotonic()
            log.warning("Pepper agent: %s", self.detail)
            self._emit("link", {})
        finally:
            self._deploying = False

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

    def _deploy_blocking(self, laptop_ip: str) -> str:
        c = self._ssh()
        try:
            self._run(c, "pkill -f '[p]epper_agent.py'; mkdir -p " + REMOTE_DIR)
            sftp = c.open_sftp()
            try:
                sftp.put(str(AGENT), REMOTE_AGENT)
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
            self._run(c, "bash -lc '{}nohup python -u {} {} {} {} > {} 2>&1 &'".format(
                prefix, REMOTE_AGENT, laptop_ip, self.listen_port, token_file, REMOTE_LOG))
            return "python on the robot"
        finally:
            c.close()

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
        peer = writer.get_extra_info("peername")
        try:
            kind, payload = await asyncio.wait_for(self._read(reader), 10)
            hello = json.loads(payload) if kind == b"J" else {}
            if hello.get("ev") != "hello" or not secrets.compare_digest(
                    str(hello.get("token", "")), self.token):
                log.warning("refused a connection from %s (bad hello)", peer)
                writer.close()
                return
        except Exception:  # noqa: BLE001
            writer.close()
            return
        if self.writer is not None:
            self.writer.close()
        self.writer = writer
        self.info = hello.get("info") or {}
        self.speaker_mode = hello.get("speaker_mode")
        self.state, self.detail = "connected", "agent pid {} on {}".format(hello.get("pid"), peer[0])
        self._lost_at = None
        log.info("Pepper agent connected: %s, speaker via %s", self.info, self.speaker_mode)
        self._emit("link", {})
        try:
            while True:
                kind, payload = await self._read(reader)
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
            log.warning("Pepper agent link closed: %s", exc or type(exc).__name__)
        finally:
            if self.writer is writer:
                self.writer = None
                self.playing = False
                self.state, self.detail = "lost", "the agent's connection dropped"
                self._lost_at = time.monotonic()
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("Pepper disconnected"))
                self._pending.clear()
                self._emit("link", {})
            writer.close()

    @staticmethod
    async def _read(reader: asyncio.StreamReader) -> tuple[bytes, bytes]:
        head = await reader.readexactly(5)
        size = struct.unpack(">I", head[1:5])[0]
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

    def _write(self, kind: bytes, payload: bytes) -> None:
        if self.writer is None:
            raise ConnectionError("Pepper is not connected")
        self.writer.write(kind + struct.pack(">I", len(payload)) + payload)

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

    def send_audio(self, pcm24: bytes) -> None:
        """Queue 24 kHz mono PCM16 on Pepper's speaker."""
        self._write(b"S", pcm24)
        self.playing = True      # the agent confirms (and later clears) it
