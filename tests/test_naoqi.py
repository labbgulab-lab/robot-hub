"""NAO: Launch starts the robot's speaker server when it is not answering."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.adapters import naoqi as N  # noqa: E402


class _Settings:
    settings: dict = {}


class _Config:
    def robot(self, _type_id):
        return _Settings()

    def secret(self, _name, default=""):
        return default

    def path(self, _type_id, _key):
        return None


class _Proc:
    returncode = 1

    async def communicate(self, _stdin=None):
        return b"Speaker server did not come up.", b""

    def kill(self):
        pass


def _adapter(monkeypatch, answers):
    """`answers`: successive results of the port check."""
    # Only what _ensure_speaker_server touches; the real constructor needs a
    # Python 2.7 install for the SDK.
    a = object.__new__(N.NaoqiAdapter)
    a.found = N.Found(type_id="naoqi", address="172.20.10.14")
    a.settings, a.notes = {}, []
    replies = list(answers)

    async def answering(_port):
        return replies.pop(0) if replies else False

    deploys = []

    async def fake_exec(*argv, **_kw):
        deploys.append(argv)
        return _Proc()

    a._speaker_answering = answering
    monkeypatch.setattr(N.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(N, "SPEAKER_UP_WAIT_S", 0.05)
    return a, deploys


def _run(a):
    asyncio.run(a._ensure_speaker_server(Path("."), Path("python"),
                                         Path(N.GENERATED_CONFIG)))


def test_a_running_speaker_server_is_left_alone(monkeypatch):
    a, deploys = _adapter(monkeypatch, [True])
    _run(a)
    assert deploys == []


def test_a_missing_server_is_deployed_and_its_port_decides(monkeypatch):
    # deploy_nao.py "failed" (its own wait gave up), but the port came up.
    a, deploys = _adapter(monkeypatch, [False, True])
    _run(a)
    assert len(deploys) == 1 and "deploy_nao.py" in deploys[0]
    assert any("speaker server" in n for n in a.notes)


def test_a_server_that_never_answers_fails_with_the_deploy_output(monkeypatch):
    a, _deploys = _adapter(monkeypatch, [False])
    try:
        _run(a)
    except RuntimeError as exc:
        assert "did not come up" in str(exc)
    else:
        raise AssertionError("a silent speaker server must fail the launch")


# ------------------------------------------------------------------ Pepper
def _pepper(hostname="Pepper.local."):
    from hub.adapters.base import Found
    p = object.__new__(N.PepperAdapter)
    p.found = Found(type_id="pepper", address="172.20.10.2", port=9559,
                    meta={"hostname": hostname})
    return p


def test_pepper_is_keyed_apart_from_nao():
    p = _pepper()
    assert p.stable_key(p.found) == "pepper:pepper.local"


def test_pepper_claims_no_laptop_mic_and_offers_no_postures():
    # Its own four mics; and it has no Sit or Lying posture to offer.
    p = _pepper()
    assert p.claims() == [] and p.postures == ()


def test_pepper_launch_never_touches_nao_llm():
    # The NAO clean-up kills NAO_LLM's interpreter -- a NAO beside Pepper
    # would lose its running session.
    import asyncio
    import pytest
    p = _pepper()
    assert asyncio.run(p.ensure_zero_instances()) == []
    with pytest.raises(N.AdapterUnavailable, match="no conversation system"):
        asyncio.run(p.launch())
