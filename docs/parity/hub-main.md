# Robot Hub main page: feature parity inventory

Scope: the hub's main page (what a student sees at `http://127.0.0.1:8099/`). The Reachy page (`group.html`) is a separate inventory; this one only records how the main page hands over to it.

Files read in full:
- `robot-hub/web/index.html` (309 lines)
- `robot-hub/web/app.js` (1143 lines)
- `robot-hub/web/style.css` (517 lines; only the state colours and classes are cited)

Backend read for option values and behaviour: `hub/main.py` (366, REST + WebSocket), `hub/core.py` (686, card state machine, connect/launch/posture/WiFi), `hub/registry.py` (111, card fields), `hub/keys.py` (206, providers), `hub/wifi.py` (178, laptop WiFi check), `hub/library.py` (370, robot files), `hub/resources.py` (173, conflicts), `hub/config.py` (140), `config.example.toml`, adapters `furhat.py`, `naoqi.py` (NAO + Pepper), `reachy_wireless.py`, `reachy_lite.py`, `base.py`.

The design has no dark mode, no keyboard shortcuts beyond native form behaviour (Enter submits the key, WiFi and file forms) and no browser `confirm()` dialogs: every destructive action uses a "press twice" pattern instead.

Item IDs (A1, F3, ...) are used in the Flows and Notes. **Total: 105 numbered items, plus 8 card states and a 5-row capability table for the robot types.**

---

## A. Top bar (always visible)

| ID | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| A1 | "Robot Hub" | heading / brand | — | Page title | always | index.html:37 |
| A2 | "Auto-connect" | toggle (checkbox) | off by default (`auto_connect = false` in config.toml); hover title "Connect to each robot automatically as it appears" | PUT `/api/settings {auto_connect}`. When on: each newly detected robot is connected automatically, and a failed connect or a lost robot is retried with backoff 2 s, doubling up to 30 s ("retrying in N s" in the log). The hub broadcasts the value to every open page, and the log says "auto-connect on/off". **Global, not per robot. In memory only: a hub restart goes back to the config.toml value.** | always | index.html:39-42; app.js:1068-1074, 1106, 1118; main.py:182-193; core.py:221-222, 367-384 |
| A3 | Hub link pill: dot + "connecting" / "live" / "reconnecting" | status indicator | — | Shows the page's WebSocket to the hub. The dot turns green on "live". On close it reconnects with backoff from 500 ms, doubling to 10 s. | always | index.html:43-45; app.js:1124-1141; style.css:86 |

## B. Network banner

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| B1 | "This laptop is not on the robots' network — currently on {interfaces} / — no usable interface. Robots will look dead until you rejoin." | banner (alert icon) | — | Explains why every card went dead | `network.on_robot_subnet === false` (pushed over the WebSocket by discovery). The hub also logs an error, which raises a toast. "back on the robots' network" is logged on recovery. | index.html:51-53; app.js:916-929; core.py:267-281 |

## C. Summary bar

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| C1 | "{n} of {total} present" | live counter | present = DETECTED, CONNECTING, CONNECTED, RUNNING, DEGRADED or ERROR | Count of robots on the network | always | index.html:57-60; app.js:879-889 |
| C2 | blue dot "{n} connected" | live counter | CONNECTED, RUNNING or DEGRADED | — | always | index.html:61-63 |
| C3 | green dot "{n} running" | live counter | RUNNING | — | always | index.html:64-66 |
| C4 | "watching for robots…" / "last update HH:MM:SS" | live text | 24-hour time | Time of the last log event | always | index.html:67; app.js:938-940, 1107, 1114 |
| C5 | "Scan now" | button (refresh icon) | — | POST `/api/rescan`: discovery sweeps again now instead of waiting for its next cycle (every 5 s by default). Shows "Scanning…" with a spinner, then re-enables after 1.2 s. On failure: toast "Scan failed: …". | always | index.html:68-70; app.js:1076-1091; core.py:164-177 |

## D. Network setup panel (collapsible)

Opens by itself on the first visit in this browser (`localStorage hub.setupSeen`) and whenever the check finds a problem. It is checked again on load, on **Check again**, and whenever the hub pushes a `network` event.

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| D1 | "Network setup" | collapsible section (`<details>`) | auto-opens as described above | — | always | index.html:78-80; app.js:552-559, 600 |
| D2 | Badge "checking…" / "{ssid} · {band}" / "ready" / "needs attention" | status badge (green ok, red problem) | — | Short result of the WiFi check | always, in the summary row | index.html:81; app.js:596-599; style.css:480 |
| D3 | Status line: "This laptop is on "{ssid}" · {iPhone hotspot / Android hotspot / phone hotspot / the lab WiFi} · {2.4 GHz/5 GHz/6 GHz}. Robots can join it." or the problem sentence | live status (radar icon, or alert icon on a problem) | Problems from wifi.py: "This laptop is not on any network." / "This laptop is on X. The robots are on the lab WiFi "…" — connect…" / "Your hotspot is on 5 GHz — the robots cannot see it. Turn on 2.4 GHz…" / "…does not look like a phone hotspot…" / "Could not ask the hub (…)" | GET `/api/wifi` | panel open | index.html:84-86; app.js:561-601; wifi.py:127-176 |
| D4 | "Check again" | button (spinning while checking) | — | Runs the check again | panel open; disabled while checking | index.html:87-89; app.js:603 |
| D5 | Lab WiFi name, filled into every "the lab WiFi" phrase on the page | dynamic text | comes from `[network] lab_wifi` in config.toml and is never in the page source | Replaced with `the lab WiFi "{name}"` | when the hub knows the name | app.js:574-578 |
| D6 | "1. Connect this laptop to the lab WiFi" | static guide (3 bullets) | — | Join the laptop; turn off auto-join for other WiFi; robots appear in about 30 s; mDNS is dropped, so the hub sweeps by address | panel open | index.html:91-97 |
| D7 | "2. Put each robot on the lab WiFi (once per robot)" + note | static heading | — | — | panel open | index.html:99-100 |
| D8 | "Reachy Mini" | nested collapsible guide (3 steps) | — | New robot: bring-up tool / `/reachy-set-up`; older robot: `--name reachyN` from `reachy-mini-ap`; or the card's Add WiFi with the lab box ticked | panel open | index.html:101-108 |
| D9 | "NAO" | nested collapsible guide (4 steps) | — | Ethernet, chest button, web page settings, connmanctl fallback | panel open | index.html:109-117 |
| D10 | "Furhat" | nested collapsible guide (2 steps) | — | Own screen WiFi settings; power-cycle | panel open | index.html:118-124 |
| D11 | "Pepper" | nested collapsible guide (1 step) | — | Tablet settings WiFi; never Advanced Settings | panel open | index.html:125-131 |
| D12 | "3. Check" | static text | mentions `netscan_nearby_24s` (default 4) | How to recognise a robot's address; Scan now; power-cycle | panel open | index.html:133-134 |
| D13 | "Outside the lab: a phone hotspot" | nested collapsible guide (7 bullets) | — | iPhone Maximize Compatibility; Android 2.4 GHz; plain names; shared name/password tip; teach a robot your hotspot via Add WiFi; "not the lab WiFi" is expected there | panel open | index.html:136-153 |

