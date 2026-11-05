"""Windowless child processes, and which Python the hub's own helpers run on.

The student app runs the hub under `pythonw` with no console. A child started
without CREATE_NO_WINDOW then gets a console of its own: the netscan sweep
pings hundreds of hosts every few seconds, so without this flag a student's
screen would flash ping windows all day (STUDENT-APP-PLAN 2.3).

Every `subprocess` / `asyncio.create_subprocess_exec` call in the hub passes
`**no_window()` (or ORs `NO_WINDOW` into its own creationflags).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"
NO_WINDOW: int = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WINDOWS else 0


def no_window(extra: int = 0) -> dict[str, Any]:
    """Keyword arguments that keep a child from opening a console window.

    `extra` is ORed in (e.g. CREATE_NEW_PROCESS_GROUP). Empty off Windows.
    """
    if not IS_WINDOWS:
        return {}
    return {"creationflags": NO_WINDOW | extra}


def hub_python() -> Path:
    """The interpreter for Python children the hub starts with its own runtime
    (pepper_app, the Reachy deploy helper).

    Under the student app the hub itself is `pythonw.exe`. Its children read
    and write pipes, so they get the console build next to it, `python.exe`;
    CREATE_NO_WINDOW keeps that from showing a window.
    """
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        console = exe.with_name("python.exe")
        if console.is_file():
            return console
    return exe
