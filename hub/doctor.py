"""Preflight for a new user: `python -m hub.doctor`, also at /api/doctor (12).

The repo has to be useful to someone with one robot, or none. So every check
answers two questions: is this working, and if not, what exactly do I type to
fix it. A robot you do not own is a **note**, never an error (13.6) -- nobody
should have to install Python 2.7 to run a hub for a Furhat.

`run_checks` is called from a thread via `run_in_executor` (hub/main.py), so
it is synchronous and every subprocess it starts carries a timeout. It must
never hang: a doctor that blocks the page it is diagnosing is worse than no
doctor at all (2.4).

Each check is `{"name", "ok", "detail", "remedy"}`. The table marks a row
FAIL when `ok` is false, NOTE when it passed but still has something to say,
and PASS otherwise.
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from .config import REPO_ROOT, Config, load_config

SUBPROCESS_TIMEOUT_S = 5.0

CORE_MODULES = (
    ("fastapi", "the web app itself"),
    ("zeroconf", "mDNS discovery for Reachy-Mini and NAO"),
    ("httpx", "every HTTP call, including the Furhat fingerprint"),
    ("psutil", "watching this laptop's own network (2.8)"),
    ("sounddevice", "naming the audio device NAO would otherwise grab (2.5)"),
)

INSTALL_ALL = "pip install -r requirements.txt"


def _check(name: str, ok: bool, detail: str, remedy: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail, "remedy": remedy}


# ---------------------------------------------------------------- the checks
def run_checks(config: Optional[Config] = None) -> list[dict[str, Any]]:
    config = config or load_config()
    checks: list[dict[str, Any]] = []
    checks.append(_python_version())
    checks.append(_config_file())
    checks += [_importable(module, why) for module, why in CORE_MODULES]
    checks.append(_wmi())
    checks += _naoqi(config)
    checks += _reachy_wireless(config)
    checks.append(_reachy_lite(config))
    checks.append(_furhat_key(config))
    checks.append(_interfaces())
    return checks


def _python_version() -> dict[str, Any]:
    version = platform.python_version()
    ok = sys.version_info >= (3, 11)
    return _check(
        "Python 3.11+", ok,
        "running {} from {}".format(version, sys.executable),
        "" if ok else "Install Python 3.11 or newer and recreate the venv: "
                      "py -3.11 -m venv .venv")


def _config_file() -> dict[str, Any]:
    path = REPO_ROOT / "config.toml"
    if path.exists():
        return _check("config.toml", True, "using {}".format(path))
    return _check(
        "config.toml", True,
        "no config.toml, falling back to config.example.toml (another lab's paths)",
        "copy config.example.toml to config.toml and edit the paths for this machine")


def _importable(module: str, why: str) -> dict[str, Any]:
    try:
        __import__(module)
    except Exception as exc:  # noqa: BLE001
        return _check("import {}".format(module), False,
                      "{} is needed for {} but did not import: {}".format(module, why, exc),
                      INSTALL_ALL)
    return _check("import {}".format(module), True, why)


def _wmi() -> dict[str, Any]:
    if sys.platform != "win32":
        return _check(
            "import wmi", True,
            "not Windows, so USB detection uses pyudev instead",
            "on Linux, Reachy-Mini-Lite detection needs: pip install pyudev")
    try:
        import wmi  # noqa: F401
        import pythoncom  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        return _check(
            "import wmi", True,
            "Reachy-Mini-Lite USB detection is unavailable ({}); every other "
            "robot is unaffected".format(exc),
            "pip install wmi pywin32")
    return _check("import wmi", True, "Reachy-Mini-Lite USB detection available")


def _naoqi(config: Config) -> list[dict[str, Any]]:
    if not config.robot("naoqi").enabled:
        return [_check("NAO: Python 2.7", True, "naoqi is disabled in config")]

    python2 = config.path("naoqi", "python2")
    remedy2 = ("install Python 2.7 and set robots.naoqi.settings.python2 to its "
               "python.exe -- NAOqi has no Python 3 bindings (2.7)")
    if python2 is None:
        version_check = _check("NAO: Python 2.7", True,
                               "robots.naoqi.settings.python2 is not set", remedy2)
    elif not python2.exists():
        version_check = _check("NAO: Python 2.7", False,
                               "{} does not exist".format(python2), remedy2)
    else:
        version = _run([str(python2), "-V"])
        ok = "2.7" in version
        version_check = _check(
            "NAO: Python 2.7", ok,
            "{} reports {}".format(python2, version or "nothing"),
            "" if ok else remedy2)

    sdk = config.path("naoqi", "pynaoqi_sdk")
    remedy_sdk = ("download the pynaoqi 2.8.6 Python 2.7 SDK and point "
                  "robots.naoqi.settings.pynaoqi_sdk at the folder that contains "
                  "lib/ and bin/ (note the doubled folder name in the archive)")
    if sdk is None:
        sdk_check = _check("NAO: pynaoqi SDK", True,
                           "robots.naoqi.settings.pynaoqi_sdk is not set", remedy_sdk)
    elif not (sdk / "lib").is_dir():
        sdk_check = _check("NAO: pynaoqi SDK", False,
                           "no lib/ under {}".format(sdk), remedy_sdk)
    else:
        sdk_check = _check("NAO: pynaoqi SDK", True, "SDK at {}".format(sdk))
    return [version_check, sdk_check, _nao_llm(config)]


def _nao_llm(config: Config) -> dict[str, Any]:
    """NAO's Launch target. Its .exe console shims broke when the folder moved,
    so what has to exist is the venv's python, not a script wrapper."""
    name = "NAO: NAO_LLM"
    remedy = ("check out NAO_LLM, create its venv, and set "
              "robots.naoqi.settings.nao_llm_path to the project folder")
    root = config.path("naoqi", "nao_llm_path")
    if root is None:
        return _check(name, True, "robots.naoqi.settings.nao_llm_path is not set",
                      remedy)
    if not root.is_dir():
        return _check(name, False, "{} does not exist".format(root), remedy)

    configured = config.path("naoqi", "nao_llm_python")
    python = configured or (root / "venv" / "Scripts" / "python.exe")
    if not python.exists():
        python = root / "venv" / "bin" / "python"
    if not python.exists():
        return _check(name, False,
                      "no venv python under {} -- Launch would fail".format(root),
                      "create the venv: py -3 -m venv venv && "
                      "venv\\Scripts\\pip install -r requirements.txt")
    return _check(name, True, "NAO_LLM at {}".format(root))


