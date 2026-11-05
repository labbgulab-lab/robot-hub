"""The student-app platform (work package A1): data folder, layered config,
settings, the app routes, logs, windowless children.

No robot and no network: the update check is faked, the installer and the
folder opener are injected, and every file goes to a tmp folder.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import applog, keyscrub, settings as S, winproc  # noqa: E402
from hub.app_api import UpdateChecker, make_router, port_owner, read_version, version_tuple  # noqa: E402
from hub.config import (DEFAULTS_FILE, REPO_ROOT, Config, RobotCfg, config_layers,  # noqa: E402
                        custom_data_dir, data_dir, find_naoqi_kit, load_config)
from hub.events import EventBus  # noqa: E402

PY = sys.executable
FAKE_GEMINI = "AIza" + "T" * 35
FAKE_OPENAI = "sk-proj-" + "q" * 40


# ---------------------------------------------------------------- data dir
def test_data_dir_defaults_to_the_repo_root(monkeypatch):
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    assert custom_data_dir() is None
    assert data_dir() == REPO_ROOT


def test_data_dir_follows_robot_hub_data(monkeypatch, tmp_path):
    monkeypatch.setenv("ROBOT_HUB_DATA", str(tmp_path))
    assert custom_data_dir() == tmp_path.resolve()
    assert data_dir() == tmp_path.resolve()


def test_every_writable_path_moves_to_the_data_folder(tmp_path):
    """A fresh interpreter with ROBOT_HUB_DATA set: module-level paths and the
    hub's keys and settings all land in it, nothing in the repo."""
    code = (
        "import json\n"
        "from hub.group import conductor, phrases\n"
        "from hub.config import load_config\n"
        "from hub.core import Hub\n"
        "h = Hub(load_config())\n"
        "print(json.dumps({'cfg': str(conductor.CONFIG_FILE), 'logs': str(conductor.LOG_DIR),\n"
        "  'echo': str(conductor.ECHO_FILE), 'phrases': str(phrases.CACHE_DIR),\n"
        "  'keys': str(h.keys.path), 'settings': str(h.settings.path),\n"
        "  'data': str(h.config.data_dir), 'layers': h.config.layers,\n"
        "  'transcripts': str(h.settings.transcripts_dir())}))\n")
    env = dict(os.environ, ROBOT_HUB_DATA=str(tmp_path))
    out = subprocess.run([PY, "-c", code], cwd=str(REPO_ROOT), env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout.strip().splitlines()[-1])
    root = tmp_path.resolve()
    assert Path(got["data"]) == root
    assert Path(got["cfg"]) == root / "group.local.json"
    assert Path(got["logs"]) == root / "logs"
    assert Path(got["echo"]) == root / "cache" / "group_echo.json"
    assert Path(got["phrases"]) == root / "cache" / "group_phrases"
    assert Path(got["keys"]) == root / "keys.local.json"
    assert Path(got["settings"]) == root / "settings.json"
    assert Path(got["transcripts"]) == root / "transcripts"
    # A student install never reads the lab's config.toml in the app folder.
    assert not any(Path(p).name == "config.toml" and Path(p).parent == REPO_ROOT
                   for p in got["layers"])


