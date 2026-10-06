# Robot Hub — build plan

**Status:** design complete, ready to build. All four robots profiled against
real hardware on 2026-09-14.
**Audience:** the agents who will implement this. Read this file, then the
matching `profiles/<robot>.md` before touching that robot's adapter.

---

# 1. What we are building

One local web app. A single minimal page shows four cards — **Furhat,
Reachy-Mini, Reachy-Mini-Lite, NAOqi**. A card is dim when its robot is
absent and lights up within seconds of that robot appearing on the network
(or USB). Pressing **Connect** attaches to it and the robot **says a sentence
out loud** to confirm. Pressing **Launch** opens that robot's own existing
system in a new tab.

Any number of robots can be connected and running simultaneously, in any
order, without interfering with each other. Absent robots are never blocking.

Ships as a git repo other lab members clone and run locally. Later, optionally
deployable to AWS — designed for, not built now.

## Non-goals for v1
- Replacing or rewriting any robot's existing system. The hub **supervises and
  links**; it never reimplements.
- Remote/cloud operation (phase 7, design-compatible only).
- Pepper (nothing is set up on any lab machine).

---

# 2. Hard constraints — measured, not assumed

Every line here was observed on real hardware. These are the facts the
architecture exists to satisfy. Do not "simplify" past them.

## 2.1 Each robot needs a *different* discovery mechanism

| Robot | Mechanism | Detail |
|---|---|---|
| Reachy-Mini (wireless) | **mDNS** | `_reachy-mini._tcp`, TXT has `model=Reachy Mini Wireless`, `unit_id` |
| NAOqi | **mDNS** | `_naoqi._tcp`, TXT has `RobotType=Nao` |
| Furhat | **ARP + HTTP fingerprint** | advertises **no mDNS at all**; identify by `<title>Furhat Studio</title>` on port 80 |
| Reachy-Mini-Lite | **USB PnP** | no network stack whatsoever; `USB\VID_38FB&PID_1001` |

One mDNS browser covers two robots. Furhat and the Lite each need their own
detector. **Three detectors, four robots.**

## 2.2 IP is never an identity

Within one hour on 2026-09-14, `172.20.10.10` was held by the wireless Reachy
and then by Furhat. Different MACs, same address, same session.

> **Key every card on a stable id — `unit_id`, MAC, or USB serial. Never IP.**
> An IP-keyed hub would have shown Furhat's data under Reachy's card.

**The mDNS instance name is not stable either.** Both Reachys are named
`reachy_mini`, so when both are on, Bonjour auto-renames the second to arrive
to `reachy_mini-2`. **That suffix depends on boot order.** Observed live with
both robots powered:
```
reachy_mini-2 -> 172.20.10.10   model=Reachy Mini Wireless  unit=58b3b6a4bf81179a
reachy_mini   -> 100.98.102.61  model=Reachy Mini Lite      unit=None
```
Key on TXT `model` + `unit_id`; the Lite has no `unit_id`, so it falls back to
USB serial. Never the service instance name.

## 2.3 Status endpoints lie

| Robot | The lie | The truth |
|---|---|---|
| Reachy (both) | `POST /health-check` returns `{"status":"ok"}` even when the robot is unplugged and `state` is `error`/`stopped`. `/api/media/status` also stays `available` through a disconnect — though it *does* track `acquire`/`release` correctly, so it is unreliable as a liveness signal, not meaningless. | `state == "running" AND backend_status.ready == true` |
| Reachy (both) | ~7 s silent window after a fault where `state` still reads `running` | `control_loop_stats.nb_error` climbing — moves ~1 s after the fault, ~7 s before `state` |
| NAOqi | TCP connect to **9559 succeeds while the broker refuses**. Failed on first attempt twice on 2026-09-14, worked on retry, ping steady at 1 ms throughout. | a **successful `ALProxy` call**, with automatic retry |
| Furhat | no JSON status endpoint at all on port 80 | Studio event bus `RequestSystemStatus`, or Realtime API `request.system.status` |

## 2.4 Latency is jittery and must never block the UI

Wireless Reachy on the hotspot: **8 ms – 457 ms**, 0 % loss. NAO on WiFi:
9–347 ms. Furhat: steady ~20 ms.

> Every robot call is async with a timeout. A slow robot must never freeze a
> card, delay another robot, or block the event loop. This is the single
> biggest threat to the "0 lag" requirement and it cannot be fixed at source.

