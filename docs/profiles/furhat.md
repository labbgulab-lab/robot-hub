# furhat

Captured 2026-09-14, laptop on iPhone hotspot (`172.20.10.4/28`).
Raw machine capture in `furhat.json`. Operational detail cross-read from
`job\furhat\furhat_startup_guide.html` (lab procedure written against this
exact robot).

## A. Identity

| | |
|---|---|
| IP at capture | `172.20.10.10` (DHCP) |
| **MAC** | **`14:F6:D8:07:5D:00`** — matches the lab guide. **This is the card key.** |
| Hostname | none — no reverse DNS, no NetBIOS |
| OS | Ubuntu 16.04 (SSH banner `SSH-2.0-OpenSSH_7.2p2 Ubuntu-4ubuntu2.4`) |
| Studio password | `admin` |

### No mDNS at all
An `_services._dns-sd._udp` browse returned **`[]`** for this host. Furhat
advertises nothing. Discovery must be **ARP/MAC match** on
`14:F6:D8:07:5D:00`, or a port-80 fingerprint (`<title>Furhat Studio</title>`).

That is a **third** detector: Reachy-wireless = mDNS, Reachy-Lite = USB PnP,
Furhat = ARP/MAC. Each robot needs its own discovery strategy.

### IP is NOT a stable identifier — proven today
Furhat came up on `172.20.10.10`, **the same address the wireless Reachy held
an hour earlier**. Different MAC (`88:A2:9E:8C:E0:13` vs `14:F6:D8:07:5D:00`),
same IP, same session. The iPhone's DHCP pool is tiny and reissues freely.

> **The hub must key every card on MAC / unit_id, never on IP.**
> An IP-keyed hub would have shown Furhat's data under Reachy's card today.

The lab guide says the same in plainer words: *the address changes every time,
so re-check it each session.*

## B. Reachability

Latency **avg 20.4 ms, 0% loss** — noticeably steadier than the wireless
Reachy (8–457 ms). No power-save problem here.

Open ports (full 1–10000 sweep):
```
22  80  1932  3000  3001  5556  5558  5559  5560  5561
5570  5575  5576  5578  8000  8083  9000  9001  9003
```

## C. Surface

| Port | What it is | Notes |
|---|---|---|
| **80** | **Furhat Studio** — the web UI | Node/Express (`Cannot GET /x` on 404). **This is the Launch target.** |
| **9000** | **Furhat Realtime API** | `ws://<ip>:9000/v1/events` + browser Playground. **The programmatic control path.** |
| 8083 | Jetty 9.4.4 | 404 on everything probed |
| 9001 | FastAPI/uvicorn | `/openapi.json` returns `{"paths":{}}` — no routes registered |
| 8000 | unknown | plain-text 404. On the **robot**, so no clash with Reachy's laptop-side 8000 |
| 1932, 3000, 3001, 5556–5578, 9003 | binary banners (`\x00…`) | internal messaging, almost certainly ZeroMQ. Not for us. |

**No REST API worth using.** `/api`, `/status`, `/health`, `/openapi.json` are
all 404 on port 80. Unlike Reachy there is no JSON status endpoint — health
must be inferred from "does port 80 still serve the Studio page".

### Realtime API — the good path
```
ws://172.20.10.10:9000/v1/events        (has an Auth step)
```
The page exposes demos for Speak-Streaming, system-audio visualisation and
camera. For the hub this beats scraping Studio: it is a documented WebSocket
for external control, which is what a card's Connect actually needs.
**Auth mechanism not yet worked out — next thing to investigate.**

## D. Ownership on the laptop — **NOTHING**

This is the big one. Furhat runs **entirely on the robot**. Studio is just a
web page served from it. There is:

- no laptop-side process
- no laptop-side port
- no launcher script
- no venv, no child process to supervise

**Furhat cannot collide with anything.** No port allocation, no supervisor, no
"ensure zero instances". Connect = reach it. Launch = open `http://<ip>/` and
log in with `admin`.

Compare: Reachy-Lite needs the desktop app on `127.0.0.1:8000`;
Reachy-wireless needs `reachy_chat` on laptop `8765`/`8770`. Furhat needs zero
laptop real estate — the easiest of the three to make multi-robot safe.

