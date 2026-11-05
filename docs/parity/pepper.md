# Parity inventory: Pepper, NAO, Furhat operator UIs

Read-only inventory of what exists today, so the new design can show all of it. Paths are relative to `robot-hub/`.

**Files read (lines):**
- `pepper_app/static/index.html` (274), `pepper_app/static/app.js` (413): the Pepper Operator dashboard, which the hub's Launch opens on :8780
- `pepper_app/static/screen.html` (70), `pepper_app/static/screen-render.js` (124): Pepper's chest tablet, plus the dashboard's preview of it
- `pepper_app/static/sim.html` (236): the Pepper simulator (no robot)
- `pepper_dashboard/index.html` (232): the older "Pepper Say-It" dashboard. Same port 8780, and the hub no longer launches it.
- Backend, read only for values: `pepper_app/server.py` (892), `brain.py` (923), `script.py` (765), `speech.py` (109), `screen.py` (227), `robot.py` (293), `agent/pepper_agent.py`, `__main__.py` (39), `sim.py` (283), `pepper_dashboard/pepper_dashboard.py` (466)
- Hub: `hub/adapters/naoqi.py` (885: NAO and Pepper adapters), `hub/adapters/furhat.py` (395), `hub/adapters/nao2/agent2.py` (252), and the parts of `hub/core.py`, `hub/keys.py`, `web/index.html` (card template) and `web/app.js` (posture, WiFi, launch, battery, key picker) that these robots use

**Item count:** 119 items (H1–H19, P1–P62, T1–T8, S1–S10, L1–L11, B1–B9).

---

## 1. Hub robot card: Pepper, NAO and Furhat specifics (`web/index.html` 228-302, `web/app.js`)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| H1 | Connect | button (pill) | – | Connects to the robot. The robot then says its line out loud (see H17). | Card present | web/index.html:234 |
| H2 | Disconnect | button (pill) | – | Disconnects. For Pepper it first calls `/api/shutdown` on the dashboard, which hides the tablet page, restores the vendor dialog and stops the robot agent. Then it hard-kills the process. | Card connected/running | web/index.html:231; naoqi.py:869-879 |
| H3 | Robot name + detail line | live display | – | Name, plus adapter notes such as "head <id>", "Furhat voice set to X (was Y)", "no FURHAT_API_KEY set…" or "Pepper's dashboard was already running" | always | web/index.html:242-243; naoqi.py:449, furhat.py:316 |
| H4 | Status | status indicator (dot + text) | Absent / Detected / Connected / Running / Error; also "connected, but could not speak" | Robot state | always | web/index.html:246-248 |
| H5 | Battery (otherwise Address) | live display | "N%". The `low` style applies below 20%. | **NAO and Pepper both report battery**: Pepper inherits `reports_battery=True` from the NAOqi adapter, although a code comment says "only NAO". Furhat shows its IP address instead. | always | web/app.js:365-388; naoqi.py:275, 432-444 |
| H6 | Speaking key | select | "Default: <key>" / "Default (first Gemini key)" / "No keys — add one below", then each saved key, marked "— cannot speak yet" when that provider cannot speak | Chooses which saved key Pepper's app gets at launch. Every other provider's first key is passed too, as environment variables. | **Pepper only** (`uses_speech_key`) | web/index.html:258-261; app.js:466-495; keys.py:152-164; core.py:537-540 |
| H7 | Sit | button | – | NAO sits, then its motors turn off. Refused if any joint is at 70 °C or hotter. | **NAO only** (type `naoqi`); enabled when Connected/Running, not launching and not already moving | web/index.html:266; app.js:261-302; naoqi.py:103-118 |
| H8 | Lie down | button | – | NAO lies on its back, then its motors turn off. Same 70 °C guard. | NAO only | web/index.html:268 |
| H9 | Stand up → Confirm | button, two taps | Arms for 5 s, and the label changes to "Confirm" | Stands with motors on. Limit 60 °C. The first tap shows a warning: "NAO will stand up, motors on — make sure someone is next to it, then tap Confirm." | NAO only | web/index.html:270; app.js:250, 342-355 |
| H10 | Posture note | status line | Spinner "Sitting down… / Lying down… / Standing up…"; the armed warning (amber); a refusal (red), e.g. "NAO's right hip (RHipPitch) is at 72 °C — let it cool below 70 °C"; on success "NAO is sitting, motors off (hottest joint: right knee 48 °C)" or "already …, nothing moved" | Result of the posture command, shared by every open hub page | NAO only, when there is text | web/index.html:273; naoqi.py:512-566 |
| H11 | Add WiFi… | button (disclosure) | – | Opens the join form | NAO, Pepper, wireless Reachy; robot present | web/index.html:279; app.js:189-195 |
| H12 | Hotspot name / Password / Join (+ "This is the lab WiFi" checkbox, wireless Reachy only) | form: text, password, button, checkbox | Name 1-32 bytes; password 8-63 characters | Joins the robot to that network over SSH and connmanctl, at once, and the robot remembers it. Hint: "Turn that hotspot on first (2.4 GHz). The robot moves to it now and remembers it." | same as H11 | web/index.html:280-287; app.js:196-239; naoqi.py:473-500 |
| H13 | WiFi note | status line | "Joining “X”… up to a minute. Keep that hotspot on." / on success "Pepper joined “X” and will remember it. Connect this laptop to “X” to see it again." / error "the robot is still on this network -- it could not join … (check the password)" | Join progress and result | after Join | app.js:209-235 |
| H14 | Launch / Launching… N s / Open | primary button + elapsed seconds | – | **Pepper:** starts `pepper_app` on :8780 and opens it in a waiting tab. If no GPT key is set it still opens, with a note. **NAO:** starts NAO_LLM (its own control panel), deploying the robot speaker server first. The first run downloads a speech model of about 140 MB, with a wait of up to 20 min. **Furhat:** opens Furhat Studio's own web page at `http://<ip>/`, with the note "Studio will ask for the 'admin' password". The label reads "Open" once the robot is running. | Connected | web/index.html:290; app.js:151-180, 939-990; naoqi.py:662-714, 841-867; furhat.py:388-395 |
| H15 | Launch note | status line | "Starting its system — this can take a couple of minutes." / "Launch failed: …" | – | while launching, or after a failure | web/index.html:293 |
| H16 | Conflict box: Override / Dismiss | inline alert + 2 buttons | – | NAO claims the laptop's *default input* microphone. If another robot holds that device, a conflict appears and the user can override it. Pepper and Furhat claim nothing. | on conflict | web/index.html:295-301; naoqi.py:569-575 |
| H17 | Connect announcement | spoken + log | Text set per robot type in `config.toml`: "I am Pepper, I am connected and ready to run." / "I am NAO…" / "I am Furhat…" | The robot speaks on a manual connect. It stays silent on auto-reconnect so it does not interrupt a demo. If speaking fails, the status reads "connected, but could not speak". | on Connect | core.py:424-442; config.example.toml:41-125 |
| H18 | Furhat voice on connect | automatic | Setting `voice`, or a fallback voice when the cloud voices are not loaded yet | Switches Furhat to an English voice before it speaks, and reports that in the detail line | Furhat connect | furhat.py:295-318 |
| H19 | Hub log lines for these robots | log | e.g. "Pepper: speaking through <label> (...<last4>; how)" | – | hub log panel | core.py:540-543 |

