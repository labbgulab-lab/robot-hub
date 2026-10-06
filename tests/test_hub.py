"""Hub tests that need no hardware.

Phase 0's acceptance criteria plus the arbitration rules, because those are
the parts that must keep working when nobody has a robot plugged in.

    .venv/Scripts/python.exe -m pytest tests -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.adapters.base import Claim, Found  # noqa: E402
from hub.config import load_config  # noqa: E402
from hub.core import Hub  # noqa: E402
from hub.events import EventBus  # noqa: E402
from hub.ports import PortAllocator, is_free  # noqa: E402
from hub.registry import ABSENT, CONNECTED, Registry  # noqa: E402
from hub.resources import ConflictError, ResourceBroker  # noqa: E402


@pytest.fixture
def config():
    return load_config()


# ------------------------------------------------------------------ phase 0
def test_five_dim_cards_before_any_robot(config):
    hub = Hub(config)
    snap = hub.snapshot()
    assert len(snap["robots"]) == 5
    assert {r["type_id"] for r in snap["robots"]} == {
        "furhat", "reachy_wireless", "reachy_lite", "naoqi", "pepper"}
    assert all(r["state"] == ABSENT for r in snap["robots"])


def test_page_and_websocket(config):
    from fastapi.testclient import TestClient
    from hub import main

    with TestClient(main.app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/robots").json()["robots"]
        with client.websocket_connect("/ws") as ws:
            first = ws.receive_json()
            assert first["type"] == "snapshot"
            assert len(first["robots"]) == 5


# ------------------------------------------------------------------ registry
def test_registry_publishes_only_on_change():
    bus = EventBus()
    q = bus.subscribe()
    reg = Registry(bus)
    reg.upsert("k", type_id="furhat", name="Furhat")
    reg.set_state("k", CONNECTED, "connected")
    n = q.qsize()
    reg.set_state("k", CONNECTED, "connected")
    assert q.qsize() == n, "a no-op state write should not wake every browser"


# ------------------------------------------------------------------- ports
def test_allocator_avoids_and_bind_tests(config):
    alloc = PortAllocator(config)
    got = {alloc.allocate("a") for _ in range(5)}
    assert len(got) == 5
    assert not got & set(config.ports.avoid)
    assert all(config.ports.range_start <= p <= config.ports.range_end for p in got)
    alloc.release_owner("a")


def test_is_free_says_no_for_a_bound_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert is_free(port) is False
    finally:
        s.close()


# -------------------------------------------------------------- arbitration
def _claim(kind, value, mode="require") -> Claim:
    return {"kind": kind, "value": value, "mode": mode}


def test_second_mic_claim_is_refused_and_names_the_holder(config):
    broker = ResourceBroker(EventBus(), config)
    broker.acquire("reachy", "Reachy-Mini", [_claim("audio_in", "Microphone (USBAudio1.0)")])
    with pytest.raises(ConflictError) as exc:
        broker.acquire("nao", "NAOqi", [_claim("audio_in", "Microphone (USBAudio1.0)")])
    assert "Reachy-Mini" in str(exc.value), "the message must name who is holding it"
    assert "USBAudio1.0" in str(exc.value)


def test_override_proceeds(config):
    broker = ResourceBroker(EventBus(), config)
    broker.acquire("reachy", "Reachy-Mini", [_claim("audio_in", "K11")])
    broker.acquire("nao", "NAOqi", [_claim("audio_in", "K11")], override=True)


def test_release_frees_the_device(config):
    broker = ResourceBroker(EventBus(), config)
    broker.acquire("reachy", "Reachy-Mini", [_claim("audio_in", "K11")])
    broker.release_all("reachy")
    broker.acquire("nao", "NAOqi", [_claim("audio_in", "K11")])


def test_default_sentinel_resolves_to_a_concrete_name(config):
    """A claim on the string "default" collides silently; a claim on a real
    device name collides visibly. This is the whole point of 7.2."""
    broker = ResourceBroker(EventBus(), config)
    resolved = broker.resolve(_claim("audio_in", ""))
    assert resolved != "audio_in:"
    assert resolved != "audio_in:default"


def test_exclusive_modes_conflict(config):
    """Reachy-Lite requires the desktop app; reachy_chat requires it absent."""
    broker = ResourceBroker(EventBus(), config)
    broker.acquire("lite", "Reachy-Mini-Lite",
                   [_claim("exclusive", "reachy_desktop_app", "require")])
    with pytest.raises(ConflictError):
        broker.acquire("wireless", "Reachy-Mini",
                       [_claim("exclusive", "reachy_desktop_app", "require_absent")])


# --------------------------------------------------------------- resilience
def test_unknown_robot_actions_do_not_raise(config):
    hub = Hub(config)
    for coro in (hub.connect("nope"), hub.disconnect("nope"), hub.launch("nope")):
        assert asyncio.run(_first(coro))["ok"] is False


async def _first(coro):
    return await coro


def test_network_loss_says_so(config):
    hub = Hub(config)
    hub._on_network({"on_robot_subnet": False, "interfaces": ["10.0.0.5/24"]})
    text = " ".join(e["text"] for e in hub.bus.recent() if e["type"] == "log")
    assert "not on the robots" in text or "no longer on the robots" in text


def test_found_never_keys_on_an_address():
    f = Found(type_id="reachy_wireless", address="172.20.10.10",
              meta={"unit_id": "58b3b6a4bf81179a"})
    assert f.txt("unit_id") == "58b3b6a4bf81179a"
    assert f.address not in f.txt("unit_id")


# ------------------------------------------------------------------ launch
class _FakeAdapter:
    """Just enough of an adapter for Hub.launch."""

    def __init__(self, launch):
        self._launch = launch

    def claims(self):
        return []

    async def ensure_zero_instances(self):
        return []

    async def launch(self):
        return await self._launch()

    async def disconnect(self):
        pass


def _connected_hub(config, launch):
    hub = Hub(config)
    hub.registry.upsert("fake", type_id="naoqi", name="Fake")
    hub.registry.set_state("fake", CONNECTED)
    hub.adapters["fake"] = _FakeAdapter(launch)
    return hub


def test_launch_marks_the_card_while_it_runs(config):
    seen = {}

    async def launch():
        seen["since"] = hub.registry.get("fake").launching_since
        return "http://robot/"

    hub = _connected_hub(config, launch)
    hub.registry.upsert("fake", launch_error="old failure")
    assert asyncio.run(_first(hub.launch("fake")))["url"] == "http://robot/"
    r = hub.registry.get("fake")
    assert seen["since"] is not None              # set before the adapter ran
    assert r.launching_since is None and r.launch_error is None
    assert r.to_event()["launching_since"] is None   # the page sees it too


def test_failed_launch_keeps_the_reason_on_the_card(config):
    async def launch():
        raise asyncio.TimeoutError()              # empty message, like wait_for

    hub = _connected_hub(config, launch)
    result = asyncio.run(_first(hub.launch("fake")))
    r = hub.registry.get("fake")
    assert result == {"ok": False, "error": "timed out"}
    assert r.launch_error == "timed out" and r.launching_since is None
    asyncio.run(_first(hub.disconnect("fake")))
    assert hub.registry.get("fake").launch_error is None


def test_disconnect_cancels_a_launch_in_flight(config):
    # 2026-10-05: a Disconnect during Launch used to run beside it -- and its
    # cleanup cleared the busy flag, so a second Launch could start too.
    started = asyncio.Event()

    async def launch():
        started.set()
        await asyncio.sleep(60)                   # a robot that never answers
        return "http://robot/"

    hub = _connected_hub(config, launch)

    async def scenario():
        pending = asyncio.create_task(hub.launch("fake"))
        await started.wait()
        await hub.disconnect("fake")
        return await asyncio.wait_for(pending, 5)

    result = asyncio.run(_first(scenario()))
    assert result == {"ok": False, "error": "cancelled by Disconnect"}
    assert "fake" not in hub._busy and "fake" not in hub._launches
    assert hub.registry.get("fake").launching_since is None


def test_a_failed_connect_is_not_promoted_to_connected(config):
    # 2026-10-05: Furhat's first auto-connect failed (just booted), the next
    # healthy probe turned the card CONNECTED, and Launch ran on a robot that
    # had never logged in, spoken or had its voice set.
    from hub.registry import ERROR

    class _Refuses(_FakeAdapter):
        async def connect(self):
            raise RuntimeError("Studio never answered the login")

    config.auto_connect = False
    hub = Hub(config)
    hub.registry.upsert("fake", type_id="furhat", name="Fake")
    hub.adapters["fake"] = _Refuses(None)

    result = asyncio.run(_first(hub.connect("fake")))
    assert result["ok"] is False
    hub._apply_health("fake", {"online": True, "detail": "Studio is serving"})
    assert hub.registry.get("fake").state == ERROR
    assert asyncio.run(_first(hub.launch("fake")))["error"] == "connect first"


def test_a_robot_taking_another_cards_address_evicts_that_card(config):
    # reachy2 off, reachy3 on reachy2's old address: reachy2's card must not
    # stay green on reachy3's answers.
    config.auto_connect = False
    hub = Hub(config)
    hub.registry.upsert("unit-2", type_id="reachy_wireless", name="reachy2",
                        address="172.20.10.2", system_url="http://172.20.10.2:8765/")
    hub.registry.set_state("unit-2", "RUNNING")
    hub._connected_at["unit-2"] = 1.0
    hub._evict_address("unit-3", "reachy3", "172.20.10.2")
    r2 = hub.registry.get("unit-2")
    assert r2.state == ABSENT and r2.address is None and r2.system_url is None
    assert "unit-2" not in hub._connected_at
