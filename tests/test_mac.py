"""The student app on a Mac (Apple Silicon and Intel): the hub's macOS paths
and launch/launch_mac.py.

This laptop is Windows, so every Mac path is run with sys.platform set to
"darwin" and the system calls faked: the installer's process, the WiFi
commands, ping, the launcher's hub process and HTTP. No real hub on 8099 and
no robot is ever touched; the one HTTP server here takes a free port.
"""

from __future__ import annotations

import asyncio
import http.server
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from hub import app_api, platforms, requirements, wifi  # noqa: E402
from hub import config as config_mod  # noqa: E402
from hub.discovery import netscan, selfnet  # noqa: E402

LAUNCH_MAC = REPO / "launch" / "launch_mac.py"
REPO_NAME = "labbgulab-lab/robot-hub"


@pytest.fixture
def mac(tmp_path, monkeypatch):
    """sys.platform is "darwin" for the test (every hub module reads it
    through `sys`, so one patch covers them all). tmp_path is made first:
    pytest itself asks os.getuid() when it sees "darwin"."""
    monkeypatch.setattr(sys, "platform", "darwin")
    wifi._mac_cache.clear()
    yield
    wifi._mac_cache.clear()


# ================================================================ platforms
def test_mac_arch_names_follow_the_release_tarballs():
    assert platforms.mac_arch("arm64") == "arm64"
    assert platforms.mac_arch("aarch64") == "arm64"
    assert platforms.mac_arch("x86_64") == "x86_64"
    assert platforms.mac_arch("") == "x86_64"


def test_naoqi_is_windows_only_on_a_mac(mac):
    assert platforms.is_mac() and not platforms.is_windows()
    assert platforms.naoqi_supported() is False
    assert platforms.usb_lite_supported() is False


def test_naoqi_stays_supported_off_a_mac(monkeypatch):
    for name in ("win32", "linux"):
        monkeypatch.setattr(sys, "platform", name)
        assert platforms.naoqi_supported() is True


# ============================================================ update check
RELEASES = [
    {"tag_name": "robot-files", "assets": [{"name": "dance.json"}], "html_url": "files"},
    # The Windows-first step: v1.2.0 is out for Windows, the Mac builds are not.
    {"tag_name": "v1.2.0", "assets": [{"name": "RobotHub-1.2.0.zip"}, {"name": "install.ps1"}],
     "html_url": "v120"},
    {"tag_name": "v1.1.0", "html_url": "v110", "assets": [
        {"name": "RobotHub-1.1.0.zip"}, {"name": "install.ps1"},
        {"name": "RobotHub-mac-arm64-1.1.0.tar.gz"}, {"name": "install-mac.sh"}]},
    {"tag_name": "v1.0.9", "html_url": "v109", "assets": [
        {"name": "RobotHub-1.0.9.zip"}, {"name": "RobotHub-mac-arm64-1.0.9.tar.gz"},
        {"name": "RobotHub-mac-x86_64-1.0.9.tar.gz"}, {"name": "install-mac.sh"}]},
    {"tag_name": "v9.0.0", "draft": True,
     "assets": [{"name": "RobotHub-mac-arm64-9.0.0.tar.gz"}]},
    {"tag_name": "v8.0.0", "prerelease": True,
     "assets": [{"name": "RobotHub-mac-x86_64-8.0.0.tar.gz"}]},
]


def test_windows_takes_the_newest_zip_as_before():
    assert app_api.pick_app_release(RELEASES, "win32") == {"tag": "v1.2.0", "url": "v120"}


def test_a_mac_is_only_offered_a_release_with_its_own_tarball():
    assert app_api.pick_app_release(RELEASES, "darwin", "arm64") == {"tag": "v1.1.0", "url": "v110"}
    assert app_api.pick_app_release(RELEASES, "darwin", "x86_64") == {"tag": "v1.0.9", "url": "v109"}
    windows_only = [r for r in RELEASES if r["tag_name"] in ("v1.2.0", "robot-files")]
    assert app_api.pick_app_release(windows_only, "darwin", "arm64") == {}


