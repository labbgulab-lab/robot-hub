"""Reachy Mini Lite detector: USB PnP (PLAN.md 2.1, 2.6).

The Lite has no computer and no network stack at all, so no sweep and no mDNS
browse can find it: presence *is* USB enumeration (profiles/reachy-mini-lite.md).
The card key is the USB serial off `USB\\VID_38FB&PID_1001`, which is per-unit
-- it still names this robot correctly if the wireless Reachy is ever plugged
into the same laptop.

The address reported is the loopback daemon, not the device: the Reachy Mini
Control desktop app *is* the Lite's daemon host and binds `127.0.0.1:8000`
only (2.6). Note that the app exits about 34 s after an unplug, so the USB
sighting disappears well before the daemon does.

Both backends are optional. On Windows this is WMI, which needs
`pythoncom.CoInitialize()` on the thread that uses it -- so the poll runs in a
worker thread on a 2 s cadence rather than as an async WMI event watcher,
which cannot be driven from the event loop. On Linux it is pyudev. With
neither installed the detector says so once, in one sentence, and stops. It
never raises: a robot you do not own costs nothing (13.6).
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..adapters.base import Found
from ..config import Config
from ..events import EventBus

log = logging.getLogger("hub.discovery.usbwatch")

VENDOR_ID = "VID_38FB"          # Pollen Robotics
PRODUCT_ID = "PID_1001"         # the Lite's audio/control interface
LINUX_VENDOR_ID = "38fb"
LINUX_PRODUCT_ID = "1001"
POLL_S = 2.0
DEFAULT_LITE_URL = "http://127.0.0.1:8000"

_local = threading.local()


class UsbWatchDetector:
    name = "USB"

    def __init__(self, config: Config, bus: EventBus,
                 on_found: Callable[[Found], None]) -> None:
        self.config = config
        self.bus = bus
        self.on_found = on_found
        self._backend: Optional[Callable[[], list[dict[str, str]]]] = None
        self._wake = asyncio.Event()

    async def rescan(self) -> None:
        """Poll now instead of waiting out the 2 s cadence."""
        self._wake.set()

    async def _idle(self, interval: float) -> None:
        try:
            await asyncio.wait_for(self._wake.wait(), interval)
        except asyncio.TimeoutError:
            return
        finally:
            self._wake.clear()

    async def run(self) -> None:
        self._backend = self._pick_backend()
        if self._backend is None:
            return
        host, port = self._daemon()
        while True:
            try:
                devices = await asyncio.to_thread(self._backend)
            except Exception as exc:  # noqa: BLE001
                # A WMI hiccup must not take the detector down with it.
                log.warning("USB poll failed: %s", exc)
                devices = []
            for device in devices:
                self._emit(Found(
                    type_id="reachy_lite",
                    address=host,
                    port=port,
                    meta={"usb_serial": device.get("serial"),
                          "device_id": device.get("device_id"),
                          "device_name": device.get("name"),
                          "source": "usb"},
                ))
            await self._idle(POLL_S)

    # -------------------------------------------------------------- backends
    def _pick_backend(self) -> Optional[Callable[[], list[dict[str, str]]]]:
        if sys.platform == "win32":
            try:
                import pythoncom  # noqa: F401
                import wmi  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                self.bus.emit_log(
                    "warn",
                    "Reachy Mini Lite detection is off: this is Windows but the "
                    "WMI bindings did not import ({}). Install them with: "
                    "pip install wmi pywin32".format(exc))
                return None
            return _wmi_devices

        try:
            import pyudev  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            self.bus.emit_log(
                "warn",
                "Reachy Mini Lite detection is off: pyudev did not import ({}). "
                "Install it with: pip install pyudev".format(exc))
            return None
        return _pyudev_devices

    def _daemon(self) -> tuple[str, int]:
        raw = str(self.config.robot("reachy_lite").settings.get("daemon_url")
                  or DEFAULT_LITE_URL)
        parsed = urlparse(raw if "//" in raw else "http://" + raw)
        return (parsed.hostname or "127.0.0.1", parsed.port or 8000)

    def _emit(self, found: Found) -> None:
        try:
            self.on_found(found)
        except Exception as exc:  # noqa: BLE001
            log.warning("discovery callback raised for reachy_lite: %s", exc)


# ------------------------------------------------------------ worker thread
def _wmi_connection() -> Any:
    """One COM apartment and one WMI connection per worker thread.

    CoInitialize() is per-thread and the connection belongs to the thread that
    made it, so both are cached in thread-local storage. asyncio.to_thread may
    hand the poll to a different worker; that one simply initialises its own.
    """
    connection = getattr(_local, "wmi", None)
    if connection is None:
        import pythoncom
        import wmi
        pythoncom.CoInitialize()
        connection = wmi.WMI()
        _local.wmi = connection
    return connection


def _wmi_devices() -> list[dict[str, str]]:
    connection = _wmi_connection()
    query = ("SELECT DeviceID, Name FROM Win32_PnPEntity "
             "WHERE DeviceID LIKE '%{}%'".format(VENDOR_ID))
    try:
        entities = connection.query(query)
    except Exception as exc:  # noqa: BLE001
        log.debug("WQL LIKE query failed (%s); enumerating instead", exc)
        entities = [e for e in connection.Win32_PnPEntity()
                    if VENDOR_ID in (e.DeviceID or "").upper()]

    out: dict[str, dict[str, str]] = {}
    for entity in entities:
        device_id = (entity.DeviceID or "").upper()
        if PRODUCT_ID not in device_id:
            continue
        serial = _serial_from_device_id(device_id)
        if serial is None:
            continue
        out[serial] = {"serial": serial, "device_id": device_id,
                       "name": getattr(entity, "Name", "") or ""}
    return list(out.values())


def _serial_from_device_id(device_id: str) -> Optional[str]:
    """`USB\\VID_38FB&PID_1001\\100025004261401779` -> the serial.

    The composite sub-interfaces (`...&MI_00\\7&2a3b...&0&0000`) carry a
    generated instance path instead, which is not stable across USB ports, so
    anything containing `&` is rejected rather than used as a key (2.2).
    """
    parts = device_id.split("\\")
    if len(parts) < 3:
        return None
    instance = parts[2].strip()
    if not instance or "&" in instance:
        return None
    return instance


def _pyudev_devices() -> list[dict[str, str]]:
    import pyudev

    context = pyudev.Context()
    out: dict[str, dict[str, str]] = {}
    for device in context.list_devices(subsystem="usb"):
        if (device.get("ID_VENDOR_ID") or "").lower() != LINUX_VENDOR_ID:
            continue
        # The camera is PID_1002 on the same unit -- one robot, one card (2.2).
        if (device.get("ID_MODEL_ID") or "").lower() != LINUX_PRODUCT_ID:
            continue
        serial = device.get("ID_SERIAL_SHORT")
        if not serial:
            continue
        out[serial] = {"serial": serial,
                       "device_id": device.device_path or "",
                       "name": device.get("ID_MODEL", "") or ""}
    return list(out.values())
