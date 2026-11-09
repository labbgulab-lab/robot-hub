"""The Reachy app's backend: the reachy_chat proxy and relay, transcripts,
the Wizard of Oz quick-save setting, and the /group.html redirect."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
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


# ----------------------------------------- the Group tab's Wizard of Oz page
WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")

# A tiny fake DOM, enough to run web/reachy-group-woz.js under node and press
# keys on it. Prints one JSON object with what happened.
GWOZ_HARNESS = r"""
'use strict';
const fs = require('fs');
const vm = require('vm');
const out = {};
const calls = [];
const toasts = [];
const blurred = [];
const listeners = { keydown: [], keyup: [] };

class Node {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.dataset = {};
    this.hidden = false; this.className = ''; this._text = ''; this.on = {}; this.style = {};
    this.disabled = false; this.value = ''; this.type = ''; this.id = '';
    const self = this;
    this.classList = {
      has: (c) => self.className.split(/\s+/).includes(c),
      add: (c) => { if (!self.classList.has(c)) self.className = `${self.className} ${c}`.trim(); },
      remove: (c) => { self.className = self.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
      toggle: (c, on) => { if (on === undefined) on = !self.classList.has(c); if (on) self.classList.add(c); else self.classList.remove(c); },
      contains: (c) => self.classList.has(c),
    };
  }
  get textContent() { return this._text + this.children.map(c => (typeof c === 'string' ? c : c.textContent)).join(''); }
  set textContent(v) { this._text = String(v); this.children = []; }
  append(...xs) { xs.forEach(x => this.children.push(x)); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.on[t] = this.on[t] || []).push(f); }
  click() { (this.on.click || []).forEach(f => f({ preventDefault() {} })); }
  blur() { blurred.push(this.id || this.tagName); if (document.activeElement === this) document.activeElement = document.body; }
  focus() { document.activeElement = this; }
  all() { const r = []; this.children.forEach(c => { if (typeof c !== 'string') { r.push(c); r.push(...c.all()); } }); return r; }
  matches(sel) {
    const m = /^\[data-cue-id="(.*)"\]$/.exec(sel);
    if (m) return this.dataset.cueId === m[1];
    return sel.split('.').filter(Boolean).every(c => this.classList.has(c));
  }
  querySelectorAll(sel) { return this.all().filter(n => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const ids = {};
function make(id, tag, cls) { const n = new Node(tag || 'div'); n.id = id; if (cls) n.className = cls; ids[id] = n; return n; }
['gwoz', 'gwoz-body', 'gwoz-now', 'gwoz-count', 'gwoz-prep', 'gwoz-error', 'gwoz-board', 'gwoz-quick', 'gwoz-digits'].forEach(i => make(i));
make('gwoz-qkeys', 'span');
make('gwoz-toggle', 'button'); make('gwoz-connect', 'button'); make('gwoz-stop', 'button');
make('gwoz-target', 'select'); make('gwoz-say-form', 'form');
make('gwoz-say-text', 'input').type = 'text';
make('more-time', 'button');
make('seat-box', 'input').type = 'checkbox';
make('groups-modal', 'div', 'modal-wrap').hidden = true;
make('copy-modal', 'div', 'modal-wrap').hidden = true;
make('logs-drawer', 'div', 'drawer-wrap').hidden = true;
make('details-drawer', 'div', 'drawer-wrap').hidden = true;

const body = new Node('body');
global.window = global;
global.CSS = { escape: (s) => s };
global.document = {
  body, activeElement: body,
  getElementById: (id) => ids[id] || null,
  createElement: (tag) => new Node(tag),
  createTextNode: (t) => String(t),
  addEventListener: (type, f, capture) => { (listeners[type] = listeners[type] || []).push({ f, capture: !!capture }); },
  querySelector: (sel) => (sel.includes(':not([hidden])')
    ? Object.values(ids).find(n => (n.classList.has('modal-wrap') || n.classList.has('drawer-wrap')) && !n.hidden) || null
    : null),
};
const store = { 'reachy.group.woz.open': '1' };
global.localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
global.setInterval = () => 0;
global.clearInterval = () => {};

let state = null;
const answers = {};
const RA = global.RA = {
  arr: (v) => (Array.isArray(v) ? v : []),
  obj: (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {}),
  str: (v) => (v === null || v === undefined ? '' : String(v)),
  num: (v, f) => { const n = Number(v); return v !== null && v !== '' && v !== undefined && Number.isFinite(n) ? n : f; },
  el: (tag, cls, text) => { const n = new Node(tag); if (cls) n.className = cls; if (text !== undefined && text !== null) n.textContent = text; return n; },
  $: (id) => ids[id] || null,
  cap: (t) => { const s = RA.str(t); return s ? s[0].toUpperCase() + s.slice(1) : s; },
  toast: (m, bad) => toasts.push([m, !!bad]),
  errorText: () => 'generic',
  route: { tab: 'group' },
  hub: { settings: {}, groupLive: true },
  onHub: () => {},
  Group: { choir: () => false },
  get: async (url) => { calls.push(['GET', url]); return { ok: true, status: 200, body: state }; },
  post: async (url, payload) => {
    calls.push(['POST', url, payload]);
    return answers[url] || { ok: true, status: 200, body: { ok: true } };
  },
};

vm.runInThisContext(fs.readFileSync(process.argv[2], 'utf8'));

const tick = () => new Promise(r => setTimeout(r, 0));
const posts = () => calls.filter(c => c[0] === 'POST');
function key(type, o) {
  const ev = { key: '', code: '', repeat: false, ctrlKey: false, metaKey: false, altKey: false, target: document.activeElement,
    defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...o };
  listeners[type].forEach(l => l.f(ev));
  return ev;
}
const down = (o) => key('keydown', o);

(async () => {
  state = {
    script: { sections: [{ id: 's', title: 'תגובות (בטוח)', cues: [
      { id: 'greet', hotkey: '1', label: 'שלום', text: 'hi', ready: true, duration_s: 1 },
      { id: 'hold', hotkey: 's', label: 'Hold on', text: 'רגע', ready: true },
      { id: 'later', hotkey: '', label: 'Later', text: 'x', ready: false },
    ] }] },
    targets: [{ id: 'r1', name: 'reachy1', members: ['r1'] }, { id: 'r2', name: 'reachy2', members: ['r2'] }],
    choir: false, connected: ['r1'], note: 'could not voice later: offline',
  };
  RA.GroupWoz.init();
  out.capture = listeners.keydown.map(l => l.capture);
  out.keyup = listeners.keyup.length;
  RA.GroupWoz.onEvent({ state });
  const E = (id) => ids[id];
  out.connectShownOneMissing = !E('gwoz-connect').hidden;
  out.note = E('gwoz-error').hidden ? '' : E('gwoz-error').textContent;
  const h3 = E('gwoz-board').querySelectorAll('.gw-st')[0];
  out.titleDir = h3 && h3.attrs.dir;
  out.labelDir = E('gwoz-board').querySelectorAll('.lb').map(n => n.attrs.dir);
  const quick = E('gwoz-quick').children;
  out.quickBadges = quick.map(b => b.querySelectorAll('.dk').map(n => n.textContent).join(''));
  out.qkeys = E('gwoz-qkeys').hidden ? '' : E('gwoz-qkeys').textContent;
  out.digits = E('gwoz-digits').hidden ? '' : E('gwoz-digits').textContent;

  // Space on the last-clicked button: the outlined cue, never the button.
  E('more-time').focus();
  let ev = down({ key: ' ', code: 'Space' });
  const up = key('keyup', { key: ' ', code: 'Space' });
  await tick();
  out.spaceOnButton = { prevented: ev.defaultPrevented, upPrevented: up.defaultPrevented, blurred: blurred.includes('more-time') };
  ev = down({ key: ' ', code: 'Space', target: body });
  await tick();
  ev = down({ key: ' ', code: 'Space', target: body, repeat: true });
  await tick();
  out.fired = posts().filter(c => c[1] === '/api/group/woz/fire').map(c => c[2].cue_id);

  // A clicked cue gives focus back; a clicked quick line too.
  E('gwoz-board').querySelector('[data-cue-id="greet"]').click();
  quick[1].click();
  await tick();
  out.clickBlurs = blurred.filter(b => b === 'BUTTON').length;

  // Hebrew layout: the key's place decides.
  calls.length = 0;
  down({ key: 'ד', code: 'KeyS', target: body });
  down({ key: 'ג', code: 'KeyD', target: body });
  down({ key: 'ג', code: 'KeyD', target: body, repeat: true });
  await tick();
  out.hebrew = posts().map(c => [c[1], c[2].cue_id || c[2].text]);

  // The picker keeps its target under arrows and letters.
  calls.length = 0;
  E('gwoz-target').value = 'r2';
  E('gwoz-target').on.change[0]();
  out.pickerBlurOnChange = blurred.includes('gwoz-target');
  E('gwoz-target').focus();
  ev = down({ key: 'ArrowDown', code: 'ArrowDown' });
  const ev2 = down({ key: 'ר', code: 'KeyR', target: E('gwoz-target') });
  out.picker = { arrowPrevented: ev.defaultPrevented, letterPrevented: ev2.defaultPrevented, value: E('gwoz-target').value };
  // A checkbox clicked last: Space still fires, and does not tick it.
  E('seat-box').focus();
  ev = down({ key: ' ', code: 'Space' });
  await tick();
  out.checkboxSpace = { prevented: ev.defaultPrevented, fired: posts().length };
  // Typing: the keys are the text box's.
  calls.length = 0;
  ev = down({ key: ' ', code: 'Space', target: E('gwoz-say-text') });
  await tick();
  out.typing = { prevented: ev.defaultPrevented, posts: posts().length };

  // Esc closing a dialog is not STOP; Esc otherwise is.
  calls.length = 0;
  E('groups-modal').hidden = false;
  down({ key: 'Escape', code: 'Escape', target: body });
  E('groups-modal').hidden = true;
  E('logs-drawer').hidden = false;
  down({ key: ' ', code: 'Space', target: body });
  E('logs-drawer').hidden = true;
  await tick();
  out.dialogPosts = posts().length;
  down({ key: 'Escape', code: 'Escape', target: body });
  await tick();
  out.escStops = posts().map(c => c[1]);

  // 0-5: the panel owns a digit with a cue on it while open.
  out.owns = [RA.GroupWoz.ownsKey({ key: '1', code: 'Digit1' }), RA.GroupWoz.ownsKey({ key: '1', code: 'Numpad1' }),
    RA.GroupWoz.ownsKey({ key: '2', code: 'Digit2' }), RA.GroupWoz.ownsKey('1')];

  // Folded: Esc stops only while a cue plays.
  E('gwoz-toggle').click();
  out.folded = E('gwoz-body').hidden;
  out.ownsFolded = RA.GroupWoz.ownsKey({ key: '1', code: 'Digit1' });
  calls.length = 0;
  down({ key: 'Escape', code: 'Escape', target: body });
  RA.GroupWoz.onEvent({ playing: { cue_id: 'greet', until: Date.now() / 1000 + 10 } });
  down({ key: 'Escape', code: 'Escape', target: body });
  down({ key: ' ', code: 'Space', target: body });
  await tick();
  out.foldedPosts = posts().map(c => c[1]);
  E('gwoz-toggle').click();

  // The hub's own reason in the toast; a stale "connected" asks again.
  await new Promise(r => setTimeout(r, 400));     // the refresh the playing event asked for
  calls.length = 0;
  toasts.length = 0;
  answers['/api/group/woz/fire'] = { ok: false, status: 409,
    body: { ok: false, code: 'NO_ROBOTS', error: "none of reachy2 can be reached (the robots' WiFi?)" } };
  down({ key: ' ', code: 'Space', target: body });
  await new Promise(r => setTimeout(r, 450));
  out.toast = toasts[0];
  out.refreshed = calls.some(c => c[0] === 'GET');
  answers['/api/group/woz/fire'] = { ok: false, status: 409, body: { ok: false, code: 'NO_AUDIO' } };
  toasts.length = 0;
  down({ key: ' ', code: 'Space', target: body });
  await tick(); await tick();
  out.fallbackToast = toasts[0];

  // All connected: Connect hides; a refresh does not rebuild an unchanged board.
  const before = E('gwoz-board').children[0];
  RA.GroupWoz.onEvent({ state: { ...state, connected: ['r1', 'r2'] } });
  out.connectHiddenAll = E('gwoz-connect').hidden;
  out.boardKept = E('gwoz-board').children[0] === before;
  RA.GroupWoz.onEvent({ state: { ...state, connected: [] } });
  out.connectShownNone = !E('gwoz-connect').hidden;

  // A robot ticked after Connect (or unreachable then) is in no target: out
  // of a conversation Connect still offers it; in one, the session decides.
  const seats = [{ key: 'r1', included: true }, { key: 'r2', included: true }, { key: 'r3', included: true },
    { key: 'r4', included: false }];
  RA.Group.state = () => ({ running: false, seats });
  RA.GroupWoz.onEvent({ state: { ...state, connected: ['r1', 'r2'] } });
  out.connectShownTickedLater = !E('gwoz-connect').hidden;
  seats[2].included = false;
  RA.GroupWoz.onEvent({ state: { ...state, connected: ['r1', 'r2'] } });
  out.connectHiddenUnticked = E('gwoz-connect').hidden;
  seats[2].included = true;
  RA.Group.state = () => ({ running: true, seats });
  RA.GroupWoz.onEvent({ state: { ...state, connected: ['r1', 'r2'] } });
  out.connectHiddenRunning = E('gwoz-connect').hidden;

  // Open with digits on cues: the Group tab's 0-5 hints step aside.
  out.digitsHeld = body.classList.has('gwoz-digits');
  // Folded during a conversation: Esc is STOP (it cuts the line), no cue needed.
  E('gwoz-toggle').click();
  out.digitsHeldFolded = body.classList.has('gwoz-digits');
  calls.length = 0;
  down({ key: 'Escape', code: 'Escape', target: body });
  RA.Group.state = () => ({ running: false, seats });
  down({ key: 'Escape', code: 'Escape', target: body });
  await tick();
  out.foldedRunningPosts = posts().map(c => c[1]);
  E('gwoz-toggle').click();

  // No cues: arrows are the page's again (scroll, radio buttons); the picker
  // still never moves.
  RA.GroupWoz.onEvent({ state: { ...state, script: { sections: [] } } });
  ev = down({ key: 'ArrowDown', code: 'ArrowDown', target: body });
  out.arrowNoCuesPage = ev.defaultPrevented;
  ev = down({ key: 'ArrowDown', code: 'ArrowDown', target: E('gwoz-target') });
  out.arrowNoCuesPicker = ev.defaultPrevented;

  // Nothing saved yet and Choir on: the panel stays folded and the digits
  // stay the Group tab's interrupting keys.
  delete store['reachy.group.woz.open'];
  RA.Group.choir = () => true;
  RA.GroupWoz.onEvent({ state: { ...state, choir: true } });
  out.choirFolded = E('gwoz-body').hidden;
  out.choirOwns = RA.GroupWoz.ownsKey({ key: '1', code: 'Digit1' });
  out.choirDigitsHeld = body.classList.has('gwoz-digits');
  E('gwoz-toggle').click();
  out.choirOpenedOwns = RA.GroupWoz.ownsKey({ key: '1', code: 'Digit1' });

  console.log(JSON.stringify(out));
})().catch(e => { console.error(e); process.exit(1); });
"""


@pytest.fixture(scope="module")
def gwoz(tmp_path_factory):
    if not NODE:
        pytest.skip("node is not installed")
    harness = tmp_path_factory.mktemp("gwoz") / "harness.js"
    harness.write_text(GWOZ_HARNESS, encoding="utf-8")
    run = subprocess.run([NODE, str(harness), str(WEB / "reachy-group-woz.js")],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("name", ["reachy-group-woz.js", "reachy-group.js", "reachy.js"])
def test_group_pages_parse(name):
    if not NODE:
        pytest.skip("node is not installed")
    run = subprocess.run([NODE, "--check", str(WEB / name)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_gwoz_space_fires_the_outlined_cue_whatever_has_focus(gwoz):
    # Finding 1: Space on the last-clicked button fired that button again.
    assert gwoz["spaceOnButton"] == {"prevented": True, "upPrevented": True, "blurred": True}
    # Three presses, the last one a held key: two cues, in script order.
    assert gwoz["fired"] == ["greet", "hold"]
    assert gwoz["clickBlurs"] >= 2                     # cue and quick-line clicks
    assert gwoz["checkboxSpace"] == {"prevented": True, "fired": 1}
    assert gwoz["typing"] == {"prevented": False, "posts": 0}


def test_gwoz_keys_by_place_and_once(gwoz):
    # Findings 22, 24, 32: Hebrew layout, held keys, the script's own s/d/f.
    assert gwoz["hebrew"] == [["/api/group/woz/fire", "hold"],
                              ["/api/group/woz/say", "Let me think about that for a second."]]


def test_gwoz_picker_keeps_its_target(gwoz):
    # Finding 21: arrows and letters on a focused picker changed the target.
    assert gwoz["pickerBlurOnChange"] is True
    assert gwoz["picker"] == {"arrowPrevented": True, "letterPrevented": True, "value": "r2"}


def test_gwoz_esc_and_dialogs(gwoz):
    # Findings 23, 39: Esc closing a dialog is not STOP; drawers keep their
    # keys; folded, Esc stops a playing cue and nothing else fires.
    assert gwoz["capture"] == [True]
    assert gwoz["keyup"] == 1
    assert gwoz["dialogPosts"] == 0
    assert gwoz["escStops"] == ["/api/group/woz/stop"]
    assert gwoz["folded"] is True
    assert gwoz["foldedPosts"] == ["/api/group/woz/stop"]
    # Finding 41: folded, Esc is STOP during a conversation too (the line is
    # cut, as the button says); with nothing to silence it is left alone.
    assert gwoz["foldedRunningPosts"] == ["/api/group/woz/stop"]


def test_gwoz_quick_keys_and_digits_say_what_they_do(gwoz):
    # Findings 32, 33, 34: badges only on keys that reach a quick line; the
    # digits a cue takes are named while the panel is open.
    assert gwoz["quickBadges"] == ["", "D", "F"]
    assert "D" in gwoz["qkeys"] and "F" in gwoz["qkeys"] and "S" not in gwoz["qkeys"]
    assert gwoz["digits"].startswith("1") and "fire cues" in gwoz["digits"]
    assert gwoz["owns"] == [True, True, False, True]
    assert gwoz["ownsFolded"] is False


def test_gwoz_never_takes_the_digits_by_itself(gwoz):
    # Finding 33 (round 2): Choir on opened the panel by itself and 2 fired a
    # cue on every robot instead of setting interrupting. Only the operator's
    # own open hands the digits over, and the Group tab's 0-5 hints hide then.
    assert gwoz["choirFolded"] is True
    assert gwoz["choirOwns"] is False
    assert gwoz["choirDigitsHeld"] is False
    assert gwoz["choirOpenedOwns"] is True
    assert gwoz["digitsHeld"] is True
    assert gwoz["digitsHeldFolded"] is False
    page = (WEB / "reachy.html").read_text(encoding="utf-8")
    css = (WEB / "reachy.css").read_text(encoding="utf-8")
    assert page.count("lvl-keys") == 2
    assert ".gwoz-digits .lvl-keys{display:none}" in css


def test_gwoz_arrows_left_alone_without_cues(gwoz):
    # Round 2 regression: arrows were swallowed on the whole tab with no cues.
    assert gwoz["arrowNoCuesPage"] is False
    assert gwoz["arrowNoCuesPicker"] is True


def test_group_digits_wait_while_any_dialog_is_open():
    # Round 2 regression: with Groups open, 2 set every robot's interrupting.
    group = (WEB / "reachy-group.js").read_text(encoding="utf-8")
    start = group.index("function onKey(event)")
    body = group[start:group.index("RA.GroupWoz.ownsKey(event)", start)]
    assert "document.querySelector('.modal-wrap:not([hidden])')" in body


def test_gwoz_connect_errors_and_note(gwoz):
    # Findings 9, 35, 36: Connect shows while any target robot is not
    # connected; a NO_ROBOTS answer asks the hub again.
    assert gwoz["connectShownOneMissing"] is True
    assert gwoz["connectHiddenAll"] is True
    assert gwoz["connectShownNone"] is True
    # Round 2: a ticked robot in no target yet still shows Connect.
    assert gwoz["connectShownTickedLater"] is True
    assert gwoz["connectHiddenUnticked"] is True
    assert gwoz["connectHiddenRunning"] is True
    assert gwoz["refreshed"] is True
    assert gwoz["boardKept"] is True
    # Finding 37: the hub's reason, ours only as a fallback.
    assert gwoz["toast"] == ["None of reachy2 can be reached (the robots' WiFi?)", True]
    assert gwoz["fallbackToast"] == ["That cue has no recording yet.", True]
    # Finding 38: why cues are grey.
    assert gwoz["note"] == "could not voice later: offline"


def test_gwoz_hebrew_titles_and_labels(gwoz):
    # Finding 42.
    assert gwoz["titleDir"] == "auto"
    assert gwoz["labelDir"] == ["auto", "auto", "auto"]


def test_gwoz_page_hooks():
    page = (WEB / "reachy.html").read_text(encoding="utf-8")
    group = (WEB / "reachy-group.js").read_text(encoding="utf-8")
    # Finding 41: the tooltip says what STOP does now.
    assert "the cue and any line being said" in page
    assert 'id="gwoz-qkeys"' in page and 'id="gwoz-digits"' in page
    assert "quick lines</p>" not in page                # no fixed S D F promise
    # Findings 9, 35: fresh woz state on every group.state and socket open.
    assert group.count("RA.GroupWoz.refresh()") >= 2
    assert "RA.GroupWoz.ownsKey(event)" in group
