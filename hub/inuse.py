"""Which laptop is using a robot: a marker file on the robot itself
(STUDENT-APP-PLAN 4.2, "In use by another laptop").

The hub that launches a robot's app writes `MARKER` on the robot with this
laptop's name; Disconnect removes it (only when it is still ours). Connect
and Launch read it: a name that is not this laptop's means another student
is using the robot, and Launch says so instead of killing their app.

The marker lives in /tmp, so a reboot clears it. A marker older than
`STALE_S`, or (Reachy) one whose app is no longer running, is ignored. Any
SSH failure is silent: no marker is better than a false "in use".
"""

from __future__ import annotations

import shlex
import socket
import time
from typing import Any, Optional

MARKER = "/tmp/labalab-hub-in-use"
STALE_S = 12 * 3600.0
SSH_TIMEOUT_S = 8.0
RUNNING_WORD = "APP-RUNNING"


def this_laptop() -> str:
    name = socket.gethostname() or "a laptop"
    return "".join(ch for ch in name if ch.isalnum() or ch in "-_.")[:63] or "a laptop"


def write_command(laptop: str, now: Optional[float] = None) -> str:
    stamp = int(time.time() if now is None else now)
    return "printf '%s %s\\n' {} {} > {}".format(shlex.quote(laptop), stamp, MARKER)


def read_command(app_running: Optional[str] = None) -> str:
    cmd = "cat {} 2>/dev/null; echo".format(MARKER)
    if app_running:
        cmd += "; {} >/dev/null 2>&1 && echo {}".format(app_running, RUNNING_WORD)
    return cmd


def clear_command(laptop: str) -> str:
    # Only our own marker: another laptop may have launched it since.
    return ("[ \"$(cut -d' ' -f1 {m} 2>/dev/null)\" = {h} ] && rm -f {m}; true"
            .format(m=MARKER, h=shlex.quote(laptop)))


def parse(output: str, laptop: str, app_running_checked: bool = False,
          now: Optional[float] = None) -> Optional[str]:
    """The other laptop's name, or None (free, ours, stale, or app stopped)."""
    lines = [line.strip() for line in (output or "").splitlines() if line.strip()]
    if not lines or lines[0] == RUNNING_WORD:
        return None
    parts = lines[0].split()
    holder = parts[0]
    try:
        stamp = float(parts[1]) if len(parts) > 1 else 0.0
    except ValueError:
        stamp = 0.0
    now = time.time() if now is None else now
    if holder == laptop or (stamp and now - stamp > STALE_S):
        return None
    if app_running_checked and RUNNING_WORD not in lines:
        return None
    return holder


async def read(adapter: Any, laptop: Optional[str] = None) -> Optional[str]:
    shell = getattr(adapter, "remote_shell", None)
    if shell is None:
        return None
    laptop = laptop or this_laptop()
    running = getattr(adapter, "app_running_command", None)
    try:
        _rc, out = await shell(read_command(running), SSH_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return None
    return parse(out, laptop, app_running_checked=bool(running))


async def write(adapter: Any, laptop: Optional[str] = None) -> bool:
    shell = getattr(adapter, "remote_shell", None)
    if shell is None:
        return False
    try:
        rc, _out = await shell(write_command(laptop or this_laptop()), SSH_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return False
    return rc == 0


async def clear(adapter: Any, laptop: Optional[str] = None) -> bool:
    shell = getattr(adapter, "remote_shell", None)
    if shell is None:
        return False
    try:
        rc, _out = await shell(clear_command(laptop or this_laptop()), SSH_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        return False
    return rc == 0
