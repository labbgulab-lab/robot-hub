# Parity inventory: group conversation page, LIVE side (during and after a conversation)

Files read in full:

| File | Lines | Role |
|---|---|---|
| robot-hub/web/group.html | 290 | markup: stage, transcript, steer box, robot cards template, session bar, Groups and Copy modals, toast |
| robot-hub/web/group.js | 1874 | behaviour: WebSocket `/ws/group`, REST calls, rendering, live typing, timers, shortcuts, tooltips |
| robot-hub/web/group.css | 519 | states that carry meaning (phase colours, current line, cut-off, deaf meter, closing Stop, warn/ok) |

Backend read only for event fields and option values: robot-hub/hub/group/api.py (100 lines, all routes), robot-hub/hub/group/conductor.py (parts: `turn()` 2009, cut handling 2425-2460, live words 2915-2935, nudge 4189, start 4195, get_ready 4267, warm_state 4320, state() 4026, set_status 4109, note 4120, more_time 4578, mic_state 1347, guard_people_mic 1328).

Line refs are `file:line`; `html` = group.html, `js` = group.js, `css` = group.css, `cond` = hub/group/conductor.py.

Scope note: the robot cards and the session bar are included here too, because the page says "Everything here changes at once, also mid-conversation" (html:114). They are live controls, not setup-only.

---

## 1. Live channel (what feeds every live display)

| Item | Kind | Fields / values | What it does | file:line |
|---|---|---|---|---|
| WebSocket `/ws/group` | transport | messages: `group.state` (whole truth), `group.turn` (one transcript line, upserted by id), `group.status` (phase patch), `group.levels` (~8/s mic meters), `group.people` (live words of the person), `heartbeat` (every 20 s idle) | redraws page; reconnects with backoff 0.5 s doubling to 10 s | js:1747-1785, api.py:78-97 |
| Connection pill (top bar) | status indicator | text `connecting` / `live` / `reconnecting`; dot green when live | shows the link to the hub | html:24-26, js:1768-1783 |
| First load fetch `GET /api/group/state` | loading/error state | 404/405 -> "This hub has no group conversation yet. Restart the hub with the new code."; no answer -> "The hub did not answer (...)" (shown in error banner) | makes an old hub say so instead of an empty page | js:1789-1802, js:1390-1399 |
| `group.status` object | data | `phase` (idle, starting, ready, speaking, listening, human, thinking, stopping), `speaker` (robot name), `character` (label), `elapsed_s`, `detail`, `mode` | drives status line, phase label, timer, lit card, current transcript line | cond:2003-2007, cond:4109-4113 |
| `group.state` extra live fields | data | `running`, `connected`, `mode`, `people_live`, `limit_s`, `closing`, `eleven_credits`, `eleven_in_use`, `voice_backend{key}`, `brain{key}`, `echo{key}`, `mics[]`, `people_mic_active`, `mic{in_use,people_mic,health,robot_mics,dji}`, `warm{checks,at,busy}`, `error`, `connected_seats` | see displays below | cond:4026-4070 |

## 2. Top bar and banners

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Top bar | Group conversation | title | | page name | always | html:20 |
| Top bar | save badge: `loading` / `saving` / `not saved yet` / `not saved` / `saved` | status indicator (grey / green ok / amber problem) | | whether settings are saved on the hub | always | html:22, js:1362-1373, css:16-21 |
| Top bar | Robot Hub | link | `/` | back to main hub page | always | html:23 |
| Top bar | connecting / live / reconnecting | status indicator | | WebSocket state | always | html:24-26 |
| Below top bar | error banner (alert icon + text) | banner, role=alert | priority: hub `error` > local refused request > link error | stays until fixed; texts include "Could not start: ...", "Could not stop: ...", "Could not get ready: ...", "The setup could not be saved, so the conversation did not start.", hub errors like "could not connect the robots: ..." | shown when any message exists | html:31-33, js:684-688, js:1657, js:1664, js:1699 |
| Bottom | toast | toast, auto-hides 4.2 s | | short confirmations and failures (list in section 10) | on announce() | html:216, js:186-191 |
| Everywhere | quick tooltips | tooltip | 300 ms delay; every `title` is moved into a custom dark tooltip; titles set later by code are caught too | every control explains itself on hover | on hover; hidden on mousedown/scroll | js:1816-1873, css:477-484 |

## 3. Stage: status, clock, mode buttons (the "what is happening now" panel)

| Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|
| Status dot | status indicator | pulses in thinking / starting / stopping | phase at a glance | always | html:46, css:94-96 |
| Phase label (small caps) | live display | Not running, Starting, Speaking, Listening, People speaking, Thinking, Stopping, Connected (for `ready`) | names the phase; colour: blue speaking, green listening/ready, amber people | always | html:46, js:101-110, css:89-97 |
| Big status line (`statusParts`) | live display | speaking: "`<label>` (`<robot name>`) is speaking" (robot name only if label differs), or "`<label>` cuts in" when detail=`interrupting`; unknown seat: "`<speaker>` is speaking" / "A robot is speaking"; listening: "Waiting for you to talk" (interrupt mode) / "Listening to the room"; human: "You have the floor (for now)" (interrupt) / "The people are speaking"; ready: "Robots connected: pick a mode"; thinking: "Thinking…"; starting: "Starting…"; stopping: "Stopping…"; idle: "Running" / "Not running" | who has the floor, in visitor words; uses the label as currently edited (draft), Hebrew-safe via `<bdi>` | always; grey when idle | html:47, js:374-398 |
| Status detail (small, after the line) | live display | `<mode name>` - `<detail>`; or `<mode name>` - "closing: each robot says its last word"; hidden details: `interrupting`, `the robots are listening`, and everything in `ready` phase | mode and what the hub is doing. Hub detail strings: "answering the room", "waiting for the rest", "waiting for the person", "answering the person", "getting ready: checking every service", "getting ready: recording the interjections (first time with these voices only)", "ready: press a mode to start", "connected, but X failed the check" | hidden when empty | html:48, js:408-413, cond:2968, 3001, 3258, 3533, 4285, 4292, 4299 |
| Timer `m:ss / m:ss` | live display | elapsed / total; total = hub `limit_s` while running (includes +1 additions), else Minutes setting x 60 | session clock; ticks locally every 500 ms between hub messages, runs only in speaking/listening/human/thinking | always | html:51-53, js:420-435, js:722 |
| Timer bar | meter | fills elapsed/total; turns amber when over time | progress of the session | always | html:58, js:432-434, css:112-114 |
| +1 | button | adds 60 s per press (hub caps 600 s per call) | `POST /api/group/more_time {seconds:60}`; saved Minutes setting unchanged; hub adds note "+1 min: it now ends at m:ss" | enabled only while running, not closing, not already sending | html:54-55, js:550, js:632-644, cond:4578-4589 |
| Get ready / Getting ready… | button | turns green (`done`) when connected and every check ok | `POST /api/group/ready`: saves pending edits, connects robots, checks each service with a real request, pre-makes first line of each mode, records interrupt interjections | disabled while starting, getting ready, hub warming, running, or fewer than 2 included robots (unless Simulate) | html:60, js:535-540, js:646-662, cond:4267-4302 |
| Talk (sub: "one robot, its own app" / "starting its app…" / "in use: press to take over" / "open its app") | button | | exactly one real Reachy on the hub: opens a new tab, launches (or overrides) that robot's own app (reachy_chat) via `/api/robots/<key>/launch` or `/override`, or opens it if already RUNNING; pop-up blocked -> toast | shown only with exactly one real (non-laptop) Reachy and Simulate off; disabled while busy, starting, connected or running; tooltip "Disconnect first: the group conversation is holding the robot." when connected | html:63-65, js:439-515 |
| Group talk (sub: "robots + people" / "starting…" / "connecting…" / "running" / "switch to this") | mode button | `mode=group` | `POST /api/group/start {mode}`; saves edits first; while another mode runs it switches at once | disabled while starting, fewer than 2 included (unless Simulate), or already active; green when active | html:66-68, js:524-534, js:1650-1676 |
| Interrupt mode (sub: "they cut you off") | mode button | `mode=interrupt`; orange | a person talks, robots cut in per their Interrupting level | same as above | html:69-71, css:182 |
| Free talk (sub: "chat about anything") | mode button | `mode=free`; teal | no topic, no sides | same as above | html:72-74, css:191 |
| Stop / Stopping… / Stop now | button (red; solid dark red in closing) | first press: `POST /api/group/stop {now:false}` graceful (talking robot finishes, each robot says a closing line); while closing: `{now:true}` stops at once | ends the conversation; robots stay connected | enabled while running or starting; tooltip changes in closing | html:75, js:543-549, js:1691-1707, api.py:41-47, css:485 |
| Disconnect | button | | `POST /api/group/disconnect`: releases the robots (needed to change order, Included, Listens, add/remove) | enabled when connected and not stopping | html:76, js:551, js:1678-1689 |
| Mic state line | live display | "Mic: DJI mic · signal ok" (green) / "Mic: DJI mic · `<health>`" (amber, e.g. stalled / flat / closed) / "Mic: the robots' own (reachy1, reachy3) · DJI mic plugged in" / "Mic: DJI mic plugged in (used when the robots connect)" (green) / "Mic: no DJI plugged in · the robots' own mics" | who hears the people right now; DJI going silent or unplugged switches to robot mics by itself (hub adds a note) | always | html:80, js:572-591, cond:1328-1353 |
| Use robots' mics / Use the DJI mic | button (red / blue "back") | | `POST /api/group/mic {use: robots or people}`, instant, also mid-conversation | shown only when connected and a mic is in use; hidden when on robot mics and no DJI plugged; disabled while switching | html:81, js:592-597, js:664-676, cond:4076-4087 |
| Start hint | live display (amber when warning) | "Robots connected and listening. A mode button starts at once." / "One Reachy: Talk starts its own app. For the group modes, include a second Reachy or press + on its card for a laptop robot." / "Include at least two Reachys, or press + on a card to add a laptop robot." / "Simulation: this laptop speaks and listens." / "Not connected: a, b." / "N Reachys at the table." | what is missing before a start | when not running and not starting | html:82, js:553-567 |
| Checks pill | button / status indicator | "N checks ok" (green) / "N failed: name, name" (red) / "checking d/n" | toggles the chip list below | hidden until any check exists | html:83-84, js:602-629 |
| Service check chips | chip-list | per service: "`<name>` 1.2 s" (ok, green) / "`<name>`: failed" (red); hover = failure detail | each writer, speech-to-text, each voice, voice detection, checked with a real request | opens by itself when any check failed; else via pill | html:86, js:615-623 |

## 4. Conversation panel (transcript, live words, steer)

| Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|
| Conversation (N) | heading + count | N = lines that are not hub notes | | count hidden at 0 | html:93, js:1525-1526 |
| Jump to latest / Jump to latest (N new) | button | | scrolls to the newest line | shown when the operator scrolled up and new lines came; auto-follow resumes at the bottom or after 20 s | html:94, js:1483-1535, js:1614-1629 |
| Transcript empty state | text | "Nothing said yet. Press a mode when everyone is seated." | | when no lines | html:97, js:1524 |
| Transcript list | list, newest at bottom, scrolls alone | auto-follows; keeps position while reading; stays at bottom on resize | the whole conversation of this session (cleared on a new connection, not on a mode switch) | always | html:96, js:1504-1535, cond:4237 |
| Robot line: label | field | `character` at the time it was said (a later rename does not rewrite it); seat colour | who said it | robot rows | js:1593, css:225 |
| Robot line: robot name | field (small grey) | `who` (hub robot name) | shown only when it differs from the label | robot rows | js:1596-1597 |
| Robot line: move tag | chip | `move`: build, challenge, question, misunderstand, yes-but, joke, people, steer, wrap, intro; in interrupt mode the stance (e.g. oppose, mock, cut, approve, defend) | what kind of line it is | when present | js:1598, cond:394, cond:2788, cond:3282 |
| Robot line: latency | field | "`<n>` ms" = from the moment the room went quiet to the robot's first sound | response time | when `latency_ms` set (at first sound) | js:1601-1603, cond:2417 |
| Line time | field | `m:ss` since the session clock started | when it was said | all rows with `t` | js:1604 |
| Line text | text | size 18, auto direction (Hebrew/English); placeholder "…" for a robot line not yet filled, "listening…" for a people line not yet filled (italic grey) | what was said | always | js:1607-1609, css:232-233 |
| (cut off) | tag + strike-through | amber tag; the whole written text is struck through | the people talked over the robot and it stopped | when `cut` | js:1610, css:234-235 |
| People line | row (amber border, cream background) | label "People"; text, or "(said something the robots could not make out)" | what the room said | human rows | js:1592, css:238-239, cond:143 |
| Hub note | row (small italic grey, time first) | examples: "Group talk started", "operator: `<steer>`", "+1 min: it now ends at m:ss", "lab intro: every robot says a line about the lab", "closing: every robot says its last word", "the conversation is over", "time is up; the conversation is over", "X's voice failed: ...", "X could not speak: ...", "X was cut off by a noise; it goes on", "the director failed: ...", "the people are heard through DJI ...", "...: the robots' mics listen now", "ElevenLabs has N characters left, so the robots on Auto use other ...", "ElevenLabs refused ...", "X dropped out: ...", "X is not connected; it sits this one out", "the seats changed: reconnecting the robots", "could not understand the room (...); asking them to repeat" | system events inline with the conversation | note rows | js:1580-1586, css:240-241, cond:1168-1361, 2433-2828, 4192, 4233, 4500, 4587 |
| Current-line highlight | row state (light blue) | the last robot line while phase=speaking, or the last people line while phase=human | which line is being said now | while running | js:1538-1552, css:237 |
| Seat colour bar | row left border | one of 6 colours per robot, kept for the page's life, matches its card's top border and number badge | robot identity at a glance | robot rows | js:134, js:356-365, css:222 |
| Live people text | live display (amber box, label "People", max 3 lines) | last 160 characters of what the person is saying, typed out 2 characters every 25 ms with a block cursor `▌`; a correction keeps the matching start and retypes the rest | see the person's words while they talk | only while running and text exists; cleared when the line is final | html:99, js:693-719, css:117-125, cond:2915-2935 |
| Steer (label) + text box | text input | placeholder "e.g. make them argue about it, or ask the people a question"; max 300 chars kept by hub | tells the robots what to do next; the next line follows it, then the debate goes on | always (accepted any time; used on the next line) | html:100-106, cond:4189-4193 |
| Send | button (Enter works too) | | `POST /api/group/nudge {text}`; clears box, toast "Sent. The next line follows it."; empty -> focus box; failure -> toast "Not sent: ..." | disabled while sending | html:105, js:1724-1743 |
| Last steer: `<text>` | live display | one line, ellipsis | last instruction sent from this page | after first send | html:107, js:1733-1734 |

## 5. Robot cards (one per robot, left to right as the people see the table)

Scope per card = one robot. "Live" = takes effect mid-conversation (next line / next audio chunk). "Locked" = disabled while connected (until Disconnect).

