# Furhat — control paths (investigated 2026-09-14)

Resolves open items 1 and 4 from `furhat.md`. Everything below was run
against the lab robot at `172.20.10.10` and verified live.

There are **two** WebSocket control paths. **Both are now working and both
were verified speaking out loud** — see the VERIFIED section at the end, which
supersedes the "blocked" wording kept below for history.

---

## Path A — Realtime API on :9000 — **UNLOCKED 2026-09-14**

```
ws://<ip>:9000/v1/events
```

Originally the connection was accepted **without any auth key** while every
action was refused — `{"access":false}` and `Access denied` on everything.
**That was fixed by enabling the Realtime API in Studio and issuing a key**;
see the VERIFIED section at the end for the working calls.

### Protocol notes
- Discriminator is **`type`**, not `name`. Sending `name` gives
  `Polymorphic serializer was not found for missing class discriminator`
  (it is Kotlin `kotlinx.serialization` underneath).
- Full catalog is served at **`http://<ip>:9000/v1/events.js`** — 13
  categories: Attention, Audio, Authentication, Camera, Face, Gestures, LED,
  Listen, Speak, Speak (Streaming), System, Users, Voice.
- Auth event per the catalog: `{type:"request.auth", key:"YOUR KEY"}`.
  Its own description: *"The required level of authentication is configured
  in the web interface."*
- Note the UI asset paths are under `/v1/` (`/v1/scripts.js`, `/v1/styles.css`);
  `/scripts.js` at root is a 404.

### How it was unblocked
Studio -> **Realtime API** -> access control, then issue a key. The Redux state
in the Studio bundle holds these settings:

```js
{ ipAddress, port: "9000", localNetworkAuth, localNetworkKey,
  anywhereAuth, anywhereKey, isPremium... }
```

The earlier premium-gating guess was **wrong** - it was simply not enabled yet.
Enabling it plus a key was sufficient; no licence involved.

---

## Path B — Studio's own event bus on :80 — **WORKS TODAY** ✅

```
ws://<ip>/api          (port 80; in-browser it is window.location.port, i.e. empty)
```

This is the socket Furhat Studio itself uses. It is a full Furhat event bus
and it needs only the `admin` password we already have.

### Auto-login — verified working

Password is **SHA-256, hex, UPPERCASED**, sent as a Furhat event. From the
Studio bundle:

```js
var e = p.sha256.create();
e.update(password);
send({ event_name: "furhatos.event.actions.ActionLoginAccess",
       password: e.hex().toUpperCase() });
```

Subscribe first, or the bus stays silent:

```json
{"event_name":"furhatos.event.actions.ActionRealTimeAPISubscribe",
 "name":"furhatos.event.monitors.MonitorLoginAccess"}
```

Then log in. Live result:

```
-> ActionLoginAccess  (sha256("admin").upper()
                       = 8C6976E5B5410415BDE908BD4DEE15DFB167A9C873FC4BB8A81F6F2AB448A918)

<- {"loginApproved":true,
    "event_name":"furhatos.event.monitors.MonitorLoginAccess",
    "event_time":"2026-09-14 09:35:59.858"}
<- {"event_name":"furhatos.event.senses.SenseSystemStarted"}
```

**`loginApproved: true`.** The auto-sign-in the hub wants is a solved problem.

### The event vocabulary (from the bundle's own helpers)
```js
subscribe(name)   -> {event_name:"furhatos.event.actions.ActionRealTimeAPISubscribe", name}
subscribeGroup(g) -> {event_name:"furhatos.event.actions.ActionRealTimeAPISubscribe", group}
say(text)         -> {event_name:"furhatos.event.actions.ActionSpeech", text}
status()          -> {event_name:"furhatos.event.requests.RequestSystemStatus"}
login(pw)         -> {event_name:"furhatos.event.actions.ActionLoginAccess", password}
```
Monitors seen: `MonitorLoginAccess`, `MonitorSystemStatus`,
`SenseSystemStarted`. Events carry `event_id`, `event_sessionId`, `event_time`.

`ActionSpeech` is **tested and working** — see the VERIFIED section.

---

## Other Furhat ports, now identified

| Port | Identified as |
|---|---|
| **80** | Studio UI **and** the `/api` event bus |
| **8000** | **WebRTC camera streamer** — `new WebRTC("video", http://<host>:8000)`, stream id `furhat-0x0000` |
| **8083** | plain WS audio-level meter. Messages are space-separated: `channel silence speech energy inSpeech` (e.g. `0 0 0 17 0`). Also serves Jetty 404s. |
| 9000 | Realtime API (working - see VERIFIED section) |
| 9001 | FastAPI with `{"paths":{}}` — no routes |
| 1932, 3000, 3001, 5556–5578, 9003 | internal, binary banners |

Skill upload endpoint also spotted: `POST http://<host>:<port>/skill/deploy`
(multipart, with upload progress) — that is how Studio imports a `.skill`.

---

## Recommendation for the hub

**Use Path B.** It works now, needs no licence, and the password is already
known.

- **Health / online** — `ws://<ip>/api`, subscribe `MonitorSystemStatus`, send
  `RequestSystemStatus`. A real status signal, which `furhat.md` had listed as
  missing. Better than polling the port-80 HTML title.
