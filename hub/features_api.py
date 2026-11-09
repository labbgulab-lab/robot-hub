"""Routes for keys, setup, the network and the robot details (BUILD-PLAN
"Hub API contract").

    GET    /api/keys                          keys with status, used_by, flags
    POST   /api/keys          {key, provider?: "auto", label?}   tests, then saves
    POST   /api/keys/{id}/check               the free test call, now
    DELETE /api/keys/{id}
    PUT    /api/robots/{key}/key  {key_id: id|null, slot: "main"|"voice"}

    GET    /api/setup                         {items: [...]}
    POST   /api/setup/{id}/{download|cancel|check|choose_zip|open}

    GET    /api/network                       the network state
    POST   /api/network/open_wifi_settings    Windows' WiFi settings

    GET    /api/robots/{key}                  the full card, with facts
    POST   /api/robots/{key}/wifi  {ssid, password?, open?, save_only?}
    GET    /api/robots/{key}/wifi             the WiFi networks the robot knows

Errors are {"error": sentence, "code": CODE} with a 4xx status (plus
"ok": false, which the old page reads).
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from typing import Any, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .core import ActionError
from .requirements import SetupError


def _error(message: str, code: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message, "code": code, **extra},
                        status_code=status)


async def _body(request: Request) -> Optional[dict[str, Any]]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return None
    return body if isinstance(body, dict) else None


def open_wifi_settings() -> None:
    if sys.platform == "win32":
        os.startfile("ms-settings:network-wifi")  # type: ignore[attr-defined]
    elif sys.platform == "darwin":  # pragma: no cover
        # macOS 13+ opens the Wi-Fi pane; an older one opens System Preferences.
        subprocess.Popen(["open", "x-apple.systempreferences:com.apple.wifi-settings-extension"])
    else:  # pragma: no cover
        subprocess.Popen(["xdg-open", "settings://network"])


# ------------------------------------------------- the WiFi a robot knows
# Add WiFi's "Knows:" line. Read over the robot's own SSH (the adapter's
# remote_shell), never written. Reachy: NetworkManager profiles. NAO and
# Pepper: connman's saved ("favorite") services.
NMCLI_KNOWN = ("nmcli -t -f NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY,ACTIVE "
               "connection show")
CONNMAN_KNOWN = "connmanctl services"
SETUP_NETWORKS = ("reachy-mini-ap", "Hotspot")
LAB_FALLBACK_PRIORITY = -10


def _nm_fields(line: str) -> list[str]:
    """nmcli -t: fields split on ':'; a ':' inside a field comes as '\\:'."""
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in parts]


def parse_nmcli_known(output: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in (output or "").splitlines():
        fields = _nm_fields(line.strip())
        if len(fields) < 5 or fields[1] != "802-11-wireless" or not fields[0]:
            continue
        name, _type, auto, prio, active = fields[:5]
        try:
            priority = int(prio)
        except ValueError:
            priority = 0
        note = None
        if name in SETUP_NETWORKS:
            note = "its own setup network"
        elif auto.lower() == "no":
            note = "won't join by itself"
        elif priority <= LAB_FALLBACK_PRIORITY:
            note = "lab WiFi fallback"
        out.append({"ssid": name, "current": active.lower() == "yes", "note": note})
    out.sort(key=lambda n: (not n["current"], n["note"] == "its own setup network"))
    return out


def parse_connman_known(output: str) -> list[dict[str, Any]]:
    """`connmanctl services`: '*AO Name   wifi_..._managed_psk'. '*' = saved,
    'O'/'R' = connected now. Only saved WiFi services are listed."""
    out: list[dict[str, Any]] = []
    for line in (output or "").splitlines():
        if len(line) < 5 or not line.startswith("*"):
            continue
        flags, rest = line[:4], line[4:].strip()
        bits = rest.rsplit(None, 1)
        if len(bits) != 2 or not bits[1].startswith("wifi_"):
            continue
        name = bits[0].strip()
        if not name:
            continue
        auto = "A" in flags
        out.append({"ssid": name, "current": ("O" in flags or "R" in flags),
                    "note": None if auto else "won't join by itself"})
    out.sort(key=lambda n: not n["current"])
    return out


def make_router(hub: Any, *,
                wifi_opener: Callable[[], None] = open_wifi_settings) -> APIRouter:
    router = APIRouter()

    # ------------------------------------------------------------- keys
    # Secrets come in here and never go back out: every response is the
    # public view (label + last four characters + status).
    @router.get("/api/keys")
    async def get_keys() -> dict[str, Any]:
        return hub.keys_event()

    @router.post("/api/keys", response_model=None)
    async def post_key(request: Request):
        body = await _body(request)
        if body is None or not isinstance(body.get("key"), str):
            return _error("Paste the key.", "NOT_A_KEY")
        try:
            return await hub.add_key(str(body.get("provider") or "auto"),
                                     str(body.get("label") or ""), body["key"])
        except ActionError as exc:
            return JSONResponse(exc.body(), status_code=exc.status)

    @router.post("/api/keys/{key_id}/check", response_model=None)
    async def post_key_check(key_id: str):
        try:
            return await hub.check_key(key_id)
        except ActionError as exc:
            return JSONResponse(exc.body(), status_code=exc.status)

    @router.delete("/api/keys/{key_id}", response_model=None)
    async def delete_key(key_id: str):
        try:
            return hub.remove_key(key_id)
        except ActionError as exc:
            return JSONResponse(exc.body(), status_code=exc.status)

    @router.put("/api/robots/{key}/key", response_model=None)
    async def put_robot_key(key: str, request: Request):
        body = await _body(request)
        if body is None:
            return _error("Pick a key.", "BAD_SLOT")
        key_id = body.get("key_id")
        if key_id is not None and not isinstance(key_id, str):
            return _error("Pick a key.", "UNKNOWN_KEY")
        try:
            return hub.assign_key(key, key_id or None, str(body.get("slot") or "main"))
        except ActionError as exc:
            return JSONResponse(exc.body(), status_code=exc.status)

    # ------------------------------------------------------------ setup
    @router.get("/api/setup")
    async def get_setup() -> dict[str, Any]:
        return {"items": hub.setup.items()}

    @router.post("/api/setup/{item_id}/{action}", response_model=None)
    async def post_setup(item_id: str, action: str):
        try:
            item = await hub.setup.act(item_id, action)
        except SetupError as exc:
            return _error(str(exc), exc.code, exc.status)
        return {"ok": True, "item": item}

    # ---------------------------------------------------------- network
    @router.get("/api/network")
    async def get_network() -> dict[str, Any]:
        try:
            return await hub.refresh_network()
        except Exception:  # noqa: BLE001  (a failed read keeps the last answer)
            return hub.network

    @router.post("/api/network/open_wifi_settings", response_model=None)
    async def post_open_wifi():
        try:
            await asyncio.to_thread(wifi_opener)
        except Exception as exc:  # noqa: BLE001
            hub.bus.emit_log("warn", "could not open the WiFi settings: {}".format(exc))
            return _error("Could not open the WiFi settings.", "OPEN_FAILED", 500)
        return {"ok": True}

    # ----------------------------------------------------------- robots
    @router.get("/api/robots/{key}", response_model=None)
    async def get_robot(key: str):
        card = hub.robot_detail(key)
        if card is None:
            return _error("There is no robot called {}.".format(key), "UNKNOWN_ROBOT", 404)
        return card

    @router.post("/api/robots/{key}/wifi", response_model=None)
    async def post_wifi(key: str, request: Request):
        body = await _body(request)
        if body is None or not isinstance(body.get("ssid"), str):
            return _error("a WiFi name has 1 to 32 characters", "BAD_WIFI")
        password = body.get("password")
        if password is not None and not isinstance(password, str):
            return _error("a WiFi password has 8 to 63 characters", "BAD_WIFI")
        save_only = bool(body.get("save_only") or body.get("lab"))
        result = await hub.join_wifi(key, body["ssid"], password or "",
                                     lab=save_only, open_network=bool(body.get("open")))
        return JSONResponse(result, status_code=200 if result.get("ok") else 409)

    @router.get("/api/robots/{key}/wifi", response_model=None)
    async def get_known_wifi(key: str):
        r = hub.registry.get(key)
        adapter = hub.adapters.get(key)
        if r is None:
            return _error("There is no robot called {}.".format(key), "UNKNOWN_ROBOT", 404)
        shell = getattr(adapter, "remote_shell", None) if adapter is not None else None
        if shell is None or not hasattr(adapter, "join_wifi"):
            return {"ok": True, "supported": False, "networks": []}
        reachy = r.type_id == "reachy_wireless"
        try:
            status, output = await shell(NMCLI_KNOWN if reachy else CONNMAN_KNOWN, 10.0)
        except Exception as exc:  # noqa: BLE001
            return _error("Couldn't ask {}: {}".format(r.name, exc), "NET_UNREACHABLE", 409)
        if status != 0:
            return _error("{} didn't list its WiFi.".format(r.name), "NET_UNREACHABLE", 409)
        networks = parse_nmcli_known(output) if reachy else parse_connman_known(output)
        return {"ok": True, "supported": True, "networks": networks}

    return router
