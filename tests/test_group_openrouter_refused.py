"""2026-11-03: the OpenRouter key had expired (401 "API key expired."). Every
line paid a refused OpenRouter call before Gemini wrote it, and the warm-up
said "all ok" because the writer check fell to Gemini as well. Now a refusal
for good drops OpenRouter for the session, and the check asks OpenRouter only."""

import asyncio

import httpx
import pytest

from hub.group import services as sv

EXPIRED = '{"error":{"message":"API key expired.","code":401}}'


def services(handler, gemini="g-key"):
    s = sv.Services("", "", "google/gemini-3.5-flash-lite", [gemini] if gemini else [], "or-key")
    s.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return s


def test_expired_key_drops_openrouter_and_says_why():
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if "openrouter" in request.url.host:
            return httpx.Response(401, text=EXPIRED)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": '{"speaker": "A", "text": "hello"}'}]}}]})
    s = services(handler)
    said = []
    s.on_switch = said.append

    out = asyncio.run(s.director("sys", "user"))
    assert out["text"] == "hello"                   # Gemini stood in
    assert s.openrouter_key == "" and s.openrouter_gone == "key expired"
    assert said and "OpenRouter refused (key expired)" in said[0]
    assert "Settings, Keys" in said[0]

    calls.clear()
    asyncio.run(s.director("sys", "user"))
    assert not any("openrouter" in h for h in calls)  # no wasted call per line


def test_writer_check_fails_honestly_on_a_dead_key():
    def handler(request):
        if "openrouter" in request.url.host:
            return httpx.Response(401, text=EXPIRED)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [
            {"text": '{"ok": true}'}]}}]})
    s = services(handler)
    with pytest.raises(sv.ServiceError):
        asyncio.run(s.ping_writer("google/gemini-3.5-flash-lite"))
    with pytest.raises(sv.ServiceError, match="key expired"):
        asyncio.run(s.ping_writer("google/gemini-3.5-flash-lite"))


def test_a_passing_hiccup_keeps_openrouter():
    def handler(request):
        return httpx.Response(503, text="upstream busy")
    s = services(handler)
    assert not s.openrouter_refused(503, "upstream busy")
    assert not s.openrouter_refused(429, "rate limited, slow down")
    assert s.openrouter_key == "or-key"


def test_no_credits_counts_as_gone():
    s = services(lambda r: httpx.Response(200))
    assert s.openrouter_refused(402, '{"error":{"message":"Insufficient credits"}}')
    assert s.openrouter_gone == "no credits" and s.openrouter_key == ""


def test_kept_when_nothing_else_can_write():
    """With no Gemini key and OpenAI out, dropping OpenRouter would leave no
    writer at all: it stays, and the real error reaches the page."""
    s = services(lambda r: httpx.Response(200), gemini="")
    assert s.openrouter_refused(401, EXPIRED)
    assert s.openrouter_key == "or-key"