| Label as shown | Kind | Options / range / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|
| Robots (header) + subline | text | "left to right, as the people see the table. Everything here changes at once, also mid-conversation." / when connected: "... Order, Included and Listens are fixed until Disconnect; everything else changes at once." | | always | html:113-114, js:766-768 |
| Save state (header) | live display | "Saving shortly…" / "Saving…" / "Saved." (green) / "Not saved: ... Trying again…" (red; retries every 3 s) / "Not saved: ..." on 409 (draft reloads from hub) | per-edit save feedback; typing saves after 700 ms, clicks after 150 ms | always | html:115, js:1360-1475 |
| Groups summary | live display | "all robots as one voice" (Choir) or "Group 1 (2), Name (3)" | | when groups exist | html:116, js:1182-1191 |
| Choir / Choir: on | toggle button (pressed = blue) | | every included robot says the same line at the same moment and moves the same; later-ticked robots join; toasts on/off; "Choir needs at least two included robots." | used from the next Start | html:117-118, js:1283-1287 |
| Groups… | button -> modal | | opens Groups dialog (section 7) | used from the next Start | html:119-120, js:1270-1282 |
| Empty state | text | "No Reachys yet. Connect them on the Robot Hub page and they appear here." | | no robots | html:123 |
| Seat number badge | display | 1..n in seat colour | seat position | always | html:222, js:891 |
| Label | text input | max 30, placeholder "Reachy Mini 1" | name in transcript and for the writer, never said aloud | live | html:223-224, js:1031-1034 |
| "Another robot has this label." | inline warning (red) | | duplicate label among included robots; hub refuses Start with "two robots are called X: give each its own name" | when duplicate | html:226, js:926-928, cond:4224-4226 |
| Robot name tag | display chip | hub robot name | real robot behind the label | hidden when label equals the name (ignoring case, spaces, - and _) | html:230, js:894-898 |
| Group tag | chip in group colour | group name; hover "In Group 1: talk and move together." | | when the robot is in a group with 2+ included robots | html:231, js:900-908 |
| Connection state | status indicator | Absent, Available, Connecting, Connected, Running, Degraded, Lost, Unavailable, Not connected; blue when connected | | always | html:232, js:89-99, js:910-913 |
| Mic level meter | meter | 0..1, green fill; grey ("deaf") when Listens is off; drops to zero 1.5 s after levels stop; hover shows echo check "its own voice peaked X dB over the learned echo (keep well under 8 dB for Normal)" | per-robot mic level, ~8 updates/s | always | html:233, js:726-740, js:915-922, css:411-418 |
| ‹ › | buttons | | move one seat left / right | locked; disabled at ends | html:235-236, js:937-938, js:1091-1105 |
| + | button | up to 5 laptop robots (sim:1..sim:5) | adds a robot that talks through this laptop's speaker, right after this card | hidden in Simulate; locked; disabled at 5 | html:237, js:941-947, js:1060-1073 |
| × | button | | laptop robot: removed; real Reachy: unticks Included | hidden in Simulate; locked | html:238, js:945-949, js:1076-1089 |
| Included | checkbox | default: ticked if connected | takes part; stays connected to the hub when unticked; card fades | locked | html:242, js:930-935 |
| Listens | checkbox | default on | its mic hears the people when the DJI is not used | locked | html:243 |
| Camera | checkbox | default on | can look through its camera when asked; never comments unasked | live | html:244, js:1038-1039 |
| Personality | textarea, 3 rows | placeholder "This robot's position on the topic and how it argues." | writer follows it on every line | live (next line) | html:246-249, js:1035-1037 |
| Voice: provider | select | Auto, ElevenLabs, OpenAI, OpenRouter, Gemini (daily cap); "(no key)" appended when the hub has no key; default Auto | which service speaks for this robot (voice never swaps mid-conversation per tooltip) | live setting, saved at once | html:252-253, js:114-115, js:953-956 |
| Voice: voice | select | ElevenLabs/Auto: "Default (`<name>`)" + lab voice list; OpenAI / OpenRouter / Gemini: "Default (`<id>`)" + "id (description)"; unknown kept as "`<id>` (not in the list)" or "(not here: uses Default)"; "Default (no ElevenLabs key)"; male voices only | the voice itself | live | html:254-255, js:863-884, cond:4034-4041 |
| Writer | select | Gemini 3.5 Flash (smart, ~2.5 s) [default], gpt-oss-120b (fastest, ~1.2 s), GPT-5.4 mini (~2.8 s), GPT-4.1 mini (OpenAI key), Flash-Lite (Gemini key); unknown kept | the model that writes this robot's lines | live (next line) | html:258-259, js:118-122 |
| Interrupting 0-5 | radio buttons | 0 never, 1 rarely, 2 now and then, 3 regularly [default], 4 often, 5 every time; selected = orange | how often it cuts in (interrupt mode) | live | html:261-270, js:963-968 |
| Gestures | segmented | Lively [default] / Calm | how much it moves and reacts | live | html:271-276, js:969-973 |
| Volume | slider + value | 0-250 %, step 5, default 150 %; slider tinted in seat colour | speech volume; 100 = natural, above boosts audio; applied when the drag ends | live (next audio chunk) | html:277-279, js:975-979, js:1046-1051 |
| "Voice: X, writing via Y" | live display | what this robot uses right now (hub falls back when a key fails) | | when connected; hidden on very narrow cards | html:281, js:981-989 |
| Copy to others | button -> modal | | section 8 | disabled with fewer than 2 robots | html:282, js:990 |
| Speaking card | card state (blue ring, light background) | | the robot with the floor is lit | phase = speaking | js:679-682, css:285 |
| Excluded card | card state (faded) | | Included unticked | | js:890, css:286-287 |

## 6. Session bar (shared by the whole session)

| Label as shown | Kind | Options / range / default | What it does | Live? | file:line |
|---|---|---|---|---|---|
| Topic | text | placeholder "What they talk about (empty: they choose)"; default empty | what the robots debate | live | html:128-131 |
| Language | select | Auto [default], Hebrew, English (unknown value kept) | Auto = language the people spoke last | live | html:132-134, js:100 |
| Minutes | number | 1-60, step 1, default 5 | session length; +1 adds time during a run | live | html:135-137 |
| Gap (s) | number | 0-5, step 0.1, default 0.6 | silence after a robot line before the next robot | live | html:138-140 |
| Voice threshold | number | 0-0.9, step 0.05, default 0.3; 0 = off | quieter voices do not take the floor | live | html:141-143 |
| People cut in | select | Off (only in the gaps), Careful, Normal [default], Eager | how easily talking over a robot cuts it off | live | html:144-151 |
| Audience mic | select + level meter | Auto (DJI mic, plugged in) / Auto (DJI mic when plugged in) [default], Robots' own mics, each laptop mic by friendly name ("DJI mic", "Laptop's built-in mic"), saved but missing: "(not plugged in)"; hover: "Hearing the audience through the X" | where the audience is heard; meter key `mic:people` | disabled while running (use the stage mic switch instead) | html:152-158, js:776-799 |
| Lab intro | checkbox | default on | Group talk starts with each robot saying a line about the lab | live | html:160 |
| Slow network | checkbox | default on | compressed voices (OpenAI, ElevenLabs) | live | html:161-162 |
| Heads turn the other way | checkbox | default off | mirror head turns | live | html:163-164 |
| Simulate on this laptop | checkbox | default off | all robots talk and listen through the laptop | disabled while connected | html:165-166, js:758 |
| ElevenLabs credits: N (low: robots on Auto use OpenAI) | live display (amber when under 1500) | | voice budget | when known | html:168, js:760-764 |

