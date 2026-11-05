# Student app build plan and contracts

Status: building, started 2026-11-05 on branch `student-app`. Read with `docs/STUDENT-APP-PLAN.md` (the what and why), `docs/parity/*.md` (every control that must survive) and the design canvas "Robot Hub student app" (the look). A local copy of the canvas boards lives in the planning scratchpad; each work package names the boards it builds.

## Answers that close the open questions (2026-11-05)

| # | Answer | What the build does |
|---|---|---|
| 1 | Furhat's Studio password is `admin`; it is public (Furhat's site and videos) | Default `admin` in the shipped defaults; Settings can change it |
| 2 | The lab WiFi name may ship | `lab_wifi = "HOT-WiFi"`, `lab_wifi_open = true` in the shipped defaults |
| 3 | **Students are not admin** | Nothing may need admin: per-user install, no MSI, no firewall rule, **no inbound listeners on the laptop** (see "No admin, no firewall") |
| 4 | NAO kit 2.8.7.4 is good | The kit download uses the public 2.8.7.4 win64 zip |
| 5 | Wizard of Oz: pre-recorded cues; a typed new line is pre-recorded right away while typing, so Say is instant; live speech if it isn't ready | `prepare` while typing (debounced), `say` plays the prepared clip or falls back to live speech |
| 6 | Reachy battery: unknown | The hub looks for any battery or charge field in the daemon status and shows it only if present; otherwise nothing (S17) |
| 7 | One phone hotspot for now | The hotspot planner counts against 5 devices, laptop included, Pepper counts 2 |
| 8 | Transcripts saved by default | `save_transcripts = true` default, with a visible mark while saving |

## No admin, no firewall

A standard user cannot allow a program through Windows Firewall, and Windows shows a firewall prompt the moment a program listens on a network interface. So the student app **never listens on anything but 127.0.0.1**:

- The hub UI already binds 127.0.0.1:8099.
- **mDNS is off** in the shipped defaults (zeroconf binds UDP 5353). Discovery uses the netscan sweep, which is outbound only and which HOT-WiFi needs anyway.
- **Pepper is inverted.** Today pepper_app listens on 0.0.0.0:8780 (tablet) and 0.0.0.0:8782 (the agent connects back).
  - New: the agent on Pepper **listens** (robot port 8790, token-checked) and the laptop **connects out** to it.
  - The tablet page is **served by the agent on Pepper** (robot port 8791, `http://198.18.0.1:8791/screen` from the tablet). Screen state, taps and slide media travel over the one agent link.
  - pepper_app's own dashboard binds 127.0.0.1:8780.
  - The old connect-back path stays as a fallback only when the outbound connect fails (lab laptops with a rule), and says so in the robot chip.
- Everything else is already outbound: SSH to robots, Reachy daemon and reachy_chat on the robot, Furhat ws/http, NAOqi proxy calls.

## Install layout (per user, no admin)

```
%LOCALAPPDATA%\LabaLab\RobotHub\
  app\           replaced on every install or update
    runtime\     python-build-standalone CPython 3.12, packages installed into it (never a venv)
    robot-hub\   hub code, web, pepper_app, assets, defaults.toml
    reachy_chat\ reachy_chat source (deployed onto robots by the hub)
    launch.pyw   starts the hub (if not running), the tray icon and the app window
    VERSION
  data\          never touched by install or update
    config.toml  only the student's overrides
    settings.json, keys.local.json, group.local.json
    logs\, cache\, pepper\, transcripts\, edge-profile\
C:\LabaLab\naoqi-sdk\   the NAO/Pepper kit (an ASCII path; Python 2.7 breaks on non-ASCII user folders).
                        Fallback when C:\ is not writable: %PUBLIC%\LabaLab\naoqi-sdk
```

- `ROBOT_HUB_DATA` points the hub at `data\`; when unset, data stays in the repo root as today, so lab checkouts keep working.
- Config is layered: `robot-hub/defaults.toml` (shipped), then `config.toml` in the data folder (overrides). `config.example.toml` stays for lab checkouts.
- The app window is Microsoft Edge in app mode (`msedge --app=http://127.0.0.1:8099/ --user-data-dir=<data>\edge-profile`). A tray icon (pystray) has Open and Quit. Closing the window does not stop the robots; Settings › Quit does.
- Install line (README and release notes):
  `irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1 | iex`

