"""config.toml + .env -> one typed object.

No lab values live in code (12). Everything site-specific -- paths, keys,
the announcement sentences -- arrives through here, and every robot section
is optional: a robot you do not own must cost nothing (13.6).
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
DEFAULT_ANNOUNCE = "I am {name}, I am connected and ready to run."


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8099            # outside every reserved range in 7.1


class DiscoveryCfg(BaseModel):
    mdns: bool = True
    usb: bool = True
    netscan: bool = True
    # netscan refuses anything larger than /24 unless widened here (6)
    netscan_max_hosts: int = 256
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
    ports: PortsCfg = Field(default_factory=PortsCfg)
    auto_connect: bool = False
    robots: dict[str, RobotCfg] = Field(default_factory=dict)
    repo_root: Path = REPO_ROOT

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


def load_config(path: Optional[Path] = None) -> Config:
    _load_env(REPO_ROOT / ".env")
    path = path or REPO_ROOT / "config.toml"
    if not path.exists():
        path = REPO_ROOT / "config.example.toml"
    data: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    robots = {k: RobotCfg(**v) if isinstance(v, dict) else RobotCfg()
              for k, v in (data.pop("robots", {}) or {}).items()}
    return Config(robots=robots, **data)
