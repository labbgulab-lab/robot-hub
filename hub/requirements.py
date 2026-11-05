"""What this laptop needs before a robot works: the setup items
(STUDENT-APP-PLAN 4, BUILD-PLAN "Setup").

One generic model for every item:

    {"id": "naoqi_kit", "label": "Pepper and NAO kit", "for": ["naoqi", "pepper"],
     "state": "ok" | "missing" | "downloading" | "unpacking" | "verifying" | "failed",
     "progress": {"done": bytes or files, "total": ...} | None,
     "detail": short sentence, "code": friendly-error code | None,
     "actions": ["download", "cancel", "check", "choose_zip", "open"]}

Items:
  naoqi_kit        the pynaoqi SDK, which carries its own Python 2.7. Found in
                   C:\\LabaLab\\naoqi-sdk, %PUBLIC%\\LabaLab\\naoqi-sdk or the
                   configured path; downloaded (public 2.8.7.4 win64 zip, about
                   358 MB) with progress and cancel, unpacked zip-slip safe,
                   and verified by importing naoqi in the kit's own Python.
  reachy_lite_app  Pollen's "Reachy Mini Control" desktop app (USB Reachy).
  furhat_password  Furhat Studio's password: the saved one, and whether the
                   last login with it worked.

Every state is computed when asked, so a fix needs no restart. Progress goes
out as {"type": "setup", "item": {...}} on the hub's event bus.

Nothing here touches the network or a file dialog at import or in tests:
the downloader, the verifier, the dialog and the browser opener are all
injectable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .config import find_naoqi_kit, naoqi_kit_dirs

log = logging.getLogger("hub.setup")

# The maker's public 2.8.7.4 win64 SDK zip (no login). A lab can point the hub
# at another copy with [robots.naoqi.settings] kit_url or ROBOT_HUB_NAOQI_KIT_URL.
NAOQI_KIT_URL = ("https://community-static.aldebaran.com/resources%2F2.8.7%2FPython%20SDK%2F"
                 "pynaoqi-python2.7-2.8.7.4-win64-vs2015-20210818_210634.zip")   # 200, 358,104,930 bytes (checked 2026-11-05)
NAOQI_KIT_PAGE = "https://maxtronics.com/software-development-kit/"
NAOQI_KIT_BYTES = 358104930
# Unpacked the kit is about 1.2 GB; Defender scans ~6,000 files.
NAOQI_KIT_UNPACKED_BYTES = 1500 * 1024 * 1024
VERIFY_TIMEOUT_S = 20.0
REACHY_APP_PAGE = "https://github.com/pollen-robotics/reachy-mini-desktop-app/releases/latest"

PROGRESS_EVERY_S = 0.3

ITEMS = ("naoqi_kit", "reachy_lite_app", "furhat_password")
LABELS = {"naoqi_kit": "Pepper and NAO kit",
          "reachy_lite_app": "Reachy Mini Control app",
          "furhat_password": "Furhat password"}
FOR = {"naoqi_kit": ["naoqi", "pepper"], "reachy_lite_app": ["reachy_lite"],
       "furhat_password": ["furhat"]}
ACTIONS = ("download", "cancel", "check", "choose_zip", "open")


class SetupError(Exception):
    """A setup step that failed; `code` is the friendly-error code."""

    def __init__(self, message: str, code: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


# ------------------------------------------------------- the NAOqi kit paths
def naoqi_kit_paths(config: Any = None,
                    bases: Optional[list[Path]] = None) -> dict[str, Path]:
    """{"pynaoqi_sdk": ..., "python2": ...} or {} -- the configured paths
    when both are set and exist, else the installed kit. Read fresh each
    time, so a kit installed a moment ago is used without a restart."""
    if config is not None:
        sdk = config.path("naoqi", "pynaoqi_sdk")
        py = config.path("naoqi", "python2")
        if sdk is not None and py is not None and (sdk / "lib").is_dir() and py.is_file():
            return {"pynaoqi_sdk": sdk, "python2": py}
    return find_naoqi_kit(bases)


def kit_env(sdk: Path, python2: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(sdk / "lib")
    env["PYTHONIOENCODING"] = "utf-8"
    home = sdk / "lib" / "python2.7"
    if home.is_dir() and python2.parent == sdk / "bin":
        env["PYTHONHOME"] = str(home)
    env["PATH"] = str(sdk / "bin") + os.pathsep + env.get("PATH", "")
    return env


def verify_kit(paths: dict[str, Path]) -> tuple[bool, str]:
    """Blocking. The check is the import itself, in the kit's own Python 2.7
    (it also catches a 32-bit Python a version check would let through)."""
    from .winproc import no_window
    sdk, py = paths.get("pynaoqi_sdk"), paths.get("python2")
    if sdk is None or py is None:
        return False, "The kit has no Python 2.7 in it."
    try:
        out = subprocess.run([str(py), "-B", "-c", "import naoqi; print('ok')"],
                             env=kit_env(sdk, py), capture_output=True,
                             timeout=VERIFY_TIMEOUT_S, cwd=str(sdk), **no_window())
    except subprocess.TimeoutExpired:
        return False, "The kit's Python did not answer within {:.0f} s.".format(VERIFY_TIMEOUT_S)
    except OSError as exc:
        return False, "The kit's Python would not start ({}).".format(exc)
    if out.returncode == 0 and b"ok" in out.stdout:
        return True, "Installed."
    last = out.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
    return False, "The kit is there but naoqi does not load ({}).".format(last[0][:160])


# ------------------------------------------------------------ the download
Progress = Callable[[int, Optional[int]], None]
Downloader = Callable[[str, Path, Progress], Awaitable[None]]


class DownloadBroke(Exception):
    pass


async def httpx_download(url: str, dest: Path, progress: Progress) -> None:
    """Stream `url` into `dest`, calling progress(done, total)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0),
                                     follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise DownloadBroke("the download page answered {}".format(resp.status_code))
                total = int(resp.headers.get("content-length") or 0) or None
                done = 0
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        fh.write(chunk)
                        done += len(chunk)
                        progress(done, total)
                if total and done < total:
                    raise DownloadBroke("the download stopped at {} of {} bytes".format(done, total))
    except httpx.TransportError as exc:
        raise DownloadBroke(str(exc) or type(exc).__name__) from exc


