"""pepper_app's link to Pepper since 2026-11-05: the laptop connects OUT to the
agent (nothing on the laptop listens on the network), the tablet page is
served by the agent on the robot, and the old connect-back way is only a
fallback. No robot here: fake agents over real sockets on 127.0.0.1, and the
real agent itself (under Python 2.7 when this laptop has it) with a fake naoqi."""

import asyncio
import importlib.util
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from pepper_app import robot as robot_mod
from pepper_app.robot import FALLBACK_NOTE, RobotLink

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "pepper_app" / "agent" / "pepper_agent.py"
STATIC = REPO / "pepper_app" / "static"


def _frame(kind, payload):
    return kind + struct.pack(">I", len(payload)) + payload


async def _read(reader):
    head = await reader.readexactly(5)
    return head[:1], await reader.readexactly(struct.unpack(">I", head[1:])[0])


class FakeListeningAgent:
    """The agent's listen mode, minimal: hello check, replies, events on demand."""

    def __init__(self, token):
        self.token = token
        self.got = []
        self.writer = None
        self.refused = 0

    async def start(self):
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    def send(self, kind, payload):
        self.writer.write(_frame(kind, payload))

    def send_json(self, obj):
        self.send(b"J", json.dumps(obj).encode())

    async def _accept(self, reader, writer):
        kind, payload = await _read(reader)
        hello = json.loads(payload)
        if hello.get("token") != self.token:
            self.refused += 1
            writer.close()
            return
        self.writer = writer
        self.send_json({"ev": "hello", "info": {"name": "Pepper"}, "speaker_mode": "naoqi",
                        "pid": 7, "mode": "listen", "tablet_port": 8791})
        try:
            while True:
                kind, body = await _read(reader)
                self.got.append((kind, body))
                if kind == b"J":
                    msg = json.loads(body)
                    if msg.get("id") is not None:
                        self.send_json({"id": msg["id"], "ok": True, "did": msg["cmd"]})
        except Exception:  # noqa: BLE001
            pass

    def close(self):
        if self.writer is not None:
            self.writer.close()
        self.server.close()


def test_the_laptop_connects_out_and_the_link_works_both_ways():
    async def run():
        link = RobotLink("127.0.0.1", 0)
        agent = FakeListeningAgent(link.token)
        link.agent_port = await agent.start()
        events = []
        link.on_event = lambda kind, data: events.append((kind, data))
        assert await link.connect_out(3)
        assert link.connected and link.mode == "direct" and link.state == "connected"
        assert link.info == {"name": "Pepper"} and link.tablet_url == "http://198.18.0.1:8791/screen"
        hello = json.loads(agent.got[0][1]) if agent.got and agent.got[0][0] == b"J" else None
        assert hello is None or hello.get("ev") != "hello"         # the hello is not echoed as a command
        assert (await link.call("move", name="wave"))["did"] == "move"
        assert link.notify("screen_state", state={"v": 3})
        assert link.send_data({"rid": 1, "ok": True}, b"PNGDATA")
        link.send_audio(b"\x00\x00" * 4)
        # Robot -> laptop: the tablet's heartbeat, a tap, a request for a slide file.
        agent.send_json({"ev": "tablet", "ip": "198.18.0.2", "ua": "Android"})
        agent.send_json({"ev": "tap", "v": 4, "i": 1})
        agent.send_json({"ev": "media", "rid": 9, "deck": "abcdef012345", "file": "001.png"})
        for _ in range(100):
            if len([e for e in events if e[0] in ("tablet", "tap", "media")]) == 3:
                break
            await asyncio.sleep(0.02)
        kinds = [k for k, _ in events]
        assert {"tablet", "tap", "media"} <= set(kinds)
        await asyncio.sleep(0.1)
        cmds = [json.loads(b).get("cmd") for k, b in agent.got if k == b"J"]
        assert "screen_state" in cmds
        notify = next(json.loads(b) for k, b in agent.got if k == b"J" and json.loads(b).get("cmd") == "screen_state")
        assert "id" not in notify                       # no reply wanted
        d = next(b for k, b in agent.got if k == b"D")
        n = struct.unpack(">I", d[:4])[0]
        assert json.loads(d[4:4 + n]) == {"rid": 1, "ok": True} and d[4 + n:] == b"PNGDATA"
        assert (b"S", b"\x00\x00" * 4) in agent.got
        agent.close()
        for _ in range(100):
            if not link.connected:
                break
            await asyncio.sleep(0.02)
        assert not link.connected and link.state == "lost"
        await link.close()
    asyncio.run(run())


def test_an_agent_that_does_not_know_this_laptop_is_not_used():
    async def run():
        link = RobotLink("127.0.0.1", 0)
        agent = FakeListeningAgent("another-laptops-token")
        link.agent_port = await agent.start()
        assert not await link.connect_out(0.8)
        assert agent.refused >= 1 and not link.connected
        agent.close()
    asyncio.run(run())


