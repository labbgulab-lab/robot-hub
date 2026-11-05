# Parity inventory: Reachy Mini single-robot app (reachy_chat)

Exhaustive list of every control, display and behaviour in today's reachy_chat dashboard, the Operator Board (show mode) and its cue editor, so the new design can redraw all of it. Read-only pass. No key or token files were opened.

Root: `job/reachy-mini/reachy_chat/` (only copy; the `archive/` snapshots are older versions, not counted).

| File | Lines | Read for |
|---|---|---|
| web/static/index.html | 241 | dashboard markup |
| web/static/app.js | 817 | dashboard behaviour |
| web/static/styles.css | 127 | switches, colours, log levels |
| web/static/show.html | 159 | Operator Board + cue editor markup |
| web/static/show.js | 457 | board behaviour, shortcuts |
| web/static/wifi.js | 92 | Add WiFi panel |
| web/server.py | 348 | every REST route and its errors |
| system.py | 932 | payloads, states, heartbeat, volume |
| backend.py | 162 | brain / language / voice / EL / vision options and defaults |
| persona.py | 392 | presets, voices, limits, switch semantics |
| vision.py | 382 | camera vision behaviour |
| conversation.py | 2745 (grepped) | end phrases, opener, abort reasons, gain |
| providers/__init__.py, gemini.py, gpt_live.py, elevenlabs_voice.py | (grepped) | brain list, voice lists, EL models |
| show_editor.py, show_player.py | 396 / 258 (grepped) | cue rules, firing |
| wifi_networks.py | 121 (grepped) | WiFi rules |
| event_log.py, summary.py | 114 / 341 | file-only telemetry (no UI) |

Item count: 128 rows in the tables below (sections A to M).

Scope legend: **robot** = per robot (each reachy_chat instance is one robot, one dashboard, one port); **conv** = per conversation; **tab** = this browser tab only; **all tabs** = broadcast over the WebSocket to every open dashboard of that robot.

---

## A. Title bar (index.html:13-39)

| # | Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| A1 | Robot name (e.g. "reachy3") + grey "Handler Dashboard" | live display | default "Reachy Mini" until identity arrives | Shows the hub-assigned robot name; also sets the browser tab title to "<name> — Reachy" so ten tabs are distinguishable | always | robot | index.html:19-20, app.js:467-474 |
| A2 | Brain badge (e.g. "Gemini 3.8 Live" or "Gemini 3.8 Live + ElevenLabs voice") | status chip | slate when provider implemented, amber when not | Names the brain chosen for the NEXT conversation, plus "+ ElevenLabs voice" when EL is on | when identity has a provider | robot, all tabs | app.js:476-480, system.py:887-889 |
| A3 | Key badge "<key label> ··<last 4>" | status chip | slate; tooltip "key source: <source>" | Shows which API key the chosen brain uses, label and last four characters only (never the key) | when a key resolved | robot | app.js:481-488 |
| A4 | "no API key" | status chip (red) | tooltip = the error sentence | Warns the chosen brain has no key | when key lookup failed | robot | app.js:482-483 |
| A5 | Volume | slider | 0-150, step 5, default 100 (server max 150) | 0-100 sets the robot speaker volume; 101-150 keeps speaker at 100 and boosts the speech signal (gain up to x1.5, hard cap x2.0). Sends 250 ms after the hand stops moving | always | robot, all tabs (volume.change) | index.html:25-31, app.js:763-793, system.py:807-839 |
| A6 | "100%" next to the slider | live display | turns amber above 100% | Current level; follows other tabs unless this slider has focus | always | robot | index.html:30, app.js:765-771 |
| A7 | "Operator Board — show mode" | link button | opens /show in a new tab | Opens the stage show board (section J) | always | robot | index.html:34-38 |

## B. System Status card (index.html:53-62)

| # | Label | Kind | Options / default | What it does | Visible when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| B1 | Status dot | status indicator | amber Starting / green Idle / blue In Conversation / grey Stopped / amber Shutting Down / red Error | Colour of the system state | always | robot | app.js:68-77 |
| B2 | State label | live display | "Connecting…" at load; then Starting… / Idle / In Conversation / Stopped / Shutting Down / Error | Human name of SystemState | always | robot | index.html:57, app.js:63-76 |
| B3 | "(reconnecting…)" suffix | status indicator | appended to the label | Shown when the page lost its WebSocket; retries every 1.5 s | WS closed | tab | app.js:803-806 |
| B4 | Substate badge | status chip | LISTENING / THINKING / SPEAKING | Per-turn phase: mic open or person talking = LISTENING, audio sent = THINKING, reply audio playing = SPEAKING. Holds its last value between turns | only while In Conversation | conv | index.html:59-61, app.js:115-126, system.py:407-418 |

## C. Robot Connection card + Add WiFi (index.html:65-87, wifi.js)

| # | Label | Kind | Options / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| C1 | Connection dot + "Connected" / "Disconnected" | status indicator | green / red; "Unknown" at load | Robot link state; flips red after 2 missed heartbeats (probe every 5 s, 2 s timeout), back to green on recovery | always | robot | index.html:68-69, app.js:155-162, system.py:66-68, 213-251 |
| C2 | "IP: …" | live display | "—" until known | Robot host address | always | robot | index.html:71 |
| C3 | "Daemon: …" | live display | active / unknown / unreachable | Robot daemon state (heartbeat updates it) | always | robot | index.html:72, app.js:409-411 |
| C4 | "Add WiFi…" / "Close WiFi" | toggle button | label swaps | Opens/closes the WiFi panel, loads the saved list, focuses the name box | always | robot | index.html:75-76, wifi.js:58-63 |
| C5 | "Hotspot name" | text input | 1-32 characters | SSID to save | panel open | robot | index.html:78-79, wifi_networks.py:104 |
| C6 | "Password" | password input | 8-63 characters (client checks >= 8) | WiFi password; cleared from the page after a successful save | panel open | robot | index.html:80-81, wifi.js:68, 79 |
| C7 | "Save on robot" | button | disabled while saving or when WiFi is unavailable | Saves the network on the robot with autoconnect on, WITHOUT switching to it; the robot moves over once the current network is gone | panel open; disabled when not running on the robot | robot | index.html:82, wifi.js:65-91, wifi_networks.py:100-121 |
| C8 | WiFi message line | inline status (green/red/grey) | "Saving on the robot…"; success: '"<ssid>" saved/updated. The robot stays on this network for now; turn this hotspot off and that one on, and it moves over within a minute.'; errors: "Type the hotspot's name first.", "A WiFi password has at least 8 characters.", server error text, "Could not reach the robot: …" | Feedback | panel open | robot | index.html:83, wifi.js:18-22, 67-87 |
| C9 | "Knows:" list | read-only list | each network name + "(connected now)" / "(its own setup network)" / "(won't join by itself)"; empty = "nothing yet" | Networks the robot remembers; active first, setup network after | panel open | robot | index.html:84-85, wifi.js:24-39 |
| C10 | WiFi unavailable state | error state | "only when reachy_chat runs on the robot" (laptop mode) or nmcli reason | Disables Save, shows red reason | laptop mode / no NetworkManager | robot | wifi.js:45-50, server.py:116-126 |

