# -*- coding: utf-8 -*-
import sys
from naoqi import ALProxy
IP, PORT = "169.254.219.18", 9559

def show(label, fn):
    try:
        print("%-26s %s" % (label, fn()))
    except Exception as e:
        print("%-26s ERR %s" % (label, str(e)[:90]))

sysp = ALProxy("ALSystem", IP, PORT)
mem  = ALProxy("ALMemory", IP, PORT)

show("robotName",        lambda: sysp.robotName())
show("systemVersion",    lambda: sysp.systemVersion())
show("robotIcon/serial", lambda: mem.getData("RobotConfig/Body/BaseVersion"))
show("head id",          lambda: mem.getData("RobotConfig/Head/FullHeadId"))
show("battery %",        lambda: ALProxy("ALBattery", IP, PORT).getBatteryCharge())
show("posture",          lambda: ALProxy("ALRobotPosture", IP, PORT).getPosture())

print("\n--- AUDIO ---")
try:
    ad = ALProxy("ALAudioDevice", IP, PORT)
    show("output volume",    lambda: ad.getOutputVolume())
    show("output device",    lambda: ad.getParameter("outputDeviceName"))
    show("input device",     lambda: ad.getParameter("inputDeviceName"))
except Exception as e:
    print("ALAudioDevice ERR", str(e)[:120])

try:
    tts = ALProxy("ALTextToSpeech", IP, PORT)
    show("tts language",   lambda: tts.getLanguage())
    show("tts voice",      lambda: tts.getVoice())
    show("tts available",  lambda: tts.getAvailableLanguages())
except Exception as e:
    print("ALTextToSpeech ERR", str(e)[:120])

print("\n--- NETWORK ---")
try:
    con = ALProxy("ALConnectionManager", IP, PORT)
    show("services", lambda: [s for s in con.services()][:6])
    show("state",    lambda: con.state())
except Exception as e:
    print("ALConnectionManager ERR", str(e)[:120])

print("\n--- RUNNING SERVICES (first 45) ---")
try:
    svcs = ALProxy("ALServiceManager", IP, PORT).services()
    names = sorted([s[0] if isinstance(s, (list, tuple)) else str(s) for s in svcs])
    print(", ".join(names[:45]))
except Exception as e:
    print("ERR", str(e)[:120])