def test_nothing_listens_on_the_laptop_unless_the_fallback_needs_it():
    async def run():
        link = RobotLink("127.0.0.1", 0)
        await link.start(deploy=False)
        assert link._server is None
    asyncio.run(run())


def test_the_fallback_runs_only_when_connecting_out_fails(monkeypatch):
    """No agent answers on port 8790: the agent is restarted in connect-back
    mode, the laptop listens, and the chip says why."""
    monkeypatch.setattr(robot_mod, "OUTBOUND_WAIT_S", 0.6)
    monkeypatch.setattr(robot_mod, "laptop_ip_towards", lambda ip: "127.0.0.1")
    starts = []

    async def run():
        with socket.socket() as s:            # a port where nothing listens
            s.bind(("127.0.0.1", 0))
            dead = s.getsockname()[1]
        link = RobotLink("127.0.0.1", dead, back_port=0, back_host="127.0.0.1")
        details = []
        link.on_event = lambda kind, data: details.append((link.state, link.detail))
        loop = asyncio.get_running_loop()

        def deploy_blocking(laptop_ip):
            starts.append(laptop_ip)
            if laptop_ip is not None:            # connect-back: the agent calls the laptop
                asyncio.run_coroutine_threadsafe(_connect_back(link.back_port, link.token), loop)
            return "fake"
        monkeypatch.setattr(link, "_deploy_blocking", deploy_blocking)
        await link.deploy()
        for _ in range(100):
            if link.connected:
                break
            await asyncio.sleep(0.02)
        assert starts == [None, "127.0.0.1"]
        assert link.connected and link.mode == "connect_back"
        assert ("deploying", FALLBACK_NOTE) in details
        assert FALLBACK_NOTE in link.detail
        await link.close()

    async def _connect_back(port, token):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(_frame(b"J", json.dumps({"ev": "hello", "token": token, "info": {},
                                         "speaker_mode": "naoqi", "pid": 1}).encode()))
        await w.drain()
        await asyncio.sleep(1.0)
        w.close()
    asyncio.run(run())


# ------------------------------------------------------- the real agent
FAKE_NAOQI = '''
class _Stub(object):
    def __init__(self, *a, **k):
        pass
    def __getattr__(self, name):
        if name == "post":
            return self
        return lambda *a, **k: None
ALProxy = _Stub
class ALBroker(object):
    def __init__(self, *a, **k):
        pass
class ALModule(object):
    def __init__(self, name):
        pass
'''


def _import_agent(monkeypatch):
    fake = types.ModuleType("naoqi")
    exec(FAKE_NAOQI, fake.__dict__)
    monkeypatch.setitem(sys.modules, "naoqi", fake)
    spec = importlib.util.spec_from_file_location("pepper_agent_under_test", AGENT)
    agent = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(agent)
    monkeypatch.setattr(agent, "BIND_HOST", "127.0.0.1")
    return agent


class _FakeLink:
    def __init__(self):
        self.sent = []
        self.sock = object()
        self.on_send = None

    def send_json(self, obj):
        if self.sock is None:
            return False
        self.sent.append(obj)
        if self.on_send:
            self.on_send(obj)
        return True


def _get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers.get("Content-Type")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type")


