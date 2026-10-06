# reachy-mini-lite

Captured 2026-09-06, laptop on iPhone hotspot (`172.20.10.4/28`), robot plugged in via USB.

## A. Identity — **USB device, not a network device**

This robot has no computer and no network stack. It cannot be discovered by
any network sweep. Presence = USB enumeration + local daemon responding.

| | |
|---|---|
| Transport | USB (composite: audio + camera + HID + serial) |
| Vendor ID | `38FB` (Pollen Robotics) |
| Audio/control device | `USB\VID_38FB&PID_1001` serial **`100025004261401779`** |
| Camera device | `USB\VID_38FB&PID_1002` serial **`J20251118V0`** |
| Motor/serial board | `USB\VID_1A86&PID_55D3` (WCH CH343) serial `5B90043383` → **COM5** |
| Sub-interfaces | MI_00 audio (MEDIA), MI_03 Audio Control, MI_04 DFU Factory, MI_05 HID |
| Robot name (daemon) | `reachy_mini` |
| Hardware ID | `null` — **not exposed on Lite**, do not key the card on it |

**Card trigger:** presence of USB serial `100025004261401779`.
That serial is per-unit, so it still identifies *this* robot correctly even if
the wireless Reachy Mini is ever attached by USB at the same time.

### mDNS — present but misleading
The daemon advertises `_reachy-mini._tcp.local` as
`reachy_mini._reachy-mini._tcp.local -> <laptop-name>.local:8000` with:

```
version=1.10.0  robot_name=reachy_mini  model=Reachy Mini Lite
manufacturer=Pollen Robotics  api=rest+ws  ws_path=/ws/sdk
caps=camera,mic,speaker,motion,apps  address=100.98.102.61
```

⚠️ `address` is the **Tailscale** IP, not the hotspot IP, and the socket is
bound to `127.0.0.1` only — so that advertised address is unreachable by
anything, including the laptop's own hotspot interface. **Ignore the mDNS
address field. Always talk to `127.0.0.1:8000`.**

## B. Reachability

Not pingable — there is no IP. Health is a local HTTP call:

```
POST http://127.0.0.1:8000/health-check   ->  {"status":"ok"}
GET  http://127.0.0.1:8000/api/daemon/status
```

Loopback, so latency is sub-millisecond. Heartbeat can run at 1 Hz with
no cost.

## C. Surface

Owner of the port: **Reachy Mini Control** desktop app.

```
"C:\Program Files\Reachy Mini Control\reachy-mini-control.exe"            (PID 14940, GUI)
"...\Reachy Mini Control\.venv\Scripts\python.exe"  scripts\avast_ssl_fix.py
      --desktop-app-daemon --no-wake-up-on-start --preload-datasets       (daemon)
```

- **Binds `127.0.0.1:8000` only.** Not `0.0.0.0`. Localhost-only by design.
- FastAPI. Full `/openapi.json`, Swagger at `/docs`.
- `GET /` is the old dashboard, now self-titled **"Deprecated"**.
- WebSocket at `/ws/sdk`.
- ~80 REST endpoints. The ones the hub needs:

| Purpose | Endpoint |
|---|---|
| Health | `POST /health-check` |
| Full status | `GET /api/daemon/status` |
| **App lock** | `GET /api/daemon/robot-app-lock-status` |
| Running app | `GET /api/apps/current-app-status` |
| Start app | `POST /api/apps/start-app/{name}` (evicts) / `.../no-evict` |
| Stop app | `POST /api/apps/stop-current-app` |
| **Claim media** | `POST /api/media/acquire` / `POST /api/media/release` |
| Media state | `GET /api/media/status` |
| Motors | `GET /api/motors/status`, `POST /api/motors/set_mode/{mode}` |
| Pose | `GET /api/state/full`, `POST /api/move/goto`, `POST /api/move/stop` |
| Wake / sleep | `POST /api/move/play/wake_up`, `POST /api/move/play/goto_sleep` |
| Volume | `GET|POST /api/volume/...`, `/api/volume/microphone/...` |

### Live state at capture
```
state=running   version=1.10.0   desktop_app_daemon=true   wireless_version=false
camera_specs_name=lite   simulation=false   no_media=false   media_released=false
backend ready=true   motor_control_mode=disabled   loop ~32.5 Hz, 0 errors
app lock: {"state":"free","holder_name":null}
current app: null    startup app: null
media: {"available":true,"released":false}
HF auth: logged in as Tomer232
relay: "unavailable — Coming soon to Lite version"
```

## D. Ownership on the laptop

