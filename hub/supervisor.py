"""Child processes: start, wait, stop, and prove nothing is left over.

Everything the hub launches is a child with its own port, its own cwd and its
own env (PLAN.md 7.4), so a crash in one robot's system cannot touch another.

Two measured rules shape this file:

  * Stopping must be *verified*, not signalled. `reachy_chat`'s own
    `tools/start_reachy.py::stop_everything` explains why: two instances
    fighting over the same audio device produce a symptom identical to a
    broken microphone, and that class of failure has already cost a demo.
    So `kill_matching` re-scans afterwards and `stop` re-checks the port.
  * On Windows a child started without CREATE_NEW_PROCESS_GROUP shares the
    hub's console group, and a Ctrl-Break aimed at the child would take the
    hub with it. Every child gets its own group; nothing is ever `shell=True`.

Nothing here blocks the event loop (13.1): psutil enumeration and port
bind-tests go through `asyncio.to_thread`, the child itself is an
`asyncio.subprocess`, and its stdout/stderr are pumped into the event bus as
log lines so a failing launch explains itself in the UI (13.5).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Sequence

from .config import Config
from .events import EventBus
from .ports import PortAllocator, is_free

IS_WINDOWS = sys.platform == "win32"

STOP_GRACE_S = 8.0          # terminate, then kill
PORT_FREE_WAIT_S = 6.0      # Windows releases a listening socket lazily
LOG_LINE_LIMIT = 400        # a runaway child must not flood the event log


@dataclass
class Managed:
    """One running child. `name` is the hub-side handle, not the exe name."""

    name: str
    argv: list[str]
    cwd: str
    proc: asyncio.subprocess.Process
    port: Optional[int] = None
    owner: str = ""
    started_at: float = field(default_factory=time.time)
    pumps: list[asyncio.Task] = field(default_factory=list)

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def alive(self) -> bool:
        return self.proc.returncode is None


def _psutil() -> Any:
    """psutil is in requirements, but a hub missing it must still run (13.6)."""
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "psutil is not installed, so leftover processes cannot be found "
            "or cleared; run: pip install -r requirements.txt"
        ) from exc
    return psutil


def _norm(text: str) -> str:
    return str(text).replace("\\", "/").strip().strip('"').lower()


def _argv_matches(argv: Sequence[str], needles: Sequence[str]) -> bool:
    """True when one of this process's arguments *is* one of the needles.

    Both forms in use are covered: a bare script name ("laptop_chat.py")
    matches whatever directory it was launched from, and a full interpreter
    path matches only that interpreter.
    """
    for part in argv:
        candidate = _norm(part)
        for needle in needles:
            if candidate == needle or candidate.endswith("/" + needle):
                return True
    return False


def _ancestor_pids() -> set[int]:
    """This process and everything that launched it.

    Not just the immediate parent: the hub is typically started from a shell
    inside a terminal, and a leftover hunt must not be able to walk up that
    chain and close the window the user is watching.
    """
    pids = {os.getpid(), os.getppid()}
    try:
        psutil = _psutil()
        proc = psutil.Process().parent()
        for _ in range(16):      # capped: pid reuse can make this a cycle
            if proc is None:
                break
            pids.add(proc.pid)
            proc = proc.parent()
    except Exception:  # noqa: BLE001
        pass
    return pids


_SHARED_ALLOCATORS: dict[int, PortAllocator] = {}


def shared_port_allocator(config: Config) -> PortAllocator:
    """The allocator an adapter falls back to when the hub injected none.

    `ResourceBroker` owns the real allocator. An adapter constructed outside
    the hub (a smoke test, `hub.doctor`) still needs one, and two independent
    allocators handing out the same port would be a silent collision -- so the
    fallback is a single instance per Config object, not a fresh one per call.
    """
    key = id(config)
    allocator = _SHARED_ALLOCATORS.get(key)
    if allocator is None:
        allocator = PortAllocator(config)
        _SHARED_ALLOCATORS[key] = allocator
    return allocator


def child_env(overrides: Optional[dict[str, str]] = None,
              prepend_path: Optional[Sequence[str]] = None) -> dict[str, str]:
    """A child's own environment (7.4), built from a copy of the hub's."""
    env = dict(os.environ)
    # A Python child block-buffers stdout into a pipe, so its output would
    # reach the event log in 8 KB bursts -- or, if the hub stops it first, not
    # at all. Every launch target here is Python, and a launch that fails is
    # exactly when its own words are needed.
    env["PYTHONUNBUFFERED"] = "1"
    for entry in reversed(list(prepend_path or ())):
        env["PATH"] = "{}{}{}".format(entry, os.pathsep, env.get("PATH", ""))
    env.update({k: str(v) for k, v in (overrides or {}).items()})
    return env


class Supervisor:
    """Owns every process the hub starts. One instance per hub."""

    def __init__(self, bus: Optional[EventBus] = None) -> None:
        self.bus = bus
        self._children: dict[str, Managed] = {}

    # ------------------------------------------------------------- logging
    def _log(self, level: str, text: str) -> None:
        if self.bus is not None:
            self.bus.emit_log(level, text)

    # ------------------------------------------------------------ starting
    async def start(
        self,
        name: str,
        argv: Sequence[str],
        *,
        cwd: str | os.PathLike[str],
        env: Optional[dict[str, str]] = None,
        port: Optional[int] = None,
        owner: str = "",
        log_prefix: Optional[str] = None,
    ) -> Managed:
        """Spawn `argv` as a tracked child. Never `shell=True`."""
        if name in self._children and self._children[name].alive:
            raise RuntimeError(
                "'{}' is already running (pid {}); stop it first".format(
                    name, self._children[name].pid))

        argv = [str(a) for a in argv]
        cwd = str(cwd)
        if not os.path.isdir(cwd):
            raise RuntimeError(
                "cannot start {}: its working directory {} does not exist"
                .format(name, cwd))
        if not os.path.exists(argv[0]):
            raise RuntimeError(
                "cannot start {}: {} does not exist".format(name, argv[0]))

        kwargs: dict[str, Any] = {}
        if IS_WINDOWS:
            # Its own process group, so stopping a child never reaches the hub.
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=env or child_env(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )

        managed = Managed(name=name, argv=argv, cwd=cwd, proc=proc,
                          port=port, owner=owner)
        prefix = log_prefix or name
        managed.pumps = [
            asyncio.create_task(self._pump(proc.stdout, prefix, "info")),
            asyncio.create_task(self._pump(proc.stderr, prefix, "warn")),
        ]
        self._children[name] = managed
        self._log("info", "{}: started pid {}{}".format(
            name, proc.pid, " on port {}".format(port) if port else ""))
        return managed

    async def _pump(self, stream: Optional[asyncio.StreamReader],
                    prefix: str, level: str) -> None:
        """Child output becomes log lines. A piped stream nobody reads fills
        its buffer and deadlocks the child, so this task always runs."""
        if stream is None:
            return
        try:
            while True:
                raw = await stream.readline()
                if not raw:
                    return
                text = raw.decode("utf-8", "replace").rstrip()
                if text:
                    self._log(level, "{}: {}".format(prefix, text[:LOG_LINE_LIMIT]))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return

    # -------------------------------------------------------------- waiting
    async def wait_for_http(self, url: str, timeout_s: float,
                            *, name: str = "", interval_s: float = 0.5) -> bool:
        """Poll until `url` gives a real HTTP reply, or the deadline passes.

        A real reply, never a bare TCP connect: the Check Point VPN adapter on
        this laptop makes port-80 connects succeed for hosts that do not
        exist (2.9).
        """
        try:
            import httpx
        except Exception:  # noqa: BLE001
            self._log("warn", "httpx is not installed, so {} cannot be "
                              "health-checked".format(name or url))
            return False

        deadline = time.monotonic() + timeout_s
        last = ""
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=True) as client:
            while time.monotonic() < deadline:
                child = self._children.get(name) if name else None
                if child is not None and not child.alive:
                    return False
                try:
                    resp = await client.get(url)
                    if resp.status_code < 500:
                        return True
                    last = "HTTP {}".format(resp.status_code)
                except Exception as exc:  # noqa: BLE001
                    last = type(exc).__name__
                await asyncio.sleep(interval_s)
        if last:
            self._log("warn", "{} never answered on {} ({})".format(
                name or "the process", url, last))
        return False

    async def wait_for_exit(self, name: str, timeout_s: float) -> Optional[int]:
        child = self._children.get(name)
        if child is None:
            return None
        try:
            return await asyncio.wait_for(child.proc.wait(), timeout_s)
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------- stopping
    async def stop(self, name: str, grace_s: float = STOP_GRACE_S) -> list[str]:
        """Terminate, then kill, then *verify* the port is actually free."""
        notes: list[str] = []
        child = self._children.pop(name, None)
        if child is None:
            return notes

        if child.alive:
            try:
                child.proc.terminate()
            except ProcessLookupError:
                pass
            except Exception as exc:  # noqa: BLE001
                notes.append("could not signal {} (pid {}): {}".format(
                    name, child.pid, exc))
            try:
                await asyncio.wait_for(child.proc.wait(), grace_s)
                notes.append("stopped {} (pid {})".format(name, child.pid))
            except asyncio.TimeoutError:
                try:
                    child.proc.kill()
                    await asyncio.wait_for(child.proc.wait(), 5)
                    notes.append("killed {} (pid {}) after {:.0f} s".format(
                        name, child.pid, grace_s))
                except Exception as exc:  # noqa: BLE001
                    notes.append("{} (pid {}) would not die: {}".format(
                        name, child.pid, exc))
        for task in child.pumps:
            task.cancel()

        if child.port is not None:
            if await self.wait_for_port_free(child.port):
                notes.append("port {} is free".format(child.port))
            else:
                notes.append(
                    "WARNING: port {} is still held after stopping {} -- "
                    "something else is listening there".format(child.port, name))
        for note in notes:
            self._log("info", note)
        return notes

    async def stop_all(self) -> list[str]:
        notes: list[str] = []
        for name in list(self._children):
            notes += await self.stop(name)
        return notes

    async def wait_for_port_free(self, port: int,
                                 timeout_s: float = PORT_FREE_WAIT_S) -> bool:
        """Windows does not release a listening socket the instant the owner
        exits, so 'not free yet' and 'held by someone else' need time apart."""
        deadline = time.monotonic() + timeout_s
        while True:
            if await asyncio.to_thread(is_free, port):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.4)

    # ------------------------------------------------------- leftover hunt
    async def find_matching(self, needles: Iterable[str]) -> list[tuple[int, str]]:
        """Every process actually *running* one of `needles`, minus our own
        ancestry.

        A needle is matched against each argv entry, never against the joined
        command line. `start_reachy.py` hit the substring version of this and
        wrote the reason down: a shell's own command line contains the script
        name it was asked to run, so a plain substring match kills the parent
        shell -- observed here, terminating the terminal that started the hub.
        Its `[l]aptop_chat` bracket trick is the same fix in regex form.

        `psutil.process_iter` walks every process on the machine and can take
        hundreds of milliseconds, so it runs off the loop.
        """
        needles = [_norm(n) for n in needles if n]
        if not needles:
            return []
        return await asyncio.to_thread(self._find_matching_blocking, needles)

    @staticmethod
    def _find_matching_blocking(needles: list[str]) -> list[tuple[int, str]]:
        psutil = _psutil()
        mine = _ancestor_pids()
        hits: list[tuple[int, str]] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                if proc.info["pid"] in mine:
                    continue
                argv = proc.info["cmdline"] or []
                if argv and _argv_matches(argv, needles):
                    hits.append((proc.info["pid"], " ".join(argv)))
            except Exception:  # noqa: BLE001
                continue        # a process that exits mid-walk is not an error
        return hits

    async def kill_matching(self, needles: Iterable[str],
                            grace_s: float = 5.0,
                            scope: Optional[str] = None) -> list[str]:
        """Kill leftovers, then re-scan and report what actually remains.

        The re-scan is the point. `stop_everything` in `start_reachy.py`
        counts survivors for the same reason: a stop that only *signals* looks
        identical to a stop that worked, right up until two instances fight
        over the microphone.

        `scope`, when given, must also appear as a whole argv entry (e.g. one
        robot's address), so clearing robot A never kills robot B's instance
        of the same script.
        """
        needles = [n for n in needles if n]
        notes: list[str] = []

        async def matching() -> list[tuple[int, str]]:
            found = await self.find_matching(needles)
            if scope:
                found = [(pid, cmd) for pid, cmd in found if scope in cmd.split(" ")]
            return found

        try:
            hits = await matching()
        except RuntimeError as exc:
            return [str(exc)]
        if not hits:
            return notes

        psutil = _psutil()
        for pid, cmdline in hits:
            try:
                proc = psutil.Process(pid)
                await asyncio.to_thread(proc.terminate)
                notes.append("stopped leftover pid {} ({})".format(
                    pid, os.path.basename(cmdline.split(" ")[0])))
            except Exception as exc:  # noqa: BLE001
                notes.append("could not stop pid {}: {}".format(pid, exc))

        deadline = time.monotonic() + grace_s
        remaining = await matching()
        while remaining and time.monotonic() < deadline:
            await asyncio.sleep(0.5)
            remaining = await matching()

        for pid, _cmdline in remaining:
            try:
                await asyncio.to_thread(psutil.Process(pid).kill)
                notes.append("killed stubborn pid {}".format(pid))
            except Exception as exc:  # noqa: BLE001
                notes.append("could not kill pid {}: {}".format(pid, exc))

        survivors = await matching()
        if survivors:
            notes.append(
                "WARNING: {} process(es) still match {} -- started outside the "
                "hub? Close them by hand before launching.".format(
                    len(survivors), ", ".join(needles)))
        else:
            notes.append("verified: nothing matching {} is running".format(
                ", ".join(needles)))
        return notes

    # ---------------------------------------------------------------- state
    def get(self, name: str) -> Optional[Managed]:
        return self._children.get(name)

    def is_running(self, name: str) -> bool:
        child = self._children.get(name)
        return child is not None and child.alive

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {"name": c.name, "pid": c.pid, "port": c.port, "owner": c.owner,
             "alive": c.alive, "uptime_s": round(time.time() - c.started_at, 1)}
            for c in self._children.values()
        ]


_SHARED: Optional[Supervisor] = None


def get_supervisor(bus: Optional[EventBus] = None) -> Supervisor:
    """One supervisor for the whole process.

    Adapters are constructed as `cls(found, config)` and never handed the bus,
    so they reach the supervisor through here. The first caller that has a bus
    attaches it; later callers inherit it.
    """
    global _SHARED
    if _SHARED is None:
        _SHARED = Supervisor(bus)
    elif bus is not None and _SHARED.bus is None:
        _SHARED.bus = bus
    return _SHARED