## 2.5 Audio devices are contended — the arbitration is required

Corrected 2026-09-14 after reading NAO's actual systems.

| Robot / system | Capture device |
|---|---|
| Reachy-Lite | own USB audio (`Reachy Mini Audio`) — no laptop device |
| Furhat | own ReSpeaker 4 Mic Array — no laptop device |
| Reachy-wireless, K11-in-robot | robot-side — no laptop device |
| **Reachy-wireless, K11-in-laptop** | **`Microphone (USBAudio1.0)`** (laptop) |
| **NAO_LLM** | **Windows default input device** — `sd.InputStream(...)` in `antagonist_robot/pipeline/audio_capture.py` passes **no `device=`** |
| **NAO_LLM_v2** | same, via `sd.rec()` in `audio/asr_streaming.py` |

The danger is not merely "both want a mic". It is that **NAO grabs whatever
Windows currently calls default — which may be the K11 itself.** The failure
looks exactly like a broken microphone. `reachy_chat`'s own notes say this
class of failure already cost a demo.

### NAO's onboard mics work — this conflict is self-inflicted and fixable
Measured 2026-09-14 via `ALAudioRecorder.startMicrophonesRecording`,
48 kHz, 4 channels, 6 s (tool: `tools/naoqi/nao_mic_measure.py`):

```
left   -31.1 dBFS      right  -31.3 dBFS
front  -32.2 dBFS      rear   -31.5 dBFS      all LIVE, no clipping
```

All four are healthy and balanced. NAO listening through the laptop is a
**software choice in those two projects, not a hardware limitation.**

**Therefore, two levels of fix — do both:**

1. **Preferred, removes the conflict entirely:** patch `NAO_LLM`'s
   `audio_capture.py` to capture from NAO's own array via `ALAudioRecorder`
   (or accept a `device=` argument). NAO then touches no laptop audio at all,
   the contention disappears rather than being managed — **and NAO can finally
   be in a different room from the laptop, which is the whole point of the
   four-room scenario.** A system listening through the laptop mic cannot be.
   Track as a separate task against `NAO_LLM`, not a hub change.
2. **Still required regardless:** the hub must arbitrate, because the hub
   cannot assume every user has patched their copy, and `NAO_LLM_v2` and any
   future system may still use laptop audio. **Block the second claim, with an
   explicit override button naming the holder.** (See §7.2.)

## 2.6 The Reachy desktop app is exclusive — and the rule inverts

| | |
|---|---|
| Reachy-Lite | **requires** `Reachy Mini Control.exe` running — it *is* the daemon host. Unplug the Lite and the app exits ~34 s later, freeing port 8000. |
| Reachy-wireless + `reachy_chat` | **requires it closed** — `reachy_chat/README.md`: *"it grabs the robot's audio and this app will not get it."* |

The app also proxies whichever robot it is attached to onto laptop
`127.0.0.1:8000`, and reserves **7447, 8000, 8042, 8443**.

> ### ✅ RESOLVED 2026-09-14 — the two Reachys ARE independent
>
> Tested with the Lite on USB (desktop app attached) and the wireless robot on
> the hotspot, simultaneously:
>
> ```
> POST /api/media/acquire on the WIRELESS robot, while the app held the Lite
>   -> {"status":"ok"}  HTTP 200
> laptop :8000 throughout -> never switched away from "lite"
> Lite afterwards -> completely unchanged
> ```
>
> Then the full real-world test: `laptop_chat.py --robot-host 172.20.10.10
> --port 9101` ran the wireless robot through `reachy_chat` (claiming the K11,
> SSH-ing to the robot, starting the robot-side player) **while the desktop app
> kept the Lite**. Both stayed healthy:
> ```
> wireless: state=running ready=True nb_error=0     dashboard :9101 -> 200
> lite    : state=running ready=True nb_error=0  cam=lite
> ports   : 8000 + 8443 (desktop app)   9101 (reachy_chat)
> ```
> Stopping `reachy_chat` released :9101 and left both robots healthy.
>
> **Consequences:**
> - `Claim(exclusive, "reachy_desktop_app")` is **scoped per-robot, not
>   global**. Both Reachys can run together. No permanent exception to the
>   "all four at once" goal.
> - The README's *"close the desktop app"* warning applies only when the app
>   is attached to **the same robot** you are driving. It holds one robot at a
>   time.
> - **Port reassignment works** — `laptop_chat.py --port` was honoured, so the
>   hub can allocate freely instead of assuming 8765.

