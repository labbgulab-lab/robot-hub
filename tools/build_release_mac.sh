#!/bin/bash
# Build the Mac student app bundle: dist/RobotHub-mac-<arch>-<version>.tar.gz
# (+ .sha256, + dist/install-mac.sh). Runs ON macOS (the GitHub Actions
# runner, .github/workflows/mac-release.yml), on a Mac of the same arch.
#
#   bash tools/build_release_mac.sh arm64                       # HEAD of both repos
#   bash tools/build_release_mac.sh x86_64 --reachy-chat ../reachy_chat
#
# Options: --version X (default: VERSION of --ref, else 0.0.0), --ref <git ref
# of robot-hub> (default HEAD), --reachy-chat <checkout> (default ../reachy_chat
# or ../reachy-mini/reachy_chat), --reachy-chat-ref (default HEAD: the CI
# clones the main branch), --out <dir> (default dist), --from-working-tree
# (uncommitted work too, for testing; never publish that), --keep-staging.
#
# The Mac twin of tools/build_release.ps1, with the same rules:
#   runtime/      python-build-standalone CPython 3.12 (same release as the
#                 Windows build), sha256-checked against that release's
#                 SHA256SUMS, with requirements.txt + release-extra-requirements
#                 (minus the Windows tray, pystray) pip-installed INTO it (no
#                 venv: venvs hard-code their paths)
#   robot-hub/    git archive of --ref, without tests, docs, dev scripts
#   reachy_chat/  the same for reachy_chat (deployed onto the robots by the hub)
#   launch_mac.py, install-mac.sh, VERSION, MACOS_MIN, robothub.icns
#   reachy_chat/COMMIT  the reachy_chat commit inside (Windows writes it too)
#
# Never in the bundle: keys.local.json, .env, config.toml, group.local.json,
# logs/, cache/, data/, key files. The build removes any it finds and then
# fails if a file name or a key-shaped string is still there.
#
# Oldest macOS: wheels are picked for the oldest macOS they all support
# (11.0 first, then newer), not for the runner's own macOS, so a student on an
# older Mac gets packages that load there. The result is app/MACOS_MIN;
# install-mac.sh refuses an older Mac with a clear line.
#
# Bash 3.2 compatible (the one macOS ships).

set -e -o pipefail

# CPython 3.12 (3.13 drops audioop, which pepper_app uses). Same release as
# tools/build_release.ps1; bump both together.
PBS_RELEASE="20261021"
PY_VERSION="3.12.15"
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/$PBS_RELEASE"

# Files and folders that are never shipped, wherever they are (as build_release.ps1).
SECRET_NAMES="keys.local.json .env config.toml group.local.json keys.json backend.json hf_token.txt
hf_token.txt.bak .gemini_key openai_key.txt elevenlabs_key.txt robot_identity.json persona.json
known_addresses.json settings.json"
SECRET_PATTERNS="*_key.txt *.key *.gemini_key .keys-* *.skill *.log"
NEVER_DIRS="logs cache .venv venv __pycache__ .pytest_cache .mypy_cache conversations system_logs
archive backups"
# Key-shaped strings (OpenAI/OpenRouter, Gemini, ElevenLabs, Hugging Face).
KEY_RE='sk-(or-v1-)?[A-Za-z0-9_-]{32,}|AIza[0-9A-Za-z_-]{35}|sk_[0-9a-f]{40,}|hf_[A-Za-z0-9]{30,}'
TEXT_EXT="py json toml txt md js html css yaml yml ps1 cmd sh cfg ini"

# Per repo: what a student's laptop does not need (as build_release.ps1, plus
# the Mac build files and the CI workflow).
HUB_DROP="docs tests launch .github .gitignore .gitattributes .env.example CLAUDE.md NEXT-SESSION.md
PLAN.md run.ps1 run.sh pepper_app/data data tools/build_release.ps1
tools/install.ps1 tools/make_icon.py tools/release-extra-requirements.txt tools/release-constraints.txt
tools/setup-windows.ps1 tools/start-hub.ps1 tools/build_release_mac.sh tools/install-mac.sh
tools/release-constraints-mac.txt"
CHAT_DROP="docs tests .gitignore .gitattributes show/audio show/backups"

