"""Work package A2: keys with free test calls, setup items (the NAO/Pepper kit),
the network state, the new robot-card fields and Add WiFi options.

No network, no robots: every HTTP call, download, dialog and SSH session is a
fake.
"""

from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import config as config_mod  # noqa: E402
from hub import inuse, keycheck, network, requirements  # noqa: E402
from hub.adapters.base import AdapterUnavailable, Found  # noqa: E402
from hub.adapters.reachy_common import find_battery  # noqa: E402
from hub.config import load_config  # noqa: E402
from hub.core import ActionError, Hub  # noqa: E402
from hub.keys import KeyStore  # noqa: E402
from hub import registry as R  # noqa: E402

OAI = "sk-proj-OPENAIsecretvalue000000001111"
GEM = "AIzaSyGEMINIsecretvalue00000002222"
ELV = "sk_elevenSECRETvalue0000000003333"
ORT = "sk-or-v1-openrouterSECRET000004444"
QWN = "sk-qwenDASHSCOPEsecret00000005555"


def run(coro):
    return asyncio.run(_await(coro))


async def _await(coro):
    return await coro


class FakeHTTP:
    """url -> (status, body) or an exception; records every call."""

    def __init__(self, table=None, default=(200, {"data": []})):
        self.table = table or {}
        self.default = default
        self.calls = []

    async def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        for prefix, answer in self.table.items():
            if url.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return self.default


