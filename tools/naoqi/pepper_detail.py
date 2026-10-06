# -*- coding: utf-8 -*-
"""Deep, read-only fingerprint of a Pepper (NAOqi 2.5). Moves nothing.

    cd ~/Desktop/job/naoqi
    sh run_naoqi.sh ../robot-hub/tools/naoqi/pepper_detail.py <ip>

Prints identity, network, speech, audio, tablet, cameras, sensors, joints,
postures, Autonomous Life, installed apps and the running services. Every
probe is wrapped, so one unsupported call does not end the run.
"""
from __future__ import print_function
import sys
from naoqi import ALProxy

IP, PORT = sys.argv[1], 9559


def px(name):
    try:
        return ALProxy(name, IP, PORT)
    except Exception as e:
        print("  %s unavailable: %s" % (name, str(e).strip().splitlines()[-1][:90]))
        return None


def show(label, fn):
    try:
        print("  %-28s %s" % (label, fn()))
    except Exception as e:
        print("  %-28s ERR %s" % (label, str(e).strip().splitlines()[-1][:90]))


def section(t):
    print("\n--- %s ---" % t)


mem = px("ALMemory")
sysp = px("ALSystem")

section("IDENTITY")
show("robotName", lambda: sysp.robotName())
show("systemVersion", lambda: sysp.systemVersion())
show("timezone", lambda: sysp.timezone())
for k in ["RobotConfig/Body/Type", "RobotConfig/Body/BaseVersion",
          "RobotConfig/Body/Version", "RobotConfig/Head/FullHeadId",
          "RobotConfig/Head/BaseVersion", "RobotConfig/Body/Device/LegCAN/Name",
          "RobotConfig/Head/Device/Micro/Version"]:
    show(k, lambda k=k: mem.getData(k))
show("battery %", lambda: px("ALBattery").getBatteryCharge())
show("battery current A", lambda: mem.getData("Device/SubDeviceList/Battery/Current/Sensor/Value"))

section("NETWORK")
con = px("ALConnectionManager")
if con:
    show("state", lambda: con.state())
    for s in con.services():
        d = dict((p[0], p[1]) for p in s)
        if d.get("State") not in ("idle", None):
            print("  %-10s %-14s %-8s mac=%s ipv4=%s" % (
                d.get("Type"), (d.get("Name") or "")[:14], d.get("State"),
                d.get("Ethernet", [[None, None]]), d.get("IPv4")))

section("SPEECH")
tts = px("ALTextToSpeech")
if tts:
    show("tts language", lambda: tts.getLanguage())
    show("tts languages", lambda: tts.getAvailableLanguages())
    show("tts voice", lambda: tts.getVoice())
    show("tts voices", lambda: tts.getAvailableVoices())
    show("tts volume", lambda: tts.getVolume())
asr = px("ALSpeechRecognition")
if asr:
    show("asr language", lambda: asr.getLanguage())
    show("asr languages", lambda: asr.getAvailableLanguages())
dlg = px("ALDialog")
if dlg:
    show("dialog language", lambda: dlg.getLanguage())
    show("dialog languages", lambda: dlg.getSupportedLanguages())
    show("loaded topics", lambda: dlg.getLoadedTopics(dlg.getLanguage()))

section("AUDIO")
ad = px("ALAudioDevice")
if ad:
    show("output volume", lambda: ad.getOutputVolume())
    show("audio out muted", lambda: ad.isAudioOutMuted())

section("TABLET")
tab = px("ALTabletService")
if tab:
    show("version", lambda: tab.version())
    show("robotIp (as tablet sees head)", lambda: tab.robotIp())
    show("wifi status", lambda: tab.getWifiStatus())
    show("wifi mac", lambda: tab.getWifiMacAddress())
    show("brightness", lambda: tab.getBrightness())
    show("screen on", lambda: tab.isScreenOn() if hasattr(tab, "isScreenOn") else "n/a")
    show("onTouch/methods", lambda: sorted(m for m in tab.getMethodList()
                                          if not m.startswith("_"))[:80])

section("CAMERAS")
vid = px("ALVideoDevice")
if vid:
    show("camera indexes", lambda: vid.getCameraIndexes() if hasattr(vid, "getCameraIndexes") else "n/a")
    for i, n in [(0, "top"), (1, "bottom"), (2, "depth")]:
        show("camera %d (%s) model" % (i, n), lambda i=i: vid.getCameraModel(i))
        show("camera %d (%s) name" % (i, n), lambda i=i: vid.getCameraName(i))

section("SENSORS (samples)")
for k in ["Device/SubDeviceList/Platform/Front/Sonar/Sensor/Value",
          "Device/SubDeviceList/Platform/Back/Sonar/Sensor/Value",
          "Device/SubDeviceList/Platform/LaserSensor/Front/Horizontal/Seg01/X/Sensor/Value",
          "Device/SubDeviceList/Platform/FrontRight/Bumper/Sensor/Value",
          "Device/SubDeviceList/Head/Touch/Front/Sensor/Value",
          "Device/SubDeviceList/LHand/Touch/Back/Sensor/Value",
          "Device/SubDeviceList/Platform/InertialSensorBase/AccX/Sensor/Value"]:
    show(k.replace("Device/SubDeviceList/", ""), lambda k=k: mem.getData(k))

section("MOTION")
mot = px("ALMotion")
if mot:
    show("body names", lambda: mot.getBodyNames("Body"))
    show("stiffness (body avg)", lambda: round(sum(mot.getStiffnesses("Body")) / len(mot.getStiffnesses("Body")), 2))
    show("wake", lambda: mot.robotIsWakeUp())
    show("external collision prot.", lambda: mot.getExternalCollisionProtectionEnabled("All"))
    show("move arms enabled", lambda: mot.getMoveArmsEnabled("Arms"))
pos = px("ALRobotPosture")
if pos:
    show("posture", lambda: pos.getPosture())
    show("postures", lambda: pos.getPostureList())

section("AUTONOMOUS LIFE")
life = px("ALAutonomousLife")
if life:
    show("state", lambda: life.getState())
    show("focused activity", lambda: life.focusedActivity())
    show("autonomous abilities", lambda: [(a, life.getAutonomousAbilityEnabled(a)) for a in
          ["AutonomousBlinking", "BackgroundMovement", "BasicAwareness",
           "ListeningMovement", "SpeakingMovement"]])

section("INSTALLED APPS")
bm = px("ALBehaviorManager")
if bm:
    show("default behaviors", lambda: bm.getDefaultBehaviors())
    try:
        inst = bm.getInstalledBehaviors()
        tops = sorted(set(b.split("/")[0] for b in inst))
        print("  %-28s %d behaviors in %d packages" % ("installed", len(inst), len(tops)))
        for t in tops:
            print("    " + t)
    except Exception as e:
        print("  installed ERR", str(e)[:90])

section("RUNNING SERVICES")
try:
    sm = px("ALServiceManager")
    names = sorted(str(s[0][1] if isinstance(s[0], (list, tuple)) else s[0]) for s in sm.services())
    print("  %d running" % len(names))
    print("  " + ", ".join(names))
except Exception as e:
    print("  ERR", str(e)[:90])
