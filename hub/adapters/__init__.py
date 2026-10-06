"""Adapter lookup.

Imports are lazy and individually guarded: a missing SDK disables exactly one
card and leaves the hub running (PLAN.md 13.6).
"""

from __future__ import annotations

import logging
from typing import Optional, Type

from .base import (AdapterUnavailable, Claim, Found, Health, PostureRefused,
                   RobotAdapter)

log = logging.getLogger("hub.adapters")

_MODULES = {
    "furhat": ("furhat", "FurhatAdapter"),
    "reachy_wireless": ("reachy_wireless", "ReachyWirelessAdapter"),
    "reachy_lite": ("reachy_lite", "ReachyLiteAdapter"),
    "naoqi": ("naoqi", "NaoqiAdapter"),
    "pepper": ("naoqi", "PepperAdapter"),
}

# The four cards the page renders even when nothing is powered on (10, Phase 0).
KNOWN_TYPES = ("furhat", "reachy_wireless", "reachy_lite", "naoqi", "pepper")

DISPLAY_NAMES = {
    "furhat": "Furhat",
    "reachy_wireless": "Reachy-Mini",
    "reachy_lite": "Reachy-Mini-Lite",
    "naoqi": "NAOqi",
    "pepper": "Pepper",
}

_cache: dict[str, Optional[Type[RobotAdapter]]] = {}


def get_adapter_class(type_id: str) -> Optional[Type[RobotAdapter]]:
    if type_id in _cache:
        return _cache[type_id]
    entry = _MODULES.get(type_id)
    cls: Optional[Type[RobotAdapter]] = None
    if entry:
        module_name, class_name = entry
        try:
            mod = __import__(f"hub.adapters.{module_name}", fromlist=[class_name])
            cls = getattr(mod, class_name)
        except Exception as exc:                     # noqa: BLE001
            log.warning("adapter %s unavailable: %s", type_id, exc)
    _cache[type_id] = cls
    return cls


__all__ = [
    "AdapterUnavailable", "Claim", "Found", "Health", "PostureRefused", "RobotAdapter",
    "get_adapter_class", "KNOWN_TYPES", "DISPLAY_NAMES",
]