## 2. Pepper Operator dashboard (`pepper_app/static/index.html` + `app.js`)

It runs on port 8780. The controls answer requests from this laptop only (`only_this_laptop` middleware); the tablet can reach only `/screen*`. Every setting below is saved per laptop in `pepper_app/data/settings.json`. Defaults are in `server.py:44-47`.

### 2a. Title bar (always visible)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P1 | "Pepper Operator" | title | – | – | always | index.html:91 |
| P2 | Robot pill | status indicator | Dot: green = connected, amber = deploying/starting, red = otherwise. Text: "<ip> · battery N%, charging" / "starting its agent…" / the failure detail / "dashboard server stopped". Tooltip: "<name> · NAOqi <ver> · <posture> · speaker: <mode>" | Robot link plus battery. **The failure detail can be the firewall hint**: "the agent never connected back to <laptop>:8782 -- is Windows Firewall blocking Python on this network?" | always | index.html:92; app.js:83-90, 407-410; robot.py:117-122 |
| P3 | Screen pill | status indicator | Dot green/red. Text: "<tablet ip> · live Ns" / "not connected yet · people see nothing" / "lost Ns ago · people see nothing" | Whether Pepper's chest tablet is calling in (heartbeat every 500 ms) | always | index.html:93-96; app.js:91-94 |
| P4 | Reload (inside Screen pill) | button, small | – | Re-opens the tablet web page on Pepper. The server also does this by itself every 20 s while the tablet is silent. | only when the screen is NOT connected; needs the robot | index.html:95; app.js:95, 241; server.py:221-226 |
| P5 | Volume | slider + value | 0-100, step 5, initial 50. Synced from the robot unless the slider has focus; shown as "N%". | Pepper's speaker volume. Sent 250 ms after the slider stops moving. | needs the robot | index.html:97-100; app.js:99, 365-367 |
| P6 | "No OpenAI key · add a GPT key in the hub" | warning badge | – | Says the AI and the AI voice will not work | only when the dashboard has no OpenAI key | index.html:101-102; app.js:389 |
| P7 | Stop everything | danger button | – | Ends the conversation, flushes queued speech, stops the robot's speech and motion | always | index.html:103; app.js:332; server.py:718-726 |
| P8 | AI failure banner: "The AI stopped answering. Speak for Pepper from Wizard of Oz." + **Restart AI** | floating banner + button | – | Shown while the AI is stuck (no output for 10 s). When it appears, the two Wizard of Oz cards flash. Restart AI restarts the AI session, keeps the history and does not greet again. | conversation running and stuck | index.html:107-111; app.js:131-134, 331; server.py:424-429 |
| P9 | Toast | toast, bottom-right, 4.5 s | Server error text, "The dashboard server is not answering", "Turning X into slides…", "N emoji allowed…", "Upload a presentation first", "No camera picture yet" | Feedback for any failed control | on events | index.html:112; app.js:29-33 |

### 2b. Conversation card (column 1)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P10 | State badge | status chip | IDLE / WAITING FOR ANSWER / THINKING / SPEAKING / PAUSED · YOU / AI STUCK, each with its own colour | AI state | always | index.html:122; app.js:8-13, 119-122 |
| P11 | Model label "GPT Realtime 2.1" | static text | **Never updated.** The scripted experience actually reacts with `gpt-4.1`, and the server sends `ai.model`, but the page ignores it. | – | always | index.html:123; script.py:39, 765 |
| P12 | Step "n/N Title" | live display | "–" when idle. The scripted demo has 9 steps: Welcome, Choice, Comfort, Faces: happy, Faces: surprised, Story, Look, Feedback, Bye. | Progress through the experience | always | index.html:124; app.js:128; script.py:97-224 |
| P13 | Experience | select | "Feelings Together (demo) · scripted" (**default**); "Feelings Together (research demo) · with emoji" (**shown greyed "(not for the demo)", cannot be selected, and the server rejects it**); "Free conversation" (one-sentence replies, no screen, no gestures) | Which conversation runs | always | index.html:126; app.js:376-379; brain.py:137-146; server.py:601-602 |
| P14 | Engine | select | "GPT Realtime (speech to speech)" / "ElevenLabs ears + voice, GPT brain" (**default eleven**) | How Pepper hears and speaks. ElevenLabs gives stronger Hebrew; GPT still decides what to say. Changing it re-warms the offline phrases. | always | index.html:128; brain.py:50-51; server.py:608-609 |
| P15 | Language | select | Auto lang / English / Hebrew (**default Hebrew**) | Conversation language. It also picks which walk line is said before Walking (P38). | always | index.html:129-131 |
| P16 | Voice | select (its options depend on Engine) | GPT voices: marin (default), cedar, alloy, ash, ballad, coral, echo, sage, shimmer, verse. ElevenLabs: the account's voices as "Name (language)", default a premade female voice. Empty state: "No ElevenLabs voices (key?)". | Pepper's voice for **both the AI and Wizard of Oz** (the operator never picks a separate voice). Saved as `voice` or `el_voice` depending on the engine. Re-warms the phrases. | always | index.html:134; app.js:165-174, 335; brain.py:49 |
| P17 | Vision | toggle chip | off by default | The AI sees Pepper's camera. Also raises the camera rate from 0.5 to 2 fps. | always; applies live during a conversation | index.html:137; server.py:242-246, 606-611 |
| P18 | AI drives screen | toggle chip | on by default | The AI puts choices and slides on the tablet by itself | always; applies live | index.html:138 |
| P19 | Gestures | toggle chip | on by default | The AI may wave and nod while talking. Also controls the body animation when Pepper speaks in its own voice. | always | index.html:139; server.py:466-470 |
| P20 | Start conversation / End conversation | primary/danger button | – | Start opens the mic, pauses the vendor app's dialog, shows the welcome screen and starts the brain. Errors: "Pepper isn't connected yet -- wait for the Robot pill to turn green", "could not open the microphone…" | always; disabled during the request | index.html:142; app.js:123-124, 325-329; server.py:365-403 |
| P21 | Resume AI | button (violet) | – | Hands the conversation back to the AI after a Wizard of Oz pause | only when running and paused | index.html:143; app.js:125, 330 |
| P22 | Turns | counter | – | Number of turns so far | always | index.html:145 |
| P23 | Clock mm:ss | timer | – | Time since the conversation started | always; ticks while running | index.html:145; app.js:135-141 |
| P24 | Latency "~N ms" | live display | "–" | Reply latency | always | index.html:145; app.js:127 |
| P25 | Turn info | live display | "Waiting for an answer · m:ss · re-asks at 12s" / "… · asked again, waiting" / "… · no question open" / "Pepper is thinking" / "Pepper is speaking" | Strict-turn status. Pepper repeats an open question **once** after 12 s of silence. | row visible while running and not paused | index.html:149-150; app.js:145-161; brain.py:59 |
| P26 | Repeat question | button | – | Pepper asks its question again | same as P25 | index.html:151; app.js:162 |
| P27 | Skip | button | – | Pepper says it is fine and moves to the next step | same as P25 | index.html:152; app.js:163 |

