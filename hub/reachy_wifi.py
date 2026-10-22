"""Teach a Reachy Mini a WiFi over SSH -- the card's "Add WiFi..." and
tools/reachy_add_wifi.py.

The lab WiFi is every robot's baseline: it has no internet, but a lab member's
laptop on it can reach any robot there and hand it their own hotspot. So
nobody needs a robot that already knows them, and no Pollen desktop app.

NetworkManager on the robot picks, among the networks in range, the profile
with the highest autoconnect-priority:

    lab hotspot ("lab WiFi")   -10   fallback, never preferred
    anything Pollen's app made   0   (e.g. "Tomer Iphone")
    a hotspot added here        10   wins whenever it is on

so a robot in the lab joins a lab member's hotspot whenever it is on, and
falls back to the lab WiFi when it is off.

When the new hotspot is in range the robot moves to it now. That runs
detached on the robot (setsid), because the SSH session dies with the old
network. If it cannot join, the robot goes back to the network it was on --
never to `reachy-mini-ap`, which is what the daemon's own `POST /wifi/connect`
does on failure -- and writes "fail" to RESULT_FILE for the hub to read.

Secrets: the sudo password and the WiFi password travel on stdin, never on a
command line the hub sends. On the robot the WiFi password is an nmcli
argument for the instant nmcli runs -- the same trade reachy_chat's
wifi_networks.py makes, acceptable on a lab robot. Neither is logged.
"""

from __future__ import annotations

import shlex
import time
from typing import Callable, Optional

LAB_PRIORITY = -10
HOTSPOT_PRIORITY = 10
RESULT_FILE = "/tmp/hub-wifi.result"
# nmcli --wait for the new network, then again for the way back.
JOIN_WAIT_S = 30
# How long the hub watches after scheduling a move: the 3 s head start, a
# failed join, the way back, and slack for SSH timeouts while it is away.
WATCH_S = 75.0
POLL_S = 4.0

# $1 ssid  $2 priority  $3 move: "1" = now if in range, "2" = now even unseen
# (bring-up: a robot hosting its own reachy-mini-ap cannot scan), "0" = never.
# stdin: sudo password, then the WiFi password, one per line.
ROBOT_SCRIPT = r"""
set -u
IFS= read -r SPW || true
IFS= read -r PSK || true
SSID=$1; PRIO=$2; SWITCH=$3
nm() { printf '%s\n' "$SPW" | sudo -S -p '' nmcli "$@"; }
# nmcli -t escapes '\' and ':' inside a field
ESC=${SSID//\\/\\\\}; ESC=${ESC//:/\\:}

DEV=$(nmcli -t -f DEVICE,TYPE device | awk -F: '$2=="wifi"{print $1; exit}')
[ -n "$DEV" ] || { echo "ERR this robot has no WiFi device"; exit 3; }

CUR=$(nmcli -t -f UUID,TYPE,DEVICE connection show --active \
      | awk -F: -v d="$DEV" '$2=="802-11-wireless" && $3==d {print $1; exit}')
CURNAME=""
[ -n "$CUR" ] && CURNAME=$(nmcli -g connection.id connection show uuid "$CUR")

# the profile that already holds this SSID, whatever it is called
PROFILE=""
for u in $(nmcli -t -f UUID,TYPE connection show | awk -F: '$2=="802-11-wireless"{print $1}'); do
  s=$(nmcli -g 802-11-wireless.ssid connection show uuid "$u" 2>/dev/null)
  if [ "$s" = "$SSID" ] || [ "$s" = "$ESC" ]; then PROFILE=$u; break; fi
done

nm device wifi rescan ifname "$DEV" >/dev/null 2>&1 && sleep 5
SEEN=no
if nmcli -t -f SSID device wifi list ifname "$DEV" --rescan no | grep -Fxq -- "$ESC"; then
  SEEN=yes
fi

NEW=old
if [ -n "$PROFILE" ]; then
  nm connection modify uuid "$PROFILE" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
     connection.autoconnect yes connection.autoconnect-priority "$PRIO" \
     || { echo "ERR NetworkManager would not update it"; exit 4; }
  ACTION=updated
else
  OUT=$(nm connection add type wifi con-name "$SSID" ifname "$DEV" ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
        connection.autoconnect yes connection.autoconnect-priority "$PRIO" 2>&1) \
     || { echo "ERR NetworkManager would not save it: $OUT"; exit 4; }
  PROFILE=$(printf '%s' "$OUT" | sed -n 's/.*(\([0-9a-f-]\{36\}\)).*/\1/p')
  ACTION=saved
  NEW=new
fi

MOVE=no
if { [ "$SWITCH" = 2 ] || { [ "$SWITCH" = 1 ] && [ "$SEEN" = yes ]; }; }    && [ -n "$PROFILE" ] && [ "$PROFILE" != "$CUR" ]; then
  printf '%s\n' "$SPW" | sudo -S -p '' setsid -f sh -c '
    : >RESULT_FILE
    sleep 3
    if nmcli --wait JOIN_WAIT connection up uuid "$1" >/tmp/hub-wifi.log 2>&1; then
      echo ok >RESULT_FILE
    else
      [ "$3" = new ] && nmcli connection delete uuid "$1" >>/tmp/hub-wifi.log 2>&1
      if [ -n "$2" ]; then nmcli --wait JOIN_WAIT connection up uuid "$2" >>/tmp/hub-wifi.log 2>&1
      else nmcli device connect "$4" >>/tmp/hub-wifi.log 2>&1; fi
      echo fail >RESULT_FILE
    fi' hubwifi "$PROFILE" "$CUR" "$NEW" "$DEV" >/dev/null 2>&1
  MOVE=yes
fi

echo "CURRENT $CURNAME"
echo "SEEN $SEEN"
echo "ACTION $ACTION"
echo "MOVE $MOVE"
""".replace("RESULT_FILE", RESULT_FILE).replace("JOIN_WAIT", str(JOIN_WAIT_S))

