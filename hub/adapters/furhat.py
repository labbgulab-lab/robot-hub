"""Furhat -- no mDNS, no JSON status endpoint, and nothing on this laptop.

Furhat advertises no mDNS at all, so it is found by the netscan detector's
HTTP fingerprint and keyed on the MAC that detector supplies (PLAN.md 2.1,
2.2). Everything else about it runs on the robot: no laptop port, no launcher,
no child process, and no laptop capture device -- it is the only robot of the
four guaranteed never to enter the microphone arbitration.

Control is Path B from `docs/profiles/furhat-control.md`: the same WebSocket
event bus Studio itself uses, `ws://<ip>/api`, with a SHA-256 login. That
capture is verified working and is followed here exactly -- subscribe first or
the bus stays silent, then send the password as uppercase hex SHA-256.

Status: there is no status endpoint on port 80, so `RequestSystemStatus` over
that same bus is the real signal. When a key is configured, the Realtime API
on :9000 adds structured reads; several of its requests are silent without
`"monitor": true`, so no reply never means unsupported (2.9). The key is
per-install and user-supplied, so its absence disables that path quietly
rather than counting as an error (11.2).

Speech is `ActionSpeech`. TTS caches per string -- the first utterance of a
phrase costs ~1.1 s of generation and repeats cost 0 ms, shared across both
paths -- so every connect after the first one is instant. Neither captured
path has a generate-without-speaking request, so the phrase cannot be warmed
silently: the announcement *is* the warming utterance, and what the adapter
does instead is allow a cold phrase its generation second and hold a warm one
to a short timeout, so a robot that has gone quiet is noticed quickly. When no
start event comes back at all, the sentence names the engine trap from
`profiles/furhat.md`, because that warning is itself the diagnosis.

Settings read from `[robots.furhat.settings]`:
    username   Studio web login (default "admin"); only used for the Launch hint
    password   Studio password, hashed before it ever leaves this process
Environment:
    FURHAT_API_KEY   optional Realtime API key; absent = that path is unused
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Callable, Optional

from .base import AdapterUnavailable, Claim, Found, Health, RobotAdapter

STUDIO_WS_PATH = "/api"
REALTIME_PORT = 9000
REALTIME_PATH = "/v1/events"

EV_SUBSCRIBE = "furhatos.event.actions.ActionRealTimeAPISubscribe"
EV_LOGIN = "furhatos.event.actions.ActionLoginAccess"
EV_SPEECH = "furhatos.event.actions.ActionSpeech"
EV_STATUS_REQUEST = "furhatos.event.requests.RequestSystemStatus"
EV_VOICE_REQUEST = "furhatos.event.requests.RequestVoice"
EV_CONFIG_VOICE = "furhatos.event.actions.ActionConfigVoice"

MON_LOGIN = "furhatos.event.monitors.MonitorLoginAccess"
MON_STATUS = "furhatos.event.monitors.MonitorSystemStatus"
MON_SPEECH_START = "furhatos.event.monitors.MonitorSpeechStart"
MON_SPEECH_END = "furhatos.event.monitors.MonitorSpeechEnd"
MON_CONFIG_VOICE = "furhatos.event.monitors.MonitorConfigVoice"
RESP_VOICE = "furhatos.event.responses.ResponseVoice"

# After a reboot Furhat comes up on its factory voice, Sakura22k_HQ (ja-JP),
# and reads English in Japanese; the cloud voices (Polly, Azure) also load a
# while after boot (2026-10-05: 192 voices at first, 914 later). So Connect
# sets an English voice every time instead of trusting what is set.
DEFAULT_VOICE = "Gregory-Neural (en-US) - Amazon Polly"
FALLBACK_VOICE = "Will22k_HQ (en-US) - Acapela"   # built in, no cloud needed
VOICE_TIMEOUT_S = 5.0

LOGIN_TIMEOUT_S = 8.0
STATUS_TIMEOUT_S = 3.0
SPEECH_START_TIMEOUT_S = 10.0   # a cold phrase costs ~1.1 s of generation
SPEECH_START_CACHED_S = 4.0     # a phrase already in the cache starts in 0 ms

ENGINE_TRAP = (
    "Furhat accepted the speech but never started speaking. On this robot "
    "that is almost always the engine trap: in Settings -> Speaking and "
    "Settings -> Listening, flip each engine to Custom and straight back to "
    "Furhat provided, and check speech recognition is Microsoft Azure, not "
    "Google Cloud"
)


def _websockets() -> Any:
    try:
        import websockets
    except Exception as exc:  # noqa: BLE001
        raise AdapterUnavailable(
            "the websockets package is not installed, so Furhat cannot be "
            "controlled; run: pip install -r requirements.txt"
        ) from exc
    return websockets


async def _ws_connect(uri: str, timeout_s: float) -> Any:
    websockets = _websockets()
    try:
        from websockets.asyncio.client import connect
    except Exception:  # noqa: BLE001  - older websockets releases
        connect = websockets.connect
    return await asyncio.wait_for(connect(uri, ping_interval=20), timeout_s)


class StudioBus:
    """One live connection to `ws://<ip>/api`, with the login already done."""

    def __init__(self, host: str, password: str,
                 on_event: Optional[Callable[[dict], None]] = None) -> None:
        self.host = host
        self.password = password
        self.on_event = on_event
        self._ws: Any = None
        self._reader: Optional[asyncio.Task] = None
        self._waiters: list[tuple[set[str], asyncio.Future]] = []
        self.system_status: dict[str, Any] = {}
        # Studio hands out a session id at login and stamps it on every event
        # it sends. Speech works without it; settings changes do not -- they
        # are answered "Redirect", Studio's "not logged in" (2026-10-05).
        self.session_id = ""

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._reader is not None \
            and not self._reader.done()

    async def open(self) -> None:
        self._ws = await _ws_connect(
            "ws://{}{}".format(self.host, STUDIO_WS_PATH), LOGIN_TIMEOUT_S)
        self._reader = asyncio.create_task(self._read_loop())
        # Subscribe before logging in -- the bus stays silent otherwise.
        for monitor in (MON_LOGIN, MON_STATUS, MON_SPEECH_START, MON_SPEECH_END,
                        MON_CONFIG_VOICE, RESP_VOICE):
            await self.send({"event_name": EV_SUBSCRIBE, "name": monitor})

        digest = hashlib.sha256(self.password.encode("utf-8")).hexdigest().upper()
        reply = await self.request({"event_name": EV_LOGIN, "password": digest},
                                   {MON_LOGIN}, LOGIN_TIMEOUT_S)
        if reply is None:
            raise RuntimeError(
                "Furhat Studio never answered the login on ws://{}{}".format(
                    self.host, STUDIO_WS_PATH))
        if not reply.get("loginApproved"):
            raise RuntimeError(
                "Furhat Studio refused the login -- the password in "
                "config.toml does not match the one set in Studio")
        self.session_id = str(reply.get("event_sessionId") or "")

    async def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
        for _names, future in self._waiters:
            if not future.done():
                future.cancel()
        self._waiters.clear()

    async def send(self, event: dict[str, Any]) -> None:
        if self._ws is None:
            raise RuntimeError("not connected to Furhat Studio")
        if self.session_id:
            event = {**event, "event_sessionId": self.session_id}
        await self._ws.send(json.dumps(event))

    async def request(self, event: dict[str, Any], expect: set[str],
                      timeout_s: float) -> Optional[dict[str, Any]]:
        """Send, then wait for one of `expect`. None means nothing came back,
        which on this bus means 'no monitor for that', not 'unsupported'."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        waiter = (set(expect), future)
        self._waiters.append(waiter)
        try:
            await self.send(event)
            return await asyncio.wait_for(future, timeout_s)
        except asyncio.TimeoutError:
            return None
        finally:
            if waiter in self._waiters:
                self._waiters.remove(waiter)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    event = json.loads(raw)
                except Exception:  # noqa: BLE001
                    continue
                name = event.get("event_name", "")
                if name == MON_STATUS:
                    self.system_status = event
                if self.on_event is not None:
                    self.on_event(event)
                for names, future in list(self._waiters):
                    if name in names and not future.done():
                        future.set_result(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            return          # the socket died; `connected` reports it


class FurhatAdapter(RobotAdapter):
    type_id = "furhat"
    display_name = "Furhat"
    reports_battery = False     # mains powered; it reports no battery at all

    def __init__(self, found: Found, config: Any) -> None:
        super().__init__(found, config)
        self.settings = config.robot(self.type_id).settings
        self._bus: Optional[StudioBus] = None
        self._spoken: set[str] = set()

    # ------------------------------------------------------------ identity
    def stable_key(self, found: Found) -> str:
        mac = found.meta.get("mac") or found.txt("mac")
        if mac:
            return str(mac).lower()
        raise RuntimeError(
            "this Furhat was found without a MAC address, so its card cannot "
            "be keyed -- Furhat and a Reachy already shared one IP inside an "
            "hour on this hotspot")

    # ----------------------------------------------------------- lifecycle
    async def probe(self, found: Found) -> Health:
        self.found = found
        if self._bus is not None and self._bus.connected:
            reply = await self._bus.request(
                {"event_name": EV_STATUS_REQUEST}, {MON_STATUS}, STATUS_TIMEOUT_S)
            if reply is not None:
                return {"online": True, "degraded": False,
                        "detail": "Studio reports the system running",
                        "battery": None}
            # The bus is alive; silence here is a missing monitor, not death.
            return {"online": True, "degraded": False,
                    "detail": "connected; Studio sent no status reply",
                    "battery": None}
        return await self._fingerprint(found.address)

    async def _fingerprint(self, address: str) -> Health:
        """Port 80 must give a real Furhat Studio page.

        A bare connect is worthless on this laptop: the Check Point VPN
        adapter hooks outbound port-80 connects and makes them succeed for
        hosts that do not exist (2.9).
        """
        try:
            import httpx
        except Exception:  # noqa: BLE001
            return {"online": False, "degraded": False,
                    "detail": "httpx is not installed, so Furhat cannot be "
                              "probed", "battery": None}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                response = await client.get("http://{}/".format(address))
            if "furhat studio" in response.text.lower():
                return {"online": True, "degraded": False,
                        "detail": "Studio is serving on port 80",
                        "battery": None}
            return {"online": False, "degraded": True,
                    "detail": "something answered on port 80 but it is not "
                              "Furhat Studio", "battery": None}
        except Exception as exc:  # noqa: BLE001
            return {"online": False, "degraded": False,
                    "detail": "Furhat Studio did not answer on {} ({})".format(
                        address, type(exc).__name__), "battery": None}

    async def connect(self) -> None:
        password = str(self.settings.get("password")
                       or self.config.secret("FURHAT_PASSWORD") or "")
        if not password:
            raise RuntimeError(
                "Furhat Studio's password is not set -- put it in .env as "
                "FURHAT_PASSWORD (or in config.toml under "
                "[robots.furhat.settings]) so the hub can log in to the "
                "event bus")
        await self.disconnect()
        bus = StudioBus(self.found.address, password)
        await bus.open()
        self._bus = bus
        await self._ensure_voice(bus)
        if not self.config.secret("FURHAT_API_KEY"):
            self.notes.append(
                "no FURHAT_API_KEY set, so the Realtime API reads on port "
                "9000 are unavailable; Studio's own bus is being used")

    async def _ensure_voice(self, bus: StudioBus) -> None:
        """Put Furhat on an English voice before it says anything."""
        wanted = str(self.settings.get("voice") or DEFAULT_VOICE)
        status = await bus.request({"event_name": EV_VOICE_REQUEST},
                                   {RESP_VOICE}, VOICE_TIMEOUT_S) or {}
        current = str(status.get("voice") or "")
        available = {str(v.get("uniqueName")) for v in status.get("voiceList") or []
                     if isinstance(v, dict)}
        target = wanted
        if available and wanted not in available:
            # Typically the cloud voices are not loaded yet after a boot.
            target = FALLBACK_VOICE
            self.notes.append("voice '{}' is not available on Furhat yet; "
                              "using {} instead".format(wanted, target))
        if current == target:
            return
        reply = await bus.request({"event_name": EV_CONFIG_VOICE, "name": target},
                                  {MON_CONFIG_VOICE}, VOICE_TIMEOUT_S)
        if not (reply or {}).get("successfulSave"):
            self.notes.append("Furhat did not confirm the voice change to {} "
                              "(it was on {})".format(target, current or "unknown"))
        else:
            self.notes.append("voice set to {} (was {})".format(
                target, current or "unknown"))

    async def disconnect(self) -> None:
        bus, self._bus = self._bus, None
        if bus is not None:
            await bus.close()

    async def announce(self, text: str) -> None:
        if self._bus is None or not self._bus.connected:
            await self.connect()
        assert self._bus is not None
        timeout = (SPEECH_START_CACHED_S if text in self._spoken
                   else SPEECH_START_TIMEOUT_S)
        reply = await self._bus.request(
            {"event_name": EV_SPEECH, "text": text},
            {MON_SPEECH_START}, timeout)
        if reply is None:
            raise RuntimeError(ENGINE_TRAP)
        self._spoken.add(text)

    async def system_status(self) -> dict[str, Any]:
        status: dict[str, Any] = {"mic": "ReSpeaker 4 Mic Array (onboard)"}
        extra = await self._realtime_status()
        if extra:
            status["meta"] = extra
        return status

    async def _realtime_status(self) -> dict[str, Any]:
        """Path A: richer reads, only when the user supplied a key (11.2)."""
        key = self.config.secret("FURHAT_API_KEY")
        if not key:
            return {}
        uri = "ws://{}:{}{}".format(self.found.address, REALTIME_PORT, REALTIME_PATH)
        try:
            ws = await _ws_connect(uri, 5.0)
        except Exception as exc:  # noqa: BLE001
            self.notes.append(
                "the Realtime API on port {} did not accept a connection "
                "({})".format(REALTIME_PORT, type(exc).__name__))
            return {}
        try:
            await ws.send(json.dumps({"type": "request.auth", "key": key}))
            auth = json.loads(await asyncio.wait_for(ws.recv(), 5.0))
            if not auth.get("access"):
                self.notes.append(
                    "the Realtime API refused FURHAT_API_KEY -- it is "
                    "per-install and is regenerated whenever Studio reissues it")
                return {}
            await ws.send(json.dumps({"type": "request.system.status",
                                      "monitor": True}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 5.0))
            return reply if isinstance(reply, dict) else {}
        except Exception:  # noqa: BLE001
            return {}       # several requests are silent without a monitor
        finally:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------------- claims
    def claims(self) -> list[Claim]:
        """None. Furhat owns no laptop port, process or capture device, so it
        cannot collide with anything the hub runs (2.5)."""
        return []

    async def ensure_zero_instances(self) -> list[str]:
        return ["Furhat runs entirely on the robot; there is nothing on this "
                "laptop to stop"]

    async def launch(self) -> str:
        health = await self._fingerprint(self.found.address)
        if not health["online"]:
            raise RuntimeError(health["detail"])
        username = str(self.settings.get("username") or "admin")
        self.notes.append(
            "Studio will ask for the '{}' password".format(username))
        return "http://{}/".format(self.found.address)
