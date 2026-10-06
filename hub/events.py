"""Internal pub/sub bus + the event log.

One producer set (detectors, probe loops, supervisor), two consumers: the
WebSocket fan-out and the in-memory log the UI scrolls. Publishing never
awaits a slow subscriber -- a stalled browser cannot stall a robot (2.4).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Iterable

log = logging.getLogger("hub.events")

LogLevel = str  # "info" | "warn" | "error" | "ok"


class EventBus:
    def __init__(self, log_size: int = 500) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._log: deque[dict[str, Any]] = deque(maxlen=log_size)
        self._seq = 0

    # -- subscription -------------------------------------------------
    def subscribe(self, maxsize: int = 256) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    # -- publishing ---------------------------------------------------
    def publish(self, event: dict[str, Any]) -> None:
        """Fire-and-forget. Drops for one slow subscriber, never for all."""
        self._seq += 1
        event.setdefault("ts", time.time())
        event["seq"] = self._seq
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("dropping event for a subscriber that fell behind")

    def emit_log(self, level: LogLevel, text: str, **extra: Any) -> None:
        """Every failure gets a human sentence, not just a colour (13.5)."""
        event = {"type": "log", "level": level, "text": text, **extra}
        self._log.append(event)
        getattr(log, "warning" if level == "warn" else
                ("error" if level == "error" else "info"))(text)
        self.publish(event)

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        items = list(self._log)
        return items[-limit:]


class _NullBus(EventBus):
    """For unit tests and adapters constructed outside the app."""

    def publish(self, event: dict[str, Any]) -> None:  # pragma: no cover
        pass


def coalesce(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the newest `robot` event per key -- used when a client
    reconnects and we replay state rather than history."""
    seen: dict[str, dict[str, Any]] = {}
    other: list[dict[str, Any]] = []
    for e in events:
        if e.get("type") == "robot" and e.get("key"):
            seen[e["key"]] = e
        else:
            other.append(e)
    return other + list(seen.values())
