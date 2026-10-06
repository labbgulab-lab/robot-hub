"""FastAPI app: static page, REST actions, one WebSocket for live state.

The browser never polls a robot. The hub polls; the browser subscribes (3).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import shutil
import tempfile

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import REPO_ROOT, load_config
from .core import Hub
from .library import MAX_BYTES, Library, LibraryError
from . import wifi
from .discovery.selfnet import local_ipv4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)-18s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hub.main")

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="Robot Hub", lifespan=lifespan)


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


class Settings(BaseModel):
    auto_connect: bool


@app.get("/api/settings")
async def get_settings() -> dict[str, Any]:
    return {"auto_connect": hub.config.auto_connect}


@app.put("/api/settings")
async def put_settings(settings: Settings) -> dict[str, Any]:
    hub.config.auto_connect = settings.auto_connect
    hub.bus.emit_log("info", "auto-connect {}".format(
        "on" if settings.auto_connect else "off"))
    hub.bus.publish({"type": "settings", "auto_connect": settings.auto_connect})
    return {"auto_connect": hub.config.auto_connect}


# ------------------------------------------------------------------- keys
# Secrets come in here and never go back out: every response is the public
# view (label + last four characters).


class NewKey(BaseModel):
    provider: str
    label: str = ""
    key: str


class KeyChoice(BaseModel):
    key_id: str | None = None


@app.get("/api/keys")
async def get_keys() -> dict[str, Any]:
    return hub.keys_event()


@app.post("/api/keys")
async def post_key(body: NewKey) -> dict[str, Any]:
    return hub.add_key(body.provider, body.label, body.key)


@app.delete("/api/keys/{key_id}")
async def delete_key(key_id: str) -> dict[str, Any]:
    return hub.remove_key(key_id)


@app.put("/api/robots/{key}/key")
async def put_robot_key(key: str, body: KeyChoice) -> dict[str, Any]:
    return hub.assign_key(key, body.key_id)


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
    return await asyncio.to_thread(wifi.status, addresses)


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


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def main() -> None:
    import uvicorn
    uvicorn.run("hub.main:app", host=config.server.host, port=config.server.port,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