## 7. Groups modal

| Label | Kind | Options / default | What it does | file:line |
|---|---|---|---|---|
| Groups (title) + help text | modal | | explains talk-together (one voice, first robot's voice and settings, under the group's name) and move-together | html:173-176 |
| Group row: name | text, max 30 | placeholder "Group N" | name in transcript and for the writer | js:1201-1209 |
| Group row: kind | select | Talk and move together [default], Talk together, each moves its own way, Move together, each says its own lines | | js:145-146, js:1210-1222 |
| Group row: × | button | | remove group | js:1223-1227 |
| Group row: member ticks | checkbox list | each robot (label + robot name); greyed "taken" if in another group (ticking moves it); hover "Not included in the conversation: it sits this one out." | membership in seat order | js:1230-1256 |
| "Needs two included robots to count." / "Talks in X's voice and settings." | inline note | | | js:1258-1265 |
| Empty state | text | "No groups: every robot is on its own." | | html:178 |
| Add group / Everyone: one Choir / No groups / Done | buttons | | | html:180-183, js:1288-1298 |
| Esc / click outside | shortcut | | closes | js:1299-1302 |

## 8. Copy settings modal

| Label | Kind | Options / default | file:line |
|---|---|---|---|
| Copy `<label>`'s settings | modal title | | js:1310 |
| To | checkbox list | every other robot, all ticked | js:1312-1321 |
| What | checkboxes | Interrupting (0-5) [on], Voice provider [on], The voice itself [off], Writer [on], Gestures [on], Camera [on], Volume [on], Personality [off] | html:197-207 |
| Cancel / Copy | buttons | toast "Copied to a, b." or "Pick at least one robot and one setting." | html:209-212, js:1334-1352 |
| Esc / click outside | shortcut | closes | js:1353-1356 |

## 9. Keyboard shortcuts

| Key | Scope | What it does | file:line |
|---|---|---|---|
| 0, 1, 2, 3, 4, 5 | whole page, not while typing in an input/textarea/select, not with Ctrl/Alt/Meta, not while Copy modal open | sets EVERY robot's Interrupting level at once; toast "Interrupting 3 (regularly) for every robot." | js:1711-1722 |
| Enter | Steer box | sends the steer | html:100-106 |
| Esc | Groups / Copy modal | closes it | js:1300-1302, js:1354-1356 |

## 10. Toasts and confirmations (complete list)

"Could not add time: ...", "Could not get ready: ...", "Could not switch the mic: ...", "Could not start: ...", "Could not stop: ...", "Could not disconnect: ...", "Sent. The next line follows it.", "Not sent: ...", "Interrupting N (...) for every robot.", "Choir on: every robot at the table says the same line at once, also robots you tick later (from the next Start).", "Choir off: every robot is on its own (from the next Start).", "Choir needs at least two included robots.", "Copied to ...", "Pick at least one robot and one setting.", "The browser blocked the new tab. Allow pop-ups for the hub.", "`<conflict>` Press Talk again to take it over.", "The robot's app did not start.", "Talk failed: ...". There are NO confirm dialogs on this page: Stop, Disconnect, mode switch and Choir act at once (Stop is two-step by design: graceful, then "Stop now").

## 11. Data the hub sends that the page does NOT show today (available for the new design)

| Field | Where | Meaning | file:line |
|---|---|---|---|
| `heard_by` on people lines | group.turn | robot key whose mic heard the person best (writer is told "heard closest to X") | cond:2103, cond:3016, cond:3552 |
| `spoken` on cut lines | group.turn | the part actually said before the cut ("first words..."); page strikes through the full text instead | cond:2458, cond:3700 |
| `unspoken` | group.turn | the voice failed, not a sound was played | cond:2437 |
| `writer_ms`, `voice`, `voice_first_ms` | group.turn (set at first sound) | writer time, voice service used, voice time to first audio | cond:2025-2033 |
| `gesture`, `tone`, `saw`, `interrupting`, `mode` | group.turn | gesture name played, tone, what the camera saw, line opened with an interjection, mode at the time | cond:2786-2788, 2881-2884, 3280-3284 |
| `status.character` | group.status | label of the speaker (page re-derives it) | cond:2005 |
| `eleven_in_use`, `connected_seats`, `warm.at` | group.state | | cond:4032, 4052, 4321 |
| `POST /api/group/loudness` | route | per-robot live volume route (page uses config save instead) | api.py:58-61 |
| Session log file | disk | every line (with timings) appended to `robot-hub/logs/group-YYYYMMDD-HHMMSS.jsonl`, one file per connection | cond:51, cond:4129-4144, cond:4238 |

## 12. Requested in scope but NOT present on this page today

| Asked for | Status today |
|---|---|
| Live caption of the robot's words as they are spoken | Not present. A robot line appears whole at its first sound (with latency); there is no word-by-word robot caption. Only the PEOPLE get live typing. docs/STUDENT-APP-PLAN.md:199 lists it as a NEW requirement for reachy_app. |
| Pause | Not present. Only Stop (graceful) then Stop now; +1 for time. |
| Wizard of Oz (say box, cues, moves, quick saves, history) | Not on the group page. It lives in reachy_chat's `/show` board (outside this repo) and is planned per STUDENT-APP-PLAN.md S14/S16 (lines 23, 25, 188, 212, 223, 251). The Steer box is the only operator text input here. |
| End-of-session summary / export | Not present in the UI. After the end the transcript stays on screen (until the next connection clears it) with the notes "closing: every robot says its last word" and "the conversation is over"; the full record is the JSONL session log on disk (section 11). No download button. |
| heard_by display | Sent by the hub, not shown (section 11). |

