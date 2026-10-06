#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""The whole of the hub's NAOqi surface, in Python 2.7 (PLAN.md 2.7).

NAOqi's Python SDK is Python 2.7 only, so the hub -- which is 3.11+ -- can
never import `naoqi`. Rather than shell out to a different ad-hoc snippet per
operation, everything goes through this one script: it reads a JSON command on
argv or stdin and prints exactly one JSON line, `{"ok": ...}`.

Keep this file valid Python 2.7. No f-strings, no annotations, no pathlib.

The retry loop here is not defensive noise. A raw TCP connect to 9559 succeeds
while the broker still refuses: `ALProxy` failed on the first attempt twice on
2026-09-14 and worked on retry, with ping steady at 1 ms throughout (2.3).
Retrying inside this process costs one broker handshake; retrying outside
costs a whole interpreter start, so the cheap retry lives here and the caller
retries the subprocess only if this still fails.
"""

from __future__ import print_function

import json
import sys
import time

PROXY_RETRIES = 2
PROXY_BACKOFF_S = 0.5

# Head and body ids are per-unit serials, which is what the card should be
# keyed on. Different NAOqi builds expose them under different ALMemory keys.
ID_KEYS = (
    ("head_id", "RobotConfig/Head/FullHeadId"),
    ("body_id", "RobotConfig/Body/FullBodyId"),
    ("base_version", "RobotConfig/Body/BaseVersion"),
)


def emit(payload):
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()


def as_bytes(value):
    """ALProxy is a SWIG binding over `char *` and rejects `unicode` outright.

    `json.loads` hands back `unicode` for every string in Python 2, so passing
    the decoded command straight through raises
    "Wrong number or type of arguments for overloaded function 'new_proxy'" --
    a type error that reads like a broken SDK rather than an encoding issue.
    """
    if isinstance(value, unicode):  # noqa: F821 - Python 2 only
        return value.encode("utf-8")
    return str(value)


def make_proxy(service, ip, port):
    from naoqi import ALProxy
    service, ip = as_bytes(service), as_bytes(ip)
    last = None
    for attempt in range(PROXY_RETRIES + 1):
        try:
            return ALProxy(service, ip, int(port))
        except Exception as exc:
            last = exc
            if attempt < PROXY_RETRIES:
                time.sleep(PROXY_BACKOFF_S)
    raise last


def cmd_ping(args):
    system = make_proxy("ALSystem", args["ip"], args["port"])
    return {"ok": True, "robot_name": system.robotName()}


def cmd_identity(args):
    system = make_proxy("ALSystem", args["ip"], args["port"])
    result = {"ok": True,
              "robot_name": system.robotName(),
              "system_version": system.systemVersion()}
    try:
        memory = make_proxy("ALMemory", args["ip"], args["port"])
    except Exception:
        return result
    for label, key in ID_KEYS:
        try:
            result[label] = memory.getData(key)
        except Exception:
            pass
    return result


def cmd_battery(args):
    battery = make_proxy("ALBattery", args["ip"], args["port"])
    return {"ok": True, "battery": int(battery.getBatteryCharge())}


def cmd_say(args):
    text = args.get("text") or ""
    if isinstance(text, unicode):  # noqa: F821 - Python 2 only
        text = text.encode("utf-8")
    tts = make_proxy("ALTextToSpeech", args["ip"], args["port"])
    tts.say(text)
    return {"ok": True, "said": args.get("text")}


# ------------------------------------------------------------------ posture
# The operator buttons on NAO's card. Same NAOqi steps as job/naoqi/stand.py
# and lie_down.py. Never Crouch and never ALMotion.rest(): a crouched NAO with
# its motors off fell over on 2026-10-05.
POSTURES = {
    "sit":   {"target": "Sit", "speed": 0.4, "motors_off": True},
    "lie":   {"target": "LyingBack", "speed": 0.4, "motors_off": True},
    "stand": {"target": "Stand", "speed": 0.5, "motors_off": False},
}
TEMPERATURE_KEY = "Device/SubDeviceList/%s/Temperature/Sensor/Value"
# The hub sends its own limit; this is only the fallback.
DEFAULT_MAX_TEMP_C = 60.0


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def read_temperatures(motion, memory):
    """{joint: degrees C} for every body joint that reports one."""
    names = list(motion.getBodyNames("Body"))
    keys = [TEMPERATURE_KEY % name for name in names]
    try:
        values = list(memory.getListData(keys))
    except Exception:
        # One unknown key fails the whole batch on some builds.
        values = []
        for key in keys:
            try:
                values.append(memory.getData(key))
            except Exception:
                values.append(None)
    temps = {}
    for name, value in zip(names, values):
        number = _number(value)
        if number is not None:
            temps[name] = number
    return temps


def hottest(temps):
    if not temps:
        return None, None
    joint = max(sorted(temps), key=lambda name: temps[name])
    return joint, temps[joint]


def park_autonomous_life(args):
    """Autonomous Life fights manual posture commands and would stand a limp
    robot back up -- stand.py, lie_down.py and rest.py all park it first."""
    try:
        life = make_proxy("ALAutonomousLife", args["ip"], args["port"])
        if life.getState() != "disabled":
            life.setState("disabled")
            time.sleep(1.0)
    except Exception:
        pass


def cmd_posture(args):
    spec = POSTURES.get(args.get("name"))
    if spec is None:
        return {"ok": False,
                "error": "unknown posture %r; known: %s"
                         % (args.get("name"), ", ".join(sorted(POSTURES)))}
    limit = _number(args.get("max_temp_c")) or DEFAULT_MAX_TEMP_C
    motion = make_proxy("ALMotion", args["ip"], args["port"])
    memory = make_proxy("ALMemory", args["ip"], args["port"])
    posture = make_proxy("ALRobotPosture", args["ip"], args["port"])

    # Heat guard: every one of these powers the motors, so nothing moves
    # until the hottest joint is known to be below the limit.
    temps = read_temperatures(motion, memory)
    joint, temp = hottest(temps)
    if joint is None:
        return {"ok": False, "refused": "no_temperatures"}
    if temp >= limit:
        return {"ok": False, "refused": "hot",
                "joint": joint, "temp_c": temp, "limit_c": limit}
    heat = {"joint": joint, "temp_c": temp}

    target = spec["target"]
    before = posture.getPosture()
    awake = motion.robotIsWakeUp()
    if before == target and awake != spec["motors_off"]:
        return {"ok": True, "already": True, "posture": before,
                "motors_off": not awake, "hottest": heat}

    park_autonomous_life(args)
    motion.wakeUp()     # NAO keeps its current position while stiffening
    reached = posture.goToPosture(target, spec["speed"])
    now = posture.getPosture()
    if not reached:
        # Unknown pose: dropping stiffness here could make it fall.
        return {"ok": False, "reached": False, "posture": now,
                "motors_off": False, "hottest": heat}

    if spec["motors_off"]:
        motion.setStiffnesses("Body", 0.0)
        time.sleep(0.3)
    return {"ok": True, "posture": now, "motors_off": spec["motors_off"],
            "hottest": heat}


COMMANDS = {
    "ping": cmd_ping,
    "identity": cmd_identity,
    "battery": cmd_battery,
    "say": cmd_say,
    "posture": cmd_posture,
}


def main():
    raw = sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()
    try:
        args = json.loads(raw)
    except Exception as exc:
        emit({"ok": False, "error": "could not read the command: %s" % exc})
        return 0

    name = args.get("cmd")
    handler = COMMANDS.get(name)
    if handler is None:
        emit({"ok": False,
              "error": "unknown command %r; known: %s"
                       % (name, ", ".join(sorted(COMMANDS)))})
        return 0

    args.setdefault("port", 9559)
    try:
        emit(handler(args))
    except ImportError as exc:
        emit({"ok": False,
              "error": "the pynaoqi SDK is not on PYTHONPATH (%s)" % exc})
    except Exception as exc:
        emit({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