def _tk_pick_zip() -> Optional[str]:
    """Blocking: the native Open dialog, on top of everything."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass
    try:
        path = filedialog.askopenfilename(
            parent=root, title="Choose the Pepper and NAO kit zip",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")])
    finally:
        root.destroy()
    return path or None


def _open_page(url: str) -> None:
    import webbrowser
    webbrowser.open(url)


# ------------------------------------------------------------------ unpack
class WrongZip(Exception):
    pass


class Cancelled(Exception):
    pass


def unpack_zip(zip_path: Path, dest: Path, progress: Progress,
               cancelled: Callable[[], bool] = lambda: False) -> None:
    """Blocking. Unpack into `dest` (created fresh), dropping a single top
    folder shared by every entry. Refuses any entry that would land outside
    `dest` (zip slip)."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise WrongZip("that file is not a zip ({})".format(exc)) from exc
    with zf:
        members = [m for m in zf.infolist() if m.filename and not m.filename.startswith("__MACOSX")]
        if not members:
            raise WrongZip("the zip is empty")
        tops = {m.filename.replace("\\", "/").split("/", 1)[0] for m in members}
        strip = ""
        if len(tops) == 1 and all("/" in m.filename.replace("\\", "/") for m in members
                                  if not m.is_dir()):
            strip = tops.pop() + "/"
        root = dest.resolve()
        dest.mkdir(parents=True, exist_ok=True)
        total = len(members)
        for n, member in enumerate(members, 1):
            if cancelled():
                raise Cancelled()
            name = member.filename.replace("\\", "/")
            if strip and name.startswith(strip):
                name = name[len(strip):]
            if not name:
                continue
            target = (root / name).resolve()
            if target != root and root not in target.parents:
                raise WrongZip("the zip tries to write outside its folder ({})".format(member.filename))
            if member.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
            progress(n, total)


