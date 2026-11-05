"""The hub's own log: a daily file, 14 days kept, and the "Send logs" zip.

* `DailyFileHandler` writes `logs/hub-<date>.log` and moves to a new file at
  midnight (a hub left running overnight used to keep writing to the day it
  started). Files older than KEEP_DAYS are deleted when a new day starts.
* `BusForwarder` puts the group conversation's warnings and errors on the
  event bus (source "group"), so they reach the Logs drawer, not only the file.
* `make_report()` zips today's hub log and group logs, with every key blanked,
  into the user's Downloads folder (POST /api/log/report).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import re
import time
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import keyscrub

KEEP_DAYS = 14
LOG_FORMAT = "%(asctime)s  %(levelname)-7s %(name)-18s %(message)s"
_HUB_LOG = re.compile(r"^hub-(\d{4}-\d{2}-\d{2})\.log$")
_GROUP_LOG = re.compile(r"^group-(\d{8})-\d{6}\.jsonl$")


def hub_log_name(day: Optional[_dt.date] = None) -> str:
    return "hub-{}.log".format((day or _dt.date.today()).isoformat())


class DailyFileHandler(logging.Handler):
    """logs/hub-YYYY-MM-DD.log, switching files when the date changes."""

    def __init__(self, log_dir: Path, keep_days: int = KEEP_DAYS,
                 today: Callable[[], _dt.date] = _dt.date.today) -> None:
        super().__init__()
        self.log_dir = Path(log_dir)
        self.keep_days = keep_days
        self._today = today
        self._day: Optional[_dt.date] = None
        self._stream: Any = None
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._open()

    @property
    def baseFilename(self) -> str:   # same name as logging.FileHandler's
        return str(self.log_dir / hub_log_name(self._day))

    def _open(self) -> None:
        day = self._today()
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
        self._day = day
        self._stream = open(self.log_dir / hub_log_name(day), "a", encoding="utf-8")
        prune(self.log_dir, self.keep_days, day)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.acquire()
            try:
                # Reopened after a close too, like logging.FileHandler: uvicorn's
                # dictConfig closes every existing handler at start-up but
                # leaves it on the root logger.
                if self._stream is None or self._today() != self._day:
                    self._open()
                self._stream.write(msg + "\n")
                self._stream.flush()
            finally:
                self.release()
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def close(self) -> None:
        self.acquire()
        try:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
        finally:
            self.release()
        super().close()


def prune(log_dir: Path, keep_days: int = KEEP_DAYS,
          today: Optional[_dt.date] = None) -> list[Path]:
    """Delete hub logs older than `keep_days`. Returns what was removed."""
    cutoff = (today or _dt.date.today()) - _dt.timedelta(days=keep_days)
    removed: list[Path] = []
    try:
        entries = list(Path(log_dir).iterdir())
    except OSError:
        return removed
    for path in entries:
        m = _HUB_LOG.match(path.name)
        if not m:
            continue
        try:
            day = _dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if day < cutoff:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


def install_file_log(log_dir: Path) -> Optional[DailyFileHandler]:
    """Send the root logger to the daily file. None when it cannot be opened."""
    try:
        handler = DailyFileHandler(log_dir)
    except OSError as exc:
        logging.getLogger("hub.main").warning("could not open the hub's log file: %s", exc)
        return None
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
    logging.getLogger().addHandler(handler)
    return handler


# ----------------------------------------------------------- bus forwarding
class BusForwarder(logging.Handler):
    """Warnings and errors from one logger tree -> the event bus.

    Group code logs from worker threads too (the ears), and the bus's queues
    are not thread-safe, so off-loop records are handed over with
    call_soon_threadsafe. Keys are blanked first.
    """

    def __init__(self, bus: Any, source: str, loop: asyncio.AbstractEventLoop,
                 level: int = logging.WARNING) -> None:
        super().__init__(level)
        self.bus = bus
        self.source = source
        self.loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = keyscrub.scrub_text(record.getMessage())
            level = "error" if record.levelno >= logging.ERROR else "warn"
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is self.loop:
                self.bus.add_log(level, text, source=self.source)
            elif not self.loop.is_closed():
                self.loop.call_soon_threadsafe(
                    lambda: self.bus.add_log(level, text, source=self.source))
        except Exception:  # noqa: BLE001
            self.handleError(record)


def forward_to_bus(bus: Any, logger_name: str, source: str,
                   loop: Optional[asyncio.AbstractEventLoop] = None) -> BusForwarder:
    handler = BusForwarder(bus, source, loop or asyncio.get_running_loop())
    logging.getLogger(logger_name).addHandler(handler)
    return handler


# ----------------------------------------------------------------- report
def downloads_dir() -> Path:
    """The user's Downloads folder (the Windows known folder when it can be
    read: it may have been moved), else ~/Downloads."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            from uuid import UUID

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

            u = UUID("374DE290-123F-4565-9164-39C4925E467B")   # FOLDERID_Downloads
            guid = GUID(u.fields[0], u.fields[1], u.fields[2],
                        (ctypes.c_ubyte * 8).from_buffer_copy(u.bytes[8:]))
            out = ctypes.c_wchar_p()
            shell32 = ctypes.windll.shell32
            if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None,
                                            ctypes.byref(out)) == 0:
                path = Path(out.value)
                ctypes.windll.ole32.CoTaskMemFree(out)
                if path.is_dir():
                    return path
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / "Downloads"


def todays_logs(log_dir: Path, day: Optional[_dt.date] = None) -> list[Path]:
    """Today's hub log and every group log started today."""
    day = day or _dt.date.today()
    found: list[Path] = []
    hub_log = Path(log_dir) / hub_log_name(day)
    if hub_log.is_file():
        found.append(hub_log)
    stamp = day.strftime("%Y%m%d")
    try:
        for path in sorted(Path(log_dir).glob("group-*.jsonl")):
            m = _GROUP_LOG.match(path.name)
            if m and m.group(1) == stamp:
                found.append(path)
    except OSError:
        pass
    return found


def make_report(log_dir: Path, out_dir: Path, secrets: Iterable[str] = (),
                extra: Optional[dict[str, str]] = None,
                day: Optional[_dt.date] = None) -> Path:
    """Zip today's logs, keys blanked, into `out_dir`. `extra` adds text files
    (name -> content), scrubbed the same way. Returns the zip's path."""
    secret_bytes = keyscrub.known_secrets(secrets)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "robot-hub-logs-{}.zip".format(time.strftime("%Y-%m-%d-%H%M%S"))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in todays_logs(log_dir, day):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            zf.writestr(path.name, keyscrub.scrub_text(text, secret_bytes))
        for name, content in (extra or {}).items():
            zf.writestr(name, keyscrub.scrub_text(content, secret_bytes))
    return target

