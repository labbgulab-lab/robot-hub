# Student app plan: LabaLab Robot Hub for non-technical students

Status: plan, 2026-11-04, updated 2026-11-05. Nothing here is built yet.
Design: the "Robot Hub student app" canvas (23 boards in 6 rows: hub in rows 1-4, reachy_app in rows 5-6) and the "LabaLab Robot Hub" design system v2.

**Rule since 2026-11-05 (S19): full feature parity.** The new app keeps every control, setting and live display of today's hub page, group page and reachy_chat dashboard. Only the look changes, and the copy stays short. The checklists are the parity inventories in `docs/parity/` (hub-main, group-setup, group-live, reachy-chat, pepper), each with file:line references and a checker pass.

## 0. Decisions

| # | Decision |
|---|---|
| S1 | The student app is Robot Hub only, downloaded from GitHub and run on the student's own laptop. No login, no server, no AWS. |
| S2 | **Windows only** in v1. Mac is a later phase. |
| S3 | **Install = one pasted PowerShell line.** It downloads a portable bundle from GitHub Releases into the user's own app folder, makes a desktop shortcut and opens the app. Running it again updates. A zip stays as the fallback. |
| S4 | **Keys:** on first open, a popup asks for a key. The key is the student's own, or a personal capped key from the lab. It is tested when pasted. "Later" closes the popup, and a warning bar stays at the top until a working key exists. |
| S5 | **Goal: every key type works on every robot** (OpenAI, Gemini, OpenRouter; ElevenLabs optional for voices). v1 ships what already works; section 5 has the rest. |
| S6 | **Robots come in two tiers.** Ready out of the box: Reachy Mini (wireless) and Furhat. One-time setup: Pepper and NAO (one kit download), Reachy Mini Lite (Pollen's app). The setup model is generic, so future robots fit it. |
| S7 | **A finished setup is never shown again.** It comes back only as a warning or error when something breaks. |
| S8 | **A small Logs button** opens a live logs drawer. |
| S9 | **English only. Minimal text:** a status word and one action per card. A sentence appears only for a problem, and it stays short. No emoji. |
| S10 | **Students see everything today's pages have** (S19), including the per-robot key choice and every group-page setting. **Behind the "Lab staff tools" switch in Settings:** robot files library, Add WiFi, Reachy bring-up, the NAO app (NAO_LLM) Start button, "Check this laptop". Superseded wording, 2026-11-04: "per-robot key choice and the group page's expert settings behind Advanced" (rejected 2026-11-05). |
| S11 | **Furhat:** the skill will be rebuilt **without** a baked-in key. Furhat then uses the student's key like every other robot. The skill rebuild is done in the lab. |
| S12 | **NAO in v1:** setup, connect (it says hello), battery and postures for students. The NAO app (NAO_LLM) stays reachable as a lab-staff Start button on the NAO card until a light version of CRAB replaces it. |
| S13 | **Reachy runs in robot mode only:** it listens through its own microphone. Only reachy0 has a broken mic, and it is out of use. Laptop-mic mode, which needs a 1.1 GB runtime, is not in the student app. |
| S14 | **Students get an updated Wizard of Oz dashboard for Reachy:** type a line and the robot says it, a cue script, moves, quick saves and Stop. It is based on reachy_chat's `/show` board. |
| S15 | **Personal capped keys**, one per student, created by the lab manager and deleted when the student leaves. |
| S16 | **One Reachy conversation app.** Talk (one Reachy), Group (two or more) and Wizard of Oz live in one place that adapts to how many Reachys are picked. It merges reachy_chat's dashboard and the group conversation page (section 6b). |
| S17 | **Battery is shown wherever the robot reports it** (NAO, Pepper), and a warning appears when it runs low. A robot that reports no battery (Reachy, Furhat) shows none; we never show a made-up number (section 7b). |
| S18 | **A phone hotspot takes 5 devices, and the laptop is one of them.** Pepper takes two (robot and chest tablet). The app counts devices on a hotspot and has a demo planner (section 7c). |
| S19 | **Full parity, new look** (2026-11-05). Nothing from today's hub, group page or reachy_chat dashboard is dropped or moved to a global Settings page when it is chosen per robot or per conversation today (AI service, key, voice, writer, character, language). Settings holds only keys, robot passwords, extra software, transcripts, staff tools and About. |

## 1. The student's path

1. **Install.** Open PowerShell and paste one line. The installer downloads about 150 MB, unpacks it, makes the "LabaLab Robot Hub" desktop icon and opens the app.
2. **Key.** The popup appears. The student pastes a key, the service is detected from the prefix, and the key is tested. A green "It works" means done. "Later" leaves the warning bar.
3. **Robots.** Robots on the same WiFi appear as cards. Each card offers Talk, Wizard of Oz for Reachy, and a "Say hi" speaker that makes the robot say its name.
4. **More robots.** Pepper/NAO and Reachy Lite sit in a quiet "More robots" row with **Set up**. Setup is one download with a progress bar. After that the row disappears for good.
5. **When something is wrong,** a short bar or card line appears with one button: "Charge it." [Try again], "Another laptop is using it.", "No robots nearby" [Open WiFi settings].
6. **Every later day:** double-click the icon, and the robots appear.

## 2. How it runs

### 2.1 App and data are separate
Today every writable file sits inside the code folder, so an update would wipe it (`hub/config.py:22`; `hub/core.py:67`; `hub/main.py:47-49`; `hub/group/conductor.py:50,51,142`; `hub/group/phrases.py:28`; `pepper_app/__main__.py:27`; `hub/adapters/naoqi.py:627`).

```
%LOCALAPPDATA%\LabaLab\RobotHub\app\    replaced by every install/update
%LOCALAPPDATA%\LabaLab\RobotHub\data\   never touched by the installer
    config.toml (student overrides only), keys.local.json, setup.json,
    group.local.json, logs\, cache\, pepper\, nao_llm\
C:\LabaLab\naoqi-sdk\                   short ASCII path (Python 2.7 breaks on Hebrew user names)
```

- `hub/config.py` gets a `DATA_DIR` from `ROBOT_HUB_DATA`. It defaults to the repo root, so lab clones keep working.
- Config becomes layered: a shipped `defaults.toml`, then `DATA_DIR\config.toml`. A writer is added; `tomli-w` is already in requirements.
- Every writable path in the list above moves to `DATA_DIR`. `pepper_app` gets `--data`, and NAO_LLM's generated yaml goes to `DATA_DIR\nao_llm\`.

### 2.2 Runtime
- **A portable Python 3.12** (python-build-standalone) with the hub's packages installed into it. No venvs: they hard-code absolute paths and cannot be moved. Pin 3.12, because 3.13 removes `audioop`, which `pepper_app` uses.
- **Reachy needs no reachy_chat venv on the laptop.** Today every Launch runs `tools/deploy_robot_app.py` from reachy_chat's venv (`hub/adapters/reachy_wireless.py:363-378,475-508`), and that tool imports `conversation` for constants (`deploy_robot_app.py:30-37`). Move those constants to a small module and run the deploy with the hub's own Python. Ship the reachy_chat source in the bundle (a few MB).
- Bundle size: about 300-350 MB installed, about 120-150 MB zipped.

### 2.3 Window and process
- **The app runs windowless.** The desktop icon starts `pythonw` with the hub, then opens the page as an app window (`msedge --app=http://127.0.0.1:8099`), which carries the logo with no browser bar. Closing the window does not kill the robots. A small tray icon or the Settings page has **Quit**.
- **Single instance.** A second start only focuses the open window.
- New routes: `/api/version`, `/api/quit`.
- Every child process gets `CREATE_NO_WINDOW`. Otherwise ping.exe would flash thousands of windows: `hub/discovery/netscan.py:389,463`, `hub/supervisor.py:195`, `hub/adapters/naoqi.py:399,628,733`, `hub/adapters/reachy_wireless.py:486`, `hub/doctor.py:263`, `hub/library.py:118`.
- uvicorn logging goes to a file when stdout is missing (`hub/main.py:33-37,361`).
- Logs rotate daily, keeping 14 days.

### 2.4 Build and release
- `tools/build_release.ps1`, run by hand on a lab laptop or by a GitHub Actions Windows runner. It builds **only from fresh clones**, never from working folders: those hold `.env`, `keys.local.json`, reachy_chat's key `.txt` files and NAO_LLM's participant data.
- Steps: lock files, pip install into the portable runtime, pre-compile, prune tests, zip with `tar`, then upload `RobotHub-Windows.zip` and `install.ps1` as release assets.
- **`install.ps1`**:
  - set TLS 1.2 and turn off the slow progress bar;
  - stop a running hub (`/api/quit`, then kill processes under `app\`);
  - extract into `app.new`, swap it in, keep the previous version;
  - never touch `data\`;
  - make the shortcut with an `.ico` built from the LabaLab camel-and-robot mark;
  - open the app.
- The README gets one block at the top: the line to paste, the zip link and a link to the guide with pictures.

## 3. Keys

Today keys are never tested, and the fallback is "the first Gemini key" (`hub/keys.py:138-150,174-189`).

- **`hub/keys.py`**
  - Each key gets `status` (ok / bad / no_credit / limited / unreachable / unchecked), `detail`, `checked_at` and `credit_left`.
  - Detect the provider from the prefix: `sk-or-` OpenRouter, `sk-`/`sk-proj-` OpenAI, `sk_` ElevenLabs, `AIza` Gemini, otherwise ask. Strip quotes, a "Bearer " prefix and whitespace.
  - Drop Qwen and the label field for students.
  - `for_robot()` picks the best **working** key the robot can use, not "first Gemini".
  - `env_for_robot()` skips bad keys and exports `OPENROUTER_API_KEY` too.
  - Add `has_working_key()` to drive the warning bar.
- **New `hub/keycheck.py`.** One free test call per provider:

  | Provider | Call | Note |
  |---|---|---|
  | OpenAI | `GET /v1/models` | 401 = bad. A key with $0 still passes; a 429 `insufficient_quota` at use time means no credit. |
  | Gemini | `GET v1beta/models` with `x-goog-api-key` | A bad key returns 400 `API_KEY_INVALID`, not 401. |
  | OpenRouter | `GET /api/v1/key` | Gives `limit_remaining`. Show "$4.20 left of $5". |
  | ElevenLabs | `GET /v1/user/subscription` | Characters left. "Out of credit" is also a 401, so read the body. |

  A network error never marks a key bad. It says "Can't reach OpenAI from this network" and leaves the key unchecked.
- **Routes:** `POST /api/keys/test`, `POST /api/keys` tests before saving, `POST /api/keys/{id}/test`. Keys are re-checked with the free calls at start.
- **Launch pre-flight.** Each adapter declares `required_keys` (e.g. any of gemini, gpt) and `optional_keys`. A missing key gives one sentence and an "Add a key" button before the robot is touched.
- **Laptop-mode bug:** the key is not passed at all (`hub/adapters/reachy_wireless.py:604-606`). Robot mode only makes this moot for students, but fix it for staff.
- **No paid calls at start.** Today every hub start spends credit: `HUB_WARM_AT_START` runs a chat call, writer pings, a transcription and ElevenLabs lines (`hub/main.py:92-93`, `hub/group/conductor.py:4339-4383`). In the student app the warm-up runs only when the group page's start is pressed.
- **Scrub keys out of log lines** before they reach the drawer, the file or Copy (`hub/events.py:48-54`, `hub/supervisor.py:221-234`). Reuse `keyscrub`.
- **Pepper:** a dashboard started earlier is reused with its old keys (`hub/adapters/naoqi.py:851-853`). Restart it when keys change.

## 4. Robots and their setup (two tiers)

### 4.1 Generic requirement model (new `hub/requirements.py`)
Each adapter class declares `requirements` and `setup_tier`:

```python
Requirement(id, label, gate="connect"|"launch", audience="student"|"internal",
            check, locate=(), download=Link, how_to=(), fix=Fix, shared_with=())
CheckResult(status="ok"|"missing"|"broken"|"checking", detail, value, version)
```

- Results are cached in `DATA_DIR\setup.json` with a fingerprint (mtime and size). At start only a cheap check runs. A full check runs on "Check again", after a fix, or when the fingerprint changes.
- A runtime failure that points at a requirement calls `store.report_failure()`. The card then shows an error, and the setup comes back (S7).
- **Card state precedence:** running > error > needs setup > needs key > not nearby > ready. A placeholder card shows "needs setup" even when no robot is present.
- Routes: `GET /api/setup`, `POST /api/setup/{id}/check`, `POST /api/setup/{id}/fix` with progress events.
- `hub/doctor.py` becomes a CLI view over the same checks. Every remedy that says "edit config.toml" or "run pip" goes (`hub/doctor.py:38-39,113-150`).

### 4.2 Per robot

| Robot | Tier | Needs on the laptop | v1 work |
|---|---|---|---|
| **Reachy Mini (wireless)** | Ready | Nothing beyond the bundle, plus a key | Robot mode only (S13). Slim deploy with the hub's Python (2.2). **"In use by another laptop":** before Launch, check for a running app on the robot and for a marker file the hub writes there. Today Launch kills the other student's app (`hub/adapters/reachy_wireless.py:387-422`). |
| **Furhat** | Ready | Key, plus the Studio password once | Studio password: entered once on the card, stored with the keys (`hub/adapters/furhat.py:276-284`). The skill gets the student's key at launch (S11, 5.2). |
| **Pepper** | Setup | NAO/Pepper kit | Kit (4.3). **No firewall step** (decided 2026-11-05, students are not admin): the agent on Pepper listens on robot port 8790 and the laptop connects out; the agent also serves the tablet page on robot port 8791. Nothing on the laptop listens on the network, so Windows never asks. The old connect-back mode is only a fallback, and the robot chip says so. |
| **NAO** | Setup | Same kit | Connect, say, postures (S12). NAO_LLM is not in the bundle. |
| **Reachy Mini Lite (USB)** | Setup | Pollen "Reachy Mini Control" app | Locate it through the registry `InstallDir`, Program Files or `%LOCALAPPDATA%\Programs`. Fix: download the MSI from Pollen's latest GitHub release. Needs admin. |

### 4.3 The NAO/Pepper kit
- **The pynaoqi SDK ships its own 64-bit Python 2.7** (`bin/python.exe`, verified). With `PYTHONHOME=<sdk>/lib/python2.7`, `PYTHONPATH=<sdk>/lib` and `PATH=<sdk>/bin`, `import naoqi` works. Students then need **one** download, not Python 2.7 plus the SDK. The Python 2.7.18 **amd64** MSI is a fallback, shown only if the kit's own Python fails on a clean machine (it may need the VC90 runtime).
- **Download:** the official 2.8.7.4 win64 zip, 358 MB, no login, from the maker's site. The "Get it" button downloads it from that official URL, and "I have the zip" accepts a file the student already has. Either way we never host the SDK.
- **Extract** with Python `zipfile`, stripping the top folder, into `C:\LabaLab\naoqi-sdk\`. Show a progress bar; Defender scans about 6,000 files, so it is slow. Check for about 1.5 GB of free space first. Accept either level of the doubled folder.
- **The check is the import itself**, `python -B -c "import naoqi"` with a 10 s timeout. It also catches a 32-bit Python that a version check would let through.
- **To test before students rely on it:** the lab's tested SDK is 2.8.6.23, and only 2.8.7.4 is public. One lab session with NAO and Pepper on 2.8.7.4 is needed.
- **Discovery without the kit.** On HOT-WiFi, NAO and Pepper are invisible without the SDK: multicast is dropped, and netscan needs Python 2.7 to identify them (`hub/discovery/netscan.py:243-246,337-341`). Emit an "unidentified NAOqi robot at port 9559" sighting so the card can say "Pepper or NAO is here. Set up first."
- Build the probe from the live setup store, not the startup config, so a fix needs no restart.

## 5. Every key on every robot (S5)

| | OpenAI | Gemini | OpenRouter | ElevenLabs |
|---|---|---|---|---|
| Reachy talk (reachy_chat) | v1 (GPT realtime) | v1 (Gemini Live) | phase 2 | voices, with Gemini |
| Group conversation | v1 | v1 | v1 | v1 voices |
| Pepper (pepper_app) | v1 | phase 2 | phase 2 | v1 voices |
| Furhat (skill) | v1 after the rebuild | phase 2 | phase 2 | - |
| NAO | no conversation in v1 | | | |

**Phase 2: how to fill the gaps.**
1. **One "brain" layer.** Chat goes through OpenAI-compatible endpoints: OpenAI itself, OpenRouter, and Gemini's OpenAI-compatible endpoint. A base URL plus a key covers all three.
2. **Reachy with an OpenRouter-only key:** run one-to-one talk through the group conversation pipeline with a single seat. That pipeline already hears, writes and speaks through OpenRouter (`hub/group/services.py`).
3. **Pepper:** give `pepper_app`'s brain the same base-URL switch. Voice falls back the same way the group voices do.
4. **Furhat:** the rebuilt skill takes `{base_url, key, model}` from the hub at launch.
   - **Option A:** the hub installs the skill with the key filled in. The robot files library already rewrites keys in `.properties` files.
   - **Option B:** the hub sends the key to the running skill over Furhat's realtime API.

   Spike both; B keeps the key off disk.

**Lab keys until phase 2:** hand out **OpenAI** project keys with a budget. They run Reachy, group talk, Pepper and the rebuilt Furhat. After phase 2, OpenRouter keys become possible; they have exact dollar caps per key.

## 6. UI (the canvas is the reference)

- **`web/index.html`, `web/app.js`, `web/style.css`, rebuilt to the design:**
  - top bar: logo, network chip, Logs, Settings;
  - warning/error bar;
  - robot grid;
  - "More robots" row;
  - keys popup; setup sheet; logs drawer; Settings page.
  - Colours come from the design system tokens: warm off-white, white cards, logo orange `#FD9903` for the single primary button with dark text on it.
- **Card** (canvas boards 4 and 13): picture, name, status pill under the name, and on the right the "..." details button plus battery, USB link or address. Below: the live detail line in full (never cut to two lines), the **Speaks through** key picker on Reachy and Pepper (Pepper: GPT key and Voice key, each with Default), NAO postures with the two-tap Stand, then Disconnect and the main action (Connect, Talk, Open, Open Studio, Open dashboard, NAO app for staff, or "Starting… n s"). A problem shows one short note with its button (Override/Dismiss, See log, Add a key).
- **Robot details panel** ("..." on a card, boards 5-6): every fact the hub has (address, mic, robot software version, what it holds on this laptop, last seen), the key picker, Disconnect, Copy details, and Add WiFi for staff with every result state.
- **Network panel** (the WiFi chip, board 7): the check result with Check again, "Looking on <subnet>" with Scan now, and the per-robot steps for Reachy, NAO, Furhat and Pepper. It opens by itself on a first run and on any problem.
- **Top bar:** network chip, Auto-connect switch, Scan, the hub's Live dot, Logs, Settings. Under the title: "n of m nearby, n connected, n running, updated hh:mm:ss". Robots that are known but away show as "Not nearby" chips.
- **Hide, don't delete.** Both scripts attach listeners to elements without null checks (`web/app.js:11-22,41-48,544-547,603,610-619,860-869,1050,1068`; `web/group.js:17-87,806-825,1282-1298`). Staff controls stay in the page under a `[data-advanced]` CSS gate.
- **Friendly errors.** Adapters return codes, not sentences: `NEEDS_KIT`, `NEEDS_KEY`, `NEEDS_FURHAT_PW`, `NET_UNREACHABLE`, `AUTH_REFUSED`, `FIREWALL`, `IN_USE_ELSEWHERE`, `DEPLOY_FAILED`, `NO_DASHBOARD`, `BATTERY_LIKELY`. The UI maps each code to one short sentence and one button. The raw text goes to the logs only.
  - A failed Connect gets its own state instead of "Lost" (`hub/core.py:444-453`).
  - Stop toasting every `error` log line (`web/app.js:1113`).
- **Logs drawer.** Reuse the `/ws` `log` event and backfill from `/api/log?limit=500`.
  - Forward `hub.group.*` warnings to the bus. Today the group conversation is missing from the live log.
  - Child stderr is no longer shown as a warning by default.
  - "Save a report for the lab" zips today's logs with keys scrubbed.
- **Settings** keeps UI state on the hub side (advanced, setup done), not in localStorage, which resets when the port changes.
- **Group page** (`web/group.html`, `group.js`, 1,873 lines): re-skin it into reachy_app's Group tab (6b). Every control stays visible (S19); nothing goes behind Advanced.
- **Wizard of Oz** (canvas screen 10), from reachy_chat's `/show` board:
  - a Say box (type, Enter, the robot says it);
  - the cue script, with the next cue outlined and Space to fire it;
  - Moves; quick saves S/D/F; Stop on Esc;
  - a "Said" history with Again;
  - cues editable in the page, with no terminal step.

  "Type and say" needs live speech for any text, not only pre-recorded cues.

## 6b. One Reachy conversation app (S16), now called **reachy_app**

Canvas rows 5-6 (boards reachy_app 1-7). Redrawn 2026-11-05 as a detailed control room with full parity (S19). The first, minimal draft was rejected and deleted from the canvas.

**Shell:** back to Robots, "Reachy app", three tabs, the save state ("Saved" / "Not saved: … Trying again…"), the Live dot, Logs.
- **Talk** (one Reachy: today's reachy_chat dashboard). The robot's brain and key badges and the volume slider (0-150, boost above 100) sit in the top bar.
- **Group** (two or more Reachys: today's group page): Group talk, Interrupt, Free talk, Choir and groups.
- **Wizard of Oz** (today's Operator Board, plus a Say box).

**Talk (board 1)**
- Robot panel: state with the LISTENING / THINKING / SPEAKING badge, address, daemon state, Stop system / Start system, and Details (Add WiFi for staff).
- How it talks:
  - Brain, with "(no key)" marks;
  - Language;
  - Brain voice, or ElevenLabs v4 voice with its voice list;
  - Camera vision with its source note;
  - the honest message line ("Applies to the next conversation", start refusals).
- Character:
  - on/off switch (off keeps the text; Clear wipes it);
  - presets or "Write my own";
  - the text with an n / 1500 counter;
  - character voice, used while Brain voice is Default;
  - Save and Clear.
- Conversation:
  - session id, turn count and this-turn timer;
  - the backend line;
  - bubbles with turn numbers and the gesture played;
  - aborted turns;
  - **the robot's words typed in live as they are spoken**;
  - End conversation, with the goodbye phrases named.
- Event log with Copy logs.

**Group, before start (board 2)**
- Stage:
  - phase and big status line;
  - **the Get ready progress text** (today a bug hides it);
  - timer and bar, +1 min;
  - Group talk / Interrupt / Free talk with their sub-lines;
  - Get ready, Stop / Stop now, Disconnect;
  - the mic line with Use robots' mics / Use the DJI mic;
  - start hints;
  - the checks pill with every check chip (pending checks show a spinner) and "last checked".
- This conversation:
  - Topic, Language, Minutes, Lab intro;
  - each setting is tagged with the modes that use it (Topic and Personality: Group, Interrupt; Lab intro: Group only; Interrupting: Interrupt only);
  - ElevenLabs credits;
  - a "Room and network" fold: Gap (0.2-3.0 s, the hub's real range), Voice threshold, People cut in, Audience mic with meter, Slow network, Heads turn the other way, Simulate.
- Robots:
  - header: save state, groups summary, Choir, Groups…;
  - one seat card per robot: seat number and colour, Label, real name, group tag, state, mic meter with the echo check, ‹ ›, Included, Listens, Camera, Personality, Voice service and Voice (remembered per service), Writer, Interrupting 0-5, Gestures, Volume 0-250, "Voice: X, writing via Y", Copy to others, + (laptop robot) and ×;
  - Order, Included and Listens lock while connected, and say so;
  - keys 0-5 set every robot's interrupting.

**Group, live (board 3)**
- Compact seat cards (voice service, voice, writer, interrupting, volume, link to the rest), with the speaker ringed.
- Transcript lines show:
  - seat colour, label and robot name;
  - move, ms and time;
  - "cut off" with strike-through;
  - People rows with "heard closest to";
  - operator and hub notes;
  - the current line highlighted, **the robot's line typed in live as it is spoken**.
- The People live box types in what the person says.
- Steer, with Last steer.
- Conversation settings stay editable while it runs.

**Board 4:** the Groups dialog (name, kind, members, "taken", validity notes, Add group, Everyone: one Choir, No groups) and the Copy dialog (targets, the eight fields).

**Board 5, Wizard of Oz:**
- state and warning chips, Reload script, Rebuild audio, STOP · Esc;
- Now playing with countdown, bar and text;
- the shortcut legend;
- cue sections with hotkey, duration, text, motion, "motion only", "no audio: press Rebuild", edit and + add cue, with the next cue outlined;
- plus Say anything, quick saves and a Said history with Again.

**Boards 6-7:** the cue editor and every Talk and Group state:
- refusals, ElevenLabs with GPT-Live, system stopped with its reason, robot lost, ended with a summary, character limits;
- volume refused, no camera, robot held by the Group or another app, robot WiFi;
- start banner, not saved, check failed, closing / Stop now, over time, Interrupt lines, start hints, every mic state;
- locked seat with a duplicate label, no Reachys, low credits, notes with Jump to latest, toasts.

**How to build it** (route A of `REACHY-ONE-APP-PLAN.md`: bridge first, keep both engines)
1. **Hub proxy** `/api/reachy/<key>/...` to the robot's reachy_chat (status, start/end, persona, backend, volume, show cues), plus a WebSocket relay for its transcript and state. The Talk screen renders that. Students never see reachy_chat's own dashboard again.
2. **`/reachy` page** = the group page re-skinned, plus the Talk and Wizard of Oz panes. The mode follows the count. `/group.html` redirects to it.
3. **Wizard of Oz:**
   - the show board comes into the hub page through the proxy;
   - cue editing uses the existing `show_editor`;
   - **free "Say" text** uses live TTS through the conductor's voice chain and plays on the robot's player;
   - with two or more robots, the line goes to the robot picked.
4. **Every group-page control stays** (S19); the 2026-11-04 list of controls to hide is withdrawn. Fix while porting: show the Get ready progress text (`group.js:408-409` precedence bug), use the hub's real ranges (Gap 0.2-3.0 s, Minutes 0.5-60), drive the "Applies to the next conversation" hints from live state, and turn reachy_chat's raw 409/503 start errors into sentences.
5. **Seat locking stays as today:** Order, Included, Listens, + and × lock while connected, with the reason shown.
6. **One transcript folder** in `DATA_DIR\conversations`. reachy_chat's log is copied there when a Talk ends. A small "Saving transcript" mark shows during every conversation, and a Settings switch turns it off. Research participants talk to these robots, so saving must never be invisible.
7. **Size:** about 3-5 days after v1. It does not fit the 11-11 week.

## 6c. Pepper dashboard (pepper_app, :8780), redrawn in the lab style

Canvas row 8 (Pepper boards 1-3). Same features as today's Pepper Operator (S19); `docs/parity/pepper.md` is the checklist.

**What's on it**
- Top bar:
  - robot chip (address, battery, charging, firewall hint when the agent can't call back);
  - tablet chip (live / not connected / lost, with Reload);
  - volume, the GPT and ElevenLabs key badges;
  - More (emoji check, put a message or choice on the screen, lab facts, rehearse without the robot), Logs, Stop everything.
- Conversation card:
  - state badge and the **real** model;
  - Experience (the "with emoji" demo stays greyed), Engine, Language, Voice (list follows the engine);
  - Vision, AI drives screen, Gestures, **Web search**;
  - Start/End, Resume AI, turns, clock, latency, step;
  - Repeat question and Skip.
- Two rules made visible:
  - a toggle that the chosen experience ignores is greyed, with the reason;
  - while a conversation runs, Engine, Language and Voice say "apply at the next Start".
- Wizard of Oz:
  - Say: pause AI, tell AI, a new Pause AI button, all 10 quick phrases, free text (Enter talks), Talk, Stop;
  - Move: Stop motion, 8 gestures and Walking, head Left/Center/Right, Stand, Face tracking showing its real state.
- Live conversation:
  - mic line and meter;
  - partial Pepper text;
  - Person and Wizard of Oz bubbles, event and tap pills;
  - "Heard, not used" with Accept;
  - event log with Copy.
- Camera: Top/Bottom, faces, Save. The tablet preview is clickable to tap for the person, with presentation select, Delete, Prev/Next, Home/Clear, thumbnails and drop to upload (also the AI's picture library).
- States board: every link, key, refusal, stuck, paused, charging, upload, empty and toast state. Rehearsal board: the simulator.
- Fix while porting: bundle Tailwind and pdf.js (the lab WiFi may have no internet), and replace the browser prompt for "Mark broken" with an in-page field.

**New: Web search** (asked for 2026-11-05)
- A toggle in the Conversation card, with an info hover: "Pepper can look things up online. Answers may take a few seconds longer."
- **Free conversation only.** The scripted demo is a closed flow and never makes things up, so there the toggle is greyed: "Not in the scripted demo".
- Also greyed, with the reason, when the laptop has no internet or the key can't search.
- **How:**
  - when on, the free-conversation Realtime session gets one function tool, `web_search(query)`;
  - the hub runs it through the OpenAI Responses API with its built-in web search tool, on the same GPT key;
  - the call returns a 2-3 sentence answer, which is fed back to the Realtime model, and Pepper says it.
- While it searches:
  - Pepper says a short pre-made "Let me check…" (in the conversation voice and language) so the silence isn't awkward;
  - the badge reads SEARCHING;
  - the chat gets a pill `Searched the web: "<query>" · 2.8 s`;
  - the log gets the query, the time and the number of sources.
- Build notes (from the parity check):
  - today free mode sends `tools: []` with `tool_choice: none`, and its prompt says Pepper can't look things up; all three follow the toggle;
  - `web_search` joins the server's live set (with vision, AI screen, deck, emoji), so it applies mid-conversation;
  - the "AI stopped answering" watchdog (10 s) pauses during a search;
  - free mode needs its own follow-up after the tool result (today's follow-up text is written for the script);
  - greyed reasons: scripted demo, no GPT key, no internet, or the key can't reach the search endpoint (checked when the toggle is turned on).
- Limits:
  - an 8 s timeout, after which Pepper answers without it and says so;
  - lab questions still come only from `lab_facts.md`;
  - the setting is saved like the other toggles and applies live.
- Cost: one extra Responses call per search, on the same key.
- The same toggle could later go into reachy_app's Talk and Group writers.

## 7. Network

- **Run the sweep always.** Today it runs only when Furhat is enabled (`hub/discovery/manager.py:79`), and the lab WiFi needs it for every robot.
- **One network state:** ok, no WiFi, wrong network, hotspot on 5 GHz, VPN on, network isolates devices, searching.
- **Remember** "robots were last seen on WiFi X", so a wrong-network warning works from a cold start (`hub/discovery/selfnet.py:113-116`).
- **Skip VPN, Tailscale and virtual adapters** in the sweep (`hub/discovery/netscan.py:437-455`).
- **Remove the "does not look like a phone hotspot" rule** (`hub/wifi.py:172-175`). A failed `netsh` read means unknown, not a warning: newer Windows hides the WiFi name unless Location is on.
- **Robot networks** become a list: the lab WiFi plus demo hotspots. Decide whether the lab WiFi name may ship in the public default config (open question 2).

## 7b. Battery (S17)

| Robot | What we can read | What the card shows |
|---|---|---|
| NAO, Pepper | Battery % from the probe every few seconds (`hub/adapters/naoqi.py:430-441`); charging state from NAOqi's battery service | Battery icon and % next to the status pill, in tabular figures, with a charging mark when plugged in. At 20% and below: red, and "Plug it in soon." At 10% and below: the top bar says "NAO battery 8%. Plug it in now." **NAO Stand up asks first when the battery is low** (a falling robot). |
| Reachy Mini (wireless) | **Nothing.** No battery reading in the daemon or the SDK we have (SDK 1.7.3; `hub/adapters/reachy_wireless.py:163`). Check daemon 1.13's `GET /api/daemon/status` on hardware. | Nothing, until a reading exists. When a running Reachy goes silent, the card says "Battery may be flat. Charge it." Optional hint: "On for 1 h 20 min" from the robot's uptime over SSH, with a warning after a run time the lab measures once. |
| Furhat | Mains powered | Nothing |
| This laptop | `psutil.sensors_battery()` | During a conversation or demo, a small chip "Laptop 15%" when below 20% and not charging. The laptop runs the group conversation, so a flat laptop ends the demo. |

Today the low gauge turns red below 20% with no message at all (`web/app.js:372-376`; nothing in `hub/core.py:322`). Add a `battery_low` event so the bar can show it.

## 7c. Demos on a phone hotspot (S18)

- **The limit:** 5 devices per phone hotspot, and this laptop is one, so 4 spots are left. **Pepper takes 2**, because its chest tablet joins the WiFi separately from the robot. Each Reachy, NAO and Furhat takes 1. Anything else on the hotspot (a second laptop, the presenter's phone) also takes a spot.
  - Examples: laptop + Pepper + 2 Reachys = 5, full. Laptop + 4 Reachys = 5, full.
- **The app counts.** When the laptop is on a phone hotspot (`hub/wifi.py` already tells phone hotspots apart), the network chip shows **"Phone hotspot 4/5"**: the laptop, plus each robot found, plus 1 for Pepper's tablet. At 5/5 the chip turns amber, and the bar says "Hotspot full. Another device won't join." The limit is a setting (`hotspot_max`, default 5).
- **Demo planner (screen 11)**, from the chip or from Settings:
  - pick the robots you're bringing;
  - see the 5 spots fill, then "Fits" or "1 too many: leave a robot or bring a second phone";
  - **a short checklist:**
    - Maximize Compatibility on (2.4 GHz);
    - every robot already knows this hotspot (taught in the lab beforehand with Add WiFi or the bring-up, a staff step);
    - Pepper's tablet knows it too (Add WiFi doesn't teach the tablet);
    - hotspot on **before** Furhat starts (Furhat only looks for WiFi at boot);
    - phone on a charger.
- **Robots on two hotspots can't talk together.** A group conversation needs all its robots on one network. For more than 4 robots, a small travel router (20+ devices) replaces the phone. See open question 7.

## 8. Schedule

Work days left: Thu 11-05, Sun 11-08, Mon 11-09, Tue 11-10, Wed 11-11 (last day; the interim lab owner takes over).

| Day | Must ship | Proof |
|---|---|---|
| 11-05 | Data folder split (2.1). Keys: test, detect, best key, no paid start (3). Reachy slim deploy (2.2). | Hub runs from a copied folder with data elsewhere; a bad key shows a sentence |
| 11-08 | Portable runtime, `build_release.ps1`, `install.ps1`, app window, single instance, no console windows (2.2-2.4). First release on GitHub. | The paste-one-line install works on a second laptop |
| 11-09 | New main page: top bar, keys popup, warning bar, cards with battery, More robots, logs drawer, Advanced gate, friendly errors (6, 7b). Hotspot count on the network chip (7c). | A non-technical person installs and talks to a Reachy without help |
| 11-10 | **In the lab:** requirement model and the kit setup (4.1, 4.3); Pepper outbound link and tablet page from the robot; Furhat password; "in use" marker; Furhat skill rebuilt without a key. Test 2.8.7.4 on NAO and Pepper. | Each robot from a clean laptop, plus the failure table in 9 |
| 11-11 | Fixes, README install block, student guide with pictures, lab-manager guide for capped keys, handover note. | The interim lab owner installs it from the README |

**Moves to the next developer if time runs out,** in this order:
1. The one Reachy conversation app (6b): proxy, `/reachy` page, Talk, Group and Wizard of Oz screens.
2. The demo planner screen (7c). The hotspot count itself ships in v1.
3. Reachy Lite setup.
4. Phase 2 of "every key on every robot" (5).
5. Light CRAB for NAO.
6. Mac.
7. Code signing.

## 9. Test plan

- **A clean Windows laptop or VM, standard user, never had Python.** The SDK's Python, VC runtimes, firewall and Defender behaviour can only be proven there. The development laptop already has `C:\Python27`, VC90 and firewall rules, so it proves nothing.
- **Failure table to walk through:**
  - laptop on the wrong WiFi;
  - VPN on;
  - robot off;
  - Reachy battery dies mid-talk;
  - key typo; key with no credit;
  - offline while adding a key;
  - Pepper blocked by the firewall;
  - Furhat wrong password;
  - kit zip half-downloaded;
  - two laptops on one Reachy;
  - update while robots run;
  - a Hebrew Windows user name;
  - phone hotspot with 5 devices, then a 6th robot switched on;
  - Pepper's tablet on a different WiFi from Pepper;
  - NAO and Pepper at 15% and 8% battery, and Stand up on a low battery;
  - a Reachy dropping out mid-group (the others carry on);
  - a Talk in Hebrew and a Group in English.
- **Every screen on the canvas** is checked against the real app at 1280×800 and at a small laptop width.

## 10. Risks

- **Secret leaks at build time.** Build only from fresh clones; check the zip for `.env`, `keys`, `*_key.txt`, `.skill` and `data/` before uploading.
- **Shared robots, mixed versions.** Every robot-mode Launch pushes the laptop's reachy_chat to the robot by size and date (`hub/adapters/reachy_wireless.py:503-508`). Students on different app versions would overwrite each other. Version-stamp the robot copy and refuse to downgrade.
- **Factory SSH passwords on an open WiFi.** These are Reachy's Pollen default and NAO/Pepper's `nao`. Changing them later touches three code paths; make them one setting first.
- **MAX_PATH.** Deep SDK paths under a long user folder break Windows' "Extract All". The app's own extraction to `C:\LabaLab\` avoids this.
- **Admin rights.** Students are not admin (answer 2026-11-05). Nothing in the app needs it: per-user install, no firewall rule (Pepper inverted), the kit ships its own Python 2.7. Only the Pollen desktop app (Reachy Mini Lite) may need an admin install; the setup card says to ask the lab.
- **The first Reachy launch on a factory robot** pip-installs on the robot, which needs internet there.

## 11. Open questions

1. **Furhat Studio password:** the lab hands it out with the key, or Furhat is set to a known lab password at the skill-rebuild visit?
2. **May the lab WiFi name ship in the public default config?** It's an ISP network name, not a secret, but the code keeps it out on purpose today.
3. ~~Are student laptops admin-capable?~~ **Answered 2026-11-05: no.** See BUILD-PLAN "No admin, no firewall".
4. **NAO kit version:** after testing 2.8.7.4, is it good enough, or does the lab need 2.8.6.23 (not publicly available)?
5. **The Wizard of Oz Say box:** which voice? The robot's normal voice needs live TTS with the student's key; pre-recorded cues need a rebuild step.
6. **Reachy battery:** does daemon 1.13 report it? If not, is "on for N minutes" from uptime useful, and what run time should trigger the warning?
7. **Demos with more than 4 robots, or with Pepper and 3 Reachys:** buy a travel router, or always bring two phones and split robots that don't need to talk together?
8. **Transcripts:** saved by default with a visible mark, or off by default? Is research consent handled outside the app?

## 12. Every UI element and state (checklist for building and testing)

Tick each of these against the canvas and then the real app. "Drawn" means it is on the canvas.

**Update 2026-11-05 (later): the hub was redrawn for full parity (S19), boards 4-16, and reachy_app is drawn, boards reachy_app 1-7.** The earlier note follows.

**Update 2026-11-05: every hub state below is now drawn.** Canvas row 5 has screens 16-18:
- app states: starting, hub stopped, update available, updating, Logs dot, every network chip;
- key and setup states: no credit, offline, unknown kind, voice-only key, downloading with Cancel, verifying, download broke, wrong zip, disk full, Windows permission asked and refused;
- card states: searching skeleton, connecting, in a group, unknown robot, NAO postures, NAO Stand on a low battery, Pepper charging, long name.

Settings now also has "Save transcripts", the demo planner link and Quit. Where a line below still says "not drawn", it now refers only to the conversation screens, which belong to reachy_app (6b).

**App shell**
- Starting: the window opens on "Starting..." until the hub answers (not drawn).
- Hub stopped: an overlay "Robot Hub stopped" with **Restart** (not drawn).
- A second launch focuses the open window.
- **Update available:** a quiet line in the top bar, "New version", with **Update**, which runs the installer (not drawn).
- Quit in Settings.
- Smallest window: 1024×700; check at 1366×768.
- Light theme only in v1 (dark tokens exist for later).
- `prefers-reduced-motion` keeps fades and drops movement.

**Top bar**
- Logo.
- Network chip: lab WiFi / Phone hotspot n/5 / wrong network / no WiFi / VPN on (drawn: lab WiFi, wrong network, hotspot).
- **Logs**, with a small dot when a new error arrived while the drawer was closed.
- Settings.

**Message bar.** Only one bar shows at a time, highest priority first:
1. hub stopped;
2. wrong network;
3. no working key;
4. robot error;
5. battery at 10%;
6. hotspot full.

Blocking bars can't be dismissed; the others can.

**Robot card states** (drawn unless marked):
- searching: skeleton cards for the first ~10 s (not drawn);
- nearby; ready; talking + timer; Wizard of Oz;
- in a group (not drawn); in use by another laptop;
- needs a key; needs setup; needs password; blocked by Windows; stopped/lost;
- battery low;
- unknown robot type (not drawn: a plain card, "Not supported yet").

**Robot card parts**
- Picture, name, status pill (always under the name), battery when known, Say hi, one primary and at most one secondary action.
- Long names wrap to two lines; never truncate a robot name.
- A "..." menu only with Advanced on: rename, per-robot key, Add WiFi, disconnect.

**NAO card.** Sit / Stand / Lie down. Stand asks first when the battery is low. No Talk until CRAB-light.

**Pepper card.**
- Talk opens Pepper's own app, `pepper_app`: the scripted demo or free talk. Its dashboard is still the technical one, so re-skin it after v1.
- The chest tablet's WiFi state, if it can be read.

**Furhat card.** Talk starts the skill. Furhat Studio is never shown to students.

**Empty states**
- No robots nearby (drawn).
- No Reachys for a conversation: "No Reachys nearby" with a link back (not drawn).
- No keys (drawn).

**Keys popup states.** Drawn interactively: empty, typed + detected, checking, works, didn't work. Still to draw:
- no credit;
- offline ("checked later");
- unknown prefix: four service chips to pick from;
- the lab key path text.

**Setup sheet states**
- Drawn: idle, downloading %, unpacking, done.
- Still to draw:
  - Cancel;
  - verifying;
  - failed: download broke (retry), wrong zip, disk full, admin refused (Ask the lab).

**Logs drawer**
- Live; filter per robot; Copy all; Save a report (drawn).
- "Jump to latest" when scrolled up; nothing yet; error lines in red (partly drawn).

**Settings**
- Keys with status and credit; Remove (two taps); Check again; robot passwords; extra software; version and updates; staff switch (drawn).
- Not drawn: "Save transcripts" switch, Quit, demo planner link.

**Conversation**
- Who/How/About/Start (drawn); Talk live (drawn); Group live (drawn); robot settings (drawn).
- Not drawn:
  - connecting state;
  - robot dropped out;
  - muted;
  - Ended summary;
  - Wizard of Oz with 2+ robots (Who says it);
  - TTS failing in Wizard of Oz ("Say isn't working: key").

**Toasts.** Only for the student's own actions ("Key saved", "Copied", "Report saved"), 3 s, bottom right, one at a time. Never for background errors; those go to the bar or the card.

**Confirmations.** Remove key; Wrap up, then Stop now; NAO Stand on a low battery. Students can never take over another laptop's robot. Staff can, with Advanced on.

**Copy and accessibility** (S9)
- One status word, short sentences only for problems, robot names as the robots say them.
- Counts pluralised.
- Tabular numbers for timers, percentages and money.
- 44 px targets; visible focus rings; `aria-live` on status and transcripts.
- Contrast from the tokens.
- Keyboard shortcuts **only** inside Wizard of Oz (Space, Esc, S/D/F, 1-9). The group page's global 0-5 keys go.