## E. Robots section header

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| E1 | "Robots ({n})" | heading + live count | — | Number of cards | always | index.html:159; app.js:888 |
| E2 | Range: radar icon + "{interfaces}" / "this network" / "off the robots' network" | live text | — | Which interfaces discovery is on | always | index.html:160; app.js:924-927 |
| E3 | Card grid | grid | 3 columns; 2 below 1080 px; 1 on a phone | Cards in fixed type order: Furhat, Reachy Mini (wireless), Reachy Mini Lite, NAO, Pepper | always | index.html:162; app.js:24, 80-84; style.css:427-429 |
| E4 | Placeholder cards | card state | one per enabled robot type, "waiting for this robot to appear" | Dim cards shown before any robot is found; each is replaced when its robot appears | before discovery finds that type | core.py:71-83, 284-287 |

## F. Robot card: shared parts (one per robot; per-robot scope)

Card states (`data-state`) and how they look:

| State | Status text | Look |
|---|---|---|
| ABSENT | Absent | card dimmed (opacity .55); detail "not on the network" |
| DETECTED | Available | grey status |
| CONNECTING | Connecting | amber, pulsing dot; spinner on Connect |
| CONNECTED | Connected | blue border and ring |
| RUNNING | Running | green border; Launch turns into the light-blue "Open" |
| DEGRADED | Degraded | amber border (for example "stopped answering discovery", "not answering yet (daemon restart?)", a probe timeout) |
| ERROR | Lost | red border; auto-reconnect when Auto-connect is on |
| DISABLED | Unavailable | dimmed; detail = `disabled_reason` (a local prerequisite is missing, e.g. "set nao_llm_path in config.toml…") |

(app.js:30-39; style.css:147-152, 205-211; core.py throughout)

