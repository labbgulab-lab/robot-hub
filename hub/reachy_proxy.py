"""The Reachy app's Talk and Wizard of Oz tabs reach the robot through the hub.

reachy_chat runs on the robot (port 8765). The app never talks to the robot
itself: it calls the hub on 127.0.0.1, and the hub forwards.

    /api/reachy/{key}/{path}   ->  http://<robot>:8765/api/{path}
                                   GET / POST / PUT / DELETE, query string and
                                   body passed through, the answer (JSON or
                                   binary) passed back with its status
    /ws/reachy/{key}           <-> ws://<robot>:8765/ws

The robot is looked up in the hub's registry: its app's URL (`system_url`,
set by Launch) or else its address on port 8765. Errors are the hub's usual
`{error, code, ok: false}`:

    404 UNKNOWN_ROBOT   no such Reachy on this hub
    409 NOT_RUNNING     the robot's app is not up (refused or no answer)
    504 ROBOT_TIMEOUT   the app took the request but did not answer in time
    502 ROBOT_UNREACHABLE  any other network failure

The WebSocket relay sends its own messages, all with an `event` starting
with "proxy.": `proxy.open` once the robot's socket is up, `proxy.error`
`{code, error}` when it cannot be reached (then it closes), and
`proxy.closed` when the robot's side went away. The page reconnects.

Every message relayed from the robot also goes to the transcripts
(hub/transcripts.py), so a Talk conversation is saved while the app is open.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

log = logging.getLogger("hub.reachy_proxy")

APP_PORT = 8765                      # reachy_chat's dashboard on the robot
CONNECT_TIMEOUT_S = 3.0
READ_TIMEOUT_S = 15.0
# Routes that block on the robot for longer than a normal call.
SLOW_ROUTES = (
    ("system/start", 45.0),          # ~7-10 s, more on a slow link
    ("system/stop", 60.0),           # ends a conversation gracefully (40 s cap)
    ("conversation/end", 60.0),
    ("conversation/start", 30.0),
    ("show/prepare", 40.0),          # records the line (30 s cap on the robot)
    ("show/say", 45.0),
    ("show/rebuild", 300.0),         # re-records every changed line
    ("show/cue", 60.0),              # save / add / delete re-record one line
)
METHODS = ["GET", "POST", "PUT", "DELETE"]
# Request headers worth passing on; everything else (host, cookies) stays here.
PASS_REQUEST_HEADERS = ("content-type", "accept")
PASS_RESPONSE_HEADERS = ("content-type", "content-disposition", "cache-control")

WsConnect = Callable[[str], Awaitable[Any]]


def read_timeout(path: str) -> float:
    for prefix, seconds in SLOW_ROUTES:
        if path.startswith(prefix):
            return seconds
    return READ_TIMEOUT_S


def error(message: str, code: str, status: int) -> JSONResponse:
    return JSONResponse({"error": message, "code": code, "ok": False}, status_code=status)


def is_reachy(robot: Any) -> bool:
    return str(getattr(robot, "type_id", "")).startswith("reachy")


def app_base(robot: Any) -> Optional[str]:
    """http://host:port of the robot's reachy_chat, or None if unknown."""
    url = getattr(robot, "system_url", None)
    if url:
        parts = urlsplit(str(url))
        if parts.hostname:
            host = parts.hostname
            if ":" in host:          # IPv6
                host = "[{}]".format(host)
            return "{}://{}:{}".format(parts.scheme or "http", host, parts.port or APP_PORT)
    address = getattr(robot, "address", None)
    if address:
        return "http://{}:{}".format(address, APP_PORT)
    return None


async def _default_ws_connect(url: str) -> Any:
    from websockets.asyncio.client import connect
    # proxy=None: the robot is on the local network; websockets would
    # otherwise go through the laptop's system proxy and never arrive.
    return await connect(url, open_timeout=CONNECT_TIMEOUT_S, ping_interval=20,
                         ping_timeout=20, max_size=8 * 1024 * 1024, proxy=None)