# ------------------------------------------------------------------ config
def _toml(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_defaults_are_the_student_defaults(tmp_path):
    cfg = load_config(defaults=DEFAULTS_FILE, data=tmp_path)
    assert cfg.layers == [str(DEFAULTS_FILE)]
    assert cfg.server.host == "127.0.0.1" and cfg.server.port == 8099
    assert cfg.discovery.mdns is False          # no listener, no firewall prompt
    assert cfg.discovery.netscan is True and cfg.discovery.usb is True
    assert cfg.network.lab_wifi == "HOT-WiFi" and cfg.network.lab_wifi_open is True
    rw = cfg.robot("reachy_wireless")
    assert {u.display_name for u in rw.units.values()} == {"reachy{}".format(i) for i in range(1, 9)}
    assert rw.settings["mic_mode"] == "robot"
    assert rw.settings["python"] == ""
    assert cfg.path("reachy_wireless", "reachy_chat_path") == (REPO_ROOT.parent / "reachy_chat").resolve()
    assert cfg.robot("furhat").settings["password"] == "admin"
    assert cfg.robot("furhat").settings["username"] == "admin"
    assert cfg.robot("naoqi").settings["python2"] == ""
    assert cfg.robot("reachy_lite").settings["control_app"] == ""
    assert cfg.data_dir == tmp_path


def test_layers_override_key_by_key(tmp_path):
    defaults = _toml(tmp_path / "defaults.toml", """
auto_connect = false
[discovery]
mdns = false
netscan = true
[robots.furhat.settings]
password = "admin"
voice = ""
""")
    lab = _toml(tmp_path / "lab.toml", """
[discovery]
mdns = true
[robots.furhat.settings]
voice = "Lab voice"
""")
    data = tmp_path / "data"
    data.mkdir()
    _toml(data / "config.toml", """
auto_connect = true
[robots.furhat.settings]
voice = "Student voice"
""")
    # A lab file passed explicitly sits between the defaults and the data folder.
    cfg = load_config(lab, defaults=defaults, data=data)
    assert cfg.layers == [str(defaults), str(lab), str(data / "config.toml")]
    assert cfg.discovery.mdns is True            # lab over defaults
    assert cfg.discovery.netscan is True         # untouched default survives
    assert cfg.auto_connect is True              # data over everything
    assert cfg.robot("furhat").settings == {"password": "admin", "voice": "Student voice"}


def test_lab_checkout_reads_its_config_toml_and_no_data_layer(monkeypatch):
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    layers = config_layers()
    assert layers[0] == DEFAULTS_FILE
    lab = REPO_ROOT / "config.toml"
    assert layers[1] == (lab if lab.exists() else REPO_ROOT / "config.example.toml")
    assert len(layers) == 2


def test_student_install_reads_only_defaults_and_its_data_config(tmp_path):
    assert config_layers(data=tmp_path) == [DEFAULTS_FILE]
    _toml(tmp_path / "config.toml", "auto_connect = true\n")
    assert config_layers(data=tmp_path) == [DEFAULTS_FILE, tmp_path / "config.toml"]


def test_netscan_runs_even_with_furhat_disabled(monkeypatch):
    from hub.discovery import manager as M

    started = []

    class Fake:
        def __init__(self, *a, **k):
            started.append(type(self).__name__)

    monkeypatch.setattr(M, "NetscanDetector", type("NetscanDetector", (Fake,), {}))
    monkeypatch.setattr(M, "MdnsDetector", type("MdnsDetector", (Fake,), {}))
    monkeypatch.setattr(M, "UsbWatchDetector", type("UsbWatchDetector", (Fake,), {}))
    cfg = Config(robots={"furhat": RobotCfg(enabled=False)})
    cfg.discovery.mdns = False
    cfg.discovery.usb = False
    mgr = M.DiscoveryManager(cfg, EventBus(), on_found=lambda f: None,
                             on_lost=lambda *a: None, on_network=lambda i: None)
    monkeypatch.setattr(mgr, "_spawn", lambda d: None)

    async def go():
        await mgr.start()
        for t in mgr._tasks:
            t.cancel()
    asyncio.run(go())
    assert "NetscanDetector" in started and "MdnsDetector" not in started


# --------------------------------------------------------------- naoqi kit
def test_the_naoqi_kit_is_found_in_its_doubled_folder(tmp_path):
    base = tmp_path / "naoqi-sdk"
    sdk = base / "pynaoqi-python2.7-2.8.7.4-win64" / "pynaoqi-python2.7-2.8.7.4-win64"
    (sdk / "lib" / "python2.7").mkdir(parents=True)
    (sdk / "bin").mkdir()
    exe = "python.exe" if sys.platform == "win32" else "python"
    (sdk / "bin" / exe).write_text("")
    assert find_naoqi_kit([tmp_path / "missing", base]) == {
        "pynaoqi_sdk": sdk, "python2": sdk / "bin" / exe}
    assert find_naoqi_kit([tmp_path / "missing"]) == {}


def test_nao_runs_the_kits_own_python_with_pythonhome(tmp_path):
    from hub.adapters import naoqi as N
    sdk = tmp_path / "sdk"
    (sdk / "lib" / "python2.7").mkdir(parents=True)
    (sdk / "bin").mkdir()
    a = object.__new__(N.NaoqiAdapter)
    a._sdk, a._python2 = sdk, sdk / "bin" / "python.exe"
    env = a._env()
    assert env["PYTHONHOME"] == str(sdk / "lib" / "python2.7")
    assert env["PYTHONPATH"] == str(sdk / "lib")
    a._python2 = Path("C:/Python27/python.exe")      # a separate Python 2.7
    assert a._env().get("PYTHONHOME") == os.environ.get("PYTHONHOME")


# ---------------------------------------------------------------- settings
class _Cfg:
    """Just what SettingsStore reads from a Config."""

    def __init__(self, password=""):
        self.auto_connect = False
        self.network = type("N", (), {"lab_wifi": "HOT-WiFi", "lab_wifi_open": True})()
        self._password = password

    def robot(self, type_id):
        return RobotCfg(settings={"password": self._password} if self._password else {})


def test_settings_defaults_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_HUB_DATA", str(tmp_path))   # a student install
    cfg = _Cfg()
    store = S.SettingsStore(tmp_path / "settings.json", cfg)
    assert store.first_run is True
    pub = store.public()
    assert pub["auto_connect"] is False and pub["staff_tools"] is False
    assert pub["save_transcripts"] is True and pub["setup_seen"] is False
    assert pub["lab_wifi"] == {"name": "HOT-WiFi", "open": True}
    assert pub["passwords"] == {"furhat": {"set": True, "works": None}}

    store.update({"auto_connect": True, "staff_tools": True, "setup_seen": True,
                  "lab_wifi": {"name": "Lab-2", "open": False}})
    assert cfg.auto_connect is True                    # applied live
    assert cfg.network.lab_wifi == "Lab-2" and cfg.network.lab_wifi_open is False

    cfg2 = _Cfg()
    again = S.SettingsStore(tmp_path / "settings.json", cfg2)
    assert again.first_run is False
    assert again.public()["staff_tools"] is True
    assert cfg2.auto_connect is True                   # survives a restart now
    assert cfg2.network.lab_wifi == "Lab-2"


def test_settings_refuse_wrong_values(tmp_path):
    store = S.SettingsStore(tmp_path / "s.json", _Cfg())
    for bad in ({"auto_connect": "yes"}, {"nope": True}, {"lab_wifi": "x"},
                {"lab_wifi": {"open": "no"}}):
        with pytest.raises(S.SettingsError):
            store.update(bad)
    assert not (tmp_path / "s.json").exists()


def test_furhat_password_order(tmp_path, monkeypatch):
    monkeypatch.delenv("FURHAT_PASSWORD", raising=False)
    store = S.SettingsStore(tmp_path / "s.json", _Cfg())
    assert store.password("furhat") == "admin"                  # maker's default
    store = S.SettingsStore(tmp_path / "s.json", _Cfg(password="fromconfig"))
    assert store.password("furhat") == "fromconfig"
    store.set_password("furhat", "  saved  ")
    assert store.password("furhat") == "saved"                  # Settings over config
    assert json.loads((tmp_path / "s.json").read_text())["passwords"]["furhat"] == "saved"
    assert "saved" not in json.dumps(store.public())            # never sent back
    monkeypatch.setenv("FURHAT_PASSWORD", "lab-env")
    assert store.password("furhat") == "lab-env"                # a lab .env wins
    monkeypatch.delenv("FURHAT_PASSWORD")
    store.set_password("furhat", "")
    assert store.password("furhat") == "fromconfig"
    with pytest.raises(S.SettingsError) as exc:
        store.set_password("nao", "x")
    assert exc.value.code == "UNKNOWN_ROBOT"


def test_furhat_login_result_is_reported(tmp_path, monkeypatch):
    monkeypatch.delenv("FURHAT_PASSWORD", raising=False)
    monkeypatch.setattr(S, "_CURRENT", None)     # restored after the test
    store = S.open_store(tmp_path, _Cfg())
    S.note_login("furhat", False)
    assert store.public()["passwords"]["furhat"]["works"] is False
    assert S.robot_password("furhat") == "admin"
    store.set_password("furhat", "new")
    assert store.public()["passwords"]["furhat"]["works"] is None


def test_robots_network_is_remembered_and_throttled(tmp_path):
    store = S.SettingsStore(tmp_path / "s.json", _Cfg())
    store.note_robots_network("HOT-WiFi", when=1000.0)
    store.note_robots_network("HOT-WiFi", when=1030.0)      # within a minute: no write
    assert json.loads((tmp_path / "s.json").read_text())["robots_network"]["last_seen"] == 1000.0
    store.note_robots_network("Phone", when=1031.0)
    assert S.SettingsStore(tmp_path / "s.json", _Cfg()).public()["robots_network"]["ssid"] == "Phone"


# -------------------------------------------------------------- app routes
class _Keys:
    def all_secrets(self):
        return [{"id": "k1", "provider": "gemini", "label": "x", "key": FAKE_GEMINI}]


class _FakeHub:
    def __init__(self, tmp_path):
        self.bus = EventBus()
        self.config = Config(data_dir=tmp_path)
        self.settings = S.SettingsStore(tmp_path / "settings.json", self.config)
        self.keys = _Keys()


def _client(tmp_path, **kw):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    hub = _FakeHub(tmp_path)
    calls = {"quit": 0, "installer": 0, "opened": []}

    async def quit_app():
        calls["quit"] += 1

    def installer():
        calls["installer"] += 1

    checker = kw.pop("checker", None) or UpdateChecker("1.0.0")
    app = FastAPI()
    app.include_router(make_router(
        hub, checker=checker, quit_app=quit_app, installer=installer,
        opener=lambda p: calls["opened"].append(p),
        downloads=lambda: tmp_path / "Downloads"))
    return TestClient(app), hub, calls


def test_get_app_reports_version_data_folder_and_first_run(tmp_path):
    client, _hub, _ = _client(tmp_path)
    body = client.get("/api/app").json()
    assert body["version"] == read_version() == "1.0.0"
    assert Path(body["data_dir"]) == tmp_path
    assert body["first_run"] is True
    assert body["update"] == {"available": False, "latest": None, "notes_url": None}
    assert client.get("/api/version").json() == {"version": "1.0.0"}


def test_update_check_is_faked_and_compared_by_number():
    calls = []

    async def fetch():
        calls.append(1)
        return {"tag": "v1.0.10", "url": "https://example.invalid/notes"}

    checker = UpdateChecker("1.0.9", fetch=fetch, interval_s=3600)
    checker.poke()                      # disabled: never fetches
    assert calls == [] and checker.due()
    asyncio.run(checker.check())
    assert checker.public() == {"available": True, "latest": "v1.0.10",
                                "notes_url": "https://example.invalid/notes"}
    assert not checker.due(now=checker.checked_at + 60)
    assert checker.due(now=checker.checked_at + 3600)
    assert UpdateChecker("1.0.10").available is False
    assert version_tuple("v2.1") > version_tuple("1.9.9")


def test_update_check_failure_keeps_the_last_answer():
    async def boom():
        raise OSError("offline")
    checker = UpdateChecker("1.0.0", fetch=boom)
    checker.latest = "v1.1.0"
    assert asyncio.run(checker.check())["available"] is True


def test_get_app_pokes_an_enabled_checker_in_the_background(tmp_path):
    seen = []

    async def fetch():
        seen.append(1)
        return {"tag": "v9.0.0", "url": "u"}
    checker = UpdateChecker("1.0.0", fetch=fetch)
    checker.enable()
    client, _hub, _ = _client(tmp_path, checker=checker)
    with client:
        client.get("/api/app")
        for _ in range(50):
            if checker.latest:
                break
            import time
            time.sleep(0.02)
        assert client.get("/api/app").json()["update"]["available"] is True
    assert seen == [1]                  # once, not on every request


def test_settings_routes(tmp_path, monkeypatch):
    monkeypatch.delenv("FURHAT_PASSWORD", raising=False)
    client, hub, _ = _client(tmp_path)
    q = hub.bus.subscribe()
    assert client.get("/api/settings").json()["save_transcripts"] is True
    r = client.put("/api/settings", json={"auto_connect": True})
    assert r.status_code == 200 and r.json()["auto_connect"] is True
    assert hub.config.auto_connect is True
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert any(e["type"] == "settings" and e["auto_connect"] is True for e in events)
    assert any(e["type"] == "log" and e["text"] == "auto-connect on" for e in events)

    bad = client.put("/api/settings", json={"auto_connect": "yes"})
    assert bad.status_code == 400 and bad.json()["code"] == "BAD_SETTING"
    assert client.put("/api/settings", json=[1]).status_code == 400

    r = client.put("/api/settings/password/furhat", json={"password": "studio"})
    assert r.status_code == 200
    assert r.json()["passwords"]["furhat"] == {"set": True, "works": None}
    assert hub.settings.password("furhat") == "studio"
    r = client.put("/api/settings/password/pepper", json={"password": "x"})
    assert r.status_code == 404 and r.json()["code"] == "UNKNOWN_ROBOT"
    assert client.put("/api/settings/password/furhat", json={}).status_code == 400


def test_transcripts_open(tmp_path):
    client, _hub, calls = _client(tmp_path)
    r = client.post("/api/transcripts/open")
    assert r.status_code == 200
    assert calls["opened"] == [tmp_path / "transcripts"]
    assert (tmp_path / "transcripts").is_dir()


def test_quit_and_update(tmp_path):
    client, _hub, calls = _client(tmp_path)
    assert client.post("/api/app/quit").json() == {"ok": True}
    assert calls["quit"] == 1
    assert client.post("/api/quit").status_code == 200
    assert calls["quit"] == 2
    assert client.post("/api/app/update").json() == {"ok": True}
    assert calls == {"quit": 3, "installer": 1, "opened": []}


def test_main_quit_stops_children_then_the_server(monkeypatch):
    from hub import main
    from hub import supervisor as SV

    stopped = []

    class Adapter:
        display_name = "x"

        async def stop_system(self):
            stopped.append("system")

    class Sup:
        async def stop_all(self):
            stopped.append("children")

    server = type("Srv", (), {"should_exit": False})()
    monkeypatch.setattr(main, "_server", server)
    monkeypatch.setattr(SV, "get_supervisor", lambda bus=None: Sup())
    monkeypatch.setattr(main.hub, "adapters", {"a": Adapter()})
    asyncio.run(main.quit_app())
    assert stopped == ["system", "children"] and server.should_exit is True


def test_log_report_zips_todays_logs_without_keys(tmp_path):
    client, hub, _ = _client(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    today = dt.date.today()
    (logs / applog.hub_log_name(today)).write_text(
        "launch with key {} and {}\n".format(FAKE_GEMINI, FAKE_OPENAI), encoding="utf-8")
    (logs / applog.hub_log_name(today - dt.timedelta(days=1))).write_text("old\n")
    (logs / "group-{}-101500.jsonl".format(today.strftime("%Y%m%d"))).write_text(
        json.dumps({"text": "hi", "k": FAKE_GEMINI}) + "\n", encoding="utf-8")
    hub.bus.emit_log("info", "activity line")
    r = client.post("/api/log/report")
    assert r.status_code == 200
    path = Path(r.json()["path"])
    assert path.parent == tmp_path / "Downloads" and path.suffix == ".zip"
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert applog.hub_log_name(today) in names
        assert applog.hub_log_name(today - dt.timedelta(days=1)) not in names
        assert any(n.startswith("group-") for n in names)
        assert {"about.txt", "activity.txt"} <= names
        everything = "".join(zf.read(n).decode("utf-8") for n in names)
    assert FAKE_GEMINI not in everything and FAKE_OPENAI not in everything
    assert keyscrub.KEY_MARK in everything and "activity line" in everything


# -------------------------------------------------------------------- logs
def test_daily_log_switches_files_and_keeps_14_days(tmp_path):
    days = [dt.date(2026, 11, 5)]
    old = tmp_path / applog.hub_log_name(dt.date(2026, 10, 1))
    keep = tmp_path / applog.hub_log_name(dt.date(2026, 10, 25))
    other = tmp_path / "group-20261001-101010.jsonl"
    for p in (old, keep, other):
        p.write_text("x")
    handler = applog.DailyFileHandler(tmp_path, today=lambda: days[0])
    handler.setFormatter(logging.Formatter("%(message)s"))
    try:
        assert not old.exists() and keep.exists() and other.exists()
        rec = logging.LogRecord("t", logging.INFO, "", 0, "first day", None, None)
        handler.emit(rec)
        days[0] = dt.date(2026, 11, 6)
        handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "second day", None, None))
        # uvicorn's dictConfig closes existing handlers but leaves them attached.
        handler.close()
        handler.emit(logging.LogRecord("t", logging.INFO, "", 0, "after close", None, None))
    finally:
        handler.close()
    assert (tmp_path / "hub-2026-11-05.log").read_text().strip() == "first day"
    assert (tmp_path / "hub-2026-11-06.log").read_text().split() == [
        "second", "day", "after", "close"]


