"""Port allocator.

Hands out 9100-9199 for anything the hub starts. The avoid list in config is
measured on a real laptop (PLAN.md 7.1), but it is only a hint -- every
candidate is bind-tested, because another machine reserves different ports.

`reachy_chat` honours `--port` (verified 2026-09-14), so the hub allocates
rather than assuming 8765.
"""

from __future__ import annotations

import socket
from typing import Optional

from .config import Config


def is_free(port: int, host: str = "127.0.0.1") -> bool:
    """A real bind, not a connect. A connect-based probe is worthless on this
    laptop: the Check Point VPN adapter makes port-80 connects succeed for
    hosts that do not exist (2.9)."""
    for family, addr in ((socket.AF_INET, (host, port)), (socket.AF_INET, ("0.0.0.0", port))):
        s = socket.socket(family, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            s.bind(addr)
        except OSError:
            return False
        finally:
            s.close()
    return True


class PortAllocator:
    def __init__(self, config: Config) -> None:
        self.cfg = config.ports
        self._held: dict[int, str] = {}   # port -> owner key

    def allocate(self, owner: str, preferred: Optional[int] = None) -> int:
        candidates = []
        if preferred:
            candidates.append(preferred)
        candidates += list(range(self.cfg.range_start, self.cfg.range_end + 1))
        for port in candidates:
            if port in self.cfg.avoid or port in self._held:
                continue
            if is_free(port):
                self._held[port] = owner
                return port
        raise RuntimeError(
            "no free port in {}-{} (avoiding {})".format(
                self.cfg.range_start, self.cfg.range_end, len(self.cfg.avoid)))

    def release(self, port: int) -> None:
        self._held.pop(port, None)

    def release_owner(self, owner: str) -> None:
        for port in [p for p, o in self._held.items() if o == owner]:
            self._held.pop(port, None)

    def held(self) -> dict[int, str]:
        return dict(self._held)
