r"""LabaLab Robot Hub: what the desktop icon runs (with the bundled pythonw).

    app\runtime\pythonw.exe app\launch.pyw            the normal start
    app\runtime\python.exe  app\launch.pyw --check    headless self-test: start
                                                      the hub, ask it for the
                                                      robots, stop it again
    ... launch.pyw --no-window                        tray only, no window

What it does:
  1. One launcher per Windows user (a named mutex). A second start only asks
     the first one to open the window, then exits.
  2. Points the hub at the data folder (ROBOT_HUB_DATA = <root>\data) and
     starts it windowless (runtime\python.exe, CREATE_NO_WINDOW),
     unless the hub already answers on 127.0.0.1.
  3. Opens the hub as an app window: Microsoft Edge with --app and its own
     profile in data\edge-profile. Without Edge, the default browser.
  4. A tray icon with Open, Restart (only when the hub stopped) and Quit.

Closing the window does not stop the robots. Quit (tray or Settings) does.
The hub only ever listens on 127.0.0.1, so Windows never asks about the
firewall (docs/BUILD-PLAN.md, "No admin, no firewall").

Also runs from a lab checkout (robot-hub/launch/launch.pyw): then the hub is
this repo, the Python is the one running this file, and data stays where the
hub keeps it unless ROBOT_HUB_DATA is set.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import socket
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:  # pragma: no cover - the runtime is 3.12
    tomllib = None  # type: ignore[assignment]

APP_NAME = "Robot Hub"
DEFAULT_PORT = 8099
START_TIMEOUT = 120          # seconds; the first start compiles nothing, but onnxruntime is slow to import
QUIT_TIMEOUT = 30           # Quit first stops every robot program (up to 20 s)
CLOSE_GRACE = 5             # then the hub closes its port; this long to exit after that
MUTEX_NAME = "Local\\LabaLab.RobotHub.Launcher"
OPEN_EVENT_NAME = "Local\\LabaLab.RobotHub.Open"
EDGE_APP_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200
# Not `-m hub.main`: that runs the module as __main__ while uvicorn imports
# "hub.main:app" a second time, so the hub would exist twice and Quit would
# reach the copy that has no server (it then ends by Ctrl+C, 0xC000013A).
HUB_ARGS = ("-c", "from hub.main import main; main()")
# How a hub that was told to quit exits: 0, or STATUS_CONTROL_C_EXIT when it
# ends itself with SIGINT.
CLEAN_EXITS = (0, 0xC000013A)
ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
WAIT_OBJECT_0 = 0
ASFW_ANY = -1
SW_RESTORE = 9
WM_CLOSE = 0x0010
MB_ICONERROR = 0x10

# ----------------------------------------------------------------- layout
HERE = Path(__file__).resolve().parent
if (HERE / "robot-hub" / "hub").is_dir():
    # Installed: <root>\app\launch.pyw next to runtime\ and robot-hub\.
    INSTALLED = True
    HUB_DIR = HERE / "robot-hub"
    PYTHON = HERE / "runtime" / "python.exe"
    DATA_DIR: Optional[Path] = Path(os.environ.get("ROBOT_HUB_DATA") or HERE.parent / "data")
else:
    # Lab checkout: robot-hub\launch\launch.pyw.
    INSTALLED = False
    HUB_DIR = HERE.parent
    _exe = Path(sys.executable)
    PYTHON = _exe.with_name("python.exe") if _exe.name.lower() == "pythonw.exe" else _exe
    DATA_DIR = Path(os.environ["ROBOT_HUB_DATA"]) if os.environ.get("ROBOT_HUB_DATA") else None

if INSTALLED:
    # The bundle's runtime must not see the student's own Python packages
    # (pip install --user lands in the same 3.12 user site). The shortcut
    # passes -I too; this covers a double-clicked launch.pyw.
    import site
    _user_site = getattr(site, "USER_SITE", None) or ""
    if _user_site:
        sys.path[:] = [p for p in sys.path if not p.startswith(_user_site)]

STATE_DIR = DATA_DIR or HUB_DIR                 # where logs and the Edge profile go
LOG_DIR = STATE_DIR / "logs"
EDGE_PROFILE = STATE_DIR / ("edge-profile" if DATA_DIR else "cache/edge-profile")

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
    if DATA_DIR:
        candidates.insert(0, DATA_DIR / "config.toml")
    else:
        candidates.insert(0, HUB_DIR / "config.toml")
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


# ----------------------------------------------------------------- win32
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_u32 = ctypes.WinDLL("user32", use_last_error=True)
_k32.CreateMutexW.restype = wt.HANDLE
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
_k32.CreateEventW.restype = wt.HANDLE
_k32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
_k32.OpenEventW.restype = wt.HANDLE
_k32.OpenEventW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
_k32.SetEvent.argtypes = [wt.HANDLE]
_k32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_k32.WaitForSingleObject.restype = wt.DWORD
_k32.CloseHandle.argtypes = [wt.HANDLE]
_u32.AllowSetForegroundWindow.argtypes = [wt.DWORD]
_u32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
_u32.GetWindowTextLengthW.argtypes = [wt.HWND]
_u32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
_u32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
_u32.IsWindowVisible.argtypes = [wt.HWND]
_u32.IsIconic.argtypes = [wt.HWND]
_u32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
_u32.SetForegroundWindow.argtypes = [wt.HWND]
_u32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
_u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
_WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
_u32.EnumWindows.argtypes = [_WNDENUMPROC, wt.LPARAM]


def message(text: str) -> None:
    _u32.MessageBoxW(None, text, APP_NAME, MB_ICONERROR)


def take_single_instance() -> Optional[int]:
    """The mutex handle if this is the only launcher, else None."""
    handle = _k32.CreateMutexW(None, False, MUTEX_NAME)
    if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(handle)
        return None
    return handle


def ask_first_launcher_to_open() -> bool:
    """A second start: let the running launcher bring its window to the
    front (we hold the user's click, so we may hand it the foreground)."""
    _u32.AllowSetForegroundWindow(wt.DWORD(ASFW_ANY & 0xFFFFFFFF))
    for _ in range(50):
        event = _k32.OpenEventW(EVENT_MODIFY_STATE, False, OPEN_EVENT_NAME)
        if event:
            _k32.SetEvent(event)
            _k32.CloseHandle(event)
            return True
        time.sleep(0.1)
    return False


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
    status, body = _http("GET", "/api/robots", timeout=1.5)
    if status != 200:
        return False
    try:
        json.loads(body)
        return True
    except ValueError:
        return False         # something else holds the port


class HubProcess:
    """The hub this launcher started (None when it was already running)."""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self._out = None

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        out_path = LOG_DIR / "hub-stdout.log"
        _rotate(out_path, 5_000_000)
        self._close_out()
        self._out = open(out_path, "ab")
        self._out.write(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} starting the hub\n".encode())
        self._out.flush()
        env = dict(os.environ)
        for var in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "VIRTUAL_ENV"):
            env.pop(var, None)
        env["PYTHONNOUSERSITE"] = "1"         # never mix in the user's own packages
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        if DATA_DIR:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            env["ROBOT_HUB_DATA"] = str(DATA_DIR)
        log.info("starting the hub: %s %s (in %s)", PYTHON, " ".join(HUB_ARGS), HUB_DIR)
        self.proc = subprocess.Popen(
            [str(PYTHON), *HUB_ARGS], cwd=str(HUB_DIR), env=env,
            stdin=subprocess.DEVNULL, stdout=self._out, stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, close_fds=True)

    def exit_code(self) -> Optional[int]:
        """None while it runs (or when we did not start it)."""
        return None if self.proc is None else self.proc.poll()

    def ours(self) -> bool:
        return self.proc is not None

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
        port. An open app window holds a WebSocket that can keep the server
        waiting ~25 s more, so once the port is closed, CLOSE_GRACE is enough.
        """
        status, _ = _http("POST", "/api/app/quit", timeout=5)
        log.info("POST /api/app/quit -> %s", status or "no answer")
        end = time.monotonic() + QUIT_TIMEOUT
        closed_at = None
        while time.monotonic() < end:
            if self.proc is not None:
                if self.proc.poll() is not None:
                    break
                if not port_open():
                    closed_at = closed_at or time.monotonic()
                    if time.monotonic() - closed_at > CLOSE_GRACE:
                        self._kill_tree()
                        break
            elif not hub_answers():      # a hub this launcher did not start
                break
            time.sleep(0.3)
        else:
            self._kill_tree()
        self._close_out()

    def kill(self) -> None:
        self._kill_tree()
        self._close_out()

    def _kill_tree(self) -> None:
        pid = self.proc.pid if self.proc is not None else _pid_on_port(PORT)
        if not pid:
            return
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
        except Exception as exc:  # noqa: BLE001 - psutil missing or the process is gone
            log.info("tree kill: %s", exc)
            if self.proc is not None:
                self.proc.kill()

    def _close_out(self) -> None:
        if self._out is not None:
            try:
                self._out.close()
            except OSError:
                pass
            self._out = None


def _pid_on_port(port: int) -> Optional[int]:
    """The process listening on 127.0.0.1:<port>, if it runs our runtime."""
    try:
        import psutil
        for conn in psutil.net_connections(kind="tcp"):
            if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN and conn.pid:
                exe = Path(psutil.Process(conn.pid).exe())
                if exe.parent == PYTHON.parent:
                    return conn.pid
    except Exception:  # noqa: BLE001
        pass
    return None


# ----------------------------------------------------------------- window
def find_edge() -> Optional[Path]:
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, EDGE_APP_PATH, 0, winreg.KEY_READ | view) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                path = Path(os.path.expandvars(str(value).strip('"')))
                if path.is_file():
                    return path
            except OSError:
                continue
    for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.is_file():
                return path
    return None


def _process_name(pid: int) -> str:
    try:
        import psutil
        return psutil.Process(pid).name().lower()
    except Exception:  # noqa: BLE001
        return ""


def app_windows() -> list[int]:
    """Our Edge app windows: Edge's window class, a title with "Robot Hub" and
    no browser suffix (an app window shows only the page title)."""
    found: list[int] = []

    def visit(hwnd, _lparam):
        if not _u32.IsWindowVisible(hwnd):
            return True
        n = _u32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        _u32.GetWindowTextW(hwnd, title, n + 1)
        cls = ctypes.create_unicode_buffer(64)
        _u32.GetClassNameW(hwnd, cls, 64)
        text = title.value
        if (cls.value == "Chrome_WidgetWin_1" and "Robot Hub" in text
                and not text.endswith(("Edge", "Chrome", "Firefox"))):
            pid = wt.DWORD()
            _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _process_name(pid.value) == "msedge.exe":
                found.append(hwnd)
        return True

    _u32.EnumWindows(_WNDENUMPROC(visit), 0)
    return found


def open_window() -> None:
    """Bring the app window to the front, or open one."""
    for hwnd in app_windows():
        if _u32.IsIconic(hwnd):
            _u32.ShowWindow(hwnd, SW_RESTORE)
        _u32.SetForegroundWindow(hwnd)
        log.info("focused the open window")
        return
    edge = find_edge()
    if edge:
        EDGE_PROFILE.mkdir(parents=True, exist_ok=True)
        args = [str(edge), f"--app={URL}", f"--user-data-dir={EDGE_PROFILE}",
                "--no-first-run", "--no-default-browser-check", "--window-size=1280,860"]
        try:
            subprocess.Popen(args, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log.info("opened the app window with %s", edge)
            return
        except OSError as exc:
            log.warning("could not start Edge: %s", exc)
    import webbrowser
    webbrowser.open(URL)
    log.info("opened %s in the default browser", URL)


def close_windows() -> None:
    for hwnd in app_windows():
        _u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


# ----------------------------------------------------------------- tray
class Tray:
    def __init__(self, hub: HubProcess, open_on_start: bool) -> None:
        import pystray
        from PIL import Image, ImageOps

        self.hub = hub
        self.open_on_start = open_on_start
        self.state = "starting"          # starting | running | stopped | quitting
        self._lock = threading.Lock()
        self._misses = 0
        img = Image.open(HUB_DIR / "assets" / "labalab.ico")
        img.size = (64, 64)
        img.load()
        self.img_on = img.convert("RGBA")
        grey = ImageOps.grayscale(self.img_on).convert("RGBA")
        grey.putalpha(self.img_on.getchannel("A").point(lambda a: a * 6 // 10))
        self.img_off = grey
        item = pystray.MenuItem
        self.icon = pystray.Icon(
            "LabaLabRobotHub", self.img_on, APP_NAME,
            menu=pystray.Menu(
                item("Open Robot Hub", self.on_open, default=True),
                item(lambda _i: self.status_word(), None, enabled=False),
                item("Restart", self.on_restart, visible=lambda _i: self.state == "stopped"),
                pystray.Menu.SEPARATOR,
                item("Quit", self.on_quit),
            ))

    def status_word(self) -> str:
        return {"starting": "Starting", "running": "Running",
                "stopped": "Stopped", "quitting": "Quitting"}[self.state]

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        log.info("hub state: %s -> %s", self.state, state)
        self.state = state
        self.icon.icon = self.img_off if state == "stopped" else self.img_on
        self.icon.title = APP_NAME if state == "running" else f"{APP_NAME}: {self.status_word().lower()}"
        try:
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass
        if state == "stopped":
            try:
                self.icon.notify("Robot Hub stopped. Click the tray icon to start it again.", APP_NAME)
            except Exception:  # noqa: BLE001
                pass

    # -- actions
    def boot(self, open_after: bool) -> None:
        with self._lock:
            self.set_state("starting")
            if not hub_answers():
                try:
                    self.hub.start()
                except OSError as exc:
                    log.error("could not start the hub: %s", exc)
                    self.set_state("stopped")
                    message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'hub-stdout.log'}")
                    return
                if not self.hub.wait_ready():
                    self.set_state("stopped")
                    message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'hub-stdout.log'}")
                    return
            self._misses = 0
            self.set_state("running")
        if open_after:
            open_window()

    def on_open(self, *_a) -> None:
        if self.state == "stopped":
            threading.Thread(target=self.boot, args=(True,), daemon=True).start()
        elif self.state == "running":
            open_window()
        # starting: the window opens by itself when the hub is up

    def on_restart(self, *_a) -> None:
        threading.Thread(target=self.boot, args=(True,), daemon=True).start()

    def on_quit(self, *_a) -> None:
        self.state = "quitting"
        threading.Thread(target=self._quit, daemon=True).start()

    def _quit(self) -> None:
        log.info("quit from the tray")
        self.hub.stop()
        close_windows()
        self.icon.stop()

    # -- background threads
    def watch(self) -> None:
        """Notice a hub that stopped. A clean exit means it was told to quit
        (Settings > Quit): then the launcher goes too."""
        while self.state != "quitting":
            time.sleep(2)
            if self.state != "running":
                continue
            code = self.hub.exit_code()
            if code is not None:
                if code in CLEAN_EXITS and hub_answers():
                    # It found another hub already on the port and left that
                    # one running: watch that one instead.
                    log.info("another hub holds the port; watching it")
                    self.hub.proc = None
                    continue
                if code in CLEAN_EXITS:
                    log.info("the hub quit (exit code %s); the launcher quits too", code)
                    self.state = "quitting"
                    close_windows()
                    self.icon.stop()
                    return
                log.error("the hub stopped with exit code %s", code)
                self.set_state("stopped")
                continue
            if self.hub.ours():
                # Quit from the page: the port closes first, the process may
                # linger on an open WebSocket. Robots are already stopped then.
                self._misses = 0 if port_open() else self._misses + 1
                if self._misses * 2 > CLOSE_GRACE:
                    log.info("the hub closed its port; ending it and quitting")
                    self.hub.kill()
                    self.state = "quitting"
                    close_windows()
                    self.icon.stop()
                    return
            else:
                self._misses = 0 if hub_answers() else self._misses + 1
                if self._misses >= 3:
                    self.set_state("stopped")

    def listen_for_second_start(self) -> None:
        event = _k32.CreateEventW(None, False, False, OPEN_EVENT_NAME)
        if not event:
            return
        while self.state != "quitting":
            if _k32.WaitForSingleObject(event, 1000) == WAIT_OBJECT_0:
                log.info("a second start asked for the window")
                self.on_open()

    def run(self) -> None:
        def setup(icon) -> None:
            icon.visible = True
            threading.Thread(target=self.listen_for_second_start, daemon=True).start()
            threading.Thread(target=self.boot, args=(self.open_on_start,), daemon=True).start()
            threading.Thread(target=self.watch, daemon=True).start()
        self.icon.run(setup=setup)


# ----------------------------------------------------------------- entry
def self_check() -> int:
    """--check: start the hub the way the icon does, ask it for the robots and
    the app info, stop it again (only if this run started it). Prints JSON."""
    hub = HubProcess()
    started = False
    t0 = time.monotonic()
    if not hub_answers():
        hub.start()
        started = True
        if not hub.wait_ready():
            print(json.dumps({"ok": False, "error": "the hub did not start",
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
    result = {"ok": status == 200, "started_by_check": started, "ready_seconds": ready_s,
              "url": URL, "robots_status": status,
              "robots": len(robots) if isinstance(robots, (list, dict)) else None,
              "app_status": app_status, "app": app, "edge": str(find_edge() or ""),
              "data_dir": str(DATA_DIR or ""), "python": str(PYTHON)}
    if started:
        hub.stop()
        result["stopped"] = not hub_answers()
    print(json.dumps(result, indent=1))
    return 0 if result["ok"] else 1


def main(argv: list[str]) -> int:
    check = "--check" in argv
    _setup_logging(to_console=check)
    log.info("launcher %s (installed=%s, data=%s, url=%s)", __file__, INSTALLED, DATA_DIR, URL)
    if not PYTHON.is_file():
        message(f"Robot Hub is incomplete: {PYTHON} is missing. Run the install line again.")
        return 1
    mutex = take_single_instance()
    if mutex is None:
        if check:
            print(json.dumps({"ok": False, "error": "Robot Hub is already running from the tray"}))
            return 1
        if not ask_first_launcher_to_open():
            open_window()
        return 0
    if check:
        return self_check()
    try:
        Tray(HubProcess(), open_on_start="--no-window" not in argv).run()
    except Exception:  # noqa: BLE001 - pythonw has no console to show a traceback
        log.exception("the tray failed; running without it")
        hub = HubProcess()
        if not hub_answers():
            hub.start()
            if not hub.wait_ready():
                message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'hub-stdout.log'}")
                return 1
        if "--no-window" not in argv:
            open_window()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        logging.getLogger("launcher").exception("launcher crashed")
        message(f"Robot Hub could not start.\n\nDetails: {LOG_DIR / 'launcher.log'}")
        sys.exit(1)
