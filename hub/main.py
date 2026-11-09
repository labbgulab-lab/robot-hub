"""FastAPI app: static page, REST actions, one WebSocket for live state.

The browser never polls a robot. The hub polls; the browser subscribes (3).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import shutil
import tempfile
import time

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import applog, platforms
from .app_api import UpdateChecker, make_router as make_app_router, port_owner, read_version
from .config import REPO_ROOT, load_config
from .core import Hub
from .features_api import make_router as make_features_router
from .group.api import make_router as make_group_router
from .group.conductor import GroupManager
from .library import MAX_BYTES, Library, LibraryError
from .reachy_proxy import make_router as make_reachy_router
from .transcripts import TranscriptStore, make_router as make_transcripts_router
from . import wifi
from .discovery.selfnet import local_ipv4

# Under pythonw (the student app has no console) sys.stdout and sys.stderr are
# None, and anything that writes to them -- uvicorn's console logging, a stray
# print -- raises. They go nowhere instead; the log file has everything.
# The Mac launcher has no console either, but hands the hub a file for its
# output (data/logs/hub-stdout.log, for a crash at start) and sets
# ROBOT_HUB_WINDOWLESS=1: no per-request lines there, only warnings.
STDOUT_IS_LOG = os.environ.get("ROBOT_HUB_WINDOWLESS") == "1"
WINDOWLESS = sys.stdout is None or sys.stderr is None or STDOUT_IS_LOG
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hub.main")


def _log_to_file() -> bool:
    """The Activity panel lives in memory, so a failed Launch on someone
    else's laptop left no trace once the window closed (2026-10-06). The same
    lines go to <data>/logs/hub-<date>.log (git-ignored), a new file each day,
    14 days kept; keys are never logged, only labels. Called from main() only,
    so tests never write to it."""
    handler = applog.install_file_log(config.data_dir / "logs")
    if handler is None:
        return False
    log.info("hub %s starting; this log is %s", read_version(), handler.baseFilename)
    log.info("data folder %s; config from %s", config.data_dir,
             ", ".join(config.layers) or "built-in defaults")
    return True


def _quiet_console(root: logging.Logger = logging.getLogger()) -> None:
    """Console handlers (here a file the launcher reads only after a failed
    start) keep warnings and errors; the dated log file keeps everything.
    Otherwise hub-stdout.log grows by every line of a long lab session."""
    for handler in root.handlers:
        if type(handler) is logging.StreamHandler:
            handler.setLevel(logging.WARNING)

# The Furhat detector fingerprints every host on the subnet every few seconds,
# so httpx at INFO would drown the hub's own log in one line per probe. The
# scan itself reports through the event bus, which is what the user reads.
for _noisy in ("httpx", "httpcore", "zeroconf", "paramiko"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


class _DropProactorResetNoise(logging.Filter):
    """Closing a browser tab makes Windows' proactor transport log a full
    traceback for WinError 10054. It is noise, not a fault -- but only that
    exact case is dropped, so real asyncio errors still surface."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "_call_connection_lost" not in record.getMessage()


logging.getLogger("asyncio").addFilter(_DropProactorResetNoise())

WEB_DIR = REPO_ROOT / "web"
config = load_config()
hub = Hub(config)
library = Library(config, hub.keys, hub.bus)


group = GroupManager(hub)
# Readable transcripts of every Reachy conversation (hub/transcripts.py).
transcripts = TranscriptStore(folder=hub.settings.transcripts_dir,
                              enabled=lambda: bool(hub.settings.get("save_transcripts")),
                              publish=hub.bus.publish)
transcripts.attach_group(group)
updates = UpdateChecker(read_version())
# The running uvicorn server, so Quit can end it cleanly (set by main()).
_server: Any = None
# One Quit is enough: a second press (or the tray and the page together) while
# the first is still stopping the robots does nothing more.
_quit_started = False
# A Quit always ends the process, even when part of the shutdown hangs (a
# robot that never answers, a stuck thread): this many seconds after the
# server was told to stop, the process exits anyway, with code 0, so the
# launcher still sees a quit and closes the window. Only main() arms it;
# tests that call quit_app() never do.
QUIT_HARD_EXIT_S = 15.0
_hard_exit_on_quit = False