def _free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        return shutil.disk_usage(str(probe)).free
    except OSError:
        return 1 << 62


def _writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_bytes(b"x")
        probe.unlink()
        return True
    except OSError:
        return False


# ----------------------------------------------------------------- manager
class SetupManager:
    def __init__(self, config: Any, bus: Any = None, settings: Any = None, *,
                 downloader: Optional[Downloader] = None,
                 verifier: Optional[Callable[[dict[str, Path]], tuple[bool, str]]] = None,
                 file_dialog: Optional[Callable[[], Optional[str]]] = None,
                 opener: Optional[Callable[[str], None]] = None,
                 kit_dirs: Optional[list[Path]] = None,
                 free_bytes: Callable[[Path], int] = _free_bytes,
                 find_control_app: Optional[Callable[[], Optional[Path]]] = None) -> None:
        self.config = config
        self.bus = bus
        self.settings = settings
        self.downloader = downloader or httpx_download
        self.verifier = verifier or verify_kit
        self.file_dialog = file_dialog or _tk_pick_zip
        self.opener = opener or _open_page
        self.kit_dirs = kit_dirs
        self.free_bytes = free_bytes
        self._find_control_app = find_control_app
        # The kit job in flight (download / unpack / verify) and its view.
        self._job: Optional[asyncio.Task] = None
        self._cancel = False
        self._phase: Optional[str] = None
        self._progress: Optional[dict[str, Any]] = None
        self._failure: Optional[tuple[str, str]] = None     # (code, detail)
        self._verified: dict[str, tuple[bool, str]] = {}    # sdk path -> result
        self._last_sent = 0.0
        # Called (no arguments) whenever an item's state may have changed.
        self.listeners: list[Callable[[], None]] = []

    # ------------------------------------------------------------- views
    def items(self) -> list[dict[str, Any]]:
        return [self.item(i) for i in ITEMS]

    def item(self, item_id: str) -> dict[str, Any]:
        if item_id == "naoqi_kit":
            return self._kit_item()
        if item_id == "reachy_lite_app":
            return self._lite_item()
        if item_id == "furhat_password":
            return self._furhat_item()
        raise SetupError("There is no setup step called {}.".format(item_id),
                         "UNKNOWN_SETUP", 404)

    def _base(self, item_id: str, state: str, detail: str = "",
              code: Optional[str] = None, actions: tuple[str, ...] = (),
              progress: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"id": item_id, "label": LABELS[item_id], "for": list(FOR[item_id]),
                "state": state, "progress": progress, "detail": detail, "code": code,
                "actions": list(actions)}

    def kit_paths(self) -> dict[str, Path]:
        return naoqi_kit_paths(self.config, self.kit_dirs)

    def kit_ready(self) -> bool:
        return self._kit_item()["state"] == "ok"

    def _kit_item(self) -> dict[str, Any]:
        if self._phase is not None:
            words = {"downloading": "Downloading", "unpacking": "Unpacking",
                     "verifying": "Checking"}
            return self._base("naoqi_kit", self._phase, words.get(self._phase, ""),
                              actions=("cancel",), progress=self._progress)
        if self._failure is not None:
            code, detail = self._failure
            return self._base("naoqi_kit", "failed", detail, code,
                              ("download", "choose_zip", "open", "check"))
        paths = self.kit_paths()
        if paths.get("pynaoqi_sdk") and paths.get("python2"):
            known = self._verified.get(str(paths["pynaoqi_sdk"]))
            if known is not None and not known[0]:
                return self._base("naoqi_kit", "failed", known[1], "KIT_BROKEN",
                                  ("download", "choose_zip", "open", "check"))
            return self._base("naoqi_kit", "ok", "Installed.", actions=("check",))
        return self._base("naoqi_kit", "missing", "One free download, about 360 MB.",
                          actions=("download", "choose_zip", "open", "check"))

    def _control_app(self) -> Optional[Path]:
        if self.config is not None:
            configured = self.config.path("reachy_lite", "control_app")
            if configured is not None and configured.is_file():
                return configured
        finder = self._find_control_app
        if finder is None:
            try:
                from .adapters.reachy_lite import find_control_app as finder
            except Exception:  # noqa: BLE001
                return None
        try:
            return finder()
        except Exception:  # noqa: BLE001
            return None

    def _lite_item(self) -> dict[str, Any]:
        app = self._control_app()
        if app is not None:
            return self._base("reachy_lite_app", "ok", "Installed.", actions=("check", "open"))
        return self._base("reachy_lite_app", "missing",
                          "Install Reachy Mini Control from Pollen.", actions=("open", "check"))

    def _furhat_item(self) -> dict[str, Any]:
        info = {}
        if self.settings is not None:
            try:
                info = self.settings.public()["passwords"]["furhat"]
            except Exception:  # noqa: BLE001
                info = {}
        works = info.get("works")
        if works is False:
            return self._base("furhat_password", "failed",
                              "Furhat refused the password. Type the one set on this Furhat.",
                              "PASSWORD_WRONG", ("check",))
        detail = "Works." if works else "Used at the next Connect."
        return self._base("furhat_password", "ok", detail, actions=("check",))

    # ----------------------------------------------------------- events
    def _changed(self, force: bool = True) -> None:
        now = time.monotonic()
        if not force and now - self._last_sent < PROGRESS_EVERY_S:
            return
        self._last_sent = now
        if self.bus is not None:
            self.bus.publish({"type": "setup", "item": self._kit_item()})
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("setup listener failed")

    def _publish(self, item_id: str) -> None:
        if self.bus is not None:
            self.bus.publish({"type": "setup", "item": self.item(item_id)})
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.exception("setup listener failed")

    def _log(self, level: str, text: str) -> None:
        if self.bus is not None and hasattr(self.bus, "emit_log"):
            self.bus.emit_log(level, text)
        else:
            log.info(text)

    # ----------------------------------------------------------- actions
    async def act(self, item_id: str, action: str) -> dict[str, Any]:
        self.item(item_id)          # raises UNKNOWN_SETUP
        if action not in ACTIONS:
            raise SetupError("There is no action called {}.".format(action), "BAD_ACTION")
        if action == "check":
            return await self.check(item_id)
        if action == "open":
            return await self.open_page(item_id)
        if item_id != "naoqi_kit":
            raise SetupError("{} has no {}.".format(LABELS[item_id], action), "BAD_ACTION")
        if action == "download":
            return self.start_download()
        if action == "cancel":
            return await self.cancel()
        return await self.choose_zip()

    async def check(self, item_id: str) -> dict[str, Any]:
        if item_id == "naoqi_kit" and self._phase is None:
            self._failure = None
            paths = self.kit_paths()
            if paths.get("pynaoqi_sdk") and paths.get("python2"):
                result = await asyncio.to_thread(self.verifier, paths)
                self._verified[str(paths["pynaoqi_sdk"])] = result
        self._publish(item_id)
        return self.item(item_id)

    async def open_page(self, item_id: str) -> dict[str, Any]:
        url = {"naoqi_kit": NAOQI_KIT_PAGE, "reachy_lite_app": REACHY_APP_PAGE}.get(item_id)
        if url is None:
            raise SetupError("{} has no download page.".format(LABELS[item_id]), "BAD_ACTION")
        try:
            await asyncio.to_thread(self.opener, url)
        except Exception as exc:  # noqa: BLE001
            raise SetupError("Could not open the page ({}).".format(exc), "OPEN_FAILED", 500)
        return {**self.item(item_id), "url": url}

    def kit_url(self) -> str:
        env = os.environ.get("ROBOT_HUB_NAOQI_KIT_URL", "").strip()
        if env:
            return env
        if self.config is not None:
            url = str(self.config.robot("naoqi").settings.get("kit_url") or "").strip()
            if url:
                return url
        return NAOQI_KIT_URL

    def _busy(self) -> bool:
        return self._job is not None and not self._job.done()

    def start_download(self) -> dict[str, Any]:
        if self._busy():
            raise SetupError("The kit is already being set up.", "BUSY", 409)
        self._start(self._download_job())
        self._phase, self._progress = "downloading", {"done": 0, "total": NAOQI_KIT_BYTES}
        return self.item("naoqi_kit")

    async def choose_zip(self) -> dict[str, Any]:
        if self._busy():
            raise SetupError("The kit is already being set up.", "BUSY", 409)
        try:
            chosen = await asyncio.to_thread(self.file_dialog)
        except Exception as exc:  # noqa: BLE001
            raise SetupError("Could not open the file chooser ({}).".format(exc),
                             "OPEN_FAILED", 500)
        if not chosen:
            return {**self.item("naoqi_kit"), "chosen": None}
        self._start(self._install_job(Path(chosen), downloaded=False))
        return {**self.item("naoqi_kit"), "chosen": Path(chosen).name}

    async def cancel(self) -> dict[str, Any]:
        job = self._job
        if job is not None and not job.done():
            self._cancel = True
            job.cancel()
            await asyncio.wait({job}, timeout=30)
        if self._phase is not None:         # cancelled before it even started
            self._set(None)
        return self.item("naoqi_kit")

    async def wait(self) -> None:
        """Tests: wait for the job in flight."""
        if self._job is not None:
            await asyncio.wait({self._job})

    def _start(self, coro: Awaitable[None]) -> None:
        self._cancel = False
        self._failure = None
        self._job = asyncio.ensure_future(coro)

    def _set(self, phase: Optional[str], done: int = 0, total: Optional[int] = None,
             force: bool = True) -> None:
        self._phase = phase
        self._progress = None if phase is None else {"done": done, "total": total}
        self._changed(force)

    def _fail(self, code: str, detail: str) -> None:
        self._phase = None
        self._progress = None
        self._failure = (code, detail)
        self._log("error", "Pepper and NAO kit: {}".format(detail))
        self._changed()

    def _target_dir(self) -> Path:
        for base in (self.kit_dirs if self.kit_dirs is not None else naoqi_kit_dirs()):
            if _writable_dir(base.parent):
                return base
        raise SetupError("No folder for the kit can be written on this laptop.", "DISK_FULL")

    def _cache_dir(self) -> Path:
        data = Path(getattr(self.config, "data_dir", ".")) if self.config is not None else Path(".")
        return data / "cache"

    async def _download_job(self) -> None:
        cache = self._cache_dir()
        part = cache / "naoqi-kit.zip.part"
        try:
            target = self._target_dir()
            cache.mkdir(parents=True, exist_ok=True)
            if self.free_bytes(cache) < NAOQI_KIT_BYTES + (64 << 20):
                self._fail("DISK_FULL", "Not enough free space for the download (about 360 MB).")
                return
            if self.free_bytes(target) < NAOQI_KIT_UNPACKED_BYTES:
                self._fail("DISK_FULL", "Not enough free space for the kit (about 1.5 GB).")
                return
            self._set("downloading", 0, NAOQI_KIT_BYTES)
            self._log("info", "Pepper and NAO kit: downloading")

            def progress(done: int, total: Optional[int]) -> None:
                self._set("downloading", done, total or NAOQI_KIT_BYTES, force=False)

            await self.downloader(self.kit_url(), part, progress)
        except asyncio.CancelledError:
            _unlink(part)
            self._set(None)
            self._log("info", "Pepper and NAO kit: cancelled")
            raise
        except SetupError as exc:
            _unlink(part)
            self._fail(exc.code, str(exc))
            return
        except OSError as exc:
            _unlink(part)
            if getattr(exc, "errno", None) == 28:       # ENOSPC
                self._fail("DISK_FULL", "The disk filled up during the download.")
            else:
                self._fail("DOWNLOAD_BROKE", "The download broke ({}).".format(exc))
            return
        except Exception as exc:  # noqa: BLE001  (DownloadBroke, Offline, httpx)
            _unlink(part)
            self._fail("DOWNLOAD_BROKE", "The download broke ({}).".format(
                str(exc)[:160] or type(exc).__name__))
            return
        zip_path = cache / "naoqi-kit.zip"
        try:
            os.replace(part, zip_path)
        except OSError as exc:
            self._fail("DOWNLOAD_BROKE", "Could not keep the download ({}).".format(exc))
            return
        try:
            await self._install_job(zip_path, downloaded=True)
        finally:
            _unlink(zip_path)

    async def _install_job(self, zip_path: Path, downloaded: bool) -> None:
        """Unpack `zip_path` into the kit folder, then verify it."""
        try:
            target = self._target_dir()
        except SetupError as exc:
            self._fail(exc.code, str(exc))
            return
        if not downloaded and self.free_bytes(target) < NAOQI_KIT_UNPACKED_BYTES:
            self._fail("DISK_FULL", "Not enough free space for the kit (about 1.5 GB).")
            return
        partial = target.with_name(target.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        self._set("unpacking", 0, None)
        self._log("info", "Pepper and NAO kit: unpacking (Windows checks every file; "
                          "this takes a few minutes)")
        loop = asyncio.get_running_loop()

        def progress(done: int, total: Optional[int]) -> None:
            loop.call_soon_threadsafe(self._set, "unpacking", done, total, False)

        try:
            await asyncio.to_thread(unpack_zip, zip_path, partial, progress,
                                    lambda: self._cancel)
        except asyncio.CancelledError:
            self._cancel = True
            shutil.rmtree(partial, ignore_errors=True)
            self._set(None)
            self._log("info", "Pepper and NAO kit: cancelled")
            raise
        except Cancelled:
            shutil.rmtree(partial, ignore_errors=True)
            self._set(None)
            return
        except WrongZip as exc:
            shutil.rmtree(partial, ignore_errors=True)
            self._fail("WRONG_ZIP", "That is not the Pepper and NAO kit: {}.".format(exc))
            return
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            if getattr(exc, "errno", None) == 28:
                self._fail("DISK_FULL", "The disk filled up while unpacking.")
            else:
                self._fail("WRONG_ZIP", "Could not unpack the kit ({}).".format(exc))
            return

        found = find_naoqi_kit([partial])
        if not found.get("pynaoqi_sdk") or not found.get("python2"):
            shutil.rmtree(partial, ignore_errors=True)
            self._fail("WRONG_ZIP", "That zip is not the Windows 64-bit Pepper and NAO kit.")
            return
        try:
            if target.exists():
                old = target.with_name(target.name + ".old")
                shutil.rmtree(old, ignore_errors=True)
                os.replace(target, old)
                shutil.rmtree(old, ignore_errors=True)
            os.replace(partial, target)
        except OSError as exc:
            shutil.rmtree(partial, ignore_errors=True)
            self._fail("WRONG_ZIP", "Could not move the kit into place ({}).".format(exc))
            return

        self._set("verifying", 0, None)
        paths = find_naoqi_kit([target])
        ok, detail = await asyncio.to_thread(self.verifier, paths)
        self._verified[str(paths.get("pynaoqi_sdk"))] = (ok, detail)
        if not ok:
            self._fail("WRONG_ZIP", detail)
            return
        self._set(None)
        self._log("ok", "Pepper and NAO kit installed in {}".format(target))
        self._changed()


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