# Oldest macOS the wheels are picked for, tried in this order.
MAC_MINS="11.0 12.0 13.0 14.0 15.0"

ARCH=""
VERSION=""
REF="HEAD"
REACHY_CHAT=""
REACHY_CHAT_REF="HEAD"
OUT_DIR=""
FROM_WORKING_TREE=0
KEEP_STAGING=0

usage() {
    sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        arm64|aarch64) ARCH="arm64" ;;
        x86_64|intel) ARCH="x86_64" ;;
        --version) VERSION="$2"; shift ;;
        --ref) REF="$2"; shift ;;
        --reachy-chat) REACHY_CHAT="$2"; shift ;;
        --reachy-chat-ref) REACHY_CHAT_REF="$2"; shift ;;
        --out) OUT_DIR="$2"; shift ;;
        --from-working-tree) FROM_WORKING_TREE=1 ;;
        --keep-staging) KEEP_STAGING=1 ;;
        -h|--help) usage ;;
        *) echo "unknown option: $1" >&2; usage ;;
    esac
    shift
done

T0=$(date +%s)
step() { printf '[%5ss] %s\n' "$(( $(date +%s) - T0 ))" "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
die() { printf '\nBUILD FAILED: %s\n\n' "$*" >&2; exit 1; }

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    else sha256sum "$1" | awk '{print $1}'; fi
}

[ -n "$ARCH" ] || { echo "Which Mac? Pass arm64 or x86_64." >&2; usage; }
[ "$(uname -s)" = "Darwin" ] || die "this builds the Mac app and must run on macOS (the GitHub Action does)"
here_arch=$(uname -m)
if [ "$here_arch" != "$ARCH" ]; then
    warn "building $ARCH on a $here_arch Mac: the smoke test needs it to run here (Rosetta)"
fi
case "$ARCH" in
    arm64) PBS_TRIPLE="aarch64-apple-darwin" ;;
    x86_64) PBS_TRIPLE="x86_64-apple-darwin" ;;
esac

HUB_REPO=$(cd "$(dirname "$0")/.." && pwd)
[ -n "$OUT_DIR" ] || OUT_DIR="$HUB_REPO/dist"
mkdir -p "$OUT_DIR"
OUT_DIR=$(cd "$OUT_DIR" && pwd)

# ---------------------------------------------------------------- inputs
if [ -z "$REACHY_CHAT" ]; then
    for c in "$HUB_REPO/../reachy_chat" "$HUB_REPO/../reachy-mini/reachy_chat"; do
        if [ -f "$c/conversation.py" ]; then REACHY_CHAT="$c"; break; fi
    done
fi
[ -n "$REACHY_CHAT" ] && [ -d "$REACHY_CHAT" ] || die "reachy_chat checkout not found; pass --reachy-chat <folder>"
REACHY_CHAT=$(cd "$REACHY_CHAT" && pwd)

if [ -z "$VERSION" ]; then
    if [ "$FROM_WORKING_TREE" = 1 ]; then
        [ -f "$HUB_REPO/VERSION" ] && VERSION=$(tr -d ' \r\n' < "$HUB_REPO/VERSION")
    else
        VERSION=$(git -C "$HUB_REPO" show "$REF:VERSION" 2>/dev/null | tr -d ' \r\n') || VERSION=""
    fi
    [ -n "$VERSION" ] || VERSION="0.0.0"
fi
case "$VERSION" in
    *[!0-9A-Za-z.+-]*) die "odd version '$VERSION'" ;;
esac

STAGING="$OUT_DIR/build-mac-$ARCH"
APP="$STAGING/app"
CACHE="$OUT_DIR/cache"
NAME="RobotHub-mac-$ARCH-$VERSION"
TARBALL="$OUT_DIR/$NAME.tar.gz"
step "Robot Hub $VERSION for $ARCH Macs -> $TARBALL"
rm -rf "$STAGING"
mkdir -p "$APP" "$CACHE"