def test_the_platform_defaults_to_this_laptop(mac, monkeypatch):
    monkeypatch.setattr(platforms.platform, "machine", lambda: "arm64")
    assert app_api.pick_app_release(RELEASES) == {"tag": "v1.1.0", "url": "v110"}
    monkeypatch.setattr(platforms.platform, "machine", lambda: "x86_64")
    assert app_api.pick_app_release(RELEASES) == {"tag": "v1.0.9", "url": "v109"}


def test_asset_names_never_cross_platforms():
    assert app_api.app_asset_matches("RobotHub-1.0.0.zip", "win32")
    assert not app_api.app_asset_matches("RobotHub-mac-arm64-1.0.0.tar.gz", "win32")
    assert not app_api.app_asset_matches("RobotHub-1.0.0.zip", "darwin", "arm64")
    assert not app_api.app_asset_matches("RobotHub-mac-x86_64-1.0.0.tar.gz", "darwin", "arm64")
    assert not app_api.app_asset_matches("install-mac.sh", "darwin", "arm64")


def test_github_latest_passes_the_platform_through(monkeypatch):
    import httpx

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return RELEASES

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            assert url == app_api.RELEASES_API.format(REPO_NAME)
            return Resp()

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    got = asyncio.run(app_api.github_latest(REPO_NAME, "darwin", "x86_64"))
    assert got == {"tag": "v1.0.9", "url": "v109"}


# ================================================================ installer
class FakePopen:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        out = kwargs.get("stdout")
        self.calls.append((list(argv), dict(kwargs), getattr(out, "closed", None)))
        return self


def test_the_mac_installer_is_curl_into_bash_in_its_own_session(mac, tmp_path):
    popen = FakePopen()
    app_api.start_installer(REPO_NAME, popen=popen, log_dir=tmp_path / "logs")
    (argv, kwargs, out_closed_at_call), = popen.calls
    assert argv == ["/bin/bash", "-c",
                    "curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/"
                    "download/install-mac.sh | bash"]
    assert kwargs["start_new_session"] is True and kwargs["close_fds"] is True
    assert "creationflags" not in kwargs
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.STDOUT
    assert out_closed_at_call is False and kwargs["stdout"].closed   # handed over, then closed
    log = (tmp_path / "logs" / "update.log").read_text(encoding="utf-8")
    assert "updating Robot Hub" in log


def test_the_mac_update_log_goes_to_the_data_folder(mac, tmp_path, monkeypatch):
    monkeypatch.setenv("ROBOT_HUB_DATA", str(tmp_path / "data"))
    popen = FakePopen()
    app_api.start_installer(REPO_NAME, popen=popen)
    assert (tmp_path / "data" / "logs" / "update.log").is_file()
    assert popen.calls[0][0][0] == "/bin/bash"


def test_installer_argv_per_platform():
    assert app_api.installer_argv(REPO_NAME, "win32")[0] == "powershell"
    assert "install.ps1" in app_api.installer_argv(REPO_NAME, "win32")[-1]
    assert app_api.installer_argv(REPO_NAME, "darwin")[:2] == ["/bin/bash", "-c"]


