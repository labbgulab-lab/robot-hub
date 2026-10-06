# reachy-mini-wireless

Captured 2026-09-14, laptop on iPhone hotspot (`172.20.10.4/28`), robot on WiFi.
Raw machine capture in `reachy-mini-wireless.json`.

## A. Identity — network device, **discoverable**

| | |
|---|---|
| IP | `172.20.10.10` (DHCP lease from the iPhone) |
| MAC | `88:A2:9E:8C:E0:13` |
| Hostname | `reachy-mini.local` (via mDNS; reverse DNS is `None`) |
| **`hardware_id` / `unit_id`** | **`58b3b6a4bf81179a`** — stable, use as the card key |
| OS | Debian (SSH banner `SSH-2.0-OpenSSH_10.0p2 Debian-7`) |
| Daemon version | **1.10.0** — upgraded from 1.9.0 on 2026-09-14; now matches the Lite |

### mDNS — clean and usable, unlike the Lite
```
_reachy-mini._tcp.local  ->  reachy-mini.local:8000   addresses: [172.20.10.10]
  model=Reachy Mini Wireless   manufacturer=Pollen Robotics
  version=1.10.0  unit_id=58b3b6a4bf81179a
  api=rest+ws   ws_path=/ws/sdk   caps=camera,mic,speaker,motion,apps
  address=172.20.10.10          <-- correct, unlike the Lite
_workstation._tcp.local  ->  reachy-mini [88:a2:9e:8c:e0:13]
```

**This is the discovery mechanism for the hub.** Browse `_reachy-mini._tcp`
and read the TXT record:
- `model` separates **Reachy Mini Wireless** from **Reachy Mini Lite**
- `unit_id` is present only on wireless (the Lite reports `hardware_id: null`)

No scanning needed. Fall back to a /28 sweep of port 8000 only if mDNS is
blocked (Tailscale is running on this laptop — watch for interference).

## B. Reachability

Open ports: **22 (SSH), 8000 (daemon), 8443 (TLS, unidentified)**.
Ports 1–10000 swept; nothing else.

`8443` refuses both plain HTTP (`RemoteDisconnected`) and normal TLS
(`SSLError`). Not identified. Not needed — ignore it.

### ⚠️ Latency is jittery, not slow
```
sample 1 (10 pings): 29, 38, 457, 214, 63, 64, 282, 114, 47, 28 ms   avg 134
sample 2 (20 pings): min 8 / avg 29 / max 101 ms
loss: 0% in both
```
8 ms to 457 ms on a 5-device hotspot — WiFi power-save on the robot.
**Design consequence:** the hub must never block on a robot call. Every probe
gets a timeout, runs off the UI thread, and a slow reply must never freeze a
card or delay the other robots. This is the single biggest threat to the
"0 lag" requirement, and it is not fixable on our side.

## C. Surface - 98 endpoints, a *superset* of the Lite

`http://172.20.10.10:8000`, uvicorn/FastAPI, OpenAPI at `/docs`.
`GET /` is the deprecated dashboard. `/settings` and `/logs` are SPA routes
that return that same HTML, **not** APIs - do not treat them as endpoints.

Families: `api` 76, `wifi` 10, `update` 6, `cache` 2, plus `/`, `/health-check`,
`/logs`, `/settings`. On 1.10.0 it is a strict superset of the Lite - the
`/api/daemon/robot-name` gap closed with the upgrade. Extra families the Lite
does not have:

| Family | Why it matters |
|---|---|
| `/wifi/*` | `status`, `scan_and_list`, `connect`, `forget`, `setup_hotspot`, `prov_key` |
| `/update/*` | `available`, `start`, `start-from-ref`, `validate-ref` - daemon self-update |
| `/cache/*` | `clear-hf`, `reset-apps` |
| `/logs`, `/settings` | SPA routes only |

