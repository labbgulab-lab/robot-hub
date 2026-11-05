"""Is this key any good? One free call per provider (STUDENT-APP-PLAN 3).

Every check is a read-only listing call that costs nothing:

    OpenAI      GET  https://api.openai.com/v1/models            Bearer
    Gemini      GET  .../v1beta/models                            x-goog-api-key
    OpenRouter  GET  https://openrouter.ai/api/v1/key             Bearer (gives limit_remaining)
    ElevenLabs  GET  https://api.elevenlabs.io/v1/user/subscription  xi-api-key
    Qwen        GET  .../compatible-mode/v1/models                Bearer

The answer is a status:

    {"state": "works" | "bad" | "no_credit" | "offline" | "unknown" | "checking",
     "detail": short sentence, "credit": {"left", "limit", "unit"} | None,
     "checked_at": epoch seconds}

A network error never marks a key bad: it is "offline" and the key stays as
it was. The HTTP layer is injectable (`Transport`), so tests never touch the
network, and nothing here runs at import.
"""

from __future__ import annotations

import re
import time
from typing import Any, Awaitable, Callable, Optional

# (status code, parsed JSON or text). Raises Offline when nothing answered.
Transport = Callable[[str, dict], Awaitable["tuple[int, Any]"]]

STATES = ("works", "bad", "no_credit", "offline", "unknown", "checking")
TIMEOUT_S = 10.0

OPENAI_MODELS = "https://api.openai.com/v1/models"
GEMINI_MODELS = "https://generativelanguage.googleapis.com/v1beta/models"
OPENROUTER_KEY = "https://openrouter.ai/api/v1/key"
ELEVEN_SUBSCRIPTION = "https://api.elevenlabs.io/v1/user/subscription"
# DashScope keys belong to one region; the international one first.
QWEN_MODELS = ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
               "https://dashscope.aliyuncs.com/compatible-mode/v1/models")

PROVIDER_NAMES = {"gpt": "OpenAI", "gemini": "Gemini", "openrouter": "OpenRouter",
                  "elevenlabs": "ElevenLabs", "qwen": "Qwen"}


class Offline(Exception):
    """No answer at all: no internet, DNS, a timeout, a blocked host."""


async def httpx_transport(url: str, headers: dict) -> "tuple[int, Any]":
    import httpx
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
    except (httpx.TransportError, OSError) as exc:
        raise Offline(str(exc) or type(exc).__name__) from exc
    try:
        body: Any = resp.json()
    except ValueError:
        body = resp.text[:2000]
    return resp.status_code, body


# ------------------------------------------------------------------ keys
def clean(raw: str) -> str:
    """Strip what a copy-paste brings along: quotes, "Bearer ", spaces,
    "OPENAI_API_KEY=" in front."""
    text = (raw or "").strip()
    text = re.sub(r"^[A-Z_]*API_KEY\s*=\s*", "", text)
    text = text.strip().strip("'\"` ").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    return re.sub(r"\s+", "", text)


def detect(key: str) -> list[str]:
    """Providers this key could belong to, by its prefix; [] = ask."""
    if key.startswith("sk-or-"):
        return ["openrouter"]
    if key.startswith("sk_"):
        return ["elevenlabs"]
    if key.startswith("AIza"):
        return ["gemini"]
    if key.startswith("sk-"):
        # DashScope (Qwen) keys are sk- too; OpenAI is far more common here.
        return ["gpt", "qwen"]
    return []


def looks_like_a_key(key: str) -> bool:
    return 16 <= len(key) <= 300 and bool(re.fullmatch(r"[A-Za-z0-9_\-.:]+", key))


# ---------------------------------------------------------------- status
def status(state: str, detail: str = "", credit: Optional[dict] = None,
           when: Optional[float] = None) -> dict[str, Any]:
    return {"state": state, "detail": detail, "credit": credit,
            "checked_at": time.time() if when is None else when}


def _text(body: Any) -> str:
    if isinstance(body, (dict, list)):
        import json
        return json.dumps(body)
    return str(body or "")


def _money(value: float) -> str:
    return "${:,.2f}".format(value).replace(".00", "")


