"""Reachy Mini Lite -- USB only, and the desktop-app rule inverts here.

The Lite has no computer and no network stack: it cannot be found by any
sweep, and its mDNS record advertises a Tailscale address that nothing can
reach. Presence is USB enumeration; the daemon is always `127.0.0.1:8000`
(PLAN.md 2.1, 6).

`Reachy Mini Control` is not a competitor for this robot, it is its host --
the app *is* the daemon. So the claim is `require`, the mirror image of the
wireless robot's `require_absent`, and it is scoped per robot because the app
holds one robot at a time and both Reachys are measured to coexist (2.6).

The app also exits entirely about 34 seconds after the robot is unplugged, so
replugging does not restore service. If the hub is to reconnect this card at
all it must be willing to start the app itself, which `connect()` does.

Settings read from `[robots.reachy_lite.settings]`:
    daemon_url    where the daemon answers (default http://127.0.0.1:8000)
    control_app   full path to "Reachy Mini Control.exe"
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .. import announce as announce_helper
from ..supervisor import get_supervisor
from .base import AdapterUnavailable, Claim, Found, Health, RobotAdapter
from .reachy_common import (
    DaemonError,
    DaemonRestarting,
    PollenDaemon,
    wait_for_daemon,
)

DEFAULT_DAEMON_URL = "http://127.0.0.1:8000"

# hub/core.py gives connect() 25 s in total, so the app has to come up inside
# that or the card gets a timeout instead of a sentence explaining itself.
APP_WAIT_S = 20.0

_SERIAL_KEYS = ("serial", "usb_serial", "serial_number", "SerialNumber")


def _serial_from_meta(meta: dict[str, Any]) -> str:
    for key in _SERIAL_KEYS:
        value = meta.get(key)
        if value:
            return str(value)
    # Windows PnP ids look like USB\VID_38FB&PID_1001\100025004261401779.
    for key in ("device_id", "DeviceID", "pnp_id", "instance_id"):
        raw = meta.get(key)
        if raw and "\\" in str(raw):
            tail = str(raw).rsplit("\\", 1)[-1].strip()
            if tail:
                return tail
    return ""


class ReachyLiteAdapter(RobotAdapter):
    type_id = "reachy_lite"
    display_name = "Reachy-Mini-Lite"
    reports_battery = False     # USB powered; there is no battery to report

    def __init__(self, found: Found, config: Any) -> None:
        super().__init__(found, config)
        self.settings = config.robot(self.type_id).settings
        self._daemon: Optional[PollenDaemon] = None
        self._app_child = ""

    # ------------------------------------------------------------ identity
    def stable_key(self, found: Found) -> str:
        serial = _serial_from_meta(found.meta)
        if serial:
            return serial
        raise RuntimeError(
            "this Reachy Lite reported no USB serial, so its card cannot be "
            "keyed -- the daemon exposes hardware_id as null on the Lite")

    # -------------------------------------------------------------- daemon
    def _daemon_url(self) -> str:
        return str(self.settings.get("daemon_url") or DEFAULT_DAEMON_URL).rstrip("/")

    def _get_daemon(self) -> PollenDaemon:
        if self._daemon is None:
            self._daemon = PollenDaemon(self._daemon_url(), name=self.display_name)
        return self._daemon

    # ----------------------------------------------------------- lifecycle
    async def probe(self, found: Found) -> Health:
        self.found = found
        return await self._get_daemon().health()

    async def connect(self) -> None:
        daemon = self._get_daemon()
        try:
            health = await daemon.health()
        except Exception:  # noqa: BLE001
            health = {"online": False, "degraded": False, "detail": "",
                      "battery": None}
        if not health["online"]:
            await self._start_control_app()
            if not await wait_for_daemon(daemon, APP_WAIT_S):
                raise RuntimeError(
                    "Reachy Mini Control was started but its daemon never "
                    "answered on {} within {:.0f} s -- open the app and check "
                    "the robot is attached".format(self._daemon_url(), APP_WAIT_S))
            health = await daemon.health()
            if not health["online"]:
                raise RuntimeError(health["detail"])

        holder = await daemon.lock_holder()
        if holder:
            # Single-tenant by design: start-app evicts. Surface the holder
            # rather than fight it -- most "the robot is stuck" is this.
            self.notes.append(
                "an app named '{}' currently holds the robot".format(holder))

    async def disconnect(self) -> None:
        daemon, self._daemon = self._daemon, None
        if daemon is not None:
            try:
                await daemon.media_release()
            except (DaemonError, DaemonRestarting):
                pass
            await daemon.aclose()
        # The desktop app is deliberately left running: it is this robot's
        # daemon host, not something the hub owns.

    async def announce(self, text: str) -> None:
        path = announce_helper.wav_path(self.config, text)
        await self._get_daemon().play_wav(path)

    async def system_status(self) -> dict[str, Any]:
        status = await self._get_daemon().system_status()
        status["mic"] = "Reachy Mini Audio (own USB device)"
        return status

    # -------------------------------------------------------------- claims
    def claims(self) -> list[Claim]:
        # `require`, not `require_absent` -- and scoped per robot, since the
        # app holds one robot at a time and the wireless Reachy can run
        # alongside it (2.6).
        return [{"kind": "exclusive",
                 "value": "reachy_desktop_app:{}".format(
                     self.stable_key(self.found)),
                 "mode": "require"}]

    # -------------------------------------------------------- desktop app
    def _control_app(self) -> Path:
        path = self.config.path(self.type_id, "control_app")
        if path is None:
            raise AdapterUnavailable(
                "set control_app in config.toml to your Reachy Mini Control "
                "executable -- the Lite has no daemon without it")
        if not path.is_file():
            raise AdapterUnavailable(
                "Reachy Mini Control was not found at {} -- install it or fix "
                "control_app in config.toml".format(path))
        return path

    async def _start_control_app(self) -> None:
        app = self._control_app()
        supervisor = get_supervisor()
        self._app_child = "reachy_mini_control"
        if supervisor.is_running(self._app_child):
            return
        await supervisor.start(self._app_child, [str(app)], cwd=app.parent,
                               owner=self.stable_key(self.found),
                               log_prefix=self.display_name)
        self.notes.append("started Reachy Mini Control (the Lite's daemon host)")

    async def ensure_zero_instances(self) -> list[str]:
        """Nothing to clear: the Lite's system is the desktop app, and the
        daemon enforces one app at a time itself. Report the holder instead."""
        holder = await self._get_daemon().lock_holder()
        if holder:
            return ["'{}' is holding the robot; starting another app would "
                    "evict it".format(holder)]
        return ["the robot's app lock is free"]

    async def launch(self) -> str:
        daemon = self._get_daemon()
        if not await wait_for_daemon(daemon, 3.0, interval_s=0.5):
            await self._start_control_app()
            if not await wait_for_daemon(daemon, APP_WAIT_S):
                raise RuntimeError(
                    "the Lite's daemon is not answering on {}, so there is no "
                    "page to open".format(self._daemon_url()))
        return self._daemon_url() + "/"
