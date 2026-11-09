#!/bin/bash
# LabaLab Robot Hub installer for macOS. For this Mac user only: no admin,
# no Python, no Git, no Xcode. Running it again updates.
#
#   curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install-mac.sh | bash
#
# With options (pass them after `bash -s --`, or to a saved copy):
#   curl -fsSL .../install-mac.sh | bash -s -- --uninstall [--remove-data]
#   bash install-mac.sh [--tar RobotHub-mac-<arch>-x.y.z.tar.gz] [--root <dir>]
#       [--apps-dir <dir>] [--no-launch] [--uninstall [--remove-data]]
#
# Layout (the Mac twin of tools/install.ps1):
#   <root>/app/       replaced on every install; the previous one stays as app.old
#   <root>/data/      the student's keys, settings, logs: never touched here
#                     (only --uninstall --remove-data deletes it)
#   <apps-dir>/LabaLab Robot Hub.app   the icon; it runs <root>/app/launch_mac.py
# root defaults to ~/Library/Application Support/LabaLab/RobotHub, apps-dir to
# ~/Applications. Installing with curl sets no quarantine flag, so Gatekeeper
# does not stop the unsigned app.
#
# This file is also the release asset install-mac.sh, and it sits in the
# tarball as app/install-mac.sh. The hub's Update button runs the curl line
# above in the background (output in <root>/data/logs/update.log).
#
# Bash 3.2 compatible (the one macOS ships): no associative arrays, no
# mapfile, no ${var,,}. Everything is inside main(), so a download cut short
# under `curl | bash` runs nothing.

