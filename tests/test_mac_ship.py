"""Shipping the Mac student app: tools/build_release_mac.sh, tools/install-mac.sh
and .github/workflows/mac-release.yml.

Neither script can run for real off a Mac (the build needs the macOS runtime,
the installer needs macOS). What runs here: bash -n, a check for syntax the
bash 3.2 of macOS lacks, the installer's release picker, download, .app maker
and failure paths (main() on a pretend Mac: uname, open and the alert are
faked) and the build's secret scan (with Git Bash on Windows), and the names
the contract fixes (asset names, install line, layout). The real build,
install and launch_mac.py --check run in the GitHub Action on macOS runners,
and this file runs there too with the Mac's own bash 3.2 and awk.
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


def sh_path(path: Path) -> str:
    """A path as bash sees it: /c/Users/... in Git Bash (GNU tar reads C:
    as a host name, and the installer takes only absolute /... paths)."""
    text = Path(path).resolve().as_posix()
    if sys.platform == "win32" and re.match(r"^[A-Za-z]:/", text):
        return "/" + text[0].lower() + text[2:]
    return text


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
    assert ' -c -z -f "$TARBALL" -C "$STAGING" app' in build
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
    # The installer's own tests run with the Mac's bash 3.2 and awk, and gate the job.
    ship = next(s for s in steps if "tests/test_mac_ship.py" in str(s.get("run", "")))
    assert "continue-on-error" not in ship
    # The rest of the hub's tests (written on Windows) are information only:
    # a warning in the summary, never a red job.
    pytest_step = next(s for s in steps if s.get("id") == "pytest")
    assert "-m pytest tests " in pytest_step["run"]
    assert pytest_step["continue-on-error"] is True
    assert not any("steps.pytest.outcome" in str(s.get("if", "")) for s in steps)
    assert not any("steps.pytest.outcome" in str(s.get("run", "")) and "exit 1" in str(s.get("run", ""))
                   for s in steps)
    upload = next(s for s in steps if "gh release upload" in str(s.get("run", "")))
    assert upload["if"] == "${{ inputs.upload }}"
    assert "--clobber" in upload["run"]
    assert ".sha256" in upload["run"]
    assert steps.index(ship) < steps.index(upload)
    assert any(str(s.get("uses", "")).startswith("actions/upload-artifact@") for s in steps)


def test_workflow_uploads_install_mac_sh_even_when_a_mac_job_fails():
    """Every release must carry install-mac.sh: the install line and the Mac
    Update fetch it from the latest release. One job after both Macs, whatever
    they did (not one per Mac: two --clobber uploads of one name race)."""
    flow = load_workflow()
    mac_upload = next(s for s in flow["jobs"]["mac"]["steps"] if "gh release upload" in str(s.get("run", "")))
    assert "install-mac.sh" not in mac_upload["run"]
    job = flow["jobs"]["install-script"]
    assert job["needs"] == "mac" or job["needs"] == ["mac"]
    assert "always()" in job["if"] and "inputs.upload" in job["if"]
    run = "\n".join(str(s.get("run", "")) for s in job["steps"])
    assert 'gh release upload "$TAG" tools/install-mac.sh --clobber' in run
    checkout = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ inputs.tag }}"


def test_windows_build_ships_install_mac_sh_and_the_same_reachy_chat():
    ps1 = (REPO / "tools" / "build_release.ps1").read_text(encoding="utf-8")
    assert '$macInstaller = Join-Path $PSScriptRoot "install-mac.sh"' in ps1
    assert '(Join-Path $OutDir "install-mac.sh")' in ps1
    # One reachy_chat for both: the same default ref, and the commit recorded in the bundle.
    win_ref = re.search(r'\[string\]\$ReachyChatRef = "([^"]+)"', ps1).group(1)
    flow = load_workflow()
    assert flow["on"]["workflow_dispatch"]["inputs"]["reachy_chat_ref"]["default"] == win_ref == "main"
    assert 'Join-Path $app "reachy_chat\\COMMIT"' in ps1
    build = BUILD.read_text(encoding="utf-8")
    assert 'printf \'%s\\n\' "$CHAT_COMMIT" > "$APP/reachy_chat/COMMIT"' in build
    for path in (README, LAB_STAFF):
        text = path.read_text(encoding="utf-8")
        assert "multi-provider" not in text, path.name
        assert "install-mac.sh" in text
    staff = LAB_STAFF.read_text(encoding="utf-8")
    assert "`dist\\install-mac.sh`" in staff
    assert "must be on `master`" in staff
    assert "macos-13" not in staff and "macos-13" not in WORKFLOW.read_text(encoding="utf-8")


def test_build_wheel_fallbacks_and_clean_tar():
    build = BUILD.read_text(encoding="utf-8")
    assert re.search(r'MAC_MINS="[^"]*\b15\.0\b', build)
    # The last resort takes wheels only; no package is built on the runner.
    assert "--prefer-binary" not in build
    last = build[build.index('if [ -z "$MACOS_MIN" ]; then'):build.index('printf \'%s\' "$MACOS_MIN"')]
    assert "--only-binary=:all:" in last
    # The onnxruntime retry runs only when onnxruntime is what failed.
    assert "grep -qi '^onnxruntime$'" in build
    # No runner xattrs (com.apple.provenance) in the tarball.
    assert 'COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -c -z -f "$TARBALL" -C "$STAGING" app' in build


@needs_bash
def test_build_names_the_package_with_no_wheel(tmp_path):
    text = BUILD.read_text(encoding="utf-8")
    start = text.index("missing_wheel() {")
    func = text[start:text.index("\n}\n", start) + 3]
    lib = tmp_path / "missing.sh"
    lib.write_text(func, encoding="utf-8", newline="\n")
    log = tmp_path / "pip.log"
    log.write_text("Collecting fastapi\n"
                   "ERROR: Could not find a version that satisfies the requirement numpy==2.5.4 "
                   "(from versions: 1.26.4)\n"
                   "ERROR: No matching distribution found for numpy==2.5.4\n", encoding="utf-8")
    res = run_bash('. "$1"; missing_wheel "$2"', sh_path(lib), sh_path(log))
    assert res.stdout.strip() == "numpy"
    log.write_text("ERROR: No matching distribution found for onnxruntime==1.31.0\n", encoding="utf-8")
    assert run_bash('. "$1"; missing_wheel "$2"', sh_path(lib), sh_path(log)).stdout.strip() == "onnxruntime"
    log.write_text("all fine\n", encoding="utf-8")
    assert run_bash('. "$1"; missing_wheel "$2"', sh_path(lib), sh_path(log)).stdout.strip() == ""


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


@needs_bash
def test_picker_reads_the_json_once_and_fast(tmp_path):
    """The macOS awk measures the whole string in every substr(): the picker
    splits the JSON once into characters instead. 30 releases with long notes
    and many assets (about half a MB) must stay quick."""
    text = INSTALL.read_text(encoding="utf-8")
    picker = text[text.index("pick_release() {"):text.index("download_release() {")]
    assert 'n = split(s, ch, "")' in picker
    assert "substr(s, i" not in picker and "substr(s," not in picker
    releases = []
    for n in range(30, 0, -1):
        assets = [{"name": "RobotHub-mac-{}-1.{}.0.tar.gz".format(a, n),
                   "browser_download_url": "https://x/{}/{}".format(a, n), "size": n,
                   "uploader": {"login": "lab", "id": n, "site_admin": False, "urls": ["u"] * 20}}
                  for a in ("arm64", "x86_64")]
        assets += [{"name": "extra-{}-{}.bin".format(n, k), "browser_download_url": "https://x/e",
                    "size": k, "uploader": {"login": "lab", "urls": ["u"] * 20}} for k in range(6)]
        releases.append({"tag_name": "v1.{}.0".format(n), "draft": False, "prerelease": False,
                         "body": "Notes, \"quoted\" and [long]. " * 400, "assets": assets})
    import time
    t0 = time.monotonic()
    res = pick(tmp_path, releases, "x86_64", indent=2)
    took = time.monotonic() - t0
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().split("|")[:2] == ["v1.30.0", "https://x/x86_64/30"]
    assert (tmp_path / "releases.json").stat().st_size > 400_000
    assert took < 30, "the picker took {:.1f} s".format(took)


# ------------------------------------------------------------------ download and failure paths
# A fake curl for download_release and main: answers by URL, from env vars.
#   API_JSON  file the releases API returns (empty: the API call fails)
#   LATEST    tag the /releases/latest redirect names (empty: no network)
#   DL        "ok": the tarball downloads (as the bytes "tarball"); else HTTP 404
#   SHA       what the .sha256 asset says
FAKE_CURL = r'''
curl() {
    local out="" url=""
    while [ $# -gt 0 ]; do
        case "$1" in
            -o) out="$2"; shift ;;
            http*) url="$1" ;;
        esac
        shift
    done
    echo "CURL $url" >> "$LOG"
    case "$url" in
        https://api.github.com/*)
            [ -n "$API_JSON" ] || return 22
            cat "$API_JSON" > "$out" ;;
        */releases/latest)
            [ -n "$LATEST" ] || return 6
            printf 'HTTP/2 302\r\nLocation: https://github.com/o/r/releases/tag/%s\r\n\r\n' "$LATEST" ;;
        *.sha256)
            printf '%s  x.tar.gz\n' "$SHA" ;;
        *)
            [ "$DL" = ok ] || return 22
            printf 'tarball' > "$out" ;;
    esac
}
'''
TARBALL_SHA = __import__("hashlib").sha256(b"tarball").hexdigest()


def run_download(tmp_path: Path, **env) -> tuple[int, str]:
    lib = installer_functions(tmp_path)
    log = tmp_path / "calls.log"
    log.write_text("", encoding="utf-8")
    full = dict(os.environ, LOG=sh_path(log), API_JSON="", LATEST="", DL="", SHA="")
    full.update(env)
    script = '. "$1"' + FAKE_CURL + 'download_release o/r arm64 "$2"; echo "rc=$?"'
    res = subprocess.run([BASH, "-c", script, "bash", sh_path(lib), sh_path(tmp_path / "dl.tar.gz")],
                         capture_output=True, text=True, timeout=60, env=full)
    rc = int(re.search(r"rc=(\d+)", res.stdout).group(1))
    return rc, log.read_text(encoding="utf-8")


def api_json(tmp_path: Path, releases) -> str:
    path = tmp_path / "api.json"
    path.write_text(json.dumps(releases), encoding="utf-8")
    return sh_path(path)


@needs_bash
def test_download_uses_the_redirect_only_when_the_api_call_failed(tmp_path):
    # The API answered, but no release has this Mac's tarball: no guessing.
    windows_only = [{"tag_name": "v2.0.0", "draft": False, "prerelease": False,
                     "assets": [{"name": "RobotHub-2.0.0.zip", "browser_download_url": "w", "size": 1}]}]
    rc, calls = run_download(tmp_path, API_JSON=api_json(tmp_path, windows_only), LATEST="v2.0.0", DL="ok")
    assert rc == 2
    assert "releases/latest" not in calls and "RobotHub-mac" not in calls
    # No network at all.
    rc, calls = run_download(tmp_path)
    assert rc == 1 and "releases/latest" in calls
    # The API failed (its hourly limit); the latest release is not an app release.
    assert run_download(tmp_path, LATEST="robot-files")[0] == 2
    # The latest release is Windows-only: the guessed tarball is a 404.
    rc, calls = run_download(tmp_path, LATEST="v1.2.3")
    assert rc == 2
    assert "https://github.com/o/r/releases/download/v1.2.3/RobotHub-mac-arm64-1.2.3.tar.gz" in calls
    # The guess works, checked against its .sha256 asset.
    assert run_download(tmp_path, LATEST="v1.2.3", DL="ok", SHA=TARBALL_SHA)[0] == 0
    assert run_download(tmp_path, LATEST="v1.2.3", DL="ok", SHA="0" * 64)[0] == 3


@needs_bash
def test_download_checks_the_api_digest(tmp_path):
    def releases(digest):
        return [{"tag_name": "v1.0.6", "draft": False, "prerelease": False,
                 "assets": [{"name": "RobotHub-mac-arm64-1.0.6.tar.gz", "browser_download_url": "https://x/a",
                             "size": 7, "digest": digest}]}]
    rc, calls = run_download(tmp_path, API_JSON=api_json(tmp_path, releases("sha256:" + TARBALL_SHA.upper())),
                             DL="ok")
    assert rc == 0 and "CURL https://x/a" in calls and "releases/latest" not in calls
    assert run_download(tmp_path, API_JSON=api_json(tmp_path, releases("sha256:" + "1" * 64)), DL="ok")[0] == 3
    assert run_download(tmp_path, API_JSON=api_json(tmp_path, releases(None)), DL="")[0] == 1


# main() on a pretend Mac: uname says Darwin, and open, the alert and
# stop_hub only write to the log. stdout is a file, as under the hub's Update.
FAKE_MAC = r'''
uname() { echo Darwin; }
open() { echo "OPEN $*" >> "$LOG"; return 0; }
show_alert() { echo "ALERT $1 | $2" >> "$LOG"; }
stop_hub() { echo "STOP" >> "$LOG"; }
sw_vers() { echo "${FAKE_MACOS:-14.5}"; }
xattr() { :; }
'''


def make_tarball(path: Path, version="9.9.9", macos_min="12.0") -> Path:
    import io
    import tarfile
    files = {"app/runtime/bin/python3": b"#!/bin/sh\n", "app/robot-hub/hub/main.py": b"",
             "app/launch_mac.py": b"", "app/VERSION": version.encode(), "app/MACOS_MIN": macos_min.encode()}
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))
    return path


class FakeMac:
    """An installed app (app/ with OLD_MARKER) and its icon, under tmp_path."""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.root = tmp_path / "Application Support" / "RobotHub"
        self.apps = tmp_path / "Applications"
        self.bundle = self.apps / "LabaLab Robot Hub.app"
        (self.root / "app").mkdir(parents=True)
        (self.root / "app" / "OLD_MARKER").write_text("old", encoding="utf-8")
        (self.bundle / "Contents").mkdir(parents=True)
        self.log = tmp_path / "calls.log"
        self.lib = installer_functions(tmp_path)

    def run(self, *args: str, extra: str = "", **env) -> tuple[int, str, str]:
        self.log.write_text("", encoding="utf-8")
        out = self.tmp / "main.out"
        full = dict(os.environ, LOG=sh_path(self.log), API_JSON="", LATEST="", DL="", SHA="")
        full.update(env)
        script = ('. "$1"' + FAKE_CURL + FAKE_MAC + extra
                  + '\nshift; main "$@" > "$OUT" 2>&1; echo "rc=$?"')
        full["OUT"] = sh_path(out)
        res = subprocess.run([BASH, "-c", script, "bash", sh_path(self.lib),
                              "--root", sh_path(self.root), "--apps-dir", sh_path(self.apps),
                              "--arch", "arm64", *args],
                             capture_output=True, text=True, timeout=120, env=full)
        rc = int(re.search(r"rc=(\d+)", res.stdout).group(1))
        return rc, self.log.read_text(encoding="utf-8"), out.read_text(encoding="utf-8")

    def old_app_intact(self) -> bool:
        return (self.root / "app" / "OLD_MARKER").is_file() and not (self.root / "app.new").exists()


@needs_bash
def test_a_failed_update_opens_the_old_app_and_says_so(tmp_path):
    mac = FakeMac(tmp_path)
    rc, calls, out = mac.run()          # no network
    assert rc == 1
    assert "The download failed" in out
    assert mac.old_app_intact()
    lines = calls.splitlines()
    # It waits for the quitting hub, then opens the old version, then the alert.
    assert lines.index("STOP") < lines.index("OPEN " + sh_path(mac.bundle))
    alert = [l for l in lines if l.startswith("ALERT ")]
    assert len(alert) == 1 and "Robot Hub could not update" in alert[0]
    assert "The download failed" in alert[0] and "The old version is open again." in alert[0]
    assert alert[0].endswith("data/logs/update.log")


@needs_bash
def test_a_mac_too_old_for_the_update_keeps_the_old_app(tmp_path):
    mac = FakeMac(tmp_path)
    tar = make_tarball(tmp_path / "new.tar.gz", macos_min="99.0")
    rc, calls, out = mac.run("--tar", sh_path(tar), FAKE_MACOS="13.6")
    assert rc == 1
    assert "Robot Hub needs macOS 99.0 or newer" in out
    assert mac.old_app_intact()
    assert "OPEN " + sh_path(mac.bundle) in calls
    assert "needs macOS 99.0" in calls
    # --no-launch (the CI run) never opens anything or shows an alert.
    rc, calls, out = mac.run("--tar", sh_path(tar), "--no-launch", FAKE_MACOS="13.6")
    assert rc == 1 and "OPEN" not in calls and "ALERT" not in calls
    # The API answered with no release for this Mac: says so, not "check the internet".
    windows_only = [{"tag_name": "v2.0.0", "draft": False, "prerelease": False,
                     "assets": [{"name": "RobotHub-2.0.0.zip", "browser_download_url": "w", "size": 1}]}]
    rc, calls, out = mac.run(API_JSON=api_json(tmp_path, windows_only))
    assert rc == 1 and "no Robot Hub release for this Mac (arm64)" in out
    assert "internet" not in out


@needs_bash
@pytest.mark.parametrize("which", ["app-to-old", "new-to-app"])
def test_a_failed_swap_puts_the_old_app_back(tmp_path, which):
    mac = FakeMac(tmp_path)
    tar = make_tarball(tmp_path / "new.tar.gz")
    pattern = {"app-to-old": '*"/app|"*"/app.old"', "new-to-app": '*"/app.new|"*"/app"'}[which]
    fake_mv = ('\nmv() { case "$1|$2" in ' + pattern + ') echo "MVFAIL" >> "$LOG"; return 1 ;; esac; '
               'command mv "$@"; }\n')
    rc, calls, out = mac.run("--tar", sh_path(tar), extra=fake_mv)
    assert rc == 1, out
    assert "MVFAIL" in calls
    assert mac.old_app_intact()
    assert not (mac.root / "app" / "VERSION").exists()
    assert "OPEN " + sh_path(mac.bundle) in calls and "ALERT " in calls


@needs_bash
def test_an_update_swaps_the_app_and_opens_the_new_one(tmp_path):
    mac = FakeMac(tmp_path)
    tar = make_tarball(tmp_path / "new.tar.gz")
    rc, calls, out = mac.run("--tar", sh_path(tar))
    assert rc == 0, out
    assert (mac.root / "app" / "VERSION").read_text(encoding="utf-8") == "9.9.9"
    assert (mac.root / "app.old" / "OLD_MARKER").is_file()
    assert (mac.root / "data").is_dir()
    info = plistlib.loads((mac.bundle / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == "9.9.9"
    assert calls.count("OPEN ") == 1 and "ALERT" not in calls
    assert "Unpacking (version 9.9.9)" in out


def test_every_failure_after_the_options_goes_through_on_fail():
    text = INSTALL.read_text(encoding="utf-8")
    main = text[text.index("main() {"):text.index("\n}\n", text.index("main() {"))]
    after_options = main[main.index("done\n"):]
    # Only the option parser itself uses plain fail.
    assert re.findall(r"(?<!on_)\bfail \"", after_options) == []
    assert after_options.count("on_fail ") >= 10
    on_fail = text[text.index("on_fail() {"):text.index("show_alert() {")]
    assert "[ -t 1 ] && return 0" in on_fail
    assert '[ "$NO_LAUNCH" = 1 ] && return 0' in on_fail
    assert 'open "$BUNDLE"' in on_fail and "stop_hub" in on_fail


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