| ID | Label | Kind | Options | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| F1 | "Disconnect" (top left) | pill button (unlink icon) | — | POST `/disconnect`. Cancels a launch in flight first (waits up to 50 s), stops the robot's system (NAO_LLM / pepper_app / reachy_chat), and puts a Reachy to sleep. Releases resources, clears the launch error and the posture note, and sets the card to DETECTED, "disconnected". | enabled when CONNECTED, RUNNING, DEGRADED or ERROR | index.html:232-234; app.js:120; core.py:457-496 |
| F2 | "Connect" (top right) | pill button (link icon; spins while connecting) | — | POST `/connect` (25 s timeout). Reads system status, then **the robot says its announcement out loud** (default "I am {name}, I am connected and ready to run.", set per robot type in config.toml). A Reachy also gets its volume set and wakes up. An auto-reconnect stays silent. | enabled when present, not connected, not connecting | index.html:235-237; app.js:119-121; core.py:400-455; config.py:23,90 |
| F3 | Robot picture | image | `/photos/{type_id}.png`; falls back to a robot glyph if missing | — | always | index.html:240; app.js:131-145 |
| F4 | Robot name (e.g. reachy1, Furhat, NAOqi, Pepper) | heading | per-unit `display_name` in config.toml, else the type name | — | always | index.html:242; app.js:95-96; core.py:203 |
| F5 | Muted-microphone icon after the name, hover "connected, but could not speak" | status indicator (amber) | — | The connect announcement failed. On Furhat this usually means a misconfigured speech engine. | CONNECTED/RUNNING/DEGRADED and `can_speak === false` | app.js:99-103; style.css:215 |
| F6 | Detail line | live text | e.g. "detected at x.x.x.x", "connecting", "connected", "broker answering, battery 64%", "Studio is serving on port 80", "system running", "disconnected", "its address now belongs to {other}", "connect timed out", "connect failed: …", "no answer within 6 s" | Latest detail from the probe or the action | always | index.html:243; app.js:105-106 |
| F7 | "Status" metric (dot + text) | status indicator | the 8 states above | — | always | index.html:246-249; app.js:107 |
| F8 | Right metric: **Battery** "{n}%" (red below 20%) / **Link** "USB" or "unplugged" (Reachy Lite) / **Address** "{ip}" or "—" | live display | Battery is shown for any robot that reports one: NAO, and Pepper (it shares NAO's adapter) | Polled about every 2 s | always | index.html:250-256; app.js:365-388; naoqi.py:432-444 |
| F9 | Card speaking-key picker | select | see section G | — | robots that use a speaking key (Reachy Mini wireless, Pepper) | index.html:258-261 |
| F10 | Posture row | button group | see section H | — | NAO only | index.html:265-273 |
| F11 | "Add WiFi…" | toggle + form | see section I | — | NAO, Pepper, Reachy Mini wireless, when present | index.html:278-288 |
| F12 | "Launch" / "Open" / "Launching… {n} s" | primary button | see section J | — | always rendered | index.html:290-293 |
| F13 | Conflict box | inline alert | see section K | — | on a resource conflict | index.html:295-302 |
| F14 | Reorder / removal | behaviour | — | A new card is placed in type order; a `robot_removed` event deletes the card | — | app.js:80-84, 871-877 |
| F15 | Stale-address eviction | behaviour → state | — | When another robot appears at a card's address, the old card goes ABSENT with "its address now belongs to {name}", and the log says "{old} is gone: {new} now answers at {ip}" | — | core.py:224-244 |
| F16 | Hidden card fields (sent by the hub, not shown) | data, not rendered | `mic` (e.g. "robot's built-in mic (reachymini_audio_src)", the laptop DJI device, "Pepper's own four microphones", "Windows default input (NAO_LLM …)"), `daemon_version`, `last_seen` | Present on every robot event but never drawn | — | registry.py:38-40; reachy_wireless.py:267-277; naoqi.py:459-470 |

## G. Card: speaking key (per robot)

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| G1 | Key icon + select, hover "Which key this robot speaks through; sent at launch" | select | First option: "Default: {label} · {provider} · …{last4}" when unassigned and a key exists / "Default (first Gemini key)" / "No keys — add one below". Then every key as "{label} · {Provider} · …{last4}", with " — cannot speak yet" for ElevenLabs, Qwen and OpenRouter. | PUT `/api/robots/{key}/key {key_id}`. The log says "{robot} will speak through {label}", plus " (applies at next Launch)" if the robot is running. **The chosen key's provider decides the robot's AI backend at Launch** (Gemini → gemini, GPT → gpt_live). Launch also exports the first key of every provider (GEMINI/OPENAI/ELEVENLABS env), so the robot's own dashboard can switch backend mid-session. | robot type has `uses_speech_key` (reachy_wireless, pepper) | index.html:258-261; app.js:466-495, 509-515; keys.py:39-53, 138-171; core.py:122-133, 537-543 |
| G2 | Fallback styling | state | amber text when no key is assigned (the default is used) | Warns that the robot is on the default key | unassigned | app.js:489; style.css:421 |
| G3 | Deleted-key fallback | behaviour | — | A robot whose assigned key is deleted falls back to the default | — | keys.py:191-197 |

## H. Card: NAO posture (per robot, NAO only; Pepper has none)

| ID | Label | Kind | Options | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| H1 | "Sit" (hover "Sit on the floor, then motors off") | pill button | — | POST `/posture {name:"sit"}`. Refused if any joint is ≥ 70 °C. | NAO; enabled when CONNECTED or RUNNING, not launching, not already moving | index.html:266-267; app.js:260-304; naoqi.py:103-112, 513-566 |
| H2 | "Lie down" (hover "Lie on its back, then motors off") | pill button | — | Same, `lie` (LyingBack), 70 °C limit | same | index.html:268-269 |
| H3 | "Stand up" → "Confirm" (hover "Stand up, motors stay on — someone should be next to it") | pill button, **two taps** | the first tap arms it for 5 s (amber), the second stands | `stand`; **lower heat limit, 60 °C**; motors stay on | same | index.html:270-271; app.js:247-258, 345-358 |
| H4 | Posture note | live status line | spinner + "Sitting down… / Lying down… / Standing up…" (busy stripes on the button); amber "NAO will stand up, motors on — make sure someone is next to it, then tap Confirm."; red refusal ("{joint} is {temp} …", "NAO reported no joint temperatures…", "is launching — wait…", "is busy…", "connect to … first", "Restart the hub to use the posture buttons."); result "NAO is sitting, motors off (hottest joint: left knee 54 °C)" / "NAO was already …— nothing moved"; failure "NAO did not reach Sit … motors left on…" | Shared by every open page (the hub keeps `posture_pending`, `posture_note` and `posture_failed` on the card) | NAO | index.html:273; app.js:286-303; core.py:615-672 |
| H5 | Toast on refusal | toast | — | Repeats the refusal | on refusal | app.js:336 |

## I. Card: Add WiFi (per robot: NAO, Pepper, Reachy Mini wireless)

| ID | Label | Kind | Options | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| I1 | "Add WiFi…" | text toggle button | — | Shows or hides the form and focuses the name field | type is naoqi, pepper or reachy_wireless, and the robot is present (stays visible while a join is busy) | index.html:279; app.js:189-196, 1011-1016 |
| I2 | "Hotspot name" | text input | 1-32 bytes (checked by the server) | SSID | form open | index.html:281 |
| I3 | "Password" | password input | the client requires ≥ 8 characters; the server takes 8-63 | — | form open | index.html:282; app.js:212; naoqi.py:478-481 |
| I4 | "This is the lab WiFi (the robot's fallback; it does not move now)" | checkbox | off by default | **Reachy only.** Saves the network as the robot's fallback without moving it. The server forces this on when the SSID equals the configured lab WiFi. | Reachy wireless cards only | index.html:284; app.js:196, 204; core.py:592-598 |
| I5 | "Join" | submit button | — | POST `/api/robots/{key}/wifi {ssid,password,lab}`. Takes up to a minute (NAO 90 s). On success the robot moves to the hotspot and its card goes dim until the laptop follows; the password field clears and the form closes. | form open; disabled while joining | index.html:283; app.js:199-239; core.py:567-613 |
| I6 | Hint "Turn that hotspot on first (2.4 GHz). The robot moves to it now and remembers it." | static text | — | — | form open | index.html:285 |
| I7 | WiFi note | live status line | "Type the hotspot name." / "A WiFi password has at least 8 characters." / "Joining "X"… up to a minute. Keep that hotspot on." / "Saving "X" as the lab WiFi…" / green success "{robot} joined "X" and will remember it. Connect this laptop to "X" to see it again." / red error (e.g. "is launching — wait for it first", "is busy…", "the robot is still on this network -- it could not join…(check the password)", "Could not ask the hub: …") | Plus a success toast | after Join | index.html:287; app.js:205-234; naoqi.py:473-498 |

## J. Card: Launch (per robot)

| ID | Label | Kind | Options | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| J1 | "Launch" | primary button | — | **Furhat:** opens Furhat Studio at `http://{ip}/` (the log notes "Studio will ask for the 'admin' password"). **NAO:** writes NAO_LLM's config on a free port, starts NAO's speaker server on the robot (about a minute), starts NAO_LLM and opens its control panel `http://127.0.0.1:{port}/`; the first run downloads a speech model (several minutes); it refuses if NAO_LLM's API keys are missing. **Pepper:** starts `pepper_app` and opens its dashboard `http://127.0.0.1:8780/` with the GPT key from the card (without one: "dashboard opens, but the AI conversation and the AI voice need one"). **Reachy Lite:** starts Reachy Mini Control if needed and opens the daemon page. **Reachy Mini wireless:** does NOT launch from the card: it opens the Reachy page (`/group.html`, one named tab "robot-hub-group"). There one Reachy talks alone (Talk) and two or more hold a group conversation or Choir. Hover text says so. | enabled when CONNECTED, RUNNING or DEGRADED and not busy | index.html:290-292; app.js:151-181, 891-901, 984-994, 1017-1028; furhat.py:388-395; naoqi.py:662-714, 841-867; reachy_lite.py:183-191 |
| J2 | "Open" | primary button (light blue) | — | Running robot (not Reachy wireless): reopens its system URL in a new tab without restarting it | state RUNNING with a system URL | app.js:160-161, 1021-1025; style.css:247 |
| J3 | "Launching… {n} s" | busy button (spinner, stripes, live seconds counter) | ticks every second | Survives a page refresh (the hub keeps `launching_since` on the card) | while launching (the hub allows up to 120 s by default; NAO, Pepper and Reachy have longer bounds) | app.js:147-181, 360-363; core.py:498-522 |
| J4 | Launch note | live status line | "Starting its system — this can take a couple of minutes." / red "Launch failed: {reason}" (e.g. "timed out", "cancelled by Disconnect", "connect first", "{name} is already busy", "NAO_LLM refuses to start without …", "Pepper's dashboard never answered on port 8780 within … s") | Shown under the button | busy, or after a failure (until the next launch or Disconnect) | index.html:293; app.js:176-180 |
| J5 | Waiting tab "Launching {name}… This tab opens its system as soon as it is ready." | new browser tab | — | Opened during the click so it is not blocked as a popup; it navigates to the system when ready and closes on failure | on Launch / Override | app.js:944-966 |
| J6 | Popup-blocked toasts | toast | "Launched. The browser blocked the new tab — press Open on the card." / "The browser blocked the new tab. Allow pop-ups for the hub." (Reachy page) | — | when blocked | app.js:900, 965 |
| J7 | Launch-time key handover | behaviour (log) | "{robot}: speaking through {label} (...{last4}; assigned / no key assigned, using the first Gemini key)" | — | robots with a speaking key | core.py:537-543 |
| J8 | Pre-launch clean-up notes | behaviour (log) | e.g. "an app named 'X' is already holding this robot", "Furhat runs entirely on the robot; nothing to stop", "Pepper's dashboard was already running" | — | at launch | core.py:545-546 |

## K. Card: resource conflict (per robot)

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| K1 | Conflict text, e.g. "Cannot start: {device} is in use by {robot}. Stop that first, or override." / "Cannot start: X is claimed by Y." / "…must not be running, but Y needs it." | inline alert (alert icon) + toast | — | A launch claimed a resource another robot holds (for example NAO and a laptop-mic Reachy both wanting the Windows default microphone) | `conflict` event or a conflict reply to a launch | index.html:295-297; app.js:931-936, 975, 1117; resources.py:144-156 |
| K2 | "Override" | pill button | — | POST `/override`: launches anyway (logged as "OVERRIDE: …" warnings); hides the box; opens a waiting tab | conflict box shown | index.html:299; app.js:1026-1027; main.py:140-144 |
| K3 | "Dismiss" | pill button | — | Hides the box | conflict box shown | index.html:300; app.js:1003-1006 |

## L. Speaking keys panel (collapsible, closed by default)

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| L1 | "Speaking keys ({n})" | collapsible section + count | — | — | always | index.html:167-169; app.js:421 |
| L2 | "Stored on this laptop only. A robot gets its key when it launches — nothing is kept on the robot." | note | — | — | open | index.html:170 |
| L3 | Key row: provider badge (greyed "no-speech" for providers that cannot speak) · label · "…{last4}" · **"used by" list of robot names** · bin | list row | — | Shows which robots are assigned each key | per key | app.js:429-460 |
| L4 | Bin (hover "Delete this key" → "Press again to delete") | button, **two presses within 4 s** | — | The first press arms it and toasts "Press the bin again to delete "{label}"."; the second press DELETEs `/api/keys/{id}` | per key | app.js:446-457, 517-519 |
| L5 | Empty state "No keys yet. Robots cannot speak until one is added." | empty state | — | — | no keys | app.js:423-428 |
| L6 | Provider | select | Gemini, GPT, ElevenLabs "(no speaking backend yet)", Qwen "(no speaking backend yet)", OpenRouter "(no speaking backend yet)"; default is the first, Gemini | — | open | index.html:173; app.js:412-419; keys.py:34-45 |
| L7 | "Label, e.g. Lab Gemini 2" | text input | optional; empty → "{Provider} key" | — | open | index.html:174; keys.py:184 |
| L8 | "Paste the API key" | password input, required | ≥ 8 characters; duplicates refused | — | open | index.html:175; keys.py:178-183 |
| L9 | "Add key" | submit button | — | POST `/api/keys`. On success it clears the secret and the label and toasts "Key added. Pick it on a robot's card." Errors are toasted ("that does not look like an API key", "that key is already in the hub", "'x' is not one of …"). | open | index.html:176; app.js:521-535 |
| L10 | First-run seeding | behaviour | — | With no keys, the hub imports the Gemini key file reachy_chat already used on this laptop | hub start | core.py:85-91 |

## M. Robot files panel (collapsible; loads when first opened)

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| M1 | "Robot files ({n})" | collapsible section + total count | — | The first open loads `/api/files` | always | index.html:184-186; app.js:867-869 |
| M2 | "Shared with the lab on GitHub ({repo}). Keys are removed before a file goes up…" | note with the live repo name | repo from `ROBOT_FILES_REPO` or the default | — | open | index.html:187-188; app.js:671 |
| M3 | "Robot" | select | Furhat, Reachy Mini, Reachy Mini Lite, NAO, Pepper, each with "({count})"; remembered per browser (`hub.filesRobot`) | Filters the list | open | index.html:190-191; app.js:659-678, 861-865; library.py:48-54 |
| M4 | Refresh (hover "Reload the list") | icon button (spins) | — | Reloads the list | open | index.html:192-194; app.js:866 |
| M5 | File row: file icon · name · meta "{size} · by {uploader} · {date} · needs a {Provider} key" | list row | — | — | per file of the chosen robot | app.js:701-719 |
| M6 | Key-to-insert select | select | "Without a key" + "With {label} · {provider} · …{last4}" for each of this laptop's keys matching the file's needed providers; **the first matching key is preselected** | Puts your own key back into the downloaded copy | file needs a key | app.js:721-740 |
| M7 | "Download" | button with live progress | "Getting it…" / "Getting it, adding your key…" / "{n}%" / size | Streams `/api/files/{id}/download?key_id=` and saves it. Toast "{name} has your key in it — keep that copy to yourself." / "Downloaded {name}." / error | per file | app.js:742-747, 772-814 |
| M8 | Bin (hover "Delete from the lab library" → "Press again to delete it for everyone") | button, **two presses within 4 s** | — | DELETE `/api/files/{id}` **for the whole lab**; toast "Deleted {name}." | per file | app.js:749-768 |
| M9 | File picker | file input, required | up to 2 GB; not empty | — | open | index.html:198; main.py:277-303 |
| M10 | "Upload" | submit button | `replace=false` the first time | POST raw body. Live status "Uploading {name}: checking it for keys, then sending it to GitHub… {n} s" with a spinner. Success: "{name} is shared — its key was removed first." If a file with that name exists: "{error}. Press Upload again to replace it for everyone." (**the second press replaces it**). Errors include "uploading needs a GitHub sign-in with write access…". | open; disabled while uploading | index.html:199-201; app.js:816-858 |
| M11 | Files status line | live status | spinner / green / red | — | after an action; cleared on a new file pick | index.html:203; app.js:632-643, 860 |
| M12 | Empty and error states | empty state | "No files for {robot} yet. Upload the first one below." / "Could not load the files: {error}" (e.g. "could not reach GitHub: …") | — | — | app.js:681-697 |

## N. Activity log (collapsible, open by default)

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| N1 | "Activity" | collapsible section | open by default | — | always | index.html:207-209 |
| N2 | Log rows: "HH:MM:SS" + text, coloured by level (info grey, ok green, warn amber, error red) | live list, newest first, at most 300 rows; the snapshot brings the last 100 | — | Every hub event: appeared/gone, connecting, connected, "{robot} said: "…"", retries, launches with URLs, key changes, WiFi joins, postures, OVERRIDE warnings, adapter notes (head id, volume, first-run install, mic not found), files | always | index.html:214; app.js:903-914; style.css:361-363 |
| N3 | "Copy" (hover "Copy the activity log") → "Copied" | button | — | Copies the log as plain text (clipboard API, with a fallback). Toasts "Nothing in the log yet." / "Could not copy — select the log and press Ctrl+C." | always (it sits in the summary row and does not fold the log) | index.html:210-212; app.js:1033-1066 |
| N4 | Error-level events also raise a toast | toast | — | — | on each `error` log | app.js:1113 |

## O. Global feedback and footer

| ID | Label | Kind | Options | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| O1 | Toast | toast (bottom centre, 4.2 s, polite live region) | one at a time | Every short message on the page | on demand | index.html:224; app.js:61-66; style.css:370-381 |
| O2 | "The hub launches each robot's own system; it never replaces one." | footer note | — | — | always | index.html:218-221 |
| O3 | "Enable JavaScript to see the robots." | noscript fallback | — | — | JavaScript off | index.html:306 |

## P. Per-robot-type capabilities (from the adapters)

| Robot type | Connect does | Says on connect | Battery | Speaking key on card | Postures | Add WiFi | Launch opens | Claims laptop resources |
|---|---|---|---|---|---|---|---|---|
| Furhat | Realtime API login, voice check | yes | no (mains) | no | no | no | Furhat Studio `http://{ip}/` (password prompt) | none |
| Reachy Mini (wireless), per unit reachy1-8 | daemon health; notes the app holding the robot; sets volume; wakes up | yes | no | yes | no | yes + lab fallback box | the Reachy page (`group.html`); Talk there runs reachy_chat (robot mic, or the laptop DJI mic when one is plugged in; `mic_mode` auto) | the laptop mic only in laptop-mic mode |
| Reachy Mini Lite (USB) | daemon over USB | yes | no; Link "USB"/"unplugged" | no | no | no | the Lite daemon page (starts Reachy Mini Control) | — |
| NAO | NAOqi identity (head id) | yes | yes | no (NAO_LLM reads its own .env keys) | Sit / Lie down / Stand up | yes | NAO_LLM control panel (local port) | Windows default input mic |
| Pepper | NAOqi identity | yes (silent on auto-reconnect) | yes (shares NAO's adapter) | yes (needs a GPT key; ElevenLabs is exported too) | none | yes | pepper_app dashboard :8780 (scripted demo + free talk, Wizard of Oz, camera, tablet) | none |

A **"Say hi" button does not exist** on the current main page. The only spoken test is the automatic announcement during Connect (F2). The F5 icon marks a robot that failed it.

## Q. Backend features with no control on the main page

| ID | What | Where it is set / reachable | file:line |
|---|---|---|---|
| Q1 | `GET /api/doctor`: environment checks | API only (also `run.ps1 -Doctor`) | main.py:241-245 |
| Q2 | `GET /api/resources`: who holds which mic/port | API only | main.py:236-238 |
| Q3 | `GET /api/log?limit=` | API only | main.py:231-233 |
| Q4 | Per-robot announcement text, display names, per-unit names (reachy1-8) | config.toml | config.example.toml:36-110 |
| Q5 | Reachy `mic_mode` (auto/laptop/robot), `mic_device`, `mic_match`, `robot_mic_match`, `robot_mic_rate`, `volume` | config.toml `[robots.reachy_wireless.settings]` | reachy_wireless.py:18-35 |
| Q6 | Discovery: mdns/usb/netscan on-off, `netscan_interval_s` 5, `netscan_max_hosts` 256, `netscan_nearby_24s` 4, `expected_subnet` | config.toml `[discovery]` | config.example.toml |
| Q7 | `lab_wifi`, `lab_wifi_open`, `hotspot` | config.toml `[network]` | config.py:35-38 |
| Q8 | Server host/port (127.0.0.1:8099) | config.toml `[server]` | config.example.toml |

---

## Flows

1. **First visit.** The page opens and the WebSocket goes "live". The Network setup panel opens by itself and checks the WiFi. If the badge says "needs attention", read the status line, join the lab WiFi, press Check again. Cards appear within about 30 s (or press Scan now).
2. **Add a key.** Open Speaking keys, pick a Provider, optionally type a Label, paste the key, Add key. The toast says "Pick it on a robot's card". The key row shows which robots use it.
3. **Choose what a robot speaks through (its AI backend).** On a Reachy or Pepper card, pick a key in the key select (Gemini or GPT). The log confirms it, and if the robot is running the choice applies at the next Launch. With no choice the default is used (amber).
4. **Connect and launch (Furhat / NAO / Pepper / Lite).** Connect: spinner, the robot says its announcement, the card turns blue (or shows the muted icon if it could not speak). Launch: a waiting tab opens, the button shows "Launching… n s", the card turns green and the tab loads the system. Later presses show "Open", which reopens the tab without restarting.
5. **Reachy.** Connect each Reachy (or turn on Auto-connect). Launch on any Reachy card opens the one Reachy page tab. Talk (1 Reachy), group modes and Choir live there.
6. **Conflict.** Launch is refused and the card shows "Cannot start: … in use by X". Either Disconnect X and Launch again, press Override (logged as OVERRIDE), or press Dismiss.
7. **Launch failure / cancel.** A red "Launch failed: reason" stays on the card. Disconnect during a launch cancels it (up to 50 s).
8. **NAO posture.** Connect. Sit or Lie down (motors off afterwards). Stand up needs a second tap on Confirm within 5 s. A hot joint gives a red refusal with the joint and its temperature; the result sentence names the hottest joint.
9. **Teach a robot a hotspot.** Present card, Add WiFi…, name and password (≥ 8), Join. Up to a minute later the success note appears, the card dims, and the laptop moves to that hotspot. Reachy variant: tick "This is the lab WiFi" to save a fallback without moving.
10. **Lost laptop network.** The red banner and an error toast appear, the range says "off the robots' network", and the setup panel reopens on the next network event.
11. **Robot lost.** The card turns amber (Degraded), then red (Lost). With Auto-connect on it retries with backoff; otherwise press Connect.
12. **Share a file.** Robot files, choose a robot, choose a file, Upload (live seconds). If the name exists, press Upload again to replace. **Get a file:** choose "With {your key}" and Download (live %), or download it "Without a key".
13. **Delete** a key or a file: press the bin, then press it again within 4 s.
14. **Report a problem.** Activity, then Copy, then paste.

## Notes for the new design

**Must stay IN CONTEXT, on or next to the robot / conversation:**
- The per-robot speaking-key / AI-provider choice (G1) belongs on the robot card and wherever a conversation starts. Today the **key implies the provider** (Gemini or GPT), and that choice is made per robot right before Launch. A global "Keys" settings page is fine for adding and deleting keys (L6-L9), but **picking which key or provider a robot uses must not move there**. It should also show the fallback state (G2) and "applies at next Launch".
- Connect / Disconnect / Launch / Open / Launching n s / launch-failed note (F1, F2, J1-J4) stay together on the card.
- The connect announcement result, i.e. the "could not speak" icon (F5), and the live detail line (F6).
- Battery with the low-battery state (F8), status colour per state (8 states), address or USB link.
- NAO posture buttons, the stand-confirm and the heat notes (H1-H4): safety-critical, keep them on the card.
- Add WiFi with the Reachy-only lab fallback checkbox (I1-I7): per robot, keep it on the card (or in a per-robot drawer, never a global page).
- Conflict alert with Override / Dismiss (K1-K3): must appear where Launch was pressed.
- Launch of a wireless Reachy goes to the Reachy conversation page. Its own provider/voice choices are covered by the Reachy page inventory and must be next to the conversation there too.
- Network-lost banner (B1) and the WebSocket "live" pill (A3): always visible.
- Toasts (O1) and the error toasts raised from log errors (N4).

**Could live in a settings or secondary page:**
- Adding and deleting keys (L1-L10), as long as each card still has its key picker and an "add one" link when there are none.
- Network setup guide text (D6-D13). The status badge (D2) and Check again (D4) should remain glanceable, and the panel must still **open automatically on a problem or a first visit**.
- Robot files library (M1-M12): its own tab or page. Keep the per-file "With your key" choice (M6) and the replace-on-second-Upload behaviour.
- Auto-connect (A2) is global and could go in settings, but today it is one click in the top bar and people flip it during a session; keep it reachable from the robots view.
- Activity log (N1-N3): could be a drawer, but Copy must stay.
- Config-only items (Q4-Q8): today they are config.toml only. The new app may expose them in settings (announcement text, Reachy mic mode, discovery range), but that is new, not parity.

**Gaps worth knowing (data exists, nothing shows it):** each card's `mic` and `daemon_version` (F16); `/api/doctor` and `/api/resources` (Q1-Q2). The new design can show them for free. The client-side 8-character password rule (I3) blocks saving an *open* lab WiFi from the card, even though the backend supports open networks (`lab_wifi_open`).

---

## Checker additions

Second pass, line by line, over `web/index.html` (309 lines), `web/app.js` (1143) and `web/style.css` (517). Also read: `hub/main.py`, `hub/core.py`, `hub/keys.py`, `hub/library.py`, `hub/keyscrub.py`, `hub/reachy_wifi.py`, `hub/wifi.py`, `hub/registry.py` and the adapters. I also read the parts of `web/group.js` and `hub/group/conductor.py` that use the main page's key picker. **29 items added (X1-X29) and 6 corrections (C1-C6).**

### Corrections to the inventory above

| ID | Corrects | What is actually true | file:line |
|---|---|---|---|
| C1 | G1 and the summary ("the key chosen decides the robot's AI, Gemini or GPT") | This holds for **Reachy Mini wireless only**. On **Pepper** the chosen key's provider does not switch anything, because Pepper's dashboard always runs GPT Realtime. The picker only decides *which GPT key* goes in. A GPT key picked on the card goes into `OPENAI_API_KEY`; otherwise the hub uses its first GPT key. Picking a Gemini key on Pepper's card changes nothing, yet the default option still reads "Default (first Gemini key)", which misleads on Pepper. With no GPT key at all, the log says "no GPT key in the hub: Pepper's dashboard opens, but the AI conversation and the AI voice need one (Keys panel)". | keys.py:138-163; naoqi.py:813-847; app.js:476-480 |
| C2 | J1 (Reachy wireless Launch) | A Reachy card's Launch only opens `group.html` and never calls the hub, yet it stays **disabled until that Reachy is Connected**. With no Reachy connected, the cards offer no way into the Reachy page. | app.js:157, 1017-1019 |
| C3 | G1, Flow 3 and the Notes (where a Reachy's provider choice applies) | A Reachy card's key reaches the robot **only through solo Talk on the Reachy page**. Talk calls `/api/robots/{key}/launch` (or `/override` on a second press after a conflict), and that call hands over the card's key. **Group modes and Choir ignore the card key.** They use the backend chosen for each seat on the Reachy page and the **first key of each provider** in the hub. So today the AI choice for a Reachy lives in two places: the card (solo Talk) and the Reachy page seats (group). | group.js:464-515; core.py:537-543; conductor.py:4017-4023 |
| C4 | I1 ("Add WiFi… when present") | The hub accepts Add WiFi when the card is Available, Connected, Running or Degraded, so **Connect is not needed**. In Connecting or Lost the button still shows, but the hub answers "{robot} is not on the network". | app.js:193; core.py:583-584 |
| C5 | I3 and "Gaps" (the 8-character rule) | This goes further than "the card cannot save an open WiFi". For a network set up as open, the server refuses any password ("“X” is set up as an open WiFi: leave the password empty"), while the page refuses an empty one. So an **open lab WiFi cannot be saved from the card at all**. | app.js:212; reachy_wifi.py:129-140 |
| C6 | F2 (Connect): the failure path was missing | A failed Connect turns the card **Lost (red)** with "connect timed out" or "connect failed: …". It logs an error, which raises a toast, and with Auto-connect on it schedules a retry. A card whose Connect failed **stays Lost even after the robot answers again**, until a retry or a manual Connect succeeds. A second Connect while one is running is refused with "already working on this robot" (toast). | core.py:331-333, 404-454; app.js:976 |

### Added items

| ID | Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|---|
| X1 | A (top bar) | WebSocket snapshot rebuild | behaviour | on every (re)connect of the page's link | The hub sends a full snapshot. The page **clears every card and the whole Activity log**, then redraws them from the hub (the log gets the last 100 entries). Older lines in the on-page log are lost after a reconnect, but the hub's own log file keeps them (X27). The stamp goes back to "watching for robots…". | each time the pill goes back to "live" | app.js:1097-1108; main.py:326-339 |
| X2 | A | Heartbeat | behaviour | after 20 s without other messages | Keeps the link alive; nothing changes on screen | always | main.py:333-336; app.js:1120 |
| X3 | A | Pill hover "Live connection to the hub"; Auto-connect hover "Connect to each robot automatically as it appears" | tooltips | — | — | hover | index.html:39, 43 |
| X4 | F (card) | Detail line, Reachy wireless wording | live text | "ready" / "ready, control loop {n} Hz" / amber "control loop is reporting errors ({n}) -- the robot usually stops about 7 seconds later" / "daemon is running but the robot backend is not ready" / "daemon reports state '{s}'" / "{daemon error} (state {s})" | Live health from the daemon every 2 s. The errors line turns the card **Degraded about 7 s before the robot stops**. | Reachy cards | reachy_common.py:195-233 |
| X5 | F | **Daemon-too-old warning**, added to the Reachy detail line: "daemon {v} is older than 1.10.0, where `ready` is permanently false -- a desktop-app update can downgrade it silently; re-run the daemon update" | live text (warning) | threshold 1.10.0 | The only place where the page tells a student that a desktop-app update silently downgraded a Reachy's daemon | Reachy card with an old daemon | reachy_common.py:170-179, 226-228 |
| X6 | F | Detail line, Furhat wording | live text | "Studio reports the system running" / "connected; Studio sent no status reply" / "Studio is serving on port 80" / "something answered on port 80 but it is not Furhat Studio" / "Furhat Studio did not answer on {ip} (…)" | — | Furhat card | furhat.py:240-273 |
| X7 | F | Detail line, NAO and Pepper wording | live text | "broker answering" / "broker answering, battery {n}%" / the connection error text | — | NAO, Pepper | naoqi.py:432-444 |
| X8 | F | Detail line **clamped to two lines**, with no tooltip | layout limit | fixed height 2.7em | Long sentences (X5, launch errors in the detail) are cut off on the card; only the Activity log shows them in full. The new design should let the whole text be read. | always | style.css:180-185 |
| X9 | F | Robot picture per type, on a tile tinted per type | image | photos for furhat, reachy_wireless, reachy_lite, naoqi and pepper; tint keyed by type, not position | Each robot type has its own avatar-tile colour. The glyph shows if the photo fails to load. | always | style.css:155-175; web/photos/ |
| X10 | F / J | Card shows a Talk started on the Reachy page | behaviour | — | When Talk on the Reachy page launches a Reachy, **its card shows "Launching… n s"**, then turns green (Running). If the launch fails, the card shows its launch error in red. A Reachy card's button never becomes "Open"; it always opens the Reachy page. | Reachy wireless | app.js:151-181; group.js:491-492 |
| X11 | F / J | Health probe restores or downgrades the state | behaviour | 22 s grace period after Connect | A robot that has a system URL and answers again goes back to Running. One that stops answering within 22 s of Connect shows Degraded "not answering yet (daemon restart?)". After that it shows Lost and logs "{robot} lost: …" (error toast). A Degraded robot that recovers logs "{robot} recovered". | always | core.py:318-365 |
| X12 | F | Disconnect log notes | log lines | "cancelling the launch in flight" / "launch cancelled by Disconnect" / warning "the launch did not stop within 50 s; disconnecting anyway" / warning "disconnect reported …" | Disconnect also clears the muted-mic flag and the posture note (unless NAO is moving) | on Disconnect | core.py:457-496 |
| X13 | G (card key) | Reachy launch refusals caused by the card key | error text (card launch error, toast on the Reachy page) | "the hub has no speaking key yet -- add one in the Keys panel and pick it on this card" / "'{label}' is a {Provider} key, and reachy_chat has no {Provider} speaking backend yet -- pick a Gemini key on this card" | Picking an ElevenLabs, Qwen or OpenRouter key on a Reachy card makes that robot's solo Talk fail | Reachy, at Talk | reachy_wireless.py:458-473 |
| X14 | G | Launch hands over one key per provider | behaviour | GEMINI_API_KEY, OPENAI_API_KEY, ELEVENLABS_API_KEY; the card's key fills its own provider, and the first key of each other provider fills the rest | The robot's own reachy_chat dashboard (and Pepper's) can switch backend or voice mid-session without the hub | Reachy, Pepper | keys.py:42-46, 152-163 |
| X15 | J | First Talk installs the Reachy app | behaviour (log + long launch) | "syncing reachy_chat onto the robot (a few minutes the first time, seconds after that)"; the launch time limit is extended for it | A factory Reachy gets reachy_chat installed by its first Talk, so the timer can run for minutes | Reachy, first Talk | reachy_wireless.py:165, 475-500 |
| X16 | J / P | Connect sets Furhat's voice every time | behaviour (log) | voice from config `voice`, default an English Amazon Polly voice | After a reboot Furhat is back on a Japanese factory voice. Connect switches the voice every time and logs "voice set to X (was Y)", "voice 'X' is not available on Furhat yet" or "Furhat did not confirm the voice change". | Furhat, Connect | furhat.py:65-69, 289-320 |
| X17 | I (Add WiFi) | Reachy results | WiFi note texts | green "{robot} is already on “X”; its password is updated." / green "{robot} saved “X” but cannot see it right now, so it stays on “Y”…" / red "{robot} could not join “X” (wrong password?) -- it is back on “Y”" / red "that is the robot's own setup network" / red "the robot refused sudo -- set REACHY_SSH_PASSWORD" / "a WiFi name has 1 to 32 characters" / "a WiFi password cannot contain a line break" / lab fallback "… as the lab WiFi: its fallback whenever none of its hotspots is on. It stays on “Y” for now." | "Saved but cannot see it" still shows green and closes the form, although the robot did not move | Reachy cards | reachy_wifi.py:129-215 |
| X18 | I | Other WiFi errors | note texts | "Failed ({status})." / "{robot} has no Add WiFi" / "only a Reachy Mini keeps a lab WiFi fallback" | — | after Join | app.js:231; core.py:581-593 |
| X19 | I | WiFi note stays after the form closes | behaviour | — | The green or red note stays under the card after the form closes, until the next Join. The lab box is unticked after a success. | after Join | app.js:224-232 |
| X20 | H (posture) | More posture refusals and failures | note and toast texts | "Request failed: …" / "The hub answered {status}." / "{robot} is launching — wait for it to finish before moving it" / "{robot} is already moving" / "no answer within {n} s — check on it" (posture timeout; the note stays red) | The armed "Confirm" state belongs to one browser page and is not shared. It disarms by itself when the robot is no longer ready. | NAO | app.js:312-343; core.py:615-672 |
| X21 | L (keys) | Key log lines | log | "key added: {label} ({provider}, ...{last4})" / "key removed" / "{robot} will speak through the default key" (after choosing Default again) | — | on key changes | core.py:105-133 |
| X22 | L | Key picker on absent robots | behaviour | — | The picker covers every Reachy and Pepper the hub knows, even when absent. A key assigned to a robot that is off the network is kept for its next Launch. | — | core.py:94-98 |
| X23 | M (files) | **Upload refused when a key cannot be removed** | error text | "{file} contains {where} -- remove it and upload again" / "{file} holds {where} in {entry} -- rebuild it without the key and upload again" | The hub strips keys only from text entries and from `.skill`, `.jar` and `.zip` archives. A key it cannot blank (in compiled code, for example) blocks the upload. When stripping works, the log notes "Files: removed {what} from {file} before upload". | Upload | keyscrub.py:55, 175-210; library.py:228-237 |
| X24 | M | Upload limits | error texts | "GitHub takes files up to 2 GB" / "that file is empty" / "could not read {file}: …" / "upload failed: …" (each is also logged as an error, so it raises a toast) | — | Upload | main.py:277-303 |
| X25 | M | Download errors and cache | error toasts + behaviour | "that key is no longer in the hub" / "{file} has no place for a {Provider} key" / "the download of {file} was cut short…" | The first download of a file comes from GitHub through the hub and can take minutes. After that the hub serves it from a local cache of the last 4 files, and the uploader's own download is instant. | Download | library.py:40-44, 265, 310-332 |
| X26 | M | Smaller file-panel behaviours | behaviour | — | A row's uploader name is the GitHub account that uploaded the file. Upload silently does nothing before the list has loaded or when no robot is chosen. The bin is disabled while a delete runs, then the list reloads. When the keys change, every file row is redrawn and its key choice resets to the first matching key. | files panel | library.py:92; app.js:463, 763-766, 819 |
| X27 | Q (no control on the page) | Daily log file `logs/hub-<date>.log` | file | git-ignored; keys are never logged, only their labels | The whole Activity log, kept on disk, so a failed Launch on another laptop is still traceable after its window closes | hub start | main.py:41-57 |
| X28 | Q | Hub start warms the Reachy group services | behaviour | only on a normal start, not in tests | At hub start the DJI-mic watcher starts, and every service the group conversation uses is warmed up (these are paid API calls). The main page shows none of it. | hub start | main.py:86-93 |
| X29 | Q / O | Per-robot connection settings (config only) | config | Furhat `voice`, `username` (admin), `password`; NAO and Pepper `port`, `speaker_port`, `ssh_user`, `ssh_password`; Reachy `daemon_port`, `robot_dashboard_port`, `ssh_user`, `ssh_password`, `volume`; Lite `daemon_url` | None of these has a control today | config.toml | furhat.py:277-297, 392; naoqi.py:346, 484-485, 727; reachy_wireless.py:209, 242, 410-428, 524; reachy_lite.py:83 |

Also checked, with nothing missing: the page title "Robot Hub", the meta description and the blue favicon (index.html:5-8); animations turn off under the system's reduce-motion setting (style.css:439-441); breakpoints at 1080, 760 and 600 px (style.css:427-438); focus rings on buttons and summaries (style.css:53); app.js has no keydown handlers.

### Notes for the new design (additions)

- **Provider choice lives in two places today, and both must stay in context.** On a Reachy card, the key picker sets the AI for that robot's **solo Talk** (C3). Group modes take the backend from each seat on the Reachy page and the key from the first key of each provider. If the new app puts "Talk with one Reachy" and "group conversation" on one screen, the provider and key picker must sit next to each robot (seat) on that screen. It must not live only on the hub card, and never only in Settings.
- On **Pepper**, the picker should list **GPT keys only** and show which ElevenLabs key Pepper will use. The default option should not say "first Gemini key" (C1).
- Let a student open the Reachy conversation screen **without connecting first** (C2), or make Connect part of that screen.
- Show the whole detail sentence somewhere (X8), and give the Reachy daemon-too-old warning (X5) a visible badge.
- Allow saving an **open** lab WiFi (C5).
- Keep the per-file "With your key" choice next to Download, and the "cannot remove the key" refusal (X23) next to Upload.
