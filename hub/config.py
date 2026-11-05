"""config.toml + .env -> one typed object.

No lab values live in code (12). Everything site-specific -- paths, keys,
the announcement sentences -- arrives through here, and every robot section
is optional: a robot you do not own must cost nothing (13.6).

App and data are separate (STUDENT-APP-PLAN 2.1). `ROBOT_HUB_DATA` names the
folder every writable file lives in (logs, keys, settings, caches, pepper
data, transcripts); when it is unset that folder is the repo root, so a lab
checkout keeps working exactly as before.

Config is layered, each layer overriding the one before it:

  1. `defaults.toml` (shipped with the app; the student defaults)
  2. lab checkout only (ROBOT_HUB_DATA unset): `config.toml` in the repo
     root, or `config.example.toml` when there is none
  3. `<ROBOT_HUB_DATA>/config.toml`: the student's own overrides
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    raise SystemExit("Robot Hub needs Python 3.11+")

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULTS_FILE = REPO_ROOT / "defaults.toml"
DATA_ENV = "ROBOT_HUB_DATA"
DEFAULT_ANNOUNCE = "I am {name}, I am connected and ready to run."


def custom_data_dir() -> Optional[Path]:
    """The folder ROBOT_HUB_DATA names, or None in a lab checkout."""
    raw = os.environ.get(DATA_ENV, "").strip().strip('"')
    if not raw:
        return None
    return Path(os.path.expandvars(raw)).expanduser().resolve()


def data_dir() -> Path:
    """Where every writable file goes: ROBOT_HUB_DATA, else the repo root."""
    return custom_data_dir() or REPO_ROOT


# Read once at import: the launcher sets the variable before Python starts.
# Module-level paths elsewhere (logs, group.local.json, caches) build on it.
DATA_DIR = data_dir()

# The NAO/Pepper kit lives on a short ASCII path: Python 2.7 breaks on a
# user folder with Hebrew in it (STUDENT-APP-PLAN 4.3).
NAOQI_KIT_DIRS = (Path("C:/LabaLab/naoqi-sdk"),)


def naoqi_kit_dirs() -> list[Path]:
    dirs = list(NAOQI_KIT_DIRS)
    public = os.environ.get("PUBLIC")
    if public:
        dirs.append(Path(public) / "LabaLab" / "naoqi-sdk")
    return dirs


def _sdk_root(base: Path) -> Optional[Path]:
    """The folder holding lib/ and bin/: the kit itself, or one or two levels
    down (the official zip doubles its top folder)."""
    level = [base]
    for _ in range(3):
        nxt: list[Path] = []
        for p in level:
            if (p / "lib").is_dir() and (p / "bin").is_dir():
                return p
            try:
                nxt += sorted(c for c in p.iterdir() if c.is_dir())
            except OSError:
                continue
        level = nxt
    return None


def find_naoqi_kit(bases: Optional[list[Path]] = None) -> dict[str, Path]:
    """{"pynaoqi_sdk": ..., "python2": ...} for the installed kit, or {}.

    The kit ships its own 64-bit Python 2.7 as bin/python.exe, so a found kit
    supplies both settings; run it with PYTHONHOME=<sdk>/lib/python2.7.
    """
    for base in bases if bases is not None else naoqi_kit_dirs():
        if not base.is_dir():
            continue
        sdk = _sdk_root(base)
        if sdk is None:
            continue
        found = {"pynaoqi_sdk": sdk}
        exe = "python.exe" if sys.platform == "win32" else "python"
        if (sdk / "bin" / exe).is_file():
            found["python2"] = sdk / "bin" / exe
        return found
    return {}


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8099            # outside every reserved range in 7.1


class NetworkCfg(BaseModel):
    # The lab's own WiFi: every Reachy's fallback, and where a
    # lab member hands a robot their hotspot (hub/reachy_wifi.py). Its name
    # lives here, in the git-ignored config.toml, not in the public repo.
    lab_wifi: str = ""
    # true when the lab WiFi has no password (2026-11-03): robots
    # save it as an open network and LAB_WIFI_PASSWORD is not needed.
    lab_wifi_open: bool = False
    # The hotspot every new robot is set up on (tools/reachy_bringup.py);
    # its password is HOTSPOT_PASSWORD in .env.
    hotspot: str = ""


class DiscoveryCfg(BaseModel):
    mdns: bool = True
    usb: bool = True
    netscan: bool = True
    # netscan refuses anything larger than /24 unless widened here (6)
    netscan_max_hosts: int = 256
    # on a network bigger than that: this laptop's /24 plus this many /24s on
    # each side (DHCP on a big lab WiFi spreads robots over neighbouring /24s)
    netscan_nearby_24s: int = 4
    netscan_interval_s: float = 5.0
    selfnet_interval_s: float = 3.0
    lost_after_s: float = 12.0
    # robot subnet the laptop is expected to be on; blank = infer (2.8)
    expected_subnet: str = ""


class PortsCfg(BaseModel):
    range_start: int = 9100
    range_end: int = 9199
    # measured on this laptop; the allocator bind-tests anyway (7.1)
    avoid: list[int] = Field(default_factory=lambda: [
        5040, 5357, 7680, 7778,          # Windows services
        7447, 8000, 8042, 8443,          # Reachy Mini Control desktop app
        8765, 8770,                      # reachy_chat dashboard / launcher
        8080,                            # Furhat SDK (virtual Furhat)
    ])


class UnitCfg(BaseModel):
    """One physical robot, keyed by its stable id (HUB-INTERFACE.md 2)."""
    display_name: str = ""


class RobotCfg(BaseModel):
    enabled: bool = True
    display_name: str = ""
    announce: str = ""
    # per-robot free-form settings; each adapter documents its own keys
    settings: dict[str, Any] = Field(default_factory=dict)
    # per-unit overrides keyed by unit_id; a name is assigned once, then permanent
    units: dict[str, UnitCfg] = Field(default_factory=dict)

    def name_for(self, key: str, fallback: str) -> str:
        unit = self.units.get(key)
        return (unit.display_name if unit else "") or self.display_name or fallback

    def announcement(self, name: str) -> str:
        return (self.announce or DEFAULT_ANNOUNCE).format(name=name)


class Config(BaseModel):
    server: ServerCfg = Field(default_factory=ServerCfg)
    discovery: DiscoveryCfg = Field(default_factory=DiscoveryCfg)
    network: NetworkCfg = Field(default_factory=NetworkCfg)
    ports: PortsCfg = Field(default_factory=PortsCfg)
    auto_connect: bool = False
    robots: dict[str, RobotCfg] = Field(default_factory=dict)
    repo_root: Path = REPO_ROOT
    # Every writable file lives under here (ROBOT_HUB_DATA, else repo_root).
    data_dir: Path = Field(default_factory=data_dir)
    # The files this config was built from, in load order (for the log).
    layers: list[str] = Field(default_factory=list)

    def robot(self, type_id: str) -> RobotCfg:
        return self.robots.get(type_id, RobotCfg())

    def secret(self, key: str, default: str = "") -> str:
        """Secrets come from the environment only, never config.toml (12)."""
        return os.environ.get(key, default)

    def path(self, type_id: str, key: str) -> Optional[Path]:
        raw = self.robot(type_id).settings.get(key)
        if not raw:
            return None
        p = Path(os.path.expandvars(str(raw))).expanduser()
        return p if p.is_absolute() else (self.repo_root / p).resolve()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """`over` on top of `base`, tables merged key by key (a copy)."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def config_layers(path: Optional[Path] = None,
                  defaults: Optional[Path] = None,
                  data: Optional[Path] = None) -> list[Path]:
    """The files load_config reads, lowest first (see the module docstring)."""
    layers: list[Path] = []
    defaults = DEFAULTS_FILE if defaults is None else defaults
    if defaults.is_file():
        layers.append(defaults)
    custom = data if data is not None else custom_data_dir()
    if path is not None or custom is None:
        lab = path or REPO_ROOT / "config.toml"
        if not lab.exists():
            lab = REPO_ROOT / "config.example.toml"
        if lab.is_file():
            layers.append(lab)
    if custom is not None and (custom / "config.toml").is_file():
        layers.append(custom / "config.toml")
    return layers


def load_config(path: Optional[Path] = None, *,
                defaults: Optional[Path] = None,
                data: Optional[Path] = None) -> Config:
    """`path` is a lab config file to use instead of config.toml; `defaults`
    and `data` stand in for defaults.toml and ROBOT_HUB_DATA (tests)."""
    _load_env(REPO_ROOT / ".env")
    merged: dict[str, Any] = {}
    layers = config_layers(path, defaults, data)
    for layer in layers:
        merged = merge(merged, _read_toml(layer))
    robots = {k: RobotCfg(**v) if isinstance(v, dict) else RobotCfg()
              for k, v in (merged.pop("robots", {}) or {}).items()}
    for key in ("repo_root", "data_dir", "layers"):
        merged.pop(key, None)       # never taken from a file
    data_root = data if data is not None else data_dir()
    return Config(robots=robots, data_dir=data_root,
                  layers=[str(p) for p in layers], **merged)
