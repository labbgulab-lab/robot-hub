# Pepper Say-It dashboard

Type text in the browser and Pepper says it, plus wave, nod yes, shake no and
volume. The hub's **Launch** on the Pepper card starts it and opens
http://127.0.0.1:8780/ (reachable from this laptop only).

It runs under the same Python 2.7 and pynaoqi SDK as the NAO card, set in
`[robots.naoqi.settings]` of `config.toml`, and needs nothing else. To run it
without the hub (Windows, paths from `tools/setup-windows.ps1`):

```powershell
$sdk = "$HOME\robot-lab\naoqi-sdk\<the pynaoqi-... folder holding lib\>"
$env:PYTHONPATH = "$sdk\lib"; $env:PATH = "$sdk\bin;$env:PATH"
C:\Python27\python.exe pepper_dashboard.py            # finds Pepper by itself
C:\Python27\python.exe pepper_dashboard.py <ip>       # or pin an address
```

## How it finds Pepper

1. An address you chose with **Connect** (or gave on the command line).
2. **Every address Pepper was ever found at**, newest first, saved in
   `known_addresses.json` next to this file (per laptop, not in git).
3. `Pepper.local` (mDNS).
4. A **scan of the laptop's own network** for port 9559, every 30 s while
   Pepper is missing, or on demand with **Scan this network**. Only a robot
   whose body type is Pepper counts; NAO is ignored. Networks larger than a
   /24 are only scanned in the laptop's own /24.

You can also **Add** an IP by hand, and **Forget** stale ones.

## Getting Pepper onto your hotspot

Pepper only joins WiFi networks it already knows. Teach it yours once with
**Add WiFi...** on the hub's Pepper card, while Pepper is still on a network
it knows and your hotspot is switched on. It remembers both afterwards.

Pressing Pepper's chest button once makes it say its current IP. "No IP /
can't connect" means it is on no network at all.

## Notes
- Speech is English only.
- Nod and shake briefly pause Pepper's face tracking, then restore it.
- The battery shows a bolt while charging. This dashboard never drives the
  wheels.
- Pepper's chest tablet has its own WiFi and takes a second place on the
  hotspot; the dashboard does not need it.
