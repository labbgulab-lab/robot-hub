# Reachy page (group conversation): setup-side parity inventory

Read-only inventory of what the current Reachy / group-conversation page offers, so the new design can redraw every control. Nothing here was changed.

**Files read in full**
| File | Lines |
|---|---|
| robot-hub/web/group.html | 290 |
| robot-hub/web/group.js | 1873 |
| robot-hub/web/group.css | 519 (selectors for states and layout) |
| robot-hub/hub/group/api.py | 99 |
| robot-hub/hub/group/conductor.py | 4643 (only settings, defaults, clamps, modes, warm-up, premade, mic, state) |
| robot-hub/hub/group/services.py | 980 (only writer list and voice lists) |
| robot-hub/web/app.js | lines 891-901 only (how the main page opens this page) |

**How people get here:** on the main hub page, a wireless Reachy card's **Launch** opens `/group.html` in one named tab (`robot-hub-group`). A second click brings back the same tab (app.js:893-901). With one Reachy the page offers **Talk** (that robot's own app). With two or more it offers the group modes and Choir.

**What does NOT exist in this page today**, even though the brief lists it: Wizard of Oz mode, saved presets, and a picker for ready-made scripts. The "premade" first lines and the ready-made interjection clips ("Wait, wait, wait!", the "say again?" phrases) are made **automatically** by the backend. They come from Get ready and from conductor.py:4409-4480 and phrases.py. No control picks them. Do not invent controls for them. Keep the automatic behaviour, and keep it visible through the Get ready status text and the checks.

Item IDs (G1...) are for cross-reference. Kinds: button, toggle (checkbox), select, slider, number, text, textarea, chip-list, live display, table, modal, toast, shortcut, link, status indicator.

---

## 1. Top bar (page-wide)

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| G1 | "Group conversation" | heading | - | Page title (browser tab title is the same) | always | group.html:7,20 |
| G2 | save badge: `loading` / `saving` / `not saved yet` / `not saved` / `saved` | status indicator | colours: green = saved, amber = not saved yet or not saved | Says whether the setup is saved on the hub. Settings are kept for next time. | always | group.html:22; group.js:1362-1373 |
| G3 | "Robot Hub" | link | - | Back to the main hub page | always | group.html:23 |
| G4 | dot + `connecting` / `live` / `reconnecting` | status indicator | - | Live WebSocket link to the hub. Reconnects by itself with backoff from 0.5 s up to 10 s. | always | group.html:24-26; group.js:1764-1785 |
| G5 | error banner (alert icon + text) | status indicator (banner) | text is one of: the hub's own error (wins), a refused request, or "This hub has no group conversation yet. Restart the hub with the new code." / "The hub did not answer (...)." | Stays until the cause is fixed | hidden when there is no error | group.html:31-33; group.js:684-688, 1390-1399, 1789-1802 |