# ---------------------------------------------------------------- helpers
export_repo() {   # export_repo <repo> <ref> <dest>
    local repo="$1" ref="$2" dest="$3"
    mkdir -p "$dest"
    if [ "$FROM_WORKING_TREE" = 1 ]; then
        local n=0 rel
        while IFS= read -r -d '' rel; do
            [ -f "$repo/$rel" ] || continue   # deleted, not yet committed
            mkdir -p "$dest/$(dirname "$rel")"
            cp -p "$repo/$rel" "$dest/$rel"
            n=$((n + 1))
        done < <(git -C "$repo" ls-files -co --exclude-standard -z)
        echo "    $n files from the working tree of $repo"
    else
        git -C "$repo" archive --format=tar "$ref" | tar -x -f - -C "$dest" \
            || die "git archive ($ref) of $repo failed"
        echo "    $ref ($(git -C "$repo" rev-parse --short "$ref^{commit}")) of $repo"
    fi
}

remove_listed() {   # remove_listed <base> <space-separated relative paths>
    local base="$1" r
    for r in $2; do
        [ -e "$base/$r" ] && rm -rf "${base:?}/$r"
    done
    return 0
}

secret_find_expr() {
    # Prints a find(1) name test for every private file name and pattern.
    local first=1 n
    for n in $SECRET_NAMES $SECRET_PATTERNS; do
        if [ $first = 1 ]; then printf '%s\n' "-iname" "$n"; first=0
        else printf '%s\n' "-o" "-iname" "$n"; fi
    done
}

private_files() {   # private_files <base>: NUL-separated paths
    local base="$1" expr=() line
    while IFS= read -r line; do expr+=("$line"); done < <(set -f; secret_find_expr)
    find "$base" -type f \( "${expr[@]}" \) -print0
}

remove_secrets() {   # remove_secrets <base>
    local base="$1" d f
    for d in $NEVER_DIRS; do
        find "$base" -type d -name "$d" -prune -exec rm -rf {} + 2>/dev/null || true
    done
    while IFS= read -r -d '' f; do
        warn "left out a private file: ${f#"$base"/}"
        rm -f "$f"
    done < <(private_files "$base")
}

assert_clean() {   # assert_clean <base>
    local base="$1" f hits expr=() e first=1
    while IFS= read -r -d '' f; do
        die "private file in the bundle: $f"
    done < <(private_files "$base")
    for e in $TEXT_EXT; do
        if [ $first = 1 ]; then expr+=(-name "*.$e"); first=0; else expr+=(-o -name "*.$e"); fi
    done
    expr+=(-o "!" -name "*.*")
    hits=$(find "$base" -type f \( "${expr[@]}" \) -size -5M -print0 \
           | xargs -0 grep -nIE "$KEY_RE" /dev/null 2>/dev/null || true)
    if [ -n "$hits" ]; then
        printf '%s\n' "$hits" | cut -d: -f1,2 | sed 's/^/WARNING: key-shaped string: /' >&2
        die "the bundle looks like it holds a key; nothing was packed"
    fi
}

# ---------------------------------------------------------------- (a) (b) sources
step "robot-hub"
export_repo "$HUB_REPO" "$REF" "$APP/robot-hub"
# The launcher and the installer come from the same ref as the hub.
[ -f "$APP/robot-hub/launch/launch_mac.py" ] || die "launch/launch_mac.py (the Mac launcher) is missing in $REF"
[ -f "$APP/robot-hub/tools/install-mac.sh" ] || die "tools/install-mac.sh is missing in $REF"
cp "$APP/robot-hub/launch/launch_mac.py" "$APP/launch_mac.py"
cp "$APP/robot-hub/tools/install-mac.sh" "$APP/install-mac.sh"
chmod 755 "$APP/install-mac.sh"
ICON_SRC="$STAGING/labalab-mark-square.png"
cp "$APP/robot-hub/docs/design/img/labalab-mark-square.png" "$ICON_SRC" 2>/dev/null || ICON_SRC=""
remove_listed "$APP/robot-hub" "$HUB_DROP"
rm -f "$APP/robot-hub/Start Robot Hub.cmd"   # a name with spaces, so not in the list above
remove_secrets "$APP/robot-hub"

