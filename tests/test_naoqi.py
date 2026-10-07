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
    p = _pepper()
    assert asyncio.run(p.ensure_zero_instances()) == []


class _Sup:
    def __init__(self, up_before):
        self.up_before, self.started = up_before, None

    async def wait_for_http(self, url, timeout_s, name=""):
        return self.up_before or self.started is not None

    async def start(self, name, argv, **kw):
        self.started = (name, argv, kw)

    async def stop(self, name):
        pass


def _pepper_launch(monkeypatch, tmp_path, up_before):
    import asyncio
    (tmp_path / "pepper_dashboard.py").write_text("# dashboard")
    p = _pepper()
    p.config = type("C", (), {"path": lambda self, t, k: tmp_path, "repo_root": tmp_path})()
    p.notes, p._child_name = [], ""
    p._python2, p._sdk = Path("C:/Python27/python.exe"), tmp_path
    p._env = lambda: {}
    sup = _Sup(up_before)
    monkeypatch.setattr(N, "get_supervisor", lambda: sup)
    return asyncio.run(p.launch()), sup


def test_pepper_launch_starts_the_dashboard_on_the_robot(monkeypatch, tmp_path):
    url, sup = _pepper_launch(monkeypatch, tmp_path, up_before=False)
    assert url == "http://127.0.0.1:8780/"
    name, argv, kw = sup.started
    assert argv[1].endswith("pepper_dashboard.py") and argv[2] == "172.20.10.2"
    assert kw["port"] == 8780


def test_a_dashboard_started_by_hand_is_reused(monkeypatch, tmp_path):
    url, sup = _pepper_launch(monkeypatch, tmp_path, up_before=True)
    assert url == "http://127.0.0.1:8780/" and sup.started is None


# ------------------------------------------------------------- Add WiFi
SERVICES = ("*AO Tomer Iphone         wifi_2824ff461d28_546f6d6572204970686f6e65_managed_psk\r\n"
            "    Dani Robots          wifi_2824ff461d28_44616e6920526f626f7473_managed_psk\r\n"
            "    eduroam              wifi_2824ff461d28_656475726f616d_managed_ieee8021x\r\n")


def test_the_service_is_found_by_the_hex_name_not_the_column():
    assert N._connman_service(SERVICES, "Dani Robots") == (
        "wifi_2824ff461d28_44616e6920526f626f7473_managed_psk", "psk")
    assert N._connman_service(SERVICES, "Dani") is None
    assert N._connman_service(SERVICES, "eduroam")[1] == "ieee8021x"


class _Chan:
    """connmanctl as the robot would answer, keyed on what was sent."""

    def __init__(self, script):
        self.script, self.out, self.closed = script, [], False

    def send(self, text):
        for prefix, reply in self.script:
            if text.startswith(prefix):
                if reply is None:
                    self.closed = True          # the robot left the network
                else:
                    self.out.append(reply)
                return

    def recv_ready(self):
        return bool(self.out)

    def recv(self, _n):
        return self.out.pop(0).encode()

    def exit_status_ready(self):
        return False


def _fake_paramiko(monkeypatch, script):
    chan = _Chan(script)

    class Client:
        def set_missing_host_key_policy(self, _p): pass
        def connect(self, *a, **k): pass
        def invoke_shell(self, **k): return chan
        def close(self): pass

    fake = type(sys)("paramiko")
    fake.SSHClient = Client
    fake.AutoAddPolicy = lambda: None
    monkeypatch.setitem(sys.modules, "paramiko", fake)
    return chan


BASE = [("connmanctl", "connmanctl> "), ("agent on", "Agent registered\r\n"),
        ("scan wifi", "Scan completed for wifi\r\n"), ("services", SERVICES)]


def test_join_with_a_password(monkeypatch):
    _fake_paramiko(monkeypatch, BASE + [("connect wifi_", "Agent RequestInput\r\n  Passphrase? "),
                                        ("goodpass1", "Connected wifi_2824ff461d28_44616e69\r\n")])
    assert N._connman_join("h", "nao", "nao", "Dani Robots", "goodpass1", 20) == "joined"


def test_the_session_dropping_after_the_password_means_it_moved(monkeypatch):
    _fake_paramiko(monkeypatch, BASE + [("connect wifi_", "Passphrase? "), ("goodpass1", None)])
    assert N._connman_join("h", "nao", "nao", "Dani Robots", "goodpass1", 20) == "moved"


def test_a_wrong_password_says_so(monkeypatch):
    import pytest
    _fake_paramiko(monkeypatch, BASE + [("connect wifi_", "Passphrase? "),
                                        ("badpass99", "Retry (yes/no)? ")])
    with pytest.raises(RuntimeError, match="wrong password"):
        N._connman_join("h", "nao", "nao", "Dani Robots", "badpass99", 20)


def test_a_hotspot_out_of_range_is_named(monkeypatch):
    import pytest
    _fake_paramiko(monkeypatch, BASE)
    with pytest.raises(RuntimeError, match="cannot see “Other Phone”"):
        N._connman_join("h", "nao", "nao", "Other Phone", "goodpass1", 20)


def test_moved_but_still_answering_is_a_failure(monkeypatch):
    import asyncio
    import pytest
    p = _pepper()
    p.settings, p.config = {}, type("C", (), {"secret": lambda self, k: ""})()
    monkeypatch.setattr(N, "_connman_join", lambda *a, **k: "moved")
    real_sleep = asyncio.sleep
    monkeypatch.setattr(N.asyncio, "sleep", lambda s: real_sleep(0))

    async def here():
        return True
    p._still_here = here
    with pytest.raises(RuntimeError, match="still on this network"):
        asyncio.run(p.join_wifi("Dani Robots", "goodpass1"))


# ------------------------------------------------- dashboard + first-run ASR
def _pepper_with_repo(repo):
    p = _pepper()
    p.config = type("C", (), {"path": lambda self, t, k: None, "repo_root": repo})()
    return p


def test_pepper_dashboard_comes_from_the_hub_repo_first(tmp_path):
    repo = tmp_path / "robot-hub"
    for d in (repo / "pepper_dashboard", tmp_path / "pepper" / "dashboard"):
        d.mkdir(parents=True)
        (d / "pepper_dashboard.py").write_text("# dashboard")
    assert _pepper_with_repo(repo)._dashboard().parent == repo / "pepper_dashboard"


def test_pepper_dashboard_falls_back_to_the_usb_kit_copy(tmp_path):
    repo = tmp_path / "robot-hub"
    repo.mkdir()
    kit = tmp_path / "pepper" / "dashboard"
    kit.mkdir(parents=True)
    (kit / "pepper_dashboard.py").write_text("# dashboard")
    assert _pepper_with_repo(repo)._dashboard().parent == kit.resolve()


def test_asr_model_size_is_read_from_nao_llm_config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text('asr:\n  model_size: "small.en"   # English\n  device: "auto"\n')
    assert N._asr_model_size(cfg) == "small.en"
    assert N._asr_model_size(tmp_path / "missing.yaml") == "base.en"


def test_whisper_cache_check(monkeypatch, tmp_path):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not N._whisper_cached("base.en")
    snap = tmp_path / "models--Systran--faster-whisper-base.en" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    assert not N._whisper_cached("base.en")     # a half-finished download
    (snap / "model.bin").write_bytes(b"x")
    assert N._whisper_cached("base.en")
    assert N._whisper_cached(str(tmp_path))     # a local model folder