### 2c. Wizard of Oz · Say card (column 1)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P28 | "N offline" | live display | – | How many quick phrases are pre-made in the current voice, so they play without the network | when the count is known and greater than 0 | index.html:159; app.js:100; server.py:490-497 |
| P29 | pause AI | checkbox | **checked** | On: when you talk, the AI stops and waits for Resume AI (P21). Off: it only cancels the AI's current reply. | always | index.html:160-161; server.py:445-449 |
| P30 | tell AI | checkbox | **checked** | The AI is told what Pepper said, so it can continue from there | always | index.html:162-163 |
| P31 | Quick phrase chips | chip grid, 2 columns | 10 phrases: 6 English, 4 Hebrew, each tagged EN/HE (e.g. "Sorry, I didn't catch that…", "Please look at my screen and choose one.", "Great choice!", "Hello! I am Pepper…") | One click speaks the phrase in the conversation's voice | always | index.html:165; app.js:383-388; speech.py:33-44 |
| P32 | Free text box | textarea (direction follows the text) | English or Hebrew. **Enter = talk, Shift+Enter = new line.** Server cuts at 600 characters. | What Pepper should say | always | index.html:167-168; app.js:346 |
| P33 | Talk | button (violet) | – | Speaks the text in the conversation voice. Falls back to Pepper's built-in voice for English only; Hebrew fails with an error. The chat shows it as "Pepper · you (Wizard of Oz)". | always | index.html:170; server.py:431-464 |
| P34 | Stop | button | – | Stops speech now; also cancels the AI's current reply | always | index.html:171; server.py:673-679 |

### 2d. Wizard of Oz · Move card (column 1)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P35 | Stop motion | button | – | Stops the animation, walking and base movement | needs the robot | index.html:179; app.js:364 |
| P36 | Gesture grid | 8 buttons | Wave, Nod yes, Shake no, Both arms up, Arms wide, Right arm up, Left arm up, Open/close hands | Plays a gesture tested on this robot. The chat shows the event "Gesture: <name>". | needs the robot | app.js:5-7, 349-355; server.py:681-689 |
| P37 | Walking | button (violet) | Tooltip: "1 m forward, turn around, 1 m forward, turn around. Unplug the charger first; keep 1.5 m clear." | Pepper first says a walk line in the conversation voice, in Hebrew or English, then walks | needs the robot; **refused while charging** ("unplug the charger and close the flap…") | app.js:352; server.py:472-488, 38-40 |
| P38 | Head Left / Center / Right | 3 buttons | Yaw ±0.5 rad | Turns the head (face tracking is paused during the move) | needs the robot | index.html:184-187; pepper_agent.py:489-496 |
| P39 | Stand | button | StandInit | Returns Pepper to the standing pose. Stand is the only posture tested on Pepper. | needs the robot | index.html:189; pepper_agent.py:503-506 |
| P40 | Face tracking: on/off | toggle button | **The label starts at "on" whatever the robot is doing.** The real value (`awareness`) is in the robot's status but is not shown. | Pepper turns its head toward faces | needs the robot | index.html:190; app.js:358-363 |

### 2e. Live conversation + Event log (column 2)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P41 | Mic status | live display + level meter | (empty when idle) / "Pepper speaking · mic shut" / "AI paused · you have the floor" / "Pepper's turn · mic shut" / "hearing: <live partial transcript>" / animated "listening" wave plus a level bar (mic level ÷ 8000) | What the mic is doing right now | while a conversation runs | index.html:200; app.js:104-116 |
| P42 | Chat transcript | live list | Bubbles: **Pepper** (grey; faded while partial, updated as the text streams), **Person** (blue, right), **Pepper · you (Wizard of Oz)** (dashed violet). Event pills (amber): "Conversation started/ended", "AI put choice: A / B on the screen", "You put slide 3 on the screen", "Gesture: wave". Tap pills (green): "Tapped the screen: <label>". Keeps 300 lines and auto-scrolls only when you are already at the bottom. Empty state: "Press “Start conversation” and Pepper begins talking". | Full conversation record | always | index.html:202; app.js:50-80, 392 |
| P43 | "Heard, not used: “…” (reason)" + **Accept** | chat row + button | – | Speech the system ignored as noise or not an answer. Accept counts it as the person's answer. | inside the chat, when it happens | app.js:52-59; server.py:655-660 |
| P44 | Event log | log panel (monospace) | "HH:MM:SS LEVEL message", coloured INFO/WARNING/ERROR. Keeps 600 lines and auto-scrolls when at the bottom. Includes robot agent lines, options changes, "woz: say … via ElevenLabs voice · AI paused", and "STOP EVERYTHING". | Diagnostics | always | index.html:212; app.js:37-45 |
| P45 | Copy logs + "Copied" / "Copy failed" | button + feedback | – | Copies the whole log to the clipboard | always | index.html:208-209; app.js:46-48 |