## 2. Stage: status, clock and mode buttons

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| G6 | phase label: Not running / Starting / Speaking / Listening / People speaking / Thinking / Stopping / Connected | status indicator | colour per phase: speaking blue, listening and ready green, human amber, stopping pulses | The current phase | always | group.html:46; group.js:101-110, 404; group.css:90-97 |
| G7 | big status line | live display | "<Label> (<robot name>) is speaking" / "<Label> cuts in" / "Listening to the room" / "Waiting for you to talk" (Interrupt) / "The people are speaking" / "You have the floor (for now)" (Interrupt) / "Robots connected: pick a mode" / "Thinking…" / "Starting…" / "Stopping…" / "Running" / "Not running" | Who has the floor, in plain words | always | group.html:47; group.js:374-398 |
| G8 | status detail | live display | "<Mode name> - <detail>", or "<Mode> - closing: each robot says its last word". The detail comes from the hub, for example "getting ready: checking every service", "getting ready: recording the interjections (first time with these voices only)", "ready: press a mode to start", "connected, but X failed the check". | Running mode plus what the hub is doing | hidden when empty | group.html:48; group.js:407-413; conductor.py:4284-4304 |
| G9 | timer `m:ss / m:ss` | live display | elapsed / total. Total = the running limit (minutes plus every +1), else Minutes x 60. | Session clock. Runs only in the live phases (speaking, listening, human, thinking). Redraws twice a second. | always | group.html:51-53; group.js:420-435, 722 |
| G10 | timer bar | live display (progress) | turns amber when over time | Share of the time used | always | group.html:58; group.js:432-434; group.css:112-114 |
| G11 | `+1` | button | +60 s per press; backend caps each press at 600 s | Adds a minute to the running conversation. The saved Minutes setting does not change. Error toast: "Could not add time: ...". | enabled only while running, not while closing, not while a +1 is on its way | group.html:54-55; group.js:550, 632-644; api.py:48-51; conductor.py:4578-4586 |
| G12 | `Get ready` / `Getting ready…` | button | turns green ("done") when connected and every check is OK | Saves any pending edits, connects the robots, checks every service with a real request, makes and voices the first line of each of the three modes ahead of time, and records the interjection clips if needed. After that, a mode button speaks at once. Error: banner and toast "Could not get ready: ...". | disabled while starting, while getting ready, while the hub is warming up, while running, or with fewer than 2 included robots (unless Simulate is on) | group.html:60; group.js:535-540, 646-662; conductor.py:4267-4305, 4430-4455 |
| G13 | `Talk` with sub-line `one robot, its own app` / `starting its app…` / `in use: press to take over` / `open its app` | button | - | One Reachy only. Opens a new tab ("Starting X's app…"), then starts that robot's own app, reachy_chat (Gemini Live and the other voices, persona, Show mode). If the app already runs, it opens it. On a conflict the second press takes over. Toasts: the conflict message plus "Press Talk again to take it over.", "The robot's app did not start.", "Talk failed: ...", "The browser blocked the new tab. Allow pop-ups for the hub." | shown only when exactly one real Reachy is available and Simulate is off. Disabled while busy, while a mode is starting, or while the group session is connected or running (tooltip then says "Disconnect first: the group conversation is holding the robot.") | group.html:63-65; group.js:439-515 |
| G14 | `Group talk` / sub `robots + people` | button (mode) | sub-line changes: `connecting…` / `starting…` / `running` / `switch to this` | Robots debate the topic, and people join in at any time. Talking over a robot cuts it off. While another mode runs, this switches at once. | disabled while starting, with fewer than 2 included robots (unless Simulate), or when this mode is already the active one (shown green) | group.html:66-68; group.js:524-534, 1650-1676 |
| G15 | `Interrupt mode` / sub `they cut you off` | button (mode, orange) | as G14 | A person talks about the topic and the robots cut in to argue, cheer, mock or correct. How often depends on each robot's Interrupting level. | as G14 | group.html:69-71; group.css:182 |
| G16 | `Free talk` / sub `chat about anything` | button (mode, teal) | as G14 | No topic and no sides. The robots chat freely, follow the room and start their own subjects. | as G14 | group.html:72-74; group.css:191 |
| G17 | `Stop` / `Stop now` / `Stopping…` | button (red) | first press: graceful stop; while closing: `Stop now` | First press: the robot that is talking finishes, then every robot says a closing line and goodbye. A second press stops at once. The robots stay connected. Error: "Could not stop: ...". | enabled while running or starting | group.html:75; group.js:543-549, 1691-1707; api.py:39-46 |
| G18 | `Disconnect` | button | - | Releases the robots. It is needed only to change the seats (order, Included, Listens, adding or removing robots). Error toast: "Could not disconnect: ...". | enabled when connected | group.html:76; group.js:551, 1678-1689 |
| G19 | `Mic: ...` | status indicator | "Mic: DJI mic · signal ok" (green) / "Mic: DJI mic · <health>" (amber; health is stalled, flat or closed) / "Mic: the robots' own (reachyX, ...) · DJI mic plugged in" / "Mic: DJI mic plugged in (used when the robots connect)" / "Mic: no DJI plugged in · the robots' own mics" | Who hears the people right now. A dead or unplugged DJI switches to the robots' mics by itself. | always | group.html:80; group.js:572-598; conductor.py:1330-1352 |
| G20 | `Use robots' mics` / `Use the DJI mic` | button | toggles between the DJI mic and the robots' mics | Switches the mic at once, also mid-conversation. Error toast: "Could not switch the mic: ...". | shown only when connected and a mic is in use. Hidden when the robots' mics are in use and no DJI is plugged in. Disabled while switching. | group.html:81; group.js:592-597, 664-676; api.py:63-67 |
| G21 | start hint | live display | "Robots connected and listening. A mode button starts at once." / "One Reachy: Talk starts its own app. For the group modes, include a second Reachy or press + on its card for a laptop robot." / "Include at least two Reachys, or press + on a card to add a laptop robot." (amber) / "Simulation: this laptop speaks and listens." / "Not connected: reachyX, ..." (amber) / "N Reachys at the table." | Guidance before a start | text empty while running or starting | group.html:82; group.js:553-567 |
| G22 | checks pill: `N checks ok` / `checking d/N` / `K failed: <names>` | button (expander) | green when all OK, red when any failed | Opens or closes the check list (G23). It opens by itself when a check fails. | hidden until a check exists (checks also run on their own at hub start) | group.html:83-84; group.js:602-629 |
| G23 | check list | chip-list | one chip per service: "OpenAI", "Writer <model id>" (each writer the robots use, plus the racers gpt-oss-120b and gemini-3.5-flash-lite through OpenRouter), "Hearing (speech to text)", "Voice of <label>" (each distinct ElevenLabs voice), "Voice detection" (not in Simulate). Chip text: "<name> 1.2 s" or "<name>: failed", with the error detail in the tooltip. | Shows the result of every service checked with a real request | hidden until opened (opens itself on failure) | group.html:86; group.js:616-623; conductor.py:4339-4396 |

## 3. Conversation panel (around the conversation)

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| G24 | "Conversation (N)" | live display | N = lines said (notes are not counted) | Count of lines | count hidden at 0 | group.html:93; group.js:1525-1526 |
| G25 | `Jump to latest (N new)` | button | - | Scrolls to the newest line. Auto-follow stops when the user scrolls up and comes back after 20 s or at the bottom. | shown only when scrolled up and new lines came in | group.html:94; group.js:1483-1498, 1528-1534, 1614-1629 |
| G26 | transcript line, robot | table/list row | fields: speaker label (the name it had when it spoke), the real robot name tag (when it differs), gesture or move name, latency "NNN ms", time "m:ss", text; a pending line shows "…"; a line that was cut off gets struck through plus "(cut off)"; the line being spoken now is highlighted; left border in the seat's colour | One robot line | always (newest at the bottom) | group.html:96; group.js:1564-1612; group.css:232-238 |
| G27 | transcript line, people | list row | "People", time, text, "listening…" while pending; amber styling | What the room said | - | group.js:1592, 1609 |
| G28 | transcript note | list row | time + text (for example "operator: <steer>", "Group talk started", "the seats changed: reconnecting the robots", mic switches, service fallbacks) | System or operator notes | - | group.js:1580-1586; conductor.py:4191, 4223 |
| G29 | "Nothing said yet. Press a mode when everyone is seated." | empty state | - | - | while the transcript is empty | group.html:97 |
| G30 | people-live line | live display | the last 160 characters of what the person is saying, typed out with a cursor; earlier words are corrected in place | Live caption of the speaker in the room | only while running and someone speaks | group.html:99; group.js:693-719 |
| G31 | `Steer` + text field (placeholder "e.g. make them argue about it, or ask the people a question") + `Send` | text + button (form) | backend keeps up to 300 characters | Tells the robots what to do next. The next line follows it, then the debate goes on. Also written to the transcript as "operator: ...". Toasts: "Sent. The next line follows it." / "Not sent: ...". Enter sends. | always enabled (Send is disabled while sending) | group.html:100-106; group.js:1724-1743; conductor.py:4189-4193 |
| G32 | "Last steer: <text>" | live display | - | Echo of the last steer sent | after the first steer | group.html:107; group.js:1733-1734 |

