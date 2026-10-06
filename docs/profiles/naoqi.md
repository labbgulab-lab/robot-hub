# naoqi (NAO)

Captured 2026-09-14. **NAO is now on the iPhone hotspot over WiFi — the
cable is gone.** The original capture was made over ethernet; addresses and
the network section below have been updated. Raw machine capture in
`naoqi.json` still holds the original link-local readings.

Scripts live in `job/naoqi/` (moved out of `job/pepper/` on 2026-09-14).

## A. Identity

| | |
|---|---|
| **IP (WiFi, current)** | **`172.20.10.14`** — DHCP from the iPhone hotspot |
| IP when cabled | `169.254.219.18` (link-local; only when the cable is plugged) |
| Ethernet MAC | `00:13:95:1F:59:3B` |
| **WiFi MAC** | **`28:24:FF:46:1D:28`** |
| Hostname | `nao.local` (mDNS) |
| Robot name | `nao` |
| Model | NAO **V6.0**, head `P0000074A04S8C300053` |
| NAOqi version | **2.8.5.10** |
| OS | OpenSSH 7.1, nginx 1.8.1 |

### mDNS works — and is the right detector
```
_naoqi._tcp.local    -> nao.local:9559  [172.20.10.14]
     RobotType=Nao   RobotMaterialization=Real   MdnsInterfaceLocal=0
_ssh._tcp            -> nao.local:22
_sftp-ssh._tcp       -> nao.local:22
```

**mDNS follows the active interface automatically.** It advertised
`169.254.219.18` while cabled and switched to `172.20.10.14` within seconds of
unplugging, with no intervention. The hub gets the correct address for free.

**The link-local address changes every session** — `naoqi_host.py` already says
so: *"Never hardcode it — mDNS always knows the current one."* Resolve
`nao.local` via `getaddrinfo(..., AF_INET)` (force IPv4; the AAAA record also
answers but the NAOqi broker wants IPv4).

Note Windows `ping nao.local` failed while zeroconf resolved it fine — so the
hub must do mDNS **itself**, not lean on the OS resolver.

### Discovery grouping
`_naoqi._tcp` is a different service type from Reachy's `_reachy-mini._tcp`,
but the same mechanism. **One mDNS browser covers NAO and Reachy-wireless.**
Furhat (no mDNS → ARP/MAC) and Reachy-Lite (USB PnP) still need their own.

## B. Reachability

**Over WiFi: 18 ms avg, 0% loss** (range 9-347 ms - the usual hotspot jitter).
Over the cable it was 1.0 ms. Fine for NAO's workload either way.

Open ports (full 1–10000 sweep): **22, 80, 7102, 8002, 9443, 9503, 9559**

| Port | What |
|---|---|
| 22 | SSH (OpenSSH 7.1) |
| 80 | nginx 1.8.1 — the robot's web page |
| **9559** | **NAOqi broker** — the one that matters |
| 7102 | `LoLA - Web Debug` (server header `LoLADbgItf`) — low-level joint bus debug |
| 8002 | TornadoServer 4.3 (404 on probes) |
| 9443, 9503 | open, unidentified |

### ⚠️ Port 9559 opens BEFORE the broker is ready
First `ALProxy("ALMemory", ...)` failed with:
```
RuntimeError: ALBroker::createBroker  Cannot connect to tcp://169.254.219.18:9559
```
while a raw TCP connect to 9559 was *intermittent* — one timeout, then two
successes — with ping rock-solid at 1 ms throughout. A retry moments later
connected fine.

**Same class of trap as Reachy's `ready:false`: the port is a lie.** A card
that goes green on "9559 is open" will show ready while every call still
fails. **Liveness = a successful `ALProxy` call, not an open socket**, and the
hub must retry rather than declare failure on the first miss.

## C. Surface — NAOqi SDK, not HTTP

No REST API. Everything goes through the NAOqi broker via proxies:
`ALMemory`, `ALSystem`, `ALBattery`, `ALRobotPosture`, `ALTextToSpeech`,
`ALAudioDevice`, `ALConnectionManager`, `ALServiceManager`, … **45 services
running.**

### Live state at capture
```
robotName    nao            systemVersion  2.8.5.10
body/head    Nao / Nao      base version   V6.0
battery      100%           posture        LyingBack
services     45 running     tts            English, voice "naoenu"
tts langs    Japanese, Chinese, English
audio out    volume 100
```

### ✅ Battery IS reported
`ALBattery.getBatteryCharge()` → `100`. **Unlike both Reachys**, NAO can show a
real battery percentage on its card. Worth surfacing — it is the only robot of
the four that can.

`ALAudioDevice.getParameter("inputDeviceName"/"outputDeviceName")` is **not
supported** on this version (raises). Volume reads fine.

