"""Web search in Pepper's free conversation (2026-11-05): the Responses API
call (against a fake endpoint on 127.0.0.1), the Realtime session's tool, the
flow while it searches, and the dashboard's availability rules."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pepper_app import websearch
from pepper_app.brain import Brain

ANSWER = {
    "output": [
        {"type": "web_search_call", "status": "completed",
         "action": {"type": "search", "sources": [{"url": "https://a.example/1"}]}},
        {"type": "message", "content": [{"type": "output_text",
                                         "text": "Maccabi won 2-1, with a late goal.",
                                         "annotations": [{"type": "url_citation", "url": "https://a.example/1"},
                                                         {"type": "url_citation", "url": "https://b.example/2"},
                                                         {"type": "url_citation", "url": "https://c.example/3"}]}]},
    ]}


class FakeResponses:
    """POST /v1/responses on 127.0.0.1, with a delay and a status to choose."""

    def __init__(self, delay=0.0, status=200, body=ANSWER):
        self.delay, self.status, self.body = delay, status, body
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                outer.requests.append({"auth": self.headers.get("Authorization"),
                                       "body": json.loads(self.rfile.read(n))})
                time.sleep(outer.delay)
                raw = json.dumps(outer.body).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self.send_response(outer.status)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:{}/v1/responses".format(self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def fake(monkeypatch):
    servers = []

    def make(**kw):
        f = FakeResponses(**kw)
        servers.append(f)
        monkeypatch.setattr(websearch, "RESPONSES_URL", f.url)
        monkeypatch.setattr(websearch, "MODEL_URL", f.url.replace("/responses", "/models/"))
        return f
    yield make
    for f in servers:
        f.close()


def test_search_asks_the_responses_api_with_its_web_search_tool(fake):
    f = fake()
    answer, sources = asyncio.run(websearch.search("sk-test", "football result last night", "Hebrew"))
    assert answer == "Maccabi won 2-1, with a late goal." and sources == 3
    req = f.requests[0]
    assert req["auth"] == "Bearer sk-test"
    assert req["body"]["model"] == "gpt-4.1-mini" and req["body"]["tools"] == [{"type": "web_search"}]
    assert "football result last night" in req["body"]["input"]
    assert "2-3 short sentences in Hebrew" in req["body"]["input"]


def test_a_slow_or_refused_search_fails_quickly(fake):
    fake(delay=1.0)
    with pytest.raises(websearch.SearchFailed, match="timeout"):
        asyncio.run(websearch.search("k", "q", "English", timeout=0.3))
    fake(status=401)
    with pytest.raises(websearch.SearchFailed, match="401"):
        asyncio.run(websearch.search("k", "q", "English"))
    with pytest.raises(websearch.SearchFailed):
        asyncio.run(websearch.search("", "q", "English"))


def test_the_probe_tells_a_key_that_cannot_search(fake):
    fake(status=200)
    assert asyncio.run(websearch.probe("k")) == "ok"
    fake(status=403)
    assert asyncio.run(websearch.probe("k")) == "no_access"
    assert asyncio.run(websearch.probe("")) == "no_key"


def test_availability_reasons_match_the_dashboard():
    a = websearch.availability
    assert a("free", True, "ok") == {"available": True, "reason": "", "check": "ok"}
    assert a("free", True, "unknown")["available"]
    assert a("feelings:script", True, "ok")["reason"] == "Not in the scripted demo"
    assert a("free", False, "ok")["reason"] == "No GPT key"
    assert a("free", True, "no_internet")["reason"] == "No internet on this network"
    assert a("free", True, "no_access")["reason"] == "This key can't search"


# ------------------------------------------------------------ the brain
class _WS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


async def _no_flush():
    pass


def _brain(cfg, said=None):
    events = []

    async def say_line(text):
        if said is not None:
            said.append(text)
    b = Brain(openai_key="sk-test", eleven_key="", play=lambda pcm: None, flush=_no_flush,
              tool=lambda n, a: "ok", emit=lambda k, d: events.append((k, d)), frame=lambda: None,
              speaking=lambda: False, choice_open=lambda: False, fallback=None, say_line=say_line)
    b.ws, b.cfg = _WS(), dict(cfg)
    return b, events


def test_free_conversation_gets_the_web_search_tool_only_when_it_is_on():
    on, _ = _brain({"experience": "free", "language": "en", "web_search": True})
    s = on._session()
    assert [t["name"] for t in s["tools"]] == ["web_search"] and s["tool_choice"] == "auto"
    assert "web_search tool" in s["instructions"] and "cannot look anything up" not in s["instructions"]
    assert "lab facts" in s["instructions"]                # lab questions: lab_facts.md only
    off, _ = _brain({"experience": "free", "language": "en", "web_search": False})
    s = off._session()
    assert s["tools"] == [] and s["tool_choice"] == "none" and "cannot look anything up" in s["instructions"]
    blocked, _ = _brain({"experience": "free", "language": "en", "web_search": True, "web_ok": False})
    assert blocked._session()["tools"] == []
    scripted_ai, _ = _brain({"experience": "feelings:emoji", "web_search": True, "ai_screen": True})
    assert "web_search" not in [t["name"] for t in scripted_ai._session()["tools"]]


def test_turning_web_search_on_mid_conversation_updates_the_session():
    async def run():
        b, _ = _brain({"experience": "free", "language": "en", "web_search": False})
        b.running = True
        await b.update({"web_search": True})
        upd = b.ws.sent[-1]
        assert upd["type"] == "session.update" and upd["session"]["tools"][0]["name"] == "web_search"
        assert "audio" not in upd["session"]
    asyncio.run(run())


def test_a_search_says_let_me_check_waits_without_the_stuck_alarm_and_answers(fake, monkeypatch):
    import pepper_app.brain as B
    fake(delay=0.8)
    monkeypatch.setattr(B, "STUCK_AFTER_S", 0.3)

    async def run():
        said = []
        b, events = _brain({"experience": "free", "language": "he", "web_search": True}, said)
        b.running = True
        b.history.append(("person", "Who won the football game last night?"))
        await b._respond()
        b.tasks = [asyncio.create_task(b._watchdog())]
        await b._on({"type": "response.created"})
        await b._on({"type": "response.function_call_arguments.done", "name": "web_search",
                     "call_id": "call_1", "arguments": json.dumps({"query": "football result last night"})})
        assert b.searching and b.public()["state"] == "searching"
        assert b.public()["search"]["query"] == "football result last night"
        await b._on({"type": "response.done", "response": {"output": [{"type": "function_call"}]}})
        await asyncio.sleep(0.6)                      # longer than STUCK_AFTER_S
        assert not b.stuck and b.turn == "pepper"     # the alarm waits for the search
        for _ in range(100):
            if not b.searching:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.05)
        b.tasks[0].cancel()
        assert said == ["Let me check…"]                # English: the person spoke English
        search = [d for k, d in events if k == "search"]
        assert search and search[0]["ok"] and search[0]["sources"] == 3
        assert search[0]["query"] == "football result last night" and search[0]["secs"] >= 0.7
        sent = b.ws.sent
        out = next(m for m in sent if m.get("item", {}).get("type") == "function_call_output")
        assert out["item"]["call_id"] == "call_1" and "Maccabi" in out["item"]["output"]
        i = sent.index(out)
        assert sent[i + 1]["item"]["content"][0]["text"] == websearch.FOLLOW_UP
        assert sent[i + 2]["type"] == "response.create"
        assert any(k == "chat" and d.get("text") == "Let me check…" for k, d in events)
    asyncio.run(run())


def test_a_failed_search_lets_pepper_answer_without_it(fake, monkeypatch):
    fake(delay=1.0)
    monkeypatch.setattr(websearch, "TIMEOUT_S", 0.3)

    async def run():
        said = []
        b, events = _brain({"experience": "free", "language": "he", "web_search": True}, said)
        b.running = True
        b.history.append(("person", "מה מזג האוויר בבאר שבע?"))
        await b._on({"type": "response.function_call_arguments.done", "name": "web_search",
                     "call_id": "c2", "arguments": json.dumps({"query": "מזג אוויר באר שבע"})})
        for _ in range(100):
            if not b.searching:
                break
            await asyncio.sleep(0.05)
        assert said == [websearch.CHECK_LINES["he"]]
        search = [d for k, d in events if k == "search"][0]
        assert not search["ok"] and search["error"] == "timeout"
        out = next(m for m in b.ws.sent if m.get("item", {}).get("type") == "function_call_output")
        assert out["item"]["output"].startswith("search failed (timeout)")
        assert b.ws.sent[-1]["type"] == "response.create"
    asyncio.run(run())


# ------------------------------------------------------------ the server
def test_the_server_saves_web_search_applies_it_live_and_reports_why_not(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from pepper_app.server import DEFAULTS, LIVE_OPTIONS, create_app
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert DEFAULTS["web_search"] is True and "web_search" in LIVE_OPTIONS
    app = create_app("", 0, 0, tmp_path)
    P = app.state.pepper
    c = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000))
    snap = P.snapshot()
    assert snap["web"]["reason"] == "Not in the scripted demo"       # the default experience
    assert snap["keys"] == {"gpt": {"has": False, "tail": ""}, "eleven": {"has": False, "tail": ""}}
    assert snap["ai"]["model"] == "gpt-4.1" and snap["ai"]["state"] == "off"
    assert c.post("/api/options", json={"experience": "free"}).status_code == 200
    assert P.web_state()["reason"] == "No GPT key"
    assert P.ai_public()["model"] == "gpt-realtime-2.1"
    c.post("/api/options", json={"web_search": False})
    assert json.loads((tmp_path / "settings.json").read_text())["web_search"] is False

    class FakeBrain:
        running = True
        updates = []

        async def update(self, cfg):
            self.updates.append(cfg)

        def public(self):
            return {"state": "waiting", "running": True}
    P.brain = FakeBrain()
    c.post("/api/options", json={"web_search": True})
    assert FakeBrain.updates and FakeBrain.updates[-1]["web_search"] is True
    P.brain = None
    # A search shows as a pill in the chat and a line in the log.
    P._brain_event("search", {"query": "weather", "secs": 2.8, "sources": 3, "ok": True, "error": ""})
    P._brain_event("search", {"query": "x", "secs": 8.0, "sources": 0, "ok": False, "error": "timeout"})
    chat = [e for e in P.chat if e["role"] == "web"]
    assert chat[0]["text"] == 'Searched the web: "weather" · 2.8 s'
    assert chat[1]["text"] == "Web search failed: timeout. Pepper answered without it."
    assert any('web_search "weather" 2.8 s, 3 sources' in l["msg"] for l in P.logs)


def test_the_key_badges_show_only_the_last_four_characters(tmp_path, monkeypatch):
    from pepper_app.server import create_app
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-abcdefghijklmnop5b12")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_abcdefghijklmnopqrse01b")
    P = create_app("", 0, 0, tmp_path).state.pepper
    assert P.key_badges() == {"gpt": {"has": True, "tail": "5b12"}, "eleven": {"has": True, "tail": "e01b"}}
    assert "abcdefgh" not in json.dumps(P.snapshot())
