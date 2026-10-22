"""Routes of the group conversation page (Contract 2 in docs/GROUP-CONVERSATION.md)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .conductor import GroupManager

log = logging.getLogger("hub.group.api")


def make_router(group: GroupManager) -> APIRouter:
    router = APIRouter()

    def reply(result: dict) -> JSONResponse:
        return JSONResponse(result, status_code=200 if result.get("ok") else 409)

    @router.get("/api/group/state")
    async def get_state() -> dict[str, Any]:
        await group.ensure_voices()
        return group.state()

    @router.put("/api/group/config")
    async def put_config(body: dict = Body(...)) -> JSONResponse:
        result = group.save_config(body)
        if not result.get("ok"):
            return reply(result)
        return JSONResponse(group.state())

    @router.post("/api/group/start")
    async def post_start(body: dict = Body(default={})) -> JSONResponse:
        """{"mode": "group" | "interrupt"}; also switches a running one."""
        await group.ensure_voices()
        return reply(await group.start(str((body or {}).get("mode") or "group")))

    @router.post("/api/group/stop")
    async def post_stop() -> JSONResponse:
        """Stop talking; the robots stay connected for the next start."""
        return reply(await group.stop())

    @router.post("/api/group/disconnect")
    async def post_disconnect() -> JSONResponse:
        return reply(await group.disconnect())

    @router.post("/api/group/loudness")
    async def post_loudness(body: dict = Body(...)) -> JSONResponse:
        """{"key": robot key, "loudness": 0-250 (% of natural level)}; live."""
        return reply(group.set_loudness(str(body.get("key", "")), body.get("loudness")))

    @router.post("/api/group/mic")
    async def post_mic(body: dict = Body(...)) -> JSONResponse:
        """{"use": "robots" | "people"}: who hears the people, at once, also
        mid-conversation (the robots' mics wait ready behind the DJI)."""
        return reply(await group.switch_mic(str((body or {}).get("use", ""))))

    @router.post("/api/group/ready")
    async def post_ready() -> JSONResponse:
        """Connect the robots and warm every service, so Start is instant."""
        return reply(await group.get_ready())

    @router.post("/api/group/nudge")
    async def post_nudge(body: dict = Body(...)) -> JSONResponse:
        return reply(group.nudge(str(body.get("text", ""))))

    @router.websocket("/ws/group")
    async def ws_group(ws: WebSocket) -> None:
        await ws.accept()
        queue = group.subscribe()
        try:
            await group.ensure_voices()
            await ws.send_json({"type": "group.state", **group.state()})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    await ws.send_json({"type": "heartbeat"})
                    continue
                await ws.send_json(event)
        except WebSocketDisconnect:
            pass
        except Exception as exc:  # noqa: BLE001
            log.info("group websocket closed: %s", exc)
        finally:
            group.unsubscribe(queue)

    return router
