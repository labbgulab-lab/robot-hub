"""LabaLab Robot Hub on a Mac: what the app icon runs (with the bundled Python).

    app/runtime/bin/python3 app/launch_mac.py            the normal start
    app/runtime/bin/python3 app/launch_mac.py --check    headless self-test: start
                                                         the hub, ask it for the
                                                         robots, stop it again
    app/runtime/bin/python3 app/launch_mac.py --quit     ask a running hub to quit

"$HOME/Applications/LabaLab Robot Hub.app" (made by tools/install-mac.sh) runs
the first line. What it does:
  1. Points the hub at the data folder (ROBOT_HUB_DATA = <root>/data) and
     starts it detached, in its own session (it outlives this launcher and
     the app icon), unless the hub already answers on 127.0.0.1.
  2. Waits until the hub answers (at most START_TIMEOUT), then opens it in
     the default browser.
That is all: no tray and no window of its own. Quit lives in the hub's
Settings; clicking the icon again opens the page again.

The installed layout (<root> = ~/Library/Application Support/LabaLab/RobotHub):

    <root>/app/runtime/      python-build-standalone 3.12, packages inside it
    <root>/app/robot-hub/    the hub
    <root>/app/reachy_chat/
    <root>/app/launch_mac.py this file (the source is robot-hub/launch/launch_mac.py)
    <root>/data/             keys, settings, logs: never touched by an update

Also runs from a lab checkout (robot-hub/launch/launch_mac.py): then the hub is
this repo, the Python is the one running this file, and data stays where the
hub keeps it unless ROBOT_HUB_DATA is set.

Standard library only: it must run on the bundled runtime before anything else.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

try:
    import tomllib
except ImportError:  # pragma: no cover - the runtime is 3.12
    tomllib = None  # type: ignore[assignment]

APP_NAME = "Robot Hub"
DEFAULT_PORT = 8099
START_TIMEOUT = 60          # seconds; onnxruntime is slow to import the first time
QUIT_TIMEOUT = 30           # Quit first stops every robot program (up to 20 s)
CLOSE_GRACE = 5             # then the hub closes its port; this long to exit after that
# The same start as `python -m hub.main`, but the module is imported once: with
# -m it runs as __main__ and uvicorn's import would make a second hub that
# Quit cannot reach (launch.pyw has the same line).
HUB_ARGS = ("-c", "from hub.main import main; main()")
OPEN = "/usr/bin/open"


# ----------------------------------------------------------------- layout
def find_layout(here: Path, env: Optional[dict[str, str]] = None,
                executable: Optional[str] = None) -> dict[str, Any]:
    """{"installed", "hub_dir", "python", "data_dir"} for a launcher in `here`.

    Installed: <app>/launch_mac.py next to robot-hub/ and runtime/. Checkout:
    robot-hub/launch/launch_mac.py, run by whatever Python runs it."""
    env = os.environ if env is None else env
    if (here / "robot-hub" / "hub").is_dir():
        return {"installed": True, "hub_dir": here / "robot-hub",
                "python": here / "runtime" / "bin" / "python3",
                "data_dir": Path(env.get("ROBOT_HUB_DATA") or here.parent / "data")}
    return {"installed": False, "hub_dir": here.parent,
            "python": Path(executable or sys.executable),
            "data_dir": Path(env["ROBOT_HUB_DATA"]) if env.get("ROBOT_HUB_DATA") else None}


HERE = Path(__file__).resolve().parent
_layout = find_layout(HERE)
INSTALLED: bool = _layout["installed"]
HUB_DIR: Path = _layout["hub_dir"]
PYTHON: Path = _layout["python"]
DATA_DIR: Optional[Path] = _layout["data_dir"]

if INSTALLED:
    # The bundle's runtime must not see the student's own Python packages
    # (pip install --user lands in the same 3.12 user site).
    import site
    _user_site = getattr(site, "USER_SITE", None) or ""
    if _user_site:
        sys.path[:] = [p for p in sys.path if not p.startswith(_user_site)]

STATE_DIR = DATA_DIR or HUB_DIR                 # where the logs go
LOG_DIR = STATE_DIR / "logs"

log = logging.getLogger("launcher")


def _setup_logging(to_console: bool) -> None:
    handlers: list[logging.Handler] = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate(LOG_DIR / "launcher.log", 1_000_000)
        handlers.append(logging.FileHandler(LOG_DIR / "launcher.log", encoding="utf-8"))
    except OSError:
        pass
    if to_console and sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(level=logging.INFO, handlers=handlers or [logging.NullHandler()],
                        format="%(asctime)s  %(levelname)-7s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")


def _rotate(path: Path, limit: int) -> None:
    """Keep one older copy once a log passes `limit` bytes."""
    try:
        if path.exists() and path.stat().st_size > limit:
            old = path.with_suffix(path.suffix + ".1")
            if old.exists():
                old.unlink()
            path.rename(old)
    except OSError:
        pass


def hub_port() -> int:
    """[server] port from the student's config, then the shipped defaults."""
    candidates = [HUB_DIR / "defaults.toml"]
    candidates.insert(0, (DATA_DIR or HUB_DIR) / "config.toml")
    for path in candidates:
        if tomllib is None or not path.is_file():
            continue
        try:
            with path.open("rb") as fh:
                port = (tomllib.load(fh).get("server") or {}).get("port")
            if port:
                return int(port)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("could not read the port from %s: %s", path, exc)
    return DEFAULT_PORT