### 2f. Pepper's camera (column 3)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P46 | "frame sent to AI N s ago" | live display | – | When the AI last received a frame | after the first vision frame | index.html:222; app.js:321-322 |
| P47 | Camera | select | Top (default) / Bottom | Which head camera to use; saved | needs the robot | index.html:223; app.js:320 |
| P48 | faces | checkbox | checked | Draws green face boxes over the picture | always | index.html:224; app.js:312-313 |
| P49 | Save | button | – | Downloads the current frame as `pepper-camera-<timestamp>.png` | always (toast if there is no frame yet) | index.html:225; app.js:315-319 |
| P50 | Camera view + LIVE badge "LIVE · W×H · top/bottom" | live image | Empty state "No camera picture yet". 0.5 fps, or 2 fps with Vision on. | Pepper's view | always | index.html:228-235; app.js:302-314 |

### 2g. On Pepper's screen (column 3)

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| P51 | "by the AI" / "by you" | live display | – | Who put the current page on the tablet | when known | index.html:242; app.js:192 |
| P52 | Last tap | live display | "click an option = tap for them" until a tap happens, then "last tap: <label> · time" | What the person last tapped | always | index.html:243; app.js:398-399 |
| P53 | Emoji test | button | Tooltip says how many emoji are allowed now | Shows every candidate emoji (~40), numbered, on the tablet, to find the ones that draw as empty boxes | always | index.html:244; app.js:242 |
| P54 | Mark broken | button → browser prompt | Prompt: "Which numbers show as empty boxes or wrong on Pepper's tablet? (e.g. 4, 17, 30). Empty = all fine.", prefilled with the current list | Saves the broken emoji, which the AI then never uses. Toast: "N emoji allowed on Pepper's screen". | only while the emoji test page is shown | index.html:245; app.js:243-250; server.py:768-783 |
| P55 | Tablet preview | live mirror, clickable | – | Draws exactly what the tablet shows. **Clicking a choice option taps it on the person's behalf.** | always | index.html:248-249; app.js:189-196 |
| P56 | "Screen not connected / People in front of Pepper see nothing" | overlay | – | – | when the tablet is not calling in | index.html:250-252 |
| P57 | Presentation | select | "<name> · N slides" / "No presentations yet — upload one" | Current slide deck. It is also handed to the AI, which can show its slides. | always | index.html:256; app.js:198-206, 231; server.py:355-363 |
| P58 | Delete | button → confirm dialog | "Delete “<name>” (N slides) from this laptop?" | Deletes the deck | always | index.html:257; app.js:236-240 |
| P59 | ◀ Prev · "n/N" · Next ▶ | buttons + counter | Wraps around | Shows the slide on the tablet. The counter also shows upload progress. | always | index.html:258-260; app.js:223-233 |
| P60 | Home / Clear | 2 buttons | – | Home shows the welcome page; Clear shows a black screen | always | index.html:261-262; app.js:234-235 |
| P61 | Upload (+ drag and drop onto the card) | file input + drop zone | Images or PDF, several at once. A PDF is turned into one PNG per page (at most 60 pages). Other files get the toast "only images and PDFs (save PowerPoint as PDF first)". The deck is named after the file, or "N images". | Makes a new presentation | always | index.html:263-264; app.js:252-299 |
| P62 | Thumbnail strip | clickable thumbnails | Current slide outlined; tooltip shows the slide title | Jumps to a slide | when the deck has slides | index.html:266; app.js:208-217 |

## 3. Pepper's chest tablet (`screen.html`, `screen-render.js`): what visitors see

| ID | Item | Kind | Details | Where |
|---|---|---|---|---|
| T1 | Welcome page | display | "Hi, I'm Pepper!" / "Come closer and say hello", gradient background, lab logo at the bottom | screen-render.js:406-407, 349-354 |
| T2 | Choice page | tappable display | Question plus 2-4 coloured options. Each option shows a picture, an emoji (in "with emoji" experiences) or a big word. After a tap the picked option turns green and the others dim. A tap is ignored if the page has already changed. | screen-render.js:391-405; screen.html:273-283; screen.py:136-144 |
| T3 | Message page | display | Optional big emoji plus text | screen-render.js:381-383 |
| T4 | Slide | display | Full screen on black, no logo | screen-render.js:380 |
| T5 | Blank | display | Black | screen-render.js:379 |
| T6 | Emoji test grid | display | Numbered cells | screen-render.js:384-390 |
| T7 | Lost-connection dot | status indicator | A small red dot, bottom-right, after 3 s without the server. On purpose it has no text, so the public never reads an error. | screen.html:12-13, 287-289 |
| T8 | Heartbeat | background | Polls every 500 ms; this drives the Screen pill (P3) | screen.html:285-297 |

## 4. Pepper simulator (`sim.html`; run with `python -m pepper_app.sim [--mute] [--port] [--no-browser]`)

| ID | Item / label | Kind | Options / default | What it does | Where |
|---|---|---|---|---|---|
| S1 | "No robot. Type what the visitor says; tap the tablet like a visitor would." + "Operator dashboard" link | header | – | Opens the real dashboard in a new tab | sim.html:48-52 |
| S2 | Pepper's chest tablet | iframe of `/screen`, scaled | – | Taps here count as the visitor's answer | sim.html:55-59 |
| S3 | Pepper's body | live list | The last 6 movements with times / "No movements yet." | Shows the gestures the robot would make | sim.html:60-63, 223-233 |
| S4 | Experience / Engine / Language | 3 selects | The same lists as P13/P14. Language here reads "Auto (English, Hebrew if spoken to)". | Saved through `/api/options` | sim.html:69-77, 196-197 |
| S5 | Start conversation / Stop / Repeat question / Skip | 4 buttons | Start is disabled while running; the others are disabled while idle | – | sim.html:80-83, 161-162 |
| S6 | State line | live display | Off / "Waiting for the visitor's answer · N s (asked again once)" / Pepper is thinking... / Pepper is talking / AI paused / "AI is stuck (see the dashboard log)" | – | sim.html:85, 148-158 |
| S7 | Step line | live display | "Step n of N: title · turns t" | – | sim.html:86, 159-160 |
| S8 | Conversation | chat | Visitor / Pepper / Pepper (operator) bubbles; amber "Heard, not used" lines; taps | – | sim.html:90, 124-146 |
| S9 | "The visitor says..." + Say | text + submit | Text typed while Pepper talks is held and shown as "Held until Pepper finishes talking: …", then sent automatically. Error "Start a conversation first". | – | sim.html:91-96, 204-221 |
| S10 | Error line + hints | status | Shows server errors and the last ERROR log line | – | sim.html:96-97, 190 |