@pytest.mark.skipif(sys.platform != "win32", reason="the PowerShell installer is Windows")
def test_the_windows_installer_is_unchanged(tmp_path):
    popen = FakePopen()
    app_api.start_installer(REPO_NAME, popen=popen, log_dir=tmp_path)
    (argv, kwargs, _), = popen.calls
    assert argv[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
    assert argv[5] == "irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1 | iex"
    assert kwargs["creationflags"] & subprocess.CREATE_NEW_CONSOLE
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert not (tmp_path / "update.log").exists()


def test_open_folder_on_a_mac_uses_open(mac, tmp_path):
    popen = FakePopen()
    app_api.open_folder(tmp_path, popen=popen)
    assert popen.calls[0][0] == ["open", str(tmp_path)]


# ============================================================ is_installed
def test_the_mac_layout_counts_as_installed(tmp_path):
    app = tmp_path / "RobotHub" / "app"
    (app / "robot-hub").mkdir(parents=True)
    assert app_api.is_installed(app / "robot-hub") is False
    (app / "launch_mac.py").write_text("", encoding="utf-8")
    assert app_api.is_installed(app / "robot-hub") is False      # no runtime yet
    (app / "runtime" / "bin").mkdir(parents=True)
    assert app_api.is_installed(app / "robot-hub") is True
    assert app_api.is_installed() is False                       # this checkout


# ===================================================================== ping
def test_ping_flags_per_system():
    assert netscan.ping_argv("10.0.0.7", "win32") == ["ping", "-n", "1", "-w", "700", "10.0.0.7"]
    # macOS: -W is milliseconds, -t the whole run in seconds.
    assert netscan.ping_argv("10.0.0.7", "darwin") == ["ping", "-c", "1", "-W", "700", "-t", "1", "10.0.0.7"]
    assert netscan.ping_argv("10.0.0.7", "linux") == ["ping", "-c", "1", "-W", "1", "10.0.0.7"]


def test_the_sweep_pings_with_the_mac_flags(mac, monkeypatch):
    started = []

    class Proc:
        returncode = 0

        async def communicate(self):
            return b"64 bytes from 10.0.0.7: icmp_seq=0 ttl=64 time=3.1 ms", b""

        def kill(self):
            pass

    async def fake_exec(*argv, **kwargs):
        started.append((argv, kwargs))
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    det = netscan.NetscanDetector.__new__(netscan.NetscanDetector)

    async def main():
        det._sem = asyncio.Semaphore(4)
        return await det._ping("10.0.0.7")
    assert asyncio.run(main()) is True
    (argv, kwargs), = started
    assert list(argv) == ["ping", "-c", "1", "-W", "700", "-t", "1", "10.0.0.7"]


# ====================================================================== arp
def test_mac_arp_lines_give_the_same_mac_as_windows():
    windows = "  172.20.10.5          00-1a-2b-0c-4d-5e     dynamic\n"
    mac_text = ("? (172.20.10.5) at 0:1a:2b:c:4d:5e on en0 ifscope [ethernet]\n"
                "? (172.20.10.9) at (incomplete) on en0 ifscope [ethernet]\n"
                "? (172.20.10.15) at ff:ff:ff:ff:ff:ff on en0 ifscope [ethernet]\n")
    assert netscan.parse_arp(windows) == {"172.20.10.5": "00:1a:2b:0c:4d:5e"}
    table = netscan.parse_arp(mac_text)
    assert table["172.20.10.5"] == "00:1a:2b:0c:4d:5e"
    assert "172.20.10.9" not in table


def test_the_mac_arp_table_is_read_without_name_lookups(mac, monkeypatch):
    started = []

    class Proc:
        async def communicate(self):
            return b"? (10.0.0.4) at a:b:c:d:e:f on en0 ifscope [ethernet]\n", b""

    async def fake_exec(*argv, **kwargs):
        started.append(argv)
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert asyncio.run(netscan.arp_table()) == {"10.0.0.4": "0a:0b:0c:0d:0e:0f"}
    assert started == [("arp", "-an")]


# ============================================================ mac adapters
def test_mac_interface_names():
    assert selfnet.is_vpn_adapter("utun4") and selfnet.is_vpn_adapter("ipsec0")
    assert selfnet.is_virtual_adapter("bridge100") and selfnet.is_virtual_adapter("awdl0")
    assert not selfnet.is_vpn_adapter("en0") and not selfnet.is_virtual_adapter("en0")
    assert not selfnet.is_virtual_adapter("Wi-Fi")


# ===================================================================== wifi
PROFILE = {"SPAirPortDataType": [{"spairport_airport_interfaces": [
    {"_name": "en0", "spairport_current_network_information": {
        "_name": "<redacted>", "spairport_network_channel": "149 (5GHz, 80MHz)"}}]}]}
PORTS = "Hardware Port: Ethernet\nDevice: en1\n\nHardware Port: Wi-Fi\nDevice: en0\nEthernet Address: x\n"


def _mac_commands(monkeypatch, answers):
    calls = []

    def run(argv, timeout=8.0):
        calls.append(tuple(argv))
        for key, text in answers.items():
            if tuple(argv[:len(key)]) == key:
                return text
        return ""
    monkeypatch.setattr(wifi, "_run", run)
    return calls


def test_the_mac_wifi_name_comes_from_networksetup(mac, monkeypatch):
    calls = _mac_commands(monkeypatch, {
        ("networksetup", "-listallhardwareports"): PORTS,
        ("networksetup", "-getairportnetwork"): "Current Wi-Fi Network: Open Lab\n",
        ("system_profiler",): json.dumps(PROFILE)})
    info = wifi.status(["172.19.84.41/16"], lab_wifi="Open Lab")
    assert info["ssid"] == "Open Lab" and info["band"] == "5 GHz" and info["channel"] == 149
    assert info["hotspot"] == "lab" and info["ok"] and info["platform"] == "darwin"
    assert ("networksetup", "-getairportnetwork", "en0") in calls


def test_then_from_ipconfig_getsummary(mac, monkeypatch):
    _mac_commands(monkeypatch, {
        ("networksetup", "-getairportnetwork"): "You are not associated with an AirPort network.\n",
        ("ipconfig", "getsummary"): "<dictionary> {\n  BSSID : 4a:00:00:00:00:01\n  SSID : Dana Phone\n}\n",
        ("system_profiler",): json.dumps(PROFILE)})
    info = wifi.status(["172.20.10.6/28"])
    assert info["ssid"] == "Dana Phone" and info["hotspot"] == "iphone"
    assert not info["ok"] and "Maximize Compatibility" in info["problem"]   # 5 GHz hotspot


def test_a_hidden_mac_wifi_name_is_unknown_never_a_warning(mac, monkeypatch):
    # macOS 14+ without Location access: every source hides the name.
    _mac_commands(monkeypatch, {
        ("networksetup", "-getairportnetwork"): "You are not associated with an AirPort network.\n",
        ("ipconfig", "getsummary"): "  SSID : <redacted>\n",
        ("system_profiler",): json.dumps(PROFILE)})
    info = wifi.status(["10.12.0.55/16"], lab_wifi="Open Lab")
    assert info["ssid"] is None and info["unknown"]
    assert info["ok"] and info["problem"] is None


def test_no_wifi_commands_at_all_is_unknown(mac, monkeypatch):
    _mac_commands(monkeypatch, {})
    info = wifi.status(["10.0.0.5/24"], lab_wifi="Open Lab")
    assert info["unknown"] and info["ok"] and info["problem"] is None


def test_system_profiler_is_cached_between_checks(mac, monkeypatch):
    calls = _mac_commands(monkeypatch, {
        ("networksetup", "-getairportnetwork"): "Current Wi-Fi Network: Open Lab\n",
        ("system_profiler",): json.dumps(PROFILE)})
    for _ in range(3):
        wifi.status(["172.19.84.41/16"])
    assert sum(1 for c in calls if c[0] == "system_profiler") == 1
    assert sum(1 for c in calls if c[:2] == ("networksetup", "-getairportnetwork")) == 3


# ================================================= NAO and Pepper on a Mac
@pytest.fixture
def mac_hub(mac, monkeypatch, tmp_path):
    from hub.config import load_config
    from hub.core import Hub
    kit = tmp_path / "LabaLab" / "naoqi-sdk"
    monkeypatch.setattr(config_mod, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.setattr(requirements, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    cfg = load_config(data=tmp_path / "data")
    (tmp_path / "data").mkdir(exist_ok=True)
    cfg.auto_connect = False
    return Hub(cfg)


def test_nao_and_pepper_cards_say_windows_only_on_a_mac(mac_hub):
    for type_id in ("naoqi", "pepper"):
        card = mac_hub.registry.get("placeholder:{}".format(type_id))
        assert card.needs_setup is None                 # no "Set up" that cannot work
        assert card.detail == platforms.NAOQI_WINDOWS_ONLY
    assert mac_hub.registry.get("placeholder:furhat").detail == "waiting for this robot to appear"
    assert mac_hub.registry.get("placeholder:reachy_wireless").needs_setup is None


def test_the_mac_setup_list_has_no_windows_only_steps(mac_hub):
    assert [i["id"] for i in mac_hub.setup.items()] == ["furhat_password"]
    kit = mac_hub.setup.item("naoqi_kit")
    assert kit["state"] == "failed" and kit["code"] == "WINDOWS_ONLY" and kit["actions"] == []
    assert mac_hub.setup.kit_ready() is False
    with pytest.raises(requirements.SetupError) as err:
        asyncio.run(mac_hub.setup.act("naoqi_kit", "download"))
    assert err.value.code == "WINDOWS_ONLY"
    assert "Windows" in str(err.value)


def test_a_nao_seen_from_a_mac_gets_a_clear_disabled_card(mac_hub):
    from hub import registry as R
    from hub.adapters import AdapterUnavailable, Found
    from hub.adapters.naoqi import NaoqiAdapter, PepperAdapter
    found = Found(type_id="pepper", address="10.0.0.40", port=9559, meta={})
    for cls in (NaoqiAdapter, PepperAdapter):
        with pytest.raises(AdapterUnavailable) as err:
            cls(Found(type_id=cls.type_id, address="10.0.0.40"), mac_hub.config)
        assert str(err.value) == platforms.NAOQI_WINDOWS_ONLY
        assert err.value.requirement is None
    mac_hub._on_found(found)
    card = mac_hub.registry.get("placeholder:pepper")
    assert card.state == R.DISABLED and card.needs_setup is None
    assert card.disabled_reason == platforms.NAOQI_WINDOWS_ONLY
    mac_hub._on_lost("pepper", "nobody")
    card = mac_hub.registry.get("placeholder:pepper")
    assert card.state == R.ABSENT and card.detail == platforms.NAOQI_WINDOWS_ONLY


def test_windows_still_offers_the_kit(monkeypatch, tmp_path):
    from hub.config import load_config
    from hub.core import Hub
    monkeypatch.setattr(sys, "platform", "win32")
    kit = tmp_path / "LabaLab" / "naoqi-sdk"
    monkeypatch.setattr(config_mod, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.setattr(requirements, "naoqi_kit_dirs", lambda: [kit])
    monkeypatch.delenv("ROBOT_HUB_DATA", raising=False)
    hub = Hub(load_config(data=tmp_path / "data"))
    assert hub.registry.get("placeholder:naoqi").needs_setup == "naoqi_kit"
    assert {i["id"] for i in hub.setup.items()} == set(requirements.ITEMS)


def test_the_usb_lite_watcher_stops_quietly_on_a_mac(mac):
    from hub.config import load_config
    from hub.discovery.usbwatch import UsbWatchDetector
    from hub.events import EventBus
    bus = EventBus()
    det = UsbWatchDetector(load_config(), bus, lambda found: None)
    assert det._pick_backend() is None
    lines = [e["text"] for e in bus.recent(10)]
    assert any("not found on a Mac" in t for t in lines)
    assert not any("pip install" in t for t in lines)


def test_the_doctor_explains_the_mac(mac):
    from hub import doctor
    from hub.config import load_config
    rows = doctor._naoqi(load_config())
    assert len(rows) == 1 and rows[0]["ok"] and rows[0]["detail"] == platforms.NAOQI_WINDOWS_ONLY
    wmi = doctor._wmi()
    assert wmi["ok"] and "macOS" in wmi["detail"] and "pip" not in wmi["remedy"]


# ============================================== the whole hub under "darwin"
def test_every_hub_module_imports_and_the_hub_starts_under_darwin(tmp_path):
    """A fresh interpreter that says it is a Mac: every hub module imports,
    hub.main builds the app, the setup list and the cards are the Mac ones,
    and the doctor runs. The standard library and the hub's packages are
    imported first, as the real platform: only the hub's own code is under
    test, not Python's Windows internals."""
    code = textwrap.dedent("""
        import asyncio, json, os, pkgutil, socket, subprocess, sys, importlib
        import fastapi, httpx, psutil, uvicorn, starlette.testclient
        for optional in ("numpy", "sounddevice", "soundfile", "paramiko", "zeroconf",
                         "onnxruntime", "websockets", "tomli_w"):
            try:
                importlib.import_module(optional)
            except Exception:
                pass
        sys.platform = "darwin"
        sys.path.insert(0, {root!r})
        import hub
        names = []
        for mod in pkgutil.walk_packages(hub.__path__, "hub."):
            if mod.name in ("hub.main",):
                continue
            importlib.import_module(mod.name)
            names.append(mod.name)
        from hub import main as hub_main
        snap = hub_main.hub.snapshot()
        from hub import doctor
        checks = doctor.run_checks(hub_main.config)
        print(json.dumps({{
            "modules": len(names),
            "setup": [i["id"] for i in snap["setup"]],
            "nao": [r["detail"] for r in snap["robots"] if r["type_id"] in ("naoqi", "pepper")],
            "needs_setup": [r.get("needs_setup") for r in snap["robots"]],
            "doctor": len(checks),
            "no_window": hub.winproc.no_window(),
        }}))
    """).format(root=str(REPO))
    env = dict(os.environ, ROBOT_HUB_DATA=str(tmp_path / "data"))
    env.pop("PYTHONPATH", None)
    out = subprocess.run([sys.executable, "-c", code], cwd=str(tmp_path), env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-3000:]
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["modules"] > 30
    assert got["setup"] == ["furhat_password"]
    assert got["nao"] == [platforms.NAOQI_WINDOWS_ONLY] * 2
    assert not any(got["needs_setup"])
    assert got["doctor"] > 5
    assert got["no_window"] == {}


# ============================================================ launch_mac.py
def load_mac_launcher():
    loader = importlib.machinery.SourceFileLoader("robot_hub_launch_mac", str(LAUNCH_MAC))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    """The Mac launcher pointed at a temp install: app/ and data/ in tmp."""
    mod = load_mac_launcher()
    root = tmp_path / "RobotHub"
    app = root / "app"
    (app / "robot-hub" / "hub").mkdir(parents=True)
    (app / "runtime" / "bin").mkdir(parents=True)
    (app / "runtime" / "bin" / "python3").write_text("", encoding="utf-8")
    layout = mod.find_layout(app, env={})
    monkeypatch.setattr(mod, "INSTALLED", True)
    monkeypatch.setattr(mod, "HUB_DIR", layout["hub_dir"])
    monkeypatch.setattr(mod, "PYTHON", layout["python"])
    monkeypatch.setattr(mod, "DATA_DIR", layout["data_dir"])
    monkeypatch.setattr(mod, "LOG_DIR", layout["data_dir"] / "logs")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return mod


def test_the_launcher_imports_on_any_system_and_knows_a_checkout():
    mod = load_mac_launcher()
    assert mod.INSTALLED is False
    assert mod.HUB_DIR == REPO
    assert mod.URL == "http://127.0.0.1:{}/".format(mod.PORT)


def test_the_installed_layout(tmp_path):
    mod = load_mac_launcher()
    app = tmp_path / "RobotHub" / "app"
    (app / "robot-hub" / "hub").mkdir(parents=True)
    got = mod.find_layout(app, env={})
    assert got["installed"] is True
    assert got["hub_dir"] == app / "robot-hub"
    assert got["python"] == app / "runtime" / "bin" / "python3"
    assert got["data_dir"] == tmp_path / "RobotHub" / "data"
    assert mod.find_layout(app, env={"ROBOT_HUB_DATA": str(tmp_path / "x")})["data_dir"] == tmp_path / "x"


def test_the_hub_env_points_at_the_data_folder(launcher):
    env = launcher.hub_env({"PYTHONPATH": "/somewhere", "VIRTUAL_ENV": "/v", "HOME": "home-folder"})
    assert env["ROBOT_HUB_DATA"] == str(launcher.DATA_DIR)
    assert "PYTHONPATH" not in env and "VIRTUAL_ENV" not in env
    assert env["PYTHONNOUSERSITE"] == "1" and env["HOME"] == "home-folder"


def test_the_hub_starts_detached_with_its_output_in_the_log(launcher):
    popen = FakePopen()
    hub = launcher.HubProcess(popen=popen)
    hub.start()
    (argv, kwargs, out_closed_at_call), = popen.calls
    assert argv == [str(launcher.PYTHON), "-c", "from hub.main import main; main()"]
    assert kwargs["cwd"] == str(launcher.HUB_DIR)
    assert kwargs["start_new_session"] is True
    assert kwargs["stderr"] is subprocess.STDOUT and out_closed_at_call is False
    assert kwargs["env"]["ROBOT_HUB_DATA"] == str(launcher.DATA_DIR)
    assert "starting the hub" in (launcher.LOG_DIR / "hub-stdout.log").read_text(encoding="utf-8")


class FakeHub:
    """HubProcess stand-in: records what the launcher asked of it."""

    def __init__(self, ready=True):
        self.ready = ready
        self.events = []

    def start(self):
        self.events.append("start")

    def wait_ready(self, timeout=None):
        self.events.append("wait")
        return self.ready

    def stop(self):
        self.events.append("stop")


def _fake_http(mod, monkeypatch, running):
    """The hub's HTTP, faked: `running` is a one-item list the fake flips."""
    calls = []

    def http(method, path, timeout=2.0):
        calls.append((method, path))
        if method == "POST" and path == "/api/app/quit":
            running[0] = False
            return 200, b'{"ok": true}'
        if not running[0]:
            return 0, b""
        if path == "/api/app":
            return 200, b'{"version": "1.0.5", "installed": true}'
        if path == "/api/robots":
            return 200, b'{"robots": []}'
        return 404, b""
    monkeypatch.setattr(mod, "_http", http)
    return calls


def test_check_starts_a_hub_reports_it_and_stops_it(launcher, monkeypatch, capsys):
    running = [False]
    _fake_http(launcher, monkeypatch, running)
    hub = FakeHub()
    hub.start = lambda: (hub.events.append("start"), running.__setitem__(0, True))
    hub.stop = lambda: (hub.events.append("stop"), running.__setitem__(0, False))
    assert launcher.self_check(hub) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["started_by_check"] is True
    assert out["app"] == {"version": "1.0.5", "installed": True}
    assert out["stopped"] is True
    assert hub.events == ["start", "wait", "stop"]


def test_check_leaves_a_running_hub_alone(launcher, monkeypatch, capsys):
    _fake_http(launcher, monkeypatch, [True])
    hub = FakeHub()
    assert launcher.self_check(hub) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["started_by_check"] is False
    assert hub.events == []


def test_check_fails_when_the_hub_never_answers(launcher, monkeypatch, capsys):
    _fake_http(launcher, monkeypatch, [False])
    hub = FakeHub(ready=False)
    assert launcher.self_check(hub) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["started_by_check"] is True
    assert hub.events == ["start", "wait", "stop"]


def test_the_icon_starts_the_hub_then_opens_the_page(launcher, monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(launcher.URL))
    _fake_http(launcher, monkeypatch, [False])
    hub = FakeHub()
    assert launcher.start_and_open(hub) == 0
    assert hub.events == ["start", "wait"] and opened == [launcher.URL]


def test_the_icon_only_opens_the_page_when_the_hub_runs(launcher, monkeypatch):
    opened = []
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(1))
    _fake_http(launcher, monkeypatch, [True])
    hub = FakeHub()
    assert launcher.start_and_open(hub) == 0
    assert hub.events == [] and opened == [1]


def test_a_hub_that_will_not_start_says_where_the_log_is(launcher, monkeypatch):
    said = []
    monkeypatch.setattr(launcher, "message", said.append)
    monkeypatch.setattr(launcher, "open_browser", lambda: said.append("opened"))
    _fake_http(launcher, monkeypatch, [False])
    assert launcher.start_and_open(FakeHub(ready=False)) == 1
    assert len(said) == 1 and "hub-stdout.log" in said[0]


def test_quit_posts_to_the_hub(launcher, monkeypatch, capsys):
    calls = _fake_http(launcher, monkeypatch, [True])
    assert launcher.quit_hub() == 0
    assert ("POST", "/api/app/quit") in calls
    assert json.loads(capsys.readouterr().out)["running"] is True
    calls.clear()
    assert launcher.quit_hub() == 0                 # nothing running: nothing to do
    assert ("POST", "/api/app/quit") not in calls


def test_main_refuses_an_incomplete_install(launcher, monkeypatch):
    said = []
    monkeypatch.setattr(launcher, "message", said.append)
    monkeypatch.setattr(launcher, "PYTHON", launcher.HUB_DIR / "missing" / "python3")
    assert launcher.main([]) == 1
    assert "Run the install line again" in said[0]


def test_main_dispatches(launcher, monkeypatch):
    seen = []
    monkeypatch.setattr(launcher, "self_check", lambda: seen.append("check") or 0)
    monkeypatch.setattr(launcher, "start_and_open", lambda: seen.append("open") or 0)
    monkeypatch.setattr(launcher, "quit_hub", lambda: seen.append("quit") or 0)
    assert launcher.main(["--check"]) == 0
    assert launcher.main([]) == 0
    assert launcher.main(["--quit"]) == 0
    assert seen == ["check", "open", "quit"]


def test_the_page_opens_with_open(launcher, monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(launcher, "OPEN", sys.executable)     # a file that exists
    launcher.open_browser(popen=popen)
    assert popen.calls[0][0] == [sys.executable, launcher.URL]


def test_stop_kills_a_hub_that_will_not_quit(launcher, monkeypatch):
    killed = []

    class Proc:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(launcher, "_http", lambda *a, **k: (0, b""))
    monkeypatch.setattr(launcher, "port_open", lambda: False)
    monkeypatch.setattr(launcher, "CLOSE_GRACE", -1)
    hub = launcher.HubProcess()
    hub.proc = Proc()
    monkeypatch.setattr(hub, "kill", lambda: killed.append(hub.proc.pid))
    hub.stop()
    assert killed == [4242]


# A real HTTP round trip on a free port (never 8099): the launcher's urllib
# path against a stand-in hub.
class _StandInHub(http.server.BaseHTTPRequestHandler):
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
def stand_in_hub():
    _StandInHub.alive, _StandInHub.quits = True, 0
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _StandInHub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_check_against_a_real_http_hub(stand_in_hub, monkeypatch, capsys):
    mod = load_mac_launcher()
    monkeypatch.setattr(mod, "PORT", stand_in_hub)
    monkeypatch.setattr(mod, "URL", "http://127.0.0.1:{}/".format(stand_in_hub))
    assert mod.hub_answers()
    assert mod.self_check(FakeHub()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["started_by_check"] is False
    assert out["app"] == {"version": "9.9.9"}
    assert _StandInHub.quits == 0
    assert mod.quit_hub() == 0 and _StandInHub.quits == 1
    assert not mod.hub_answers()