step "reachy_chat"
export_repo "$REACHY_CHAT" "$REACHY_CHAT_REF" "$APP/reachy_chat"
# Which reachy_chat this bundle deploys onto the robots: Windows and Mac
# builds of one version must hold the same commit.
if [ "$FROM_WORKING_TREE" = 1 ]; then
    CHAT_COMMIT="$(git -C "$REACHY_CHAT" rev-parse HEAD)+working-tree"
else
    CHAT_COMMIT=$(git -C "$REACHY_CHAT" rev-parse "$REACHY_CHAT_REF^{commit}")
fi
remove_listed "$APP/reachy_chat" "$CHAT_DROP"
remove_secrets "$APP/reachy_chat"

# ---------------------------------------------------------------- (c) runtime
PY_FILE="cpython-$PY_VERSION+$PBS_RELEASE-$PBS_TRIPLE-install_only.tar.gz"
PY_URL="$PBS_BASE/cpython-$PY_VERSION%2B$PBS_RELEASE-$PBS_TRIPLE-install_only.tar.gz"
PY_TGZ="$CACHE/$PY_FILE"
SUMS="$CACHE/SHA256SUMS-$PBS_RELEASE"
if [ ! -s "$SUMS" ]; then
    step "downloading SHA256SUMS of python-build-standalone $PBS_RELEASE"
    curl -fsSL --retry 3 -o "$SUMS.part" "$PBS_BASE/SHA256SUMS" || die "could not download SHA256SUMS"
    mv "$SUMS.part" "$SUMS"
fi
PY_SHA=$(awk -v f="$PY_FILE" '$2 == f || $2 == "*" f {print $1}' "$SUMS" | head -n 1)
[ -n "$PY_SHA" ] || die "$PY_FILE is not in the release's SHA256SUMS"
if [ ! -f "$PY_TGZ" ] || [ "$(sha256_of "$PY_TGZ")" != "$PY_SHA" ]; then
    step "downloading CPython $PY_VERSION ($PBS_TRIPLE)"
    curl -fsSL --retry 3 -o "$PY_TGZ" "$PY_URL" || die "could not download $PY_URL"
fi
got=$(sha256_of "$PY_TGZ")
if [ "$got" != "$PY_SHA" ]; then rm -f "$PY_TGZ"; die "CPython download has the wrong sha256 ($got)"; fi
step "runtime (sha256 ok)"
tar -x -z -f "$PY_TGZ" -C "$APP"
mv "$APP/python" "$APP/runtime"
PY="$APP/runtime/bin/python3"
[ -x "$PY" ] || die "the runtime has no bin/python3"
LIB="$APP/runtime/lib/python3.12"
SITE="$LIB/site-packages"
[ -d "$SITE" ] || die "the runtime has no $SITE"

step "pip install into the runtime"
export PYTHONNOUSERSITE=1 PIP_USER=0 PIP_REQUIRE_VIRTUALENV=0 PIP_DISABLE_PIP_VERSION_CHECK=1
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
"$PY" -c "import pip" 2>/dev/null || "$PY" -m ensurepip --default-pip || die "ensurepip failed"