### Live state after the 1.10.0 upgrade
```
version=1.10.0   state=running   hardware_id=58b3b6a4bf81179a
backend_status.ready=TRUE        last_alive=1789365728.13
motor_control_mode=disabled      nb_error=0   loop ~49.5 Hz
/api/daemon/robot-name -> {"name":"reachy_mini"}   (was 404 on 1.9.0)
app lock: {"state":"free","holder_name":null}
update/available: is_available=false, current=1.10.0
```

### The `ready:false` lie is GONE - one health rule now covers both robots
On 1.9.0, `ready` was permanently `false` and `last_alive` permanently `null`
while the robot worked fine. After upgrading to 1.10.0 both report truthfully
(`ready:true`, `last_alive` populated). The per-model health split is no
longer needed:

```
online  =  state == "running"  AND  backend_status.ready == true
amber   =  control_loop_stats.nb_error climbing   (leading indicator)
NEVER   =  /health-check        (returns ok even when the robot is gone)
```

**Keep both robots on 1.10.0.** A desktop-app update that silently downgrades
a daemon would reintroduce the split, so the hub should record and display the
daemon version on every connect.

### `/wifi/status` — useful, wireless only
```json
{"mode":"wlan","known_networks":["Tomer's iPhone","May&Tomer"],
 "connected_network":"Tomer's iPhone"}
```
Good source for the card's network line and for diagnosing a drop.

### No battery endpoint
Swept all 98 paths for `batt|power|charge|temp` — **nothing**. Confirms the
robot cannot report charge level at all. Card shows no battery for this robot;
charge it fully before a demo.

## D. Ownership on the laptop

### 🔴 The port-8000 collision — confirmed, and avoidable
`reachy-mini-control.exe` (the desktop app) **proxies whichever robot it is
attached to onto laptop `127.0.0.1:8000`**. Verified: with the Lite unplugged
and this robot connected, `127.0.0.1:8000` returned *this* robot's payload
(`wlan_ip 172.20.10.10`, `hardware_id 58b3b6a4bf81179a`, `version 1.9.0`).

That is the same single address the Lite's own daemon binds. So:

> **The two Reachys can never both be driven through the desktop app.**

**Avoidance:** the wireless robot serves its own daemon on its own IP, so the
hub talks to `172.20.10.10:8000` **directly and never involves the desktop
app**. Lite → `127.0.0.1:8000`; wireless → robot IP. No overlap.

### Laptop ports the desktop app reserves (all `127.0.0.1`)
**7447, 8000, 8042, 8443** — one process, PID observed 13424.
7447 and 8042 answer `503 "No content yet - service starting up"`.
**The hub must avoid all four.**

### The wireless robot's own system (`reachy_chat`)
| | |
|---|---|
| Launcher | `reachy-mini\start.ps1` → `reachy_chat\tools\start_reachy.py` |
| Launcher page port | **8770** (`LAUNCHER_PORT`, `127.0.0.1` only) |
| Dashboard / chat UI | **8765** (`DASHBOARD_PORT` / `laptop_chat.py DEFAULT_PORT`) |
| Reassignable? | **Yes** — `laptop_chat.py --port N`. Good: the hub can allocate. |
| Direct run | `laptop_chat.py --robot-host 172.20.10.10` |
| Reusable helpers | `tools/find_robot.py`, `probe_robot.py`, `preflight.py`, `mic_check.py` |

`find_robot.py` already scans the laptop's own /24 for port 8000 and confirms
via `/api/daemon/status` — same approach the hub needs, but mDNS is better.

## E. Audio — K11 receiver, **no conflict after all**

Onboard mic is broken (to be fixed later), so it uses the K11 radio mic.
With the receiver **in the laptop**, it enumerates as its own USB device:

```
MEDIA  "USBAudio1.0"   ->  capture endpoint  "Microphone (USBAudio1.0)"
```

### ✅ Correction to an earlier assumption
The K11 is a **separate USB capture device**, *not* the built-in
`Microphone Array (Intel Smart Sound)`. So "the laptop has one mic" was the
wrong frame. If NAOqi needs the **built-in** array, the two do **not**
contend — they are different devices.

