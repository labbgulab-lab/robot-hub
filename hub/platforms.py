"""What this laptop's operating system can do: Windows, macOS, or Linux.

The student app runs on Windows and on macOS (Apple Silicon and Intel). Two
things stay Windows-only:

  * NAO and Pepper: their NAOqi kit (pynaoqi with its own Python 2.7) is the
    maker's Windows build. On a Mac their cards say so instead of offering a
    download that cannot work.
  * The USB Reachy Mini Lite: its detector is WMI on Windows and pyudev on
    Linux; a Mac has neither.

Everything reads `sys.platform` when called, never at import, so a test can
set it to "darwin" on a Windows laptop.
"""

from __future__ import annotations

import logging
import platform
import sys
from typing import Any, Optional

log = logging.getLogger("hub.platforms")

# Open files a Mac hub asks for (launchd starts apps with 256).
OPEN_FILES = 4096

NAOQI_TYPES = ("naoqi", "pepper")
NAOQI_WINDOWS_ONLY = "Pepper and NAO work from a Windows laptop only."
LITE_WINDOWS_ONLY = "The USB Reachy Mini Lite works from a Windows laptop only."


def is_windows() -> bool:
    return sys.platform == "win32"


def is_mac() -> bool:
    return sys.platform == "darwin"


def naoqi_supported() -> bool:
    """NAO and Pepper need the NAOqi kit, which has no macOS build."""
    return not is_mac()


def usb_lite_supported() -> bool:
    return not is_mac()


def raise_open_file_limit(want: int = OPEN_FILES, resource_mod: Any = None) -> Optional[int]:
    """Lift the soft limit on open files to `want` (never above the hard
    limit, never lower than it is). Returns the new soft limit, or None when
    this system has no such limit (Windows)."""
    try:
        resource = resource_mod
        if resource is None:
            import resource  # type: ignore[no-redef]  # POSIX only
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        cap = want if hard == resource.RLIM_INFINITY else min(want, hard)
        if soft != resource.RLIM_INFINITY and soft < cap:
            resource.setrlimit(resource.RLIMIT_NOFILE, (cap, hard))
            log.info("open files: %s -> %s", soft, cap)
            return cap
        return soft
    except (ImportError, OSError, ValueError) as exc:
        log.info("open files limit unchanged: %s", exc)
        return None


def mac_arch(machine: Optional[str] = None) -> str:
    """"arm64" (Apple Silicon) or "x86_64" (Intel), the names the Mac
    release tarballs carry. `platform.machine()` says "arm64" on Apple
    Silicon; a runtime under Rosetta says "x86_64", and gets the Intel build
    it is running as."""
    name = (platform.machine() if machine is None else machine or "").strip().lower()
    if name in ("arm64", "aarch64", "armv8", "arm64e"):
        return "arm64"
    return "x86_64"