REQ_HUB="$APP/robot-hub/requirements.txt"
[ -f "$REQ_HUB" ] || REQ_HUB="$HUB_REPO/requirements.txt"
REQ_ALL="$STAGING/requirements-mac.txt"
CONSTRAINTS="$STAGING/constraints-mac.txt"
{
    grep -v '^[[:space:]]*#' "$REQ_HUB"
    # The tray icon (pystray) is the Windows launcher's; the Mac one has none.
    grep -v '^[[:space:]]*#' "$HUB_REPO/tools/release-extra-requirements.txt" | grep -iv '^[[:space:]]*pystray' || true
} | grep -v '^[[:space:]]*$' > "$REQ_ALL"
# Pinned versions are the ones the hub's tests ran on (Windows). On Intel Macs
# onnxruntime stopped shipping wheels after the 1.2x series, so its pin is
# dropped there: pip takes the newest that has one. Further Mac-only pins or
# overrides go in tools/release-constraints-mac.txt (they replace a pin of the
# same name).
cp "$HUB_REPO/tools/release-constraints.txt" "$CONSTRAINTS"
if [ "$ARCH" = "x86_64" ]; then
    grep -iv '^onnxruntime==' "$CONSTRAINTS" > "$CONSTRAINTS.tmp" || true
    mv "$CONSTRAINTS.tmp" "$CONSTRAINTS"
fi
MAC_CONSTRAINTS="$HUB_REPO/tools/release-constraints-mac.txt"
if [ -f "$MAC_CONSTRAINTS" ]; then
    while IFS= read -r line; do
        case "$line" in ''|'#'*) continue ;; esac
        pkg=$(printf '%s' "$line" | sed 's/[[:space:]]*[<>=!~;].*//' | tr 'A-Z_' 'a-z-')
        awk -v p="$pkg" '{ n = tolower($0); gsub(/_/, "-", n); sub(/[ \t]*[<>=!~;].*/, "", n); if (n != p) print }' \
            "$CONSTRAINTS" > "$CONSTRAINTS.tmp"
        mv "$CONSTRAINTS.tmp" "$CONSTRAINTS"
        printf '%s\n' "$line" >> "$CONSTRAINTS"
    done < "$MAC_CONSTRAINTS"
fi

# zeroconf publishes no wheel for Intel Macs (checked 2026-11-09, up to
# 0.154): build it here as plain Python (SKIP_CYTHON=1, its own switch), tag
# that wheel py3-none-any and offer it to pip. Plain Python runs on any Mac;
# the build fails if anything compiled ended up inside.
WHEELHOUSE="$STAGING/wheelhouse"
mkdir -p "$WHEELHOUSE"
if [ "$ARCH" = "x86_64" ]; then
    step "zeroconf as plain Python (no Intel Mac wheel on PyPI)"
    zc_pin=$(grep -i '^zeroconf==' "$CONSTRAINTS" | head -n 1 | sed 's/^[^=]*==//')
    zc_spec="zeroconf${zc_pin:+==$zc_pin}"
    rm -rf "$STAGING/zc-raw" "$STAGING/wheeltool"
    SKIP_CYTHON=1 "$PY" -m pip wheel --no-deps --no-binary zeroconf "$zc_spec" \
        -w "$STAGING/zc-raw" > "$STAGING/pip-zeroconf.log" 2>&1 \
        || { tail -n 20 "$STAGING/pip-zeroconf.log"; die "could not build $zc_spec as plain Python"; }
    "$PY" -m pip install -q --no-warn-script-location --target "$STAGING/wheeltool" wheel \
        || die "could not get the wheel tool"
    for w in "$STAGING/zc-raw"/zeroconf-*.whl; do
        if unzip -l "$w" | grep -qE '\.(so|dylib)$'; then die "the zeroconf wheel holds compiled code: $w"; fi
        PYTHONPATH="$STAGING/wheeltool" "$PY" -m wheel tags --remove --python-tag py3 \
            --abi-tag none --platform-tag any "$w" > /dev/null || die "could not retag $w"
    done
    mv "$STAGING/zc-raw"/zeroconf-*-py3-none-any.whl "$WHEELHOUSE/" || die "no plain-Python zeroconf wheel"
    echo "    $(cd "$WHEELHOUSE" && ls zeroconf-*.whl)"
fi

pip_for_macos() {   # pip_for_macos <min macOS> <requirements file>: wheels for that macOS, into the runtime
    local min="$1" req="$2" target="$STAGING/site-$1"
    rm -rf "$target"
    "$PY" -m pip install --no-warn-script-location --only-binary=:all: \
        --find-links "$WHEELHOUSE" \
        --platform "macosx_${min%%.*}_${min#*.}_$ARCH" --target "$target" \
        -r "$req" -c "$CONSTRAINTS" > "$STAGING/pip-$min.log" 2>&1 || return 1
    rm -rf "$target/bin"
    cp -R "$target/." "$SITE/"
    rm -rf "$target"
    return 0
}

