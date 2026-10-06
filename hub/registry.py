"""The card store. One RobotState per discovered robot, keyed by stable id.

Keyed by stable_key -- never an IP (2.2). A card outlives the robot's
address; when Reachy and Furhat swapped 172.20.10.10 inside an hour, this
is what kept their data apart.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .events import EventBus

# Card state machine (5.2). DEGRADED is amber and honest; green would lie.
ABSENT = "ABSENT"
DETECTED = "DETECTED"
CONNECTING = "CONNECTING"
CONNECTED = "CONNECTED"
RUNNING = "RUNNING"
DEGRADED = "DEGRADED"
ERROR = "ERROR"
DISABLED = "DISABLED"   # robot present but a local prerequisite is missing

STATES = (ABSENT, DETECTED, CONNECTING, CONNECTED, RUNNING, DEGRADED, ERROR, DISABLED)


@dataclass
class RobotState:
    key: str
    type_id: str
    name: str
    state: str = ABSENT
    address: Optional[str] = None
    battery: Optional[int] = None
    detail: str = ""
    mic: Optional[str] = None
    system_url: Optional[str] = None
    daemon_version: Optional[str] = None   # recorded on every connect (12)
    can_speak: bool = True                 # false => "connected, but silent"
    disabled_reason: Optional[str] = None
    # A launch can take two minutes. Kept on the card, not in the page, so a
    # refreshed page still shows the spinner -- and why the last one failed.
    launching_since: Optional[float] = None
    launch_error: Optional[str] = None
    # Operator posture buttons (NAO only): the posture in flight, and the
    # last outcome as a sentence -- on the card, so every open page agrees.
    posture_pending: Optional[str] = None
    posture_note: Optional[str] = None
    posture_failed: bool = False
    last_seen: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_event(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("meta", None)
        d["type"] = "robot"
        return d


class Registry:
    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._robots: dict[str, RobotState] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._robots

    def get(self, key: str) -> Optional[RobotState]:
        return self._robots.get(key)

    def all(self) -> list[RobotState]:
        return list(self._robots.values())

    def upsert(self, key: str, **fields: Any) -> RobotState:
        r = self._robots.get(key)
        if r is None:
            r = RobotState(key=key,
                           type_id=fields.pop("type_id", "unknown"),
                           name=fields.pop("name", key))
            self._robots[key] = r
        changed = False
        for k, v in fields.items():
            if hasattr(r, k) and getattr(r, k) != v:
                setattr(r, k, v)
                changed = True
        r.last_seen = time.time()
        if changed:
            self.bus.publish(r.to_event())
        return r

    def set_state(self, key: str, state: str, detail: str = "") -> Optional[RobotState]:
        assert state in STATES, state
        r = self._robots.get(key)
        if r is None:
            return None
        if r.state != state or (detail and detail != r.detail):
            r.state = state
            if detail:
                r.detail = detail
            self.bus.publish(r.to_event())
        return r

    def remove(self, key: str) -> None:
        if self._robots.pop(key, None) is not None:
            self.bus.publish({"type": "robot_removed", "key": key})

    def broadcast_all(self) -> None:
        for r in self._robots.values():
            self.bus.publish(r.to_event())
