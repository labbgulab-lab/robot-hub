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

import platform
import sys
from typing import Optional

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


def mac_arch(machine: Optional[str] = None) -> str:
    """"arm64" (Apple Silicon) or "x86_64" (Intel), the names the Mac
    release tarballs carry. `platform.machine()` says "arm64" on Apple
    Silicon; a runtime under Rosetta says "x86_64", and gets the Intel build
    it is running as."""
    name = (platform.machine() if machine is None else machine or "").strip().lower()
    if name in ("arm64", "aarch64", "armv8", "arm64e"):
        return "arm64"
    return "x86_64"
