"""The Reachy app's backend: the reachy_chat proxy and relay, transcripts,
the Wizard of Oz quick-save setting, and the /group.html redirect."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from hub import settings as S
from hub.events import EventBus
from hub.reachy_proxy import app_base, make_router, read_timeout
from hub.registry import Registry
from hub.transcripts import TranscriptStore, make_router as make_transcripts_router


# ------------------------------------------------------------------ helpers
def fake_hub():
    registry = Registry(EventBus())
    registry.upsert("reachy:a1", type_id="reachy_wireless", name="reachy3",
                    address="10.0.4.23", state="RUNNING",
                    system_url="http://10.0.4.23:8765/")
    registry.upsert("reachy:b2", type_id="reachy_wireless", name="reachy6",
                    address="10.0.4.24", state="CONNECTED")
    registry.upsert("reachy:none", type_id="reachy_wireless", name="reachy9")
    registry.upsert("pepper:p1", type_id="pepper", name="Pepper", address="10.0.4.40")
    return SimpleNamespace(registry=registry)


def proxy_app(handler=None, ws_connect=None, transcripts=None):
    app = FastAPI()
    transport = httpx.MockTransport(handler) if handler else None
    app.include_router(make_router(fake_hub(), transport=transport,
                                   ws_connect=ws_connect, transcripts=transcripts))
    return TestClient(app)


# -------------------------------------------------------------------- proxy
def test_app_base_prefers_the_launched_url():
    r = SimpleNamespace(system_url="http://10.0.4.23:8765/", address="10.9.9.9")
    assert app_base(r) == "http://10.0.4.23:8765"
    assert app_base(SimpleNamespace(system_url=None, address="10.0.4.24")) == "http://10.0.4.24:8765"
    assert app_base(SimpleNamespace(system_url=None, address=None)) is None


def test_slow_routes_get_longer_timeouts():
    assert read_timeout("status") == 15.0
    assert read_timeout("show/rebuild") == 300.0
    assert read_timeout("show/cue/abc") == 60.0
    assert read_timeout("system/start") == 45.0


def test_get_and_query_pass_through():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        return httpx.Response(200, json={"voices": [{"voice_id": "v1"}]})

    client = proxy_app(handler)
    res = client.get("/api/reachy/reachy:a1/backend/elevenlabs/voices?refresh=true")
    assert res.status_code == 200
    assert res.json() == {"voices": [{"voice_id": "v1"}]}
    assert seen["url"] == "http://10.0.4.23:8765/api/backend/elevenlabs/voices?refresh=true"
    assert seen["method"] == "GET"


def test_put_body_and_upstream_errors_pass_through():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        seen["type"] = request.headers.get("content-type")
        return httpx.Response(400, json={"error": "rejected", "detail": "too long"})

    client = proxy_app(handler)
    res = client.put("/api/reachy/reachy:a1/persona", json={"overlay": "x" * 2000})
    assert res.status_code == 400
    assert res.json()["detail"] == "too long"
    assert seen["body"] == {"overlay": "x" * 2000}
    assert seen["type"] == "application/json"


def test_delete_and_post_without_body():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path.decode(), request.content))
        return httpx.Response(200, json={"ok": True})

    client = proxy_app(handler)
    assert client.delete("/api/reachy/reachy:a1/show/cue/c%201").status_code == 200
    assert client.post("/api/reachy/reachy:a1/show/stop").status_code == 200
    assert calls[0][0] == "DELETE" and calls[0][1] == "/api/show/cue/c%201"
    assert calls[1] == ("POST", "/api/show/stop", b"")


def test_binary_answer_passes_through():
    wav = b"RIFF\x00\x01\x02WAVEdata"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=wav, headers={"content-type": "audio/wav"})

    res = proxy_app(handler).get("/api/reachy/reachy:a1/show/audio/x.wav")
    assert res.content == wav
    assert res.headers["content-type"] == "audio/wav"


def test_robot_without_launch_uses_its_address():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        return httpx.Response(200, json={})

    proxy_app(handler).get("/api/reachy/reachy:b2/status")
    assert seen["host"] == "10.0.4.24"


def test_unknown_robot_and_not_a_reachy_are_404():
    client = proxy_app(lambda r: httpx.Response(200, json={}))
    for key in ("nobody", "pepper:p1"):
        res = client.get("/api/reachy/{}/status".format(key))
        assert res.status_code == 404
        assert res.json()["code"] == "UNKNOWN_ROBOT" and res.json()["ok"] is False


def test_app_not_up_is_409_not_running():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = proxy_app(refused)
    res = client.post("/api/reachy/reachy:a1/conversation/start")
    assert res.status_code == 409
    assert res.json() == {"error": "reachy3's app is not running.", "code": "NOT_RUNNING",
                          "ok": False}
    # No address at all: also not running.
    assert client.get("/api/reachy/reachy:none/status").json()["code"] == "NOT_RUNNING"


def test_slow_robot_is_504():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    res = proxy_app(slow).get("/api/reachy/reachy:a1/status")
    assert res.status_code == 504 and res.json()["code"] == "ROBOT_TIMEOUT"


# -------------------------------------------------------------------- relay
class FakeUpstream:
    """Stands in for the robot's /ws: sends `script`, records what it gets."""

    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self.closed = False
        self.done = asyncio.Event()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.script:
            return self.script.pop(0)
        await self.done.wait()      # stays open until the page goes
        raise StopAsyncIteration

    async def send(self, message):
        self.sent.append(message)

    async def close(self):
        self.closed = True
        self.done.set()