## 4. Robots panel header (table-wide robot controls)

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| G33 | "Robots" + sub-line | heading + live display | disconnected: "left to right, as the people see the table. Everything here changes at once, also mid-conversation."; connected: "... Order, Included and Listens are fixed until Disconnect; everything else changes at once." | Explains what is locked | always | group.html:113-114; group.js:766-768 |
| G34 | save note: "Saving shortly…" / "Saving…" / "Saved." / "Not saved: <reason>. Trying again…" / "Not saved: <reason>" | status indicator | - | Autosave state. Typing saves after 0.7 s, a click after 0.15 s. A failed save retries every 3 s. A refusal (409) puts back the hub's version. | always | group.html:115; group.js:135-136, 1360-1475 |
| G35 | groups summary | live display | "all robots as one voice" (Choir) or "Group 1 (3), Team B (2)" | Which groups are set | empty when there are no groups | group.html:116; group.js:1182-1191 |
| G36 | `Choir` / `Choir: on` | toggle button | - | Every robot at the table says the same line at the same moment and moves the same way. Robots ticked later join too. Takes effect from the next Start. Toasts: "Choir on: ...", "Choir off: every robot is on its own (from the next Start).", "Choir needs at least two included robots." | always | group.html:117-118; group.js:1283-1287 |
| G37 | `Groups…` | button | - | Opens the Groups dialog (G83-G93) | always | group.html:119-120; group.js:1270-1282 |
| G38 | "No Reachys yet. Connect them on the Robot Hub page and they appear here." | empty state | - | - | when there are no robots | group.html:123; group.js:858 |
| G39 | card grid layout | layout | all side by side up to 5 robots, then two rows; compact cards from 4 robots on; the page grows past 5 | - | - | group.js:849-856; group.css:40, 279 |

## 5. Per-robot card (one per robot; every value is PER ROBOT)