## D. Ownership on the laptop — Python 2.7 + pynaoqi

The hard constraint. NAOqi's Python SDK is **Python 2.7 only**:

```sh
SDK="/c/Users/tomer/Documents/NAO_GROK/pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649/pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649"
PYTHONPATH="$SDK/lib" PATH="$SDK/bin:$PATH" /c/Python27/python.exe "$@"
```
(that doubled directory name is real — see `pepper/run_naoqi.sh`)

**The hub cannot import `naoqi` directly.** Whatever it is written in, NAO
control must be a **subprocess call out to Python 2.7** with that environment.
That is the single biggest structural difference between NAO and the others,
and it argues for the supervisor model we already chose: the hub shells out,
it does not link in.

### No fixed laptop port
The qi messaging session opens an **ephemeral** listener (observed
`:51437`) and binds **every** laptop interface:
```
tcp://172.20.10.4:51437   tcp://169.254.227.14:51437
tcp://127.0.0.1:51437     tcp://100.98.102.61:51437
```
So nothing to allocate — but note it advertises itself on all interfaces
including **Tailscale**. Multi-homing is something qi messaging can get
confused by; worth remembering if a connection misbehaves.

### Existing material (`job/naoqi/`)
`connect_naoqi.py` (identify + battery + posture), `find_robots.py`,
`naoqi_host.py` (mDNS resolver), `run_naoqi.sh`, `say.py`, `stand.py`.
There is **no conversation pipeline** for NAO — unlike Reachy. Its card starts
much simpler.

New reusable probes saved to `robot-hub/tools/naoqi/`:
`nao_detail.py` (identity/battery/TTS/network), `nao_wifi.py` (scan + list).

### Check Point VPN caveat — already known, now confirmed in place
`Ethernet 2` is `Check Point Virtual Network Adapter For Endpoint VPN Client`
(currently **Disconnected**). `find_robots.py` documents that it hooks
outbound port-80 connects and makes `connect()` succeed for hosts that do not
exist. **Port 80 is not a valid liveness probe on this laptop.** Port 9559 is
not hooked. The hub should ICMP-gate and require a real HTTP reply, exactly as
that script does.

## E. Audio — depends entirely on WHICH system you run ⚠️

### Bare NAOqi scripts: fully onboard
`say.py`, `stand.py`, `connect_naoqi.py` — NAO speaks through its own speakers
(`ALTextToSpeech`) and, if asked, listens through its own 4-mic array. Both
run **on the robot**. No laptop audio device is touched.

### 🔴 CORRECTION (2026-09-14): NAO's real systems DO use the laptop mic
An earlier version of this file concluded "the mic lock is unnecessary".
**That was wrong.** It was true of the bare scripts above, but not of the
systems NAO actually runs:

| System | Capture call | Device |
|---|---|---|
| `NAO_LLM` | `sd.InputStream(...)` in `antagonist_robot/pipeline/audio_capture.py:71` | **no `device=` argument → Windows default input** |
| `NAO_LLM_v2` | `sd.rec(...)` in `audio/asr_streaming.py:110`, `audio/asr_whisper.py:25` | same |

`NAO_LLM_v2`'s README states it plainly: *"Simulation mode (PC microphone and
speakers) — current default."* `config.yaml` has an `audio.device: "auto"` key
but it is **not** passed to `InputStream` on this code path.

### Why this is worse than a plain conflict
NAO does not ask for a *named* device — it takes whatever Windows currently
calls **default**. If the K11 receiver is plugged into the laptop and is the
default, **NAO silently captures the K11**, i.e. the wireless Reachy's
microphone. The symptom is indistinguishable from a broken mic, which is
exactly the failure class `reachy_chat`'s notes say already cost a demo.

### Current picture
| Robot / mode | Capture device |
|---|---|
| Reachy-Lite | own USB audio (`Reachy Mini Audio`) — no laptop device |
| Furhat | own ReSpeaker 4 Mic Array — no laptop device |
| Reachy-wireless, K11 **in robot** | robot-side — no laptop device |
| Reachy-wireless, K11 **in laptop** | `Microphone (USBAudio1.0)` |
| **NAO_LLM / NAO_LLM_v2** | **Windows default input — may be either of the above** |

**So the arbitration is required after all.** The hub resolves "default" to a
concrete device name at launch time and blocks a second claim on it, naming
the holder, with an explicit override. See `PLAN.md` §2.5 and §7.2.

### ✅ NAO's own microphones WORK — measured 2026-09-14
`ALAudioRecorder.startMicrophonesRecording("/home/nao/mictest.wav", "wav",
48000, (1,1,1,1))`, 6 s, pulled back over SFTP and measured per channel
(tool: `tools/naoqi/nao_mic_measure.py`):