def test_the_tablet_page_is_served_by_the_agent_and_talks_over_the_link(monkeypatch, tmp_path):
    agent = _import_agent(monkeypatch)
    link = _FakeLink()
    files = tmp_path / "screen"
    files.mkdir()
    shutil.copy(STATIC / "screen.html", files / "screen.html")
    shutil.copy(STATIC / "screen-render.js", files / "screen-render.js")
    shutil.copy(STATIC / "labalab-logo.png", files / "labalab-logo.png")
    tablet = agent.Tablet(0, link, str(files), str(tmp_path / "media"))
    port = tablet.start()
    base = "http://127.0.0.1:{}".format(port)
    try:
        code, body, ctype = _get(base + "/screen")
        assert code == 200 and b"/screen/render.js" in body and ctype.startswith("text/html")
        assert _get(base + "/screen/render.js")[0] == 200
        assert _get(base + "/screen/logo.png")[0] == 200
        # The state the laptop pushed; each tablet poll is a heartbeat to the laptop.
        code, body, _ = _get(base + "/screen/state?tablet=1&t=1")
        assert code == 200 and json.loads(body)["item"]["kind"] == "welcome"
        tablet.set_state({"v": 5, "item": {"kind": "message", "text": "שלום"}, "by": "you", "picked": None})
        code, body, _ = _get(base + "/screen/state?tablet=1")
        assert json.loads(body.decode("utf-8"))["item"]["text"] == "שלום"
        assert [m["ev"] for m in link.sent] == ["tablet", "tablet"]
        assert _get(base + "/screen/state")[0] == 200 and len(link.sent) == 2   # the preview is no heartbeat
        # A tap goes to the laptop.
        code, body, _ = _get(base + "/screen/tap", json.dumps({"v": 5, "i": 1}).encode())
        assert code == 200 and link.sent[-1] == {"ev": "tap", "v": 5, "i": 1}
        # A slide: asked of the laptop once, then from the robot's cache.
        def answer(msg):
            if msg.get("ev") == "media":
                head = json.dumps({"rid": msg["rid"], "ok": msg["file"] == "001.png"}).encode()
                payload = struct.pack(">I", len(head)) + head + b"\x89PNG-slide"
                threading.Timer(0.05, tablet.media_in, args=(payload,)).start()
        link.on_send = answer
        code, body, ctype = _get(base + "/screen/media/abcdef012345/001.png")
        assert code == 200 and body == b"\x89PNG-slide" and ctype == "image/png"
        asks = len([m for m in link.sent if m["ev"] == "media"])
        assert _get(base + "/screen/media/abcdef012345/001.png")[1] == b"\x89PNG-slide"
        assert len([m for m in link.sent if m["ev"] == "media"]) == asks          # cached
        assert (tmp_path / "media" / "abcdef012345" / "001.png").read_bytes() == b"\x89PNG-slide"
        assert _get(base + "/screen/media/abcdef012345/002.png")[0] == 404        # the laptop said no
        assert _get(base + "/screen/media/..%2F..%2Fetc/passwd")[0] == 404
        assert _get(base + "/screen/media/abcdef012345/../../x.png")[0] == 404
        # No laptop linked: the tablet's poll fails, so it shows its small red dot.
        link.sock = None
        assert _get(base + "/screen/state?tablet=1")[0] == 503
        assert _get(base + "/screen/tap", b'{"v": 1, "i": 0}')[0] == 503
    finally:
        tablet.stop()


def test_the_agent_checks_the_laptops_token_before_anything(monkeypatch):
    agent = _import_agent(monkeypatch)
    link = agent.Link("good-token")

    class A:
        tablet = None

        def hello(self, mode, token=None):
            return {"ev": "hello", "mode": mode}

        def mic_off(self):
            pass

        def handle(self, msg):
            return {"did": msg.get("cmd")}

    def pair():
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        c = socket.create_connection(srv.getsockname())
        s, addr = srv.accept()
        srv.close()
        return c, s, addr

    laptop, conn, addr = pair()
    laptop.sendall(_frame(b"J", json.dumps({"ev": "hello", "token": "wrong"}).encode()))
    agent.welcome(link, A(), conn, addr)
    assert link.sock is None
    laptop.settimeout(2)
    assert laptop.recv(10) == b""                      # closed without a word
    laptop.close()

    laptop, conn, addr = pair()
    laptop.sendall(_frame(b"J", json.dumps({"ev": "hello", "token": "good-token"}).encode()))
    t = threading.Thread(target=agent.welcome, args=(link, A(), conn, addr), daemon=True)
    t.start()
    laptop.settimeout(3)
    head = laptop.recv(5)
    body = json.loads(laptop.recv(struct.unpack(">I", head[1:])[0]))
    assert body == {"ev": "hello", "mode": "listen"}
    for _ in range(50):
        if link.sock is not None:
            break
        time.sleep(0.02)
    assert link.sock is not None
    laptop.sendall(_frame(b"J", json.dumps({"id": 1, "cmd": "ping"}).encode())
                   + _frame(b"J", json.dumps({"cmd": "screen_state"}).encode())
                   + _frame(b"J", json.dumps({"id": 2, "cmd": "ping"}).encode()))
    replies = []
    for _ in range(2):
        head = laptop.recv(5)
        replies.append(json.loads(laptop.recv(struct.unpack(">I", head[1:])[0])))
    assert [r["id"] for r in replies] == [1, 2]                # no reply without an id
    laptop.close()
    t.join(5)
    assert link.sock is None and link.gone_since is not None


def _python27():
    for cand in (os.environ.get("PYTHON27", ""), r"C:\Python27\python.exe", shutil.which("python2.7") or "",
                 shutil.which("python2") or ""):
        if cand and Path(cand).is_file():
            return cand
    return None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(_python27() is None, reason="no Python 2.7 on this laptop")
