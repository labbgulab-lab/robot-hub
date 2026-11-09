"""The student app's own routes: version and updates, quit, settings, logs.

    GET  /api/app                    {version, data_dir, first_run, update}
                                     (?refresh=1: ask GitHub now, at most once a minute)
    POST /api/app/quit               stop the robots' programs, then the hub
    POST /api/app/update             start the installer, then quit
    GET  /api/settings               the settings (hub/settings.py)
    PUT  /api/settings               any subset -> the full object
    PUT  /api/settings/password/{robot}   {password}  (Furhat)
    POST /api/transcripts/open       opens <data>/transcripts
    POST /api/log/report             zips today's logs into Downloads -> {path}

Also `/api/version` and `/api/quit`, the names STUDENT-APP-PLAN 2.3 used.

Nothing here touches the network at import or in tests: the update check is
an injectable coroutine, started only by hub.main.main().
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from . import applog
from .config import REPO_ROOT
from .settings import SettingsError

log = logging.getLogger("hub.app")

RELEASE_REPO = os.environ.get("ROBOT_HUB_RELEASE_REPO", "labbgulab-lab/robot-hub")
RELEASES_API = "https://api.github.com/repos/{}/releases?per_page=30"
INSTALL_URL = "https://github.com/{}/releases/latest/download/install.ps1"
UPDATE_EVERY_S = 6 * 3600.0
# "Check for updates" asks GitHub at once, but not more than once a minute:
# GitHub allows 60 unauthenticated API calls an hour per address, and a lab
# shares one address.
FORCED_CHECK_MIN_S = 60.0


def read_version(root: Path = REPO_ROOT) -> str:
    """robot-hub/VERSION, or the bundle's app/VERSION one level up."""
    for path in (root / "VERSION", root.parent / "VERSION"):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return "0.0.0"


def version_tuple(text: str) -> tuple[int, ...]:
    """"v1.2.10" -> (1, 2, 10). Anything without a number -> ()."""
    return tuple(int(n) for n in re.findall(r"\d+", str(text or ""))[:4])