## D. System Controls card (index.html:90-98)

| # | Label | Kind | Default | What it does | Enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| D1 | Start System | button | disabled | Brings the robot side back up (fresh SSH + robot player), blocks ~7-10 s until Idle | only in Stopped | robot | index.html:93, app.js:110, 321-324, system.py:544-555 |
| D2 | Stop System | button | disabled | Stops any show cue, gracefully ends a running conversation (no mid-turn cut, 40 s cap), closes the robot link; web page and models stay alive | Idle or In Conversation | robot | index.html:94, app.js:111-112, 325-328, system.py:487-519 |
| D3 | Configure | button | always disabled, tooltip "Coming soon" | Placeholder, does nothing | never | robot | index.html:95-96 |
| D4 | Start/Stop failure | log line | "start system failed: {...}" / "stop system request error: …" in Event Log | Failure feedback goes to the log only | on error | tab | app.js:291-301 |

## E. Persona card (index.html:105-154)

| # | Label | Kind | Options / range / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| E1 | Persona summary line | live display | grey "Base persona" / grey "Switched on, but nothing written yet" / green bold "In character — <preset label or Custom>" | Honest line: what the robot is actually running | always | robot, all tabs | index.html:109-111, app.js:541-553 |
| E2 | Persona switch | toggle | off by default; tooltip "Off is the base persona" | On opens the panel (and saves current text if any). Off = immediate reset to base persona, but KEEPS the text for later. Message "Back to the base persona." | always | robot, all tabs, persisted (persona.json) | index.html:113-116, app.js:609-618, persona.py:8-14 |
| E3 | "Start from" | select | "Write my own" + presets (default built-ins: קאובוי cowboy, בדיחות בלבד jokes-only, מדען scientist, פיראט pirate, ביישן shy; editable list in presets.json) | Picking a preset immediately saves it, fills the textbox with its text and switches persona on | panel open | robot | index.html:121-126, app.js:620-625, persona.py:101-132 |
| E4 | "Who should this Reachy be?" | textarea (dir=auto, 4 rows) | placeholder "e.g. You are a cowboy from the wild west…"; max 1500 chars | Character overlay layered ON TOP of the base prompt (never replaces it; the language/short-answer/one-motion rules are restated after it). Editing a preset's text turns it into Custom | panel open | robot | index.html:133-135, persona.py:15-20, 322-334 |
| E5 | Applies-next hint | inline hint | "Applies to the next conversation" | Says an edit lands on the next conversation | while a conversation is running | robot | index.html:137, app.js:555-557 |
| E6 | Character counter | live display | "n / 1500", red when over | Length vs limit; hidden when empty | panel open, text present | tab | index.html:138, app.js:562-568 |
| E7 | Voice (persona) | select | "Default voice (<default>)" + the chosen brain's voices: Gemini Aoede, Kore, Charon, Puck, Leda; GPT-Live quartz, ripple, vesper, willow, stone, gleam, meridian, beacon, delta, cinder, bossa, tempo | Persona's own voice; list follows the brain picked in the backend picker; a saved voice from the other provider is dropped back to default | panel open | robot | index.html:143-144, app.js:537-538, persona.py:89-95 |
| E8 | Save persona | button (primary) | — | Saves text + voice, switch on; message "Saved." | panel open | robot | index.html:148, app.js:629-636 |
| E9 | Clear | button | tooltip "Clear the text and go back to the base persona" | Full reset: switch off AND text/preset/voice forgotten (unlike switching off). Message "Cleared — back to the base persona." | panel open | robot | index.html:149-150, app.js:640-649, persona.py:353-365 |
| E10 | Persona message | inline status, auto-clears after 4 s | green ok / red errors: "that persona is N characters; the limit is 1500", "there is no preset called …", "'<v>' is not a voice … offers", "Could not reach the robot." | Feedback | panel open | tab | index.html:152, app.js:570-576 |
| E11 | Edit protection | behaviour | — | While someone is typing, broadcasts from other tabs do not overwrite the textbox or voice | while dirty | tab | app.js:504-539 |

## F. Session Monitor + backend picker (index.html:157-204)