missing_wheel() {   # missing_wheel <pip log>: the package pip found no wheel for
    sed -n -e 's/.*No matching distribution found for \([A-Za-z0-9_.-]*\).*/\1/p' \
           -e 's/.*Could not find a version that satisfies the requirement \([A-Za-z0-9_.-]*\).*/\1/p' \
        "$1" 2>/dev/null | head -n 1
}

MACOS_MIN=""
LAST_LOG=""
try_mins() {   # try_mins <requirements file>
    local m
    for m in $MAC_MINS; do
        echo "    wheels for macOS $m or newer ..."
        if pip_for_macos "$m" "$1"; then MACOS_MIN="$m"; return 0; fi
        tail -n 3 "$STAGING/pip-$m.log" | sed 's/^/      /'
        LAST_LOG="$STAGING/pip-$m.log"
    done
    return 1
}

if ! try_mins "$REQ_ALL"; then
    # The newest macOS tried is the widest wheel choice: what fails there is the blocker.
    BLOCKER=$(missing_wheel "$LAST_LOG")
    echo "    no wheel for: ${BLOCKER:-(see $LAST_LOG)}"
    if [ "$ARCH" = "x86_64" ] && printf '%s' "$BLOCKER" | grep -qi '^onnxruntime$'; then
        # Without onnxruntime the hub runs; only the group talk's voice
        # detection (hub/group/vad.py) is missing.
        warn "no onnxruntime wheel fits an Intel Mac: building without it (group talk voice detection is off)"
        grep -iv '^[[:space:]]*onnxruntime' "$REQ_ALL" > "$REQ_ALL.noort" || true
        try_mins "$REQ_ALL.noort" || BLOCKER=$(missing_wheel "$LAST_LOG")
    fi
fi
if [ -z "$MACOS_MIN" ]; then
    # Last resort: this Mac's own wheels. Then the app needs this macOS or
    # newer. Wheels only: a package built here with the runner's compilers
    # may not load on a student's Mac.
    MACOS_MIN=$(sw_vers -productVersion | awk -F. '{print $1 ".0"}')
    warn "no wheel set fits an older macOS (no wheel for: ${BLOCKER:-see the pip logs}); using this runner's (macOS $MACOS_MIN or newer)"
    REQ_LAST="$REQ_ALL"
    [ -f "$REQ_ALL.noort" ] && REQ_LAST="$REQ_ALL.noort"
    "$PY" -m pip install --no-warn-script-location --only-binary=:all: \
        --find-links "$WHEELHOUSE" \
        -r "$REQ_LAST" -c "$CONSTRAINTS" || die "pip install failed: no Mac wheel for ${BLOCKER:-a package (see the log above)}"
fi
printf '%s' "$MACOS_MIN" > "$APP/MACOS_MIN"
echo "    the app needs macOS $MACOS_MIN or newer"

# ---------------------------------------------------------------- (d) prune, compile, smoke test
step "pruning"
remove_listed "$APP/runtime" "include share"
remove_listed "$LIB" "test idlelib lib2to3/tests ensurepip/_bundled"
find "$SITE" -type d -name tests -prune -exec rm -rf {} + 2>/dev/null || true
find "$SITE" -maxdepth 2 -type f -path '*.dist-info/RECORD' -exec rm -f {} + 2>/dev/null || true
find "$APP" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true

step "compileall"
# The runtime never changes after install: unchecked-hash pycs load without a
# look at the source. The hub's own code is checked against its source.
# reachy_chat is not compiled: it goes to robots.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$LIB" > /dev/null 2>&1 || true
"$PY" -m compileall -q -j 0 --invalidation-mode checked-hash "$APP/robot-hub" > /dev/null 2>&1 || true