async def check(provider: str, key: str,
                transport: Optional[Transport] = None) -> dict[str, Any]:
    """The key's status now. Never raises."""
    get = transport or httpx_transport
    name = PROVIDER_NAMES.get(provider, provider)
    try:
        if provider == "gpt":
            return _openai(*await get(OPENAI_MODELS, {"Authorization": "Bearer " + key}))
        if provider == "gemini":
            return _gemini(*await get(GEMINI_MODELS, {"x-goog-api-key": key}))
        if provider == "openrouter":
            return _openrouter(*await get(OPENROUTER_KEY, {"Authorization": "Bearer " + key}))
        if provider == "elevenlabs":
            return _eleven(*await get(ELEVEN_SUBSCRIPTION, {"xi-api-key": key}))
        if provider == "qwen":
            result = status("bad", "Qwen refused this key.")
            for url in QWEN_MODELS:
                result = _qwen(*await get(url, {"Authorization": "Bearer " + key}))
                if result["state"] != "bad":
                    break
            return result
    except Offline:
        return status("offline", "Can't reach {} from this network.".format(name))
    except Exception as exc:  # noqa: BLE001  (a parser surprise is not a bad key)
        return status("unknown", "Could not check: {}".format(str(exc)[:120] or type(exc).__name__))
    return status("unknown", "No check for {} keys.".format(name))


def _generic(code: int, body: Any, name: str) -> dict[str, Any]:
    if code == 200:
        return status("works", "Works.")
    if code in (401, 403):
        return status("bad", "{} refused this key.".format(name))
    if code == 429:
        return status("unknown", "{} is busy. Try again in a minute.".format(name))
    return status("unknown", "{} answered {}.".format(name, code))


def _openai(code: int, body: Any) -> dict[str, Any]:
    text = _text(body)
    if code == 429 and "insufficient_quota" in text:
        return status("no_credit", "This OpenAI key has no credit.")
    if code == 401:
        return status("bad", "OpenAI refused this key.")
    if code == 403 and "region" in text.lower():
        return status("unknown", "OpenAI is not available on this network.")
    # A key with $0 still lists models; "no credit" shows at first use.
    return _generic(code, body, "OpenAI")


def _gemini(code: int, body: Any) -> dict[str, Any]:
    text = _text(body)
    if code == 400 and ("API_KEY_INVALID" in text or "API key not valid" in text):
        return status("bad", "Google refused this key.")
    if code == 403:
        if "SERVICE_DISABLED" in text or "has not been used" in text:
            return status("bad", "This Google key has the Gemini API turned off.")
        return status("bad", "Google refused this key.")
    if code == 429:
        return status("works", "Works, but it is at its limit right now.")
    return _generic(code, body, "Gemini")


def _openrouter(code: int, body: Any) -> dict[str, Any]:
    if code == 200 and isinstance(body, dict):
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        limit = data.get("limit")
        left = data.get("limit_remaining")
        if left is None and limit is not None and data.get("usage") is not None:
            try:
                left = float(limit) - float(data["usage"])
            except (TypeError, ValueError):
                left = None
        if left is None:
            return status("works", "Works. No spending limit set.")
        left = float(left)
        credit = {"left": round(left, 2), "limit": None if limit is None else float(limit),
                  "unit": "usd"}
        if left <= 0:
            return status("no_credit", "This OpenRouter key has no credit left.", credit)
        detail = "{} left".format(_money(left))
        if limit is not None:
            detail += " of {}".format(_money(float(limit)))
        return status("works", detail + ".", credit)
    return _generic(code, body, "OpenRouter")


def _eleven(code: int, body: Any) -> dict[str, Any]:
    text = _text(body)
    if code == 200 and isinstance(body, dict):
        try:
            used = int(body.get("character_count") or 0)
            limit = int(body.get("character_limit") or 0)
        except (TypeError, ValueError):
            return status("works", "Works.")
        left = max(limit - used, 0)
        credit = {"left": left, "limit": limit, "unit": "characters"}
        if limit and left <= 0:
            return status("no_credit", "This ElevenLabs key has no characters left.", credit)
        return status("works", "{:,} characters left.".format(left), credit)
    if code == 401:
        # "Out of credit" is a 401 too, so the body decides.
        if "quota_exceeded" in text:
            return status("no_credit", "This ElevenLabs key has no characters left.")
        if "missing_permissions" in text:
            return status("works", "Works. This key can't show its credit.")
        return status("bad", "ElevenLabs refused this key.")
    return _generic(code, body, "ElevenLabs")


def _qwen(code: int, body: Any) -> dict[str, Any]:
    if code == 401 or code == 403:
        return status("bad", "Qwen refused this key.")
    return _generic(code, body, "Qwen")