PORT = hub_port()
URL = f"http://127.0.0.1:{PORT}/"


# ----------------------------------------------------------------- messages
def message(text: str) -> None:
    """A dialog the student sees (the app icon has no terminal), and stderr."""
    print(text, file=sys.stderr)
    if sys.platform != "darwin":
        return
    script = 'display alert "{}" message "{}" as critical'.format(
        APP_NAME, text.replace("\\", "\\\\").replace('"', '\\"'))
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], timeout=120,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


# ----------------------------------------------------------------- hub
def _http(method: str, path: str, timeout: float = 2.0) -> tuple[int, bytes]:
    req = urllib.request.Request(URL.rstrip("/") + path, method=method,
                                 data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (OSError, ValueError):
        return 0, b""


def port_open() -> bool:
    """Something accepts connections on the hub's port."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
            return True
    except OSError:
        return False


def hub_answers() -> bool:
    """A Robot Hub (not some other program) answers on the port."""
    status, body = _http("GET", "/api/app", timeout=1.5)
    if status != 200:
        return False
    try:
        return isinstance(json.loads(body), dict)
    except ValueError:
        return False         # something else holds the port


def hub_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """The hub's environment: the data folder, UTF-8, and nothing of the
    student's own Python setup."""
    env = dict(os.environ if base is None else base)
    for var in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV"):
        env.pop(var, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if DATA_DIR:
        env["ROBOT_HUB_DATA"] = str(DATA_DIR)
    return env


class HubProcess:
    """The hub this launcher started (proc is None when it was already running)."""

    def __init__(self, popen: Any = subprocess.Popen) -> None:
        self.popen = popen
        self.proc: Any = None
        self._out: Any = None

    def argv(self) -> list[str]:
        return [str(PYTHON), *HUB_ARGS]

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LOG_DIR / "hub-stdout.log"
        _rotate(out_path, 5_000_000)
        self._close_out()
        self._out = open(out_path, "ab")
        self._out.write(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} starting the hub\n".encode())
        self._out.flush()
        if DATA_DIR:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
        log.info("starting the hub: %s (in %s)", " ".join(self.argv()), HUB_DIR)
        # Its own session: closing the app icon or this launcher's terminal
        # never takes the hub (and the robots' programs) with it.
        try:
            self.proc = self.popen(
                self.argv(), cwd=str(HUB_DIR), env=hub_env(),
                stdin=subprocess.DEVNULL, stdout=self._out, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True)
        finally:
            self._close_out()        # the hub has its own copy of the log file

    def exit_code(self) -> Optional[int]:
        """None while it runs (or when we did not start it)."""
        return None if self.proc is None else self.proc.poll()

    def wait_ready(self, timeout: float = START_TIMEOUT) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if hub_answers():
                return True
            if self.proc is not None and self.proc.poll() is not None:
                log.error("the hub exited during start, code %s", self.proc.returncode)
                return False
            time.sleep(0.4)
        log.error("the hub did not answer within %s s", timeout)
        return False

    def stop(self) -> None:
        """Ask the hub to quit; force it (and its children) when it won't.

        Quit stops the robots' programs first, then the server closes its
        port. An open browser tab holds a WebSocket that can keep the server
        waiting a little longer, so once the port is closed, CLOSE_GRACE is
        enough."""
        status, _ = _http("POST", "/api/app/quit", timeout=5)
        log.info("POST /api/app/quit -> %s", status or "no answer")
        end = time.monotonic() + QUIT_TIMEOUT
        closed_at = None
        while time.monotonic() < end:
            if self.proc is not None:
                if self.proc.poll() is not None:
                    return
                if not port_open():
                    closed_at = closed_at or time.monotonic()
                    if time.monotonic() - closed_at > CLOSE_GRACE:
                        break
            elif not hub_answers():      # a hub this launcher did not start
                return
            time.sleep(0.3)
        self.kill()

    def kill(self) -> None:
        if self.proc is None:
            return
        pid = self.proc.pid
        log.warning("the hub did not quit; stopping process %s and its children", pid)
        try:
            import psutil
            parent = psutil.Process(pid)
            procs = parent.children(recursive=True) + [parent]
            for p in procs:
                try:
                    p.kill()
                except psutil.Error:
                    pass
            psutil.wait_procs(procs, timeout=5)
            return
        except Exception as exc:  # noqa: BLE001 - psutil missing or the process is gone
            log.info("tree kill: %s", exc)
        try:
            if hasattr(os, "killpg"):
                os.killpg(pid, signal.SIGKILL)      # its own session = its own group
            else:
                self.proc.kill()
        except OSError:
            pass

    def _close_out(self) -> None:
        if self._out is not None:
            try:
                self._out.close()
            except OSError:
                pass
            self._out = None


def open_browser(popen: Any = subprocess.Popen) -> None:
    """The hub's page in the student's default browser."""
    if os.path.exists(OPEN):
        try:
            popen([OPEN, URL], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, close_fds=True)
            log.info("opened %s", URL)
            return
        except OSError as exc:
            log.warning("could not run open: %s", exc)
    import webbrowser
    webbrowser.open(URL)
    log.info("opened %s in the default browser", URL)


class _StartLock:
    """One start at a time: a double-click on the icon starts one hub, and
    the second launcher waits, then finds it running. A no-op where fcntl
    is missing (Windows, tests)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.fh: Any = None

    def __enter__(self) -> "_StartLock":
        try:
            import fcntl
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.fh = open(self.path, "a")
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            self.fh = None
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self.fh is not None:
            try:
                self.fh.close()          # closing releases the lock
            except OSError:
                pass


# ----------------------------------------------------------------- entry
def start_and_open(hub: Optional[HubProcess] = None) -> int:
    """The icon: the hub running (started if needed), then the page open."""
    hub = hub or HubProcess()
    with _StartLock(LOG_DIR / "launcher.lock"):
        if not hub_answers():
            try:
                hub.start()
            except OSError as exc:
                log.error("could not start the hub: %s", exc)
                message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'hub-stdout.log'}")
                return 1
            if not hub.wait_ready():
                message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'hub-stdout.log'}")
                return 1
    open_browser()
    return 0


def self_check(hub: Optional[HubProcess] = None) -> int:
    """--check: start the hub the way the icon does, ask it for the robots and
    the app info, stop it again (only if this run started it). Prints JSON."""
    hub = hub or HubProcess()
    started = False
    t0 = time.monotonic()
    if not hub_answers():
        hub.start()
        started = True
        if not hub.wait_ready():
            print(json.dumps({"ok": False, "started_by_check": True,
                              "error": "the hub did not start", "app": None,
                              "log": str(LOG_DIR / "hub-stdout.log")}))
            hub.stop()
            return 1
    ready_s = round(time.monotonic() - t0, 1)
    status, body = _http("GET", "/api/robots", timeout=5)
    app_status, app_body = _http("GET", "/api/app", timeout=5)
    try:
        robots = json.loads(body)
    except ValueError:
        robots = None
    try:
        app = json.loads(app_body) if app_status == 200 else None
    except ValueError:
        app = None
    result = {"ok": status == 200 and app_status == 200, "started_by_check": started,
              "ready_seconds": ready_s, "url": URL, "robots_status": status,
              "robots": len(robots) if isinstance(robots, (list, dict)) else None,
              "app_status": app_status, "app": app,
              "data_dir": str(DATA_DIR or ""), "python": str(PYTHON)}
    if started:
        hub.stop()
        result["stopped"] = not hub_answers()
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


def quit_hub() -> int:
    """--quit: ask a running hub to quit (the installer does the same)."""
    if not hub_answers():
        print(json.dumps({"ok": True, "running": False}))
        return 0
    status, _ = _http("POST", "/api/app/quit", timeout=5)
    print(json.dumps({"ok": status == 200, "running": True, "status": status}))
    return 0 if status == 200 else 1


def main(argv: list[str]) -> int:
    check = "--check" in argv
    _setup_logging(to_console=check or "--quit" in argv)
    log.info("launcher %s (installed=%s, data=%s, url=%s)", __file__, INSTALLED, DATA_DIR, URL)
    if "--quit" in argv:
        return quit_hub()
    if not PYTHON.is_file():
        message(f"Robot Hub is incomplete: {PYTHON} is missing. Run the install line again.")
        return 1
    if check:
        return self_check()
    return start_and_open()


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        logging.getLogger("launcher").exception("launcher crashed")
        message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'launcher.log'}")
        sys.exit(1)
