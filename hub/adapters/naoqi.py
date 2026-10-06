"""NAO -- reached only through Python 2.7 subprocesses (PLAN.md 2.7).

NAOqi's SDK is Python 2.7 only, so the hub can never import `naoqi`. Every
call here is `hub/adapters/nao2/agent2.py` run under the configured Python 2.7
with the pynaoqi SDK on PYTHONPATH and PATH, driven asynchronously with a
timeout so a slow robot cannot touch the event loop (2.4, 13.1).

Liveness is a **successful ALProxy call**, never an open socket: a TCP connect
to 9559 succeeds while the broker still refuses, which happened twice on
2026-09-14 with ping steady at 1 ms (2.3). The helper retries the broker
handshake internally and this module retries the whole call on top.

NAO is the only one of the four robots that reports a battery.

The microphone claim is the important one. `NAO_LLM`'s capture calls
`sd.InputStream(...)` with no `device=`, so it takes whatever Windows
currently calls the default input -- which may be the K11 the wireless Reachy
is already listening through. The failure looks exactly like a broken
microphone and that class of failure has already cost a demo (2.5).

Settings read from `[robots.naoqi.settings]`:
    python2         Python 2.7 interpreter
    pynaoqi_sdk     the pynaoqi SDK root (the doubled directory name is real)
    port            NAOqi broker port (default 9559)
    nao_llm_path    the NAO_LLM checkout -- the Launch target
    nao_llm_python  interpreter; blank = <nao_llm_path>/venv/Scripts/python.exe
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from ..supervisor import child_env, get_supervisor, shared_port_allocator
from .base import (AdapterUnavailable, Claim, Found, Health, PostureRefused,
                   RobotAdapter, communicate_or_kill)


def _env_names(path: Path) -> set[str]:
    """The names a dotenv file sets to something non-empty. Never the values."""
    names: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return names
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):]
        name, sep, value = line.partition("=")
        if sep and not name.startswith("#") and value.strip().strip("'\""):
            names.add(name.strip())
    return names

AGENT2 = Path(__file__).resolve().parent / "nao2" / "agent2.py"

DEFAULT_BROKER_PORT = 9559
CALL_TIMEOUT_S = 12.0
CALL_RETRIES = 2            # on top of the helper's own broker retries
CALL_BACKOFF_S = 0.8

# NAO_LLM loads faster-whisper before uvicorn binds, so first start is slow.
WEB_UI_WAIT_S = 110.0

# NAO_LLM reads its web-UI port from a YAML config only -- there is no flag.
GENERATED_CONFIG = "config.hub-generated.yaml"
# NAO_LLM speaks through a small server on the robot (nao_speaker_server.py,
# installed by its deploy_nao.py) and refuses to start without it. Launch now
# starts it when it is not answering (2026-10-05: it had to be run by hand,
# and it took longer than deploy_nao.py's own wait to come up).
SPEAKER_PORT = 9600
SPEAKER_DEPLOY_TIMEOUT_S = 150.0
SPEAKER_UP_WAIT_S = 60.0

_PATCH_CONFIG = (
    "import json, sys, yaml\n"
    "src, dst, host, port, ip = sys.argv[1:6]\n"
    "data = yaml.safe_load(open(src, encoding='utf-8')) or {}\n"
    "data.setdefault('server', {})['host'] = host\n"
    "data['server']['port'] = int(port)\n"
    "data.setdefault('nao', {})['ip'] = ip\n"
    "yaml.safe_dump(data, open(dst, 'w', encoding='utf-8'),\n"
    "               sort_keys=False, allow_unicode=True)\n"
    "print(json.dumps([data.get(s, {}).get('api_key_env')\n"
    "                  for s in ('llm', 'tts')]))\n"
)

# Operator posture buttons. Every one of them powers the motors, so each is
# refused while a joint is this hot (degrees C, ALMemory's joint sensors).
# Standing holds every leg motor under load, so its limit is lower.
# 2026-10-05: the right hip reached 92 C and NAO had to cool with motors off.
HEAT_LIMIT_C = 70.0
STAND_HEAT_LIMIT_C = 60.0
# SDK load + temperature read + the move itself (lying down from standing is
# the slowest, well under a minute). No retries: a motion is never re-sent.
POSTURE_TIMEOUT_S = 90.0
POSTURE_DONE = {
    "sit": "sitting",
    "lie": "lying on its back",
    "stand": "standing",
}
POSTURE_TARGET = {"sit": "Sit", "lie": "LyingBack", "stand": "Stand"}
POSTURE_MOVING = {
    "sit": "sitting down",
    "lie": "lying down",
    "stand": "standing up",
}

_SIDES = {"L": "left ", "R": "right "}
_PARTS = (("Hip", "hip"), ("Knee", "knee"), ("Ankle", "ankle"),
          ("Shoulder", "shoulder"), ("Elbow", "elbow"), ("Wrist", "wrist"),
          ("Hand", "hand"), ("Head", "neck"))


def joint_label(joint: str) -> str:
    """'RHipPitch' -> 'right hip'. Unknown names come back unchanged."""
    side, rest = "", joint
    if joint[:1] in _SIDES and joint[1:2].isupper():
        side, rest = _SIDES[joint[0]], joint[1:]
    for prefix, label in _PARTS:
        if rest.startswith(prefix):
            return side + label
    return joint


def _degrees(value: Any) -> str:
    return "{:.0f} °C".format(float(value))


def heat_refusal(joint: str, temp_c: float, limit_c: float, name: str) -> str:
    where = "NAO's {} ({}) is at {}".format(joint_label(joint), joint,
                                            _degrees(temp_c))
    if name == "stand":
        return ("{} — standing keeps every leg motor loaded; let it cool "
                "below {} first".format(where, _degrees(limit_c)))
    return "{} — let it cool below {} before moving it".format(
        where, _degrees(limit_c))


# --- Teaching NAO / Pepper a new WiFi (the card's "Add WiFi...") -------------
# Each lab member brings their own phone hotspot. connman on the robot keeps
# every network it has joined (NAO knew nine on 2026-10-06), but the `nao`
# user cannot write connman's settings without joining: /var/lib/connman is
# root's and `nao` has no sudo. So unlike Reachy this joins at once, and the
# new hotspot must be on and in range. connmanctl is driven interactively
# because its passphrase prompt only exists in agent mode -- the route that
# worked by hand on NAO and Pepper (profiles/naoqi.md; ALConnectionManager did
# not, PEPPER-FIRST-CONNECTION.md).
WIFI_JOIN_TIMEOUT_S = 90.0
DEFAULT_NAO_SSH_USER = "nao"
DEFAULT_NAO_SSH_PASSWORD = "nao"


def _connman_service(text: str, ssid: str) -> Optional[tuple[str, str]]:
    """(service id, security) for `ssid` in `connmanctl services` output.

    Matched on the id, which carries the SSID in hex
    (wifi_<mac>_<hex ssid>_managed_<security>), never on the printed name:
    names are padded columns and may contain spaces.
    """
    want = ssid.encode("utf-8").hex()
    for m in re.finditer(r"(wifi_[0-9a-f]+_([0-9a-f]+)_managed_([a-z0-9]+))", text):
        if m.group(2) == want:
            return m.group(1), m.group(3)
    return None


def _connman_join(host: str, user: str, login: str, ssid: str, passphrase: str,
                  timeout_s: float = WIFI_JOIN_TIMEOUT_S) -> str:
    """Blocking; call through a thread. Returns "joined" when connman said
    so, "moved" when the session dropped right after the passphrase (the robot
    left this network, as it should), and raises RuntimeError otherwise."""
    import time

    import paramiko

    deadline = time.monotonic() + timeout_s
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, username=user, password=login, timeout=10,
                   look_for_keys=False, allow_agent=False)
    buf = {"text": ""}
    try:
        chan = client.invoke_shell(width=300)

        def read_until(marks: tuple[str, ...], wait_s: float) -> Optional[str]:
            end = min(deadline, time.monotonic() + wait_s)
            while time.monotonic() < end:
                if chan.recv_ready():
                    buf["text"] += chan.recv(65536).decode("utf-8", "replace")
                    for mark in marks:
                        if mark in buf["text"]:
                            return mark
                elif chan.closed or chan.exit_status_ready():
                    return None
                else:
                    time.sleep(0.1)
            return None

        chan.send("connmanctl\n")
        if read_until(("connmanctl>",), 15) is None:
            raise RuntimeError("connmanctl did not start on the robot")
        chan.send("agent on\n")
        read_until(("Agent registered", "already registered"), 10)

        found = None
        for _ in range(2):                  # a phone hotspot can miss one scan
            buf["text"] = ""
            chan.send("scan wifi\n")
            read_until(("Scan completed",), 25)
            buf["text"] = ""
            chan.send("services\n")
            read_until(("\n",), 5)
            time.sleep(1.5)                 # the list arrives in pieces
            read_until(("\x00",), 0.5)
            found = _connman_service(buf["text"], ssid)
            if found:
                break
        if found is None:
            raise RuntimeError(
                "the robot cannot see “{}” -- is the hotspot on, on 2.4 GHz "
                "(iPhone: Maximize Compatibility), with its settings screen "
                "open, and is the name typed exactly?".format(ssid))
        service, security = found
        if security not in ("psk", "none"):
            raise RuntimeError("“{}” uses {} security; only a normal "
                               "password (WPA2) hotspot works".format(ssid, security))

        buf["text"] = ""
        chan.send("connect {}\n".format(service))
        mark = read_until(("Passphrase?", "Connected", "Already connected",
                           "Error", "Input/output error"), 30)
        if mark == "Passphrase?":
            buf["text"] = ""
            chan.send(passphrase + "\n")
            mark = read_until(("Connected", "Retry", "Error", "Invalid",
                               "Input/output error"), 45)
        if mark in ("Connected", "Already connected"):
            return "joined"
        if mark is None:
            return "moved"                  # the session dropped: it left us
        if mark == "Retry":
            chan.send("no\n")
            raise RuntimeError("wrong password for “{}”".format(ssid))
        raise RuntimeError("connman refused: {}".format(
            buf["text"].strip().splitlines()[-1][:200] if buf["text"].strip() else mark))
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


_ID_META_KEYS = ("head_id", "body_id", "robot_id", "serial", "unit_id")
_HOST_META_KEYS = ("hostname", "server", "instance", "name")


class NaoqiAdapter(RobotAdapter):
    type_id = "naoqi"
    display_name = "NAOqi"
    reports_battery = True      # the only robot of the four that reports one
    postures = tuple(POSTURE_DONE)
    posture_timeout_s = POSTURE_TIMEOUT_S
    # Speaker-server deploy (up to ~3.5 min) plus NAO_LLM's own start-up.
    launch_timeout_s = SPEAKER_DEPLOY_TIMEOUT_S + SPEAKER_UP_WAIT_S + WEB_UI_WAIT_S + 30

    def __init__(self, found: Found, config: Any, *,
                 port_allocator: Any = None, port: Optional[int] = None) -> None:
        super().__init__(found, config)
        # Pepper shares NAO's Python 2.7 and SDK: its own section only needs
        # what differs, the rest falls back to [robots.naoqi].
        self.settings = {**config.robot("naoqi").settings,
                         **config.robot(self.type_id).settings}
        self.port_allocator = port_allocator
        self._ui_port = port
        self._child_name = ""
        self._identity: dict[str, Any] = {}
        # Loading the pynaoqi SDK costs several seconds of DLL work per start,
        # so two of these must never run at once.
        self._lock = asyncio.Lock()
        self._python2 = self._require_python2()
        self._sdk = self._require_sdk()

    # ------------------------------------------------------- prerequisites
    def _setting_path(self, key: str) -> Optional[Path]:
        return self.config.path(self.type_id, key) or self.config.path("naoqi", key)

    def _require_python2(self) -> Path:
        path = self._setting_path("python2")
        if path is None or not path.is_file():
            raise AdapterUnavailable(
                "NAO needs Python 2.7: install it and set python2 in "
                "config.toml (NAOqi's SDK has no Python 3 build)")
        return path

    def _require_sdk(self) -> Path:
        path = self._setting_path("pynaoqi_sdk")
        if path is None or not (path / "lib").is_dir():
            raise AdapterUnavailable(
                "the pynaoqi 2.8 SDK was not found: download it and set "
                "pynaoqi_sdk in config.toml to the folder containing lib/")
        return path

    # ------------------------------------------------------------ identity
    def stable_key(self, found: Found) -> str:
        """Never the IP, and never the mDNS instance name.

        The head id is the ideal key, but it costs a Python 2.7 subprocess and
        `stable_key` is synchronous and on the event loop -- so it is read at
        connect time for display only, and the key comes from what discovery
        already knows.
        """
        for key in _ID_META_KEYS:
            value = found.meta.get(key)
            if value:
                return str(value)
        mac = found.meta.get("mac")
        if mac:
            return str(mac).lower()
        for key in _HOST_META_KEYS:
            value = found.meta.get(key)
            if value and not str(value).replace(".", "").isdigit():
                return "naoqi:{}".format(str(value).rstrip(".").lower())
        raise RuntimeError(
            "this NAO was found with neither a robot id, a MAC, nor a "
            "hostname, so its card cannot be keyed safely")

    # ------------------------------------------------------------- calling
    def _broker_port(self) -> int:
        try:
            return int(self.settings.get("port") or DEFAULT_BROKER_PORT)
        except (TypeError, ValueError):
            return DEFAULT_BROKER_PORT

    def _env(self) -> dict[str, str]:
        return child_env(
            overrides={"PYTHONPATH": str(self._sdk / "lib"),
                       "PYTHONIOENCODING": "utf-8"},
            prepend_path=[str(self._sdk / "bin")],
        )

    async def _call(self, command: str, *, retries: int = CALL_RETRIES,
                    timeout: float = CALL_TIMEOUT_S, answer_any: bool = False,
                    **payload: Any) -> dict[str, Any]:
        """Run one command in Python 2.7 and return its single JSON line.

        `answer_any` hands back whatever the helper answered, refusals
        included, so the caller can word them; only a helper that never
        answered raises. A motion command passes `retries=0`.
        """
        if not AGENT2.is_file():
            raise AdapterUnavailable(
                "the Python 2.7 helper {} is missing from this "
                "checkout".format(AGENT2.name))
        message = json.dumps({"cmd": command, "ip": self.found.address,
                              "port": self._broker_port(), **payload})

        last = "no attempt was made"
        for attempt in range(retries + 1):
            try:
                async with self._lock:
                    result = await self._run_once(message, timeout)
            except asyncio.TimeoutError:
                last = "Python 2.7 did not answer within {:.0f} s".format(
                    timeout)
            except Exception as exc:  # noqa: BLE001
                last = "{}: {}".format(type(exc).__name__, exc)
            else:
                if result.get("ok") or answer_any:
                    return result
                last = str(result.get("error") or "the robot refused the call")
            if attempt < retries:
                await asyncio.sleep(CALL_BACKOFF_S * (attempt + 1))

        if retries == 0:
            raise RuntimeError("NAO did not complete {} ({})".format(command, last))
        raise RuntimeError(
            "NAO refused {} after {} attempts ({}) -- port 9559 opens before "
            "the broker is ready, so this is a real refusal, not a race".format(
                command, retries + 1, last))

    async def _run_once(self, message: str,
                        timeout: float = CALL_TIMEOUT_S) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            str(self._python2), str(AGENT2),
            cwd=str(AGENT2.parent),
            env=self._env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(message.encode("utf-8")), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # hub/core.py cancels a probe that overruns its own timeout. The
            # cancellation alone does not reach Python 2.7, so without this the
            # child outlives the call and the next probe starts another.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise

        for line in stdout.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        detail = stderr.decode("utf-8", "replace").strip().splitlines()
        return {"ok": False,
                "error": detail[-1] if detail else "the helper printed nothing"}

    # ----------------------------------------------------------- lifecycle
    async def probe(self, found: Found) -> Health:
        self.found = found
        try:
            result = await self._call("battery")
        except Exception as exc:  # noqa: BLE001
            return {"online": False, "degraded": False,
                    "detail": str(exc), "battery": None}
        battery = result.get("battery")
        detail = "broker answering"
        if isinstance(battery, int):
            detail = "broker answering, battery {}%".format(battery)
        return {"online": True, "degraded": False, "detail": detail,
                "battery": battery if isinstance(battery, int) else None}

    async def connect(self) -> None:
        self._identity = await self._call("identity")
        head = self._identity.get("head_id")
        if head:
            self.notes.append("head {}".format(head))

    async def disconnect(self) -> None:
        await self.stop_system()
        self._identity = {}

    async def announce(self, text: str) -> None:
        await self._call("say", text=text)

    async def system_status(self) -> dict[str, Any]:
        if not self._identity:
            try:
                self._identity = await self._call("identity")
            except Exception:  # noqa: BLE001
                return {}
        return {
            "daemon_version": self._identity.get("system_version"),
            # NAO_LLM listens through the laptop, not through NAO's own array,
            # even though all four onboard mics measured healthy.
            "mic": "Windows default input (NAO_LLM captures with no device=)",
        }

    # ------------------------------------------------------------- WiFi
    async def join_wifi(self, ssid: str, passphrase: str) -> str:
        """Teach the robot another hotspot: it joins now and keeps it.

        Returns a sentence for the card. The robot leaves this laptop's
        network on success, so its card goes dim until the laptop follows.
        """
        ssid = (ssid or "").strip()
        if not ssid or len(ssid.encode("utf-8")) > 32:
            raise RuntimeError("a WiFi name has 1 to 32 characters")
        if not 8 <= len(passphrase or "") <= 63:
            raise RuntimeError("a WiFi password has 8 to 63 characters")
        user = str(self.settings.get("ssh_user") or DEFAULT_NAO_SSH_USER)
        login = str(self.settings.get("ssh_password")
                    or self.config.secret("NAO_SSH_PASSWORD")
                    or DEFAULT_NAO_SSH_PASSWORD)
        host = self.found.address
        how = await asyncio.wait_for(
            asyncio.to_thread(_connman_join, host, user, login, ssid, passphrase),
            WIFI_JOIN_TIMEOUT_S + 15)
        if how == "moved":
            # The session dropped. Still answering here means it never left.
            await asyncio.sleep(4)
            if await self._still_here():
                raise RuntimeError(
                    "the robot is still on this network -- it could not join "
                    "“{}” (check the password)".format(ssid))
        return ("{} joined “{}” and will remember it. Connect this laptop to "
                "“{}” to see it again.".format(self.display_name, ssid, ssid))

    async def _still_here(self) -> bool:
        try:
            _r, w = await asyncio.wait_for(
                asyncio.open_connection(self.found.address, self._broker_port()), 3.0)
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        return True

    # ----------------------------------------------------------- posture
    async def posture(self, name: str) -> str:
        """Sit / lie / stand from the card. Returns a sentence for the card.

        One helper run reads every joint temperature and, only if the hottest
        is under the limit, moves -- the guard and the motion cannot be
        separated by a stale reading. Sit and lie end with the motors off so
        NAO rests without heating; stand leaves them on. Raises
        PostureRefused for the heat guard, RuntimeError for anything else.
        """
        if name not in POSTURE_DONE:
            raise PostureRefused("unknown posture {!r}; NAO knows {}".format(
                name, ", ".join(POSTURE_DONE)))
        limit = STAND_HEAT_LIMIT_C if name == "stand" else HEAT_LIMIT_C
        try:
            result = await self._call("posture", retries=0,
                                      timeout=POSTURE_TIMEOUT_S, answer_any=True,
                                      name=name, max_temp_c=limit)
        except AdapterUnavailable:
            raise
        except RuntimeError as exc:
            # Killing the helper does not stop a motion NAO already started,
            # and the motors-off step after it never ran.
            raise RuntimeError(
                "no answer from NAO while {} — check on it; if it moved, its "
                "motors may still be on ({})".format(POSTURE_MOVING[name], exc)
            ) from exc

        refused = result.get("refused")
        if refused == "hot":
            raise PostureRefused(heat_refusal(
                str(result.get("joint")), result.get("temp_c", 0.0),
                result.get("limit_c", limit), name))
        if refused == "no_temperatures":
            raise PostureRefused(
                "NAO reported no joint temperatures, so it is not safe to "
                "power its motors — check it before moving it")
        if not result.get("ok"):
            if result.get("reached") is False:
                raise RuntimeError(
                    "NAO did not reach {} (it reports {}); motors left on so it "
                    "does not fall — check on it".format(
                        POSTURE_TARGET[name], result.get("posture") or "no posture"))
            raise RuntimeError("NAO stopped while {}: {} — check on it".format(
                POSTURE_MOVING[name], result.get("error") or "no reason given"))

        motors = "motors off" if result.get("motors_off") else "motors on"
        hottest = result.get("hottest") or {}
        heat = ""
        if hottest.get("joint") and hottest.get("temp_c") is not None:
            heat = " (hottest joint: {} {})".format(
                joint_label(str(hottest["joint"])), _degrees(hottest["temp_c"]))
        if result.get("already"):
            return "NAO was already {}, {} — nothing moved{}".format(
                POSTURE_DONE[name], motors, heat)
        return "NAO is {}, {}{}".format(POSTURE_DONE[name], motors, heat)

    # -------------------------------------------------------------- claims
    def claims(self) -> list[Claim]:
        # An empty value on purpose: ResourceBroker resolves "" to the
        # concrete name Windows currently means by "default input". Naming it
        # is the whole point -- an unresolved "default" hides the collision
        # with the K11 instead of showing it (2.5, 7.2).
        return [{"kind": "audio_in", "value": "", "mode": "require"}]

    # -------------------------------------------------------------- launch
    def _nao_llm_path(self) -> Path:
        path = self.config.path(self.type_id, "nao_llm_path")
        if path is None or not path.is_dir():
            raise AdapterUnavailable(
                "set nao_llm_path in config.toml to your NAO_LLM checkout "
                "before NAO's system can be launched")
        return path

    def _nao_llm_python(self, root: Path) -> Path:
        configured = self.config.path(self.type_id, "nao_llm_python")
        if configured is not None:
            if not configured.is_file():
                raise AdapterUnavailable(
                    "nao_llm_python does not exist at {}".format(configured))
            return configured
        scripts = "Scripts" if sys.platform == "win32" else "bin"
        name = "python.exe" if sys.platform == "win32" else "python"
        candidate = root / "venv" / scripts / name
        if not candidate.is_file():
            raise AdapterUnavailable(
                "NAO_LLM has no venv at {} -- create it, or set "
                "nao_llm_python in config.toml".format(candidate))
        return candidate

    def _allocate_ui_port(self) -> int:
        if self._ui_port is not None:
            return self._ui_port
        allocator = self.port_allocator or shared_port_allocator(self.config)
        self._ui_port = allocator.allocate(self.stable_key(self.found))
        return self._ui_port

    async def _write_config(self, root: Path, python: Path,
                            port: int) -> tuple[Path, list[str]]:
        """NAO_LLM's web-UI port lives in YAML, not on the command line.

        Its default is 8000, which the Reachy Mini Control desktop app already
        owns on this laptop (7.1), so leaving it alone is not an option. The
        derived file is written next to the original because `load_config`
        resolves the database and audio directories relative to the config
        file's own folder.

        The same pass reports which environment variables NAO_LLM will look
        its API keys up in: the names live in its config, not in this hub, and
        `load_config` raises rather than starts when one is unset.
        """
        source = root / "config.yaml"
        if not source.is_file():
            raise AdapterUnavailable(
                "NAO_LLM has no config.yaml at {} -- the checkout looks "
                "incomplete".format(source))
        target = root / GENERATED_CONFIG
        proc = await asyncio.create_subprocess_exec(
            str(python), "-c", _PATCH_CONFIG,
            str(source), str(target), "127.0.0.1", str(port), self.found.address,
            cwd=str(root), env=child_env(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await communicate_or_kill(proc, 30)
        if proc.returncode != 0 or not target.is_file():
            raise RuntimeError(
                "could not write {} ({})".format(
                    GENERATED_CONFIG,
                    err.decode("utf-8", "replace").strip().splitlines()[-1:]
                    or "no output"))
        try:
            names = json.loads(out.decode("utf-8", "replace").strip() or "[]")
        except ValueError:
            names = []
        return target, [str(n) for n in names if n]

    async def ensure_zero_instances(self) -> list[str]:
        supervisor = get_supervisor()
        notes: list[str] = []
        if self._child_name:
            notes += await supervisor.stop(self._child_name)
            self._child_name = ""
        try:
            root = self._nao_llm_path()
            python = self._nao_llm_python(root)
        except AdapterUnavailable as exc:
            return notes + [str(exc)]
        # Match on NAO_LLM's own interpreter path: precise enough that an
        # unrelated process merely mentioning the folder is not killed.
        notes += await supervisor.kill_matching([str(python).lower()])
        return notes

    async def launch(self) -> str:
        root = self._nao_llm_path()
        python = self._nao_llm_python(root)

        port = self._allocate_ui_port()
        config_path, key_envs = await self._write_config(root, python, port)
        # NAO_LLM's main.py load_dotenv()s its own .env (cwd is its root), so
        # a key there counts too (2026-10-05: the hub refused a NAO_LLM that
        # had both keys).
        own_env = _env_names(root / ".env")
        missing = [name for name in key_envs
                   if not self.config.secret(name) and name not in own_env]
        if missing:
            # Its own load_config raises on a missing key before the server is
            # ever bound, so the child would die with no page to open and its
            # reason buried in the log. Say it here instead.
            raise RuntimeError(
                "NAO_LLM refuses to start without {} in the environment -- "
                "add {} to .env".format(
                    " and ".join(missing),
                    "them" if len(missing) > 1 else "it"))

        await self._ensure_speaker_server(root, python, config_path)

        supervisor = get_supervisor()
        self._child_name = "nao_llm:{}".format(self.stable_key(self.found))
        # Module form, not the venv's console shims: the .exe shims embed an
        # absolute path to their interpreter and fail silently since the
        # folder move (naoqi/README.md).
        argv = [str(python), "-m", "main", "--config", config_path.name]
        env = child_env(overrides={"PYTHONPATH": str(root)})

        await supervisor.start(self._child_name, argv, cwd=root, env=env,
                               port=port, owner=self.stable_key(self.found),
                               log_prefix="NAO_LLM")
        url = "http://127.0.0.1:{}/".format(port)
        if not await supervisor.wait_for_http(url, WEB_UI_WAIT_S,
                                              name=self._child_name):
            await supervisor.stop(self._child_name)
            self._child_name = ""
            raise RuntimeError(
                "NAO_LLM never opened its control panel on port {} within "
                "{:.0f} s -- its own output is in the log above".format(
                    port, WEB_UI_WAIT_S))
        return url

    async def _speaker_answering(self, port: int) -> bool:
        try:
            _r, w = await asyncio.wait_for(
                asyncio.open_connection(self.found.address, port), 3.0)
        except (OSError, asyncio.TimeoutError):
            return False
        w.close()
        return True

    async def _ensure_speaker_server(self, root: Path, python: Path,
                                     config_path: Path) -> None:
        port = int(self.settings.get("speaker_port") or SPEAKER_PORT)
        if await self._speaker_answering(port):
            return
        # Since 2026-10-05 the server no longer wakes or stands the robot.
        self.notes.append("starting NAO's speaker server (about a minute; "
                          "NAO stays in its posture)")
        proc = await asyncio.create_subprocess_exec(
            str(python), "deploy_nao.py", "--config", config_path.name,
            cwd=str(root), env=child_env(overrides={"PYTHONPATH": str(root)}),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await communicate_or_kill(proc, SPEAKER_DEPLOY_TIMEOUT_S)
        except asyncio.TimeoutError:
            out = b"(deploy_nao.py timed out)"
        # Its own wait can give up while the server is still coming up, so
        # the port decides, not the exit code.
        deadline = asyncio.get_running_loop().time() + SPEAKER_UP_WAIT_S
        while asyncio.get_running_loop().time() < deadline:
            if await self._speaker_answering(port):
                return
            await asyncio.sleep(2.0)
        tail = out.decode("utf-8", "replace").strip()[-500:]
        raise RuntimeError(
            "NAO's speaker server did not come up on port {} -- "
            "deploy_nao.py said:\n{}".format(port, tail))

    async def stop_system(self) -> list[str]:
        if not self._child_name:
            return []
        notes = await get_supervisor().stop(self._child_name)
        self._child_name = ""
        return notes


# Pepper's Say-It dashboard (job/pepper/dashboard): Python 2.7 + pynaoqi,
# standard library only, fixed on 127.0.0.1:8780, robot address as argv[1].
PEPPER_DASHBOARD_PORT = 8780
PEPPER_DASHBOARD_WAIT_S = 30.0


class PepperAdapter(NaoqiAdapter):
    """Pepper: a NAOqi 2.5 robot, reached exactly like NAO (Python 2.7 +
    pynaoqi, ALProxy on 9559, no login -- profiles/pepper.md).

    What differs is what it must *not* do. It has no Sit or Lying postures,
    so no posture buttons. It listens on its own four microphones, so it
    claims nothing on this laptop. Its Launch is the Say-It dashboard, under
    the same Python 2.7 and SDK, and never NAO's clean-up, which would kill a
    NAO's NAO_LLM running beside it.

    Settings, in [robots.pepper.settings]:
        dashboard_path  the dashboard folder; default ../pepper/dashboard
    """

    type_id = "pepper"
    display_name = "Pepper"
    postures = ()
    launch_timeout_s = PEPPER_DASHBOARD_WAIT_S + 30

    def stable_key(self, found: Found) -> str:
        key = super().stable_key(found)
        return "pepper:" + key[len("naoqi:"):] if key.startswith("naoqi:") else key

    def claims(self) -> list[Claim]:
        return []

    async def ensure_zero_instances(self) -> list[str]:
        return []

    def _dashboard(self) -> Path:
        folder = self.config.path(self.type_id, "dashboard_path") or (
            self.config.repo_root / ".." / "pepper" / "dashboard").resolve()
        script = folder / "pepper_dashboard.py"
        if not script.is_file():
            raise AdapterUnavailable(
                "Pepper's dashboard is not at {} -- set dashboard_path in "
                "[robots.pepper.settings]".format(folder))
        return script

    async def launch(self) -> str:
        script = self._dashboard()
        url = "http://127.0.0.1:{}/".format(PEPPER_DASHBOARD_PORT)
        supervisor = get_supervisor()
        # Started by hand (start.sh) or by an earlier hub: use it as it is.
        if await supervisor.wait_for_http(url + "api/status", 1.5):
            self.notes.append("Pepper's dashboard was already running")
            return url
        self._child_name = "pepper_dashboard:{}".format(self.stable_key(self.found))
        await supervisor.start(
            self._child_name, [str(self._python2), str(script), self.found.address],
            cwd=script.parent, env=self._env(), port=PEPPER_DASHBOARD_PORT,
            owner=self.stable_key(self.found), log_prefix="Pepper")
        if not await supervisor.wait_for_http(url + "api/status", PEPPER_DASHBOARD_WAIT_S,
                                              name=self._child_name):
            await supervisor.stop(self._child_name)
            self._child_name = ""
            raise RuntimeError(
                "Pepper's dashboard never answered on port {} within {:.0f} s "
                "-- its own output is in the log above".format(
                    PEPPER_DASHBOARD_PORT, PEPPER_DASHBOARD_WAIT_S))
        return url

    async def system_status(self) -> dict[str, Any]:
        status = await super().system_status()
        if status:
            status["mic"] = "Pepper's own four microphones"
        return status