# run(command, stdin_text, timeout_s) -> (exit status, output); raises when the
# robot cannot be reached. Both callers wrap their own SSH in one of these.
Runner = Callable[[str, Optional[str], float], "tuple[int, str]"]


def check(ssid: str, password: str) -> str:
    ssid = (ssid or "").strip()
    if not ssid or len(ssid.encode("utf-8")) > 32:
        raise RuntimeError("a WiFi name has 1 to 32 characters")
    if ssid == "Hotspot" or ssid == "reachy-mini-ap":
        raise RuntimeError("that is the robot's own setup network")
    if not 8 <= len(password or "") <= 63:
        raise RuntimeError("a WiFi password has 8 to 63 characters")
    if "\n" in password or "\r" in password:
        raise RuntimeError("a WiFi password cannot contain a line break")
    return ssid


def command(ssid: str, lab: bool, priority: Optional[int] = None,
            move: Optional[str] = None) -> str:
    prio = priority if priority is not None else (LAB_PRIORITY if lab else HOTSPOT_PRIORITY)
    # The lab WiFi is only a fallback: learning it never moves the robot.
    if move is None:
        move = "0" if lab else "1"
    return "bash -c {} hubwifi {} {} {}".format(
        shlex.quote(ROBOT_SCRIPT), shlex.quote(ssid), int(prio), move)


def parse(output: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in output.splitlines():
        key, _, value = line.partition(" ")
        if key in ("CURRENT", "SEEN", "ACTION", "MOVE", "ERR"):
            out[key] = value.strip()
    return out


def teach(run: Runner, sudo_password: str, ssid: str, password: str,
          lab: bool = False, name: str = "The robot", *,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic) -> str:
    """Blocking; call through a thread. Returns a sentence for the card,
    raises RuntimeError with one otherwise."""
    ssid = check(ssid, password)
    status, output = run(command(ssid, lab),
                         "{}\n{}\n".format(sudo_password, password), 60.0)
    info = parse(output)
    if info.get("ERR"):
        raise RuntimeError(info["ERR"])
    if status != 0 or "ACTION" not in info:
        tail = output.strip().splitlines()[-1:] or ["exit {}".format(status)]
        if "incorrect password" in output.lower() or "sudo" in tail[0].lower():
            raise RuntimeError("the robot refused sudo -- set REACHY_SSH_PASSWORD")
        raise RuntimeError("the robot could not save it ({})".format(tail[0][:200]))
    current = info.get("CURRENT") or "its current network"

    if lab:
        return ("{} {} “{}” as the lab WiFi: its fallback whenever none of "
                "its hotspots is on. It stays on “{}” for now.".format(
                    name, "knows" if info["ACTION"] == "updated" else "learned",
                    ssid, current))
    if info.get("MOVE") != "yes":
        if current == ssid:
            return "{} is already on “{}”; its password is updated.".format(name, ssid)
        return ("{} saved “{}” but cannot see it right now, so it stays on “{}”. "
                "It joins “{}” by itself the next time it is on (2.4 GHz; "
                "iPhone: Maximize Compatibility) -- or power the robot off and on "
                "with it on.".format(name, ssid, current, ssid))

    # It is moving. Gone for good = it joined; "fail" = it came back.
    deadline = clock() + WATCH_S
    sleep(POLL_S)
    while clock() < deadline:
        try:
            _st, text = run("cat {} 2>/dev/null".format(RESULT_FILE), None, 8.0)
        except Exception:  # noqa: BLE001 -- away, as it should be
            text = ""
        word = text.strip()
        if word == "fail":
            return_word = "" if info["ACTION"] == "updated" else " and forgot it again"
            raise RuntimeError(
                "{} could not join “{}” (wrong password?){} -- it is back on "
                "“{}”".format(name, ssid, return_word, current))
        if word == "ok":
            break
        sleep(POLL_S)
    return ("{} moved to “{}” and will remember it. Connect this laptop to "
            "“{}” to see it again.".format(name, ssid, ssid))