## 2.7 NAOqi is Python 2.7 only

```sh
SDK=".../sdk/pynaoqi-python2.7-2.8.6.23-win64-vs2015-20191127_152649/<same again>"
PYTHONPATH="$SDK/lib" PATH="$SDK/bin:$PATH" /c/Python27/python.exe script.py
```

The hub **cannot import `naoqi`**. Every NAO call is a **subprocess** to
Python 2.7. This is the largest structural difference between robots and is
the main reason the supervisor model was chosen.

## 2.8 The laptop's own network is a failure mode

On 2026-09-14 the laptop silently roamed from the hotspot to campus WiFi.
Every robot became unreachable, the desktop app's log simply froze — no error,
no dialog. It read as "the robot hung". Cost about an hour.

> The hub **must watch its own interfaces** and, when it is not on the robots'
> subnet, say so across every card instead of showing robots as mysteriously
> dead. First-class feature, not an edge case.

## 2.9 Assorted measured facts the adapters need

- A Reachy daemon restart = **~20 s of ConnectionError**, then clean. Normal.
  Ride it out; do not declare offline or start a reconnect storm.
- Reachy app lock held looks like
  `{"state":"local_app","holder_name":"reachy_mini_conversation_app"}`;
  free is `{"state":"free","holder_name":null}`. It **releases cleanly on app
  exit** — no stale-lock cleanup needed.
- `/api/apps/list-available/local` returns `[]` on both Reachys even while an
  app runs. Use `/api/apps/current-app-status`.
- Furhat TTS caches: first utterance of a string costs ~1.1 s, repeats cost
  0 ms, and **the cache is shared across both control paths**.
- Furhat's Realtime API is silent without `monitor: true` on many requests.
  No reply ≠ unsupported.
- Only **NAO** reports battery (`ALBattery.getBatteryCharge()`). Reachy
  reports none at all (all 98 endpoints swept). Furhat is mains-powered.
- Check Point VPN adapter hooks outbound port-80 connects and makes
  `connect()` succeed for hosts that do not exist. **Port 80 is not a valid
  liveness probe on this laptop.** ICMP-gate and require a real HTTP reply.

---

# 3. Stack

**Backend: Python 3.11+, FastAPI + uvicorn.**
Non-negotiable reasons: every robot SDK is Python; NAOqi forces a Python 2.7
subprocess anyway; `zeroconf`, `requests`, `websockets`, `sounddevice`,
`pyserial` are all mature here. A Node hub would shell out to Python for
three of four robots.

**Frontend: plain HTML + CSS + vanilla JS. No build step, no npm, no
framework.**
The page is four cards and a status bar. A build pipeline would add install
friction for lab users and buy nothing. Served as static files by FastAPI.

**Browser transport:** one WebSocket for live state (push, never poll) plus
REST for actions. The UI never polls robots; the hub does, and broadcasts.

**Concurrency:** asyncio throughout. Blocking SDK work goes to
`run_in_executor` or a subprocess. **Nothing blocking on the event loop.**

---

# 4. Repo layout

Hub-only with adapters (decided). Robot systems stay in their own folders and
are referenced by path from config.

```
robot-hub/
├── README.md                  # what it is, quickstart
├── PLAN.md                    # this file
├── requirements.txt
├── config.example.toml
├── .env.example               # secrets, never committed
├── run.ps1 / run.sh           # one-command start
├── hub/
│   ├── main.py                # FastAPI app, static mount, /ws
│   ├── config.py              # pydantic-settings; config.toml + .env
│   ├── events.py              # internal pub/sub bus
│   ├── registry.py            # RobotState store, keyed by stable id
│   ├── doctor.py              # `python -m hub.doctor` preflight for new users
│   ├── discovery/
│   │   ├── manager.py         # runs detectors, emits presence events
│   │   ├── mdns.py            # _reachy-mini._tcp, _naoqi._tcp
│   │   ├── netscan.py         # ICMP-gated sweep + HTTP fingerprint (Furhat)
│   │   ├── usbwatch.py        # USB PnP (Reachy Lite)
│   │   └── selfnet.py         # the laptop's own interfaces (§2.8)
│   ├── adapters/
│   │   ├── base.py            # RobotAdapter ABC + Health/Claim types
│   │   ├── reachy_common.py   # shared Pollen daemon client
│   │   ├── reachy_lite.py
│   │   ├── reachy_wireless.py
│   │   ├── furhat.py
│   │   └── naoqi.py
│   ├── resources.py           # audio-device + exclusive-resource arbitration
│   ├── ports.py               # port allocator
│   ├── supervisor.py          # child processes: start, stop, verify-zero
│   └── announce.py            # per-robot connection announcement
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── assets/announcements/      # pre-rendered WAVs for Reachy (see §8)
├── docs/
│   ├── SETUP.md               # per-robot install steps for a new user
│   ├── ADAPTERS.md            # how to add a fifth robot
│   └── profiles/              # the measured profiles (already written)
└── tools/                     # existing probes: profile_robot.py, naoqi/
```