## 5. Legacy "Pepper Say-It" dashboard (`pepper_dashboard/index.html`). The hub no longer launches it.

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| L1 | Status card | live display | Dot + "Pepper connected" / the server's note / "dashboard server stopped"; IP; "Battery N% ⚡ charging"; **Laptop WiFi** (which network the laptop is on) | – | always; polled every 3 s | index.html:58-63, 155-169 |
| L2 | Scan this network / ⏳ Scanning… + result | button + text | "Last scan T: N addresses, Pepper at x / no Pepper found" | Looks for Pepper on the laptop's /24 network (port 9559, Pepper body only) | needs the dashboard server | 68-69, 177-182, 224 |
| L3 | Add an IP by hand + Add | text + button | – | Saves an address to try | needs the server | 72-73, 225-226 |
| L4 | Auto | button | Tooltip: "Stop using a chosen address and search automatically" | Unpins the chosen address | only when an address is pinned | 74, 183, 227 |
| L5 | Known addresses list | table rows + Connect / Forget per row | Robot name, IP, "● connected", "WiFi: X", "seen T" / "never seen", note. Empty state: "No saved addresses yet." | Pick or forget an address | always | 76, 184-199 |
| L6 | Help text | text | Names an old personal hotspot (out of date) | – | always | 77 |
| L7 | Say box + Speak + Stop talking + **Gestures while talking** (checkbox, on) | textarea + buttons + checkbox | Enter = speak, Shift+Enter = new line, English only | Pepper's built-in voice speaks the text, with body animation when Gestures is on | needs Pepper connected | 81-86, 134-144 |
| L8 | 6 quick chips | chips | "Hello! I am Pepper.", "Welcome to our lab!", "Nice to meet you.", "Can you please wait a moment?", "Thank you very much!", "Goodbye, see you soon!" | Speaks the phrase | connected | 113-114, 145 |
| L9 | Body: Wave / Nod yes / Shake no + Volume slider (0-100, step 5) | buttons + slider | – | – | connected | 91-97, 146-153 |
| L10 | Pepper's WiFi networks | live list | Per network: name, "signal N%", "Pepper's IP here: x", security, tags **connected** / **saved**. Empty states: "Connect to Pepper to see its networks." / "No WiFi networks in range." / "Could not read networks: …". Refreshed every 15 s. | Shows which networks Pepper can see and remembers | always | 100-104, 200-223 |
| L11 | History | log | Time + "🗣 text" / "■ stopped" / "Failed: …" (red) | – | always | 106-109, 117-123 |

## 6. Backend capabilities with no control (or a hidden one) today

| ID | Item | What exists | Where |
|---|---|---|---|
| B1 | Pause AI without speaking | `POST /api/ai/pause` exists. The UI pauses the AI only as a side effect of Talk with "pause AI" ticked. | server.py:627-644 |
| B2 | Custom tablet message / choice | `POST /api/screen` accepts `message` (≤300 chars) and `choice` (question ≤120 chars, 2-4 options ≤40 chars). **The operator UI has no form for either**; only the AI uses them. | server.py:742-766 |
| B3 | Robot status fields not shown | The agent reports `awake`, `awareness` (face tracking), `posture`, `playing`, `speaker_mode`. Only battery, charging and volume are shown; posture and speaker mode appear in a tooltip only. | pepper_agent.py:596-611; app.js:90 |
| B4 | Vendor dialog muted | On connect and on Start, Pepper's built-in chat app is paused so it does not answer people too. Restored on shutdown. | server.py:173-190, 547-559 |
| B5 | Tablet auto re-open | Every 20 s while the tablet is silent | server.py:200-227 |
| B6 | No-speaker error | Log line "no way to play audio on Pepper's speaker -- the AI cannot talk; Wizard of Oz with Pepper's own voice still works (English)" | server.py:183-187 |
| B7 | Firewall | Pepper's agent connects *back* to the laptop on port 8782 (the dashboard is on 8780). If Windows Firewall blocks Python, the Robot pill shows the firewall hint. There is no firewall button; it is diagnosis only. | robot.py:117-122; __main__.py:17-18 |
| B8 | Testing without a robot | `python -m pepper_app --robot ""` runs with laptop audio only | __main__.py:3-4 |
| B9 | NAO helper commands | Only ping, identity, battery, say and posture. NAO's conversation UI is NAO_LLM's own control panel, opened by Launch; it is not part of this hub. | nao2/agent2.py:215-221 |

---

## Flows

