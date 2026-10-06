"""NAO's Sit / Lie down / Stand up buttons -- against fakes only.

No test here reaches a robot: the hub side runs with fake adapters, and the
Python 2.7 helper's posture logic runs in-process with fake ALProxy objects.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hub.adapters import naoqi as N  # noqa: E402
from hub.adapters.base import PostureRefused  # noqa: E402
from hub.config import load_config  # noqa: E402
from hub.core import Hub  # noqa: E402
from hub.registry import CONNECTED, DETECTED, RUNNING  # noqa: E402


def _run(coro):
    async def first():
        return await coro
    return asyncio.run(first())


# --------------------------------------------------------------- fake bridge
def _load_agent2():
    """The real helper, imported under Python 3 with its proxies faked."""
    spec = importlib.util.spec_from_file_location("agent2_under_test", N.AGENT2)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeNao:
    """The NAOqi services cmd_posture uses, recording every call."""

    JOINTS = ["HeadYaw", "HeadPitch", "LHipPitch", "RHipPitch", "RKneePitch"]

    def __init__(self, temps=None, posture="Stand", awake=True, reaches=True,
                 life="solitary"):
        self.temps = {"HeadYaw": 38.0, "HeadPitch": 37.0, "LHipPitch": 45.0,
                      "RHipPitch": 47.0, "RKneePitch": 44.0}
        if temps is not None:
            self.temps = temps
        self.posture = posture
        self.awake = awake
        self.reaches = reaches
        self.life = life
        self.calls: list[tuple] = []

    # ALMotion
    def getBodyNames(self, chain):
        return list(self.JOINTS)

    def robotIsWakeUp(self):
        return self.awake

    def wakeUp(self):
        self.calls.append(("wakeUp",))
        self.awake = True

    def setStiffnesses(self, names, value):
        self.calls.append(("setStiffnesses", names, value))
        if names == "Body" and value == 0.0:
            self.awake = False

    def rest(self):                      # must never be called
        self.calls.append(("rest",))

    # ALMemory
    def getListData(self, keys):
        out = []
        for key in keys:
            joint = key.split("/")[2]
            out.append(self.temps.get(joint))
        return out

    # ALRobotPosture
    def getPosture(self):
        return self.posture

    def goToPosture(self, name, speed):
        self.calls.append(("goToPosture", name, speed))
        if self.reaches:
            self.posture = name
        return self.reaches

    # ALAutonomousLife
    def getState(self):
        return self.life

    def setState(self, state):
        self.calls.append(("setState", state))
        self.life = state

    @property
    def motions(self):
        return [c for c in self.calls if c[0] in
                ("wakeUp", "goToPosture", "setStiffnesses", "rest")]


@pytest.fixture
def agent2(monkeypatch):
    module = _load_agent2()
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)
    return module


def _bridge(agent2, monkeypatch, nao):
    monkeypatch.setattr(agent2, "make_proxy", lambda service, ip, port: nao)

    def posture(name, limit):
        return agent2.cmd_posture({"ip": "nao.test", "port": 9559,
                                   "name": name, "max_temp_c": limit})
    return posture


@pytest.mark.parametrize("name,target", [("sit", "Sit"), ("lie", "LyingBack")])
def test_sit_and_lie_end_with_the_motors_off(agent2, monkeypatch, name, target):
    nao = FakeNao()
    result = _bridge(agent2, monkeypatch, nao)(name, 70.0)
    assert result["ok"] and result["motors_off"] is True
    assert ("goToPosture", target, 0.4) in nao.calls
    assert nao.motions[-1] == ("setStiffnesses", "Body", 0.0)
    assert ("rest",) not in nao.calls
    assert not any(c[0] == "goToPosture" and c[1] == "Crouch" for c in nao.calls)


def test_stand_parks_life_wakes_and_keeps_the_motors_on(agent2, monkeypatch):
    nao = FakeNao(posture="Sit", awake=False)
    result = _bridge(agent2, monkeypatch, nao)("stand", 60.0)
    assert result["ok"] and result["motors_off"] is False
    assert ("setState", "disabled") in nao.calls
    assert nao.motions == [("wakeUp",), ("goToPosture", "Stand", 0.5)]


@pytest.mark.parametrize("name,limit", [("sit", 70.0), ("lie", 70.0), ("stand", 60.0)])
def test_a_hot_joint_refuses_before_anything_moves(agent2, monkeypatch, name, limit):
    nao = FakeNao(temps={"HeadYaw": 40.0, "RHipPitch": 92.0, "RKneePitch": 55.0})
    result = _bridge(agent2, monkeypatch, nao)(name, limit)
    assert result == {"ok": False, "refused": "hot", "joint": "RHipPitch",
                      "temp_c": 92.0, "limit_c": limit}
    assert nao.calls == [], "nothing may move -- not even Autonomous Life"


def test_stand_has_the_lower_limit(agent2, monkeypatch):
    warm = {"RHipPitch": 64.0, "RKneePitch": 50.0}
    assert _bridge(agent2, monkeypatch, FakeNao(temps=dict(warm)))(
        "stand", N.STAND_HEAT_LIMIT_C)["refused"] == "hot"
    assert _bridge(agent2, monkeypatch, FakeNao(temps=dict(warm)))(
        "sit", N.HEAT_LIMIT_C)["ok"] is True


def test_no_temperatures_means_no_motion(agent2, monkeypatch):
    nao = FakeNao(temps={})
    result = _bridge(agent2, monkeypatch, nao)("sit", 70.0)
    assert result == {"ok": False, "refused": "no_temperatures"}
    assert nao.calls == []


def test_a_posture_it_could_not_reach_keeps_the_motors_on(agent2, monkeypatch):
    # Dropping stiffness in an unknown pose could make it fall.
    nao = FakeNao(reaches=False)
    result = _bridge(agent2, monkeypatch, nao)("sit", 70.0)
    assert result["ok"] is False and result["reached"] is False
    assert not any(c[0] == "setStiffnesses" for c in nao.calls)


def test_already_sitting_with_motors_off_moves_nothing(agent2, monkeypatch):
    nao = FakeNao(posture="Sit", awake=False)
    result = _bridge(agent2, monkeypatch, nao)("sit", 70.0)
    assert result["ok"] and result["already"]
    assert nao.motions == []


def test_temperatures_fall_back_to_one_key_at_a_time(agent2):
    class Memory:
        def getListData(self, keys):
            raise RuntimeError("ALMemory: unknown key")

        def getData(self, key):
            if "RHipPitch" in key:
                raise RuntimeError("unknown key")
            return 51.5

    temps = agent2.read_temperatures(FakeNao(), Memory())
    assert "RHipPitch" not in temps and temps["LHipPitch"] == 51.5


# ------------------------------------------------------------- the adapter
def _adapter(monkeypatch, nao=None, agent2=None, answer=None):
    """A NaoqiAdapter whose bridge is either the in-process helper or a
    canned answer. The real constructor needs Python 2.7 and the SDK."""
    a = object.__new__(N.NaoqiAdapter)
    a.found = N.Found(type_id="naoqi", address="nao.test")
    a.settings, a.notes = {}, []
    sent = []

    async def call(command, **kw):
        sent.append((command, kw))
        if answer is not None:
            return answer
        payload = {k: v for k, v in kw.items()
                   if k not in ("retries", "timeout", "answer_any")}
        return agent2.COMMANDS[command]({"ip": "nao.test", "port": 9559, **payload})

    if agent2 is not None:
        monkeypatch.setattr(agent2, "make_proxy", lambda service, ip, port: nao)
    a._call = call
    return a, sent


def test_adapter_sends_one_unretried_call_with_the_right_limit(monkeypatch, agent2):
    for name, limit in (("sit", N.HEAT_LIMIT_C), ("lie", N.HEAT_LIMIT_C),
                        ("stand", N.STAND_HEAT_LIMIT_C)):
        a, sent = _adapter(monkeypatch, FakeNao(), agent2)
        _run(a.posture(name))
        assert len(sent) == 1
        command, kw = sent[0]
        assert command == "posture" and kw["name"] == name
        assert kw["max_temp_c"] == limit and kw["retries"] == 0


def test_adapter_words_the_result(monkeypatch, agent2):
    a, _ = _adapter(monkeypatch, FakeNao(), agent2)
    message = _run(a.posture("sit"))
    assert message.startswith("NAO is sitting, motors off")
    a, _ = _adapter(monkeypatch, FakeNao(posture="Sit"), agent2)
    assert _run(a.posture("stand")).startswith("NAO is standing, motors on")


def test_adapter_heat_refusal_names_the_joint_and_temperature(monkeypatch, agent2):
    nao = FakeNao(temps={"RHipPitch": 92.0, "HeadYaw": 40.0})
    a, _ = _adapter(monkeypatch, nao, agent2)
    with pytest.raises(PostureRefused) as exc:
        _run(a.posture("sit"))
    text = str(exc.value)
    assert "right hip" in text and "92 °C" in text and "cool" in text
    assert nao.calls == []


def test_adapter_unreached_posture_is_an_error_not_a_refusal(monkeypatch):
    a, _ = _adapter(monkeypatch, answer={"ok": False, "reached": False,
                                         "posture": "Crouch"})
    with pytest.raises(RuntimeError) as exc:
        _run(a.posture("lie"))
    assert not isinstance(exc.value, PostureRefused)
    assert "motors left on" in str(exc.value)


def test_a_refusal_is_not_retried(monkeypatch):
    a = object.__new__(N.NaoqiAdapter)
    a.found = N.Found(type_id="naoqi", address="nao.test")
    a.settings, a._lock = {}, asyncio.Lock()
    runs = []

    async def run_once(message, timeout):
        runs.append(timeout)
        return {"ok": False, "refused": "hot", "joint": "RHipPitch",
                "temp_c": 80.0, "limit_c": 70.0}

    a._run_once = run_once

    async def scenario():
        a._lock = asyncio.Lock()
        with pytest.raises(PostureRefused):
            await a.posture("sit")

    asyncio.run(scenario())
    assert runs == [N.POSTURE_TIMEOUT_S]


def test_joint_labels():
    assert N.joint_label("RHipPitch") == "right hip"
    assert N.joint_label("LHipYawPitch") == "left hip"
    assert N.joint_label("HeadPitch") == "neck"
    assert N.joint_label("Mystery") == "Mystery"


# ------------------------------------------------------------------ the hub
class _PostureAdapter:
    postures = ("sit", "lie", "stand")
    posture_timeout_s = 5.0

    def __init__(self, outcome=None):
        self.outcome = outcome
        self.asked: list[str] = []
        self.release = None

    async def posture(self, name):
        self.asked.append(name)
        if self.release is not None:
            await self.release.wait()
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome or "NAO is sitting, motors off"

    def claims(self):
        return []

    async def ensure_zero_instances(self):
        return []

    async def launch(self):
        return "http://robot/"

    async def disconnect(self):
        pass


class _NoPostures(_PostureAdapter):
    postures = ()


@pytest.fixture
def config():
    cfg = load_config()
    cfg.auto_connect = False
    return cfg


def _hub(config, adapter, state=CONNECTED):
    hub = Hub(config)
    hub.registry.upsert("nao", type_id="naoqi", name="NAO")
    hub.registry.set_state("nao", state)
    hub.adapters["nao"] = adapter
    return hub


def _log(hub):
    return [e["text"] for e in hub.bus.recent() if e["type"] == "log"]


def test_hub_routes_to_the_adapter_and_logs(config):
    adapter = _PostureAdapter()
    hub = _hub(config, adapter)
    result = _run(hub.posture("nao", "Sit"))
    assert result == {"ok": True, "message": "NAO is sitting, motors off"}
    assert adapter.asked == ["sit"]
    r = hub.registry.get("nao")
    assert r.posture_pending is None and r.posture_note == "NAO is sitting, motors off"
    assert r.posture_failed is False
    assert "NAO: NAO is sitting, motors off" in _log(hub)
    assert "nao" not in hub._busy and "nao" not in hub._postures


def test_hub_also_moves_a_running_robot(config):
    hub = _hub(config, _PostureAdapter(), state=RUNNING)
    assert _run(hub.posture("nao", "lie"))["ok"] is True


def test_hub_refuses_when_not_connected(config):
    adapter = _PostureAdapter()
    hub = _hub(config, adapter, state=DETECTED)
    result = _run(hub.posture("nao", "sit"))
    assert result["ok"] is False and "connect" in result["error"]
    assert adapter.asked == []


def test_hub_refuses_while_busy(config):
    adapter = _PostureAdapter()
    hub = _hub(config, adapter)
    hub._busy.add("nao")                      # connecting, disconnecting...
    result = _run(hub.posture("nao", "sit"))
    assert result["ok"] is False and "busy" in result["error"]
    assert adapter.asked == []


def test_hub_refuses_while_a_launch_is_in_flight(config):
    adapter = _PostureAdapter()
    hub = _hub(config, adapter)
    started = asyncio.Event()

    async def slow_launch():
        started.set()
        await asyncio.sleep(60)
        return "http://robot/"

    adapter.launch = slow_launch

    async def scenario():
        pending = asyncio.create_task(hub.launch("nao"))
        await started.wait()
        result = await hub.posture("nao", "stand")
        await hub.disconnect("nao")
        await asyncio.wait_for(pending, 5)
        return result

    result = _run(scenario())
    assert result["ok"] is False and "launching" in result["error"]
    assert adapter.asked == []


def test_a_second_press_while_moving_is_refused_and_blocks_launch(config):
    adapter = _PostureAdapter()
    hub = _hub(config, adapter)

    async def scenario():
        adapter.release = asyncio.Event()
        first = asyncio.create_task(hub.posture("nao", "sit"))
        await asyncio.sleep(0)
        assert hub.registry.get("nao").posture_pending == "sit"
        second = await hub.posture("nao", "lie")
        launch = await hub.launch("nao")
        adapter.release.set()
        return second, launch, await first

    second, launch, first = _run(scenario())
    assert second["ok"] is False and "moving" in second["error"]
    assert launch["ok"] is False
    assert first["ok"] is True and adapter.asked == ["sit"]


def test_hub_refuses_robots_without_postures(config):
    hub = _hub(config, _NoPostures())
    result = _run(hub.posture("nao", "sit"))
    assert result["ok"] is False and "no posture controls" in result["error"]


def test_hub_refuses_unknown_names_and_robots(config):
    hub = _hub(config, _PostureAdapter())
    assert _run(hub.posture("nao", "crouch"))["ok"] is False
    assert _run(hub.posture("nope", "sit")) == {"ok": False, "error": "unknown robot"}


def test_hub_surfaces_a_heat_refusal_on_the_card(config):
    sentence = "NAO's right hip (RHipPitch) is at 92 °C — let it cool"
    hub = _hub(config, _PostureAdapter(PostureRefused(sentence)))
    result = _run(hub.posture("nao", "sit"))
    assert result == {"ok": False, "error": sentence, "refused": True}
    r = hub.registry.get("nao")
    assert r.posture_note == sentence and r.posture_failed is True
    assert r.posture_pending is None and "nao" not in hub._busy


def test_hub_reports_a_failure(config):
    hub = _hub(config, _PostureAdapter(RuntimeError("NAO did not reach Sit")))
    result = _run(hub.posture("nao", "sit"))
    assert result == {"ok": False, "error": "NAO did not reach Sit"}
    assert any("sit failed" in t for t in _log(hub))


# ----------------------------------------------------------------- the route
def test_posture_route(monkeypatch):
    from fastapi.testclient import TestClient
    from hub import main

    seen = []

    async def fake_posture(key, name):
        seen.append((key, name))
        if name == "stand":
            return {"ok": False, "error": "too hot", "refused": True}
        return {"ok": True, "message": "NAO is sitting, motors off"}

    monkeypatch.setattr(main.hub, "posture", fake_posture)
    # No `with`: the lifespan (and so discovery) never starts.
    client = TestClient(main.app)
    ok = client.post("/api/robots/nao-key/posture", json={"name": "sit"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    refused = client.post("/api/robots/nao-key/posture", json={"name": "stand"})
    assert refused.status_code == 409 and refused.json()["error"] == "too hot"
    assert client.post("/api/robots/nao-key/posture", json={}).status_code == 422
    assert seen == [("nao-key", "sit"), ("nao-key", "stand")]