The lock the hub needs is therefore **per-device, not "the laptop mic"**:
one holder per capture endpoint. Only two robots wanting the *same* endpoint
collide. Still to confirm which device NAOqi actually wants.

Receiver placement is a physical trade-off, not a software one: the receiver
and the charger share a port on the robot, so receiver-in-robot means the
robot runs on battery — and it cannot report battery level.

## F. Failure behavior

Not yet measured for this robot (the Lite's unplug test has no equivalent —
this one drops off WiFi instead). **Still to do:** power it down or drop WiFi
while watching, to get the disconnect signature the way we did for the Lite.
Expect it to differ, since `ready`/`last_alive` are already unusable here.

## Open / actionable

1. ~~Upgrade 1.9.0 -> 1.10.0~~ **DONE 2026-09-14.** `POST /update/start`,
   job ~5 min (`uv pip install 'reachy-mini[wireless-version]' --upgrade` into
   `/venvs/mini_daemon`), daemon restarted, came back on 1.10.0. Fixed the
   `ready:false` lie and closed the `robot-name` API gap.
   **Still to confirm: whether the desktop app now connects.**
2. App lock never observed **held** — `holder_name` shape still unknown on
   either robot.
3. Disconnect signature not yet captured (see F).
4. Robot port 8443 unidentified. Ignorable.


---

# Session addendum - 2026-09-14 (conversation test)

## App lock, finally observed HELD
```
free : {"state":"free",       "holder_name":null}
held : {"state":"local_app",  "holder_name":"reachy_mini_conversation_app"}
current-app: {"info":{"name":"reachy_mini_conversation_app","source_kind":"installed"},
              "state":"running","error":null}
```
`/api/apps/list-available/local` returns `[]` on BOTH robots even while an app
runs - installed apps are NOT listed there. Use `/api/apps/current-app-status`
for "what is running", never the local list.

## Two conversation pipelines, not one - and they differ in where they listen
| | Pollen built-in app | our `reachy_chat` |
|---|---|---|
| Runs on | the **robot** | the **laptop** |
| Listens through | robot onboard mic (`Reachy Mini Audio`) | K11 in the laptop (`Microphone (USBAudio1.0)`) |
| Backend | HF realtime (`huggingface_realtime.py`) | Gemini |
| Works on this robot? | **NO - onboard mic is broken** | yes (laptop mode) |

### Measured proof
150 s of talking with the Pollen app running and the lock held:
`speech_detected` **false in every one of ~120 samples**, DOA angle pinned at
0.0, head pose static (0.022<->0.023 rad jitter), `moves=[]` throughout.
The app was healthy and running - it simply never heard anything.

**This is why `reachy_chat` exists.** The built-in app cannot be used on the
wireless robot until the onboard mic is repaired, or the K11 receiver is moved
into the robot's body. The Lite does not have this problem because it is USB
and can use laptop audio.

### Hub consequence
The wireless Reachy card must show **which mic path is live**, because
"robot moves but never replies" is indistinguishable from a dozen other
faults. Card should surface: onboard-mic / K11-in-laptop / K11-in-robot, and
refuse to launch the built-in app while the mic path is onboard.

## Daemon restart timing
A daemon restart (e.g. after `/update/start`) = **~20 s of ConnectionError**,
then it returns clean. Normal, not a fault. The card must ride this out rather
than declare offline and start a reconnect storm.

## The laptop-roaming trap (cost us ~1 hour)
The laptop silently left the iPhone hotspot and rejoined BGU campus WiFi
(`132.73.150.163`). Every robot instantly became unreachable and the desktop
app's log simply **froze** - no error, no dialog. It looked exactly like "the
robot hung mid-update".

**The hub MUST watch the laptop's own network** and, when not on the robots'
subnet, say so across every card instead of showing robots as mysteriously
dead. This is a first-class failure mode, not an edge case.