1. **Run the scripted Pepper demo:** in the hub, Connect Pepper (it says its line) → optionally pick a Speaking key on the card → Launch (a waiting tab opens and becomes the dashboard) → wait for both the Robot and Screen pills to turn green (press Reload on the Screen pill if needed) → check Experience = "Feelings Together (demo) · scripted", Engine, Language, Voice, and the Vision / AI drives screen / Gestures toggles → Start conversation → watch the state badge, Step n/9, the transcript and the turn info → if needed press Repeat question, Skip, or Accept a "Heard, not used" line, or click an option in the tablet preview to tap for the person → End conversation.
2. **Free talk:** set Experience = Free conversation, then Start. There are no screen changes or gestures, and replies are one sentence long.
3. **Wizard of Oz takeover:** with "pause AI" and "tell AI" ticked, click a quick phrase or type and press Enter → the AI pauses (badge "PAUSED · YOU", Resume AI appears) → speak more, or move Pepper (gestures, head, Stand, Walking) → Resume AI.
4. **AI stuck:** the red banner appears and the Wizard of Oz cards flash → speak from Wizard of Oz, or press Restart AI (history kept).
5. **Emergency:** Stop everything (conversation, speech and motion), or Stop motion / Stop (speech) for one part only.
6. **Presentation:** Upload images or a PDF (or drop them on the card) → pick the presentation → Prev/Next or a thumbnail → Home / Clear. The AI can also show slides from the selected deck when "AI drives screen" is on.
7. **Emoji calibration:** Emoji test → look at the real tablet → Mark broken → type the numbers → toast "N emoji allowed".
8. **Walk:** unplug the charger → Walking → Pepper says the walk line in the conversation voice, then walks 1 m, turns, comes back. It is refused while charging.
9. **Teach a robot a new hotspot (NAO/Pepper):** turn the hotspot on → Add WiFi… on the card → name + password → Join → the robot moves now and remembers it → move the laptop to that hotspot.
10. **NAO posture:** Sit or Lie down (motors off afterwards), or Stand up → Confirm within 5 s. The heat guard may refuse, with the joint and its temperature.
11. **Furhat:** Connect (the voice is set to English and Furhat says its line) → Launch opens Furhat Studio in a browser (it asks for the admin password).
12. **Stop Pepper:** Disconnect or Stop in the hub → the dashboard gives Pepper back (tablet page hidden, vendor dialog restored, agent stopped).
13. **Rehearse without a robot:** run the simulator → choose the experience → Start → type what the visitor says and tap the tablet iframe.

## Notes for the new design

**These must stay IN CONTEXT, next to the conversation and the robot, not in a Settings page:**
- Everything in the Conversation card (P10–P27): Experience, **Engine (the AI provider choice: GPT Realtime or ElevenLabs+GPT)**, Language, **Voice (its list changes with the Engine)**, the Vision / AI drives screen / Gestures toggles, Start/End, Resume AI, Repeat, Skip, and the turns/clock/latency/step readouts. Operators change these between runs, at the table.
- The Speaking key on the hub card (H6). It decides which key Pepper speaks through and is chosen just before Launch, so keep it on the robot card or in the pre-launch panel.
- The "pause AI" / "tell AI" checkboxes next to the Wizard of Oz Say box, the quick phrase chips and the free-text box with Enter to talk.
- Stop everything, always visible. Stop motion and Stop speech next to their own controls.
- The Robot and Screen pills, including battery and the Reload button. The AI-stuck banner and Restart AI.
- Live transcript with partial text, the "Heard, not used" rows with Accept, the mic state line with its level meter, and the event log with Copy.
- Camera view with the Top/Bottom select, face boxes and Save. Tablet preview where clicking taps for the person, last-tap readout and "by AI/by you".
- Presentation controls (select, prev/next, thumbnails, Home/Clear, Upload and drag and drop, Delete with confirm).
- Volume in the header, live.
- NAO posture buttons with the two-tap Stand and the heat-refusal note. Add WiFi… on the robot card.