def test_the_real_agent_under_python27_listens_serves_the_tablet_and_answers(tmp_path):
    """The agent as it runs on Pepper (Python 2.7, fake naoqi), in listen mode."""
    remote = tmp_path / "robothub"
    (remote / "screen").mkdir(parents=True)
    shutil.copy(AGENT, remote / "pepper_agent.py")
    for name in ("screen.html", "screen-render.js", "labalab-logo.png"):
        shutil.copy(STATIC / name, remote / "screen" / name)
    fake = tmp_path / "fake"
    fake.mkdir()
    (fake / "naoqi.py").write_text(FAKE_NAOQI)
    token_file = remote / "token-1"
    token_file.write_text("t0ken")
    agent_port, tablet_port = _free_port(), _free_port()
    env = dict(os.environ, PYTHONPATH=str(fake), PEPPER_AGENT_HOST="127.0.0.1",
               PEPPER_AGENT_MEDIA=str(tmp_path / "media"), PYTHONIOENCODING="utf-8")
    env.pop("PYTHONHOME", None)
    out = open(tmp_path / "agent.log", "wb")
    proc = subprocess.Popen([_python27(), "-u", str(remote / "pepper_agent.py"), "listen",
                             str(agent_port), str(token_file), str(tablet_port)],
                            stdout=out, stderr=subprocess.STDOUT, env=env)

    async def run():
        link = RobotLink("127.0.0.1", agent_port, tablet_port=tablet_port)
        link.token = "t0ken"
        events = []
        link.on_event = lambda kind, data: events.append((kind, data))
        assert await link.connect_out(15), (tmp_path / "agent.log").read_text(errors="replace")
        assert link.tablet_port == tablet_port and not token_file.exists()
        assert (await link.call("ping"))["ok"]
        assert (await link.call("screen_state", state={"v": 2, "item": {"kind": "blank"}}))["ok"]
        base = "http://127.0.0.1:{}".format(tablet_port)

        def media_answer(kind, data):
            events.append((kind, data))
            if kind == "media":
                link.send_data({"rid": data["rid"], "ok": True}, b"slide-bytes")
        link.on_event = media_answer
        code, body, _ = await asyncio.to_thread(_get, base + "/screen/state?tablet=1")
        assert code == 200 and json.loads(body)["item"]["kind"] == "blank"
        code, body, _ = await asyncio.to_thread(_get, base + "/screen/media/abcdef012345/003.jpg")
        assert code == 200 and body == b"slide-bytes"
        code, body, _ = await asyncio.to_thread(_get, base + "/screen/tap", b'{"v": 2, "i": 0}')
        assert code == 200
        await asyncio.sleep(0.3)
        kinds = [k for k, _ in events]
        assert "tablet" in kinds and "tap" in kinds and "media" in kinds
        # A second laptop without the token gets nothing.
        other = RobotLink("127.0.0.1", agent_port)
        assert not await other.connect_out(1.0)
        assert link.connected
        await link.close()

    try:
        asyncio.run(run())
    finally:
        proc.kill()
        proc.wait(5)
        out.close()


# ------------------------------------------------- the server's side of the tablet
def test_the_server_pushes_the_screen_and_answers_the_tablet_over_the_link(tmp_path):
    from pepper_app.server import create_app
    app = create_app("", 0, 0, tmp_path)
    P = app.state.pepper
    pushed, data = [], []
    P.robot.notify = lambda cmd, **kw: pushed.append((cmd, kw)) or True
    P.robot.send_data = lambda header, payload: data.append((header, payload)) or True
    deck = P.screen.new_deck("Animals")
    P.screen.add_slide(deck["id"], "dog.png", b"\x89PNG-dog")

    async def run():
        # Each poll of the tablet's page on the robot is its heartbeat.
        assert not P.screen.connected
        P._on_robot("tablet", {"ev": "tablet", "ip": "198.18.0.2", "ua": "Android WebView"})
        assert P.screen.connected and P.screen.health()["ip"] == "198.18.0.2"
        # A screen change goes to the robot at once.
        P.set_screen({"kind": "choice", "question": "Which?", "options": [{"label": "Dog"}, {"label": "Cat"}]}, "you")
        cmd, kw = pushed[-1]
        assert cmd == "screen_state" and kw["state"]["item"]["question"] == "Which?"
        # A tap on the real tablet arrives through the agent.
        P._on_robot("tap", {"ev": "tap", "v": P.screen.version, "i": 1})
        await asyncio.sleep(0.05)
        assert P.screen.picked == "Cat" and pushed[-1][1]["state"]["picked"] == "Cat"
        assert any(e["role"] == "tap" and e["text"] == "Cat" for e in P.chat)
        # The agent asks for a slide file; a bad name gets a refusal, never a path outside the deck.
        await P.send_media({"rid": 3, "deck": deck["id"], "file": "001.png"})
        await P.send_media({"rid": 4, "deck": deck["id"], "file": "../deck.json"})
        assert data == [({"rid": 3, "ok": True}, b"\x89PNG-dog"), ({"rid": 4, "ok": False}, b"")]
        # The tablet is told to load its page from the robot.
        assert P.robot.tablet_url == "http://198.18.0.1:8791/screen"
    asyncio.run(run())