def test_group_warnings_reach_the_bus_scrubbed_from_any_thread():
    bus = EventBus()

    async def go():
        q = bus.subscribe()
        handler = applog.forward_to_bus(bus, "hub.group.test", "group")
        lg = logging.getLogger("hub.group.test")
        try:
            lg.info("not forwarded")
            lg.warning("warm-up failed with %s", FAKE_GEMINI)
            t = threading.Thread(target=lambda: lg.error("from a thread"))
            t.start()
            t.join()
            await asyncio.sleep(0.05)
        finally:
            lg.removeHandler(handler)
        return [q.get_nowait() for _ in range(q.qsize())]

    events = asyncio.run(go())
    assert [(e["level"], e["source"]) for e in events] == [("warn", "group"), ("error", "group")]
    assert FAKE_GEMINI not in events[0]["text"] and keyscrub.KEY_MARK in events[0]["text"]
    assert bus.recent()[-1]["text"] == "from a thread"


def test_scrub_text():
    line = "GEMINI={} OPENAI={} task-runner-abcdefghijklmnopqrstuvwxyz".format(
        FAKE_GEMINI, FAKE_OPENAI)
    out = keyscrub.scrub_text(line)
    assert FAKE_GEMINI not in out and FAKE_OPENAI not in out
    assert "task-runner-abcdefghijklmnopqrstuvwxyz" in out
    assert keyscrub.scrub_text("pw=averyspecificsecretvalue!", ["averyspecificsecretvalue!"]) \
        == "pw=" + keyscrub.KEY_MARK