**Could move to a Settings / maintenance area, if they stay reachable:**
- Emoji test + Mark broken (one-time tablet calibration, P53/P54).
- Saved keys themselves (adding and deleting). The per-robot *choice* stays in context.
- The connection-finding tools from the legacy dashboard (scan, add IP, known addresses, Pepper's WiFi list, L2–L5, L10), if they are brought back. Their information is useful for troubleshooting.
- The simulator: a "rehearse without robot" entry point, not part of the live screen.

**Easy to drop by mistake:**
- Pepper's battery is shown on the hub card too; it is not only NAO's.
- The voice list depends on the engine.
- "Feelings Together · with emoji" is shown but cannot be selected.
- The tablet preview can be clicked to tap for the person.
- Enter / Shift+Enter in both text boxes.
- The model label is static and wrong for the scripted experience (it uses gpt-4.1). Show the real model from the server.
- Face tracking starts as "on" whatever the robot is doing. Show the real `awareness` value.
- A custom tablet message or choice and a pause-only AI button exist on the server with no control. Consider adding them.
- The Screen pill's Reload appears only when the tablet is lost.
- The Walking button is refused while Pepper is charging.
- The firewall hint appears only inside the Robot pill's failure text.

---

## Checker additions

A second pass re-read every file above line by line (each id, handler, option list, WebSocket message type and server route) and checked the backend behind each control. It found **32 new items (C1–C32)** and **12 corrections (K1–K12)**. Paths are relative to `robot-hub/`.

### A. Pepper Operator: hidden rules behind the Conversation controls

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| C1 | Which options each Experience uses | hidden rule | **Scripted demo:** it always listens with ElevenLabs Scribe, whatever the Engine says. Engine and Voice only pick the speaking voice. **Vision and AI drives screen are ignored**, because the script drives the screen itself; Gestures is honoured. The reacting model is gpt-4.1. **Free conversation:** the AI gets no tools, so **AI drives screen and Gestures do nothing**; Vision works; Step stays "–". | The UI shows every toggle as active in every experience, so the operator cannot tell which ones matter | always | script.py:380-395; brain.py:127, 389, 401-408; server.py:271-276 |
| C2 | Settings that apply only at the next Start | hidden rule | Experience, Engine, Language and Voice are saved at once, but a **running** conversation keeps the values it started with. Only Vision, AI drives screen, the presentation and the emoji list reach a running conversation. Gestures is read on every gesture, so it also applies at once. | Changing Engine or Voice mid-conversation leaves the AI's voice as it was. Wizard of Oz Talk, the walk line and the quick phrases switch to the new voice at once (they use `voice_now()`), so **Pepper can speak in two voices in one conversation.** | while a conversation runs | server.py:598-615 (update set), 251-255 (voice_now); brain.py:347, 615 |
| C3 | Start conversation key errors (toast) | toast / error | "no OpenAI key -- add a GPT key in the hub's Keys panel"; "no ElevenLabs key -- add one in the hub's Keys panel, or use the GPT Realtime engine"; "pick an ElevenLabs voice first"; "the scripted experience listens with ElevenLabs -- add an ElevenLabs key" | Start is refused and the mic is closed again | on Start | brain.py:349-355; script.py:383-384; server.py:396-400 |
| C4 | No ElevenLabs-key warning | missing status | The server sends `has_eleven`, but the page never shows it. The only hint is the Voice list reading "No ElevenLabs voices (key?)". Without an ElevenLabs key, Wizard of Oz and the walk line **silently fall back to the OpenAI voice**, while the scripted demo refuses to start (C3). | – | ElevenLabs engine with no ElevenLabs key | server.py:147, 251-255 |
| C5 | Settings shared live and remembered | behaviour | Every option change is broadcast (`cfg`) to every open dashboard and to the simulator, and saved in `data/settings.json`. If "with emoji" was saved, it is reset to the scripted demo on load. | Two operator tabs always agree. The new app must keep a single source of truth. | always | server.py:80-93, 613-614 |
| C6 | Start also resets the screen and history | behaviour | Start puts the **welcome page** on the tablet (logged as "AI put welcome on the screen"), clears the conversation history, re-opens the mic and mutes the vendor dialog | – | on Start | server.py:370-396 |
| C7 | Robot link states in full | status | starting → deploying (amber, "starting its agent…", up to 60 s for the agent to call back) → connected; **lost** (red, "the agent's connection dropped") or **failed** (red, the error text, including the firewall hint and "started without a robot address"). From lost or failed it **re-deploys by itself after 20 s**. | Shown in the Robot pill (P2); P2 lists only part of this | always | robot.py:36-37, 63, 95, 107-125, 236 |
| C8 | WebSocket reconnect | state | When the dashboard server goes away: "dashboard server stopped", the pill turns red, and the page retries every 2 s. On reconnect it redraws chat, log, options and screen from a fresh snapshot. | – | dashboard restart | app.js:370-412 |

### B. Pepper Operator: chat events, toasts and errors that were not listed

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| C9 | "AI gesture: <name>" event pill | chat event | Separate from the operator's "Gesture: <name>". **It is shown even when Gestures is off**, though Pepper does not move then. AI gestures: wave, yes, no, arms_wide. | Tells the operator what the AI tried to do | AI conversations | server.py:296-301; brain.py:61 |
| C10 | "<AI/You> put <what> on the screen" events | chat event | what = "choice: A / B", "message", "slide N", "welcome", "blank", "the emoji test card" | Record of every screen change and who made it | on every screen change | server.py:338-346 |
| C11 | A screen tap is the person's answer | behaviour | A tap (on the tablet or in the preview) goes to the running AI as the answer. Only **one tap per choice page** counts; later taps or taps on an old page are ignored. Log: "screen: tap “X” -> sent to AI". | – | choice page shown | server.py:868-882; screen.py:136-146; screen.html:37-47 |
| C12 | Walk line said before Walking | chat bubble | Hebrew or English by the Language setting (Auto counts as Hebrew). It shows in the chat as a Wizard of Oz bubble. If the line cannot be synthesised, Pepper walks anyway (warning in the log). | – | Walking | server.py:38-40, 472-488 |
| C13 | Control error toasts | toast | "no conversation is running" (Resume, Restart AI, Repeat, Skip, Accept while idle); "Pepper is not connected" (Talk with no robot); "could not speak it: …" (Hebrew Talk when the voice fails); "Pepper is charging: unplug the charger and close the flap, then press Walking again"; "Pepper did not answer" / robot errors such as "only Stand was tested on this robot"; "nothing to say" | Shown in the toast (P9) | on failure | server.py:556-560, 627-664, 431-450, 476-478; pepper_agent.py:474-506 |
| C14 | Upload errors and rules | toast + limit | Slides must be png, jpg, gif or webp, and **at most 15 MB each** ("that image is over 15 MB"). A PDF that fails gives "Could not read <file>: <error>"; a rejected slide gives "<name>: <error>". During upload the slide counter shows "i/N". **The new deck is selected automatically** when the upload ends. | – | on Upload or drop | app.js:272-294; screen.py:38-41, 188-191; server.py:813-826 |
| C15 | Delete of the selected deck | behaviour | Deleting the selected presentation clears the selection, so the AI then has no slides ("failed: no presentation is selected") | – | Delete | server.py:828-839, 316-318 |
| C16 | "Only this laptop" refusal | error | Any control request from another device gets 403 "the operator dashboard is only open on this laptop". Only `/screen*` is open to the tablet. | Matters if the new app is ever opened from another device | always | server.py:541-549 |

### C. Pepper content with no control in the UI (new design should surface or document)

| ID | Item | What exists | Where |
|---|---|---|---|
| C17 | **Uploaded slides are also the AI's picture library** | Every uploaded slide, by its file title, can be put on a choice option as a picture by the AI. The AI is told the list of picture names. So uploading "dog.png" lets the AI show a dog choice. | screen.py:221-227; server.py:302-311, 348-355 |
| C18 | Lab facts file for free conversation | `pepper_app/lab_facts.md` is the only source Pepper may use for questions about the lab. You edit the file, then relaunch Pepper. There is no UI for it. | lab_facts.md:1-5; brain.py:181-190 |
| C19 | Robot status fields gathered on connect but never shown | NAO: system version, plus mic = "Windows default input". Pepper: mic = "Pepper's own four microphones". Furhat: mic = ReSpeaker array, plus Realtime status when `FURHAT_API_KEY` is set (it can be refused: "the Realtime API refused FURHAT_API_KEY…"). The hub stores these, but the card does not display them. | naoqi.py:459-471, 881-885; furhat.py:338-376; core.py:416-419 |
| C20 | Emoji candidates | 45 candidate emoji: faces, hands, animals, food, places and sky. The Mark broken numbers refer to this list. | screen.py:54-66 |
| C21 | Page needs the internet | The operator page loads Tailwind from a CDN (no styling offline), and PDF upload loads pdf.js from cdnjs. On the lab WiFi without internet, PDF upload fails. | index.html:7; app.js:254-259 |
| C22 | Free conversation self-recovery | If the Realtime link drops, the AI session reconnects with the last 20 turns as context ("The connection dropped and was restored…"). Restart AI uses the same path with no greeting. | brain.py:384-394; server.py:416-421 |

### D. Hub robot card: missed details

| ID | Item / label | Kind | Options / default | What it does | Visible / enabled when | Where |
|---|---|---|---|---|---|---|
| C23 | Mute icon next to the name | status icon | Tooltip "connected, but could not speak" | It is an icon by the robot name, not a status text (see K1) | Connected/Running and the announcement failed | web/app.js:95-101 |
| C24 | Robot photo | image | `web/photos/<type>.png`; falls back to the robot glyph when missing | – | always | web/app.js:122-135 |
| C25 | Connect spinner / Disconnect in Lost state | button states | Connect: disabled when not present, already connected or connecting, with its icon spinning while connecting. **Disconnect is enabled in the Lost (ERROR) state too.** Detail line reads "not on the network" when Absent. | – | – | web/app.js:103-117 |
| C26 | Waiting tab + popup fallback | new tab + toast | The tab opens at once with "Launching <name>… This tab opens its system as soon as it is ready." If the browser blocks it: toast "Launched. The browser blocked the new tab — press Open on the card." | Avoids the popup blocker on long launches | Launch | web/app.js:948-971 |
| C27 | Open on a running robot | button | "Open" reopens the tab only. It **does not restart** the system. | – | state Running | web/app.js:1020-1024 |
| C28 | **Pepper's Speaking key applies only to a fresh launch** | rule | Pepper uses an OpenAI (GPT) key and an ElevenLabs key. Picking a key of either provider replaces that one; every other provider gets its first key. **If Pepper's dashboard is already running, Launch reuses it ("Pepper's dashboard was already running") and a newly picked key is ignored** until Disconnect and Launch. The fallback label "Default (first Gemini key)" is misleading for Pepper, which never uses Gemini. | – | Pepper card | keys.py:140-164; naoqi.py:841-855; core.py:537-543 |
| C29 | WiFi form checks and results | validation + toast | "Type the hotspot name." / "A WiFi password has at least 8 characters." / "Could not ask the hub: …". On success the form closes, the password clears and the message also appears as a toast. | – | Join | web/app.js:211-237 |
| C30 | NAO Launch needs NAO_LLM's keys | error + notes | NAO has **no key picker**. The key names come from NAO_LLM's `config.yaml`, and if one is missing: "NAO_LLM refuses to start without X -- add it to .env". Notes: "starting NAO's speaker server (about a minute; NAO stays in its posture)". Failures: "NAO's speaker server did not come up on port 9600 -- deploy_nao.py said: …"; "NAO_LLM never opened its control panel on port N within S s". NAO_LLM gets its own port (never 8000). | – | NAO Launch | naoqi.py:601-714, 725-751 |
| C31 | Posture toasts | toast | A refusal is also shown as a toast. On an old hub: "Restart the hub to use the posture buttons." Network failure: "Request failed: …" | – | NAO posture | web/app.js:316-343 |
| C32 | Child output in the hub log | log | The Pepper dashboard's and NAO_LLM's own output appear in the hub log with the prefix "Pepper" or "NAO_LLM". Launch errors point to it ("its own output is in the log above"). | – | Launch | naoqi.py:692-694, 857-867 |

### E. Corrections to the inventory above

| # | Item | Correction |
|---|---|---|
| K1 | H4 Status | The labels are **Absent / Available / Connecting / Connected / Running / Degraded / Lost / Unavailable**, not "Detected" or "Error". "Could not speak" is a mute icon next to the name (C23), not a status. (web/app.js:30-39) |
| K2 | P17/P18/P19 toggles | They are not live for every experience: see C1 and C2. Vision and AI drives screen do nothing in the scripted demo; AI drives screen and Gestures do nothing in free conversation. |
| K3 | P14 Engine | In the scripted demo (the default), Engine does not change the ears, which are always ElevenLabs. It only picks the voice provider. ElevenLabs is mandatory there. |
| K4 | S4 Simulator selects | The simulator's Experience list **does not** grey out "with emoji". Picking it is silently dropped by the server and the select snaps back. The simulator has **no** Voice, Vision/AI screen/Gestures, Wizard of Oz, camera or Accept: it uses the dashboard's saved values. (sim.html:166-197) |
| K5 | S9 Simulator hint | Typed text counts as a finished spoken sentence, and fillers such as "hmm" are ignored. `--mute` gives Pepper's lines as text only. (sim.html:97; sim.py:259) |
| K6 | P42 Chat | The page keeps 300 rows, but the server keeps only the **last 200** for a reload. The log keeps 600 on both sides. (server.py:72-73) |
| K7 | P3 Screen pill | The server counts the tablet as lost after **4 s** without a poll. The tablet's own red dot appears after 3 s. (screen.py:38) |
| K8 | Section 3 line numbers | `screen-render.js` has 124 lines and `screen.html` 70. The real places: welcome page screen-render.js:100-101; choice page 85-98; message 75-77; slide 74; blank 73; emoji grid 78-84; logo on every page **except** blank, slide and emoji test (64-69, 45-48). Lost dot screen.html:11-13, 51-53; heartbeat 49-61; tap once per page 37-47. |
| K9 | P53 Emoji test | There are 45 candidates, not about 40 (C20) |
| K10 | P36 Gesture grid | Walking is the ninth button in the same 5-column grid. The `.move` buttons are disabled while the robot is not connected. (app.js:5-7, 98) |
| K11 | H6 Speaking key | See C28: the choice applies only when Launch starts a new dashboard, and the "first Gemini key" label is wrong for Pepper |
| K12 | L11 Legacy history | It also logs "Connecting to <ip>", "Forgot <ip>", "Added <ip>", "Back to automatic search", "Scanning network…" and the gesture names. The connected address row is highlighted. The Connection card's buttons work whenever the server is up; all the others need Pepper connected. (pepper_dashboard/index.html:146-199) |

### Design notes from this pass

- **Grey out or hide toggles the chosen Experience ignores** (C1), and mark Engine, Voice, Language and Experience as "applies at next Start" while a conversation runs (C2). Otherwise Wizard of Oz may speak in a different voice from the AI.
- Put **both keys' status** (GPT and ElevenLabs) next to the Conversation card, and say up front which experience needs which key (C3, C4). Keep the key choice on the Pepper card, but say it applies at the next Launch (C28).
- Present the **presentation upload as the AI's picture library too** (C17), and give lab_facts.md an "edit facts" entry point or at least a pointer (C18).
- Bundle Tailwind and pdf.js locally in the new app: the lab WiFi may have no internet (C21).
