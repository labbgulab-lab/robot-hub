"""The wireless Reachy path that fleet bring-up (2026-09-23) changed.

Nothing here needs a robot: SSH, HTTP and the daemon are faked. These are the
behaviours that broke on real hardware that day -- a launch that ran on the
laptop and could not hear, an announcement that switched the robot's audio off,
a name that never reached the card, a sweep that killed the other robot.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub.adapters import reachy_wireless as rw  # noqa: E402
from hub.adapters.base import Found  # noqa: E402
from hub.adapters.reachy_common import PollenDaemon, _wav_seconds  # noqa: E402
from hub.config import Config, RobotCfg, UnitCfg  # noqa: E402

UNIT = "1bf3f0e96e9b0151"
IP = "172.20.10.2"


def _config(**settings) -> Config:
    return Config(robots={"reachy_wireless": RobotCfg(
        display_name="", settings=settings,
        units={UNIT: UnitCfg(display_name="reachy2")})})


SECRET = "AIzaSyTESTSECRETvalue1234"
GEMINI_KEY = {"id": "k1", "provider": "gemini", "label": "Lab Gemini", "key": SECRET}


def _adapter(credential=GEMINI_KEY, **settings) -> rw.ReachyWirelessAdapter:
    found = Found(type_id="reachy_wireless", address=IP, port=8000,
                  meta={"unit_id": UNIT})
    a = rw.ReachyWirelessAdapter(found, _config(**settings))
    a.credential = credential
    return a


class _FakeDaemon:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def media_acquire(self) -> None:
        self.calls.append("acquire")


class _FakeSupervisor:
    def __init__(self, http_ok: bool = True) -> None:
        self.http_ok = http_ok
        self.killed: list[tuple] = []
        self.waited: list[str] = []

    async def wait_for_http(self, url, timeout_s, **_kw) -> bool:
        self.waited.append(url)
        return self.http_ok

    async def kill_matching(self, needles, grace_s=5.0, scope=None):
        self.killed.append((tuple(needles), scope))
        return []

    async def stop(self, _name):
        return []


def _wire(monkeypatch, adapter, ssh_replies, supervisor=None):
    """Script the adapter's SSH replies in order; record every command."""
    sent: list[str] = []
    replies = list(ssh_replies)
    adapter.stdin_sent = []

    async def fake_ssh(command, timeout_s=0, stdin_text=None):
        sent.append(command)
        adapter.stdin_sent.append(stdin_text)
        return replies.pop(0) if replies else (0, "")

    async def fake_clear():
        sent.append("<clear robot side>")
        return ["cleared"]

    async def fake_provision():
        sent.append("<sync reachy_chat>")

    adapter._ssh = fake_ssh
    adapter._clear_robot_side = fake_clear
    adapter._provision_robot = fake_provision
    daemon = _FakeDaemon()
    adapter._get_daemon = lambda found=None: daemon
    sup = supervisor or _FakeSupervisor()
    monkeypatch.setattr(rw, "get_supervisor", lambda: sup)
    return sent, daemon, sup


# ------------------------------------------------------------------ naming
def test_card_and_announcement_use_the_units_own_name():
    a = _adapter()
    assert a.display_name == "reachy2"
    cfg = _config().robot("reachy_wireless")
    assert cfg.name_for("someone-else", "Reachy-Mini") == "Reachy-Mini"


# ------------------------------------------------------------ robot launch
def test_launch_runs_on_the_robot_and_opens_its_dashboard(monkeypatch):
    a = _adapter()
    sent, daemon, sup = _wire(monkeypatch, a, [(0, ""), (0, "started\n")])

    url = asyncio.run(a.launch())

    assert url == "http://{}:8765/".format(IP)
    assert sup.waited == [url]
    assert daemon.calls == ["acquire"]          # audio held before the player starts
    start = sent[2]
    for flag in ("--local-robot", "--host 0.0.0.0", "--robot-id " + UNIT,
                 "--robot-name reachy2", "--mic-match reachymini_audio_src",
                 "--mic-rate 16000", "setsid nohup"):
        assert flag in start, flag


def test_every_launch_syncs_the_app_then_checks_it(monkeypatch):
    # A robot provisioned once must still get today's reachy_chat.
    a = _adapter()
    sent, _daemon, _sup = _wire(monkeypatch, a, [(0, ""), (0, "started")])
    asyncio.run(a.launch())
    assert sent[:2] == ["<sync reachy_chat>", rw.ROBOT_READY_CHECK]


def test_a_failed_check_after_sync_refuses_to_start(monkeypatch):
    a = _adapter()
    sent, _daemon, _sup = _wire(monkeypatch, a, [(1, "")])
    try:
        asyncio.run(a.launch())
    except RuntimeError as exc:
        assert "deploy_robot_app.py" in str(exc)
    else:
        raise AssertionError("a robot failing its check must not be started")
    assert not any("setsid" in c for c in sent)


def test_dead_dashboard_reports_the_robots_own_output(monkeypatch):
    a = _adapter()
    _wire(monkeypatch, a, [(0, ""), (0, "started"), (0, "Traceback: boom")],
          supervisor=_FakeSupervisor(http_ok=False))
    try:
        asyncio.run(a.launch())
    except RuntimeError as exc:
        assert "Traceback: boom" in str(exc)
    else:
        raise AssertionError("a dashboard that never answers must fail the launch")