def test_relay_passes_both_ways_and_feeds_transcripts(tmp_path):
    upstream = FakeUpstream([
        json.dumps({"event": "conversation.started", "id": "c1", "backend": "Gemini 3.8 Live"}),
        json.dumps({"event": "transcript.robot", "turn_id": 0, "text": "Hi, I'm Reachy Mini."}),
        json.dumps({"event": "conversation.partial", "turn": 1, "who": "robot", "text": "So"}),
    ])
    urls = []

    async def connect(url):
        urls.append(url)
        return upstream

    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: True)
    client = proxy_app(ws_connect=connect, transcripts=store)
    with client.websocket_connect("/ws/reachy/reachy:a1") as ws:
        assert ws.receive_json() == {"event": "proxy.open", "key": "reachy:a1", "robot": "reachy3"}
        assert ws.receive_json()["event"] == "conversation.started"
        assert ws.receive_json()["text"] == "Hi, I'm Reachy Mini."
        assert ws.receive_json()["event"] == "conversation.partial"
        ws.send_text('{"ping": 1}')
        for _ in range(50):
            if upstream.sent:
                break
            import time
            time.sleep(0.02)
    assert urls == ["ws://10.0.4.23:8765/ws"]
    assert upstream.sent == ['{"ping": 1}']
    files = list(tmp_path.glob("talk-*-reachy3.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "[turn 0] reachy3: Hi, I'm Reachy Mini." in text
    assert "Gemini 3.8 Live" in text


def test_relay_says_not_running_when_the_robot_refuses():
    async def connect(url):
        raise OSError("refused")

    client = proxy_app(ws_connect=connect)
    with client.websocket_connect("/ws/reachy/reachy:a1") as ws:
        msg = ws.receive_json()
    assert msg["event"] == "proxy.error" and msg["code"] == "NOT_RUNNING"


def test_relay_unknown_robot():
    client = proxy_app(ws_connect=lambda url: None)
    with client.websocket_connect("/ws/reachy/ghost") as ws:
        assert ws.receive_json()["code"] == "UNKNOWN_ROBOT"


def test_relay_reports_the_robot_going_away():
    upstream = FakeUpstream([json.dumps({"event": "state.change", "state": "IDLE_BREATHING"})])

    async def connect(url):
        upstream.done.set()     # the robot closes right after its message
        return upstream

    client = proxy_app(ws_connect=connect)
    with client.websocket_connect("/ws/reachy/reachy:a1") as ws:
        assert ws.receive_json()["event"] == "proxy.open"
        assert ws.receive_json()["event"] == "state.change"
        assert ws.receive_json()["event"] == "proxy.closed"


# -------------------------------------------------------------- transcripts
def test_talk_transcript_is_idempotent_and_ends(tmp_path):
    clock = iter([1_700_000_000.0 + i for i in range(100)])
    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: True, clock=lambda: next(clock))
    ev = [
        {"event": "conversation.started", "id": "c9", "backend": "Gemini 3.8 Live · en-US"},
        {"event": "transcript.robot", "turn_id": 0, "text": "Hello!"},
        {"event": "transcript.user", "turn_id": 1, "text": "מה שלומך?"},
        {"event": "turn.aborted", "turn_id": 2, "reason": "gemini_silent"},
    ]
    for e in ev + ev[1:]:            # a second tab relays the same lines again
        store.talk_event("reachy:a1", "reachy3", e)
    assert store.status()["active"][0]["kind"] == "talk"
    store.talk_event("reachy:a1", "reachy3", {"event": "conversation.ended", "reason": "user"})
    files = list(tmp_path.glob("talk-*.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert text.count("Hello!") == 1
    assert "[turn 1] Person: מה שלומך?" in text
    assert "[turn 2] -- aborted (gemini_silent)" in text
    assert "(user)" in text
    assert store.status()["active"] == []


def test_talk_transcript_from_a_snapshot_mid_conversation(tmp_path):
    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: True)
    store.talk_event("k", "reachy1", {
        "event": "state.snapshot", "state": "CONVERSATION_RUNNING",
        "conversation": {"id": "c2", "backend": "GPT-Live-1"},
        "transcript": [{"role": "robot", "turn_id": 0, "text": "Hi"},
                       {"role": "user", "turn_id": 1, "text": "Hey"}]})
    store.talk_event("k", "reachy1", {"event": "state.snapshot", "state": "IDLE_BREATHING",
                                      "conversation": None})
    text = next(tmp_path.glob("talk-*.txt")).read_text(encoding="utf-8")
    assert "[turn 0] reachy1: Hi" in text and "[turn 1] Person: Hey" in text and "Ended" in text


def test_nothing_is_written_when_the_switch_is_off(tmp_path):
    published = []
    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: False,
                            publish=published.append)
    store.talk_event("k", "reachy1", {"event": "conversation.started", "id": "c1"})
    store.talk_event("k", "reachy1", {"event": "transcript.robot", "turn_id": 0, "text": "Hi"})
    assert list(tmp_path.iterdir()) == []
    assert store.status() == {"enabled": False, "dir": str(tmp_path), "active": []}
    assert published and published[-1]["type"] == "transcripts"


class FakeGroup:
    def __init__(self):
        self.events = []
        self.transcript = []
        self.running = False
        self._log_path = None
        self.session = None

    def publish(self, event):
        self.events.append(event)


def test_group_transcript_one_file_per_connection(tmp_path):
    published = []
    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: True,
                            publish=published.append)
    g = FakeGroup()
    store.attach_group(g)
    g._log_path = Path("logs/group-20261105-141203.jsonl")
    g.session = SimpleNamespace(seats=[{"key": "reachy:1", "name": "reachy1", "character": "Max"},
                                       {"key": "sim:1", "name": "laptop", "character": "Leo"}])
    g.running = True
    g.transcript = [{"id": 1, "kind": "note", "text": "Group talk started", "t": 0}]
    g.publish({"type": "group.turn", "turn": g.transcript[-1]})
    assert list(tmp_path.iterdir()) == []          # nothing said yet: no file
    g.transcript.append({"id": 2, "kind": "robot", "who": "reachy1", "character": "Max",
                         "text": "Welcome to Laba Lab.", "move": "intro", "t": 1.2, "cut": False})
    g.transcript.append({"id": 3, "kind": "human", "who": "people", "text": "Hello robots", "t": 44})
    g.transcript.append({"id": 4, "kind": "robot", "who": "laptop", "character": "Leo",
                         "text": "Fair, but", "move": "yes-but", "t": 50, "cut": True})
    g.publish({"type": "group.turn", "turn": g.transcript[-1]})
    assert len(g.events) == 2                      # the conductor's own publish still runs
    files = list(tmp_path.glob("group-*-reachy1-laptop1.txt"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "0:01  Max (reachy1) [intro]: Welcome to Laba Lab." in text
    assert "0:44  People: Hello robots" in text
    assert "[yes-but, cut off]: Fair, but" in text
    assert "-- Group talk started" in text
    assert store.status()["active"][0]["kind"] == "group"
    assert any(p["type"] == "transcripts" and p["active"] for p in published)

    # A new connection: a second file.
    g._log_path = Path("logs/group-20261105-150000.jsonl")
    g.transcript = [{"id": 1, "kind": "robot", "who": "reachy1", "character": "Max",
                     "text": "Again!", "t": 1}]
    g.publish({"type": "group.state"})
    assert len(list(tmp_path.glob("group-*.txt"))) == 2
    g.running = False
    g.publish({"type": "group.status", "status": {"phase": "ready"}})
    assert store.status()["active"] == []


def test_transcripts_route(tmp_path):
    store = TranscriptStore(folder=lambda: tmp_path, enabled=lambda: True)
    app = FastAPI()
    app.include_router(make_transcripts_router(store))
    body = TestClient(app).get("/api/transcripts/current").json()
    assert body == {"enabled": True, "dir": str(tmp_path), "active": []}


# ----------------------------------------------------------------- settings
def test_woz_quick_defaults_and_update(tmp_path):
    store = S.SettingsStore(tmp_path / "settings.json")
    assert store.public()["woz_quick"] == S.DEFAULT_WOZ_QUICK
    out = store.update({"woz_quick": ["  Wait,   wait! ", "", "Bye"]})
    assert out["woz_quick"] == ["Wait, wait!", "", "Bye"]
    assert S.SettingsStore(tmp_path / "settings.json").public()["woz_quick"][0] == "Wait, wait!"


@pytest.mark.parametrize("bad", [["a", "b"], "abc", ["a", "b", 3], ["a", "b", "x" * 601]])
def test_woz_quick_refuses_bad_values(tmp_path, bad):
    store = S.SettingsStore(tmp_path / "settings.json")
    with pytest.raises(S.SettingsError):
        store.update({"woz_quick": bad})
    assert store.public()["woz_quick"] == S.DEFAULT_WOZ_QUICK


# ----------------------------------------------------------------- the app
def test_main_app_serves_the_reachy_app_and_redirects_the_group_page():
    from hub.main import app
    client = TestClient(app)
    res = client.get("/group.html", follow_redirects=False)
    assert res.status_code == 307 and res.headers["location"] == "/reachy.html#group"
    page = client.get("/reachy.html")
    assert page.status_code == 200 and "reachy.js" in page.text
    assert client.get("/api/reachy/ghost/status").json()["code"] == "UNKNOWN_ROBOT"
    assert client.get("/api/transcripts/current").status_code == 200


def test_group_tab_has_the_table_wizard_of_oz_panel():
    from hub.main import app
    client = TestClient(app)
    page = client.get("/reachy.html").text
    assert 'id="gwoz"' in page and "/reachy-group-woz.js?v=" in page
    js = client.get("/reachy-group-woz.js")
    assert js.status_code == 200 and "/api/group/woz/fire" in js.text


# ------------------------------------------------- end to end, real sockets
def test_proxy_and_relay_against_a_real_upstream(tmp_path):
    """A fake reachy_chat on a real port: the default httpx client and the
    default websockets connector both reach it through the hub's routes."""
    import socket
    import threading
    import time

    import uvicorn

    upstream = FastAPI()

    @upstream.get("/api/status")
    async def status():
        return {"state": "IDLE_BREATHING"}

    @upstream.post("/api/show/say")
    async def say(body: dict):
        return {"played": True, "text": body.get("text")}

    @upstream.websocket("/ws")
    async def ws(socket_: WebSocket):
        await socket_.accept()
        await socket_.send_json({"event": "state.snapshot", "state": "IDLE_BREATHING"})
        text = await socket_.receive_text()
        await socket_.send_json({"event": "echo", "got": text})
        await socket_.close()

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(upstream, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        registry = Registry(EventBus())
        registry.upsert("reachy:x", type_id="reachy_wireless", name="reachyX", address="127.0.0.1",
                        state="RUNNING", system_url="http://127.0.0.1:{}/".format(port))
        app = FastAPI()
        app.include_router(make_router(SimpleNamespace(registry=registry)))
        client = TestClient(app)
        assert client.get("/api/reachy/reachy:x/status").json() == {"state": "IDLE_BREATHING"}
        assert client.post("/api/reachy/reachy:x/show/say", json={"text": "hi"}).json()["text"] == "hi"
        with client.websocket_connect("/ws/reachy/reachy:x") as ws:
            assert ws.receive_json()["event"] == "proxy.open"
            assert ws.receive_json()["event"] == "state.snapshot"
            ws.send_text("hello")
            assert ws.receive_json() == {"event": "echo", "got": "hello"}
            assert ws.receive_json()["event"] == "proxy.closed"
    finally:
        server.should_exit = True
        thread.join(5)