| | |
|---|---|
| Port it binds | **8000** (fixed, not configurable via CLI) — hub must avoid |
| Launcher (normal) | Reachy Mini Control GUI → Play on "Conversation" |
| Launcher (backup) | `reachy-mini\reachy-mini-lite\start-conversation.ps1` |
| Underlying exe | `%LOCALAPPDATA%\Reachy Mini Control\apps_venv\Scripts\reachy-mini-conversation-app.exe` |
| UI URL for **Launch** button | `http://127.0.0.1:8000/` (deprecated dashboard) or the desktop app window |
| Single-instance? | **Yes, hard.** One app at a time, enforced by daemon lock |

### The constraint that matters
The daemon is **single-tenant by design**:
- `robot-app-lock-status` has one holder.
- `start-app` **evicts** whatever is running unless `/no-evict` is used.
- README says explicitly: *"Do NOT also press Play on an app inside the
  desktop app while this runs."*

So the hub must never race the desktop app. Before starting anything it must
read the lock and refuse with a clear message if held. This is not a
limitation the hub can engineer around — it belongs to Pollen's daemon.

### Known fragility
Play button crashed out of the box on daemon 1.8.0
(pollen-robotics/reachy-mini-desktop-app#304). Fixed on 2026-08-31 by
upgrading to **1.10.0**. A desktop-app update can replace the daemon and
reintroduce it — `start-conversation.ps1` is the bypass. The hub should
record the daemon version on every connect so a silent downgrade is visible.

## E. Audio — self-contained ✅

Own USB mic + speaker, exposed to Windows as **two** endpoints named
`Echo Cancelling Speakerphone (Reachy Mini Audio)` (render + capture).
Daemon reports both volume devices as that same endpoint.

**Does not touch the laptop mic or Realtek speakers.** No conflict with any
other robot. `POST /api/media/acquire` / `release` is its own internal claim,
scoped to its own hardware.

## F. Failure behavior — **measured**, unplug captured live

No WiFi to drop. The failure mode is USB unplug. Observed cascade, t=0 at unplug:

| t | `state` | `ready` | `nb_error` | `daemon_error` | `/health-check` |
|---|---|---|---|---|---|
| 0 | `running` | `true` | 0 | null | **ok** |
| +7.4s | `running` | `true` | **8** | null | **ok** |
| +8.4s | **`error`** | null | – | `Motor communication error! Check connections and power supply.` | **ok** |
| +19.0s | **`stopped`** | null | – | same | **ok** |
| +33.6s | *daemon process gone* | – | – | – | ConnectionError |

End state confirmed: `reachy-mini-control.exe` **gone**, port **8000 free**,
no `VID_38FB` USB devices, audio endpoints back to laptop-only (Realtek +
Intel mic).

### ⚠️ Three traps for the hub

1. **`/health-check` lies.** It returned `{"status":"ok"}` at *every* stage —
   including `state=error` and `state=stopped`. It is a liveness check of the
   web server, not the robot. **Never use it as the card's online signal.**
2. **`/api/media/status` lies too.** Stayed `{"available":true,"released":false}`
   through the entire cascade. Equally unusable.
3. **There is a ~7-second silent degraded window.** Between unplug and
   `state` changing, the daemon still says `running` + `ready:true` and only
   `nb_error` climbs. A hub polling `state` alone shows green for ~8s after
   the robot is physically gone.

### The only trustworthy online signal
```
state == "running"  AND  backend_status.ready == true
AND  backend_status.control_loop_stats.nb_error is not climbing
```
Watch `nb_error` as a **leading indicator** — it moves ~1s after the fault,
7s before `state` does. That is what makes the card go amber early.

### Recovery is not automatic
The desktop app **exits entirely** ~34s after unplug. So replugging does not
restore service — `Reachy Mini Control.exe` must be relaunched. If the hub is
to deliver auto-reconnect for this robot, it must be willing to **start the
desktop app itself**, not merely wait for it. The running conversation app
does not survive either.

- **No battery** — USB powered, so no battery state to report at all.

### Side effect worth confirming
Motor mode was `disabled` before this session and `enabled` after opening
`/ws/sdk`. Single observation, not proven, but the timing is clean:
**opening the SDK WebSocket is not a passive read and may energize motors.**
Another reason cards should poll HTTP rather than hold that socket open.

## Implications for the hub

1. Discovery for this card is **USB WMI/PnP watch**, not network. It needs a
   completely different detector than Furhat/NAOqi.
2. **Port 8000 is taken and immovable.** Hub and every other robot's system
   must avoid it. Also avoid 5040, 5357, 7680, 7778 (already in use).
3. Connect = verify daemon health + read app lock. Disconnect = `stop-current-app`
   (+ `media/release` if we acquired it). Launch = open its UI.
4. The hub is a **client of a single-tenant daemon**. It must surface the lock
   holder rather than fight it — most "robot is stuck" incidents will be this.
