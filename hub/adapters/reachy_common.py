"""One async client for the Pollen daemon, shared by both Reachys.

The daemon is the clearest example of PLAN.md 2.3 -- *status endpoints lie* --
and this module is where that is dealt with once instead of twice:

  * `POST /health-check` returned `{"status":"ok"}` at every stage of the
    measured unplug cascade, including `state=error` and `state=stopped`. It
    is a liveness check of the web server, not of the robot. Never used here.
  * The only trustworthy online signal is
    `state == "running" AND backend_status.ready == true`.
  * `control_loop_stats.nb_error` is a *leading* indicator: it moved ~1 s
    after the fault and ~7 s before `state` did. A hub watching `state` alone
    shows green for eight seconds after the robot is physically gone, so a
    rise in nb_error takes the card amber immediately.
  * A daemon restart is ~20 s of ConnectionError and then clean (2.9). That is
    normal, so it is reported as `restarting` rather than as death -- the
    caller rides it out instead of starting a reconnect storm.
  * `/api/apps/list-available/local` returns `[]` on both robots even while an
    app runs. `/api/apps/current-app-status` is the real answer.
  * The daemon version is recorded on connect, because on 1.9.0 `ready` is
    permanently false and a desktop-app update can silently downgrade it (12).

There is no TTS endpoint anywhere in the 98 paths, so the announcement is a
pre-rendered WAV: upload (idempotent), acquire media, play, release (8).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from .base import AdapterUnavailable, Health

# 1.10.0 removed the `ready:false` lie; below it the health rule is different.
MIN_GOOD_VERSION = (1, 10, 0)

# A restart is ~20 s of ConnectionError (2.9). Allow a little margin.
RESTART_WINDOW_S = 26.0

# Once nb_error rises, hold amber long enough for `state` to catch up (~7 s),
# so the card does not flicker back to green inside the silent window.
DEGRADE_HOLD_S = 10.0

DEFAULT_TIMEOUT_S = 4.0


class DaemonRestarting(RuntimeError):
    """The daemon stopped answering recently enough to be a restart, not a
    death. Distinguishable on purpose so the caller can wait it out."""


class DaemonError(RuntimeError):
    """Any other daemon failure, already phrased as a human sentence."""


def _httpx() -> Any:
    try:
        import httpx
    except Exception as exc:  # noqa: BLE001
        raise AdapterUnavailable(
            "httpx is not installed, so no Reachy can be reached; run: "
            "pip install -r requirements.txt"
        ) from exc
    return httpx


def version_tuple(version: Optional[str]) -> tuple[int, ...]:
    if not version:
        return ()
    parts: list[int] = []
    for chunk in str(version).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


class PollenDaemon:
    """HTTP client for one robot's daemon. One instance per robot."""

    def __init__(self, base_url: str, *, name: str = "Reachy",
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.timeout_s = timeout_s
        self.daemon_version: Optional[str] = None
        self.last_status: dict[str, Any] = {}
        self._client: Any = None
        self._prev_nb_error: Optional[int] = None
        self._degraded_until: float = 0.0
        self._unreachable_since: Optional[float] = None

    # ------------------------------------------------------------ plumbing
    async def _get_client(self) -> Any:
        if self._client is None:
            httpx = _httpx()
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        httpx = _httpx()
        client = await self._get_client()
        try:
            response = await client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout,
                httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            now = time.monotonic()
            if self._unreachable_since is None:
                self._unreachable_since = now
            if now - self._unreachable_since < RESTART_WINDOW_S:
                raise DaemonRestarting(
                    "{} is not answering on {} -- a daemon restart looks "
                    "exactly like this for about 20 seconds".format(
                        self.name, self.base_url)) from exc
            raise DaemonError(
                "{} is not answering on {} ({})".format(
                    self.name, self.base_url, type(exc).__name__)) from exc
        except Exception as exc:  # noqa: BLE001
            raise DaemonError("{}: {} on {}{}".format(
                self.name, type(exc).__name__, self.base_url, path)) from exc

        self._unreachable_since = None
        if response.status_code >= 400:
            raise DaemonError("{}: {} {} returned HTTP {}".format(
                self.name, method, path, response.status_code))
        return response

    async def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        try:
            return response.json()
        except Exception:  # noqa: BLE001
            return {}

    @property
    def restarting(self) -> bool:
        return (self._unreachable_since is not None
                and time.monotonic() - self._unreachable_since < RESTART_WINDOW_S)

    # -------------------------------------------------------------- status
    async def status(self) -> dict[str, Any]:
        data = await self._json("GET", "/api/daemon/status")
        if isinstance(data, dict):
            self.last_status = data
            version = data.get("version")
            if version:
                self.daemon_version = str(version)
        return self.last_status

    async def robot_name(self) -> Optional[str]:
        """Present from daemon 1.10.0 onward; 404 on 1.9.0."""
        try:
            data = await self._json("GET", "/api/daemon/robot-name")
        except DaemonError:
            return None
        return data.get("name") if isinstance(data, dict) else None

    def version_note(self) -> str:
        """The sentence a silent daemon downgrade must not be able to hide."""
        if not self.daemon_version:
            return ""
        if version_tuple(self.daemon_version) < MIN_GOOD_VERSION:
            return ("daemon {} is older than 1.10.0, where `ready` is "
                    "permanently false -- a desktop-app update can downgrade "
                    "it silently; re-run the daemon update".format(
                        self.daemon_version))
        return ""

    async def health(self) -> Health:
        """The only trustworthy reading (2.3). Never calls /health-check."""
        try:
            status = await self.status()
        except DaemonRestarting as exc:
            return {"online": False, "degraded": True,
                    "detail": str(exc), "battery": None}
        except DaemonError as exc:
            return {"online": False, "degraded": False,
                    "detail": str(exc), "battery": None}

        state = str(status.get("state") or "unknown")
        backend = status.get("backend_status") or {}
        ready = backend.get("ready")
        loop_stats = backend.get("control_loop_stats") or {}
        nb_error = loop_stats.get("nb_error")
        frequency = loop_stats.get("frequency") or loop_stats.get("freq")

        rising = False
        if isinstance(nb_error, int):
            if self._prev_nb_error is not None and nb_error > self._prev_nb_error:
                rising = True
                self._degraded_until = time.monotonic() + DEGRADE_HOLD_S
            self._prev_nb_error = nb_error
        degraded = rising or time.monotonic() < self._degraded_until

        online = state == "running" and ready is True
        daemon_error = status.get("daemon_error") or backend.get("error")

        if online and degraded:
            detail = ("control loop is reporting errors ({}) -- the robot "
                      "usually stops about 7 seconds later".format(nb_error))
        elif online:
            detail = "ready"
            if frequency:
                try:
                    detail = "ready, control loop {:.1f} Hz".format(float(frequency))
                except (TypeError, ValueError):
                    pass
        elif daemon_error:
            detail = "{} (state {})".format(daemon_error, state)
        elif state == "running":
            detail = "daemon is running but the robot backend is not ready"
        else:
            detail = "daemon reports state '{}'".format(state)

        note = self.version_note()
        if note:
            detail = "{}; {}".format(detail, note)

        # Battery: swept all 98 endpoints, neither Reachy reports one (2.9).
        return {"online": online, "degraded": degraded,
                "detail": detail, "battery": None}

    async def system_status(self) -> dict[str, Any]:
        try:
            await self.status()
        except (DaemonError, DaemonRestarting):
            pass
        return {"daemon_version": self.daemon_version}

    # ----------------------------------------------------------- app state
    async def app_lock(self) -> dict[str, Any]:
        """`{"state":"local_app","holder_name":...}` when held, `"free"` when
        not. It releases cleanly on app exit -- no stale-lock cleanup."""
        data = await self._json("GET", "/api/daemon/robot-app-lock-status")
        return data if isinstance(data, dict) else {}

    async def current_app(self) -> dict[str, Any]:
        """`/api/apps/list-available/local` returns [] on both robots even
        while an app runs. This is the endpoint that answers the question."""
        data = await self._json("GET", "/api/apps/current-app-status")
        return data if isinstance(data, dict) else {}

    async def lock_holder(self) -> Optional[str]:
        try:
            lock = await self.app_lock()
        except (DaemonError, DaemonRestarting):
            return None
        if lock.get("state") in (None, "free"):
            return None
        return lock.get("holder_name") or str(lock.get("state"))

    async def stop_current_app(self) -> None:
        await self._request("POST", "/api/apps/stop-current-app")

    # --------------------------------------------------------------- media
    async def media_acquire(self) -> None:
        await self._request("POST", "/api/media/acquire")

    async def media_release(self) -> None:
        await self._request("POST", "/api/media/release")

    # ---- body: what the desktop app does on connect, so the robot looks awake
    async def set_volume(self, percent: int) -> None:
        await self._request("POST", "/api/volume/set",
                            json={"volume": max(0, min(100, int(percent)))})

    async def set_motor_mode(self, mode: str) -> None:
        """`enabled` | `disabled` | `gravity_compensation`."""
        await self._request("POST", "/api/motors/set_mode/{}".format(mode))

    async def _play_move(self, name: str, timeout_s: float) -> None:
        """Start a built-in move and wait for it to finish: the endpoint
        returns a uuid at once, and the move is done when it leaves
        /api/move/running."""
        started = await self._json("POST", "/api/move/play/{}".format(name))
        uuid = started.get("uuid") if isinstance(started, dict) else None
        deadline = time.monotonic() + timeout_s
        await asyncio.sleep(0.5)
        while uuid and time.monotonic() < deadline:
            running = await self._json("GET", "/api/move/running")
            if not any(isinstance(m, dict) and m.get("uuid") == uuid
                       for m in (running or [])):
                return
            await asyncio.sleep(0.5)

    async def wake_up(self, timeout_s: float = 10.0) -> None:
        await self.set_motor_mode("enabled")
        await self._play_move("wake_up", timeout_s)

    async def go_to_sleep(self, timeout_s: float = 10.0) -> None:
        await self._play_move("goto_sleep", timeout_s)
        await self.set_motor_mode("disabled")

    async def list_sounds(self) -> list[str]:
        data = await self._json("GET", "/api/media/sounds")
        return _sound_names(data)

    async def upload_sound(self, path: Path) -> None:
        """Idempotent per the daemon's own docs, but `list_sounds` is checked
        first anyway so a re-connect does not re-upload every time."""
        httpx = _httpx()
        client = await self._get_client()
        try:
            with path.open("rb") as handle:
                files = {"file": (path.name, handle, "audio/wav")}
                response = await client.post(
                    "/api/media/sounds/upload", files=files,
                    timeout=max(self.timeout_s, 30.0))
        except httpx.HTTPError as exc:
            raise DaemonError(
                "could not upload {} to {}: {}".format(
                    path.name, self.name, type(exc).__name__)) from exc
        except OSError as exc:
            raise DaemonError("could not read {}: {}".format(path, exc)) from exc
        if response.status_code >= 400:
            raise DaemonError(
                "{} refused the announcement upload (HTTP {}) -- the daemon's "
                "upload field name may differ on this version".format(
                    self.name, response.status_code))

    async def play_sound(self, sound: str) -> None:
        try:
            # Field is `file` (PlaySoundRequest, daemon 1.11.0 openapi.json).
            await self._request("POST", "/api/media/play_sound",
                                json={"file": sound})
        except DaemonError as exc:
            raise DaemonError(
                "{} would not play {} ({}) -- media was acquired, so this is "
                "the daemon refusing the request, not a missing claim".format(
                    self.name, sound, exc)) from exc

    async def play_wav(self, path: Path) -> None:
        """Upload-if-needed, acquire, play, release. The whole announcement."""
        if not path.is_file():
            raise DaemonError(
                "the announcement recording {} is missing -- run "
                "`python tools/make_announcement_wavs.py` (the Pollen daemon "
                "has no text-to-speech of its own)".format(path.name))

        holder = await self.lock_holder()
        if holder:
            raise DaemonError(
                "{} is held by '{}' -- stop that app before the hub can speak "
                "through the robot".format(self.name, holder))

        try:
            existing = await self.list_sounds()
        except DaemonError:
            existing = []
        if path.name not in existing:
            await self.upload_sound(path)

        # Leave media exactly as found. Releasing it when it was held switches
        # the daemon's audio off (media_released=true), and every SDK client
        # started afterwards -- reachy_chat's player included -- then falls
        # back to WebRTC and dies (reachy2, 2026-09-23).
        try:
            status = await self._json("GET", "/api/media/status")
            was_released = bool(status.get("released")) if isinstance(status, dict) else False
        except DaemonError:
            was_released = False
        if was_released:
            await self.media_acquire()
        try:
            await self.play_sound(path.name)
            # play_sound returns as soon as playback starts; releasing media
            # then would cut the sentence off, so wait out the clip.
            await asyncio.sleep(_wav_seconds(path) + 0.3)
        finally:
            if was_released:
                try:
                    await self.media_release()
                except (DaemonError, DaemonRestarting):
                    pass        # the lock releases on exit anyway (2.9)


def _wav_seconds(path: Path) -> float:
    import wave
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:  # noqa: BLE001
        return 4.0


def _sound_names(data: Any) -> list[str]:
    """The shape of `GET /api/media/sounds` was never captured, so accept the
    three plausible ones rather than guess a single wrong key."""
    if isinstance(data, dict):
        for key in ("sounds", "files", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for entry in data:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, dict):
            value = entry.get("name") or entry.get("filename") or entry.get("file")
            if value:
                names.append(str(value))
    return names


async def wait_for_daemon(daemon: PollenDaemon, timeout_s: float,
                          interval_s: float = 1.0) -> bool:
    """Poll until the daemon answers with a real status, or time runs out."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if await daemon.status():
                return True
        except (DaemonError, DaemonRestarting):
            pass
        await asyncio.sleep(interval_s)
    return False