def test_robot_mode_never_sweeps_the_laptop(monkeypatch):
    a = _adapter()
    sent, _d, sup = _wire(monkeypatch, a, [])
    asyncio.run(a.ensure_zero_instances())
    assert sup.killed == []                      # nothing of ours runs locally
    assert "<clear robot side>" in sent


def test_laptop_mode_sweep_is_scoped_to_this_robot(monkeypatch):
    a = _adapter(mic_mode="laptop")
    _sent, _d, sup = _wire(monkeypatch, a, [])
    asyncio.run(a.ensure_zero_instances())
    assert sup.killed and sup.killed[0][1] == IP


def test_stop_clears_the_robot_even_after_a_hub_restart(monkeypatch):
    a = _adapter()                               # fresh adapter: never launched
    sent, _d, _s = _wire(monkeypatch, a, [])
    asyncio.run(a.stop_system())
    assert sent == ["<clear robot side>"]


# -------------------------------------------------------------------- keys
def test_the_key_travels_on_stdin_and_never_in_a_command(monkeypatch):
    a = _adapter()
    sent, _d, _s = _wire(monkeypatch, a, [(0, ""), (0, "started")])
    asyncio.run(a.launch())
    assert all(SECRET not in c for c in sent)          # not visible to `ps`
    assert a.stdin_sent[1] == SECRET + "\nk1\nLab Gemini\n"
    assert "--provider gemini" in sent[2]
    assert "rm -f {}/.gemini_key".format(rw.ROBOT_APP_DIR) in sent[2]


def test_every_providers_key_travels_on_stdin(monkeypatch):
    # The robot dashboard can switch to GPT-Live or the ElevenLabs voice, so
    # their keys must reach the app too -- and also never on a command line.
    a = _adapter()
    a.provider_env = {"OPENAI_API_KEY": "sk-openai-111111",
                      "ELEVENLABS_API_KEY": "el-222222"}
    sent, _d, _s = _wire(monkeypatch, a, [(0, ""), (0, "started")])
    asyncio.run(a.launch())
    assert all("sk-openai-111111" not in c and "el-222222" not in c for c in sent)
    assert a.stdin_sent[1] == (SECRET + "\nk1\nLab Gemini\n"
                               "el-222222\nsk-openai-111111\n")   # sorted by name
    assert ("IFS= read -r ELEVENLABS_API_KEY && export ELEVENLABS_API_KEY && "
            "IFS= read -r OPENAI_API_KEY && export OPENAI_API_KEY") in sent[2]


def test_no_key_refuses_before_touching_the_robot(monkeypatch):
    a = _adapter(credential=None)
    sent, _d, _s = _wire(monkeypatch, a, [])
    try:
        asyncio.run(a.launch())
    except rw.AdapterUnavailable as exc:
        assert "Keys panel" in str(exc)
    else:
        raise AssertionError("launch without a key must refuse")
    assert sent == []


def test_a_qwen_key_is_refused_with_a_reason(monkeypatch):
    a = _adapter(credential={"id": "k2", "provider": "qwen", "label": "Qwen lab",
                             "key": "sk-qwen-000000"})
    sent, _d, _s = _wire(monkeypatch, a, [])
    try:
        asyncio.run(a.launch())
    except rw.AdapterUnavailable as exc:
        assert "no Qwen speaking backend" in str(exc)
    else:
        raise AssertionError("qwen has no backend in reachy_chat yet")
    assert sent == []


def test_a_gpt_key_launches_as_gpt_live(monkeypatch):
    a = _adapter(credential={"id": "k3", "provider": "gpt", "label": "OpenAI",
                             "key": "sk-openai-000000"})
    sent, _d, _s = _wire(monkeypatch, a, [(0, ""), (0, "started")])
    asyncio.run(a.launch())
    assert "--provider gpt_live" in sent[2]


def test_launch_timeout_covers_provisioning():
    assert rw.ReachyWirelessAdapter.launch_timeout_s > rw.PROVISION_TIMEOUT_S


# ------------------------------------------------------------ announcement
class _RecordingDaemon(PollenDaemon):
    def __init__(self, media_released: bool) -> None:
        super().__init__("http://robot:8000", name="reachy2")
        self.media_released = media_released
        self.log: list[tuple] = []

    async def lock_holder(self):
        return None

    async def list_sounds(self):
        return ["clip.wav"]

    async def _json(self, method, path, **kw):
        if path == "/api/media/status":
            return {"released": self.media_released}
        return {}

    async def _request(self, method, path, **kw):
        self.log.append((method, path, kw.get("json")))


def _clip(tmp_path) -> Path:
    import wave
    path = tmp_path / "clip.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 1600)       # 0.1 s
    return path


def test_announcement_sends_file_field_and_keeps_held_media(tmp_path):
    d = _RecordingDaemon(media_released=False)
    asyncio.run(d.play_wav(_clip(tmp_path)))
    paths = [p for _m, p, _j in d.log]
    assert ("POST", "/api/media/play_sound", {"file": "clip.wav"}) in d.log
    # Releasing held media switches the daemon's audio off for every client.
    assert "/api/media/release" not in paths
    assert "/api/media/acquire" not in paths


def test_announcement_restores_released_media(tmp_path):
    d = _RecordingDaemon(media_released=True)
    asyncio.run(d.play_wav(_clip(tmp_path)))
    paths = [p for _m, p, _j in d.log]
    assert paths.index("/api/media/acquire") < paths.index("/api/media/play_sound")
    assert paths[-1] == "/api/media/release"


def test_wav_length_is_read_from_the_file(tmp_path):
    assert abs(_wav_seconds(_clip(tmp_path)) - 0.1) < 1e-6
