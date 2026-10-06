# Setup

The hub itself needs Python 3.11+ and nothing else. Everything below is
per-robot, and **only if you own that robot** — a missing robot is a dim card,
a missing SDK is a disabled card with a message. Nothing blocks startup.

Run `python -m hub.doctor` (or `.\run.ps1 -Doctor`) at any point: it checks
every prerequisite here and prints the exact remedy for each one it cannot
find.

---

## The hub

```powershell
cp config.example.toml config.toml
cp .env.example .env
.\run.ps1
```

`config.toml` holds paths and preferences; `.env` holds keys and is
gitignored. Neither is committed. Nothing in `hub/` contains a lab-specific
address, MAC, or key — identity is discovered at runtime.

---

## The network

All four robots and the laptop must be on **one subnet**. In this lab that is
an iPhone hotspot; anything works as long as it is a **/24 or smaller** — the
hub refuses to sweep a larger range without `discovery.netscan_max_hosts`
raised explicitly.

Two things that have actually gone wrong here:

- **The laptop roams away silently.** It jumps from the hotspot to campus
  WiFi, every robot goes unreachable at the same instant, and nothing reports
  an error — it reads exactly like four hung robots. The hub watches its own
  interfaces and shows a banner, but the fix is to stop the laptop
  auto-joining the other network.
- **Check Point VPN lies about port 80.** Its adapter hooks outbound
  connections and makes `connect()` succeed for hosts that do not exist. That
  is why the Furhat detector requires a real HTTP response containing
  `<title>Furhat Studio</title>` and never treats an open socket as proof of
  life. If you write your own probe, do the same.

---

## Furhat

Nothing to install locally. Furhat is entirely robot-side.

1. **Bring the hotspot up *before* booting Furhat.** It only looks for a
   network at boot; if the hotspot appears afterwards it will not join.
2. The hotspot must offer **2.4 GHz** — on iPhone that means *Maximize
   Compatibility* on.
3. Furhat advertises **no mDNS whatsoever**, so the hub finds it by sweeping
   the subnet and fingerprinting Furhat Studio on port 80. Nothing to
   configure.
4. Optional: a **Realtime API key** (port 9000). It is generated per install in
   Furhat Studio and is regenerated whenever you re-pair, so it is
   user-supplied — put it in `.env` as `FURHAT_API_KEY`, never in
   `config.toml`, never in git.

Set the Studio login in `config.toml` under `[robots.furhat.settings]`.

---

## Reachy-Mini (wireless)

1. Install the **`reachy_chat`** checkout and create its venv, then point
   `[robots.reachy_wireless.settings] reachy_chat_path` at it.
2. Keep the robot's daemon at **1.10.0 or newer**. On 1.9.0 the daemon reports
   `ready: false` and `last_alive: null` permanently while the robot works
   perfectly — which would force two different health rules. Upgrade with
   `POST /update/start` (about 5 minutes). A desktop-app update can silently
   downgrade it, so the hub records and displays the daemon version on every
   connect; if a card starts showing an old version, that is why.
3. `mic_mode` decides where this robot listens:
   - `"robot"` — audio stays on the robot. No laptop device is claimed.
   - `"laptop"` — the K11 on the laptop is claimed, and the hub will then
     refuse to start NAO_LLM on the same microphone.

The hub allocates the dashboard port (9100–9199) and passes `--port`, so you do
not need 8765 free.

---

## Reachy-Mini-Lite

The Lite has **no network stack at all** — it is USB only, and the **Reachy
Mini Control desktop app is its daemon host**. The rule here is the inverse of
the wireless robot's:

| | Desktop app |
|---|---|
| Reachy-Mini-Lite | **must be running** |
| Reachy-Mini + `reachy_chat` | **must be closed** |

That second rule is scoped to *the robot the app is attached to*. The app holds
one robot at a time, and it has been verified that the app holding the Lite
does not interfere with the wireless robot — both Reachys can run at once.

Install the app, point `control_app` at its `.exe`, and leave the Lite plugged
in. Unplug it and the app exits about 34 seconds later, freeing port 8000; the
hub can start the app again itself when the Lite comes back.

Windows only: the detector uses WMI to watch for `VID_38FB`. On Linux the hub
uses `pyudev`; elsewhere the Lite card is disabled with a message.

---

## NAOqi

NAO is **Python 2.7 only** — the hub cannot import `naoqi`, so every NAO call
is a subprocess. You need:

1. **Python 2.7** — set `[robots.naoqi.settings] python2`.
2. The **pynaoqi SDK 2.8.6** — set `pynaoqi_sdk`. Note the SDK unpacks into a
   directory containing a directory of the same name; point at the inner one,
   the one that actually contains `lib/` and `bin/`.
3. **`NAO_LLM`** (the Antagonistic Robot) and its venv, for Launch.

### WiFi

**Provision NAO's WiFi over SSH — the NAOqi API cannot do it.**

```sh
ssh nao@<nao-ip>
connmanctl
  agent on
  scan wifi
  services
  connect wifi_xxxxxxxx_managed_psk
```

Then set `Favorite=True` and `AutoConnect=True` so it rejoins on boot.

### Two things that will look like bugs

- **Port 9559 accepts a TCP connection while the broker refuses.** A socket
  test is not a liveness test; only a successful `ALProxy` call is. The first
  attempt failing and the second succeeding is normal — the adapter retries.
- **`NAO_LLM`'s `.exe` console shims are broken** after the folder
  consolidation. Run it as `venv\Scripts\python.exe -m <module>`, which is what
  the hub does.

### The microphone

`NAO_LLM` captures with `sd.InputStream(...)` and **no `device=`**, so it takes
whatever Windows currently calls the default input — possibly the K11 that
Reachy is already using. The failure is indistinguishable from a broken
microphone, and it has already cost a demo, so the hub refuses the second
claim and names the holder.

NAO's own four-microphone array is healthy and balanced (measured at about
−31 dBFS on all four channels). Patching `NAO_LLM` to capture from
`ALAudioRecorder` instead removes the conflict entirely rather than managing
it — **and it is what lets NAO be in a different room from the laptop**, which
is the whole point. That is a change to `NAO_LLM`, not to the hub; the hub
arbitrates regardless, because it cannot assume every user has patched their
copy.