def _reachy_wireless(config: Config) -> list[dict[str, Any]]:
    if not config.robot("reachy_wireless").enabled:
        return [_check("Reachy-Mini: reachy_chat", True,
                       "reachy_wireless is disabled in config")]

    path = config.path("reachy_wireless", "reachy_chat_path")
    remedy = ("clone reachy_chat and set robots.reachy_wireless.settings."
              "reachy_chat_path to it")
    if path is None:
        return [_check("Reachy-Mini: reachy_chat", True,
                       "reachy_chat_path is not set", remedy),
                _check("Reachy-Mini: its venv", True, "no reachy_chat path to check")]
    if not path.is_dir():
        return [_check("Reachy-Mini: reachy_chat", False,
                       "{} does not exist".format(path), remedy),
                _check("Reachy-Mini: its venv", True, "no reachy_chat path to check")]

    python = config.path("reachy_wireless", "python") or _venv_python(path)
    venv_remedy = ("create the venv inside {}: python -m venv .venv, then "
                   "pip install -e .".format(path))
    venv = _check("Reachy-Mini: its venv", python.exists(),
                  "{}".format(python) if python.exists()
                  else "no interpreter at {}".format(python),
                  "" if python.exists() else venv_remedy)
    return [_check("Reachy-Mini: reachy_chat", True, "checkout at {}".format(path)), venv]