def make_router(hub: Any, *, transcripts: Any = None,
                transport: Optional[httpx.AsyncBaseTransport] = None,
                ws_connect: Optional[WsConnect] = None) -> APIRouter:
    """`transport` and `ws_connect` stand in for the network in tests."""
    router = APIRouter()
    connect_ws = ws_connect or _default_ws_connect

    def robot_for(key: str) -> Any:
        r = hub.registry.get(key)
        return r if r is not None and is_reachy(r) else None

    def not_running(r: Any) -> JSONResponse:
        return error("{}'s app is not running.".format(getattr(r, "name", "The robot")),
                     "NOT_RUNNING", 409)

    @router.api_route("/api/reachy/{key}/{path:path}", methods=METHODS, response_model=None)
    async def forward(key: str, path: str, request: Request):
        r = robot_for(key)
        if r is None:
            return error("There is no Reachy called {} on this hub.".format(key),
                         "UNKNOWN_ROBOT", 404)
        base = app_base(r)
        if base is None:
            return not_running(r)
        # The path arrives decoded ("c 1"); a cue id goes back out encoded.
        url = "{}/api/{}".format(base, quote(path.lstrip("/"), safe="/:@!$&'()*+,;=-._~"))
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() in PASS_REQUEST_HEADERS}
        body = await request.body()
        timeout = httpx.Timeout(read_timeout(path), connect=CONNECT_TIMEOUT_S)
        try:
            # trust_env=False: no proxy from the environment for a robot on the LAN.
            async with httpx.AsyncClient(transport=transport, timeout=timeout,
                                         trust_env=False) as client:
                upstream = await client.request(
                    request.method, url, params=list(request.query_params.multi_items()),
                    content=body or None, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return not_running(r)
        except httpx.TimeoutException:
            return error("{} did not answer in time.".format(r.name), "ROBOT_TIMEOUT", 504)
        except httpx.HTTPError as exc:
            log.info("%s: %s %s failed: %s", r.name, request.method, path, exc)
            return error("Could not reach {}.".format(r.name), "ROBOT_UNREACHABLE", 502)
        out_headers = {k: v for k, v in upstream.headers.items()
                       if k.lower() in PASS_RESPONSE_HEADERS}
        return Response(content=upstream.content, status_code=upstream.status_code,
                        headers=out_headers)

    @router.websocket("/ws/reachy/{key}")
    async def relay(ws: WebSocket, key: str) -> None:
        await ws.accept()
        r = robot_for(key)
        if r is None:
            await _say(ws, {"event": "proxy.error", "code": "UNKNOWN_ROBOT",
                            "error": "There is no Reachy called {} on this hub.".format(key)})
            await _close(ws)
            return
        base = app_base(r)
        upstream = None
        if base is not None:
            ws_url = base.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
            try:
                upstream = await connect_ws(ws_url)
            except Exception as exc:  # noqa: BLE001  (refused, timeout, DNS: all "not up")
                log.debug("%s: relay could not connect: %s", r.name, exc)
        if upstream is None:
            await _say(ws, {"event": "proxy.error", "code": "NOT_RUNNING",
                            "error": "{}'s app is not running.".format(r.name)})
            await _close(ws)
            return
        await _say(ws, {"event": "proxy.open", "key": key, "robot": r.name})

        async def robot_to_page() -> None:
            async for message in upstream:
                if isinstance(message, (bytes, bytearray)):
                    await ws.send_bytes(bytes(message))
                    continue
                if transcripts is not None:
                    try:
                        event = json.loads(message)
                        if isinstance(event, dict):
                            transcripts.talk_event(key, r.name, event)
                    except Exception:  # noqa: BLE001  (never stops the relay)
                        log.debug("transcript feed", exc_info=True)
                await ws.send_text(message)

        async def page_to_robot() -> None:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    return
                if message.get("text") is not None:
                    await upstream.send(message["text"])
                elif message.get("bytes") is not None:
                    await upstream.send(message["bytes"])

        down = asyncio.create_task(robot_to_page())
        up = asyncio.create_task(page_to_robot())
        try:
            done, _pending = await asyncio.wait({down, up}, return_when=asyncio.FIRST_COMPLETED)
            if down in done:
                await _say(ws, {"event": "proxy.closed", "code": "NOT_RUNNING",
                                "error": "{}'s app went away.".format(r.name)})
        except WebSocketDisconnect:
            pass
        finally:
            for task in (down, up):
                task.cancel()
            for task in (down, up):
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
            try:
                await upstream.close()
            except Exception:  # noqa: BLE001
                pass
            await _close(ws)

    return router


async def _say(ws: WebSocket, message: dict) -> None:
    try:
        await ws.send_json(message)
    except Exception:  # noqa: BLE001
        pass


async def _close(ws: WebSocket) -> None:
    try:
        await ws.close()
    except Exception:  # noqa: BLE001
        pass