## Hub API contract (new or changed)

All JSON. Errors are `{"error": "<sentence>", "code": "<CODE>"}` with a 4xx status. Codes are the friendly-error codes of STUDENT-APP-PLAN §6. The UI maps each code to one short sentence and one button; raw text goes to the log.

**App**
- `GET /api/app` → `{version, data_dir, update: {available, latest, notes_url}, first_run}`
- `POST /api/app/quit` → stops children and the hub
- `POST /api/app/update` → starts the installer in a new process, then quits

**Settings** (persisted in `data/settings.json`)
- `GET /api/settings` → `{auto_connect, staff_tools, save_transcripts, setup_seen, lab_wifi: {name, open}, passwords: {furhat: {set: bool, works: bool|null}}}`
- `PUT /api/settings` with any subset → the full object
- `PUT /api/settings/password/{robot}` `{password}` (Furhat)
- `POST /api/transcripts/open` opens the transcripts folder

**Keys** (`data/keys.local.json`)
- `GET /api/keys` → `{keys: [{id, provider, label, tail, status: {state: works|bad|no_credit|offline|unknown|checking, detail, credit, checked_at}, used_by: [robot names], voice_only, groups_only}], providers: [{id, label, can_talk, voice_only}], assign: {robot_key: {main?: key_id, voice?: key_id}}}`
- `POST /api/keys` `{key, provider?: "auto", label?}` → tests the key with a free call, then saves. 400 codes: `DUPLICATE`, `NOT_A_KEY`, `UNKNOWN_PROVIDER` (with `candidates`), `KEY_REFUSED`. Saved with status `offline` when there's no internet.
- `POST /api/keys/{id}/check`, `DELETE /api/keys/{id}`
- `PUT /api/robots/{key}/key` `{key_id: id|null, slot: "main"|"voice"}`
- Free test calls: OpenAI `GET /v1/models`; Gemini `GET v1beta/models` with `x-goog-api-key`; OpenRouter `GET /api/v1/key` (gives `limit_remaining`); ElevenLabs `GET /v1/user/subscription`; Qwen `GET compatible-mode/v1/models`. Detection by prefix: `sk-or-` OpenRouter, `sk-` OpenAI, `sk_` ElevenLabs, `AIza` Gemini; anything else asks.
- **No paid call at hub start** (today's group warm-up at start goes; Get ready still checks).

**Setup** (requirement model, `hub/requirements.py`)
- `GET /api/setup` → `{items: [{id: "naoqi_kit"|"reachy_lite_app"|"furhat_password", label, for: [type_ids], state: ok|missing|downloading|unpacking|verifying|failed, progress: {done, total}, detail, code, actions: [...]}]}`
- `POST /api/setup/{id}/download`, `/cancel`, `/check`, `/choose_zip` (native file dialog in the hub process), `/open` (opens a download page)
- The NAO/Pepper kit: download the public pynaoqi 2.8.7.4 win64 zip (about 358 MB) with progress, unpack to `C:\LabaLab\naoqi-sdk`, verify by running its own Python 2.7 (`PYTHONHOME=<sdk>/lib/python2.7`) with `import naoqi`. Failure codes: `DOWNLOAD_BROKE`, `WRONG_ZIP`, `DISK_FULL`.

**Network**
- `GET /api/network` → `{state: ok|searching|no_network|wrong_network|hotspot_5ghz|vpn_on|isolated, ssid, band, kind: lab|hotspot|other|none, ranges: [cidr], hotspot: {devices: n, limit: 5}, robots_network: {ssid, last_seen}}`; also pushed as the `network` event on `/ws`
- `POST /api/network/open_wifi_settings` opens `ms-settings:network-wifi`
- Robots last seen on SSID X are remembered in `data/settings.json`, so a wrong-network warning works from a cold start.

**Robots** (`/ws` `robot` event and `GET /api/robots`): new fields on RobotState
- `connect_error` (sticky until the next successful connect; ERROR then means "Lost" only after a real loss)
- `battery`, `battery_low` (below 20%), `charging`
- `in_use_by` (another laptop holds it: a marker file on the robot written by the hub that launched it)
- `needs_setup` (a requirement id: NAO/Pepper seen on 9559 without the kit get a card)
- `facts`: `{robot_software, mic, holds: [...], seen_ago}`
- `staff_only_actions`: e.g. `["nao_app"]`
- `GET /api/robots/{key}` → the full card, with facts
- `POST /api/robots/{key}/wifi` `{ssid, password?, open?: bool, save_only?: bool}` (open networks allowed; save_only = the Reachy lab fallback)

**Logs**
- `GET /api/log?limit=500` (backfill), `POST /api/log/report` → zips today's logs with keys scrubbed into the Downloads folder and returns the path
- Group conversation warnings now also go to the bus.

**Reachy app** (`/reachy.html`, replaces `/group.html` which redirects)
- Group tab: the existing `/api/group/*` and `/ws/group`, unchanged except the fixes in STUDENT-APP-PLAN 6b.
- Talk and Wizard of Oz tabs: the hub proxies the robot's reachy_chat: `/api/reachy/{key}/{path}` → `http://<robot>:8765/api/{path}` (GET/POST/PUT/DELETE), and `/ws/reachy/{key}` relays `ws://<robot>:8765/ws`. Talk starts with the existing `POST /api/robots/{key}/launch`.
- New reachy_chat endpoints (repo reachy-mini-conversation-app-bgu-lab, branch multi-provider): `POST /api/show/prepare {text}` → `{id, ready, ms}` (synthesises in the current voice and caches); `POST /api/show/say {text}` plays the prepared clip at once, or synthesises live if not ready.

**Pepper** (pepper_app on 127.0.0.1:8780): the dashboard API stays; new
- options key `web_search` (live), and model reporting `ai.model` used by the page
- `POST /api/ai/pause` gets a button; `POST /api/screen` gets the message/choice form; Mark broken takes a field instead of `prompt()`.
- Web search: free conversation only. When on, the Realtime session gets one function tool `web_search(query)`; the laptop runs it through the OpenAI Responses API with its `web_search` tool on the same GPT key (model `gpt-4.1-mini`), and returns a 2-3 sentence answer. While it runs: a pre-made "Let me check…" line, state `searching`, the stuck watchdog paused, an 8 s timeout. Lab questions still come only from `lab_facts.md`.

## Work packages and order

| WP | What | Files | Depends on |
|---|---|---|---|
| A | Hub backend: data split, layered config, settings store, app/quit/version/update, single instance, windowless children, log rotation, keys and key tests, setup/requirements and the NAO kit, network state, robot state fields, Add WiFi options, Furhat password, logs report, no paid warm-up, mDNS off by default, Reachy deploy without reachy_chat's venv, battery probe | `hub/**`, `defaults.toml`, `tests/` | — |
| B | Pepper: inversion (agent listens, tablet served from Pepper), dashboard and simulator redrawn to canvas boards Pepper 1-3, web search, new controls, pdf.js vendored, Tailwind removed | `pepper_app/**`, `tests/test_pepper_app.py` | — |
| C | reachy_chat: `prepare`/`say`, deploy helper usable without importing `conversation`, hub-driven transcripts | other repo | — |
| D | Packaging: `tools/build_release.ps1`, `tools/install.ps1`, `launch.pyw` (tray, window, single instance), icon from the logo, README install block | `tools/`, `launch/`, README | A for paths |
| E | Hub UI: `web/index.html`, `app.js`, `style.css` to canvas boards 1-16 | `web/` (main page) | A's contract |
| F | reachy_app UI: `web/reachy.html` (+js/css) to canvas reachy_app boards 1-9; hub proxy | `web/reachy*`, `web/group*`, `hub/reachy_proxy.py` | A, C |
| G | Verification: pytest, headless screenshots against the canvas, parity sweep against `docs/parity/`, a local release build and install test, student and staff guides | all | all |