def _reachy_lite(config: Config) -> dict[str, Any]:
    if not config.robot("reachy_lite").enabled:
        return _check("Reachy-Mini-Lite: control app", True,
                      "reachy_lite is disabled in config")

    app = config.path("reachy_lite", "control_app")
    remedy = ("install the Reachy Mini Control desktop app (daemon 1.10.0 or "
              "newer) and point robots.reachy_lite.settings.control_app at its "
              "exe -- the Lite has no network stack, the app is its daemon (2.6)")
    if app is None:
        return _check("Reachy-Mini-Lite: control app", True,
                      "control_app is not set", remedy)
    if app.exists():
        return _check("Reachy-Mini-Lite: control app", True, "{}".format(app))

    sibling = _nearby_exe(app)
    if sibling is not None:
        return _check(
            "Reachy-Mini-Lite: control app", False,
            "{} does not exist, but {} does".format(app.name, sibling.name),
            "set robots.reachy_lite.settings.control_app = \"{}\"".format(
                str(sibling).replace("\\", "/")))
    return _check("Reachy-Mini-Lite: control app", False,
                  "{} does not exist".format(app), remedy)


def _furhat_key(config: Config) -> dict[str, Any]:
    if not config.robot("furhat").enabled:
        return _check("Furhat: FURHAT_API_KEY", True, "furhat is disabled in config")
    if config.secret("FURHAT_API_KEY"):
        return _check("Furhat: FURHAT_API_KEY", True, "present in the environment")
    return _check(
        "Furhat: FURHAT_API_KEY", True,
        "not set -- optional: Studio still works, the Realtime API does not",
        "the key is per-install: generate it in Furhat Studio and put "
        "FURHAT_API_KEY=... in .env (never in config.toml)")


def _interfaces() -> dict[str, Any]:
    try:
        import psutil
    except Exception as exc:  # noqa: BLE001
        return _check("network interfaces", False,
                      "cannot enumerate interfaces: {}".format(exc), INSTALL_ALL)
    import socket

    stats = psutil.net_if_stats()
    up: list[str] = []
    for name, addrs in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if stat is not None and not stat.isup:
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                up.append("{} {}".format(name, addr.address))
    if not up:
        return _check(
            "network interfaces", False, "no usable IPv4 interface is up",
            "join the robots' WiFi (or plug the cable in) -- every robot will "
            "look dead until you do (2.8)")
    return _check("network interfaces", True, "; ".join(up))


# ---------------------------------------------------------------- helpers
def _run(args: list[str]) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=SUBPROCESS_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        return "could not run it: {}".format(exc)
    return (proc.stdout + proc.stderr).strip().splitlines()[0] if (
        proc.stdout or proc.stderr) else ""


def _venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / ".venv" / "Scripts" / "python.exe"
    return root / ".venv" / "bin" / "python"


def _nearby_exe(app: Path) -> Optional[Path]:
    """The Reachy app has shipped under more than one exe name; if the folder
    is there, say which file to point at instead of just 'missing'."""
    try:
        if not app.parent.is_dir():
            return None
        for candidate in sorted(app.parent.glob("*.exe")):
            if "control" in candidate.name.lower():
                return candidate
    except OSError:
        return None
    return None


# ------------------------------------------------------------------- table
def _marker(check: dict[str, Any]) -> str:
    if not check["ok"]:
        return "FAIL"
    return "NOTE" if check["remedy"] else "PASS"


def main() -> None:
    checks = run_checks()
    width = max(len(c["name"]) for c in checks)
    print()
    print("Robot Hub doctor -- {}".format(REPO_ROOT))
    print("-" * (width + 60))
    for check in checks:
        print("{:4}  {:{w}}  {}".format(
            _marker(check), check["name"], check["detail"], w=width))
        if check["remedy"]:
            print("      {:{w}}  -> {}".format("", check["remedy"], w=width))
    failed = [c for c in checks if not c["ok"]]
    notes = [c for c in checks if c["ok"] and c["remedy"]]
    print("-" * (width + 60))
    print("{} checks, {} failed, {} notes.".format(len(checks), len(failed), len(notes)))
    if failed:
        print("Fix the FAIL lines above; the NOTE lines are robots you may "
              "simply not own.")
    # Always exit 0: the doctor reports, it does not gate. A missing robot is
    # not an error (12).


if __name__ == "__main__":
    main()