| # | Label | Kind | Options / range / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| F1 | "Active Session ID:" | live display (mono) | "—" when none | Conversation id (also the folder name of its logs) | always; whole row dimmed unless In Conversation | conv | index.html:160-161, app.js:165-174 |
| F2 | "Turn Count:" | live display | 0 | Current turn number | always | conv | index.html:162-163, app.js:120 |
| F3 | "Current Turn Duration:" | live timer mm:ss | 00:00 | Resets at each new turn's first LISTENING, ticks every second, freezes when the conversation ends | always | conv | index.html:164-165, app.js:128-152 |
| F4 | Brain | select (tooltip "Who listens and thinks") | Gemini 3.8 Live (default), Gemini 3.1 Flash Live (previous), OpenAI GPT-Live-1; each gets "— no key" suffix when its key is missing | Which realtime model listens, thinks and talks. Choosing GPT-Live turns ElevenLabs OFF automatically. Saved immediately | always (can change during a conversation; applies next) | robot, all tabs, persisted (backend.json) | index.html:171, app.js:667-671, 750, providers/__init__.py:29-38, backend.py:119-127 |
| F5 | Language | select (tooltip "Conversation language") | עברית (he, default), English (en), Auto (עברית / English) | Picks the base prompt, language code and the opener language; Auto replies in whichever language the person spoke, opener in Hebrew | always | robot, persisted | index.html:172-173, backend.py:42-46, conversation.py:161-166, 323 |
| F6 | Voice (brain's own) | select (tooltip "The brain's own voice") | "Default (<persona voice or provider default>)" + provider voices (Gemini 5, GPT-Live 12, see E7); default Gemini Aoede, GPT-Live gleam | Brain's native voice, remembered separately per provider | hidden when ElevenLabs is on or the provider lists no voices | robot, persisted per provider | index.html:175-179, app.js:676-682, backend.py:128-137 |
| F7 | "ElevenLabs v4 voice" | toggle (tooltip "Speak with an ElevenLabs v4 voice instead of the brain's own") | off by default | Brain still thinks; robot speaks with ElevenLabs instead of the native voice | always | robot, persisted | index.html:181-185, app.js:753, backend.py:14-16 |
| F8 | ElevenLabs voice | select (tooltip "ElevenLabs voice") | "First voice in the account" + account voices "<name> (<language>)"; "No voices (check the key)" if empty; list cached 10 min | Which EL voice; blank = first voice in the account | only when F7 is on | robot, persisted | index.html:186-187, app.js:714-731, 755-761, system.py:725-739 |
| F9 | EL-not-recommended warning (red) | inline warning | "ElevenLabs is not recommended with GPT-Live-1 — it stutters. Use it with Gemini." | Warns the combo stutters | when brain is GPT-Live | robot | index.html:189-191, app.js:683 |
| F10 | "Camera vision" | toggle (tooltip "Let the robot see through its head camera and talk about what it sees") | ON by default (off everywhere if env REACHY_VISION=0) | Robot sees through its head camera (1 frame/s, 512x288, memory only, nothing saved). Gemini gets the picture with each turn; GPT-Live gets a 2-3 sentence description from a side model (gpt-4.1-mini) | always | robot, persisted | index.html:193-200, app.js:684-690, 754, vision.py:36-56, backend.py:17-18 |
| F11 | Vision note | live display (truncated, full text in tooltip) | "robot camera · the model sees the frames" / "robot camera · described for the model by gpt-4.1-mini" / amber "no camera here (the app is not running on the robot)" | Where vision comes from and how | when F10 is on | robot | index.html:199, app.js:686-690, system.py:783-789 |
| F12 | Backend message line | inline status (red/amber/green/grey) | red: "<brain key error>" and/or "ElevenLabs: <key error>" (e.g. "No Gemini key yet — add one to keys.json or set GEMINI_API_KEY"); amber: GPT-Live note "Hebrew is unverified on GPT-Live (OpenAI publishes no language list). Its gestures are picked from what it says by a small side model, a moment behind Gemini's."; grey "Applies to the next conversation." during a conversation; "Could not start: <reason>" after a refused start; "Could not load the ElevenLabs voices."; "Could not reach the robot." | The honest line under the picker: what the next conversation will be and what would stop it | always | robot | index.html:201, app.js:656-662, 697-712, 311, system.py:746-756 |
| F13 | Start Conversation / End Conversation | primary button (blue / red) | "…" at load; Start (blue) when Idle; End (red) when In Conversation; disabled otherwise and while a request is in flight | Start: settles brain/key/EL first and refuses with a sentence if something is missing (409 already running, 503 not ready). End: graceful drain, robot finishes its line | Idle or In Conversation | conv | index.html:203, app.js:90-108, 302-320, server.py:74-93 |
| F14 | Hidden backend option: ElevenLabs model | API only (no UI) | eleven_v4_turbo (default), eleven_v4 | Picks the EL model | not shown anywhere today | robot | backend.py:56, 150-154, elevenlabs_voice.py:59-60, server.py:190-191 |
| F15 | Hidden option: refresh EL voice list | API only | /api/backend/elevenlabs/voices?refresh=true | Bypasses the 10-minute cache | not shown (page never passes refresh=true) | robot | app.js:714-716, server.py:219-222 |

## G. Live Conversation Stream (index.html:211-218, app.js:176-258)

| # | Label | Kind | Details | Visible when | Scope | file:line |
|---|---|---|---|---|---|---|
| G1 | "Conversation: <id>" | live display | Conversation id above the chat | during/after a conversation | conv | index.html:213-215 |
| G2 | Person bubble | transcript entry | right-aligned grey bubble, text dir=auto (Hebrew RTL works), "(no transcript)" when empty, "Turn: N" under it | per user turn | conv | app.js:205-215 |
| G3 | Robot bubble | transcript entry | left-aligned orange bubble with a small robot icon, "Turn: N" under it | per robot reply | conv | app.js:217-231 |
| G4 | Aborted-turn line | transcript entry (centred italic) | "Turn N aborted — Gemini silent" or "Turn N aborted" (other reasons: gemini_no_reply, send_failed, drain_failed, cancelled, opener_failed) | when a turn fails | conv | app.js:233-242, conversation.py:2244-2251 |
| G5 | Backend system line | transcript entry (centred grey) | "<brain label> · <language code> · <voice>" e.g. "Gemini 3.8 Live · he-IL · Gemini Live voice Aoede" or the EL voice description | first line of each conversation | conv | app.js:418-421, system.py:717-723 |
| G6 | Auto-scroll | behaviour | sticks to bottom only if already within 40 px of it; bubbles slide in (150 ms) | always | tab | app.js:186-187, styles.css:122-127 |
| G7 | Clear on new conversation | behaviour | chat wiped at conversation.started; kept after it ends until the next one starts | — | conv | app.js:412-414 |
| G8 | Restore on refresh | behaviour | a refreshed or new tab rebuilds the running conversation's transcript from the snapshot | page load | conv | app.js:399-401, system.py:928-929 |
| G9 | Robot opener | behaviour (shows as first robot bubble) | robot speaks first: says hi, that it is Reachy Mini, asks one short question (Gemini only; env REACHY_OPENER=0 disables) | conversation start | conv | conversation.py:305-326 |
| G10 | Voice end phrases | behaviour (no UI hint today except the log) | saying להתראות / ביי / סיים שיחה / תסיים שיחה / תפסיק / תפסיקי / goodbye / good bye / end conversation / end the conversation / stop ends the conversation | in conversation | conv | conversation.py:168-189, 2696 |

## H. Event Log (index.html:221-234)

| # | Label | Kind | Details | Visible when | Scope | file:line |
|---|---|---|---|---|---|---|
| H1 | Log pane | live log (mono, wraps) | lines "HH:MM:SS.mmm LEVEL logger message"; colours INFO slate, WARNING amber, ERROR/CRITICAL red, DEBUG light grey; auto-scroll when at bottom | always | robot | index.html:231-233, app.js:260-288, styles.css:60-65 |
| H2 | Log history on load | behaviour | last 200 lines (server ring buffer) restored on connect/refresh | page load | robot | app.js:395-398, broadcaster.py:29-32 |
| H3 | Client-side lines | log lines from "client" | "conversation on <backend>", "conversation ended (<reason>)" (reasons: user, end_phrase, cancelled, crash), "start failed: …", request errors | events | tab | app.js:420, 433, 312 |
| H4 | Server error lines | log lines | "error" events, e.g. a conversation crash "<provider>: <Type>: <message>", startup fatal | errors | robot | app.js:457-458, system.py:349-353, 436-437 |
| H5 | Copy logs | button | copies all log lines; works on plain http from the robot via a fallback | always | tab | index.html:226-228, app.js:329-377 |
| H6 | Copy status | inline status, clears after 2.5 s | "Copied" / "Nothing to copy" / "Copy failed — select the log and use Ctrl-C" | after Copy | tab | index.html:225, app.js:358-376 |

## I. Page-wide behaviour (app.js)

| # | Item | Kind | Details | file:line |
|---|---|---|---|---|
| I1 | WebSocket live sync | behaviour | one socket per tab; every change (state, persona, backend, identity, volume) reaches every open tab of that robot | app.js:380-463, 799-808 |
| I2 | Auto-reconnect | behaviour | retries every 1.5 s, label shows "(reconnecting…)" | app.js:803-806 |
| I3 | Initial REST loads | behaviour | /api/identity, /api/persona, /api/backend, /api/volume fetched at load (WS snapshot repeats them) | app.js:599-607, 790-797, 814-816 |
| I4 | Layout | layout | page never scrolls; left column (controls, ~58%) scrolls inside itself; right column chat:log split 3:2 | index.html:42-47, 210-221 |
| I5 | No stale page | behaviour | server sends no-cache for pages so a new Launch always ships the new UI | server.py:61-68 |
| I6 | Unrendered server field | gap | snapshot carries `error_message` (startup fatal reason) that the page never shows except via the log | system.py:930-931 |
| I7 | Unrendered summary | gap | conversation.ended carries a `summary` (turn counts, latency, anomalies) that the page ignores | system.py:453-457, summary.py:131-147 |

## J. Operator Board — header and now playing (show.html:28-75, show.js)

| # | Label | Kind | Options / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|
| J1 | "Operator Board" | title | dark theme on purpose (dim room, never on projector) | — | always | robot | show.html:9-11, 29 |
| J2 | System state chip | status indicator (mono) | raw state name, "…" at load | Shows STARTING / IDLE_BREATHING / CONVERSATION_RUNNING / STOPPED etc. | always | robot | show.html:30-31, show.js:360-367 |
| J3 | "conversation running — audio cues will interrupt Reachy" | warning chip (amber) | — | Warns that firing an audio cue cuts into the live conversation (allowed on purpose, e.g. save lines) | while In Conversation | robot | show.html:32-35, system.py:524-538 |
| J4 | Board dimming | status behaviour | 45% opacity | Board fades when the system is not Idle/In Conversation (firing would fail) | not usable | robot | show.js:365-366 |
| J5 | Reload script | button | — | Re-reads cues.json after a hand edit, no restart | always | robot | show.html:37-39, show.js:409-412 |
| J6 | Rebuild audio | button (tooltip "Re-record any line whose text changed") | label "rebuilding…" while busy | Re-synthesises changed lines; result shown in Now line: "rebuilt N lines" / "everything already up to date" / "rebuilt N, M failed — see the log". API also has force=true (rebuild all), not exposed | always | robot | show.html:40-43, show.js:246-267, server.py:310-318 |
| J7 | Dashboard | link | opens / in a new tab | Back to the handler dashboard | always | robot | show.html:44-45 |
| J8 | "STOP · Esc" | danger button | — | Panic: silences immediately and returns the robot to breathing; safe any time | always | robot | show.html:46-49, show.js:316-322, show_player.py:173-180 |
| J9 | Now playing: "Now" + label | live display | "—" idle; "stopped" after STOP; "error: <msg>" red for 3 s | Current cue name | always | robot | show.html:54-58, show.js:324-358, 433-444 |
| J10 | Countdown | live timer | seconds left, 0.1 s resolution | Time left on the playing line | audio cue playing | robot | show.html:59, show.js:343-351 |
| J11 | Progress bar | progress bar (sky blue) | 0-100% | Playback progress, updates every 50 ms | audio cue playing | robot | show.html:61-63 |
| J12 | Now text | live display (RTL) | the line's text | What Reachy is saying right now | audio cue playing | robot | show.html:64 |
| J13 | Shortcut legend | help text | "Space fires the outlined cue and advances · ↑ ↓ move without firing · Esc stop · letter/number keys fire directly" | — | always | — | show.html:67-72 |

## K. Operator Board — cue board (show.js:42-128)

| # | Label | Kind | Details | Visible when | Scope | file:line |
|---|---|---|---|---|---|---|
| K1 | Section card | group | one per script section, RTL title (today: opening 3, reactions 6, topic 4, fun 4, handoff 4, closing 2 cues); 1/2/3 columns by width | always | robot | show.js:100-126 |
| K2 | Cue card | clickable card | click / Enter / Space on a focused card fires it (motion first, then audio); 250 ms flash on fire; dimmer style for motion-only cues | always | robot | show.js:45-91, 288-314 |
| K3 | Hotkey key-cap | display | the cue's single-character hotkey, "·" if none | always | robot | show.js:66 |
| K4 | Cue label | display | name for the operator | always | robot | show.js:67 |
| K5 | Duration | display | "3.4s" | when audio built | robot | show.js:57, 68 |
| K6 | Line text | display (RTL) | what Reachy says | text cues | robot | show.js:70 |
| K7 | Motion chip | chip | emotion / dance name, or head direction | cue has motion | robot | show.js:58-60, 72 |
| K8 | "motion only" chip | chip | — | no text | robot | show.js:73 |
| K9 | "no audio — press Rebuild" | error chip (red) | text present but recording missing | missing audio | robot | show.js:61, 74 |
| K10 | edit | small button on each card | opens the cue editor without firing the cue | always | robot | show.js:77-90 |
| K11 | "+ add cue" | dashed button per section | opens the editor for a new cue in that section | always | robot | show.js:117-123 |
| K12 | Next-cue outline | status indicator (blue outline) | the cue Space will fire; scrolls into view | always (if cues) | tab | show.html:14, show.js:269-284 |
| K13 | Fire errors | inline error (Now line, red) | "robot not connected", "unknown cue", "no audio for … — run tools/build_show.py", "motion dispatch failed: …", invalid state (409) | on failure | tab | show.js:296-306, show_player.py:135-165 |

### Keyboard shortcuts (show.js:371-406)

| # | Key | Action | When |
|---|---|---|---|
| K14 | Space | fire the outlined cue and advance the pointer | editor closed, focus not in a field |
| K15 | ↓ or → | move pointer forward without firing | same |
| K16 | ↑ or ← | move pointer back without firing | same |
| K17 | Esc | STOP everything | editor closed |
| K18 | any cue hotkey (letter/number, case-insensitive) | fire that cue, pointer does not move | no Ctrl/Alt/Meta held |
| K19 | Esc (editor open) | close editor | editor open |
| K20 | Ctrl+Enter / Cmd+Enter (editor open) | save cue | editor open |

## L. Cue editor modal (show.html:79-155, show.js:130-244)

| # | Label | Kind | Options / range / default | What it does | Visible when | file:line |
|---|---|---|---|---|---|---|
| L1 | "Edit — <label>" / "New cue" | modal title | — | — | editor open | show.html:83, show.js:149 |
| L2 | Delete | danger button | confirm dialog: 'Delete "<label>"? Its recording is deleted too.'; refused while that cue is playing ("that cue is playing right now — stop it first") | Deletes cue + its WAV | editing an existing cue only | show.html:84-87, show.js:230-244, server.py:296-299 |
| L3 | "Name (for you, on the card)" | text | required ("label cannot be empty" / "give the cue a label so you can find it") | Card label | always | show.html:92-94 |
| L4 | "What Reachy says — leave empty for a motion-only cue" | textarea RTL, 4 rows | max 600 chars ("keep it under 600 (long lines make for long waits on stage)"); hint "Changing this re-records the line, which takes a few seconds." | Spoken line; saving re-synthesises it | always; gets focus on open | show.html:98-105, show_editor.py:56, 195-206 |
| L5 | Hotkey | text, 1 char | unique across cues ("hotkey 'x' is already used by …"); empty = none | Direct-fire key | always | show.html:110-112, show_editor.py:180-192 |
| L6 | Motion | select | none / emotion / dance / head | Motion type; changing it refills "Which" | always | show.html:115-122, show.js:417 |
| L7 | Which | select | emotion names (Pollen emotions library) / dance names (dances library) / head directions left, right, up, down, front; disabled + faded when type is none | Motion name | always | show.html:125-127, show.js:162-173, conversation.py:451-453 |
| L8 | "Boss's cue line — printed in the script, not spoken" | text RTL | optional | The presenter's prompt line, goes into the printed script doc | always | show.html:132-136, show_editor.py:259 |
| L9 | Error line | inline error (red) | server validation text, "a cue needs a line to speak, a motion, or both", "HTTP <code>" | Feedback | always | show.html:139 |
| L10 | Footer hint | help text | "Ctrl-Enter saves · Esc closes" | — | always | show.html:143 |
| L11 | Cancel | button | — | Close without saving; backdrop click also closes | always | show.html:144-147, show.js:419 |
| L12 | Save | primary button | busy label "saving + re-recording…", disabled while busy | Creates/updates the cue, re-records audio, re-renders board; every write backs up cues.json first | always | show.html:148-152, show.js:195-228 |
| L13 | Keyboard capture | behaviour | while open, hotkeys and Space do not fire cues | editor open | show.js:372-381 |

## M. Settings that exist only in the backend / launch (no UI today)

| # | Item | Values / default | Where set | file:line |
|---|---|---|---|---|
| M1 | Robot identity (id + name) | passed by the hub (--robot-id / --robot-name), cached in robot_identity.json | launch | identity.py:1-40, laptop_chat.py:75-82 |
| M2 | Launch provider + key | --provider, --api-key-id, --api-key (from the hub) or keys.json / env vars | launch | laptop_chat.py:83-90, system.py:650-673 |
| M3 | Microphone selection (laptop mode) | --mic-match, --mic-rate | launch | laptop_chat.py:96-102 |
| M4 | Robot host / local mode | --robot-host, --local-robot | launch | laptop_chat.py:69-74, 103 |
| M5 | Opener on/off | REACHY_OPENER (default on) | env | conversation.py:312 |
| M6 | Vision master switch, model, size, fps, test image | REACHY_VISION, REACHY_VISION_MODEL, REACHY_CAMERA_WIDTH/HEIGHT/FPS, REACHY_CAMERA_IMAGE | env | vision.py:54-56, 74-99 |
| M7 | Turn-taking knobs | silence hangover 0.8 s, max turn 30 s, wait for speech 15 s, min speech 0.3 s, VAD threshold 0.5, one motion tool per reply | code constants | conversation.py:191-199, 334 |
| M8 | Persistence | persona.json, presets.json, backend.json survive restarts; per-conversation folder conversations/<id>/ with laptop.log, events.jsonl, summary.json | files | persona.py:29-31, backend.py:20-22, event_log.py, summary.py |

---

## Flows

1. **Open the dashboard**: page shows "Connecting…", WS snapshot fills name, badges, state, robot card, persona, picker, last 200 log lines, and any running transcript. Tab title becomes "<robot> — Reachy".
2. **Choose how the robot talks (before a conversation, same card as Start)**: Brain (watch for "— no key") → Language → either native Voice, or flip ElevenLabs on → pick EL voice (red warning if GPT-Live) → Camera vision on/off (read the note) → read the message line (red = start will be refused). Every change saves instantly and syncs to all tabs; during a conversation it says "Applies to the next conversation."
3. **Give the robot a character**: flip Persona on → pick a preset (saves and fills the text) or "Write my own" → edit text (counter n/1500) → pick persona Voice → Save persona → summary turns green "In character — …". Flip off to hear the plain robot (text kept); Clear to wipe it.
4. **Run a conversation**: Start Conversation (blue) → if refused, the reason appears under the picker → chat clears, backend line appears, robot speaks its opener → badge cycles LISTENING / THINKING / SPEAKING, turn count and turn timer run, bubbles stream in → End Conversation (red) or the person says goodbye / להתראות → log says "conversation ended (<reason>)", timer freezes, chat stays until the next start.
5. **Adjust volume live**: drag the slider (above 100% turns amber and boosts the voice) → applies 250 ms after release → all tabs follow.
6. **Recover the robot**: Stop System (ends a conversation gracefully, disconnects) → Start System (Stopped only, ~7-10 s) → state back to Idle. Red Disconnected / Daemon unreachable after 2 missed heartbeats.
7. **Teach the robot a new WiFi**: Add WiFi… → name + password (>= 8) → Save on robot → success sentence; list shows "(connected now)", "(its own setup network)", "(won't join by itself)" → turn the old network off and the robot moves within a minute. Only works when the app runs on the robot.
8. **Copy logs for a bug report**: Copy logs → "Copied" (fallback on plain http) or "select the log and use Ctrl-C".
9. **Run a show**: Operator Board (new tab) → check state chip and amber warning → Space fires the outlined cue and advances; arrows move without firing; hotkeys fire out of order → Now line, countdown and bar show progress → Esc / STOP silences and returns the robot to breathing.
10. **Edit the script on the spot**: edit on a card (does not fire) or "+ add cue" → name, line (<= 600), hotkey, motion type + which, boss's cue line → Save / Ctrl+Enter ("saving + re-recording…") → board re-renders. Delete with confirm. Rebuild audio to re-record changed lines; Reload script after a hand edit of cues.json; red "no audio — press Rebuild" chips flag missing recordings.

---

## Notes for the new design

**Must stay IN CONTEXT, next to Start Conversation / the robot (the user's explicit rule):**
- The whole backend picker (F4-F12): brain with per-brain "no key" marking, language, native voice, ElevenLabs switch + EL voice + GPT-Live warning, camera vision switch + its source note, and the red/amber message line that predicts a refused start. Today these sit in the same card as the Start button; do not move them to Settings.
- Persona switch, preset picker, textbox with counter, persona voice, Save / Clear, and the green "In character — …" summary (E1-E11). The off-vs-Clear distinction must survive (off keeps text; Clear wipes it).
- "Applies to the next conversation" hints on both persona and picker while a conversation runs.
- Volume slider with the >100% boost and amber colouring (A5-A6): it is used mid-conversation.
- Brain + key badges next to the robot name (A2-A4), so the operator sees which key and brain are live.
- State, substate badge, turn count, turn timer, session id (B1-B4, F1-F3), live transcript with aborted-turn and backend lines (G1-G8), and the Event Log with Copy (H1-H6) next to the conversation.
- Robot connection dot, IP, daemon state (C1-C3) and Start/Stop System (D1-D2).
- Operator Board stays a separate full-screen, dark, keyboard-first surface with STOP always visible and every shortcut (K14-K20); the cue editor stays reachable from the card (edit) and from each section (+ add cue).

**Could live in a settings / advanced page (rarely touched, not per conversation):**
- Add WiFi panel (C4-C10) — or a per-robot "Network" drawer on the robot card.
- Show-script maintenance: Reload script, Rebuild audio (and the hidden force-rebuild).
- Hidden API-only options worth surfacing in an advanced area: ElevenLabs model (eleven_v4_turbo / eleven_v4, F14), refresh EL voice list (F15).
- Launch-time / env settings (M1-M7): mic selection, opener on/off, vision model, turn-taking knobs. Read-only display is enough unless the user asks for control.

**Gaps the redesign can fill without dropping anything:**
- Configure button is a dead "Coming soon" placeholder (D3): either remove or give it the advanced settings.
- `error_message` (startup fatal) and the end-of-conversation `summary` are sent but never shown (I6-I7).
- Voice end phrases (G10) and the robot opener (G9) are invisible to students; a one-line hint near Start would help.
- Start/Stop System failures only reach the log (D4); show them inline like the conversation start refusal.
- Persona voice and brain voice are two separate selects with overlapping meaning (E7 vs F6); keep both (parity) but label them clearly.

---

## Checker additions

Independent second pass over index.html, app.js, styles.css, show.html, show.js, wifi.js, web/server.py, system.py, backend.py, persona.py, conversation.py, vision.py, show_player.py, wifi_networks.py, providers/*. No key or token files opened. 46 rows added (X1-X46) plus 7 corrections (C-1 to C-7).

### Corrections to existing rows

| # | Row | Correction | file:line |
|---|---|---|---|
| C-1 | E5, F12 ("Applies to the next conversation") | The hint is NOT live. `applies_next` is only re-sent with a persona.change / backend.change, and a state change does not resend either. So the hint appears only after someone edits persona/picker DURING a conversation (or reloads the page mid-conversation), and it stays visible after the conversation ends until the next edit or reload. The new design should drive it from the live state instead. | app.js:403-405, 555-557, 710; system.py:189, 787, 857 |
| C-2 | E7 / F6 (two voice pickers) | Exact precedence for the voice the robot uses: brain voice (F6, if set for this provider) wins, else persona voice (E7, only while the persona switch is ON), else provider default (Gemini Aoede, GPT-Live gleam). The two GPT-Live lists are in different orders (brain list starts gleam, meridian, quartz…; persona list starts quartz, ripple, vesper…). | system.py:631-632, persona.py:89-95, 188-191, 371-376; providers/gpt_live.py:671-673 |
| C-3 | E7 (persona voice) | Changing the persona voice is NOT saved by itself (unlike the switch and the preset select): it only marks the panel dirty and lands on "Save persona". Leaving without Save loses it. | app.js:638, 629-636 |
| C-4 | J9 (Now label "—" idle) | "—" only at page load. After a cue ends the label keeps the last cue's name (show.cue.ended only resets bar + countdown). It reads "stopped" only after STOP. A Rebuild result ("rebuilt N lines") also lands in this same label. | show.js:354-358, 437-444, 258-260 |
| C-5 | F13 (Start refused) | Only a 400 "refused" carries a sentence. 409 already running and 503 not ready have no `detail`, so the page prints raw JSON: 'Could not start: {"error":"already_running"}' / '{"error":"not_ready","state":"STARTING"}'. The "Could not start" line is overwritten by the next backend.change. | app.js:310-311; server.py:79-86 |
| C-6 | F4 (Brain default) | Default brain on a fresh robot (no backend.json) = the first brain of the provider the hub launched it with (Gemini 3.8 Live, or GPT-Live-1 if launched on gpt_live). The launch provider's key must exist or the robot does not boot at all; any other brain's missing key is refused only at Start. | system.py:136-143, 259-279 |
| C-7 | K2 (cue card click) | Clicking a card fires it but does NOT move the Space pointer (only Space advances). Enter/Space on a focused card fire that card. | show.js:81-84, 288-313 |

### X. Missing items

| # | Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | Scope | file:line |
|---|---|---|---|---|---|---|---|---|
| X1 | E Persona | "Write my own" in Start from | select option | blank value | Choosing it sends nothing (no request, text and preset kept). The preset is dropped only when the edited text is saved and differs from the preset text; then the select falls back to "Write my own" | panel open | robot | app.js:620-622, persona.py:309-314 |
| X2 | E Persona | "In character — Custom" with an empty box | summary state | — | Persona counts as active when ON and EITHER text OR a voice is set, so a voice-only persona shows green "In character — Custom" | switch on, voice chosen, no text | robot | persona.py:193-197, app.js:542-547 |
| X3 | E Persona | Text clean-up on save | behaviour | — | Server strips control/directional characters, NFC-normalises and collapses 3+ blank lines; the box is refilled with the cleaned text, so it can differ slightly from what was typed | on save | robot | persona.py:134-149, 316-327 |
| X4 | E Persona | Language-matched closing rule | behaviour (invisible) | he / en / auto variants | The rule restated after the overlay follows the Language picker (Hebrew, English, or "reply in the language the user spoke") | persona active | conv | persona.py:58-80, 176-186 |
| X5 | E Persona | Fallback error texts | inline status | "Could not save that." (any non-OK without detail); server "nothing to change" if an empty body is sent | Feedback | panel open | tab | app.js:587; server.py:163-168 |
| X6 | E Persona | Preset list source | data rule | presets.json beside the app, written on first run; falls back to the 5 built-ins if the file is missing/broken/empty; entries without an id are skipped | — | — | robot | persona.py:214-230, 377-392 |
| X7 | E Persona | Saved voice dropped on provider change | behaviour (log only) | — | A saved persona voice from another provider is dropped at load with a WARNING log line; character text kept | startup | robot | persona.py:258-264 |
| X8 | F Picker | ElevenLabs switch allowed with GPT-Live | behaviour | — | Selecting GPT-Live turns EL off, but the switch stays usable: EL can be turned back on over GPT-Live (red F9 warning shows). Only a brain SWITCH to GPT-Live turns it off | brain = GPT-Live | robot | backend.py:119-127 |
| X9 | F Picker | ElevenLabs voice list loading | behaviour | loaded once per page when EL is on; retried on the next backend.change if it came back empty | Fetches the account voices; choosing one saves id + display label | EL on | tab | app.js:654, 691-693, 714-731, 755-761 |
| X10 | F Picker | Camera vision switch bounce | behaviour | — | With REACHY_VISION=0 the server always reports vision off; turning the switch on snaps it back off with no message | env off | robot | system.py:780, vision.py:54 |
| X11 | F Picker | Vision note extra variants | live display | "test image <file>" (REACHY_CAMERA_IMAGE set), amber "REACHY_CAMERA_IMAGE does not exist: <path>" | Where frames come from | vision on | robot | vision.py:128-136 |
| X12 | F Picker | Backend rejection texts | inline status (red) | "Could not change that." fallback; "language must be one of: he, en, auto"; "'<v>' is not a <provider> voice"; unknown brain id; "ElevenLabs model must be one of: …" | Feedback on a refused change | always | tab | app.js:741; backend.py:120, 134, 141, 152 |
| X13 | F Picker | Full list of Start-refusal sentences | inline status (red, "Could not start: …") | "<brain label>: No <Gemini/OpenAI/ElevenLabs> key yet — add one to keys.json or set <ENV VAR>"; "<brain label> client failed: …"; "ElevenLabs voice is on, but: <key error>"; "ElevenLabs voice is on, but no voice is chosen and the account's voice list could not be read" | Why Start was refused | after Start | conv | system.py:663-716 |
| X14 | F Session Monitor | Stale session values after end | behaviour | — | After a conversation ends, Active Session ID, Turn Count and the "Conversation: <id>" header keep the last conversation's values (row dims) until the next start; a page reload with no conversation resets them to "—" / 0 | after end | conv | app.js:165-174, 388-394, 432-435 |
| X15 | F Session Monitor | Mid-conversation reload | behaviour | — | After a refresh during a conversation: turn count restored, but the turn timer shows 00:00 and the substate badge stays hidden until the next turn event, and the backend line (G5) is NOT restored (it is not part of the transcript) | page reload while In Conversation | tab | app.js:382-402, 115-126; system.py:926-929 |
| X16 | F Start/End | Button during End | state | — | End disables the button; it stays disabled while the robot finishes (drain, up to 40 s) until the state flips to Idle | after End click | conv | app.js:320, system.py:459-476 |
| X17 | G Stream | Opener bubble numbering | display | "Turn: 0" | The robot's opening line is turn 0 | Gemini, opener on | conv | conversation.py:2339-2357 |
| X18 | G Stream | Robot gestures not shown | gap | play_emotion / dance / move_head, max 1 per reply (extra calls suppressed) | The model moves the robot during replies; nothing on the dashboard shows which gesture fired (log + summary.json only) | in conversation | conv | conversation.py:301-334, 1481-1551; summary.py:155-158 |
| X19 | A Volume | Volume errors are silent | behaviour | — | If the robot refuses the change (HTTP 502 "the robot did not take the volume change") or the request fails, nothing is shown; the slider stays where it was dropped. If the robot volume cannot be read, the page shows 100% | robot unreachable | robot | app.js:779-787, server.py:216-217, system.py:809-822 |
| X20 | A Volume | Unshown volume fields | gap | `speaker` (0-100 hardware level), `boost` (gain, e.g. 1.25) | Sent in every volume payload, never displayed | — | robot | system.py:821-822 |
| X21 | A Title bar | Default tab title | display | "Reachy Mini Handler Dashboard" until identity arrives | — | page load | tab | index.html:6 |
| X22 | D Controls | Start System wait | state | both System buttons disabled, no spinner, ~7-10 s | Request blocks until Idle; a second Start gets 409 | after click | robot | app.js:321-324, server.py:103-110 |
| X23 | D Controls | Startup fatal goes to Stopped | behaviour | reasons: "<provider> is not built yet — relaunch this robot with --provider gemini", key not found / "api key resolution failed: …", "<provider> client init failed: …", "VAD load failed: …", "microphone unavailable: …" (robot mode) | A boot failure lands in Stopped (grey), not Error; the reason appears only as an ERROR log line from "startup". Start System only re-runs the robot connection, it does not retry key/model/mic | startup failure | robot | system.py:259-323, 349-353, 544-555 |
| X24 | D Controls | Stop System refused | log line | 'stop system failed: {"error":"invalid_state","state":…}' | Feedback when not Idle/In Conversation | on error | tab | server.py:95-101, app.js:291-297 |
| X25 | C WiFi | Load / save error texts | inline status | "Could not ask the robot: <err>" (list load failed); "Failed (<HTTP code>)."; default "WiFi settings are not available here."; server: "a WiFi name has 1 to 32 characters", "a WiFi password has 8 to 63 characters", "'Hotspot' is the robot's own setup network", "nmcli is not on this machine -- WiFi can only be set on the robot", "NetworkManager did not answer within N s", "this robot has no WiFi device" | Feedback | panel open | robot | wifi.js:46, 54, 84; wifi_networks.py:48-56, 83, 104-108 |
| X26 | C WiFi | Panel reset on open | behaviour | — | Every open clears the message, reloads the list and focuses the name box (the name box keeps its text) | open | tab | wifi.js:58-63 |
| X27 | C WiFi | List order + no remove | data rule | connected network first, then others A-Z, setup network last; there is no forget/remove control | — | panel open | robot | wifi_networks.py:95-96 |
| X28 | C WiFi | Save re-enabled after a try | behaviour (bug) | — | After any save attempt the button is re-enabled even when WiFi is unavailable (server then answers 409) | laptop mode | tab | wifi.js:88-90 |
| X29 | H Log | Copy scope | behaviour | — | Copy logs copies only the lines in the page (last 200 from the server at load + new ones), not the full log file | — | tab | app.js:261, 358-359, broadcaster.py:29-32 |
| X30 | I Page | Unshown conversation / persona / EL fields | gap | conversation `started_at`, `persona` summary of the running conversation, conversation folder `dir`; persona `updated_at`, `active_voice`, `provider_display`, `summary`; EL `voice_name`, `model`, `models`; /api/status route unused by the page | Sent but never rendered. "The persona this conversation actually started with" is available and unshown | — | robot | system.py:386-391, 841-857, 900-917 |
| X31 | I Page | Dashboard ignores show events | gap | — | When a cue fires from the Operator Board, the dashboard shows nothing (no "cue playing" line); show.cue.* events are dropped | show in use | robot | app.js:380-462 |
| X32 | J Board | Board ignores everything but state | gap | — | The board shows no robot connection, no transcript, no volume; its WebSocket listens only to state + show events | always | robot | show.js:423-448 |
| X33 | J Board | No reconnect indicator | behaviour | retries every 1.5 s silently | State chip may be stale while disconnected | WS lost | tab | show.js:447 |
| X34 | J Board | Opening mid-cue | behaviour | — | The catalog's `playing` field is ignored, so a board opened while a cue plays shows "—" | open during cue | tab | server.py:224-229, show.js:450-455 |
| X35 | J Board | STOP also resets motion | behaviour | — | STOP drops queued audio AND sends a "stop" motion (robot back to breathing); safe with nothing playing; works even while the board is dimmed | any time | robot | show_player.py:173-183 |
| X36 | K Cues | Cue interrupt rules | behaviour | — | A new AUDIO cue cuts the cue already playing; a MOTION-ONLY cue does not cut audio that is still playing (a nod over a line) | firing | robot | show_player.py:141-142, 186-190 |
| X37 | K Cues | Motion-only cue in Now | display | — | Firing a motion-only cue shows its label in Now, clears the text line, no bar or countdown | motion-only fire | robot | show.js:433-436, show_player.py:150-154 |
| X38 | K Cues | Fire flash on failure | behaviour | — | The 250 ms blue flash happens before the request, so a refused cue still flashes, then "error: …" appears (e.g. "error: invalid_state" for a 409) | on failure | tab | show.js:291-301 |
| X39 | K Shortcuts | Space on a focused card double-fires | behaviour (bug) | — | The card's own Space handler fires that card, then the page-level Space handler also fires the outlined cue and advances | card has keyboard focus | tab | show.js:82-84, 388-392 |
| X40 | K Shortcuts | Hotkeys follow the keyboard layout | behaviour | — | Hotkeys match the typed character, so with a Hebrew keyboard layout active the Latin letter hotkeys do not fire | layout = Hebrew | tab | show.js:401 |
| X41 | K Shortcuts | Arrow keys clamp | behaviour | — | Pointer stops at first/last cue (no wrap); pointer index is not reset by Reload/Save/Delete, so it can point at a different cue after edits | — | tab | show.js:280-284 |
| X42 | J Board | Reload script has no feedback | behaviour | — | No busy state, no success line, no error handling (a failed reload fails silently) | always | tab | show.js:409-412 |
| X43 | J Board | Rebuild error | inline error | "error: <server error>" in Now (red 3 s); API `force=true` (rebuild all) has no button | on failure | robot | show.js:254, 261-262; server.py:310-311 |
| X44 | L Editor | "Which" has no blank | select behaviour | first name auto-selected when Motion type changes; motion catalog fetched once per page, empty lists (Which disabled) if the fetch fails | — | editor open | tab | show.js:135-143, 162-173, 417 |
| X45 | L Editor | Save / delete failure texts | inline error | server `error` text, "HTTP <code>", or the network exception text; on failure the editor stays open | on failure | tab | show.js:219-227, 237-243 |
| X46 | L Editor | Re-record failure | inline error | HTTP 500 `error` when the voice re-record (TTS) fails during save/add/delete | Save can fail after validation passed | on failure | robot | server.py:264-306 |

### Checker notes for the new design

- Most important for the user's rule: keep both voice pickers and their precedence (C-2), right next to Start. Persona voice needs Save while the other persona controls save at once (C-3). Either keep that or make every persona control save the same way, and say which in the UI.
- Drive the "Applies to the next conversation" hints from the live state (C-1). Today they are stale.
- Gaps worth closing while redrawing (nothing removed): show 409/503 Start refusals as sentences (C-5), show volume errors (X19), show the startup fatal reason inline (X23), keep the backend line after a refresh (X15), show the last gesture fired (X18), show "cue playing" on the dashboard (X31), fix the Space double-fire on a focused cue card (X39).