```
channels=4  rate=48000  duration=5.97s

mic        RMS      peak      dBFS    verdict
left     914.1     10313     -31.1    LIVE - clear signal
right    892.1      7703     -31.3    LIVE - clear signal
front    802.3     14345     -32.2    LIVE - clear signal
rear     870.5     12178     -31.5    LIVE - clear signal
```

Balanced across all four, healthy level, no clipping, no dead channel.

**So the laptop-mic dependency is a software decision in those two projects,
not a hardware limitation.** The better fix is to patch `NAO_LLM`'s
`audio_capture.py` to capture through `ALAudioRecorder` instead of
`sounddevice`. That removes NAO from laptop audio completely — and it is what
lets NAO run **in a different room from the laptop**, which a system listening
through the PC microphone fundamentally cannot do.

Keep the hub-side arbitration anyway: other users may not have patched their
copy, and `NAO_LLM_v2` still uses laptop audio.

Note `ALAudioDevice.getParameter("inputDeviceName")` and
`getInputVolume()` both raise on this NAOqi build — device introspection is
unavailable, so recording is the only way to verify the mics.

## F. Network — **DONE: NAO is on the hotspot over WiFi** ✅

Completed 2026-09-14. The cable is unplugged and NAO runs wireless.

```
State       = online
Favorite    = True          <- saved permanently
AutoConnect = True          <- rejoins on its own
IPv4        = 172.20.10.14 / 255.255.255.240   gw 172.20.10.1
Interface   = wlan0   28:24:FF:46:1D:28   Strength ~58-71
```

Verified end to end with the cable out: `nao.local` resolves to
`172.20.10.14` via mDNS, `connect_naoqi.py` connects with no IP argument, and
he spoke a test sentence aloud.

### The dual-network problem is gone
All four robots now sit on `172.20.10.x`. **Discovery drops from four
detectors to three:** one mDNS browser covers NAO (`_naoqi._tcp`) *and*
Reachy-wireless (`_reachy-mini._tcp`); Furhat still needs ARP/MAC; Reachy-Lite
still needs USB PnP. And NAO can now live in its own room like the others,
which is the point of the four-room scenario.

### 🔴 The NAOqi API CANNOT provision WiFi — use SSH
This cost real time, so it is worth stating plainly.

`ALConnectionManager` **looks** like it can join a network. It cannot:
```python
con.setServiceInput({"ServiceId": sid, "Passphrase": pw})   # accepted
con.connect(sid)                                            # returns None
# -> state stays "idle", Favorite stays False, Error stays "" -- silent no-op
```
`setServiceConfiguration({"ServiceId": sid, "AutoConnect": True})` likewise
reports success and changes nothing.

**Why:** ConnMan needs a registered **passphrase agent** at connect time.
NAOqi never registers one, and reports no error when the request is dropped.

Note also `setServiceInput` takes **one map**, not two arguments —
`(s[[s]])` is rejected, `(m)` is the only candidate. And this NAOqi build
exposes neither `getMethodList` nor `getMethodHelp`, so the API cannot be
introspected; method existence has to be probed by calling.

**What works — over SSH (`nao` / `nao`):**
```
connmanctl
> agent on
> connect wifi_<mac>_<ssid-hex>_managed_psk
Passphrase? ********
> quit
```
Connects immediately and sets `Favorite=True, AutoConnect=True` itself.
Driving it from the laptop needs an interactive PTY (`paramiko.invoke_shell`),
because `connmanctl connect` prompts.

`/var/lib/connman/` holds the saved-network files but is **root-owned** and
`sudo` wants a password, so the provisioning-file route was not available as
the `nao` user.

### Stale saved networks
`/var/lib/connman/` still holds entries for networks that are not in use,
including `ה-iPhone של Tomer` — the user's **previous** iPhone, renamed two
months ago. That is exactly why AutoConnect never fired before: the saved SSID
no longer existed. Others: `BITTALK`, `HUAWEI-G102XC`, `Infinix NOTE 5`,
`NAO5`, `Nau Free Network`, `Nz-BenGurion`, `SHAKED`, `TP-LINK_FA8A2E`.
Harmless, but noise when debugging a join. Clearing them needs root.

### Falling back to the cable
The wired service stays `Favorite: True, AutoConnect: True`, so plugging the
cable back in makes NAO prefer it again and mDNS follows within seconds. The
cable remains a working rescue path if WiFi ever fails.

## Open items

1. ~~Put NAO on the hotspot~~ **DONE 2026-09-14** — `172.20.10.14`, permanent.
2. Ports 9443 / 9503 unidentified.
3. Disconnect signature not captured.
4. `ALServiceManager.services()` returns nested lists, not strings — my parse
   failed. Re-read if a service list is ever needed on the card.
5. Optional cleanup: remove the stale saved networks (needs root).