@pytest.fixture(autouse=True)
def no_kit(monkeypatch, tmp_path):
    """No NAO/Pepper kit on this 'laptop' unless a test installs one."""
    kit = tmp_path / "LabaLab" / "naoqi-sdk"
    monkeypatch.setattr(config_mod, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.setattr(requirements, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    return kit


@pytest.fixture
def hub(tmp_path):
    cfg = load_config(data=tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    cfg.auto_connect = False
    h = Hub(cfg)
    h.key_transport = FakeHTTP()
    return h


# =================================================================== keys
def test_clean_and_detect():
    assert keycheck.clean('  "Bearer {}"\n'.format(OAI)) == OAI
    assert keycheck.clean("OPENAI_API_KEY={}".format(OAI)) == OAI
    assert keycheck.detect(ORT) == ["openrouter"]
    assert keycheck.detect(ELV) == ["elevenlabs"]
    assert keycheck.detect(GEM) == ["gemini"]
    assert keycheck.detect(OAI) == ["gpt", "qwen"]
    assert keycheck.detect("abcdefghijklmnopqrstuvwxyz") == []
    assert not keycheck.looks_like_a_key("hello")
    assert not keycheck.looks_like_a_key("not a key at all, just words")


@pytest.mark.parametrize("provider,answer,state", [
    ("gpt", (200, {"data": []}), "works"),
    ("gpt", (401, {"error": {"code": "invalid_api_key"}}), "bad"),
    ("gpt", (429, {"error": {"code": "insufficient_quota"}}), "no_credit"),
    ("gemini", (400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}), "bad"),
    ("gemini", (200, {"models": []}), "works"),
    ("openrouter", (200, {"data": {"limit": 5, "limit_remaining": 4.2}}), "works"),
    ("openrouter", (200, {"data": {"limit": 5, "limit_remaining": 0}}), "no_credit"),
    ("openrouter", (401, {}), "bad"),
    ("elevenlabs", (200, {"character_count": 100, "character_limit": 10000}), "works"),
    ("elevenlabs", (401, {"detail": {"status": "quota_exceeded"}}), "no_credit"),
    ("elevenlabs", (401, {"detail": {"status": "invalid_api_key"}}), "bad"),
    ("elevenlabs", (401, {"detail": {"status": "missing_permissions"}}), "works"),
    ("gpt", (500, "oops"), "unknown"),
])
def test_one_free_call_per_provider(provider, answer, state):
    http = FakeHTTP(default=answer)
    result = run(keycheck.check(provider, "x" * 30, http))
    assert result["state"] == state and result["checked_at"]
    assert len(http.calls) == 1 and "GET" not in http.calls[0][0]


def test_openrouter_reports_credit_and_elevenlabs_characters():
    r = run(keycheck.check("openrouter", ORT, FakeHTTP(
        default=(200, {"data": {"limit": 5, "limit_remaining": 4.2}}))))
    assert r["credit"] == {"left": 4.2, "limit": 5.0, "unit": "usd"}
    assert r["detail"] == "$4.20 left of $5."
    r = run(keycheck.check("elevenlabs", ELV, FakeHTTP(
        default=(200, {"character_count": 2500, "character_limit": 10000}))))
    assert r["credit"]["left"] == 7500 and "7,500 characters" in r["detail"]


def test_a_network_error_is_offline_never_bad():
    r = run(keycheck.check("gpt", OAI, FakeHTTP(default=None, table={
        "https://": keycheck.Offline("no route")})))
    assert r["state"] == "offline" and "Can't reach OpenAI" in r["detail"]


def test_qwen_tries_the_second_region():
    http = FakeHTTP(table={keycheck.QWEN_MODELS[0]: (401, {}),
                           keycheck.QWEN_MODELS[1]: (200, {"data": []})})
    assert run(keycheck.check("qwen", QWN, http))["state"] == "works"
    assert len(http.calls) == 2


def test_add_key_detects_tests_and_saves(hub):
    hub.key_transport = FakeHTTP()
    out = run(hub.add_key("auto", "", GEM))
    assert out["ok"] and out["key"]["provider"] == "gemini"
    assert out["key"]["status"]["state"] == "works"
    assert GEM not in json.dumps(out)
    assert hub.key_transport.calls[0][1] == {"x-goog-api-key": GEM}


@pytest.mark.parametrize("raw,provider,code", [
    ("hello", "auto", "NOT_A_KEY"),
    ("abcdefghijklmnopqrstuvwxyz0123", "auto", "UNKNOWN_PROVIDER"),
    ("abcdefghijklmnopqrstuvwxyz0123", "claude", "UNKNOWN_PROVIDER"),
])
def test_add_key_refusals(hub, raw, provider, code):
    with pytest.raises(ActionError) as exc:
        run(hub.add_key(provider, "", raw))
    assert exc.value.code == code
    if code == "UNKNOWN_PROVIDER":
        assert "qwen" in exc.value.body()["candidates"]


def test_add_key_duplicate_and_refused(hub):
    run(hub.add_key("auto", "", GEM))
    with pytest.raises(ActionError) as exc:
        run(hub.add_key("gemini", "", " " + GEM + " "))
    assert exc.value.code == "DUPLICATE"
    assert exc.value.body()["label"]
    hub.key_transport = FakeHTTP(default=(401, {}))
    with pytest.raises(ActionError) as exc:
        run(hub.add_key("auto", "", OAI))
    assert exc.value.code == "KEY_REFUSED"
    assert hub.keys.public()["keys"] and len(hub.keys.public()["keys"]) == 1


def test_an_sk_key_openai_refuses_is_tried_as_qwen(hub):
    hub.key_transport = FakeHTTP(table={keycheck.OPENAI_MODELS: (401, {})})
    out = run(hub.add_key("auto", "", QWN))
    assert out["key"]["provider"] == "qwen"


def test_no_internet_still_saves_the_key_as_offline(hub):
    hub.key_transport = FakeHTTP(table={"https://": keycheck.Offline("down")})
    out = run(hub.add_key("auto", "My key", OAI))
    assert out["key"]["provider"] == "gpt" and out["key"]["status"]["state"] == "offline"


def test_keys_api_shape(hub):
    from fastapi.testclient import TestClient
    app = _app_for(hub)
    client = TestClient(app)
    added = client.post("/api/keys", json={"key": ELV}).json()
    assert added["ok"] and added["key"]["voice_only"] is True
    r = client.post("/api/keys", json={"key": ELV})
    assert r.status_code == 400 and r.json()["code"] == "DUPLICATE"
    r = client.post("/api/keys", json={"key": "nope"})
    assert r.status_code == 400 and r.json()["code"] == "NOT_A_KEY"
    client.post("/api/keys", json={"key": ORT})
    listed = client.get("/api/keys").json()
    assert {p["id"] for p in listed["providers"]} >= {"gemini", "gpt", "elevenlabs",
                                                       "openrouter", "qwen"}
    talk = {p["id"]: p["can_talk"] for p in listed["providers"]}
    assert talk["gpt"] and talk["gemini"] and not talk["elevenlabs"] and not talk["qwen"]
    row = next(k for k in listed["keys"] if k["provider"] == "openrouter")
    assert row["groups_only"] and not row["voice_only"] and row["used_by"] == []
    assert set(row["status"]) >= {"state", "detail", "credit", "checked_at"}
    assert ELV not in json.dumps(listed) and ORT not in json.dumps(listed)
    kid = row["id"]
    r = client.post("/api/keys/{}/check".format(kid))
    assert r.status_code == 200 and r.json()["key"]["status"]["state"] == "works"
    assert client.post("/api/keys/nope/check").json()["code"] == "UNKNOWN_KEY"
    assert client.delete("/api/keys/nope").status_code == 404
    assert client.delete("/api/keys/" + kid).json()["ok"]


def _app_for(hub):
    from fastapi import FastAPI
    from hub.features_api import make_router
    app = FastAPI()
    app.include_router(make_router(hub, wifi_opener=lambda: None))
    return app


def test_pepper_slots_default_to_gpt_and_elevenlabs(hub):
    run(hub.add_key("auto", "Lab Gemini", GEM))
    gpt = run(hub.add_key("auto", "Lab OpenAI", OAI))["key"]["id"]
    run(hub.add_key("auto", "Lab ElevenLabs", ELV))
    hub.registry.upsert("pepper:p1", type_id="pepper", name="Pepper")
    entry, how = hub.keys.for_robot("pepper:p1", "pepper")
    assert entry["id"] == gpt and "first GPT" in how      # never the first Gemini key
    env = hub.keys.env_for_robot("pepper:p1", "pepper")
    assert env["OPENAI_API_KEY"] == OAI and env["ELEVENLABS_API_KEY"] == ELV
    with pytest.raises(ActionError) as exc:                 # a Gemini key on Pepper
        hub.assign_key("pepper:p1", hub.keys.public()["keys"][0]["id"], "main")
    assert exc.value.code == "WRONG_PROVIDER"
    with pytest.raises(ActionError) as exc:
        hub.assign_key("pepper:p1", gpt, "voice")
    assert exc.value.code == "WRONG_PROVIDER"


def test_pepper_launch_gets_the_keys_from_its_slots(hub):
    run(hub.add_key("auto", "First OpenAI", OAI))
    second = run(hub.add_key("gpt", "Second OpenAI", "sk-proj-SECONDopenai00000000009999"))["key"]["id"]
    voice = run(hub.add_key("auto", "Lab ElevenLabs", ELV))["key"]["id"]
    hub.registry.upsert("pepper:p1", type_id="pepper", name="Pepper")
    hub.adapters["pepper:p1"] = _Recorder(uses_speech_key=True)
    hub.registry.set_state("pepper:p1", R.CONNECTED)
    hub.assign_key("pepper:p1", second, "main")
    hub.assign_key("pepper:p1", voice, "voice")
    assert run(hub.launch("pepper:p1"))["ok"]
    env = hub.adapters["pepper:p1"].provider_env
    assert env["OPENAI_API_KEY"].startswith("sk-proj-SECOND")
    assert env["ELEVENLABS_API_KEY"] == ELV
    slots = hub.keys_event()["slots"]["pepper:p1"]
    assert slots["main"]["assigned"] == second and slots["voice"]["assigned"] == voice


def test_furhat_main_slot_is_stored_and_reported(hub):
    gpt = run(hub.add_key("auto", "", OAI))["key"]["id"]
    hub.registry.upsert("furhat-1", type_id="furhat", name="Furhat")
    hub.assign_key("furhat-1", gpt, "main")
    event = hub.keys_event()
    assert event["assign"]["furhat-1"] == {"main": gpt}
    assert event["slots"]["furhat-1"]["main"]["key"]["id"] == gpt
    assert "Furhat" in next(k for k in event["keys"] if k["id"] == gpt)["used_by"]
    with pytest.raises(ActionError):
        hub.assign_key("furhat-1", gpt, "voice")        # Furhat has no voice slot


def test_old_keys_file_still_reads_and_main_only_is_written_back_as_text(tmp_path):
    path = tmp_path / "keys.local.json"
    path.write_text(json.dumps({"keys": [{"id": "k1", "provider": "gpt", "label": "OpenAI",
                                          "key": OAI}],
                                "assign": {"robotA": "k1"}}), encoding="utf-8")
    store = KeyStore(path)
    assert store.for_robot("robotA")[0]["key"] == OAI
    assert store.public()["assign"] == {"robotA": {"main": "k1"}}
    assert store.public()["keys"][0]["status"]["state"] == "unknown"
    store.assign("robotB", "k1")
    on_disk = json.loads(path.read_text(encoding="utf-8"))["assign"]
    assert on_disk == {"robotA": "k1", "robotB": "k1"}     # an older hub reads this


def test_background_check_only_rechecks_stale_keys(hub):
    run(hub.add_key("auto", "", GEM))
    hub.key_transport = FakeHTTP()
    assert run(hub.check_keys(3600)) == 0                  # just checked
    assert run(hub.check_keys(0)) == 1


def test_a_recheck_while_offline_keeps_what_was_known(hub):
    kid = run(hub.add_key("auto", "", GEM))["key"]["id"]
    hub.key_transport = FakeHTTP(table={"https://": keycheck.Offline("down")})
    out = run(hub.check_key(kid))
    assert out["key"]["status"]["state"] == "works"


def test_no_key_check_runs_at_import_or_construction(tmp_path):
    cfg = load_config(data=tmp_path)
    h = Hub(cfg)
    assert h._key_task is None


# ================================================================== setup
def _kit_zip(path: Path, doubled: bool = True, extra=None) -> Path:
    top = "pynaoqi-python2.7-2.8.7.4-win64-vs2015-20210818_210634/"
    inner = top + top if doubled else top
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(inner + "lib/naoqi.py", "# naoqi\n")
        zf.writestr(inner + "lib/python2.7/os.py", "#\n")
        zf.writestr(inner + "bin/python.exe", "MZ")
        zf.writestr(inner + "bin/python", "#!")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def _manager(tmp_path, kit, **kw):
    cfg = load_config(data=tmp_path / "data")
    events = []

    class Bus:
        def publish(self, e):
            events.append(e)

        def emit_log(self, level, text, **_):
            events.append({"type": "log", "level": level, "text": text})

    kw.setdefault("verifier", lambda paths: (True, "Installed."))
    m = requirements.SetupManager(cfg, Bus(), None, kit_dirs=[kit], **kw)
    return m, events


def test_setup_items_have_the_contract_shape(tmp_path, no_kit):
    m, _ = _manager(tmp_path, no_kit, find_control_app=lambda: None)
    items = {i["id"]: i for i in m.items()}
    assert set(items) == {"naoqi_kit", "reachy_lite_app", "furhat_password"}
    kit = items["naoqi_kit"]
    assert kit["state"] == "missing" and kit["for"] == ["naoqi", "pepper"]
    assert {"download", "choose_zip", "open", "check"} <= set(kit["actions"])
    assert set(kit) == {"id", "label", "for", "state", "progress", "detail", "code", "actions"}
    assert items["reachy_lite_app"]["state"] == "missing"


def test_download_unpacks_verifies_and_reports_progress(tmp_path, no_kit):
    async def download(url, dest, progress):
        assert url == requirements.NAOQI_KIT_URL
        _kit_zip(dest)
        progress(100, 200)
        progress(200, 200)

    m, events = _manager(tmp_path, no_kit, downloader=download)

    async def go():
        m.start_download()
        assert m.item("naoqi_kit")["state"] in ("downloading", "unpacking", "verifying", "ok")
        await m.wait()
    run(go())
    item = m.item("naoqi_kit")
    assert item["state"] == "ok", item
    found = config_mod.find_naoqi_kit([no_kit])
    assert found["python2"].name == "python.exe" and (found["pynaoqi_sdk"] / "lib").is_dir()
    phases = [e["item"]["state"] for e in events if e.get("type") == "setup"]
    assert "downloading" in phases and "unpacking" in phases and phases[-1] == "ok"
    assert not list((tmp_path / "data" / "cache").glob("*.zip*"))   # no leftovers


def test_a_broken_download_and_a_full_disk_have_codes(tmp_path, no_kit):
    async def broke(url, dest, progress):
        raise requirements.DownloadBroke("connection reset")

    m, _ = _manager(tmp_path, no_kit, downloader=broke)

    async def go():
        m.start_download()
        await m.wait()
    run(go())
    assert m.item("naoqi_kit")["code"] == "DOWNLOAD_BROKE"

    m, _ = _manager(tmp_path, no_kit, downloader=broke, free_bytes=lambda p: 10)
    run(_start_and_wait(m))
    assert m.item("naoqi_kit")["code"] == "DISK_FULL"


async def _start_and_wait(m):
    m.start_download()
    await m.wait()


def test_a_wrong_zip_is_refused(tmp_path, no_kit):
    not_a_zip = tmp_path / "x.zip"
    not_a_zip.write_bytes(b"hello")
    m, _ = _manager(tmp_path, no_kit, file_dialog=lambda: str(not_a_zip))

    async def go():
        await m.choose_zip()
        await m.wait()
    run(go())
    assert m.item("naoqi_kit")["code"] == "WRONG_ZIP"

    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("readme.txt", "not the kit")
    m, _ = _manager(tmp_path, no_kit, file_dialog=lambda: str(other))
    run(go())
    assert m.item("naoqi_kit")["code"] == "WRONG_ZIP"
    assert not no_kit.exists()


def test_zip_slip_is_refused(tmp_path):
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("kit/lib/naoqi.py", "#")
        zf.writestr("../../escaped.txt", "gotcha")
    with pytest.raises(requirements.WrongZip):
        requirements.unpack_zip(evil, tmp_path / "out", lambda d, t: None)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_choose_zip_installs_the_chosen_file(tmp_path, no_kit):
    z = _kit_zip(tmp_path / "kit.zip", doubled=False)
    m, _ = _manager(tmp_path, no_kit, file_dialog=lambda: str(z))

    async def go():
        out = await m.choose_zip()
        assert out["chosen"] == "kit.zip"
        await m.wait()
    run(go())
    assert m.item("naoqi_kit")["state"] == "ok"
    assert z.exists()                         # the student's own file is kept


def test_a_kit_that_does_not_import_is_failed_on_check(tmp_path, no_kit):
    z = _kit_zip(tmp_path / "kit.zip")
    requirements.unpack_zip(z, no_kit, lambda d, t: None)
    m, _ = _manager(tmp_path, no_kit, verifier=lambda p: (False, "naoqi does not load"))
    assert m.item("naoqi_kit")["state"] == "ok"          # cheap check: files are there
    item = run(m.check("naoqi_kit"))
    assert item["state"] == "failed" and item["code"] == "KIT_BROKEN"


def test_cancel_stops_the_download_and_leaves_nothing(tmp_path, no_kit):
    async def slow(url, dest, progress):
        dest.write_bytes(b"partial")
        progress(1, 100)
        await asyncio.sleep(30)

    m, _ = _manager(tmp_path, no_kit, downloader=slow)

    async def go():
        m.start_download()
        await asyncio.sleep(0.05)
        await m.cancel()
    run(go())
    assert m.item("naoqi_kit")["state"] == "missing"
    assert not list((tmp_path / "data" / "cache").glob("*.part"))


def test_open_and_reachy_app_detection(tmp_path, no_kit):
    opened = []
    exe = tmp_path / "Reachy Mini Control.exe"
    exe.write_bytes(b"MZ")
    m, _ = _manager(tmp_path, no_kit, opener=opened.append, find_control_app=lambda: exe)
    assert m.item("reachy_lite_app")["state"] == "ok"
    run(m.act("naoqi_kit", "open"))
    run(m.act("reachy_lite_app", "open"))
    assert opened == [requirements.NAOQI_KIT_PAGE, requirements.REACHY_APP_PAGE]
    with pytest.raises(requirements.SetupError) as exc:
        run(m.act("nope", "check"))
    assert exc.value.code == "UNKNOWN_SETUP"
    with pytest.raises(requirements.SetupError):
        run(m.act("furhat_password", "download"))


def test_furhat_password_item_follows_settings(hub):
    item = hub.setup.item("furhat_password")
    assert item["state"] == "ok" and item["detail"] == "Used at the next Connect."
    hub.settings.note_login("furhat", False)
    assert hub.setup.item("furhat_password")["code"] == "PASSWORD_WRONG"


def test_setup_routes(hub):
    from fastapi.testclient import TestClient
    client = TestClient(_app_for(hub))
    items = client.get("/api/setup").json()["items"]
    assert [i["id"] for i in items] == ["naoqi_kit", "reachy_lite_app", "furhat_password"]
    r = client.post("/api/setup/nope/check")
    assert r.status_code == 404 and r.json()["code"] == "UNKNOWN_SETUP"
    r = client.post("/api/setup/naoqi_kit/explode")
    assert r.status_code == 400 and r.json()["code"] == "BAD_ACTION"
    r = client.post("/api/setup/naoqi_kit/check")
    assert r.json()["item"]["state"] == "missing"


def test_nao_without_the_kit_gets_a_needs_setup_card(hub, no_kit):
    ph = hub.registry.get("placeholder:naoqi")
    assert ph.needs_setup == "naoqi_kit" and hub.registry.get("placeholder:pepper").needs_setup
    assert hub.registry.get("placeholder:furhat").needs_setup is None
    hub._on_found(Found(type_id="naoqi", address="10.0.4.40", port=9559,
                        meta={"needs_setup": "naoqi_kit", "source": "netscan"}))
    ph = hub.registry.get("placeholder:naoqi")
    assert ph.state == R.DISABLED and ph.needs_setup == "naoqi_kit"
    assert ph.address == "10.0.4.40" and "Set up" in ph.detail
    hub._on_lost("naoqi", "naoqi:unnamed")
    ph = hub.registry.get("placeholder:naoqi")
    assert ph.state == R.ABSENT and ph.needs_setup == "naoqi_kit"

    # The kit arrives: the cards drop "needs setup" without a restart.
    no_kit.parent.mkdir(parents=True, exist_ok=True)
    requirements.unpack_zip(_kit_zip(no_kit.parent / "k.zip"), no_kit, lambda d, t: None)
    hub._setup_changed()
    assert hub.registry.get("placeholder:naoqi").needs_setup is None


def test_the_naoqi_adapter_finds_the_kit_without_config(no_kit, tmp_path):
    from hub.adapters.naoqi import NaoqiAdapter
    cfg = load_config(data=tmp_path / "d")
    with pytest.raises(AdapterUnavailable) as exc:
        NaoqiAdapter(Found(type_id="naoqi", address="10.0.0.9"), cfg)
    assert exc.value.requirement == "naoqi_kit"
    requirements.unpack_zip(_kit_zip(tmp_path / "k.zip"), no_kit, lambda d, t: None)
    adapter = NaoqiAdapter(Found(type_id="naoqi", address="10.0.0.9"), cfg)
    assert adapter._python2.name == "python.exe"
    assert adapter._env()["PYTHONHOME"].endswith("python2.7")


def test_netscan_reports_a_naoqi_robot_it_cannot_identify(tmp_path):
    from hub.discovery.netscan import NetscanDetector
    from hub.events import EventBus
    cfg = load_config(data=tmp_path)
    seen = []
    det = NetscanDetector(cfg, EventBus(), seen.append)

    async def go():
        async def port_open(ip, port, sem=None):
            return port == 9559
        det._port_open = port_open
        det._reachy_status = lambda client, ip, sem=None: _none()
        await det._other_robots(None, ["10.0.4.40"])
    run(go())
    assert seen and seen[0].type_id == "naoqi"
    assert seen[0].meta["needs_setup"] == "naoqi_kit"
    det.forget_naoqi_misses()
    assert "10.0.4.40" not in det._robots


async def _none():
    return None


# ================================================================ network
WIFI_LAB = {"ssid": "HOT-WiFi", "band": "2.4 GHz", "kind": "lab", "hotspot": "lab"}


@pytest.mark.parametrize("kw,state", [
    (dict(wifi={}, interfaces=[]), "no_network"),
    (dict(wifi=WIFI_LAB, robots=[{"type_id": "reachy_wireless"}]), "ok"),
    (dict(wifi=WIFI_LAB, vpn=["Tailscale"]), "vpn_on"),
    (dict(wifi={"ssid": "Dana Phone", "band": "5 GHz", "kind": "hotspot"}), "hotspot_5ghz"),
    (dict(wifi={"ssid": "eduroam", "band": "5 GHz", "kind": "other"}), "wrong_network"),
    (dict(wifi={"ssid": "Dana Phone", "band": "2.4 GHz", "kind": "hotspot"}, sweeps=3), "ok"),
    (dict(wifi={"ssid": "Home", "kind": "other"},
          robots_network={"ssid": "Dana Phone", "last_seen": 1.0}), "wrong_network"),
    (dict(wifi={"ssid": None, "kind": "other"}, sweeps=3, alive=4), "ok"),
    (dict(wifi=WIFI_LAB, sweeps=0), "searching"),
    (dict(wifi=WIFI_LAB, sweeps=2, alive=0, ranges=["172.19.84.0/24"]), "isolated"),
    (dict(wifi=WIFI_LAB, sweeps=2, alive=7, ranges=["172.19.84.0/24"]), "ok"),
])
def test_network_states(kw, state):
    args = dict(wifi={}, interfaces=["10.0.4.5/24"], vpn=[], robots=[],
                robots_network=None, lab_wifi="HOT-WiFi", sweeps=2, alive=3,
                ranges=["10.0.4.0/24"])
    args.update(kw)
    out = network.compute(**args)
    assert out["state"] == state, out
    assert set(out) >= {"state", "ssid", "band", "kind", "ranges", "hotspot", "robots_network"}


def test_hotspot_counts_the_laptop_and_pepper_twice():
    out = network.compute(wifi={"ssid": "Dana Phone", "band": "2.4 GHz", "kind": "hotspot"},
                          interfaces=["172.20.10.3/28"], vpn=[], robots=[
                              {"type_id": "pepper"}, {"type_id": "reachy_wireless"},
                              {"type_id": "reachy_wireless"}, {"type_id": "reachy_lite"}],
                          robots_network=None, lab_wifi="HOT-WiFi")
    assert out["hotspot"] == {"devices": 5, "limit": 5}


def test_hub_network_remembers_where_robots_were(hub):
    hub.wifi_reader = lambda: {"wifi": {"ssid": "HOT-WiFi", "band": "2.4 GHz",
                                        "kind": "lab", "hotspot": "lab"},
                               "interfaces": ["172.19.84.41/16"], "vpn": []}
    hub.registry.upsert("u1", type_id="reachy_wireless", name="reachy1",
                        address="172.19.84.50", state=R.DETECTED)
    q = hub.bus.subscribe()
    out = run(hub.refresh_network())
    assert out["state"] == "ok" and out["kind"] == "lab"
    assert hub.settings.get("robots_network")["ssid"] == "HOT-WiFi"
    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert any(e["type"] == "network" and e["state"] == "ok" for e in events)
    assert "on_robot_subnet" in out          # the old banner still works


def test_network_routes(hub):
    from fastapi.testclient import TestClient
    hub.wifi_reader = lambda: {"wifi": {"ssid": "eduroam", "kind": "other"},
                               "interfaces": ["10.12.0.5/16"], "vpn": []}
    client = TestClient(_app_for(hub))
    body = client.get("/api/network").json()
    assert body["state"] == "wrong_network" and body["ssid"] == "eduroam"
    assert client.post("/api/network/open_wifi_settings").json()["ok"]


def test_vpn_and_virtual_adapters_are_not_swept(monkeypatch):
    import socket
    import types
    from hub.discovery import netscan, selfnet
    assert selfnet.is_vpn_adapter("Tailscale") and selfnet.is_vpn_adapter("Check Point Virtual Network Adapter")
    assert selfnet.is_virtual_adapter("vEthernet (WSL)") and not selfnet.is_vpn_adapter("Wi-Fi")

    def addr(ip, mask):
        return types.SimpleNamespace(family=socket.AF_INET, address=ip, netmask=mask)
    fake = types.SimpleNamespace(
        net_if_stats=lambda: {n: types.SimpleNamespace(isup=True)
                              for n in ("Wi-Fi", "Tailscale", "vEthernet (WSL)")},
        net_if_addrs=lambda: {"Wi-Fi": [addr("10.0.4.5", "255.255.255.0")],
                              "Tailscale": [addr("100.64.1.2", "255.192.0.0")],
                              "vEthernet (WSL)": [addr("172.28.0.1", "255.255.240.0")]})
    monkeypatch.setitem(sys.modules, "psutil", fake)
    nets = [str(n) for n, _ip in netscan.local_networks()]
    assert nets == ["10.0.4.0/24"]
    assert selfnet.vpn_adapters() == ["Tailscale"]


# ============================================================ robot state
class _Recorder:
    """An adapter that records what the hub gave it and runs a fake shell."""

    def __init__(self, uses_speech_key=False, shell=None, marker=""):
        self.uses_speech_key = uses_speech_key
        self.credential = None
        self.provider_env = None
        self.commands = []
        self.marker = marker
        if shell is not None:
            self.remote_shell = shell

    def claims(self):
        return []

    async def ensure_zero_instances(self):
        return []

    async def launch(self):
        return "http://robot/"

    async def disconnect(self):
        pass

    async def connect(self):
        pass

    async def system_status(self):
        return {"daemon_version": "1.13.0", "mic": "robot's built-in mic"}

    async def announce(self, text):
        pass


def _marker_shell(rec):
    async def shell(command, timeout_s=10.0):
        rec.commands.append(command)
        if command.startswith("cat "):
            return 0, rec.marker + "\n"
        if command.startswith("printf"):
            rec.marker = "{} 9999999999".format(inuse.this_laptop())
        if "rm -f" in command:
            rec.marker = ""
        return 0, ""
    return shell


def test_battery_low_warns_once_per_drop(hub):
    hub.registry.upsert("nao", type_id="naoqi", name="NAO", state=R.CONNECTED)
    hub._connected_at["nao"] = 1.0
    for pct in (25, 18, 17, 16):
        hub._apply_health("nao", {"online": True, "degraded": False, "detail": "ok",
                                  "battery": pct, "charging": False})
    warns = [e for e in hub.bus.recent() if "battery" in e["text"] and e["level"] == "warn"]
    assert len(warns) == 1 and "18%" in warns[0]["text"]
    r = hub.registry.get("nao")
    assert r.battery_low and r.charging is False
    hub._apply_health("nao", {"online": True, "degraded": False, "detail": "ok",
                              "battery": 30, "charging": True})
    hub._apply_health("nao", {"online": True, "degraded": False, "detail": "ok",
                              "battery": 30})
    assert hub.registry.get("nao").charging is True       # kept when the probe is silent
    hub._apply_health("nao", {"online": True, "degraded": False, "detail": "ok",
                              "battery": 15, "charging": False})
    warns = [e for e in hub.bus.recent() if "battery" in e["text"] and e["level"] == "warn"]
    assert len(warns) == 2                                 # a new drop, a new warning


def test_card_event_has_the_new_fields(hub):
    hub.registry.upsert("nao", type_id="naoqi", name="NAO", daemon_version="2.8.6.23",
                        mic="Windows default input", staff_only_actions=["nao_app"])
    event = hub.registry.get("nao").to_event()
    for name in ("connect_error", "battery_low", "charging", "in_use_by", "needs_setup",
                 "facts", "staff_only_actions"):
        assert name in event
    assert event["facts"]["robot_software"] == "NAOqi 2.8.6.23"
    assert event["facts"]["mic"] == "Windows default input"
    assert "holds" not in event and isinstance(event["facts"]["seen_ago"], int)
    assert hub.registry.get("placeholder:naoqi").staff_only_actions == ["nao_app"]


def test_get_robot_detail(hub):
    from fastapi.testclient import TestClient
    client = TestClient(_app_for(hub))
    card = client.get("/api/robots/placeholder:furhat").json()
    assert card["key"] == "placeholder:furhat" and "facts" in card and "keys" in card
    r = client.get("/api/robots/nope")
    assert r.status_code == 404 and r.json()["code"] == "UNKNOWN_ROBOT"


def test_in_use_marker_is_read_written_and_cleared(hub):
    rec = _Recorder(marker="other-laptop 9999999999")
    rec.remote_shell = _marker_shell(rec)
    hub.registry.upsert("u1", type_id="reachy_wireless", name="reachy1", address="10.0.4.21")
    hub.adapters["u1"] = rec
    async def connect_and_settle():
        out = await hub.connect("u1")
        await asyncio.sleep(0.05)
        return out
    assert run(connect_and_settle())["ok"]
    assert hub.registry.get("u1").in_use_by == "other-laptop"
    refused = run(hub.launch("u1"))
    assert refused["code"] == "IN_USE" and refused["in_use_by"] == "other-laptop"
    assert run(hub.launch("u1", override=True))["ok"]

    async def settle():
        await asyncio.sleep(0.05)
    run(settle())
    assert rec.marker.startswith(inuse.this_laptop())
    assert hub.registry.get("u1").in_use_by is None
    hub._marked.add("u1")
    run(hub.disconnect("u1"))
    assert rec.marker == ""


def test_in_use_parse_ignores_our_own_stale_and_stopped():
    me = "LAPTOP-A"
    assert inuse.parse("LAPTOP-B 2000000000\n", me, now=2000000100) == "LAPTOP-B"
    assert inuse.parse("LAPTOP-A 2000000000\n", me, now=2000000100) is None
    assert inuse.parse("LAPTOP-B 1000\n", me, now=2000000000) is None          # stale
    assert inuse.parse("LAPTOP-B 2000000000\n", me, app_running_checked=True,
                       now=2000000100) is None                                    # app stopped
    assert inuse.parse("LAPTOP-B 2000000000\n" + inuse.RUNNING_WORD, me,
                       app_running_checked=True, now=2000000100) == "LAPTOP-B"
    assert inuse.parse("", me) is None


def test_an_unreachable_robot_skips_the_marker_silently(hub):
    async def broken(command, timeout_s=10.0):
        raise OSError("ssh refused")
    rec = _Recorder()
    rec.remote_shell = broken
    hub.registry.upsert("u1", type_id="reachy_wireless", name="reachy1", address="10.0.4.21")
    hub.adapters["u1"] = rec
    assert run(hub.connect("u1"))["ok"]
    assert hub.registry.get("u1").in_use_by is None
    assert run(hub.launch("u1"))["ok"]


def test_a_failed_connect_is_sticky_until_a_good_one(hub):
    class Refuses(_Recorder):
        fail = True

        async def connect(self):
            if self.fail:
                raise RuntimeError("Studio never answered the login")

    rec = Refuses()
    hub.registry.upsert("f1", type_id="furhat", name="Furhat", address="10.0.4.30")
    hub.adapters["f1"] = rec
    run(hub.connect("f1"))
    card = hub.registry.get("f1")
    assert card.state == R.DETECTED and card.connect_error
    rec.fail = False
    run(hub.connect("f1"))
    card = hub.registry.get("f1")
    assert card.state == R.CONNECTED and card.connect_error is None


def test_a_real_loss_then_a_failed_retry_stays_lost(hub):
    class Refuses(_Recorder):
        async def connect(self):
            raise RuntimeError("no answer")
    hub.registry.upsert("f1", type_id="furhat", name="Furhat", address="10.0.4.30")
    hub.registry.set_state("f1", R.ERROR)
    hub._connected_at["f1"] = 1.0
    hub.adapters["f1"] = Refuses()
    run(hub.connect("f1"))
    assert hub.registry.get("f1").state == R.ERROR


def test_nao_app_is_staff_only_in_the_student_app(hub, monkeypatch, tmp_path):
    hub.registry.upsert("nao", type_id="naoqi", name="NAO", staff_only_actions=["nao_app"])
    hub.registry.set_state("nao", R.CONNECTED)
    hub.adapters["nao"] = _Recorder()
    assert hub.staff_tools_on()                       # a lab checkout keeps NAO_LLM
    assert run(hub.launch("nao"))["ok"]
    run(hub.disconnect("nao"))
    hub.registry.set_state("nao", R.CONNECTED)
    monkeypatch.setenv("ROBOT_HUB_DATA", str(tmp_path))
    out = run(hub.launch("nao"))
    assert out["code"] == "STAFF_ONLY"
    hub.settings.update({"staff_tools": True})
    assert run(hub.launch("nao"))["ok"]


def test_reachy_battery_only_when_the_daemon_has_one():
    assert find_battery({"state": "running", "backend_status": {"ready": True}}) == (None, None)
    assert find_battery({"battery": {"percentage": 64, "charging": True}}) == (64, True)
    assert find_battery({"power": {"battery_level": 0.42}}) == (42, None)
    assert find_battery({"battery_voltage": 12.1}) == (None, None)


# ================================================================ Add WiFi
class _WifiAdapter(_Recorder):
    type_id = "naoqi"

    def __init__(self):
        super().__init__()
        self.calls = []

    async def join_wifi(self, ssid, password, **kw):
        self.calls.append((ssid, password, kw))
        return "joined “{}”".format(ssid)


def test_add_wifi_accepts_open_networks_and_checks_passwords(hub):
    a = _WifiAdapter()
    hub.registry.upsert("nao", type_id="naoqi", name="NAO", address="10.0.4.40")
    hub.registry.set_state("nao", R.DETECTED)
    hub.adapters["nao"] = a
    assert run(hub.join_wifi("nao", "Cafe", "", open_network=True))["ok"]
    assert a.calls[-1] == ("Cafe", "", {"open_network": True})
    bad = run(hub.join_wifi("nao", "Cafe", "short"))
    assert not bad["ok"] and bad["error"] == "a WiFi password has 8 to 63 characters"
    assert run(hub.join_wifi("nao", "Phone", "longenough1"))["ok"]
    assert a.calls[-1] == ("Phone", "longenough1", {})
    refused = run(hub.join_wifi("nao", "Phone", "longenough1", lab=True))
    assert refused["error"] == "only a Reachy Mini keeps a lab WiFi fallback"


def test_add_wifi_route_save_only_and_lab_alias(hub):
    from fastapi.testclient import TestClient

    class Reachy(_WifiAdapter):
        type_id = "reachy_wireless"
    a = Reachy()
    hub.registry.upsert("u1", type_id="reachy_wireless", name="reachy1", address="10.0.4.21")
    hub.registry.set_state("u1", R.DETECTED)
    hub.adapters["u1"] = a
    client = TestClient(_app_for(hub))
    r = client.post("/api/robots/u1/wifi", json={"ssid": "HOT-WiFi", "open": True,
                                                 "save_only": True})
    assert r.status_code == 200, r.json()
    assert a.calls[-1] == ("HOT-WiFi", "", {"lab": True, "open_network": True})
    r = client.post("/api/robots/u1/wifi", json={"ssid": "Lab", "password": "secretpass1",
                                                 "lab": True})
    assert r.status_code == 200 and a.calls[-1][2] == {"lab": True}
    r = client.post("/api/robots/u1/wifi", json={"ssid": "Lab", "password": "x"})
    assert r.status_code == 409 and r.json()["code"] == "BAD_WIFI"


def test_reachy_adapter_passes_open_through(monkeypatch):
    from hub.adapters import reachy_wireless as rw
    a = object.__new__(rw.ReachyWirelessAdapter)
    a.found = Found(type_id="reachy_wireless", address="10.0.4.21")
    a.settings = {"ssh_user": "pollen", "ssh_password": "pw"}
    a.display_name = "reachy1"
    a.config = type("C", (), {"network": type("N", (), {"lab_wifi": "", "lab_wifi_open": False})(),
                              "secret": lambda self, k: ""})()
    seen = []

    def fake_run(host, user, password, command, timeout_s, stdin_text=None):
        seen.append(stdin_text)
        return 0, "CURRENT Lab Net\nSEEN no\nACTION saved\nMOVE no\n"
    monkeypatch.setattr(rw, "_ssh_run", fake_run)
    msg = run(a.join_wifi("Cafe", "", open_network=True))
    assert seen == ["pw\n\n"] and "Cafe" in msg


def test_effective_staff_tools_reach_the_page(hub, monkeypatch, tmp_path):
    assert hub.snapshot()["settings"]["staff_tools"] is True      # lab checkout
    monkeypatch.setenv("ROBOT_HUB_DATA", str(tmp_path))
    assert hub.snapshot()["settings"]["staff_tools"] is False
    hub.settings.update({"staff_tools": True})
    assert hub.snapshot()["settings"]["staff_tools"] is True


def test_a_refused_furhat_login_is_pushed_to_the_page(hub):
    q = hub.bus.subscribe()
    hub.settings.note_login("furhat", False)
    ev = q.get_nowait()
    assert ev["type"] == "settings" and ev["passwords"]["furhat"]["works"] is False
    hub.settings.note_login("furhat", False)      # no change, no event
    assert q.empty()


def test_duplicate_key_error_names_the_existing_label():
    from hub.core import ActionError

    err = ActionError("That key is already here.", "DUPLICATE", label="Lab Gemini")
    assert err.body()["label"] == "Lab Gemini"
