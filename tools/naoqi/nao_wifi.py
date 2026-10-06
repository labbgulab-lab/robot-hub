# -*- coding: utf-8 -*-
from naoqi import ALProxy
import time
IP, PORT = "169.254.219.18", 9559
con = ALProxy("ALConnectionManager", IP, PORT)

print("tethering state :", con.state())
try:
    print("scanning...")
    con.scan()
    time.sleep(5)
except Exception as e:
    print("scan err:", str(e)[:120])

def field(svc, key):
    for pair in svc:
        if pair[0] == key:
            return pair[1]
    return None

print("\n%-28s %-10s %-8s %-6s %s" % ("NAME", "TYPE", "STATE", "STR", "SECURITY"))
for s in con.services():
    name = field(s, "Name") or "(hidden)"
    print("%-28s %-10s %-8s %-6s %s" % (
        name[:28], field(s, "Type"), field(s, "State"),
        field(s, "Strength"), field(s, "Security")))

print("\nWiFi MAC (from ServiceId): 28:24:ff:46:1d:28")