def _exit_soon(delay: float = QUIT_HARD_EXIT_S) -> threading.Timer:
    """The safety net above: a daemon timer, so a normal exit never waits for it."""
    def go() -> None:
        log.warning("the hub did not finish quitting within %.0f s; exiting now", delay)
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001
                pass
        os._exit(0)
    timer = threading.Timer(delay, go)
    timer.daemon = True
    timer.start()
    return timer


async def quit_app() -> None:
    """Settings > Quit, the tray's Quit and the installer: stop every robot
    program the hub started, then end the server; the lifespan below does the
    rest. The server is told to stop even if stopping a robot fails or hangs."""
    global _quit_started
    from .supervisor import get_supervisor
    if _quit_started:
        log.info("quit requested again; already quitting")
        return
    _quit_started = True
    log.info("quit requested")

    async def stop(adapter: Any) -> None:
        try:
            await asyncio.wait_for(adapter.stop_system(), 20)
        except Exception as exc:  # noqa: BLE001
            log.info("stopping %s on quit: %s", getattr(adapter, "display_name", "?"), exc)

    try:
        await asyncio.gather(*(stop(a) for a in list(hub.adapters.values())))
        try:
            await asyncio.wait_for(get_supervisor().stop_all(), 20)
        except Exception as exc:  # noqa: BLE001
            log.warning("stopping the hub's programs on quit: %s", exc)
    finally:
        # Open pages hear it first: they close their WebSocket (so the server
        # does not wait for it) and their window.
        hub.bus.publish({"type": "quitting"})
        if _hard_exit_on_quit:
            _exit_soon()
        if _server is not None:
            _server.should_exit = True
        else:   # started some other way (uvicorn on the command line)
            signal.raise_signal(signal.SIGINT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.start()
    # The group conversation's warnings and errors reach the Logs drawer.
    forwarder = applog.forward_to_bus(hub.bus, "hub.group", "group")
    # The DJI mic watcher and the free keep-alive of the group conversation's
    # services start with the hub -- from main() only (tests start this app
    # too). No paid warm-up at start since the student app (2026-11-05):
    # Get ready on the Reachy page still runs every check.
    if os.environ.get("HUB_WARM_AT_START") == "1":
        await group.startup(warm=False)
        # Keys: the free test call, at most hourly per key (never a paid call).
        hub.enable_key_checks()
    checker_task = None
    if updates.enabled:
        checker_task = asyncio.create_task(updates.run())
    try:
        yield
    finally:
        if checker_task is not None:
            checker_task.cancel()
        logging.getLogger("hub.group").removeHandler(forwarder)
        await group.shutdown()
        await hub.stop()


app = FastAPI(title="Robot Hub", lifespan=lifespan)
# Several Reachys in one conversation (docs/GROUP-CONVERSATION.md).
app.include_router(make_group_router(group))
# Version and updates, Quit, Settings, the log report (hub/app_api.py).
app.include_router(make_app_router(hub, checker=updates, quit_app=quit_app))
# Keys, setup, network, robot details, Add WiFi (hub/features_api.py).
app.include_router(make_features_router(hub))
# The Reachy app's Talk and Wizard of Oz tabs: the robot's reachy_chat through
# the hub (hub/reachy_proxy.py), and the "Saving transcript" mark.
app.include_router(make_reachy_router(hub, transcripts=transcripts))
app.include_router(make_transcripts_router(transcripts))


@app.middleware("http")
async def no_stale_page(request, call_next):
    """The page's own files are tiny and change under a running hub; without
    this a browser kept an old app.js after an update (2026-10-05)."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# ------------------------------------------------------------------- REST
@app.get("/api/robots")
async def get_robots() -> dict[str, Any]:
    return hub.snapshot()


@app.post("/api/robots/{key}/connect")
async def post_connect(key: str) -> JSONResponse:
    result = await hub.connect(key)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/robots/{key}/disconnect")
async def post_disconnect(key: str) -> JSONResponse:
    result = await hub.disconnect(key)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/robots/{key}/launch")
async def post_launch(key: str) -> JSONResponse:
    result = await hub.launch(key)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/robots/{key}/override")
async def post_override(key: str) -> JSONResponse:
    """Proceed past a resource conflict. Logged loudly (7.2)."""
    result = await hub.launch(key, override=True)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


class PostureRequest(BaseModel):
    name: str


@app.post("/api/robots/{key}/posture")
async def post_posture(key: str, body: PostureRequest) -> JSONResponse:
    """NAO's Sit / Lie down / Stand up buttons. Refusals (a hot joint, a busy
    card) come back as 409 with the sentence in `error`."""
    result = await hub.posture(key, body.name)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/rescan")
async def post_rescan() -> dict[str, Any]:
    """Ask the detectors to sweep again now. Discovery never stops; this only
    shortens the wait when someone has just powered a robot on."""
    return await hub.rescan()


# GET/PUT /api/settings live in hub/app_api.py (persisted in settings.json).


# Keys: GET/POST /api/keys, /api/keys/{id}/check, DELETE, PUT
# /api/robots/{key}/key live in hub/features_api.py.


@app.get("/api/log")
async def get_log(limit: int = 200) -> dict[str, Any]:
    return {"log": hub.bus.recent(limit)}


@app.get("/api/resources")
async def get_resources() -> dict[str, Any]:
    return hub.resources.snapshot()


@app.get("/api/doctor")
async def get_doctor() -> dict[str, Any]:
    from .doctor import run_checks
    return {"checks": await asyncio.get_running_loop().run_in_executor(
        None, run_checks, hub.config)}



# ------------------------------------------------------------------- wifi
# Which WiFi this laptop is on and whether the robots can join it (2.4 GHz,
# a phone hotspot). Asked by the Network setup panel; never cached, because
# the answer is what someone just changed on their phone.
@app.get("/api/wifi")
async def get_wifi() -> dict[str, Any]:
    addresses = [str(n) for n in await asyncio.to_thread(local_ipv4)]
    return await asyncio.to_thread(wifi.status, addresses, config.network.lab_wifi)


# ------------------------------------------------------------------ files
# The lab's shared robot files (hub/library.py): a GitHub release, keys
# removed on the way up, optionally put back (this hub's own) on the way down.

def _library_error(exc: Exception) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=409)


@app.get("/api/files")
async def get_files() -> JSONResponse:
    try:
        return JSONResponse(await library.listing())
    except (LibraryError, OSError) as exc:
        return _library_error(exc)
    except Exception as exc:  # noqa: BLE001  (network down: say so, not 500)
        return _library_error(LibraryError("could not reach GitHub: {}".format(exc)))


@app.post("/api/files")
async def post_file(request: Request, robot: str, name: str,
                    replace: bool = False) -> JSONResponse:
    # The raw body is the file: no multipart parser needed, and an 85 MB
    # skill streams to disk instead of sitting in memory.
    work = Path(tempfile.mkdtemp(dir=library._ensure_workdir()))
    try:
        source = work / Path(name).name
        size = 0
        with source.open("wb") as fh:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BYTES:
                    return _library_error(LibraryError("GitHub takes files up to 2 GB"))
                fh.write(chunk)
        if not size:
            return _library_error(LibraryError("that file is empty"))
        result = await library.upload(robot, name, source, replace=replace)
        return JSONResponse(result, status_code=200 if result.get("ok") else 409)
    except LibraryError as exc:
        hub.bus.emit_log("error", "Files: {}".format(exc))
        return _library_error(exc)
    except Exception as exc:  # noqa: BLE001
        hub.bus.emit_log("error", "Files: upload failed - {}".format(exc))
        return _library_error(LibraryError("upload failed: {}".format(exc)))
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.delete("/api/files/{asset_id}")
async def delete_file(asset_id: int) -> JSONResponse:
    try:
        return JSONResponse(await library.delete(asset_id))
    except LibraryError as exc:
        return _library_error(exc)


@app.get("/api/files/{asset_id}/download", response_model=None)
async def download_file(asset_id: int, key_id: str | None = None):
    try:
        path, name, work = await library.fetch(asset_id, key_id or None)
    except Exception as exc:  # noqa: BLE001
        hub.bus.emit_log("error", "Files: download failed - {}".format(exc))
        return _library_error(exc)
    return FileResponse(path, filename=name, media_type="application/octet-stream",
                        background=BackgroundTask(shutil.rmtree, work, True))


# -------------------------------------------------------------- WebSocket
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    queue = hub.bus.subscribe()
    try:
        await ws.send_json({"type": "snapshot", **hub.snapshot()})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                await ws.send_json({"type": "heartbeat"})
                continue
            await ws.send_json(event)
            if event.get("type") == "quitting":
                # Quit: close now, or the server waits for this socket.
                await ws.close()
                return
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.info("websocket closed: %s", exc)
    finally:
        hub.bus.unsubscribe(queue)


# ------------------------------------------------------------------ static
@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/group.html", response_model=None)
async def group_page() -> RedirectResponse:
    """The group page became the Reachy app's Group tab (2026-11-05)."""
    return RedirectResponse("/reachy.html#group", status_code=307)


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    global _server, _hard_exit_on_quit
    import uvicorn
    host, port = config.server.host, config.server.port
    # One hub per laptop: a second start must not fight the first for the
    # port (Windows lets two sockets share it). The launcher focuses the
    # open window; this only refuses.
    owner = port_owner(host, port)
    if owner is not None:
        message = ("Robot Hub is already running at http://127.0.0.1:{}/".format(port)
                   if owner == "hub" else
                   "Port {} is in use by another program, so Robot Hub cannot start. "
                   "Close that program, or set another port in config.toml.".format(port))
        log.error(message)
        print(message, file=sys.stderr)
        raise SystemExit(0 if owner == "hub" else 2)
    if _log_to_file() and STDOUT_IS_LOG:
        _quiet_console()
    if platforms.is_mac():
        # Started from Finder or the Dock, the hub has launchd's 256 open
        # files; the ping sweep alone runs 64 pings with their pipes.
        platforms.raise_open_file_limit()
    os.environ["HUB_WARM_AT_START"] = "1"   # lifespan: watch the mic, keep services open
    updates.enable()                         # background check, at most every 6 h
    if WINDOWLESS:
        # A failing log write must never print a traceback to a stderr that
        # does not exist (pythonw): that is the "'NoneType' ... write" noise.
        logging.raiseExceptions = False
    server_config = uvicorn.Config(
        # The app object, not "hub.main:app": with `python -m hub.main` the
        # string would import this module a second time, and Quit would reach
        # the copy that has no server.
        app, host=host, port=port, reload=False, log_level="info",
        # An open app window holds a WebSocket; don't wait 25 s for it on Quit.
        timeout_graceful_shutdown=3,
        # Without a console uvicorn's own handlers have nowhere to write: its
        # lines go to the root logger (the log file) instead, minus one line
        # per request.
        log_config=None if WINDOWLESS else uvicorn.config.LOGGING_CONFIG,
        access_log=not WINDOWLESS)
    _server = uvicorn.Server(server_config)
    _hard_exit_on_quit = True              # Quit always ends the process
    _server.run()


if __name__ == "__main__":
    # Run the importable module's main(), so `python -m hub.main` and
    # `from hub.main import main` share one app, one server and one Quit.
    from hub.main import main as _main
    _main()