step "smoke test"
"$PY" -I -c "import fastapi, uvicorn, pydantic_settings, httpx, websockets, zeroconf, psutil, paramiko, numpy, soundfile, sounddevice, tomli_w, PIL; print('    packages import')" \
    || die "importing the hub's packages failed"
if [ -d "$SITE/onnxruntime" ]; then
    "$PY" -I -c "import onnxruntime; print('    onnxruntime', onnxruntime.__version__)" || die "onnxruntime does not import"
else
    echo "    onnxruntime is not in this build"
fi
SMOKE_DATA="$STAGING/smoke-data"
mkdir -p "$SMOKE_DATA"
( cd "$APP/robot-hub" && ROBOT_HUB_DATA="$SMOKE_DATA" "$PY" -I -c \
    "import sys; sys.path.insert(0, '.'); import hub.config, hub.main, hub.group.woz; print('    hub.main and hub.group.woz import')" ) \
    || die "importing the hub failed"
rm -rf "$SMOKE_DATA"
# Anything the import left in the code folder (logs, caches) is not shipped;
# assert_clean below fails on a stray *.log.
remove_listed "$APP/robot-hub" "logs cache data"

# ---------------------------------------------------------------- (e) icon, version
if [ -n "$ICON_SRC" ] && command -v iconutil >/dev/null 2>&1; then
    ICONSET="$STAGING/robothub.iconset"
    mkdir -p "$ICONSET"
    if "$PY" -I - "$ICON_SRC" "$ICONSET" <<'PYEOF'
import sys
from pathlib import Path
from PIL import Image
src, out = Path(sys.argv[1]), Path(sys.argv[2])
mark = Image.open(src).convert("RGBA")
mark = mark.crop(mark.getbbox())
side = max(mark.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(mark, ((side - mark.width) // 2, (side - mark.height) // 2), mark)
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        px = size * scale
        name = "icon_{0}x{0}{1}.png".format(size, "@2x" if scale == 2 else "")
        square.resize((px, px), Image.LANCZOS).save(out / name)
PYEOF
    then
        iconutil -c icns -o "$APP/robothub.icns" "$ICONSET" && echo "    + robothub.icns" \
            || warn "iconutil failed; the app gets the default icon"
    else
        warn "could not draw the icon; the app gets the default icon"
    fi
    rm -rf "$ICONSET"
fi

printf '%s' "$VERSION" > "$APP/VERSION"
printf '%s' "$VERSION" > "$APP/robot-hub/VERSION"
printf '%s\n' "$CHAT_COMMIT" > "$APP/reachy_chat/COMMIT"

assert_clean "$APP/robot-hub"
assert_clean "$APP/reachy_chat"

# ---------------------------------------------------------------- (f) tar
step "packing"
rm -f "$TARBALL" "$TARBALL.sha256"
# COPYFILE_DISABLE: no ._ AppleDouble files. --no-xattrs --no-mac-metadata:
# no extended attributes of the runner's files (com.apple.provenance and the
# like) as pax headers, to be restored on every student's Mac.
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -c -z -f "$TARBALL" -C "$STAGING" app
TAR_SHA=$(sha256_of "$TARBALL")
printf '%s  %s\n' "$TAR_SHA" "$NAME.tar.gz" > "$TARBALL.sha256"
cp "$APP/install-mac.sh" "$OUT_DIR/install-mac.sh"
chmod 755 "$OUT_DIR/install-mac.sh"

APP_MB=$(du -sm "$APP" | awk '{print $1}')
TAR_MB=$(du -sm "$TARBALL" | awk '{print $1}')
[ "$KEEP_STAGING" = 1 ] || rm -rf "$STAGING"
step "done"
echo ""
echo "  $TARBALL"
echo "  tarball $TAR_MB MB, installed $APP_MB MB, macOS $MACOS_MIN or newer, sha256 $TAR_SHA"
echo "  reachy_chat $CHAT_COMMIT"
echo "  $OUT_DIR/install-mac.sh"
echo "  Release: tag v$VERSION, assets $NAME.tar.gz (+ .sha256) and install-mac.sh."