# ------------------------------------------------------------ child procs
def test_children_get_no_window_flag():
    if sys.platform == "win32":
        assert winproc.no_window() == {"creationflags": subprocess.CREATE_NO_WINDOW}
        flags = winproc.no_window(subprocess.CREATE_NEW_PROCESS_GROUP)["creationflags"]
        assert flags & subprocess.CREATE_NO_WINDOW and flags & subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        assert winproc.no_window() == {}


def test_supervisor_blanks_keys_in_child_output(tmp_path):
    from hub.supervisor import Supervisor, child_env

    bus = EventBus()
    sup = Supervisor(bus)

    async def go():
        env = child_env(overrides={"GEMINI_API_KEY": "not-a-pattern-but-a-secret-1234"})
        await sup.start("t", [PY, "-c",
                              "import os; print('key', os.environ['GEMINI_API_KEY']);"
                              "print('and {}')".format(FAKE_OPENAI)],
                        cwd=tmp_path, env=env)
        await sup.wait_for_exit("t", 30)
        await asyncio.sleep(0.2)
        await sup.stop("t")

    asyncio.run(go())
    lines = [e["text"] for e in bus.recent() if e["text"].startswith("t: ")]
    assert any("key " + keyscrub.KEY_MARK in line for line in lines), lines
    assert not any("not-a-pattern-but-a-secret-1234" in line or FAKE_OPENAI in line
                   for line in lines)