---

# 5. Core abstractions

## 5.1 `RobotAdapter` (hub/adapters/base.py)

Every robot implements exactly this. Nothing robot-specific leaks into the
hub core.

```python
class Health(TypedDict):
    online: bool          # green
    degraded: bool        # amber - leading indicator tripped
    detail: str           # human sentence for the card
    battery: int | None   # percent, None if the robot cannot report it

class Claim(TypedDict):
    kind: str             # "audio_in" | "audio_out" | "port" | "exclusive"
    value: str            # device name, port number, or resource name
    mode: str             # "require" | "require_absent"

class RobotAdapter(ABC):
    type_id: str                 # "reachy_lite" | "reachy_wireless" | "furhat" | "naoqi"
    display_name: str

    # identity ---------------------------------------------------------
    @abstractmethod
    def stable_key(self, found: Found) -> str: ...
        # unit_id / MAC / USB serial. NEVER an IP.

    # lifecycle --------------------------------------------------------
    @abstractmethod
    async def probe(self, found: Found) -> Health: ...
    @abstractmethod
    async def connect(self) -> None: ...
    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def announce(self, text: str) -> None: ...
        # speak out loud. MUST actually produce sound.

    # its own system ---------------------------------------------------
    @abstractmethod
    def claims(self) -> list[Claim]: ...
    @abstractmethod
    async def ensure_zero_instances(self) -> list[str]: ...
        # returns human-readable notes; MUST verify, not just signal
    @abstractmethod
    async def launch(self) -> str: ...
        # returns the URL to open in a new tab
```

`ensure_zero_instances` is deliberately part of the contract.
`reachy_chat/tools/start_reachy.py::stop_everything` already implements this
pattern and explains why in its docstring: two instances fighting over audio
produce a symptom identical to a broken mic. **Generalise it; do not drop it.**

## 5.2 Card state machine

```
        ┌──────────┐   detector fires    ┌──────────┐
        │  ABSENT  │ ──────────────────► │ DETECTED │   card lights up
        └──────────┘                     └────┬─────┘
             ▲                                │ Connect (or auto-connect)
             │ detector loses it              ▼
             │                          ┌────────────┐
             │                          │ CONNECTING │
             │                          └────┬───────┘
             │                               │ probe ok + announcement spoken
             │                               ▼
             │                          ┌───────────┐   Launch   ┌─────────┐
             └───────────────────────── │ CONNECTED │ ─────────► │ RUNNING │
                                        └────┬──────┘            └────┬────┘
                                             │ leading indicator      │
                                             ▼                        │
                                        ┌──────────┐                  │
                                        │ DEGRADED │ ◄────────────────┘
                                        └────┬─────┘
                                             │ confirmed loss
                                             ▼
                                        ┌───────┐
                                        │ ERROR │  → auto-reconnect w/ backoff
                                        └───────┘
```

`DEGRADED` exists specifically because of §2.3 — Reachy's `nb_error` moves
7 s before `state` does. Amber is honest; green would be a lie.

Auto-reconnect is exponential backoff starting at 2 s, capped at 30 s, and
**every transition is logged with a human sentence** (the user asked for a
visible log, not just a dot).

---

# 6. Discovery

`DiscoveryManager` runs all detectors concurrently and emits
`found(type_id, stable_key, address, meta)` / `lost(stable_key)`.

**Detectors are type-based, never pre-configured with this lab's MACs.** A
different lab with a different Furhat must work on clone. Identity is
*learned* at discovery time and used as the card key thereafter.

