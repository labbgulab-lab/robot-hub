"""Furhat: the hub puts it on an English voice before it speaks."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.adapters import furhat as F  # noqa: E402

GREGORY = F.DEFAULT_VOICE
SAKURA = "Sakura22k_HQ (ja-JP) - Acapela"


class _FakeBus:
    """Answers RequestVoice from `voice`/`voices`; records every request."""

    def __init__(self, voice, voices, saves=True):
        self.voice, self.voices, self.saves = voice, voices, saves
        self.sent = []

    async def request(self, event, expect, timeout_s):
        self.sent.append(event)
        if event["event_name"] == F.EV_VOICE_REQUEST:
            return {"voice": self.voice,
                    "voiceList": [{"uniqueName": v} for v in self.voices]}
        if event["event_name"] == F.EV_CONFIG_VOICE:
            if self.saves:
                self.voice = event["name"]
            return {"successfulSave": self.saves}
        return None


class _Settings:
    def __init__(self, settings):
        self.settings = settings


class _Config:
    def __init__(self, settings=None):
        self._settings = settings or {}

    def robot(self, _type_id):
        return _Settings(self._settings)

    def secret(self, _name, default=""):
        return default


def _adapter(settings=None):
    found = F.Found(type_id="furhat", address="172.20.10.10")
    return F.FurhatAdapter(found, _Config(settings))


def test_a_japanese_boot_voice_is_switched_to_english():
    a = _adapter()
    bus = _FakeBus(SAKURA, [SAKURA, GREGORY, F.FALLBACK_VOICE])
    asyncio.run(a._ensure_voice(bus))
    assert bus.voice == GREGORY
    assert any("voice set to" in n for n in a.notes)


def test_cloud_voices_not_loaded_yet_falls_back_to_built_in_english():
    a = _adapter()
    bus = _FakeBus(SAKURA, [SAKURA, F.FALLBACK_VOICE])     # no Polly yet
    asyncio.run(a._ensure_voice(bus))
    assert bus.voice == F.FALLBACK_VOICE


def test_already_on_the_voice_sends_no_change():
    a = _adapter()
    bus = _FakeBus(GREGORY, [GREGORY])
    asyncio.run(a._ensure_voice(bus))
    assert [e["event_name"] for e in bus.sent] == [F.EV_VOICE_REQUEST]


def test_the_configured_voice_wins():
    a = _adapter({"voice": "Matthew-Neural (en-US) - Amazon Polly"})
    bus = _FakeBus(SAKURA, [SAKURA, GREGORY, "Matthew-Neural (en-US) - Amazon Polly"])
    asyncio.run(a._ensure_voice(bus))
    assert bus.voice == "Matthew-Neural (en-US) - Amazon Polly"


def test_every_event_carries_the_login_session():
    bus = F.StudioBus("172.20.10.10", "pw")
    sent = []

    class _WS:
        async def send(self, raw):
            sent.append(json.loads(raw))

    bus._ws = _WS()
    bus.session_id = "_abc"
    asyncio.run(bus.send({"event_name": F.EV_CONFIG_VOICE, "name": GREGORY}))
    assert sent[0]["event_sessionId"] == "_abc"