def error(message: str, code: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": message, "code": code, **extra}, status_code=status)


# ------------------------------------------------------------------ updates
Fetch = Callable[[], Awaitable[dict[str, Any]]]


async def github_latest(repo: str = RELEASE_REPO) -> dict[str, Any]:
    """The newest release: {"tag": ..., "url": ...}; {} when there is none."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        resp = await client.get(RELEASES_API.format(repo),
                                headers={"Accept": "application/vnd.github+json"})
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return pick_app_release(resp.json())


def pick_app_release(releases: Any) -> dict[str, Any]:
    """The newest published app release: a `v<number>` tag that carries a
    RobotHub-*.zip. Other releases in the repo (the robot-files library) and
    drafts or pre-releases are skipped."""
    best: dict[str, Any] = {}
    for rel in releases if isinstance(releases, list) else []:
        tag = str(rel.get("tag_name") or "")
        if rel.get("draft") or rel.get("prerelease") or not re.match(r"^v\d", tag):
            continue
        if not any(str(a.get("name", "")).startswith("RobotHub-") and str(a.get("name", "")).endswith(".zip")
                   for a in rel.get("assets") or []):
            continue
        if not best or version_tuple(tag) > version_tuple(best["tag"]):
            best = {"tag": tag, "url": str(rel.get("html_url") or "")}
    return best


class UpdateChecker:
    """Asks GitHub for the latest release at most once per `interval_s`, in
    the background. Off until `enable()` (hub.main.main() turns it on)."""

    def __init__(self, version: str, fetch: Optional[Fetch] = None,
                 interval_s: float = UPDATE_EVERY_S) -> None:
        self.version = version
        self.fetch: Fetch = fetch or github_latest
        self.interval_s = interval_s
        self.enabled = False
        self.latest: Optional[str] = None
        self.notes_url: Optional[str] = None
        self.checked_at: Optional[float] = None
        self._task: Optional[asyncio.Task] = None

    def enable(self) -> None:
        self.enabled = True

    @property
    def available(self) -> bool:
        if not self.latest:
            return False
        latest, current = version_tuple(self.latest), version_tuple(self.version)
        return bool(latest) and latest > current

    def public(self) -> dict[str, Any]:
        return {"available": self.available, "latest": self.latest,
                "notes_url": self.notes_url}

    async def check(self) -> dict[str, Any]:
        """One check now. A network failure keeps the last answer."""
        self.checked_at = time.time()
        try:
            info = await self.fetch()
        except Exception as exc:  # noqa: BLE001
            log.info("update check failed: %s", exc)
            return self.public()
        if info:
            self.latest = info.get("tag") or None
            self.notes_url = info.get("url") or None
        if self.available:
            log.info("a newer Robot Hub is out: %s (this is %s)", self.latest, self.version)
        return self.public()

    def due(self, now: Optional[float] = None, force: bool = False) -> bool:
        now = time.time() if now is None else now
        wait = FORCED_CHECK_MIN_S if force else self.interval_s
        return self.checked_at is None or now - self.checked_at >= wait

    def poke(self, force: bool = False) -> None:
        """Start a background check if one is due (never waits for it).
        `force` is the Check for updates button: due after a minute, not
        after the full interval."""
        if not self.enabled or not self.due(force=force):
            return
        if self._task is not None and not self._task.done():
            return
        try:
            self._task = asyncio.get_running_loop().create_task(self.check())
        except RuntimeError:
            pass

    async def run(self) -> None:
        """Background loop: check now, then every interval."""
        while True:
            if self.enabled and self.due():
                await self.check()
            await asyncio.sleep(min(self.interval_s, 600.0))


def start_installer(repo: str = RELEASE_REPO) -> None:
    """Run the one-line installer in its own process, which outlives the hub.
    It stops this hub (/api/quit), swaps the app folder and opens the app.
    A visible window, so the student sees the download progress."""
    command = "irm {} | iex".format(INSTALL_URL.format(repo))
    argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                              "stderr": subprocess.DEVNULL, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | subprocess.CREATE_NEW_CONSOLE)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, **kwargs)


def open_folder(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(path)])


# ------------------------------------------------------------ single instance
def port_owner(host: str, port: int, timeout_s: float = 1.5) -> Optional[str]:
    """None when nothing listens on host:port; "hub" when a Robot Hub answers
    there; "other" when something else holds the port."""
    import socket
    probe = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        with socket.create_connection((probe, port), timeout=timeout_s):
            pass
    except OSError:
        return None
    try:
        import httpx
        for path in ("/api/app", "/api/robots"):
            resp = httpx.get("http://{}:{}{}".format(probe, port, path), timeout=timeout_s)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, dict) and ("version" in body or "robots" in body):
                    return "hub"
    except Exception:  # noqa: BLE001
        pass
    return "other"


# ------------------------------------------------------------------ router
def make_router(hub: Any, *, checker: UpdateChecker,
                quit_app: Callable[[], Awaitable[None]],
                installer: Callable[[], None] = start_installer,
                opener: Callable[[Path], None] = open_folder,
                downloads: Callable[[], Path] = applog.downloads_dir) -> APIRouter:
    router = APIRouter()
    store = hub.settings

    def data_dir() -> Path:
        return Path(hub.config.data_dir)

    def settings_changed(public: dict[str, Any]) -> dict[str, Any]:
        # The main page listens for {"type": "settings", "auto_connect": ...}.
        hub.bus.publish({"type": "settings", **public})
        return public

    # -- app ------------------------------------------------------------
    @router.get("/api/app")
    async def get_app(refresh: bool = False) -> dict[str, Any]:
        # ?refresh=1 is the Check for updates button.
        checker.poke(force=refresh)
        return {"version": checker.version, "data_dir": str(data_dir()),
                "first_run": bool(store.first_run), "update": checker.public()}

    @router.get("/api/version")
    async def get_version() -> dict[str, Any]:
        return {"version": checker.version}

    async def _quit() -> JSONResponse:
        hub.bus.emit_log("info", "Robot Hub is closing")
        return JSONResponse({"ok": True}, background=BackgroundTask(quit_app))

    router.add_api_route("/api/app/quit", _quit, methods=["POST"])
    router.add_api_route("/api/quit", _quit, methods=["POST"])

    @router.post("/api/app/update")
    async def post_update() -> JSONResponse:
        try:
            installer()
        except Exception as exc:  # noqa: BLE001
            hub.bus.emit_log("error", "could not start the update: {}".format(exc))
            return error("Could not start the update.", "UPDATE_FAILED", 500)
        hub.bus.emit_log("info", "updating Robot Hub; it will open again when done")
        return JSONResponse({"ok": True}, background=BackgroundTask(quit_app))

    # -- settings -------------------------------------------------------
    @router.get("/api/settings")
    async def get_settings() -> dict[str, Any]:
        return store.public()

    @router.put("/api/settings", response_model=None)
    async def put_settings(request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return error("That is not a settings object.", "BAD_SETTING")
        if not isinstance(body, dict):
            return error("That is not a settings object.", "BAD_SETTING")
        before = store.get("auto_connect")
        try:
            public = store.update(body)
        except SettingsError as exc:
            return error(str(exc), exc.code)
        if "auto_connect" in body and bool(body["auto_connect"]) != bool(before):
            hub.bus.emit_log("info", "auto-connect {}".format(
                "on" if public["auto_connect"] else "off"))
        return settings_changed(public)

    @router.put("/api/settings/password/{robot}", response_model=None)
    async def put_password(robot: str, request: Request):
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = None
        if not isinstance(body, dict) or not isinstance(body.get("password"), str):
            return error("Type the password.", "BAD_SETTING")
        try:
            public = store.set_password(robot, body["password"])
        except SettingsError as exc:
            return error(str(exc), exc.code, 404 if exc.code == "UNKNOWN_ROBOT" else 400)
        hub.bus.emit_log("info", "{} password saved; it is used at the next Connect".format(
            robot.capitalize()))
        return settings_changed(public)

    @router.post("/api/transcripts/open", response_model=None)
    async def open_transcripts():
        folder = store.transcripts_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(opener, folder)
        except Exception as exc:  # noqa: BLE001
            hub.bus.emit_log("warn", "could not open the transcripts folder: {}".format(exc))
            return error("Could not open the folder.", "OPEN_FAILED", 500)
        return {"ok": True, "path": str(folder)}

    # -- logs -----------------------------------------------------------
    @router.post("/api/log/report", response_model=None)
    async def post_log_report():
        secrets = [k.get("key", "") for k in hub.keys.all_secrets()]
        about = "Robot Hub {}\nPython {}\n{}\nconfig: {}\n".format(
            checker.version, platform.python_version(), platform.platform(),
            ", ".join(Path(p).name for p in getattr(hub.config, "layers", [])))
        activity = "\n".join("{}  {:5} {}".format(
            time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0))),
            e.get("level", ""), e.get("text", "")) for e in hub.bus.recent(500))
        try:
            path = await asyncio.to_thread(
                applog.make_report, data_dir() / "logs", downloads(), secrets,
                {"about.txt": about, "activity.txt": activity})
        except Exception as exc:  # noqa: BLE001
            hub.bus.emit_log("error", "could not save the logs: {}".format(exc))
            return error("Could not save the logs.", "REPORT_FAILED", 500)
        hub.bus.emit_log("ok", "logs saved to {}".format(path.name))
        return {"ok": True, "path": str(path)}

    return router