| Detector | How | Cadence |
|---|---|---|
| `mdns.py` | zeroconf `ServiceBrowser` on `_reachy-mini._tcp` and `_naoqi._tcp`. Distinguish Reachy wireless vs Lite by TXT `model`. | continuous, push |
| `netscan.py` | ICMP-gate the local /24-or-smaller, then HTTP GET `/` and match `<title>Furhat Studio</title>`. **Refuse subnets larger than /24** without explicit config. | every 5 s, cheap on a /28 |
| `usbwatch.py` | Windows: WMI `Win32_PnPEntity` watch for `VID_38FB`. Linux: `pyudev`. Key on USB serial. | event-driven, 2 s poll fallback |
| `selfnet.py` | laptop's own IPv4 interfaces; emits `network_changed` | every 3 s |

**mDNS caveats already measured:** Windows' own resolver failed on
`nao.local` while zeroconf succeeded — **do mDNS in-process, never shell out
to the OS resolver.** The Lite advertises a *Tailscale* address that nothing
can reach: for the Lite, **ignore the advertised address and use
`127.0.0.1:8000`**. mDNS otherwise follows the active interface correctly and
for free (verified when NAO's cable was unplugged).

---

# 7. Arbitration — how robots avoid each other

## 7.1 Ports

Allocator hands out ports from **9100–9199** for anything the hub starts.
Hard-avoid list, measured on this laptop:

```
5040, 5357, 7680, 7778      Windows services
7447, 8000, 8042, 8443      Reachy Mini Control desktop app
8765                        reachy_chat dashboard  (configurable: --port)
8770                        reachy_chat launcher
8080                        Furhat SDK (virtual Furhat), when running
```

Bind-test before assigning. `reachy_chat` accepts `--port`, so the hub passes
an allocated one rather than assuming 8765.

## 7.2 Audio devices

`resources.py` keeps a registry of claimed capture/playback devices, resolved
to **concrete device names at launch time** — not to the string `"default"`.

Resolution rule for NAO: query `sounddevice.query_devices(kind='input')` for
the current Windows default and claim *that concrete name*. This is what makes
the K11 collision visible instead of silent.

On conflict: **refuse the launch**, and show
> *"Cannot start NAO_LLM: `Microphone (USBAudio1.0)` is in use by
> Reachy-Mini (K11 laptop mode). Stop that first, or override."*

An **Override** button proceeds anyway. Logged loudly.

## 7.3 Exclusive resources

`Claim(kind="exclusive", value="reachy_desktop_app", mode="require" | "require_absent")`.

- Reachy-Lite → `require`
- Reachy-wireless (when launching `reachy_chat`) → `require_absent`

Conflicting modes on the same resource → blocked with an explanatory message.
**Gate this on the §11 must-verify test** — if the desktop app turns out not
to interfere when attached to the Lite over USB, scope the claim per-robot
instead and both Reachys can coexist.

## 7.4 Process isolation

Everything the hub launches is a **child process with its own port, own cwd,
own env**. No shared interpreter state. NAO's Python 2.7 subprocesses are
naturally isolated. A crash in one robot's system cannot touch another.

---

# 8. The connection announcement

Required: on successful connect, the robot **says a sentence out loud** —
voice proof that the link is real, not just a green dot.

Default text, per robot, configurable in `config.toml`:
> *"I am `<name>`, I am connected and ready to run."*

| Robot | How | Notes |
|---|---|---|
| **Furhat** | `ws://<ip>/api` → SHA-256 login → `ActionSpeech` | verified working. Also pre-warm the phrase (§2.9) |
| **NAOqi** | Py2.7 subprocess → `ALTextToSpeech.say()` | verified working |
| **Reachy (both)** | `POST /api/media/acquire` → `POST /api/media/play_sound` with a pre-rendered WAV → `release` | the Pollen daemon exposes **no TTS endpoint**; a bundled WAV is the dependency-free path |

Reachy WAVs live in `assets/announcements/` and are uploaded once via
`POST /api/media/sounds/upload` (idempotent — check `GET /api/media/sounds`
first). A small script regenerates them if the text is changed in config.

**Announcement failure must not fail the connection** — the card connects,
but shows a clear "connected, but could not speak" warning. That warning is
itself diagnostic: on Furhat it usually means the Azure/engine trap from
`profiles/furhat.md`.

---

# 9. UI contract

## 9.1 REST

```
GET    /api/robots                 -> full state of all cards
POST   /api/robots/{key}/connect
POST   /api/robots/{key}/disconnect
POST   /api/robots/{key}/launch    -> {"url": "..."}
POST   /api/robots/{key}/override  -> proceed past a resource conflict
GET    /api/settings   PUT /api/settings     -> {auto_connect: bool, ...}
GET    /api/log?limit=200          -> event log
GET    /api/doctor                 -> environment check results
```

## 9.2 WebSocket `/ws`

Server pushes on every change. Never polled by the browser.

```json
{"type":"robot",  "key":"58b3b6a4bf81179a", "state":"CONNECTED",
 "type_id":"reachy_wireless", "name":"Reachy-Mini",
 "address":"172.20.10.14", "battery":null,
 "detail":"ready, control loop 49.5 Hz", "mic":"K11 (laptop)",
 "system_url":"http://127.0.0.1:9101/"}
{"type":"network","on_robot_subnet":true,"interfaces":["172.20.10.4/28"]}
{"type":"log","level":"warn","text":"NAO: broker refused, retrying (1/5)"}
{"type":"conflict","key":"...","message":"...","resource":"audio_in:..."}
```

## 9.3 The page

Four cards. Each shows: name, dim/lit state, a small **battery %** where the
robot reports one (**NAO only** — do not render an empty battery for the
others), the three buttons (green **Connect** top-right, red **Disconnect**
top-left enabled only while connected, larger **Launch** bottom-centre), and
room in the middle for the robot photo (cosmetic, later).

Plus: an **auto-connect toggle** (user-controlled, default off), a network
banner (§2.8), and a scrolling event log.

Launch opens a **new tab**, so several robot systems can live on several
screens at once. The hub page itself stays responsive regardless of what any
robot is doing.

---

# 10. Build phases

Each phase is independently testable. Do not start a phase before its
predecessor's acceptance criteria pass.

### Phase 0 — skeleton
FastAPI app, static page, WebSocket echo, config loader, event bus, logging.
**Accept:** page loads, WS connects, four hardcoded dim cards render, `/ws`
pushes a heartbeat.

### Phase 1 — discovery only
All four detectors. No connecting yet. Cards light on presence, dim on loss.
Network banner works.
**Accept:** power each robot on and off; card lights within 5 s and dims
within 15 s. Unplug the hotspot → banner appears. Verified with **no robot
pre-configured** — identity learned at runtime.

### Phase 2 — health and battery
Per-robot probe loops with the §2.3 rules. `DEGRADED` amber state.
**Accept:** pull Reachy-Lite's USB and watch the card go amber on `nb_error`
*before* it goes red — reproducing the measured 7 s window. NAO shows battery
%. NAO's first-call retry works.

### Phase 3 — connect / disconnect / announce
Session lifecycle plus §8 announcements.
**Accept:** every robot speaks its sentence on connect. Announcement failure
degrades gracefully. Disconnect is clean and idempotent.

### Phase 4 — arbitration
`resources.py`, `ports.py`, conflict UI, override.
**Accept:** start Reachy-wireless in K11-laptop mode, then try to launch
NAO_LLM — blocked, with the holder named. Override works. Port allocation
avoids every port in §7.1.

### Phase 5 — launch
`supervisor.py` + per-robot `launch()` and `ensure_zero_instances()`.
- Reachy-wireless → `reachy_chat` via `start_reachy.py`, allocated port
- Reachy-Lite → Reachy Mini Control (hub may need to **start the app itself**;
  it exits ~34 s after unplug)
- Furhat → `http://<ip>/` with automated `admin` login
- NAOqi → **NAO_LLM** (decided), its React web UI

**Accept:** all four launch into their own tabs. **Two robots run
simultaneously with no interference** — the headline requirement.

### Phase 6 — resilience and polish
Auto-reconnect with backoff and visible log; auto-connect toggle; the ~20 s
Reachy-restart tolerance; `python -m hub.doctor`; `docs/SETUP.md`.
**Accept:** kill a robot's WiFi mid-session — card goes amber then red, then
reconnects and resumes on its own, with a readable explanation in the log.

### Phase 7 — later, not now
AWS/remote. Keep the transport abstracted so a future `agent` process on the
lab machine can relay discovery and control to a hosted UI. **Discovery is
inherently local** (mDNS is link-local, USB is physical) — remote operation
means a local agent, never a cloud-only hub. Do not design this away now;
just do not build it.

---

# 11. Must-verify before/while building

1. ~~Reachy desktop app scope~~ **RESOLVED 2026-09-14 — they are independent.
   See §2.6.** Both Reachys ran simultaneously, one via the desktop app, one
   via `reachy_chat` on a reassigned port, with no interference.
2. **Furhat Realtime API key** is per-install; the lab key was regenerated
   after testing. Treat as user-supplied config, never committed.
3. **Reachy announcement path** — `play_sound` while no app holds the lock:
   confirm `media/acquire` is enough.
4. **NAO_LLM launch contract** — exact command, port, and whether its web UI
   port is configurable. Its `.exe` console shims are broken after the folder
   move; use `venv\Scripts\python.exe -m ...` (documented in `naoqi/README.md`).
5. **Disconnect signatures** never captured for Furhat, NAO, or
   Reachy-wireless. Capture during Phase 2 and fold into the profiles.

---

# 12. Universality — other lab members

The repo must be useful to someone with one robot, or none.

- **No hardcoded lab values.** No MACs, IPs, keys, or paths in code. Identity
  is discovered; everything else is `config.toml` + `.env`.
- **Absent robots are never blocking.** A missing robot is a dim card. A
  missing *SDK* disables only that card, with a message saying what to install.
- **`python -m hub.doctor`** checks the environment and prints exact remedies:
  Python 2.7 + pynaoqi for NAO, Reachy Mini Control for the Lite, the
  `reachy_chat` path, the Furhat key. Also surfaced at `/api/doctor` in the UI.
- **`docs/SETUP.md`** carries the per-robot install steps, including the
  non-obvious ones already learned: Furhat needs the hotspot up *before* it
  boots and needs 2.4 GHz (*Maximize Compatibility*); NAO's WiFi must be
  provisioned over SSH with `connmanctl agent on` because **the NAOqi API
  cannot do it**.
- **Secrets** live in `.env` (gitignored). `.env.example` documents each key.
  Never log a key. The Furhat key, Gemini key, and NAO SSH password are all
  user-supplied.

## Minimum requirements

**Hub itself:** Python **3.11+**, ~200 MB, any OS for the core.
Windows-only pieces: USB detection (WMI) and the Reachy Mini Control app.
Provide a `pyudev` path for Linux and degrade the Lite card with a clear
message elsewhere.

```
fastapi>=0.115      uvicorn[standard]>=0.32   pydantic-settings>=2
zeroconf>=0.149     httpx>=0.27               websockets>=13
sounddevice>=0.5    psutil>=6                 paramiko>=3
tomli-w             (Windows) wmi / pywin32   (Linux) pyudev
```

**Per robot, only if you own it:**

| Robot | Needs |
|---|---|
| Reachy-Mini-Lite | Reachy Mini Control desktop app (daemon ≥ **1.10.0**) |
| Reachy-Mini | `reachy_chat` checkout + its venv; robot daemon ≥ **1.10.0** |
| Furhat | nothing local — it is entirely robot-side. Optional Realtime API key |
| NAOqi | **Python 2.7** + pynaoqi SDK 2.8.6; `NAO_LLM` + its venv |

> **Keep both Reachy daemons on 1.10.0.** On 1.9.0 `ready` is permanently
> `false` and `last_alive` permanently `null` while the robot works fine —
> which would force two different health rules. The upgrade (`POST
> /update/start`, ~5 min) collapsed them into one. A desktop-app update that
> silently downgrades a daemon reintroduces the split, so **the hub records
> and displays the daemon version on every connect.**

---

# 13. Principles for the implementing agents

1. **Never block the event loop.** Every robot call: async, timeout, executor
   or subprocess. §2.4 is not negotiable.
2. **Trust only the signals in §2.3.** If an endpoint looks like a health
   check, assume it lies until measured.
3. **The hub supervises; it never reimplements.** Launch existing systems
   unchanged.
4. **Identity is never an IP.** §2.2.
5. **Every failure gets a human sentence**, not a colour change. The user
   explicitly asked for a log that says what happened.
6. **A robot you do not own must cost nothing.** No import errors, no
   stack traces, no blocked startup.
7. **When something is uncertain, measure it on hardware.** Every constraint
   in §2 came from doing that, and several overturned a confident guess —
   including one in this document's own history (§2.5).