def test_hub_python_prefers_the_console_build(monkeypatch, tmp_path):
    (tmp_path / "pythonw.exe").write_text("")
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert winproc.hub_python() == tmp_path / "python.exe"


# ------------------------------------------------------------- reachy deploy
def test_reachy_deploy_uses_the_hubs_python_without_a_venv(monkeypatch, tmp_path):
    from hub.adapters import reachy_wireless as rw
    from hub.adapters.base import Found

    root = tmp_path / "reachy_chat"
    (root / "tools").mkdir(parents=True)
    cfg = Config(robots={"reachy_wireless": RobotCfg(settings={
        "reachy_chat_path": str(root), "python": "", "ssh_password": "robot-pass"})})
    a = rw.ReachyWirelessAdapter(Found(type_id="reachy_wireless", address="10.0.0.9",
                                       port=8000, meta={"unit_id": "u1"}), cfg)
    assert a._deploy_python(root) == winproc.hub_python()
    seen = {}

    class Proc:
        returncode = 0

    async def fake_exec(*argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return Proc()

    async def fake_comm(proc, timeout):
        return b"ok", b""

    monkeypatch.setattr(rw.asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(rw, "communicate_or_kill", fake_comm)
    asyncio.run(a._provision_robot())
    assert seen["argv"][:4] == (str(winproc.hub_python()),
                                str(root / "tools" / "deploy_robot_app.py"),
                                "--robot-host", "10.0.0.9")
    assert seen["kw"]["env"]["ROBOT_PASSWORD"] == "robot-pass"
    if sys.platform == "win32":
        assert seen["kw"]["creationflags"] & subprocess.CREATE_NO_WINDOW

    # A python that was set but is missing is still an error, not a fallback.
    cfg.robots["reachy_wireless"].settings["python"] = str(tmp_path / "nope.exe")
    from hub.adapters.base import AdapterUnavailable
    with pytest.raises(AdapterUnavailable):
        a._deploy_python(root)


# ------------------------------------------------------------- hub and keys
def test_hub_keeps_keys_in_the_data_folder_and_seeds_none(tmp_path, monkeypatch):
    from hub.core import Hub
    monkeypatch.setattr(S, "_CURRENT", S.current())     # restored after the test
    chat = tmp_path / "chat"
    chat.mkdir()
    (tmp_path / "reachy-mini llm gemini token.txt").write_text(FAKE_GEMINI)
    cfg = Config(data_dir=tmp_path / "data", robots={"reachy_wireless": RobotCfg(
        settings={"reachy_chat_path": str(chat)})})
    hub = Hub(cfg)
    assert hub.keys.path == tmp_path / "data" / "keys.local.json"
    assert not hasattr(hub, "_seed_keys")
    assert hub.keys.public()["keys"] == []


def test_no_paid_warm_up_at_hub_start(monkeypatch):
    from hub.group import conductor as C
    from hub import laptop_mic

    class FakeHub:
        def __init__(self):
            self.bus = EventBus()
            self.config = Config()
            self.registry = type("R", (), {"all": lambda self: [], "get": lambda self, k: None})()
            self.adapters = {}

    gm = C.GroupManager.__new__(C.GroupManager)
    gm._loop = None
    gm._keeper_task = None
    gm._startup_warm = None
    warmed = []

    async def warm_up(full=True):
        warmed.append(full)

    async def keep():
        await asyncio.sleep(3600)

    monkeypatch.setattr(gm, "warm_up", warm_up, raising=False)
    monkeypatch.setattr(gm, "_keep_warm", keep, raising=False)
    monkeypatch.setattr(laptop_mic.MIC_WATCH, "start", lambda: None)

    async def go():
        await gm.startup()
        await asyncio.sleep(0)
        gm._keeper_task.cancel()
    asyncio.run(go())
    assert warmed == [] and gm._startup_warm is None


# --------------------------------------------------------- single instance
def test_port_owner_tells_free_hub_and_other_apart():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert port_owner("127.0.0.1", port, timeout_s=0.5) is None

    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Hubby(BaseHTTPRequestHandler):
        body = b'{"version": "1.0.0"}'

        def do_GET(self):
            self.send_response(200 if self.path == "/api/app" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.body)

        def log_message(self, *a):
            pass

    class Other(Hubby):
        body = b"<html></html>"

    for handler, expected in ((Hubby, "hub"), (Other, "other")):
        srv = HTTPServer(("127.0.0.1", 0), handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            assert port_owner("127.0.0.1", srv.server_address[1]) == expected
        finally:
            srv.shutdown()
            srv.server_close()


def test_update_check_only_counts_app_releases():
    from hub.app_api import pick_app_release
    releases = [
        {"tag_name": "robot-files", "assets": [{"name": "dance.json"}], "html_url": "x"},
        {"tag_name": "v1.0.0", "assets": [{"name": "RobotHub-1.0.0.zip"}], "html_url": "a"},
        {"tag_name": "v1.2.0", "draft": True, "assets": [{"name": "RobotHub-1.2.0.zip"}]},
        {"tag_name": "v1.1.0", "assets": [{"name": "RobotHub-1.1.0.zip"}], "html_url": "b"},
        {"tag_name": "v9.0.0", "assets": [{"name": "notes.txt"}]},
    ]
    assert pick_app_release(releases) == {"tag": "v1.1.0", "url": "b"}
    assert pick_app_release([]) == {}
