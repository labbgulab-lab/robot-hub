"""Reachy Mini Wireless -- a real network device, found over mDNS.

Discovered on `_reachy-mini._tcp` with TXT `model=Reachy Mini Wireless` and a
`unit_id` that is the card key. The instance name is never the key: both
Reachys advertise as `reachy_mini`, so Bonjour renames whichever arrives
second to `reachy_mini-2`, and that suffix depends on boot order (PLAN.md 2.2).

This robot serves its own daemon on its own IP, so the hub talks to it
directly and never involves the Reachy Mini Control desktop app -- which
proxies whichever robot it holds onto laptop `127.0.0.1:8000`, the same single
address the Lite's daemon binds.

The desktop-app claim here is `require_absent`, and it is scoped **per robot**:
on 2026-09-14 the app held the Lite over USB while `reachy_chat` drove this
robot on an allocated port, and both stayed healthy (2.6). A globally scoped
claim would refuse a combination that is measured to work.

Launch target is `reachy_chat`'s `laptop_chat.py`. In the default "robot" mic
mode it runs **on the robot** over SSH (`--local-robot`, dashboard at
http://<robot-ip>:8765/), because the built-in mic is on the robot and nothing
streams it back (reachy_chat/docs/HUB-INTERFACE.md 1). A robot that lacks the
app is provisioned first with reachy_chat's `tools/deploy_robot_app.py`.
"laptop" mode is the old K11 path: a local child on an allocated port.

Settings read from `[robots.reachy_wireless.settings]`:
    reachy_chat_path   checkout to run `laptop_chat.py` from / deploy from
    python             interpreter; blank = <reachy_chat_path>/.venv/Scripts/python.exe
    mic_mode           "robot" (default, runs on the robot) | "laptop"
    robot_mic_match    robot capture device (default "reachymini_audio_src")
    robot_mic_rate     robot capture rate (default 16000)
    robot_dashboard_port  on-robot dashboard port (default 8765)
    volume             speaker volume set on connect (default 100)
    mic_device         exact capture device name, when it should not be guessed
    mic_match          substring used to find it instead (default "USBAudio")
    daemon_port        daemon port if it ever moves off 8000
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

from .. import announce as announce_helper
from ..keys import PROVIDER_LABELS, SPEECH_BACKEND
from ..supervisor import get_supervisor, shared_port_allocator
from .base import (AdapterUnavailable, Claim, Found, Health, RobotAdapter,
                   communicate_or_kill, thread_finishing_on_cancel)
from .reachy_common import DaemonError, DaemonRestarting, PollenDaemon

DEFAULT_DAEMON_PORT = 8000

# Tomer, 2026-09-23: every Reachy speaks at 100% by default. Robots ship at
# whatever the last owner left (reachy2 was 62%). `volume` overrides it.
DEFAULT_VOLUME = 100

# The K11 receiver enumerates under the generic USB-audio class name; this is
# the same needle `reachy_chat`'s own launcher probes for. It is a device-class
# hint, not a lab value, and `mic_device` overrides it.
DEFAULT_MIC_MATCH = "USBAudio"

# reachy_chat pays SDK init, VAD load and the Gemini client before it listens.
DASHBOARD_WAIT_S = 120.0

# Pollen's factory login. Both are overridable per site; the password also
# reads from REACHY_SSH_PASSWORD in .env so it need not sit in config.toml.
DEFAULT_SSH_USER = "pollen"
DEFAULT_SSH_PASSWORD = "root"
SSH_TIMEOUT_S = 30.0


def _ssh_clear(host: str, user: str, password: str) -> str:
    """Blocking; always called through a thread. Returns what is left running.

    The `[l]` / `[r]` bracket trick is load-bearing, and it is the reason this
    is not written the obvious way: `pkill -f` matches whole command lines,
    and the shell running this very command contains "laptop_chat.py" in its
    own. Written plainly, pkill kills its own parent shell, the count after it
    never runs, and the caller reports success having verified nothing. As a
    regex "[l]aptop_chat" still matches the real process; as a literal string
    it does not match itself.
    """
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, password=password, timeout=10)
        _in, out, _err = client.exec_command(
            "pkill -f '[l]aptop_chat.py' ; "
            "pkill -f '[r]obot_streaming_player.py' ; "
            "sleep 1 ; "
            "pgrep -f '[l]aptop_chat.py|[r]obot_streaming_player.py' | wc -l",
            timeout=SSH_TIMEOUT_S)
        lines = out.read().decode("utf-8", "replace").strip().splitlines()
        return lines[-1] if lines else "?"
    finally:
        client.close()

# --- robot mode (HUB-INTERFACE.md 1) -------------------------------------
# The built-in mic is physically on the robot and nothing streams it back, so
# reachy_chat runs ON the robot and the laptop only opens its dashboard.
# Deployed by reachy_chat/tools/deploy_robot_app.py + deploy_robot_player.py.
ROBOT_APP_DIR = "/home/pollen/reachy_chat"
ROBOT_PYTHON = "/venvs/mini_daemon/bin/python"
ROBOT_DASHBOARD_PORT = 8765
ROBOT_LOG = "/tmp/reachy_chat.out"
# Measured on reachy1-3, 2026-09-23: the mic is ALSA dsnoop
# `reachymini_audio_src` (in ~/.asoundrc), which opens mono at 16 kHz and is
# shared with the daemon.
DEFAULT_ROBOT_MIC_MATCH = "reachymini_audio_src"
DEFAULT_ROBOT_MIC_RATE = 16000
# Measured on reachy2: dashboard up 1 s after start, player ready 4 s later.
ROBOT_DASHBOARD_WAIT_S = 60.0
# deploy_robot_app.py on a factory robot: ~2.6 MB SFTP plus a pip install.
PROVISION_TIMEOUT_S = 600.0
# One cheap check that the robot has everything the app imports.
ROBOT_READY_CHECK = (
    "test -f {d}/laptop_chat.py && "
    "test -f /home/pollen/scripts/robot_streaming_player.py && "
    "test -f /home/pollen/scripts/robot_speech_tapper.py && "
    "{py} -c 'import google.genai, sounddevice, soundfile'").format(
        d=ROBOT_APP_DIR, py=ROBOT_PYTHON)


def _ssh_run(host: str, user: str, password: str, command: str,
             timeout_s: float = SSH_TIMEOUT_S,
             stdin_text: Optional[str] = None) -> tuple[int, str]:
    """Blocking; call through a thread. Returns (exit status, stdout+stderr).

    `stdin_text` is how a secret reaches the robot: written down the channel
    and read by the remote shell, so it is never part of any command line.
    """
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, password=password, timeout=10,
                       look_for_keys=False, allow_agent=False)
        inp, out, err = client.exec_command(command, timeout=timeout_s)
        if stdin_text is not None:
            inp.write(stdin_text)
            inp.flush()
            inp.channel.shutdown_write()
        text = (out.read() + err.read()).decode("utf-8", "replace")
        return out.channel.recv_exit_status(), text
    finally:
        client.close()

# Every process either mode leaves behind. Two of them fight over the audio
# device and the symptom is indistinguishable from a broken microphone.
LEFTOVER_NEEDLES = ("laptop_chat.py", "robot_streaming_player.py")


class ReachyWirelessAdapter(RobotAdapter):
    type_id = "reachy_wireless"
    display_name = "Reachy-Mini"
    reports_battery = False     # all 98 endpoints swept: no battery anywhere
    # The first launch on a factory robot installs reachy_chat onto it.
    launch_timeout_s = PROVISION_TIMEOUT_S + ROBOT_DASHBOARD_WAIT_S + 60
    # The hub sets `credential` (a KeyStore entry) just before launch().
    uses_speech_key = True
    credential: Optional[dict] = None
    # ...and `provider_env` ({"OPENAI_API_KEY": ..., ...}): one key per
    # provider, so the robot dashboard's backend picker can switch to any.
    provider_env: Optional[dict] = None

    def __init__(self, found: Found, config: Any, *,
                 port_allocator: Any = None, port: Optional[int] = None) -> None:
        super().__init__(found, config)
        self.settings = config.robot(self.type_id).settings
        self.port_allocator = port_allocator
        self._port = port
        self._daemon: Optional[PollenDaemon] = None
        self._mic_name: Optional[str] = None
        self._child_name = ""
        self._url: Optional[str] = None
        self._robot_running = False
        # Per-unit name from config.toml, so ten Reachys do not all log and
        # announce as "Reachy-Mini" (HUB-INTERFACE.md 2).
        try:
            key = self.stable_key(found)
        except RuntimeError:
            key = ""
        self.display_name = config.robot(self.type_id).name_for(
            key, type(self).display_name)

    # ------------------------------------------------------------ identity
    def stable_key(self, found: Found) -> str:
        unit_id = found.txt("unit_id") or found.meta.get("unit_id")
        if unit_id:
            return str(unit_id)
        mac = found.meta.get("mac")
        if mac:
            return str(mac).lower()
        raise RuntimeError(
            "this Reachy advertised no unit_id and no MAC, so its card cannot "
            "be keyed safely -- an IP is never an identity")

    # -------------------------------------------------------------- daemon
    def _base_url(self, found: Optional[Found] = None) -> str:
        found = found or self.found
        port = (self.settings.get("daemon_port")
                or found.port or DEFAULT_DAEMON_PORT)
        return "http://{}:{}".format(found.address, port)

    def _get_daemon(self, found: Optional[Found] = None) -> PollenDaemon:
        url = self._base_url(found)
        if self._daemon is None:
            self._daemon = PollenDaemon(url, name=self.display_name)
        elif self._daemon.base_url != url:
            # The hotspot reissues addresses freely; the card survives, the
            # HTTP client does not.
            old, self._daemon = self._daemon, PollenDaemon(
                url, name=self.display_name)
            self._daemon.daemon_version = old.daemon_version
        return self._daemon

    # ----------------------------------------------------------- lifecycle
    async def probe(self, found: Found) -> Health:
        self.found = found
        return await self._get_daemon(found).health()

    async def connect(self) -> None:
        daemon = self._get_daemon()
        health = await daemon.health()
        if not health["online"]:
            raise RuntimeError(health["detail"])
        holder = await daemon.lock_holder()
        if holder:
            self.notes.append(
                "an app named '{}' is already holding this robot".format(holder))
        # Wake the body the way the desktop app does -- a connected robot with
        # its head slumped reads as dead. Best-effort: a failed move is a note,
        # never a failed connect.
        volume = self.settings.get("volume", DEFAULT_VOLUME)
        for what, step in (("set volume to {}%".format(volume),
                            lambda: daemon.set_volume(volume)),
                           ("wake up", daemon.wake_up)):
            try:
                await step()
            except (DaemonError, DaemonRestarting) as exc:
                self.notes.append("could not {}: {}".format(what, exc))

    async def disconnect(self) -> None:
        await self.stop_system()
        daemon, self._daemon = self._daemon, None
        if daemon is not None:
            try:
                await daemon.go_to_sleep()
            except (DaemonError, DaemonRestarting):
                pass        # an unreachable robot cannot be put to sleep
            # No media_release() here: it switches the daemon's audio off and
            # the next app or chat on this robot then cannot open it.
            await daemon.aclose()

    async def announce(self, text: str) -> None:
        path = announce_helper.wav_path(self.config, text)
        await self._get_daemon().play_wav(path)

    async def system_status(self) -> dict[str, Any]:
        daemon = self._get_daemon()
        status = await daemon.system_status()
        status["mic"] = self._mic_label()
        return status

    # --------------------------------------------------------------- audio
    def _mic_label(self) -> str:
        if self._mic_mode() != "laptop":
            return "robot's built-in mic ({})".format(self._robot_mic_match())
        return self._laptop_mic_device() or "laptop capture device not found"

    def _robot_mic_match(self) -> str:
        return str(self.settings.get("robot_mic_match") or DEFAULT_ROBOT_MIC_MATCH)

    def _mic_mode(self) -> str:
        return str(self.settings.get("mic_mode") or "robot").strip().lower()

    def _laptop_mic_device(self) -> str:
        """The concrete capture endpoint, resolved -- never the word 'default'.

        A named claim is what makes the collision with NAO's device-less
        capture visible instead of silent (2.5).
        """
        if self._mic_name is not None:
            return self._mic_name
        configured = self.settings.get("mic_device")
        if configured:
            self._mic_name = str(configured)
            return self._mic_name

        needle = str(self.settings.get("mic_match") or DEFAULT_MIC_MATCH).lower()
        name = ""
        try:
            import sounddevice as sd   # optional: a hub without audio still runs
            for device in sd.query_devices():
                if (device.get("max_input_channels", 0) > 0
                        and needle in str(device.get("name", "")).lower()):
                    name = str(device["name"])
                    break
        except Exception as exc:  # noqa: BLE001
            self.notes.append(
                "could not enumerate capture devices ({}), so the microphone "
                "claim cannot name one".format(exc))
        if not name:
            self.notes.append(
                "no capture device matching '{}' is plugged in -- in laptop "
                "mic mode this robot will not hear anything".format(needle))
        self._mic_name = name
        return name

    # -------------------------------------------------------------- claims
    def claims(self) -> list[Claim]:
        claims: list[Claim] = []
        if self._mic_mode() == "laptop":
            device = self._laptop_mic_device()
            # Only a named device. ResourceBroker reads an empty audio_in value
            # as "whatever Windows calls default" -- that is NAO's claim, and
            # emitting it here would block NAO over a microphone this robot has
            # not got. The unresolved case is already a note on the card.
            if device:
                claims.append({"kind": "audio_in", "value": device,
                               "mode": "require"})
        # Scoped per robot, not globally: proven on 2026-09-14 that the
        # desktop app holding the Lite does not interfere with this robot, so
        # both Reachys can run at once (2.6). A bare "reachy_desktop_app"
        # would collide with the Lite's `require` and refuse that combination.
        claims.append({"kind": "exclusive",
                       "value": "reachy_desktop_app:{}".format(
                           self.stable_key(self.found)),
                       "mode": "require_absent"})
        return claims

    # -------------------------------------------------------------- launch
    def _reachy_chat_path(self) -> Path:
        path = self.config.path(self.type_id, "reachy_chat_path")
        if path is None or not path.is_dir():
            raise AdapterUnavailable(
                "set reachy_chat_path in config.toml to your reachy_chat "
                "checkout before this robot's system can be launched")
        return path

    def _python(self, root: Path) -> Path:
        configured = self.config.path(self.type_id, "python")
        if configured is not None:
            if not configured.is_file():
                raise AdapterUnavailable(
                    "the python set for reachy_wireless does not exist at "
                    "{}".format(configured))
            return configured
        scripts = "Scripts" if sys.platform == "win32" else "bin"
        name = "python.exe" if sys.platform == "win32" else "python"
        candidate = root / ".venv" / scripts / name
        if not candidate.is_file():
            raise AdapterUnavailable(
                "reachy_chat has no venv at {} -- create it, or set `python` "
                "in config.toml".format(candidate))
        return candidate

    def _allocate_port(self) -> int:
        if self._port is not None:
            return self._port
        allocator = self.port_allocator or shared_port_allocator(self.config)
        self._port = allocator.allocate(self.stable_key(self.found))
        return self._port

    async def ensure_zero_instances(self) -> list[str]:
        supervisor = get_supervisor()
        notes: list[str] = []
        if self._child_name:
            notes += await supervisor.stop(self._child_name)
            self._child_name = ""
        # Scoped to this robot's address: an unscoped sweep kills every other
        # robot's laptop_chat.py too (HUB-INTERFACE.md 1).
        if self._mic_mode() == "laptop":
            notes += await supervisor.kill_matching(LEFTOVER_NEEDLES,
                                                    scope=self.found.address)
        notes += await self._clear_robot_side()
        return notes

    async def _clear_robot_side(self) -> list[str]:
        """Kill leftovers on the robot too, not just on this laptop.

        A `robot_streaming_player.py` that survived on the robot reproduces
        exactly the audio contention this method exists to prevent, so
        clearing only the laptop half would verify nothing. Best-effort: if
        the robot cannot be reached the launch still proceeds, with a note
        saying what was not checked.
        """
        password = (self.settings.get("ssh_password")
                    or self.config.secret("REACHY_SSH_PASSWORD")
                    or DEFAULT_SSH_PASSWORD)
        user = str(self.settings.get("ssh_user") or DEFAULT_SSH_USER)
        try:
            remaining = await asyncio.wait_for(
                asyncio.to_thread(_ssh_clear, self.found.address, user, str(password)),
                SSH_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001
            return ["could not reach the robot over SSH to clear its own "
                    "processes ({}) -- a leftover player there would sound "
                    "like a broken microphone".format(exc)]
        return ["cleared robot-side processes (remaining: {})".format(remaining)]

    def _ssh_creds(self) -> tuple[str, str]:
        password = (self.settings.get("ssh_password")
                    or self.config.secret("REACHY_SSH_PASSWORD")
                    or DEFAULT_SSH_PASSWORD)
        return str(self.settings.get("ssh_user") or DEFAULT_SSH_USER), str(password)

    async def _ssh(self, command: str, timeout_s: float = SSH_TIMEOUT_S,
                   stdin_text: Optional[str] = None) -> tuple[int, str]:
        user, password = self._ssh_creds()
        return await thread_finishing_on_cancel(
            _ssh_run, self.found.address, user, password, command, timeout_s,
            stdin_text, timeout_s=timeout_s + 15)

    def _speech_backend(self) -> tuple[str, dict[str, str]]:
        """(reachy_chat --provider, the key entry) for this launch, or a
        sentence the card can show."""
        entry = self.credential
        if entry is None:
            raise AdapterUnavailable(
                "the hub has no speaking key yet -- add one in the Keys panel "
                "and pick it on this card")
        backend = SPEECH_BACKEND.get(entry["provider"])
        if backend is None:
            raise AdapterUnavailable(
                "'{}' is a {} key, and reachy_chat has no {} speaking backend "
                "yet -- pick a Gemini key on this card".format(
                    entry["label"], PROVIDER_LABELS[entry["provider"]],
                    PROVIDER_LABELS[entry["provider"]]))
        return backend, entry

    async def _provision_robot(self) -> None:
        """Install reachy_chat onto a robot that does not have it yet.

        Runs reachy_chat's own `tools/deploy_robot_app.py`, which copies the
        app, pip-installs what the daemon venv lacks and deploys the player --
        so a factory robot is ready after one Launch instead of three commands.
        """
        root = self._reachy_chat_path()
        python = self._python(root)
        self.notes.append("syncing reachy_chat onto the robot (a few minutes "
                          "the first time, seconds after that)")
        proc = await asyncio.create_subprocess_exec(
            str(python), str(root / "tools" / "deploy_robot_app.py"),
            "--robot-host", self.found.address,
            cwd=str(root), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await communicate_or_kill(proc, PROVISION_TIMEOUT_S)
        except asyncio.TimeoutError:
            raise RuntimeError("installing reachy_chat onto {} took longer than "
                               "{:.0f} s".format(self.display_name, PROVISION_TIMEOUT_S))
        if proc.returncode != 0:
            tail = out.decode("utf-8", "replace").strip()[-600:]
            raise RuntimeError("could not install reachy_chat onto {}:\n{}".format(
                self.display_name, tail))

    async def _launch_on_robot(self) -> str:
        """Start reachy_chat on the robot itself and return its dashboard URL."""
        provider, entry = self._speech_backend()    # refuse before touching the robot
        # Always sync, not only on a bare robot: deploy_robot_app skips
        # unchanged files, and a robot provisioned once otherwise keeps the
        # reachy_chat it was first given (2026-10-05: reachy2 had no backend
        # picker). On a bare robot this is also the pip install.
        await self._provision_robot()
        rc, _ = await self._ssh(ROBOT_READY_CHECK)
        if rc != 0:
            raise RuntimeError(
                "reachy_chat was synced onto {} but it still does not "
                "pass its own check -- run tools/deploy_robot_app.py "
                "--robot-host {} by hand to see why".format(
                    self.display_name, self.found.address))

        # The daemon's audio must be held, or the player's SDK falls back to
        # WebRTC and dies. Idempotent.
        try:
            await self._get_daemon().media_acquire()
        except (DaemonError, DaemonRestarting) as exc:
            self.notes.append("could not re-acquire the robot's media: {}".format(exc))

        port = int(self.settings.get("robot_dashboard_port") or ROBOT_DASHBOARD_PORT)
        rate = int(self.settings.get("robot_mic_rate") or DEFAULT_ROBOT_MIC_RATE)
        args = ["--local-robot", "--host", "0.0.0.0", "--no-browser",
                "--port", str(port),
                "--robot-id", self.stable_key(self.found),
                "--robot-name", self.display_name,
                "--provider", provider,
                "--mic-match", self._robot_mic_match(),
                "--mic-rate", str(rate)]
        import shlex
        # The key (and its id and label) arrive on stdin and become the app's
        # environment: never a file on the robot, never a command-line word a
        # `ps` could show. reachy_chat's credentials.resolve() reads them
        # first. Any .gemini_key an older deploy left is deleted on the way.
        # setsid + nohup + every fd redirected: the SSH session returns at
        # once and closing it cannot take the app down with it.
        # Every other provider's key follows the same way, one line each, so
        # the dashboard's backend picker (GPT-Live, ElevenLabs voice) has one.
        provider_env = self.provider_env or {}
        env_names = sorted(provider_env)
        env_reads = "".join("IFS= read -r {0} && export {0} && ".format(n)
                            for n in env_names)
        command = (
            "IFS= read -r REACHY_HUB_KEY && IFS= read -r REACHY_HUB_KEY_ID && "
            "IFS= read -r REACHY_HUB_KEY_LABEL && "
            "export REACHY_HUB_KEY REACHY_HUB_KEY_ID REACHY_HUB_KEY_LABEL && "
            "{env}rm -f {d}/.gemini_key && cd {d} && "
            # Only the app goes in the background, inside the braces. A bare
            # `a && b && app &` backgrounds the whole chain, and a background
            # job's stdin is /dev/null -- the reads got nothing, the app never
            # started, and "started" was echoed anyway (reachy3, 2026-10-05).
            "{{ setsid nohup {py} laptop_chat.py {a} > {log} 2>&1 < /dev/null & "
            "echo started; }}").format(
                env=env_reads, d=ROBOT_APP_DIR, py=ROBOT_PYTHON,
                a=" ".join(shlex.quote(x) for x in args), log=ROBOT_LOG)
        secret = "\n".join(
            str(v).replace("\n", " ").strip()
            for v in (entry["key"], entry["id"], entry["label"],
                      *(provider_env[n] for n in env_names))) + "\n"
        rc, out = await self._ssh(command, stdin_text=secret)
        if rc != 0 or "started" not in out:
            raise RuntimeError("could not start reachy_chat on {}: {}".format(
                self.display_name, out.strip()[-300:]))

        url = "http://{}:{}/".format(self.found.address, port)
        if not await get_supervisor().wait_for_http(url, ROBOT_DASHBOARD_WAIT_S):
            _, tail = await self._ssh("tail -15 {}".format(ROBOT_LOG))
            raise RuntimeError(
                "reachy_chat started on {} but its dashboard never answered at "
                "{} -- its last output:\n{}".format(self.display_name, url, tail))
        self._url = url
        self._robot_running = True
        return url

    async def launch(self) -> str:
        if self._mic_mode() != "laptop":
            return await self._launch_on_robot()
        root = self._reachy_chat_path()
        python = self._python(root)
        script = root / "laptop_chat.py"
        if not script.is_file():
            raise AdapterUnavailable(
                "laptop_chat.py is not in {} -- check reachy_chat_path".format(root))

        port = self._allocate_port()
        supervisor = get_supervisor()
        self._child_name = "reachy_chat:{}".format(self.stable_key(self.found))
        argv = [str(python), str(script),
                "--robot-host", self.found.address,
                "--port", str(port),
                "--robot-id", self.stable_key(self.found),
                "--robot-name", self.display_name,
                "--no-browser"]   # the hub opens the tab itself

        await supervisor.start(self._child_name, argv, cwd=root, port=port,
                               owner=self.stable_key(self.found),
                               log_prefix=self.display_name)
        url = "http://127.0.0.1:{}/".format(port)
        if not await supervisor.wait_for_http(url, DASHBOARD_WAIT_S,
                                              name=self._child_name):
            await supervisor.stop(self._child_name)
            self._child_name = ""
            raise RuntimeError(
                "reachy_chat never opened its dashboard on port {} within "
                "{:.0f} s -- the lines above are its own output".format(
                    port, DASHBOARD_WAIT_S))
        self._url = url
        return url

    async def stop_system(self) -> list[str]:
        if self._mic_mode() != "laptop":
            # Always, not only when this hub session launched it: after a hub
            # restart the app is still running on the robot.
            self._robot_running = False
            self._url = None
            return await self._clear_robot_side()
        if not self._child_name:
            return []
        notes = await get_supervisor().stop(self._child_name)
        self._child_name = ""
        self._url = None
        return notes