*(Separately: `job\furhat\furhat_skill_guide.txt` describes the Furhat **SDK**
running a virtual Furhat at `localhost:8080`. That is a desktop dev tool, not
this robot. Don't confuse them — but note 8080 is spoken for whenever the SDK
is running.)*

## E. Audio — fully onboard, **zero laptop contention**

| | |
|---|---|
| Mic | **ReSpeaker 4 Mic Array**, USB, in the robot's base |
| Speaker | onboard |
| Laptop audio used | **none** |

Set under `Settings → Audio devices`; must read `ReSpeaker 4 Mic Array`.

Of the four robots, Furhat is the only one guaranteed never to touch a laptop
capture device. It never participates in the mic lock.

## F. Failure behavior and operational traps

These come from the lab guide, written against this robot. They are **ordering
and configuration traps**, not crashes — which makes them worse, because
everything looks fine while being broken.

### 1. The network must exist BEFORE the robot boots
The robot pulls its cloud credentials (speech + speech recognition) **during
boot and never retries.** Boot it into a network that isn't up yet and it
*wakes up deaf* — indefinitely, with no error.

> The guide's own phrasing for the classic symptom: *"yesterday everything
> worked, today nothing does"* → cause: it booted before the network existed.
> Fix: start the hotspot first, **then** power-cycle the robot.

**Hub consequence:** unfixable after the fact. The card should track boot
order — if Furhat appeared before we saw the hotspot, flag it suspect rather
than green.

### 2. Needs 2.4 GHz
The iPhone hotspot must have **Maximize Compatibility ON**. Keep the hotspot
screen open until it joins — iOS sleeps a hotspot with no clients. It
auto-joins any network it already knows, so a different phone with the **same
SSID and password** works with no reconfiguration.

### 3. Speech/listening engines silently fail to load
Settings *display* as configured while the engines are not actually loaded.
Symptom: **the face's lips move and the room stays silent.**
Fix, required **every session even when it looks fine**: in
`Settings → Speaking` and again in `Settings → Listening`, flip each engine
(Amazon Polly, Microsoft Azure) to `Custom` and immediately back to
`Furhat provided`.

### 4. Speech recognition must be Microsoft Azure
**Never Google Cloud** — not configured on this robot. Correct state shows
`Configured (Provided)` in green with 556 voices. The guide calls this the
single most likely reason for *"Furhat can't hear you"*, and notes it
convincingly imitates a mic fault.

### 5. Default voice is Japanese
Default is `Sakura22k_HQ`. If nobody sets a language, Furhat reads English
text in Japanese. Set `Language = English (United States)`, pick e.g.
`Ella22k_HQ`.

### 6. Mic must be physically connected before power-on
So it is enumerated during boot.

### Boot time
"Several minutes — it boots a whole OS." The projected face on the mask is the
liveness signal.

## Studio layout (the Launch target)

Seven sections; the first two are daily use:
- **Home** — live camera with face tracking, mic level meter, Testing box
  (speech, gestures, listening, LED). The 30-second all-senses check.
- **Dashboard** — live conversation transcript + **Wizard board** to jump to
  any part of a script.
- **Furhat AI Creator** — no-code conversational character.
- **Realtime API** — WebSocket control + Playground + access control.
- **Skill Library** — `Your Skills` imports a `.skill` file; built-ins include
  MeetFurhat, JokeBot, Quiz, OpenAIChat. Each has Start + an Autostart toggle.
- **Face Editor**, plus one more.

Built `.skill` files live next to the SDK launcher in AppData, **not** in
`Desktop\job\furhat`.

## Open items

1. **Realtime API auth** — `/v1/events` has an Auth step, mechanism unknown.
   Needed before the hub can drive Furhat programmatically.
2. No JSON health endpoint — decide what the card polls. Likely `GET /` on 80,
   checking for the `Furhat Studio` title.
3. Disconnect signature not captured.
4. Whether the Studio `admin` login can be automated (cookie/session) for the
   auto-sign-in the hub wants.