main() {
    local REPO="labbgulab-lab/robot-hub"
    local NAME="LabaLab Robot Hub"
    local BUNDLE_ID="il.ac.bgu.labalab.robothub"
    local TAR="" ROOT="" APPS_DIR="" ARCH="" PICK_FROM=""
    local UNINSTALL=0 REMOVE_DATA=0 NO_LAUNCH=0

    while [ $# -gt 0 ]; do
        case "$1" in
            --tar) TAR="$2"; shift ;;
            --root) ROOT="$2"; shift ;;
            --apps-dir) APPS_DIR="$2"; shift ;;
            --repo) REPO="$2"; shift ;;
            --arch) ARCH="$2"; shift ;;
            --no-launch) NO_LAUNCH=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --remove-data) REMOVE_DATA=1 ;;
            --pick-release) PICK_FROM="$2"; shift ;;   # tests: print the pick from a saved releases JSON
            -h|--help) sed -n '2,12p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; return 0 ;;
            *) fail "Unknown option: $1"; return 2 ;;
        esac
        shift
    done

    [ -n "$ARCH" ] || ARCH=$(mac_arch)
    case "$ARCH" in
        arm64|aarch64) ARCH="arm64" ;;
        x86_64|i386) ARCH="x86_64" ;;
        *) fail "This Mac's processor ($ARCH) is not supported."; return 1 ;;
    esac

    if [ -n "$PICK_FROM" ]; then
        pick_release "$ARCH" < "$PICK_FROM"
        return $?
    fi

    [ -n "$ROOT" ] || ROOT="$HOME/Library/Application Support/LabaLab/RobotHub"
    [ -n "$APPS_DIR" ] || APPS_DIR="$HOME/Applications"
    ROOT=$(abs_path "$ROOT")
    APPS_DIR=$(abs_path "$APPS_DIR")
    local APP="$ROOT/app" APP_NEW="$ROOT/app.new" APP_OLD="$ROOT/app.old" DATA="$ROOT/data"
    local BUNDLE="$APPS_DIR/$NAME.app"
    local DOWNLOAD="$ROOT/download"

    echo ""
    say_title "LabaLab Robot Hub installer"
    echo "  Installing for this Mac user only. No admin needed."
    echo ""

    if [ "$(uname -s)" != "Darwin" ]; then
        fail "This installer is for macOS. On Windows, use the PowerShell line from the README."
        return 1
    fi

    # ------------------------------------------------------------ uninstall
    if [ "$UNINSTALL" = 1 ]; then
        stop_hub "$ROOT" "$DATA"
        rm -rf "$APP_NEW" "$APP" "$APP_OLD" "$DOWNLOAD" "$BUNDLE"
        if [ -e "$APP" ] || [ -e "$BUNDLE" ]; then
            fail "Could not remove the app. Quit Robot Hub and run the line again."
            return 1
        fi
        done_line "Removed the app and its icon"
        if [ "$REMOVE_DATA" = 1 ]; then
            rm -rf "$DATA"
            done_line "Removed your keys, settings and logs"
        elif [ -d "$DATA" ]; then
            say "Your keys, settings and logs stay in $DATA"
        fi
        rmdir "$ROOT" 2>/dev/null
        rmdir "$(dirname "$ROOT")" 2>/dev/null
        echo ""
        return 0
    fi

    mkdir -p "$ROOT" || { fail "Could not make the folder $ROOT"; return 1; }

    # ------------------------------------------------------------ get the bundle
    if [ -n "$TAR" ]; then
        TAR=$(abs_path "$TAR")
        if [ ! -f "$TAR" ]; then fail "No such file: $TAR"; return 1; fi
        done_line "Using $(basename "$TAR")"
    else
        rm -rf "$DOWNLOAD"
        mkdir -p "$DOWNLOAD"
        TAR="$DOWNLOAD/RobotHub.tar.gz"
        if ! download_release "$REPO" "$ARCH" "$TAR"; then
            rm -rf "$DOWNLOAD"
            rmdir "$ROOT" 2>/dev/null
            fail "The download failed. Check the internet connection and run the line again."
            return 1
        fi
    fi

    # ------------------------------------------------------------ unpack next to the old one
    say "Unpacking ..."
    rm -rf "$APP_NEW" "$ROOT/unpack"
    mkdir -p "$ROOT/unpack"
    if ! tar -x -z -f "$TAR" -C "$ROOT/unpack" 2>/dev/null || [ ! -d "$ROOT/unpack/app" ]; then
        rm -rf "$ROOT/unpack"
        fail "Unpacking failed. Download it again (run the line again)."
        return 1
    fi
    mv "$ROOT/unpack/app" "$APP_NEW"
    rm -rf "$ROOT/unpack"
    local f
    for f in runtime/bin/python3 robot-hub/hub/main.py launch_mac.py; do
        if [ ! -e "$APP_NEW/$f" ]; then
            rm -rf "$APP_NEW"
            fail "The bundle is incomplete ($f is missing)."
            return 1
        fi
    done
    local version="?" need=""
    [ -f "$APP_NEW/VERSION" ] && version=$(tr -d ' \r\n' < "$APP_NEW/VERSION")
    [ -f "$APP_NEW/MACOS_MIN" ] && need=$(tr -d ' \r\n' < "$APP_NEW/MACOS_MIN")
    if [ -n "$need" ] && command -v sw_vers >/dev/null 2>&1; then
        local have
        have=$(sw_vers -productVersion 2>/dev/null)
        if [ -n "$have" ] && ! version_ge "$have" "$need"; then
            rm -rf "$APP_NEW"
            fail "This Mac runs macOS $have. Robot Hub needs macOS $need or newer."
            return 1
        fi
    fi
    xattr -dr com.apple.quarantine "$APP_NEW" 2>/dev/null
    done_line "Unpacking (version $version)"

    # ------------------------------------------------------------ swap
    stop_hub "$ROOT" "$DATA"
    rm -rf "$APP_OLD"
    if [ -d "$APP" ]; then
        if ! mv "$APP" "$APP_OLD"; then
            fail "Robot Hub is still running. Quit it and run the line again."
            return 1
        fi
    fi
    mv "$APP_NEW" "$APP" || { fail "Could not put the new version in place."; return 1; }
    mkdir -p "$DATA"
    rm -rf "$DOWNLOAD"

    # ------------------------------------------------------------ the app icon
    if make_bundle "$BUNDLE" "$APP" "$version" "$need" "$NAME" "$BUNDLE_ID"; then
        done_line "$NAME in $(display_dir "$APPS_DIR")"
    else
        say "Could not make the app icon in $APPS_DIR"
    fi

    # ------------------------------------------------------------ open it
    if [ "$NO_LAUNCH" != 1 ]; then
        if open "$BUNDLE" </dev/null >/dev/null 2>&1; then
            done_line "Opening Robot Hub"
        else
            say "Open $NAME from $(display_dir "$APPS_DIR") to start it."
        fi
    fi
    echo ""
    say_ok "You can close this window."
    echo "  Next time, open $NAME from $(display_dir "$APPS_DIR") (or Launchpad)."
    echo "  To update, paste the same line again."
    echo ""
    return 0
}

# ---------------------------------------------------------------- output
if [ -t 1 ]; then
    C_OK=$(printf '\033[32m'); C_BAD=$(printf '\033[31m'); C_TITLE=$(printf '\033[33m'); C_END=$(printf '\033[0m')