---

## Flows

1. **Prepare (before the audience).** Open page -> cards appear for connected Reachys -> tick Included (2+), set labels, personalities, voice provider + voice, writer, levels -> set Topic, Language, Minutes -> Get ready -> watch the checks pill turn "N checks ok" and Get ready turn green -> status "Robots connected: pick a mode", hint "A mode button starts at once."
2. **Start.** Press Group talk / Interrupt mode / Free talk -> sub-line "connecting…" or "starting…" -> phase Starting -> optional Lab intro lines -> note "Group talk started" -> timer runs.
3. **During (operator loop).** Read big status line + lit card -> follow transcript (current line highlighted; scroll up to read, "Jump to latest (N new)" to return) -> watch live People text while someone talks -> Steer a new angle (Enter) -> change any robot's voice / writer / personality / level / volume on its card (saves at once, applies next line) -> keys 0-5 set everyone's interrupting -> switch mic if the DJI dies (or it switches by itself, with a note) -> +1 for more time -> switch mode in place by pressing another mode.
4. **Cut-ins.** Person talks over a robot -> line gets "(cut off)" and strike-through -> phase People speaking -> people line appears ("listening…" then the text) -> next robot answers. In Interrupt mode the status reads "X cuts in" and the line's move tag is the stance.
5. **End.** Timer reaches the limit (bar turns amber) or Stop -> "closing: each robot says its last word" -> Stop turns into "Stop now" (press to skip goodbyes) -> note "the conversation is over" -> robots stay connected (phase ready) -> start another mode at once, or Disconnect to change seats.
6. **Change seats.** Disconnect -> order arrows, Included, Listens, + and × unlock -> edit -> start again (hub reconnects; note "the seats changed: reconnecting the robots").
7. **One Reachy only.** Talk appears -> press -> new tab opens with that robot's own app; "in use: press to take over" on conflict.
8. **Errors.** Refused start/stop/ready -> red banner stays + toast; save fails -> "Not saved: ... Trying again…" every 3 s; 409 -> edits dropped, form reloads from hub; hub link lost -> pill "reconnecting".

## Notes for the new design

