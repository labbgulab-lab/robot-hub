"""The people's mic on the laptop, watched by the hub itself.

Tomer, 2026-10-22: for the 2026-10-26 demo the people are heard through a DJI
Mic Mini (receiver in the laptop's USB-C, the mic on his boss's shirt). The
hub, not the person running the demo, finds out whether it is plugged in, and
the apps start with it: the group conversation hears the people through it,
and reachy_chat is launched in its laptop-mic mode instead of on the robot.

PortAudio reads the device list once, when it starts, so a mic plugged in
later is invisible until PortAudio is restarted. The watcher restarts it
every few seconds, but only while this process has no audio stream open
(restarting it under an open stream kills the stream); while the group
conversation is listening through the mic, that stream itself says whether
the mic is still there (robots.PeopleMic).

The DJI receiver does not report its transmitters' battery over USB (only on
its own LEDs), so "the mic died" is read from the signal instead: a stream
that stops delivering, or pure digital silence for a while.

Every sounddevice call in the hub goes through PA_LOCK.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

log = logging.getLogger("hub.laptop_mic")

PA_LOCK = threading.RLock()
AUTO_HINTS = ("dji",)       # "auto" = the first input with this in its name
SCAN_S = 3.0

_streams = 0                # audio streams this process has open (no restart under them)


def stream_opened() -> None:
    global _streams
    with PA_LOCK:
        _streams += 1


def stream_closed() -> None:
    global _streams
    with PA_LOCK:
        _streams = max(0, _streams - 1)


def list_inputs(refresh: bool = False) -> list[dict]:
    """The laptop's microphones: [{"index", "name", "channels"}], one per
    device. On Windows the MME list (one entry per mic, short names; the same
    mic also appears under DirectSound, WASAPI and WDM-KS). `refresh`
    restarts PortAudio first, to see a mic plugged in since, unless a stream
    is open."""
    with PA_LOCK:
        try:
            import sounddevice as sd
            if refresh and _streams == 0:
                sd._terminate()
                sd._initialize()
            devices = sd.query_devices()
            apis = sd.query_hostapis()
        except Exception as exc:  # noqa: BLE001
            log.info("could not list the laptop's microphones: %s", exc)
            return []
    mme = next((i for i, a in enumerate(apis) if a.get("name") == "MME"), None)
    out, seen = [], set()
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) <= 0:
            continue
        if mme is not None and d.get("hostapi") != mme:
            continue
        name = str(d.get("name", "")).strip()
        if not name or "Sound Mapper" in name or name in seen:
            continue
        seen.add(name)
        out.append({"index": i, "name": name, "channels": int(d["max_input_channels"])})
    return out


def find(choice: str, devices: list[dict]) -> Optional[dict]:
    """The device a mic setting means: "robots" (or empty) none, "auto" the
    first DJI input if one is plugged in, else a device name (exact, then
    contained in a longer one)."""
    choice = (choice or "").strip()
    if not choice or choice == "robots":
        return None
    if choice == "auto":
        return next((d for d in devices
                     if any(h in d["name"].lower() for h in AUTO_HINTS)), None)
    low = choice.lower()
    return (next((d for d in devices if d["name"].lower() == low), None)
            or next((d for d in devices if low in d["name"].lower()), None))


class MicWatch:
    """Keeps the list of laptop mics current; says when a DJI mic comes or goes."""

    def __init__(self) -> None:
        self.devices: list[dict] = []
        self.scanned_at = 0.0
        self.on_change: Optional[Callable[[Optional[dict]], Any]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_dji: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self.scan()
        self._thread = threading.Thread(target=self._run, name="mic-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(SCAN_S):
            try:
                self.scan()
            except Exception:  # noqa: BLE001
                log.exception("mic scan failed")

    def scan(self) -> list[dict]:
        # With a stream open this is PortAudio's list from its last restart:
        # an unplugged mic is then noticed by its stream (robots.PeopleMic).
        self.devices = list_inputs(refresh=True)
        self.scanned_at = time.monotonic()
        dji = self.dji()
        name = dji["name"] if dji else None
        if name != self._last_dji:
            log.info("people's mic: %s", "{} plugged in".format(name) if name
                     else "{} is gone".format(self._last_dji) if self._last_dji
                     else "no DJI mic on this laptop")
            self._last_dji = name
            if self.on_change is not None:
                try:
                    self.on_change(dji)
                except Exception:  # noqa: BLE001
                    log.exception("mic change handler failed")
        return self.devices

    def dji(self) -> Optional[dict]:
        return find("auto", self.devices)

    def find(self, choice: str) -> Optional[dict]:
        return find(choice, self.devices)

    def names(self) -> list[str]:
        return [d["name"] for d in self.devices]


MIC_WATCH = MicWatch()