else
    C_OK=""; C_BAD=""; C_TITLE=""; C_END=""
fi
say() { printf '  %s\n' "$*"; }
say_title() { printf '  %s%s%s\n' "$C_TITLE" "$*" "$C_END"; }
say_ok() { printf '  %s%s%s\n' "$C_OK" "$*" "$C_END"; }
done_line() { printf '  %sdone%s  %s\n' "$C_OK" "$C_END" "$*"; }
fail() { printf '\n  %s%s%s\n\n' "$C_BAD" "$*" "$C_END" >&2; }

# ---------------------------------------------------------------- helpers
abs_path() {
    case "$1" in
        /*) printf '%s' "$1" ;;
        *) printf '%s/%s' "$(pwd)" "$1" ;;
    esac
}

display_dir() {
    case "$1" in
        "$HOME"/*) printf '~/%s' "${1#"$HOME"/}" ;;
        *) printf '%s' "$1" ;;
    esac
}

mac_arch() {
    # A Terminal running under Rosetta says x86_64 on an Apple Silicon Mac;
    # the native app is the arm64 one.
    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then echo "arm64"; else uname -m; fi
}

version_ge() {   # version_ge 13.4 12.0 -> true
    local a1 a2 a3 b1 b2 b3
    IFS=. read -r a1 a2 a3 <<EOF
$1
EOF
    IFS=. read -r b1 b2 b3 <<EOF
$2
EOF
    a1=${a1:-0}; a2=${a2:-0}; a3=${a3:-0}; b1=${b1:-0}; b2=${b2:-0}; b3=${b3:-0}
    [ "$a1" -gt "$b1" ] && return 0; [ "$a1" -lt "$b1" ] && return 1
    [ "$a2" -gt "$b2" ] && return 0; [ "$a2" -lt "$b2" ] && return 1
    [ "$a3" -ge "$b3" ]
}

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
    else sha256sum "$1" | awk '{print $1}'; fi
}

hub_port() {   # hub_port <data dir>
    local port=8099 cfg="$1/config.toml" p
    if [ -f "$cfg" ]; then
        p=$(sed -n 's/^[[:space:]]*port[[:space:]]*=[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$cfg" | head -n 1)
        [ -n "$p" ] && port="$p"
    fi
    echo "$port"
}

our_pids() {   # our_pids <root>: the launcher, the hub, anything running from app/
    local root="$1" pid cmd
    ps -axww -o pid=,command= 2>/dev/null | while read -r pid cmd; do
        [ "$pid" = "$$" ] && continue
        case "$cmd" in
            *install-mac.sh*) continue ;;
            *"$root/app/"*|*"$root/app.new/"*|*"$root/app.old/"*) echo "$pid" ;;
        esac
    done
}

stop_hub() {   # stop_hub <root> <data>
    # Only a hub started from this install is asked to quit: a lab
    # checkout's hub on the same port is left alone.
    local root="$1" data="$2" port pids i
    pids=$(our_pids "$root")
    [ -n "$pids" ] || return 0
    say "Closing the running Robot Hub ..."
    port=$(hub_port "$data")
    curl -fsS -X POST --max-time 4 "http://127.0.0.1:$port/api/app/quit" >/dev/null 2>&1
    # Quit first stops every robot program (up to 20 s), then the port closes.
    i=0
    while [ $i -lt 60 ]; do
        pids=$(our_pids "$root")
        [ -n "$pids" ] || break
        sleep 0.5
        i=$((i + 1))
    done
    pids=$(our_pids "$root")
    if [ -n "$pids" ]; then
        kill $pids 2>/dev/null
        sleep 1
        pids=$(our_pids "$root")
        [ -n "$pids" ] && kill -9 $pids 2>/dev/null
    fi
    i=0
    while [ $i -lt 20 ] && curl -fsS --max-time 1 "http://127.0.0.1:$port/api/app" >/dev/null 2>&1; do
        sleep 0.5
        i=$((i + 1))
    done
    return 0
}

pick_release() {   # pick_release <arch> < releases.json
    # The newest published app release for this Mac: a v<number> tag (not a
    # draft, not a pre-release) that carries RobotHub-mac-<arch>-*.tar.gz.
    # Not /releases/latest: the repo's "robot-files" release can be the
    # latest one, and a Windows-only release has no Mac tarball.
    # Prints: tag|url|size|digest|sha256-asset-url (not tabs: read merges empty tab fields)
    # A small JSON reader in POSIX awk: macOS has no jq before 15, and its
    # python3 is only a stub without the Xcode tools.
    awk -v arch="$1" '
    function vcmp(a, b,    na, nb, pa, pb, i, x, y) {
        gsub(/[^0-9.]/, "", a); gsub(/[^0-9.]/, "", b)
        na = split(a, pa, "."); nb = split(b, pb, ".")
        for (i = 1; i <= 4; i++) {
            x = (i <= na && pa[i] != "") ? pa[i] + 0 : 0
            y = (i <= nb && pb[i] != "") ? pb[i] + 0 : 0
            if (x > y) return 1
            if (x < y) return -1
        }
        return 0
    }
    function value(v) {
        if (d == 2 && t[2] == "{") {
            if (k[2] == "tag_name") tag = v
            else if (k[2] == "draft") draft = (v == "true")
            else if (k[2] == "prerelease") pre = (v == "true")
        } else if (d == 4 && inassets && t[4] == "{") {
            if (k[4] == "name") aname = v
            else if (k[4] == "browser_download_url") aurl = v
            else if (k[4] == "size") asize = v
            else if (k[4] == "digest") adig = v
        }
    }
    function open_(c) {
        if (c == "[" && d == 2 && k[2] == "assets") inassets = 1
        d++; t[d] = c; k[d] = ""; expect = (c == "{")
        if (d == 2 && c == "{") { tag = ""; draft = 0; pre = 0; url = ""; size = ""; dig = ""; shaurl = "" }
        if (d == 4 && c == "{" && inassets) { aname = ""; aurl = ""; asize = ""; adig = "" }
    }
    function close_(c) {
        if (d == 4 && c == "}" && inassets) {
            if (index(aname, prefix) == 1 && substr(aname, length(aname) - 6) == ".tar.gz") {
                url = aurl; size = asize; dig = adig
            } else if (index(aname, prefix) == 1 && substr(aname, length(aname) - 13) == ".tar.gz.sha256") {
                shaurl = aurl
            }
        }
        if (d == 3 && c == "]" && inassets) inassets = 0
        if (d == 2 && c == "}") {
            if (!draft && !pre && tag ~ /^v[0-9]/ && url != "") {
                if (best == "" || vcmp(tag, best) > 0) {
                    best = tag; out = tag "|" url "|" size "|" dig "|" shaurl
                }
            }
        }
        d--
        if (d > 0) expect = 0
    }
    BEGIN { prefix = "RobotHub-mac-" arch "-"; d = 0; best = ""; out = ""; s = "" }
    { s = s $0 "\n" }
    END {
        n = length(s); i = 1
        while (i <= n) {
            c = substr(s, i, 1)
            if (c == "{" || c == "[") { open_(c); i++ }
            else if (c == "}" || c == "]") { close_(c); i++ }
            else if (c == ",") { if (t[d] == "{") expect = 1; i++ }
            else if (c == ":") { expect = 0; i++ }
            else if (c == "\"") {
                str = ""; i++
                while (i <= n) {
                    c = substr(s, i, 1)
                    if (c == "\\") { str = str substr(s, i + 1, 1); i += 2; continue }
                    if (c == "\"") break
                    str = str c; i++
                }
                i++
                if (t[d] == "{" && expect) { k[d] = str; expect = 0 } else value(str)
            }
            else if (c ~ /[-0-9a-z]/) {
                tok = ""
                while (i <= n && substr(s, i, 1) ~ /[-+.0-9a-zA-Z]/) { tok = tok substr(s, i, 1); i++ }
                value(tok == "null" ? "" : tok)
            }
            else i++
        }
        if (out == "") exit 1
        print out
    }'
}

download_release() {   # download_release <repo> <arch> <dest>
    local repo="$1" arch="$2" dest="$3" ua="LabaLab-RobotHub-installer"
    local json="$dest.releases.json" line tag url size digest shaurl want got
    line=""
    if curl -fsSL --max-time 30 -H "Accept: application/vnd.github+json" -H "User-Agent: $ua" \
            -o "$json" "https://api.github.com/repos/$repo/releases?per_page=30" 2>/dev/null; then
        line=$(pick_release "$arch" < "$json")
    fi
    rm -f "$json"
    if [ -n "$line" ]; then
        IFS="|" read -r tag url size digest shaurl <<EOF
$line
EOF
    else
        # The API allows 60 calls an hour per address; the release page's
        # redirect names the latest tag (v<version>) without it.
        tag=$(curl -fsSI --max-time 30 -H "User-Agent: $ua" "https://github.com/$repo/releases/latest" 2>/dev/null \
              | tr -d '\r' | sed -n 's/^[Ll]ocation:.*\/tag\/\(.*\)$/\1/p' | head -n 1)
        case "$tag" in
            v[0-9]*) ;;
            *) say "No Robot Hub release for Macs was found."; return 1 ;;
        esac
        url="https://github.com/$repo/releases/download/$tag/RobotHub-mac-$arch-${tag#v}.tar.gz"
        size=""; digest=""; shaurl="$url.sha256"
    fi
    local mb=""
    case "$size" in
        ''|*[!0-9]*) ;;
        *) mb=" ($(( (size + 524288) / 1048576 )) MB)" ;;
    esac
    say "Downloading$mb ..."
    if ! curl -fL --retry 2 --progress-bar -H "User-Agent: $ua" -o "$dest" "$url" </dev/null; then
        return 1
    fi
    want=""
    case "$digest" in
        sha256:*) want="${digest#sha256:}" ;;
    esac
    if [ -z "$want" ] && [ -n "$shaurl" ]; then
        want=$(curl -fsSL --max-time 30 -H "User-Agent: $ua" "$shaurl" 2>/dev/null | awk '{print $1; exit}')
    fi
    if [ -n "$want" ]; then
        got=$(sha256_of "$dest")
        want=$(printf '%s' "$want" | tr 'A-F' 'a-f')
        if [ "$got" != "$want" ]; then
            say "The download is damaged. Run the line again."
            return 1
        fi
    fi
    done_line "Downloading$mb"
    return 0
}

plist_escape() {
    printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

make_bundle() {   # make_bundle <bundle> <app dir> <version> <macos min> <name> <bundle id>
    local bundle="$1" app="$2" version="$3" need="$4" name="$5" bid="$6"
    local tmp="$bundle.new" icon_line=""
    rm -rf "$tmp"
    mkdir -p "$tmp/Contents/MacOS" "$tmp/Contents/Resources" || return 1
    if [ -f "$app/robothub.icns" ]; then
        cp "$app/robothub.icns" "$tmp/Contents/Resources/robothub.icns"
        icon_line="	<key>CFBundleIconFile</key>
	<string>robothub</string>"
    fi
    case "$version" in ''|'?') version="0.0.0" ;; esac
    [ -n "$need" ] || need="11.0"
    cat > "$tmp/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key>
	<string>$(plist_escape "$name")</string>
	<key>CFBundleDisplayName</key>
	<string>$(plist_escape "$name")</string>
	<key>CFBundleIdentifier</key>
	<string>$bid</string>
	<key>CFBundleExecutable</key>
	<string>robothub</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleShortVersionString</key>
	<string>$(plist_escape "$version")</string>
	<key>CFBundleVersion</key>
	<string>$(plist_escape "$version")</string>
$icon_line
	<key>LSMinimumSystemVersion</key>
	<string>$(plist_escape "$need")</string>
	<key>LSUIElement</key>
	<false/>
	<key>NSHighResolutionCapable</key>
	<true/>
	<key>NSMicrophoneUsageDescription</key>
	<string>Robot Hub listens to the people in the room during group conversations with the robots.</string>
	<key>NSLocalNetworkUsageDescription</key>
	<string>Robot Hub finds and connects to the lab robots on this WiFi.</string>
</dict>
</plist>
EOF
    local py launcher
    py=$(printf '%q' "$app/runtime/bin/python3")
    launcher=$(printf '%q' "$app/launch_mac.py")
    cat > "$tmp/Contents/MacOS/robothub" <<EOF
#!/bin/bash
# LabaLab Robot Hub: made by install-mac.sh. Starts the hub and opens it.
if [ ! -x $py ]; then
    /usr/bin/osascript -e 'display alert "Robot Hub is incomplete" message "Paste the install line into Terminal again."' >/dev/null 2>&1
    exit 1
fi
exec $py $launcher "\$@"
EOF
    chmod 755 "$tmp/Contents/MacOS/robothub"
    printf 'APPL????' > "$tmp/Contents/PkgInfo"
    rm -rf "$bundle"
    mv "$tmp" "$bundle" || return 1
    xattr -dr com.apple.quarantine "$bundle" 2>/dev/null
    # Finder and Launchpad pick up the new icon and version.
    local lsregister="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
    [ -x "$lsregister" ] && "$lsregister" -f "$bundle" >/dev/null 2>&1
    touch "$bundle"
    return 0
}

main "$@"