**Must stay IN CONTEXT (next to the conversation / on the robot), never in a global Settings page:**
- Mode buttons, Stop / Stop now, +1, Get ready, Disconnect, Talk, all on the live stage.
- Big status line + phase + detail + timer + bar: the operator's main read-out.
- Mic state + instant mic switch (it is used mid-conversation when the DJI dies).
- Service checks pill and chips (what failed, before and during).
- Transcript with every field: label, robot name, move tag, latency ms, time, cut off + strike-through, People rows, hub notes, current-line highlight, seat colours, Jump to latest.
- Live People typing with cursor; and (new requirement) a live robot caption.
- Steer box + Last steer.
- Per-robot card controls: voice PROVIDER and voice, writer, personality, interrupting 0-5, gestures, camera, volume, label, Included/Listens, order, +/×, live "Voice: X, writing via Y", mic meter, connection state, speaking highlight, Copy to others. The user explicitly wants provider choice right where the conversation is run.
- Choir and Groups next to the robots.
- Topic, Language, Minutes, People cut in: changed between and during conversations, keep beside the stage.
- Keyboard 0-5 (everyone's interrupting); note STUDENT-APP-PLAN.md:467 proposes dropping it, which conflicts with the "keep everything" rule.
- Save badge / save state, error banner, ElevenLabs credits note.

**Could live in an "advanced" fold of the same page (still on the page, not a separate Settings page):**
- Gap (s), Voice threshold, Slow network, Heads turn the other way, Simulate on this laptop, Audience mic default, Lab intro.
- Echo-check reading (today only a hover on the mic meter).

**Nothing on this page today belongs to a global Settings page** except API keys themselves (Keys panel on the main hub, referenced by "(no key)" markers and the start refusal "the hub needs an OpenRouter, OpenAI or Gemini key").

---

## Checker additions

A second pass over group.html (290 lines), group.js (1873) and group.css (519): every id, every listener, every option list, every hidden or conditional block, every keydown handler and every WebSocket handler. The backend (api.py, conductor.py) was read for event fields and limits. Below: 54 missing items in the same table format, then the corrections.

### A. Stage and status (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Stage | Starting details: "loading voice detection", "stopping the robots' own apps", "connecting to the robots" | live display (status detail) | | what the hub is doing while it connects (phase Starting). The mode name is NOT shown before them, because `S.running` is still false | phase = starting | js:408-413, cond:1184, 1215, 1237 |
| Stage | Disconnect progress: phase "Stopping" + detail "disconnecting the robots" | live display | | shown while Disconnect runs, then phase Not running | during Disconnect | cond:4627, 4633 |
| Stage | Stop reads "Stopping…" and is disabled while **Disconnect** is pending | button state | | Disconnect and Stop share the same `stopping` flag, so pressing Disconnect also greys Stop and changes its label | while a Disconnect request is in flight | js:1680, js:543-545 |
| Stage | Phase label for an unknown phase | live display | the raw phase string | the page shows any phase it has no word for as the hub sent it | defensive | js:396, js:404 |
| Stage | Idle while running: "Running" | live display | | big line when phase=idle but `running` is true | rare transition | js:395 |
| Stage | Get ready progress shown ONLY by the button "Getting ready…" + pill "checking d/n" | live display | | the hub's ready-phase texts are never shown (see corrections) | during Get ready | js:536-537, js:613-614 |
| Stage | Pending check chip: "`<name>` 0.0 s" (no colour) | chip state | | a check that has not answered yet (neither ok nor failed) | while checking | js:619-620 |
| Stage | Failed check chip hover: "`<ExceptionType>`: `<message>`" (up to 200 chars) | tooltip | | exactly why that service failed | hover a red chip | js:621, cond:4352 |
| Stage | Timer total follows the Minutes box while NOT running | live display | | typing in Minutes redraws "/ m:ss" at once (from the draft, before the save) | not running | js:427-428, js:1387 |
| Stage | Timer stops outside live phases | live display | | the clock ticks on the page only in speaking, listening, human and thinking; it holds still in starting, stopping and ready | always | js:131, js:420-424 |
| Stage | Talk: placeholder tab titled "Starting `<name>`…", text "Starting `<name>`'s app… This tab opens it as soon as it is ready." | new tab | | the tab opens on the click (so it is not a blocked pop-up), then goes to the app's URL. An app already RUNNING (checked via `GET /api/robots`) opens without a second launch; on failure the tab closes by itself | Talk pressed | js:464-498 |
| Stage | Talk tooltip with the robot's name: "Start `<name>`'s own app: one robot talking with the people (Gemini Live and the other voices, persona, Show mode)…" | tooltip | | names the robot and what that app has | Talk visible | js:456-459 |
| Stage | Mode button disabled when that mode is already running | button state | | pressing the running mode does not restart it; Stop and press it again, or press another mode to switch | running in that mode | js:528 |

### B. Closing and end of session (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Transcript | Closing lines | robot rows (move tag "wrap") | turn field `closing: true` | Order: every robot except the one that spoke last, then that robot. Each line is written while the previous one plays. During closing nobody is cut off and the people get no answer | after Stop (graceful) or when time is up | cond:2796-2826 |
| Transcript | "`<label>`'s closing line failed: ..." | hub note | | a robot skips its goodbye | closing | cond:2812 |
| Hub | `more_time` refusals: "no conversation is running", "the robots are already saying goodbye" | toast text (via "Could not add time: ...") | | the hub refuses +1 | the press arrives as the conversation ends | cond:4582-4585 |
| Hub | After Stop now: phase "ready", detail "robots connected; press a mode to start" (the page hides it) | status | | the robots are quiet and stay connected | after stop | cond:4607-4608 |

### C. Transcript and live text (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Transcript | Full rebuild | behaviour | | when the hub's line ids stop matching the page's (a new connection, a reset), the page rebuilds the list and scrolls to the bottom, whatever the reading position | on state | js:1508-1513, js:1529 |
| Transcript | Robot line with no label: name fallback chain | field | `character` at the time -> card label -> robot name -> `who` -> "Robot" | | robot rows | js:1593 |
| Transcript | Hub note time stamp | field | `m:ss` printed BEFORE the note text | | notes with `t` | js:1583 |
| Live people text | "People" heading inside the box | label (CSS ::before) | | | while shown | css:123-125 |
| Live people text | Hidden as soon as the conversation is not running | rule | | the page shows live words only while `running`; the last words before a Stop disappear | not running | js:697 |

### D. Steer (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Steer | One-slot queue | behaviour | | the hub keeps only ONE pending steer: a second Send before the next line replaces the first (both still appear as "operator: ..." notes) | always | cond:4189-4193 |
| Steer | Focus returns to the box after Send (success or failure) | behaviour | | quick steering from the keyboard, one after another | after Send | js:1741 |
| Steer | "Last steer: ..." is page-local | scope | | lost on reload and not seen in a second browser tab; the shared record is the transcript note "operator: `<text>`" | | js:1733-1734, cond:4191 |

### E. Robot cards (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Card | Voice remembered PER PROVIDER | behaviour | Auto and ElevenLabs share `voice_id`; OpenAI and OpenRouter share `openai_voice`; Gemini uses `gemini_voice` | switching the provider shows (and later restores) the voice chosen earlier for that provider; nothing is lost on a switch | live | js:125-126, js:957-958, js:1043 |
| Card | Provider "(no key)" never on Auto | option label | | Auto always appears without a marker; another provider gets "(no key)" only when the hub reports no key for it (`providers[id] === false`) | | js:955-956 |
| Card | Interrupting picker tooltip (whole row): "`<n>`: cuts in `<never/rarely/...>` (interrupt mode)" + per-button tooltips ("Never: waits until the person finishes", "Rarely, after the person talks a while", "Now and then", "Regularly", "Often, and piles on", "Every time the person talks") | tooltip | | explains the current level | hover | js:968, html:263-268 |
| Card | Gestures tooltips: Lively "Moves its head and antennas on almost every line, and reacts while the others talk." / Calm "Moves on about half of its lines and rarely reacts to the others." | tooltip | | | hover | html:273-274 |
| Card | Volume tooltip "100 = natural level; the robot's speaker is already at its maximum, above 100 the hub boosts the audio"; the number updates while dragging and saves on release | tooltip + live value | | | | js:979, js:1046-1051 |
| Card | + / × tooltips by state: "Disconnect first to add a robot", "No more robots fit", "Add a robot here (it talks through this laptop's speaker)", "Disconnect first to remove a robot", "Remove this robot" (laptop robot), "Take this Reachy off the table (tick Included to bring it back)" | tooltip | | | hover | js:946-949 |
| Card | × disabled for a real Reachy that is already unticked | button state | | | Included off | js:945 |
| Card | New laptop robot defaults | behaviour | robot name "laptop", Included on, **Listens off**; the hub picks the label, the seat and a voice no other robot has | the first save sends only `{key, included, listen:false}` | after + | js:1060-1071, js:1404-1406 |
| Card | Group tag hidden when the robot is not Included | rule | | | | js:903 |
| Card | Keyboard focus stays on the same robot's arrow after a move | behaviour | | | ‹ › | js:1098-1104 |
| Cards | Layout by robot count | layout | 1-2 robots: conversation and robots split 50/50; 3: 37/63; 4+: 30/70 with tighter cards ("many"); up to 5 side by side; 6+ go in two rows and the whole page scrolls instead of fitting one screen | | always | js:850-856, css:37-40, css:53-67, css:279 |
| Cards | Narrow card (under 260-270 px): the "Voice: X, writing via Y" line and the Personality label are hidden; labels sit above the fields | layout | | so 5 robots fit on a laptop | 4-5 robots | css:385-406 |
| Page | Below 1100 px wide or 620 px tall: one column in the order stage, conversation, robots, session; below 600 px the mode buttons go 2 per row and the Steer label sits on its own line | layout | | | small windows | css:453-472 |

### F. Groups and Choir (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Groups | Choir follows the ticks by itself | behaviour | | ticking or unticking Included updates the Choir's members and saves at once (no button press) | Choir on | js:832, js:1155-1167 |
| Groups modal | Ticking a member by hand turns the Choir into an ordinary group | behaviour | | `whole_table` becomes false; members stay in seat order, so the FIRST robot (the group's voice) is clear | in the modal | js:1244-1253 |
| Groups modal | Typing a group name renames the card tags live; "×" tooltip "Remove this group (its robots go back to being on their own)"; name tooltip "The group's name in the transcript and for the writer, when it talks as one." | behaviour + tooltips | | | | js:1208-1227 |
| Groups head | Summary tooltip "Groups. Used from the next Start." | tooltip | | reminds the operator that groups do not change a running conversation | only while running | js:1189-1190 |

### G. Saving, loading, errors, shortcuts (missing)

| Section | Label as shown | Kind | Options / default | What it does | Visible / enabled when | file:line |
|---|---|---|---|---|---|---|
| Page | First-paint states before the hub answers: badge "loading", "Mic: checking", status "Not running", timer "0:00 / 5:00", pill "checks" (hidden) | loading state | | | until the first state | html:22, 47, 52, 80 |
| Save | A save during a run sends only the live session keys | behaviour | topic, language, minutes, listen_gap_s, heads_mirror, voice_min_level, barge_in, slow_network, lab_intro, groups | simulate, people_mic and the laptop robots are NOT sent while running; the robots' own settings always are | running | js:128-129, js:1418 |
| Save | An edit after Get ready re-makes the first lines (3 s later) | behaviour | | a mode button still speaks at once, with the NEW topic or personalities | connected, not running | cond:3949-3950 |
| Errors | Error texts from requests: "the hub did not answer (...)", "the hub answered `<code>`", "invalid settings", a validation message, "unknown mode '...'" | banner / toast text | | | refused or failed requests | js:1390-1399, js:1646, cond:4199 |
| Shortcut | 0-5 still works while the **Groups** dialog is open | shortcut quirk | | only the Copy dialog blocks it; with focus on a button in Groups, a digit changes every robot's level | Groups modal open | js:1713 |
| Shortcut | Enter in the Copy dialog | shortcut | | the dialog is a form, so Enter runs Copy | Copy modal | html:190, js:1334 |
| Tooltip | Placement | behaviour | below the control; flips above when there is no room; kept 8 px inside the window | | hover | js:1842-1851 |

### H. Hub data not shown (add to section 11)

| Field | Where | Meaning | file:line |
|---|---|---|---|
| `gaps`, `gap_ms` | group.turn / log | how many times and for how long the voice ran dry mid-line (stutter) | cond:2363-2366 |
| `buffer_ms` | group.turn / log | how long the line waited for enough audio before it played | cond:2385-2388 |
| `closing` | group.turn | the line is a goodbye | cond:2819 |
| `stance` | line (interrupt mode) | the reaction kind; today the page shows it only through the move tag | cond:2246, 3612 |
| `group.status.mode` | group.status | mode at the time of the status | cond:4111 |

### Corrections to the inventory above

1. **Section 3, Status detail (line 48):** the hub's ready-phase texts ("getting ready: checking every service", "getting ready: recording the interjections…", "ready: press a mode to start", "connected, but X failed the check", "robots connected; press a mode to start") are **never shown**: `renderStatus` blanks the detail whenever phase = ready (js:408-409). The new design should either keep it that way or show them on purpose. The detail texts the page does show are the starting texts (section A), "answering the room", "waiting for the rest", "waiting for the person", "answering the person" and "disconnecting the robots".
2. **Section 6, Gap (s):** the page allows 0-5, but the hub clamps it to **0.2-3.0** s. **Minutes:** the page minimum is 1; the hub clamps to 0.5-60. **Topic:** the hub keeps 500 chars (cond:3941-3944). The new design should use the hub's ranges.
3. **Section 6, Minutes "live":** an edit mid-run moves the end time at once (the limit is minutes x 60 plus the +1 additions), and the timer total follows at the next state (cond:1991-1992). It is not only "for the next session".
4. **Section 5, Robot name tag (line 104):** it is also shown when the label is EMPTY. It is hidden only when a label is set and equals the robot name (js:898).
5. **Section 8, Copy "The voice itself":** copies all three voice fields (ElevenLabs, OpenAI/OpenRouter, Gemini), not only the current provider's (js:1340).
6. **Section 9, keys 0-5:** only the Copy dialog blocks them, not the Groups dialog (see G).
7. **Section 2, error banner:** a "Could not start" error clears by itself once a conversation is running; other local errors stay until the next successful action of the same kind (js:332, js:656, js:1662, js:1697).
