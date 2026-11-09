"""The student app's launcher (launch/launch.pyw) and installer (tools/install.ps1).

The installer test unpacks a tiny fake bundle into a temp root with Windows
PowerShell, the way a student's laptop runs it, but with the shortcuts in a
temp folder and without opening the app.
"""

from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
LAUNCH = REPO / "launch" / "launch.pyw"
INSTALL = REPO / "tools" / "install.ps1"
WINDOWS = sys.platform == "win32"

pytestmark = pytest.mark.skipif(not WINDOWS, reason="the student app is Windows only")


def load_launcher():
    loader = importlib.machinery.SourceFileLoader("robot_hub_launch", str(LAUNCH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------ launcher
def test_launcher_in_a_checkout_uses_this_repo():
    mod = load_launcher()
    assert mod.INSTALLED is False
    assert mod.HUB_DIR == REPO
    assert mod.PYTHON.name.lower() == "python.exe"


def test_port_comes_from_the_data_config_then_defaults(tmp_path, monkeypatch):
    mod = load_launcher()
    hub_dir, data = tmp_path / "robot-hub", tmp_path / "data"
    hub_dir.mkdir()
    data.mkdir()
    monkeypatch.setattr(mod, "HUB_DIR", hub_dir)
    monkeypatch.setattr(mod, "DATA_DIR", data)
    assert mod.hub_port() == 8099
    (hub_dir / "defaults.toml").write_text("[server]\nport = 8100\n", encoding="utf-8")
    assert mod.hub_port() == 8100
    (data / "config.toml").write_text("[server]\nport = 8111\n", encoding="utf-8")
    assert mod.hub_port() == 8111
    (data / "config.toml").write_text("not toml [[[", encoding="utf-8")
    assert mod.hub_port() == 8100


def test_edge_lookup_returns_a_file_or_nothing():
    edge = load_launcher().find_edge()
    assert edge is None or (edge.is_file() and edge.name.lower() == "msedge.exe")


class _FakeHub(http.server.BaseHTTPRequestHandler):
    alive = True
    quits = 0

    def log_message(self, *_a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not type(self).alive:
            return self._send(503, {})
        if self.path == "/api/robots":
            return self._send(200, {"robots": []})
        if self.path == "/api/app":
            return self._send(200, {"version": "9.9.9"})
        self._send(404, {})

    def do_POST(self):
        if self.path == "/api/app/quit":
            type(self).quits += 1
            type(self).alive = False
            return self._send(200, {"ok": True})
        self._send(404, {})


@pytest.fixture
def fake_hub():
    _FakeHub.alive, _FakeHub.quits = True, 0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_check_mode_reports_a_running_hub(fake_hub, monkeypatch, capsys):
    mod = load_launcher()
    monkeypatch.setattr(mod, "PORT", fake_hub)
    monkeypatch.setattr(mod, "URL", f"http://127.0.0.1:{fake_hub}/")
    assert mod.hub_answers()
    assert mod.self_check() == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["started_by_check"] is False
    assert out["app"] == {"version": "9.9.9"}
    assert _FakeHub.quits == 0          # never stops a hub it did not start


def test_stop_asks_the_hub_to_quit(fake_hub, monkeypatch):
    mod = load_launcher()
    monkeypatch.setattr(mod, "URL", f"http://127.0.0.1:{fake_hub}/")
    mod.HubProcess().stop()
    assert _FakeHub.quits == 1
    assert not mod.hub_answers()


def test_without_the_tray_a_quit_still_closes_the_window(monkeypatch):
    """No tray (pystray failed): the launcher waits for its hub, and a hub
    that quit closes the app window; a crash leaves it open to show why."""
    mod = load_launcher()
    closed = []
    monkeypatch.setattr(mod, "close_windows", lambda: closed.append(1))
    hub = mod.HubProcess()
    mod.wait_and_close(hub)                     # nothing started: nothing to wait for
    hub.proc = subprocess.Popen([sys.executable, "-c", "pass"])
    mod.wait_and_close(hub)
    assert closed == [1]
    hub.proc = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    mod.wait_and_close(hub)
    assert closed == [1]


def test_nothing_on_the_port_is_not_a_hub(monkeypatch):
    mod = load_launcher()
    monkeypatch.setattr(mod, "URL", "http://127.0.0.1:9/")
    assert not mod.hub_answers()


# ------------------------------------------------------------------ installer
def _bundle(where: Path, version: str) -> Path:
    """A fake RobotHub-<version>.zip with the files the installer checks."""
    src = where / f"bundle-{version}"
    for rel in ("runtime/python.exe", "runtime/pythonw.exe", "robot-hub/hub/main.py",
                "robot-hub/assets/labalab.ico", "launch.pyw"):
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    shutil.copy(REPO / "assets" / "labalab.ico", src / "robot-hub" / "assets" / "labalab.ico")
    (src / "VERSION").write_text(version, encoding="ascii")
    zip_path = where / f"RobotHub-{version}.zip"
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    subprocess.run([str(tar), "-a", "-c", "-f", str(zip_path), "-C", str(src),
                    "runtime", "robot-hub", "launch.pyw", "VERSION"], check=True)
    return zip_path


def _install(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("PSModulePath", None)        # as from a fresh Windows PowerShell window
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(INSTALL), *args],
                          capture_output=True, text=True, timeout=180, env=env)


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="needs Windows PowerShell")
def test_install_update_uninstall(tmp_path):
    root, desk, start = tmp_path / "root", tmp_path / "desk", tmp_path / "start"
    common = ["-Root", str(root), "-NoLaunch", "-DesktopDir", str(desk), "-StartMenuDir", str(start)]
    v1, v2 = _bundle(tmp_path, "1.0.0"), _bundle(tmp_path, "1.0.1")

    r = _install("-Zip", str(v1), *common)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "app" / "VERSION").read_text() == "1.0.0"
    assert (desk / "LabaLab Robot Hub.lnk").is_file()
    assert (start / "LabaLab Robot Hub.lnk").is_file()
    assert (root / "data").is_dir()
    (root / "data" / "keys.local.json").write_text("{}", encoding="utf-8")

    r = _install("-Zip", str(v2), *common)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "app" / "VERSION").read_text() == "1.0.1"
    assert (root / "app.old" / "VERSION").read_text() == "1.0.0"
    assert not (root / "app.new").exists()
    assert (root / "data" / "keys.local.json").read_text() == "{}"     # data is never touched

    r = _install("-Uninstall", *common)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (root / "app").exists() and not (root / "app.old").exists()
    assert not (desk / "LabaLab Robot Hub.lnk").exists()
    assert (root / "data" / "keys.local.json").is_file()              # kept without -RemoveData

    r = _install("-Uninstall", "-RemoveData", *common)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not root.exists()


@pytest.mark.skipif(not shutil.which("powershell.exe"), reason="needs Windows PowerShell")
def test_install_refuses_a_broken_zip(tmp_path):
    bad = tmp_path / "RobotHub-0.zip"
    src = tmp_path / "half"
    (src / "robot-hub").mkdir(parents=True)
    (src / "VERSION").write_text("0", encoding="ascii")
    tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
    subprocess.run([str(tar), "-a", "-c", "-f", str(bad), "-C", str(src), "VERSION", "robot-hub"], check=True)
    root = tmp_path / "root"
    r = _install("-Zip", str(bad), "-Root", str(root), "-NoLaunch", "-NoShortcuts")
    assert "incomplete" in r.stdout
    assert not (root / "app").exists() and not (root / "app.new").exists()
