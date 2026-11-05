"""The student's settings, kept in <data>/settings.json.

What a student changes in the app (and what the app learns, such as the WiFi
the robots were last seen on) must survive a restart and an update, so it
lives in the data folder, not in config.toml (which the student never edits).

    {"auto_connect": false, "staff_tools": false, "save_transcripts": true,
     "setup_seen": false, "lab_wifi": {"name": "HOT-WiFi", "open": true},
     "passwords": {"furhat": "..."},
     "robots_network": {"ssid": "HOT-WiFi", "last_seen": 1730800000.0},
     "woz_quick": ["Sorry, can you say that again?", "...", "..."]}

A key missing from the file falls back to the config (auto_connect, lab_wifi)
or to the default below. Passwords never go back out: the page only learns
whether one is set and whether the last login with it worked.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("hub.settings")

SETTINGS_FILE = "settings.json"
TRANSCRIPTS_DIR = "transcripts"

# Robots whose password the student can set (PUT /api/settings/password/{robot}).
PASSWORD_ROBOTS = ("furhat",)
DEFAULT_PASSWORDS = {"furhat": "admin"}       # Furhat's published default
PASSWORD_ENV = {"furhat": "FURHAT_PASSWORD"}  # a lab checkout's .env wins

BOOL_FIELDS = ("auto_connect", "staff_tools", "save_transcripts", "setup_seen")
# The Reachy app's Wizard of Oz quick saves: the lines on S, D and F, which the
# operator can rewrite. Always three; an empty one is a key that says nothing.
WOZ_QUICK_KEYS = ("s", "d", "f")
WOZ_QUICK_MAX = 600          # reachy_chat refuses a typed line over 600 characters
DEFAULT_WOZ_QUICK = ["Sorry, can you say that again?",
                     "Let me think about that for a second.",
                     "That is a great question!"]
DEFAULTS: dict[str, Any] = {"staff_tools": False, "save_transcripts": True,
                            "setup_seen": False, "woz_quick": DEFAULT_WOZ_QUICK}


class SettingsError(ValueError):
    """A change the store refuses; `code` is the friendly-error code."""

    def __init__(self, message: str, code: str = "BAD_SETTING") -> None:
        super().__init__(message)
        self.code = code


class SettingsStore:
    def __init__(self, path: Path, config: Any = None) -> None:
        self.path = Path(path)
        self.config = config
        self._data: dict[str, Any] = {}
        # Last login result per robot type: True / False / None (not tried).
        self._works: dict[str, Optional[bool]] = {}
        # A fresh data folder: no settings were ever saved here.
        self.first_run = not self.path.exists()
        self._load()
        self.apply_to_config()

    # ------------------------------------------------------------ storage
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read %s (%s); starting from the defaults",
                        self.path.name, exc)
            return
        if isinstance(data, dict):
            self._data = data

    def save(self) -> None:
        """Atomic: a crash mid-write never leaves half a file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".settings-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------- values
    def get(self, name: str) -> Any:
        if name in self._data:
            return self._data[name]
        if name == "auto_connect":
            return bool(getattr(self.config, "auto_connect", False))
        if name == "lab_wifi":
            net = getattr(self.config, "network", None)
            return {"name": getattr(net, "lab_wifi", "") or "",
                    "open": bool(getattr(net, "lab_wifi_open", False))}
        if name == "robots_network":
            return {"ssid": "", "last_seen": None}
        return DEFAULTS.get(name)

    def apply_to_config(self) -> None:
        """Stored values the rest of the hub reads from the config object."""
        cfg = self.config
        if cfg is None:
            return
        if "auto_connect" in self._data:
            cfg.auto_connect = bool(self._data["auto_connect"])
        wifi = self._data.get("lab_wifi")
        if isinstance(wifi, dict):
            cfg.network.lab_wifi = str(wifi.get("name") or "")
            cfg.network.lab_wifi_open = bool(wifi.get("open"))

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {name: bool(self.get(name)) for name in BOOL_FIELDS}
        out["lab_wifi"] = dict(self.get("lab_wifi"))
        out["passwords"] = {robot: {"set": self.password_is_set(robot),
                                    "works": self._works.get(robot)}
                            for robot in PASSWORD_ROBOTS}
        out["robots_network"] = dict(self.get("robots_network"))
        out["woz_quick"] = list(self.get("woz_quick"))
        return out

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply any subset of the public fields; returns the full object."""
        clean: dict[str, Any] = {}
        for name, value in (changes or {}).items():
            if name in BOOL_FIELDS:
                if not isinstance(value, bool):
                    raise SettingsError("{} must be true or false".format(name))
                clean[name] = value
            elif name == "lab_wifi":
                if not isinstance(value, dict):
                    raise SettingsError("lab_wifi must be {name, open}")
                current = dict(self.get("lab_wifi"))
                if "name" in value:
                    if not isinstance(value["name"], str):
                        raise SettingsError("lab_wifi.name must be text")
                    current["name"] = value["name"].strip()
                if "open" in value:
                    if not isinstance(value["open"], bool):
                        raise SettingsError("lab_wifi.open must be true or false")
                    current["open"] = value["open"]
                clean[name] = current
            elif name == "woz_quick":
                clean[name] = _woz_quick(value)
            else:
                raise SettingsError("there is no setting called {}".format(name))
        self._data.update(clean)
        if clean:
            self.save()
            self.apply_to_config()
        return self.public()

    # ---------------------------------------------------------- passwords
    def _config_password(self, robot: str) -> str:
        cfg = self.config
        if cfg is None:
            return ""
        return str(cfg.robot(robot).settings.get("password") or "")

    def password(self, robot: str) -> str:
        """The password the hub logs in with: the lab's .env first, then the
        one saved in Settings, then config, then the maker's default."""
        env = PASSWORD_ENV.get(robot)
        if env and os.environ.get(env):
            return os.environ[env]
        stored = (self._data.get("passwords") or {}).get(robot)
        if stored:
            return str(stored)
        return self._config_password(robot) or DEFAULT_PASSWORDS.get(robot, "")

    def password_is_set(self, robot: str) -> bool:
        return bool(self.password(robot))

    def set_password(self, robot: str, password: str) -> dict[str, Any]:
        if robot not in PASSWORD_ROBOTS:
            raise SettingsError("{} has no password to set".format(robot), "UNKNOWN_ROBOT")
        if not isinstance(password, str):
            raise SettingsError("the password must be text")
        passwords = dict(self._data.get("passwords") or {})
        if password.strip():
            passwords[robot] = password.strip()
        else:
            passwords.pop(robot, None)      # blank: back to the default
        self._data["passwords"] = passwords
        self._works[robot] = None
        self.save()
        return self.public()

    def note_login(self, robot: str, works: bool) -> None:
        """A robot adapter reports whether the password just worked."""
        self._works[robot] = bool(works)

    # ------------------------------------------------------ robots network
    def note_robots_network(self, ssid: str, when: Optional[float] = None) -> None:
        """Remember the WiFi a robot was last seen on, so a wrong-network
        warning works from a cold start. Saved at most once a minute."""
        ssid = (ssid or "").strip()
        if not ssid:
            return
        now = time.time() if when is None else when
        old = self._data.get("robots_network") or {}
        if old.get("ssid") == ssid and now - float(old.get("last_seen") or 0) < 60:
            return
        self._data["robots_network"] = {"ssid": ssid, "last_seen": now}
        try:
            self.save()
        except OSError as exc:
            log.warning("could not save %s: %s", self.path.name, exc)

    # --------------------------------------------------------- transcripts
    def transcripts_dir(self) -> Path:
        return self.path.parent / TRANSCRIPTS_DIR


