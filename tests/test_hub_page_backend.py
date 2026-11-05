"""Work package E (the hub page): the small backend pieces it added.

- GET /api/robots/{key}/wifi: the WiFi networks a robot knows (Add WiFi's
  "Knows:" line), read over the robot's SSH and parsed here.
- The vendored fonts: the hub serves web/fonts/, Pepper's dashboard serves
  /static/fonts/ (no font CDN on the lab WiFi).

No robots, no network: the robot's shell is a fake.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hub import config as config_mod  # noqa: E402
from hub import requirements  # noqa: E402
from hub.config import load_config  # noqa: E402
from hub.core import Hub  # noqa: E402
from hub.features_api import (  # noqa: E402
    CONNMAN_KNOWN, NMCLI_KNOWN, parse_connman_known, parse_nmcli_known)

ROOT = Path(__file__).resolve().parent.parent

NMCLI = "\n".join([
    "HOT-WiFi:802-11-wireless:yes:-10:no",
    "Lab Phone:802-11-wireless:yes:10:yes",
    "Old Phone:802-11-wireless:no:0:no",
    "reachy-mini-ap:802-11-wireless:yes:0:no",
    "My\\:Net:802-11-wireless:yes:0:no",
    "Wired connection 1:802-3-ethernet:yes:0:yes",
])

CONNMAN = "\n".join([
    "*AO HOT-WiFi             wifi_48a9d2_484f542d57694669_managed_none",
    "*A  Lab Phone            wifi_48a9d2_4c61622050686f6e65_managed_psk",
    "*   Old Phone            wifi_48a9d2_4f6c642050686f6e65_managed_psk",
    "    Neighbours           wifi_48a9d2_4e65696768_managed_psk",
    "*AR Wired                ethernet_0800_cable",
])


def test_nmcli_known_networks_with_notes():
    nets = parse_nmcli_known(NMCLI)
    assert nets[0] == {"ssid": "Lab Phone", "current": True, "note": None}
    by = {n["ssid"]: n for n in nets}
    assert by["HOT-WiFi"]["note"] == "lab WiFi fallback"
    assert by["Old Phone"]["note"] == "won't join by itself"
    assert by["reachy-mini-ap"]["note"] == "its own setup network"
    assert "My:Net" in by                         # an escaped ':' in a name
    assert "Wired connection 1" not in by         # WiFi only
    assert nets[-1]["ssid"] == "reachy-mini-ap"   # the setup network goes last


def test_connman_lists_saved_wifi_only():
    nets = parse_connman_known(CONNMAN)
    assert [n["ssid"] for n in nets] == ["HOT-WiFi", "Lab Phone", "Old Phone"]
    assert nets[0]["current"] is True
    assert nets[2]["note"] == "won't join by itself"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    kit = tmp_path / "LabaLab" / "naoqi-sdk"
    monkeypatch.setattr(config_mod, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.setattr(requirements, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    (tmp_path / "data").mkdir()
    cfg = load_config(data=tmp_path / "data")
    cfg.auto_connect = False
    return Hub(cfg)


class FakeShellAdapter:
    def __init__(self, type_id, output, status=0, fail=False):
        self.type_id = type_id
        self.output, self.status, self.fail = output, status, fail
        self.commands = []

    async def join_wifi(self, *a, **kw):  # pragma: no cover - only its presence matters
        return ""

    async def remote_shell(self, command, timeout_s=10.0):
        self.commands.append(command)
        if self.fail:
            raise OSError("no route to host")
        return self.status, self.output


def _client(hub):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from hub.features_api import make_router
    app = FastAPI()
    app.include_router(make_router(hub, wifi_opener=lambda: None))
    return TestClient(app)


def test_known_wifi_route_reachy_and_pepper(hub):
    hub.registry.upsert("reachy:r1", type_id="reachy_wireless", name="reachy1")
    hub.registry.upsert("pepper:p1", type_id="pepper", name="Pepper")
    reachy = FakeShellAdapter("reachy_wireless", NMCLI)
    pepper = FakeShellAdapter("pepper", CONNMAN)
    hub.adapters["reachy:r1"] = reachy
    hub.adapters["pepper:p1"] = pepper
    client = _client(hub)

    body = client.get("/api/robots/reachy:r1/wifi").json()
    assert body["ok"] and body["supported"] and body["networks"][0]["ssid"] == "Lab Phone"
    assert reachy.commands == [NMCLI_KNOWN]

    body = client.get("/api/robots/pepper:p1/wifi").json()
    assert [n["ssid"] for n in body["networks"]][:1] == ["HOT-WiFi"]
    assert pepper.commands == [CONNMAN_KNOWN]


def test_known_wifi_route_errors(hub):
    client = _client(hub)
    res = client.get("/api/robots/nobody/wifi")
    assert res.status_code == 404 and res.json()["code"] == "UNKNOWN_ROBOT"

    hub.registry.upsert("reachy:r2", type_id="reachy_wireless", name="reachy2")
    hub.adapters["reachy:r2"] = FakeShellAdapter("reachy_wireless", "", fail=True)
    res = client.get("/api/robots/reachy:r2/wifi")
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "NET_UNREACHABLE" and body["ok"] is False and "reachy2" in body["error"]

    hub.registry.upsert("furhat:f", type_id="furhat", name="Furhat")
    body = client.get("/api/robots/furhat:f/wifi").json()   # no adapter, no shell
    assert body == {"ok": True, "supported": False, "networks": []}


def test_fonts_are_vendored_for_the_hub_and_pepper(tmp_path):
    for folder in (ROOT / "web" / "fonts", ROOT / "pepper_app" / "static" / "fonts"):
        for name in ("Inter-Variable.woff2", "JetBrainsMono-Variable.woff2"):
            assert (folder / name).read_bytes()[:4] == b"wOF2"
    css = (ROOT / "web" / "fonts" / "fonts.css").read_text(encoding="utf-8")
    assert "Inter-Variable.woff2" in css and "googleapis" not in css

    from fastapi.testclient import TestClient
    from pepper_app.server import create_app
    app = create_app("", 0, 0, tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000))
    res = client.get("/static/fonts/Inter-Variable.woff2")
    assert res.status_code == 200 and res.content[:4] == b"wOF2"
    assert res.headers["content-type"].startswith("font/woff2")
    assert client.get("/static/fonts/nothing.woff2").status_code == 404
    pepper_css = (ROOT / "pepper_app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert "/static/fonts/Inter-Variable.woff2" in pepper_css


def test_hub_page_uses_no_cdn():
    for name in ("index.html", "app.js", "style.css"):
        text = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert "fonts.googleapis" not in text and "cdn." not in text and "unpkg" not in text