- **Auto sign-in** — the SHA-256 flow above, exactly as the card requires.
- **Mic level** — `ws://<ip>:8083/` gives a live speech/energy meter. That is
  the direct fix for the "lips move, room silent" and "can't hear you" traps
  in `furhat.md`: the card can *show* whether audio is actually flowing rather
  than making someone guess.
- **Camera** — WebRTC on 8000 if the card ever wants a live face preview.

Path A is now available too and gives richer structured reads - see the
final section for the current recommendation.


---

# VERIFIED 2026-09-14 — both paths fully working

User enabled the Realtime API in Studio and issued a test key.
**Test key used: `ScrMFRgcey7L` — user said this was for the test only and
would be regenerated afterwards. Treat it as dead; do not hard-code it.**
The same key served both key-requiring features.

## Path A is now open

```
-> {"type":"request.auth","key":"<KEY>"}
<- {"type":"response.auth","access":true,"scope":"local_network"}
```

Auth is **per-connection and sticky** — a later bare `{"type":"request.auth"}`
on the same socket still reports `access:true`, so it doubles as a status
check. Reconnecting requires re-auth.

### Live reads that now work
```
request.system.status -> {"volume":70,"virtual":false}
request.voice.status  -> voice_id "Matthew-Neural (en-US) - Amazon Polly"
                         + full voice_list (Acapela / Polly / Azure, ja-JP, nb-NO, en-US, ...)
request.face.status   -> face_id "adult - Alex" + ~60 faces
request.users.once    -> {"users":[]}
```

Note the live voice is **English (Matthew-Neural)**, not the `Sakura22k_HQ`
Japanese default the lab guide warns about. Someone already set it. The card
should still *display* the active voice, since it silently resets.

## Speech verified on BOTH paths

### Path B (`ws://<ip>/api`, after SHA-256 login)
```
-> {"event_name":"furhatos.event.actions.ActionSpeech","text":"..."}
[+1.44s] MonitorSpeechStart  generationTime=1381ms
[+6.30s] MonitorSpeechEnd    aborted=false
```

### Path A (`ws://<ip>:9000/v1/events`, after key auth)
```
-> {"type":"request.speak.text","text":"..."}
[+0.34s] {"type":"response.speak.start","gen_time":265}
[+3.19s] {"type":"response.speak.end"}
```

The robot spoke audibly on both. Both report clean start/end events with a
shared `action` id (Path B) for correlation — usable as a "currently speaking"
indicator on the card.

### Latency - RE-MEASURED, the paths are EQUIVALENT

The first reading (A 265 ms vs B 1381 ms) was **an artefact of TTS caching,
not a difference between the paths.** Re-ran with Path A cold first, same
short text, six alternating trials:

| trial | path | gen_time |
|---|---|---|
| 1 (cold) | A | **1126 ms** |
| 2 | B | 0 ms |
| 3 | A | 0 ms |
| 4 | B | 0 ms |
| 5 | A | 0 ms |
| 6 | B | 0 ms |

Only the **first utterance of a given string** pays generation cost. After
that it is 0 ms on both paths - and trial 2 shows **the cache is shared
across paths**: Path B got a free ride on text Path A had just generated.
Speech duration was ~1.2 s in every trial on both.

**Conclusion: choose a path on capability and auth, never on speed.**

### Hub consequence
A first-time phrase costs roughly a second of TTS before any audio. For demos,
**pre-warm the fixed lines** (greeting, fallback, closing) once at Connect and
they play instantly thereafter. That is a real, cheap win the card can do on
its own.

## Gesture - WORKING, the earlier silence was my bug

`request.gesture.start` needs **`monitor: true`** to acknowledge. Without it
the server runs the gesture and says nothing - which is why the first attempt
looked dead.

```json
{"type":"request.gesture.start","name":"BigSmile",
 "intensity":1.0,"duration":1.5,"monitor":true}
```
```
<- {"type":"response.gesture.start"}
<- {"type":"response.gesture.end"}
```

Clean start/end for all four tested: **BigSmile, Nod, Shake, Surprise**.

Full gesture set from the catalog:
`Smile, BigSmile, Wink, Thoughtful, Surprise, Oh, BrowFrown, BrowRaise,
Blink, CloseEyes, OpenEyes, Nod, Shake, Roll, GazeAway, ExpressDisgust,
ExpressSad, ExpressAnger, ExpressFear`
Params: `name` (required), `intensity` (default 1.0), `duration` (default 1.0),
`monitor`.

**General rule: several Realtime API requests are silent unless `monitor:true`
is set.** Assume no reply means "no monitor requested", not "not supported".

## Verdict for the hub

Use **Path B** as the primary, as the user prefers:
- no licence dependency, no key to manage or rotate
- the `admin` password is already known and the login is automated
- gives login, speech, and `RequestSystemStatus`

Keep **Path A** as the richer read-only channel when a key is available:
- structured status for volume / voice / face / users
- lower apparent speech latency (pending re-measurement)
- the full 13-category catalog at `/v1/events.js`

Both are live simultaneously — they are independent sockets on independent
ports, and using one does not block the other. That was true during this test:
Path B logged in and spoke, then Path A authed and spoke, with no interference.