def _woz_quick(value: Any) -> list[str]:
    """Three quick-save lines (S, D, F), each up to WOZ_QUICK_MAX characters."""
    if (not isinstance(value, list) or len(value) != len(WOZ_QUICK_KEYS)
            or not all(isinstance(v, str) for v in value)):
        raise SettingsError("woz_quick must be three lines of text")
    lines = [" ".join(v.split()) for v in value]
    for key, line in zip(WOZ_QUICK_KEYS, lines):
        if len(line) > WOZ_QUICK_MAX:
            raise SettingsError("the {} line is {} characters; the limit is {}".format(
                key.upper(), len(line), WOZ_QUICK_MAX))
    return lines


_CURRENT: Optional[SettingsStore] = None


def open_store(data_dir: Path, config: Any = None) -> SettingsStore:
    """The hub's store; adapters reach it through current()."""
    global _CURRENT
    _CURRENT = SettingsStore(Path(data_dir) / SETTINGS_FILE, config)
    return _CURRENT


def current() -> Optional[SettingsStore]:
    return _CURRENT


def robot_password(robot: str, config: Any = None) -> str:
    """For adapters: the hub's store when there is one, else the same order
    without a saved password (env, config, default)."""
    if _CURRENT is not None:
        return _CURRENT.password(robot)
    env = PASSWORD_ENV.get(robot)
    if env and os.environ.get(env):
        return os.environ[env]
    if config is not None:
        value = config.robot(robot).settings.get("password")
        if value:
            return str(value)
    return DEFAULT_PASSWORDS.get(robot, "")


def note_login(robot: str, works: bool) -> None:
    if _CURRENT is not None:
        _CURRENT.note_login(robot, works)
