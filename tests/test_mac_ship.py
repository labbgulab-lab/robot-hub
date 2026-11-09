"""Shipping the Mac student app: tools/build_release_mac.sh, tools/install-mac.sh
and .github/workflows/mac-release.yml.

Neither script can run for real off a Mac (the build needs the macOS runtime,
the installer needs macOS). What runs here: bash -n, a check for syntax the
bash 3.2 of macOS lacks, the installer's release picker and its .app maker
and the build's secret scan (with Git Bash on Windows), and the names the
contract fixes (asset names, install line, layout). The real build, install
and launch_mac.py --check run in the GitHub Action on macOS runners.
"""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
BUILD = REPO / "tools" / "build_release_mac.sh"
INSTALL = REPO / "tools" / "install-mac.sh"
WORKFLOW = REPO / ".github" / "workflows" / "mac-release.yml"
README = REPO / "README.md"
STUDENT = REPO / "docs" / "guides" / "STUDENT.md"
LAB_STAFF = REPO / "docs" / "guides" / "LAB-STAFF.md"
CURL_LINE = ("curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/"
             "download/install-mac.sh | bash")


def find_bash() -> str | None:
    """Git Bash on Windows (not the WSL bash.exe in System32/WindowsApps)."""
    if sys.platform == "win32":
        git = shutil.which("git")
        candidates = []
        if git:
            root = Path(git).resolve().parent.parent      # <Git>\cmd\git.exe -> <Git>
            candidates += [root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"]
        candidates.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe")
        for c in candidates:
            if c.is_file():
                return str(c)
        return None
    return shutil.which("bash")


BASH = find_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no bash (Git Bash) on this machine")


def run_bash(script: str, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", script, "bash", *args], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None, timeout=60)


def posix(path: Path) -> str:
    return path.as_posix()


# ------------------------------------------------------------------ syntax
@needs_bash
@pytest.mark.parametrize("script", [BUILD, INSTALL], ids=lambda p: p.name)
def test_bash_n_passes(script):
    res = subprocess.run([BASH, "-n", posix(script)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr


# Syntax newer than the bash 3.2 that macOS ships.
BASH4_ONLY = [
    (r"\bdeclare\s+-[a-zA-Z]*A", "declare -A (associative arrays)"),
    (r"\blocal\s+-[a-zA-Z]*A", "local -A (associative arrays)"),
    (r"\bmapfile\b", "mapfile"),
    (r"\breadarray\b", "readarray"),
    (r"\$\{[^}]*,,?\}", "${x,,} lower-casing"),
    (r"\$\{[^}]*\^\^?\}", "${x^^} upper-casing"),
    (r"\bcoproc\b", "coproc"),
    (r";;&|;&\s*$", "case fall-through ;& / ;;&"),
    (r"\|&", "|& pipes"),
    (r"&>>", "&>> appends"),
    (r"\$\{[^}]*@[QEPAKa]\}", "${x@Q} transformations"),
    (r"\bdeclare\s+-n\b|\blocal\s+-n\b", "namerefs"),
]


@pytest.mark.parametrize("script", [BUILD, INSTALL], ids=lambda p: p.name)
def test_no_bash4_only_syntax(script):
    text = script.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for pattern, what in BASH4_ONLY:
        hit = re.search(pattern, code, re.M)
        assert hit is None, "{} uses {}: {!r}".format(script.name, what, hit.group(0) if hit else "")


@pytest.mark.parametrize("script", [BUILD, INSTALL], ids=lambda p: p.name)
def test_scripts_are_lf_with_a_bash_shebang(script):
    raw = script.read_bytes()
    assert raw.startswith(b"#!/bin/bash\n")
    assert b"\r" not in raw
    assert not re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw), "a control character slipped in"


def test_installer_runs_everything_inside_main():
    """Under `curl | bash` a download cut short must run nothing: the last
    line calls main, and nothing above the helpers does any work."""
    lines = [l for l in INSTALL.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert lines[-1] == 'main "$@"'


# ------------------------------------------------------------------ contract names
def test_asset_names_match_the_contract():
    build = BUILD.read_text(encoding="utf-8")
    install = INSTALL.read_text(encoding="utf-8")
    flow = WORKFLOW.read_text(encoding="utf-8")
    assert 'NAME="RobotHub-mac-$ARCH-$VERSION"' in build
    assert 'TARBALL="$OUT_DIR/$NAME.tar.gz"' in build
    assert '"$TARBALL.sha256"' in build
    assert 'cp "$APP/install-mac.sh" "$OUT_DIR/install-mac.sh"' in build
    # The tarball's single top folder is app/.
    assert 'tar -c -z -f "$TARBALL" -C "$STAGING" app' in build
    assert 'prefix = "RobotHub-mac-" arch "-"' in install
    assert "RobotHub-mac-$arch-${tag#v}.tar.gz" in install
    assert "dist/RobotHub-mac-$ARCH-$VERSION.tar.gz" in flow
    name = "RobotHub-mac-{}-{}.tar.gz"
    for arch in ("arm64", "x86_64"):
        assert re.fullmatch(r"RobotHub-mac-(arm64|x86_64)-[0-9][0-9A-Za-z.+-]*\.tar\.gz",
                            name.format(arch, "1.0.6"))


def test_build_uses_the_same_python_as_windows():
    ps1 = (REPO / "tools" / "build_release.ps1").read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    release = re.search(r'PBS_RELEASE="(\d+)"', build).group(1)
    version = re.search(r'PY_VERSION="([\d.]+)"', build).group(1)
    assert "cpython-{}%2B{}-x86_64-pc-windows-msvc".format(version, release) in ps1
    assert "aarch64-apple-darwin" in build and "x86_64-apple-darwin" in build
    assert "SHA256SUMS" in build


def test_build_drops_the_tray_and_ships_the_mac_launcher():
    build = BUILD.read_text(encoding="utf-8")
    assert "pystray" in build and "grep -iv '^[[:space:]]*pystray'" in build
    assert 'cp "$APP/robot-hub/launch/launch_mac.py" "$APP/launch_mac.py"' in build
    assert 'cp "$APP/robot-hub/tools/install-mac.sh" "$APP/install-mac.sh"' in build
    assert "release-constraints.txt" in build
    for module in ("hub.main", "hub.group.woz", "numpy", "sounddevice", "onnxruntime"):
        assert module in build


def test_drop_lists_match_the_windows_build():
    ps1 = (REPO / "tools" / "build_release.ps1").read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    hub_drop = re.search(r'HUB_DROP="([^"]*)"', build).group(1).split()
    win = re.search(r"\$HubDrop = @\((.*?)\)", ps1, re.S).group(1)
    win_items = [s.replace("\\", "/") for s in re.findall(r'"([^"]+)"', win)]
    for item in win_items:
        if item == "Start Robot Hub.cmd":
            assert 'rm -f "$APP/robot-hub/Start Robot Hub.cmd"' in build
            continue
        assert item in hub_drop, item
    for mac_only in (".github", "tools/build_release_mac.sh", "tools/install-mac.sh"):
        assert mac_only in hub_drop and mac_only in win_items
    chat_drop = re.search(r'CHAT_DROP="([^"]*)"', build).group(1).split()
    win_chat = re.search(r"\$ChatDrop = @\((.*?)\)", ps1, re.S).group(1)
    assert sorted(chat_drop) == sorted(s.replace("\\", "/") for s in re.findall(r'"([^"]+)"', win_chat))
    # Same secret names and key regex as the Windows build.
    names = re.search(r'SECRET_NAMES="([^"]*)"', build).group(1).split()
    win_names = re.findall(r'"([^"]+)"', re.search(r"\$SecretNames = @\((.*?)\)", ps1, re.S).group(1))
    assert sorted(names) == sorted(win_names)
    key_re = re.search(r"KEY_RE='([^']*)'", build).group(1)
    win_re = re.search(r"\$KeyRegex = '([^']*)'", ps1).group(1)
    assert key_re.replace("_-]", "_\\-]") == win_re


def test_installer_layout_and_app_bundle_names():
    text = INSTALL.read_text(encoding="utf-8")
    assert 'ROOT="$HOME/Library/Application Support/LabaLab/RobotHub"' in text
    assert 'APPS_DIR="$HOME/Applications"' in text
    assert 'NAME="LabaLab Robot Hub"' in text
    assert 'BUNDLE_ID="il.ac.bgu.labalab.robothub"' in text
    assert "<string>robothub</string>" in text
    assert "<key>LSUIElement</key>\n\t<false/>" in text
    assert '"$app/runtime/bin/python3"' in text and '"$app/launch_mac.py"' in text
    assert "/api/app/quit" in text
    assert "xattr -dr com.apple.quarantine" in text
    assert "api.github.com/repos/$repo/releases?per_page=30" in text
    for option in ("--tar", "--root", "--apps-dir", "--no-launch", "--uninstall", "--remove-data"):
        assert option + ")" in text, option
    assert "done_line \"Unpacking (version $version)\"" in text


# ------------------------------------------------------------------ workflow
def load_workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads the key `on` as True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def test_workflow_is_a_manual_run_with_tag_and_upload():
    flow = load_workflow()
    inputs = flow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["tag"]["required"] is True
    assert inputs["upload"]["type"] == "boolean" and inputs["upload"]["default"] is True
    assert flow["permissions"]["contents"] == "write"


def test_workflow_matrix_has_both_macs():
    flow = load_workflow()
    job = flow["jobs"]["mac"]
    include = job["strategy"]["matrix"]["include"]
    arches = {row["arch"]: row["runner"] for row in include}
    assert set(arches) == {"arm64", "x86_64"}
    assert arches["arm64"].startswith("macos-")
    assert "intel" in arches["x86_64"] or arches["x86_64"] == "macos-13"
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_workflow_builds_installs_checks_and_uploads():
    flow = load_workflow()
    steps = flow["jobs"]["mac"]["steps"]
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "reachy-mini-conversation-app-bgu-lab.git" in runs
    assert 'bash tools/build_release_mac.sh "$ARCH"' in runs
    assert 'bash dist/install-mac.sh --tar "dist/RobotHub-mac-$ARCH-$VERSION.tar.gz"' in runs
    assert '--root "$RUNNER_TEMP/rh" --apps-dir "$RUNNER_TEMP/apps" --no-launch' in runs
    # The gate: launch_mac.py --check must say ok true and this version.
    assert '"$RUNNER_TEMP/rh/app/launch_mac.py" --check' in runs
    assert 'result.get("ok") is not True' in runs
    assert 'app.get("version") != want' in runs
    check = next(s for s in steps if "--check" in str(s.get("run", "")))
    assert "continue-on-error" not in check
    # The hub's tests run on macOS too, and a failure is not hidden.
    pytest_step = next(s for s in steps if s.get("id") == "pytest")
    assert "-m pytest tests" in pytest_step["run"]
    assert any("steps.pytest.outcome == 'failure'" in str(s.get("if", "")) and "exit 1" in s["run"]
               for s in steps)
    upload = next(s for s in steps if "gh release upload" in str(s.get("run", "")))
    assert upload["if"] == "${{ inputs.upload }}"
    assert "--clobber" in upload["run"]
    assert "install-mac.sh" in upload["run"] and ".sha256" in upload["run"]
    assert any(str(s.get("uses", "")).startswith("actions/upload-artifact@") for s in steps)


# ------------------------------------------------------------------ docs
def test_readme_and_guides_have_the_mac_install():
    readme = README.read_text(encoding="utf-8")
    assert CURL_LINE in readme
    assert "On a Mac" in readme
    assert "Cmd+Space" in readme
    assert "bash -s -- --uninstall" in readme
    assert re.search(r"NAO and Pepper.*Windows", readme)
    assert CURL_LINE in STUDENT.read_text(encoding="utf-8")
    staff = LAB_STAFF.read_text(encoding="utf-8")
    assert "Mac release" in staff and "draft" in staff.lower()
    for path in (README, STUDENT, LAB_STAFF):
        text = path.read_text(encoding="utf-8")
        assert not re.search("[\U0001F300-\U0001FAFF\u2600-\u27BF]", text), "{} has an emoji".format(path.name)


# ------------------------------------------------------------------ the installer's release picker
def releases_fixture() -> list:
    return [
        {"tag_name": "robot-files", "draft": False, "prerelease": False,
         "assets": [{"name": "x.skill", "browser_download_url": "https://x/f", "size": 1}]},
        {"tag_name": "v1.0.7", "draft": False, "prerelease": True,
         "assets": [{"name": "RobotHub-mac-arm64-1.0.7.tar.gz", "browser_download_url": "https://x/pre", "size": 5}]},
        {"tag_name": "v1.0.8", "draft": True, "prerelease": False,
         "assets": [{"name": "RobotHub-mac-arm64-1.0.8.tar.gz", "browser_download_url": "https://x/draft", "size": 5}]},
        # Windows only: never offered to a Mac.
        {"tag_name": "v1.0.11", "draft": False, "prerelease": False,
         "assets": [{"name": "RobotHub-1.0.11.zip", "browser_download_url": "https://x/win", "size": 5,
                     "uploader": {"login": "a", "list": [1, 2, {"deep": "]"}]}}]},
        {"tag_name": "v1.0.10", "draft": False, "prerelease": False, "author": {"login": "q"},
         "body": 'notes with "quotes", [brackets] and {braces}: RobotHub-mac-arm64-9.tar.gz',
         "assets": [
             {"name": "RobotHub-mac-arm64-1.0.10.tar.gz.sha256",
              "browser_download_url": "https://x/a10.sha256", "size": 90},
             {"name": "RobotHub-mac-arm64-1.0.10.tar.gz", "browser_download_url": "https://x/a10",
              "size": 120000000, "digest": "sha256:abc123", "uploader": {"login": "b"}},
             {"name": "RobotHub-mac-x86_64-1.0.10.tar.gz", "browser_download_url": "https://x/i10",
              "size": 7, "digest": None},
             {"name": "RobotHub-1.0.10.zip", "browser_download_url": "https://x/w10", "size": 9}]},
        {"tag_name": "v1.0.9", "draft": False, "prerelease": False,
         "assets": [{"name": "RobotHub-mac-arm64-1.0.9.tar.gz", "browser_download_url": "https://x/a9", "size": 1}]},
    ]


def pick(tmp_path: Path, releases, arch: str, indent=None) -> subprocess.CompletedProcess:
    data = tmp_path / "releases.json"
    data.write_text(json.dumps(releases, indent=indent), encoding="utf-8")
    return subprocess.run([BASH, posix(INSTALL), "--pick-release", posix(data), "--arch", arch],
                          capture_output=True, text=True, timeout=60)


@needs_bash
@pytest.mark.parametrize("indent", [None, 2], ids=["compact", "pretty"])
def test_picker_takes_the_newest_published_release_for_this_mac(tmp_path, indent):
    res = pick(tmp_path, releases_fixture(), "arm64", indent)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().split("|") == [
        "v1.0.10", "https://x/a10", "120000000", "sha256:abc123", "https://x/a10.sha256"]
    res = pick(tmp_path, releases_fixture(), "x86_64", indent)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().split("|") == ["v1.0.10", "https://x/i10", "7", "", ""]


@needs_bash
def test_picker_never_offers_a_windows_only_release(tmp_path):
    only_windows = [{"tag_name": "v2.0.0", "draft": False, "prerelease": False,
                     "assets": [{"name": "RobotHub-2.0.0.zip", "browser_download_url": "w", "size": 1}]}]
    res = pick(tmp_path, only_windows, "arm64")
    assert res.returncode != 0 and res.stdout.strip() == ""
    res = pick(tmp_path, [], "arm64")
    assert res.returncode != 0
    # The Intel tarball is not the Apple Silicon one.
    intel_only = [{"tag_name": "v2.0.0", "draft": False, "prerelease": False,
                   "assets": [{"name": "RobotHub-mac-x86_64-2.0.0.tar.gz", "browser_download_url": "i", "size": 1}]}]
    assert pick(tmp_path, intel_only, "arm64").returncode != 0
    assert pick(tmp_path, intel_only, "x86_64").stdout.startswith("v2.0.0|i|")


# ------------------------------------------------------------------ the installer's helpers
def installer_functions(tmp_path: Path) -> Path:
    """install-mac.sh without its last line (main "$@"): only the functions."""
    lines = INSTALL.read_text(encoding="utf-8").splitlines()
    assert lines[-1] == 'main "$@"'
    lib = tmp_path / "install-lib.sh"
    lib.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8", newline="\n")
    return lib


@needs_bash
def test_version_ge_and_hub_port(tmp_path):
    lib = posix(installer_functions(tmp_path))
    script = ('. "$1"; for p in "13.4 12.0" "12.0 12.0" "11.7.1 12.0" "15.1 15.0.1" "10.15 11.0"; do '
              'set -- $p; if version_ge "$1" "$2"; then echo "$1>=$2 yes"; else echo "$1>=$2 no"; fi; done')
    res = run_bash(script, lib)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n")[:5] == ["13.4>=12.0 yes", "12.0>=12.0 yes", "11.7.1>=12.0 no",
                                          "15.1>=15.0.1 yes", "10.15>=11.0 no"]
    data = tmp_path / "data"
    data.mkdir()
    res = run_bash('. "$1"; hub_port "$2"', lib, posix(data))
    assert res.stdout.strip() == "8099"
    (data / "config.toml").write_text("[server]\nport = 8111\n", encoding="utf-8")
    res = run_bash('. "$1"; hub_port "$2"', lib, posix(data))
    assert res.stdout.strip() == "8111"


@needs_bash
def test_make_bundle_writes_a_working_app(tmp_path):
    lib = posix(installer_functions(tmp_path))
    app = tmp_path / "Application Support" / "RobotHub" / "app"
    (app / "runtime" / "bin").mkdir(parents=True)
    (app / "robothub.icns").write_bytes(b"icns")
    bundle = tmp_path / "Applications" / "LabaLab Robot Hub.app"
    bundle.parent.mkdir()
    res = run_bash('. "$1"; make_bundle "$2" "$3" "1.2.3" "12.0" "LabaLab Robot Hub" "il.ac.bgu.labalab.robothub"',
                   lib, posix(bundle), posix(app))
    assert res.returncode == 0, res.stderr
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "robothub"
    assert info["CFBundleIdentifier"] == "il.ac.bgu.labalab.robothub"
    assert info["CFBundleName"] == "LabaLab Robot Hub"
    assert info["CFBundlePackageType"] == "APPL"
    assert info["CFBundleShortVersionString"] == "1.2.3"
    assert info["LSUIElement"] is False
    assert info["LSMinimumSystemVersion"] == "12.0"
    assert info["CFBundleIconFile"] == "robothub"
    assert info["NSMicrophoneUsageDescription"] and info["NSLocalNetworkUsageDescription"]
    assert (bundle / "Contents" / "Resources" / "robothub.icns").read_bytes() == b"icns"
    launcher = bundle / "Contents" / "MacOS" / "robothub"
    text = launcher.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash\n")
    exec_line = [l for l in text.splitlines() if l.startswith("exec ")][0]
    # The path has a space ("Application Support"): bash must still read it
    # as one word. Ask bash how it splits the exec line.
    assert exec_line.endswith(' "$@"')
    words = exec_line[len("exec "):-len(' "$@"')]
    res = run_bash('eval "set -- $1"; printf "%s\\n" "$@"', words)
    assert res.stdout.splitlines() == [posix(app / "runtime" / "bin" / "python3"),
                                       posix(app / "launch_mac.py")]
    # No icon file: no CFBundleIconFile.
    (app / "robothub.icns").unlink()
    res = run_bash('. "$1"; make_bundle "$2" "$3" "?" "" "LabaLab Robot Hub" "il.ac.bgu.labalab.robothub"',
                   lib, posix(bundle), posix(app))
    info = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    assert "CFBundleIconFile" not in info
    assert info["CFBundleShortVersionString"] == "0.0.0"
    assert info["LSMinimumSystemVersion"] == "11.0"


@needs_bash
def test_installer_refuses_another_os_and_odd_options(tmp_path):
    if sys.platform == "darwin":
        pytest.skip("this is the Mac")
    res = subprocess.run([BASH, posix(INSTALL), "--tar", "x.tar.gz", "--root", posix(tmp_path / "r"),
                          "--apps-dir", posix(tmp_path / "a"), "--no-launch", "--arch", "arm64"],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode != 0
    assert "for macOS" in res.stderr
    assert not (tmp_path / "r").exists()
    res = subprocess.run([BASH, posix(INSTALL), "--bogus"], capture_output=True, text=True, timeout=60)
    assert res.returncode != 0 and "Unknown option" in res.stderr


# ------------------------------------------------------------------ the build's secret scan
def build_helpers(tmp_path: Path) -> Path:
    """The build script's settings and helper functions, without the build."""
    text = BUILD.read_text(encoding="utf-8")
    head = text[:text.index("ARCH=\"\"\n")]
    helpers = text[text.index("# ---------------------------------------------------------------- helpers"):
                   text.index("# ---------------------------------------------------------------- (a)")]
    lib = tmp_path / "build-lib.sh"
    lib.write_text(head + "\ndie() { printf 'BUILD FAILED: %s\\n' \"$*\" >&2; exit 1; }\n"
                   "warn() { printf 'WARNING: %s\\n' \"$*\" >&2; }\n" + helpers,
                   encoding="utf-8", newline="\n")
    return lib


@needs_bash
def test_build_removes_private_files_and_fails_on_a_key(tmp_path):
    lib = posix(build_helpers(tmp_path))
    base = tmp_path / "bundle"
    (base / "hub" / "logs").mkdir(parents=True)
    (base / "hub" / "logs" / "today.txt").write_text("x", encoding="utf-8")
    (base / "hub" / "__pycache__").mkdir()
    (base / "hub" / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (base / "keys.local.json").write_text("{}", encoding="utf-8")
    (base / "Openai_Key.txt").write_text("x", encoding="utf-8")
    (base / "run.log").write_text("x", encoding="utf-8")
    (base / "notes.md").write_text("*.log and keys.local.json are left out\n", encoding="utf-8")
    res = run_bash('. "$1"; remove_secrets "$2" && assert_clean "$2" && echo CLEAN', lib, posix(base))
    assert res.returncode == 0, res.stderr
    assert "CLEAN" in res.stdout
    assert "left out a private file: keys.local.json" in res.stderr
    left = sorted(p.relative_to(base).as_posix() for p in base.rglob("*"))
    assert left == ["hub", "hub/main.py", "notes.md"]

    # A key-shaped string anywhere in a text file fails the build. (Built
    # here, so this test file holds no key-shaped string itself.)
    fake = "sk-" + "proj" + "A1b2C3d4" * 6
    (base / "hub" / "config_extra.py").write_text("KEY = '{}'\n".format(fake), encoding="utf-8")
    res = run_bash('. "$1"; assert_clean "$2"; echo AFTER', lib, posix(base))
    assert res.returncode != 0
    assert "holds a key" in res.stderr
    assert "config_extra.py" in res.stderr
    assert "AFTER" not in res.stdout