Scope: each card is one seat (a real Reachy, or a laptop robot `sim:1`...`sim:5`). A robot the hub sees but has no saved seat for still gets a card. It is Included if connected, with Listens on (group.js:306-314).

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| G40 | seat number `1..N` | live display | - | Position at the table, left to right as the people see it | always | group.html:222; group.js:891 |
| G41 | seat colour (top border, transcript lines) | status indicator | 6 colours, kept per robot while the page is open | Matches a card to its transcript lines | always | group.js:132-134, 354-365, 889 |
| G42 | Label (placeholder "Reachy Mini 1") | text | max 30 characters. Defaults "Reachy Mini 1..5" (backend DEFAULT_CHARACTERS). Empty keeps the old label. | The robot's label in the transcript and for the writer. It is never said aloud. Live. | always | group.html:223-224; group.js:1031-1034; conductor.py:211-224, 957-959 |
| G43 | "Another robot has this label." | inline warning | - | Two included robots with the same label (case-insensitive). Start is then refused: "two robots are called X: give each its own name". | when a duplicate exists | group.html:226; group.js:926-928; conductor.py:4220-4225 |
| G44 | real robot name (e.g. reachy6) | live display | - | The robot's own hub name | hidden when the label is the same name | group.html:230; group.js:894-898 |
| G45 | group tag | status indicator | group name in the group's colour; the tooltip says the kind | Which group the robot is in | only when its group has 2 or more included robots and this robot is included | group.html:231; group.js:900-908 |
| G46 | connection state | status indicator | Absent / Available / Connecting / Connected / Running / Degraded / Lost / Unavailable / Not connected; blue when connected | The robot's hub state | always | group.html:232; group.js:89-99, 910-913 |
| G47 | mic level bar | live display (meter) | 0-1, about 8 updates a second; greyed ("deaf") when Listens is off. Tooltip: "Echo check: its own voice peaked X dB over the learned echo (keep well under 8 dB for Normal)." | This robot's microphone level and echo health | always; drops to 0 after 1.5 s without data | group.html:233; group.js:726-740, 915-922 |
| G48 | `‹` Move left | button | - | Moves the seat one place left | disabled while connected, or on the first seat | group.html:235; group.js:937, 1091-1105 |
| G49 | `›` Move right | button | - | Moves the seat one place right | disabled while connected, or on the last seat | group.html:236; group.js:938 |
| G50 | `+` Add a robot | button | up to 5 laptop robots | Adds a laptop robot (it speaks through this laptop's speaker) right after this card. The hub gives it a label, position and voice. | hidden in Simulate. Disabled while connected ("Disconnect first to add a robot") or when 5 already exist ("No more robots fit"). | group.html:237; group.js:941-947, 1058-1073 |
| G51 | `×` Remove | button | - | A laptop robot is deleted. A real Reachy only leaves the table (Included is unticked). | hidden in Simulate. Disabled while connected, or on a real Reachy that is already excluded. | group.html:238; group.js:942-949, 1075-1089 |
| G52 | Included | toggle | default: on when connected | The robot takes part in the conversation. Unticking it keeps it connected to the hub. A dimmed card means it is excluded. | disabled while connected (fixed until Disconnect) | group.html:242; group.js:930-935, 1025-1030 |
| G53 | Listens | toggle | default on; laptop robots off | Its mic hears the people when the DJI mic is not in use | disabled while connected | group.html:243 |
| G54 | Camera | toggle | default on (from the session default `vision: true`) | It can look through its camera when someone asks what it sees. It never comments on the room unasked. Live. | always | group.html:244; group.js:1038-1039 |
| G55 | Personality | textarea | max 800 characters. Defaults: "Optimistic about the topic...", "Skeptical...", "Precise: brings facts and numbers...", "Playful: light humor...", "Turns to the people...". | The robot's position on the topic and how it argues. Applies from the next line. | always | group.html:246-249; conductor.py:211-224, 960-961 |
| G56 | Voice provider | select | Auto / ElevenLabs / OpenAI / OpenRouter / Gemini (daily cap); "(no key)" is added when the hub has no key for it; default Auto | Which service speaks for this robot. Auto means ElevenLabs while it has credits, else OpenAI. The voice never changes mid-line. | always | group.html:252-253; group.js:114-115, 953-956, 1040-1041 |
| G57 | Voice | select | the list depends on the provider. ElevenLabs/Auto: "Default (<name>)" plus the account's male voices; an unknown saved voice shows "<id> (not in the list)"; with no key, "Default (no ElevenLabs key)". OpenAI: male voices (ash, ballad, cedar, echo, fable, onyx, verse). OpenRouter: ash, ballad, cedar, echo, verse. Gemini: male voices from GEMINI_VOICE_LIST. A saved voice the provider lacks shows "<id> (not here: uses Default)". | The voice itself. Each provider keeps its own saved voice (voice_id / openai_voice / gemini_voice). | always | group.html:254-255; group.js:123-126, 863-884, 1042-1043; services.py:892-910; conductor.py:4031-4040 |
| G58 | Writer | select | Gemini 3.5 Flash (smart, ~2.5 s) [default] / gpt-oss-120b (fastest, ~1.2 s) / GPT-5.4 mini (~2.8 s) / GPT-4.1 mini (OpenAI key) / Flash-Lite (Gemini key). The backend also accepts a direct `gpt-5.4-mini`, shown as its raw id if saved. | The AI model that writes this robot's lines. The first robot's writer is also the table's writer (races, hearing). | always | group.html:258-260; group.js:118-122, 960-961; services.py:49-50; conductor.py:4012-4015 |
| G59 | Interrupting 0 1 2 3 4 5 | segmented radio | default 3. Tooltips: 0 never, 1 rarely, 2 now and then, 3 regularly, 4 often and piles on, 5 every time. The backend cuts in after about 12 / 8 / 5 / 3.2 / 2.2 s of talking (±25%). Levels 2-5 sometimes defend the person; 4-5 pile on. | How often this robot cuts in, in Interrupt mode | always | group.html:261-270; group.js:963-968, 1001-1002; conductor.py:143-146 |
| G60 | Gestures: Lively / Calm | segmented radio | default Lively | Lively: moves on almost every line and reacts while others talk. Calm: moves on about half of its lines and rarely reacts. | always | group.html:271-276; group.js:969-973 |
| G61 | Volume slider + "150%" | slider | 0-250, step 5, default 150 | 100 is the natural level. The speaker is already at its maximum, so above 100 the hub boosts the audio. It is saved when the drag ends. | always | group.html:277-279; group.js:975-979, 1046-1051 |
| G62 | "Voice: ElevenLabs, writing via OpenRouter" | live display | - | What the robot uses right now (the hub falls back when a key fails) | only while connected | group.html:281; group.js:981-989 |
| G63 | `Copy to others` | button | - | Opens the Copy dialog (G94-G98) | disabled with fewer than 2 robots | group.html:282; group.js:990, 1306-1325 |
| G64 | speaking highlight | status indicator | blue ring | The card of the robot that has the floor lights up | while that robot speaks | group.js:679-682; group.css:285 |
| G65 | excluded dimming | status indicator | - | A card that is not Included is dimmed | when Included is off | group.js:890; group.css:287 |

## 6. Session settings (shared by the whole table)

| ID | Label as shown | Kind | Options / range / default | What it does | Live while running? | file:line |
|---|---|---|---|---|---|---|
| G66 | Topic (placeholder "What they talk about (empty: they choose)") | text | max 500 characters; default empty | What the robots debate. Each robot's side is in its Personality. Empty means the robots pick a topic. | yes | group.html:128-131; conductor.py:3940 |
| G67 | Language | select | Auto / Hebrew / English (an unknown saved value is shown as-is); default Auto | Auto follows the language the people spoke last | yes | group.html:132-134; group.js:100, 747-748 |
| G68 | Minutes | number | page 1-60, step 1; backend 0.5-60; default 5 | How long a conversation lasts. Every robot says a closing line at the end. | yes | group.html:135-137; conductor.py:3943 |
| G69 | Gap (s) | number | page 0-5, step 0.1; **backend clamps to 0.2-3.0**; default 0.6 | Silence after a robot line before the next robot speaks | yes | group.html:138-140; conductor.py:3944 |
| G70 | Voice threshold | number | 0-0.9, step 0.05; default 0.3; 0 = off | On the mic-meter scale, a quieter voice does not take the floor | yes | group.html:141-143; conductor.py:3945 |
| G71 | People cut in | select | Off (only in the gaps) / Careful / Normal [default] / Eager. The backend needs 14 / 10 / 7 dB over the robot's echo; Interrupt mode forces at least 12 dB when Off. | How easily a person talking over a robot cuts it off | yes | group.html:144-151; conductor.py:69, 4004-4008 |
| G72 | Audience mic | select + level meter | "Auto (DJI mic, plugged in)" or "Auto (DJI mic when plugged in)" [default] / "Robots' own mics" / each laptop mic by a friendly name ("DJI mic", "Laptop's built-in mic", ...) / a saved mic that is missing: "<name> (not plugged in)". The meter shows the audience mic level. | Where the audience is heard. A change reconnects the robots at the next start. | **no**: disabled while running | group.html:152-158; group.js:776-799 |
| G73 | Lab intro | toggle | default on | Group talk opens with every robot saying one line about the lab (from Pepper's lab facts). The first robot hands over to the topic. | yes | group.html:160; conductor.py:175, 2729 |
| G74 | Slow network | toggle | default on | Voice audio comes compressed (OpenAI and ElevenLabs only), for slow links such as the hotspot | yes | group.html:161-162; conductor.py:4011 |
| G75 | Heads turn the other way | toggle | default off | Mirrors head turns if the robots look away from whoever is speaking | yes | group.html:163-164 |
| G76 | Simulate on this laptop | toggle | default off | No robots needed: every robot talks through the laptop speaker and listens through its mic, for rehearsing. It hides `+`/`×` and Talk, and the modes then need only 1 seat. | **no**: disabled while connected; the backend refuses a switch while running | group.html:165-166; group.js:757-758; conductor.py:3882-3884 |
| G77 | "ElevenLabs credits: 12,345" (+ " (low: robots on Auto use OpenAI)" in amber below 1500) | live display | - | ElevenLabs balance and the automatic fallback | shown when credits are known | group.html:168; group.js:760-764; conductor.py:186 |

Hidden session defaults (no own control, used as each new robot's defaults): `voice_provider` auto, `director_model` google/gemini-3.5-flash, `interrupt_level` 3, `vision` true, `gestures` lively, `groups` [], `laptop_seats` (set by `+`/`×`). See group.js:138-142 and conductor.py:167-180, 943-951.

## 7. Toasts, shortcuts and tooltips

| ID | Label as shown | Kind | What it does | file:line |
|---|---|---|---|---|
| G78 | toast area | toast | One message at a time, 4.2 s. The messages are listed with their controls above, plus "Copied to X, Y.", "Pick at least one robot and one setting.", "Interrupting N (<words>) for every robot." | group.html:216; group.js:186-191 |
| G79 | keys `0`-`5` | shortcut | Set **every** robot's Interrupting level at once, mid-demo. Ignored while typing or while the Copy dialog is open. | group.js:1709-1722 |
| G80 | `Escape` | shortcut | Closes the Groups or Copy dialog | group.js:1300-1302, 1354-1356 |
| G81 | `Enter` in Steer | shortcut | Sends the steer | group.html:105 |
| G82 | help tooltips on every control | tooltip | A quick tooltip (300 ms) replaces the browser one. Every control carries its explanation text, including texts the code sets later (Talk, Stop, mic, echo, audience mic). | group.js:1810-1873 |

## 8. Groups dialog (modal)

| ID | Label as shown | Kind | Options / range / default | What it does | file:line |
|---|---|---|---|---|---|
| G83 | "Groups" + help paragraph | modal | - | Explains talk-together (one voice, the first robot's voice and settings, the group's name) and move-together. Changes apply from the next Start. | group.html:173-178 |
| G84 | "No groups: every robot is on its own." | empty state | - | - | group.html:178; group.js:1196 |
| G85 | group name (placeholder "Group N") | text | max 30 characters | The group's name in the transcript and for the writer | group.js:1201-1209; conductor.py:855 |
| G86 | what it does together | select | Talk and move together [default for new groups] / Talk together, each moves its own way / Move together, each says its own lines | Sets the group's talk and move flags | group.js:145-146, 1210-1222 |
| G87 | `×` Remove group | button | - | Its robots go back to being on their own | group.js:1223-1227 |
| G88 | member checkboxes (one per robot: label + real name) | chip-list / toggles | a robot is in at most one group. Ticking a robot that is in another group moves it (marked "taken", with a tooltip). An excluded robot has the tooltip "Not included in the conversation: it sits this one out." Ticking by hand turns a Choir into a normal group. | Group membership in seat order | group.js:1230-1256 |
| G89 | "Needs two included robots to count." / "Talks in X's voice and settings." | inline note | - | Validity and whose voice the group uses | group.js:1258-1265 |
| G90 | `Add group` | button | max 12 groups (backend) | Adds an empty group | group.html:180; group.js:1288-1292; conductor.py:856 |
| G91 | `Everyone: one Choir` | button | - | Replaces all groups with one whole-table Choir (needs 2 included robots) | group.html:181; group.js:1293-1296 |
| G92 | `No groups` | button | - | Clears all groups | group.html:182 |
| G93 | `Done` / click on the backdrop / Escape | button | - | Closes the dialog. Edits are already saved. | group.html:183; group.js:1298-1302 |

## 9. Copy settings dialog (modal)

| ID | Label as shown | Kind | Options / range / default | What it does | file:line |
|---|---|---|---|---|---|
| G94 | "Copy <label>'s settings" | modal | - | Copies from the robot whose button was pressed | group.html:189-191; group.js:1306-1325 |
| G95 | To: one checkbox per other robot | toggles | all ticked by default | Target robots | group.js:1312-1321 |
| G96 | What: Interrupting (0-5) ✓, Voice provider ✓, The voice itself ☐, Writer ✓, Gestures ✓, Camera ✓, Volume ✓, Personality ☐ | toggles | ticked as shown | The fields to copy ("The voice itself" copies all three saved voices) | group.html:197-207; group.js:1340 |
| G97 | `Copy` | button | - | Applies the copy and saves. Toast: "Copied to ...". With nothing picked: "Pick at least one robot and one setting." | group.html:211; group.js:1334-1351 |
| G98 | `Cancel` / backdrop / Escape | button | - | Closes the dialog | group.html:210; group.js:1352-1356 |

## 10. Behaviour rules the design must keep (not controls, but visible)

| ID | Rule | file:line |
|---|---|---|
| G99 | Autosave: no Save button. Every edit saves itself. A start or Get ready first waits for the save. A failed save blocks the start with "The setup could not be saved, so the conversation did not start." | group.js:1380-1388, 1650-1660 |
| G100 | While **running**, only the live session keys are sent (topic, language, minutes, gap, mirror, threshold, cut-in, slow network, lab intro, groups). Audience mic and Simulate wait. | group.js:127-129, 1415-1420 |
| G101 | While **connected**, order, Included, Listens, `+` and `×` are locked. Every other per-robot field (label, personality, provider, voice, writer, level, gestures, camera, volume) is live. | group.js:888, 934-949; conductor.py:202-205 |
| G102 | Groups and Choir save at once but take effect from the **next Start** | group.js:1189; conductor.py:3926-3928 |
| G103 | Changing the topic, language, lab intro, any seat's label, personality, provider, voice, writer or level, or the groups, throws away the first line made ahead and remakes it 3 s later | conductor.py:3949-3950, 4409-4422 |
| G104 | A mode button while another mode runs switches at once (stop, then start) | conductor.py:4195-4207 |
| G105 | Start refusals shown in the banner: "include at least two connected Reachys", "no seats are included", "two robots are called X...", "the hub needs an OpenRouter, OpenAI or Gemini key (Keys panel on the main page)", "stop the conversation to switch simulation", "stop the conversation to add or remove robots" | conductor.py:3882-3890, 4210-4229 |
| G106 | A changed seat set reconnects the robots at the next Start (transcript note: "the seats changed: reconnecting the robots") | conductor.py:4230-4234 |

**Total: 106 items** (G1-G106).

---

## Flows

1. **Open:** main hub, Reachy card, Launch. The Reachy page opens in its named tab. The WS indicator goes from "connecting" to "live", and the badge from "loading" to "saved".
2. **One Reachy:** only one real Reachy is available, so the Talk button shows. Talk opens a new tab, starts or opens that robot's reachy_chat app, and on a conflict says "Press Talk again to take it over".
3. **Set the table (before connecting):** tick or untick Included and Listens, reorder with ‹ ›, add laptop robots with `+` (up to 5), remove with `×`. Fix any duplicate-label warning.
4. **Per robot:** label, personality, voice provider, then voice (the list changes with the provider), writer, interrupting 0-5, gestures, camera, volume. Optionally use "Copy to others", which opens the dialog where you pick targets and fields and press Copy.
5. **Groups:** either the Choir toggle, or Groups…: Add group, name it, pick the kind, tick the members, Done. The summary and the card tags update. They take effect at the next Start.
6. **Session:** topic, language, minutes, gap, voice threshold, people cut in, audience mic, lab intro, slow network, heads mirror, simulate. Check the ElevenLabs credits note.
7. **Get ready:** the edits save, the robots connect, and the status detail shows "getting ready: checking every service". The checks pill fills ("checking d/N", then "N checks ok" or "K failed: ..."). The first lines of all three modes are made and voiced, and the interjections are recorded the first time with new voices. "ready: press a mode to start" appears and the button turns green.
8. **Start a mode:** Group talk, Interrupt or Free (the sub-line shows "connecting…"/"starting…", then "running"). The clock runs, the transcript fills, the speaking card lights up, the people-live caption types, and the mic line shows who listens.
9. **During:** change any live per-robot setting (provider, voice, writer...) mid-conversation, steer (Enter), press +1, use the mic switch, press 0-5 to set every robot's interrupting level, or switch to another mode at once.
10. **End:** Stop (closing lines, and the button becomes "Stop now"), then Stop now if needed. The robots stay connected and the first lines are made again. Disconnect to change the seats.
11. **Rehearse without robots:** tick Simulate (only while disconnected), then press a mode. The laptop speaks and listens.

## Notes for the new design

**Must stay IN CONTEXT, on the robot card or next to the conversation (the user's explicit complaint):**
- Per robot, on its card: **Voice provider + Voice** (G56-G57), **Writer/LLM** (G58), Personality, Label, Interrupting 0-5, Gestures, Camera, Volume, Included, Listens, the order arrows, `+`/`×`, Copy to others, and the live "Voice: X, writing via Y" line. These are per-robot and live mid-conversation. A global Settings page would break both.
- Next to the mode buttons: Topic, Language, Minutes and Lab intro. They change what the next start says. Topic and Language are also live.
- On the stage: Get ready with its checks pill and list, Talk (one Reachy), the 3 mode buttons, Stop / Stop now, Disconnect, +1, timer and bar, the mic state line plus the mic switch, the start hint, and the status line and detail.
- Under the transcript: Steer and "Last steer".
- Robots header: Choir toggle, Groups…, groups summary, save state.
- The ElevenLabs credits note belongs near the voice pickers, because it explains why Auto falls back.

**Could move to an "Advanced / room" drawer that is still on this page (not a separate Settings page):** Gap (s), Voice threshold, People cut in, Audience mic, Slow network, Heads turn the other way, Simulate. They are tuned per room or network, not per conversation. Keep them one click away, because Audience mic and People cut in are adjusted on the day of a demo.

**Must not be lost:**
- the explanatory tooltip on every control (G82)
- the lock rules and their wording (G33, G101)
- the autosave badge (G2, G34)
- the 0-5 keyboard shortcut (G79)
- per-seat colours shared by cards and transcript (G41)
- transcript latency, gesture name and "(cut off)" (G26)
- the echo dB tooltip on the mic meter (G47)
- the "(no key)" and "(not in the list)" option suffixes (G56-G57)
- the empty states (G29, G38, G84)


---

## Checker additions

A second pass read group.html (290 lines), group.js (1873) and group.css (519) line by line, plus api.py (all 99 lines) and the parts of conductor.py and services.py named below. Items C1-C33 are missing from the inventory above. Corrections to items already listed come first (X1-X7). Nothing in the project was changed.

### A. Corrections to items above (read these first)

| Ref | What the inventory says | What the code does | file:line |
|---|---|---|---|
| X1 (G8, flow 7, the "does NOT exist" note) | While Get ready runs, the status detail shows "getting ready: checking every service", "recording the interjections…", "ready: press a mode to start" and "connected, but X failed the check". | **The page never shows these texts.** The expression `A or phase === 'ready' ? '' : detail` is read as `(A or ready) ? ''`, and Get ready sets every one of those details with phase `ready`. So the big line only says "Robots connected: pick a mode". Get ready progress is visible only as the button text "Getting ready…", the checks pill and the green "done" button. A failed check after Get ready shows only on the pill, not as "connected, but X failed". The hub does send the texts, so the new design can show them (a step line under Get ready). | group.js:408-409; conductor.py:4283-4304 |
| X2 (G31) | Steer is always enabled. | It is enabled at any time, but a steer sent **before** a mode starts is thrown away at Start (`pending_nudge` is reset). Only the "operator: …" note stays. A steer is used for **one** line, then cleared. Empty or whitespace-only text is not sent; the field just gets the focus. | conductor.py:4189-4193, 4204, 3187-3193; group.js:1726-1727 |
| X3 (G79) | Keys 0-5 are ignored while typing or while the Copy dialog is open. | They are also ignored whenever the focus is on **any** input, select or textarea (a checkbox, the Volume slider, a select), and with Ctrl, Alt or Meta held. They are **not** blocked while the Groups dialog is open. They do nothing when there are no seats. | group.js:1711-1716 |
| X4 (G43) | Two included robots with the same label make Start refuse. | The page warns about any two included robots with the same label. The hub refuses only duplicates among the **speakers**, so robots inside one talking group may share a label without a refusal (the warning still shows). | group.js:926-928; conductor.py:4218-4225 |
| X5 (G57) | OpenAI/OpenRouter/Gemini list voice names. | Each option reads "id (description)", for example "ash (male)", "onyx (male, deep)", "fable (male, British)". Gemini's male list is Achird, Algenib, Algieba, Alnilam, Charon, Enceladus, Fenrir, Iapetus, Orus, Puck, Rasalgethi, Sadachbia, Sadaltager, Schedar, Umbriel, Zubenelgenubi. For these three providers the first option is also "Default (<that robot's default voice id>)", taken from the seat's `default_voices`, as it is for ElevenLabs. | conductor.py:4034-4041; services.py:892-913; group.js:876-879 |
| X6 (G22-G23) | A chip reads "<name> 1.2 s" or "<name>: failed". | A check that is still running reads "<name> 0.0 s" with no colour (there is no pending state). When a failure opens the list by itself, the pill's aria-expanded stays "false". | group.js:615-621 |
| X7 (G66, G55) | Topic and Personality shape the conversation. | They are **mode-dependent**. In Free talk, Topic is ignored and **every card's Personality is ignored**: each seat gets a fixed free-talk personality by position (see C20). With an empty topic, Group talk uses "Anything the robots find interesting; start somewhere surprising." and Interrupt uses "Whatever the person wants to argue about." | conductor.py:440-451, 2558, 3041-3058, 3110 |

### B. Missing items

| ID | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| C1 | transcript note "+1 min: it now ends at m:ss" | transcript note | - | Written each time a +1 is accepted | after each +1 | conductor.py:4587 |
| C2 | +1 refusals: "no conversation is running", "the robots are already saying goodbye" | toast text ("Could not add time: …") | - | Why +1 did nothing | on a refused +1 | conductor.py:4582-4585 |
| C3 | Get ready refusal "could not connect the robots: <error>" | banner + toast | - | The connection failed. The hub then **disconnects** everything again. | on a failed connect | conductor.py:4276-4281 |
| C4 | Mic switch refusals "connect the robots first" / "unknown mic" | toast | - | Why the mic did not switch | on a refusal | conductor.py:4078-4086 |
| C5 | Start refusal "unknown mode '<x>'" | banner | modes: group, interrupt, free | - | - | conductor.py:54, 4198-4199 |
| C6 | Interrupting picker tooltip, for example "3: cuts in regularly (interrupt mode)" | tooltip (live) | follows the chosen level | Says the current level in words, and that it applies to Interrupt mode only | always | group.js:968 |
| C7 | Volume tooltip "100 = natural level; the robot's speaker is already at its maximum, above 100 the hub boosts the audio" | tooltip | - | Explains the 0-250 scale | always | group.js:979 |
| C8 | Audience mic tooltip (live): "Hearing the audience through the <mic>" / "Hearing the audience through the robots' mics" / "Used when the robots connect" | tooltip (live) | - | Says which mic actually hears the room, as opposed to the one chosen | always | group.js:795-798 |
| C9 | `+` / `×` tooltips (live): "Add a robot here (it talks through this laptop's speaker)" / "No more robots fit" / "Disconnect first to add a robot"; "Remove this robot" / "Take this Reachy off the table (tick Included to bring it back)" / "Disconnect first to remove a robot" | tooltip (live) | - | The button explains its own disabled state | always | group.js:946-949 |
| C10 | Groups summary tooltip "Groups. Used from the next Start." | tooltip (live) | the "Used from the next Start." part appears only while running | - | when groups exist | group.js:1189-1190 |
| C11 | Talk's loading tab: title "Starting <robot>…", body "Starting <robot>'s app… This tab opens it as soon as it is ready." | live display (new tab) | - | The tab opens inside the click (so it is not blocked as a pop-up), then goes to the robot's app. It closes itself on failure. | after pressing Talk | group.js:468-480, 499, 507 |
| C12 | Talk's "already running" path | behaviour | - | Before starting, it asks `/api/robots`. If that robot is already RUNNING, it opens its `system_url` and does not start it again. After a conflict, the second press calls `override` instead of `launch`. | Talk | group.js:485-492 |
| C13 | Transcript highlight of the **people** line | status indicator | - | During phase `human`, the latest People line is highlighted, as the robot line is during `speaking`. | while running | group.js:1538-1552 |
| C14 | Transcript lifetime | behaviour | - | The transcript is cleared only when a **new connection** starts: the first Start or Get ready after a Disconnect, or a reconnect because the seats changed. Stop, a mode switch or a new Start while connected **keep** the earlier lines. | - | conductor.py:4233-4239 |
| C15 | Session log file `logs/group-YYYYMMDD-HHMMSS.jsonl` | log (no UI) | one file per connection | Everything is written to a log on the hub. No control opens it. An "open log" link would be new. | - | conductor.py:4239 |
| C16 | Lines of a talking group | transcript row | - | A talking group speaks under the group's name (or "Group N"), in its first robot's voice and colour. | when a talking group counts | conductor.py:900-909; group.js:1593 |
| C17 | Real robot name in the dialogs | live display | the robot's real name in muted text after its label | Tells robots apart in the Groups and Copy dialogs | in both dialogs | group.js:1237-1238, 1318-1319 |
| C18 | Group row colour stripe | status indicator | 6 group colours, the same as the card's group tag | Matches a dialog row to the tags on the cards | Groups dialog | group.js:144, 1199; group.css:502-505 |
| C19 | Dialog focus rules | behaviour | - | Groups: the focus goes to the first field on open, and back to the Groups… button on close. Copy: the focus goes to the first target on open, and back to that card's Copy button on close. A seat move keeps the focus on the same arrow. | - | group.js:1270-1280, 1322-1332, 1098-1104 |
| C20 | Free-talk personalities (hidden, fixed by seat position) | hidden setting | 1 "Curious and bubbly…", 2 "Dry and witty…", 3 "Playful: little games, riddles…", 4 "Warm: interested in the people…", 5 "A bit of a nerd: surprising true facts…" (they repeat after 5) | Used instead of the cards' Personality in Free talk. There is no control for them. | Free talk | conductor.py:444-451, 3055-3058 |
| C21 | Language "Auto" starting language | hidden rule | - | Auto begins in **Hebrew** when the topic is Hebrew or empty, otherwise in English. After that it follows the people. | Language = Auto | conductor.py:1925-1928 |
| C22 | The label drives hidden defaults | hidden rule | OpenAI defaults: Reachy Mini 1 ash, 2 verse, 3 echo, 4 ballad, 5 cedar. Fixed voice styles for those five labels ("bright, quick, enthusiastic", ...). Five default ElevenLabs voices by seat. | Renaming a robot away from "Reachy Mini N" changes its **default** OpenAI/Gemini voice. Its OpenAI acting style then comes from the first 120 characters of its Personality. | Voice = Default; OpenAI/OpenRouter voices | conductor.py:211-235, 983-993, 1542 |
| C23 | OpenRouter default voice fallback | hidden rule | `ash` | When the seat's default OpenAI voice is not one OpenRouter has, OpenRouter uses ash | provider OpenRouter | conductor.py:1536-1538 |
| C24 | Interrupt-mode poke | behaviour (visible) | after 8 s of silence, longer with each poke | When nobody talks, a robot pokes the person | Interrupt mode | conductor.py:154, 3259 |
| C25 | Lab intro applies only to Group talk | rule | - | Not used in Interrupt or Free talk. The checkbox stays enabled in every mode. | - | conductor.py:2727-2729 |
| C26 | ElevenLabs voice list loading | behaviour | loaded once per hub run, male voices only | A voice added to the ElevenLabs account appears only after a hub restart. There is no refresh control. Credits are re-read during a session. | - | conductor.py:4001-4015, 1359 |
| C27 | Hub data the page receives but does not show | available data | `warm.at` (time of the last checks), `eleven_in_use` (whether ElevenLabs is in use now), `connected_seats` (who the session really connected) | Candidates for the new design: "checked 2 min ago", an "ElevenLabs in use" badge, "connected: …" | - | conductor.py:4032, 4052, 4321 |
| C28 | Unused route `POST /api/group/loudness` {key, loudness 0-250} | API (no UI) | - | A per-robot volume change without a full config save. The page sends volume through the config PUT instead. | - | api.py:58-61 |
| C29 | Responsive layout | layout | At 1100x620 or larger: one screen, and only the transcript and the cards scroll. Columns follow the robot count: 1-2 robots 50/50, 3 robots 37/63, 4 or more 30/70 with compact cards. 6 or more robots: the page scrolls and the transcript is 260-680 px high. Narrower or lower: one column in the order Status, Conversation, Robots, Session. Under 600 px: mode buttons 2 per row, and Steer wraps. | - | - | group.css:30-66, 453-472, 515-518 |
| C30 | Action row with Talk ("solo" layout) | layout | an extra column for Talk | When Talk shows, the action row gets one more column | one Reachy | group.js:448; group.css:190 |
| C31 | Status details the page hides on purpose | rule | "interrupting" and "the robots are listening" are not shown as detail. "interrupting" turns the big line into "<label> cuts in". | - | - | group.js:378, 408 |
| C32 | Card dimming detail | status indicator | the head, the checkboxes and the order, + and × buttons stay at full strength; the rest fades to 45% | An excluded robot can still be re-included or moved at a glance | Included off | group.css:286-287 |
| C33 | noscript text "Enable JavaScript to see the conversation." | empty/error state | - | - | JavaScript off | group.html:287 |

**Checker total: 33 new items (C1-C33) and 7 corrections (X1-X7).**

### C. Extra notes for the new design (from the checker)

- **Show the Get ready progress text** (X1). Today it is lost because of an operator-precedence bug. The hub sends it, and it is the only place where the automatic "premade first lines" and "interjection recording" become visible.
- **Mark which settings each mode uses** (X7, C6, C20, C25):
  - Topic: Group talk and Interrupt.
  - Personality: Group talk and Interrupt.
  - Lab intro: Group talk only.
  - Interrupting 0-5: Interrupt only.
  - Free talk ignores the cards' Personality.

  A small "used in: Group / Interrupt / Free" hint beside each field keeps every control, and stops people tuning a field the chosen mode ignores.
- **Steer belongs to the running conversation** (X2). Either disable it before Start or say "used once the conversation runs".
- **The label is not cosmetic** (C22). Renaming a robot changes its default voices and its OpenAI acting style, so keep Label next to Voice on the card.
- **C27 offers cheap, useful additions:** a last-checked time on the checks pill, and an "ElevenLabs in use" badge next to the credits note.
