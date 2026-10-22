# Put a Reachy on your hotspot — over Bluetooth (plan, not built)

Written 2026-10-12. Status: **planned only — nothing in the hub has changed.**
Build it after the 2026-10-13 Itai demo, not before.

## Goal

A student arrives with their own phone hotspot. Tomer's hotspot is off, Tomer
is not in the room. The student powers on reachy1, opens the hub, and in about
30 seconds the robot is on *their* hotspot and its card lights up. No Pollen
desktop app, no joining a robot WiFi, no cable, no SSH.

## Why Bluetooth (verified read-only on reachy1, daemon 1.11.0)

Daemon 1.11 ships BLE WiFi provisioning (spec on the robot:
`/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/daemon/app/services/bluetooth/BLE_WIFI_PROVISIONING.md`).

- Bluetooth is up whatever the WiFi is doing, so a robot still hunting for
  "Tomer Iphone" (or on nothing) can be moved. The laptop never leaves the
  student's hotspot, and the student's iPhone keeps hosting it throughout.
- GATT service `12345678-1234-5678-1234-56789abcdef0`;
  command `...def1` (write, UTF-8 text); response `...def2` (read + notify).
  Hardware ID characteristic `...def7` (in the status service `...def3`).
- Commands: `PIN_<pin>` opens a 300 s session (wrong-PIN throttle);
  `WIFI_STATUS` (public: mode, connected, error); `WIFI_KEYEX`
  (`{kid, pk, alg}`); `WIFI_SCAN` (session: SSIDs the robot sees);
  `WIFI_CONNECT_ENC <json>` (session); `WIFI_FORGET <ssid>`; `SET_NAME <name>`.
- Async: a write returns `OK: working`; the real answer is the *next*
  notification on `...def2`. Subscribe before writing.
- Password sealing `x25519-hkdf-sha256-aesgcm`: ephemeral X25519 against the
  robot's `pk`; `key = HKDF-SHA256(shared, salt=PIN utf-8,
  info=b"reachy-mini-wifi-psk-v1", 32)`; `AES-GCM(key, 12-byte nonce, psk,
  aad=ssid utf-8)`; send `{"ssid","kid","epk","nonce","ct"}` base64, `ct` =
  ciphertext||tag (exactly what Python `AESGCM.encrypt` returns).
- Every unit advertises the BLE name **`ReachyMini`**. Tell them apart by
  `...def7`, which equals the daemon `hardware_id` = the hub's `unit_id`
  (reachy1 = `6563a10e4204345e`, already in `config.example.toml`).
- PIN = last 5 chars of the audio-device serial (`get_pin()` in
  `bluetooth_service.py`). Pollen says it is printed on the robot.

## Traps the tool must handle

1. **A failed connect deletes the network and flips the robot to its own
   `reachy-mini-ap`** (`connect_to_wifi_network_sealed` in `wifi_config.py`).
   So run `WIFI_SCAN` first and refuse to send if the hotspot is not in the
   robot's list ("turn on Maximize Compatibility / 2.4 GHz, keep the Personal
   Hotspot screen open, try again").
2. **Older daemons have no WIFI_* commands.** They answer `ECHO: WIFI_STATUS`.
   Detect that and say "this robot needs a software update first".
   Check reachy2, reachy3 and the 10 new units before relying on this.
3. All units share one BLE name and the hostname `reachy-mini`; never trust a
   name, always read `...def7`.
4. If Tomer's hotspot and the student's are both in range, both saved networks
   have priority 0. Verify which one NetworkManager prefers after a reboot
   (expected: most recently used).
5. macOS asks for Bluetooth permission for the terminal/Python running the hub
   on first use. Windows needs nothing (Intel BLE on this laptop, `bthserv`
   running).
6. Never log the hotspot password; never write a PIN to a tracked file (this
   repo is public). PINs go only in `keys.local.json` (gitignored).

## Design

**Where:** the *Network setup* panel (`web/index.html` ~line 104, step 2,
"Reachy Mini" block), not a robot card. A robot not on the network has no card
yet. This replaces today's text that sends students to the desktop app.

**Backend, Python (`bleak` + `cryptography`)**, not Web Bluetooth, for the hub:
works in any browser, fits the hub's "Python does robot I/O" rule, and is
testable with a fake transport. Web Bluetooth stays the later no-hub page.

### Student flow (the panel)

1. The panel already knows the laptop's SSID and band (`hub/wifi.py`). If it
   is 5 GHz or not a hotspot, stop there (existing message).
2. **Find Reachys nearby** → BLE scan ~8 s → for each `ReachyMini`: read
   `...def7` + public `WIFI_STATUS` → list rows like
   `reachy1 — on "Tomer Iphone"` / `reachy1 — not connected` /
   `Unregistered Reachy (id 1bf3…)`. Names come from `config.toml` units.
3. Pick one → fields: **PIN** (prefilled if remembered for that unit),
   **hotspot name** (prefilled with the laptop's SSID), **password**,
   checkbox "remember this robot's PIN on this laptop".
4. **Put it on my hotspot** → progress lines via the event bus
   (`bus.emit_log`, as `join_wifi` does for NAO):
   PIN → `WIFI_SCAN` (trap 1) → `WIFI_KEYEX` → seal → `WIFI_CONNECT_ENC` →
   poll `WIFI_STATUS` every 2 s, up to 60 s, until `mode == wlan` and connected
   to that SSID; else show `WIFI_STATUS.error`.
5. On success → trigger an immediate discovery pass; the card appears.
   Text-only UI, no emojis (lab rule).

## Build steps

### Step 0: Spike on hardware (read-only, ~20 min, before any hub code)
In a scratch venv (`pip install bleak cryptography`), from this laptop:
- scan → see `ReachyMini`; connect; read `...def7` == `6563a10e4204345e`;
- subscribe `...def2`; write `WIFI_STATUS` → expect JSON;
- write `PIN_<pin>` → `OK: Connected`; `WIFI_SCAN` → SSID list;
- confirm a plain BLE write needs no Windows pairing prompt (Just Works).
Get the PIN with (SSH pollen/root, prints 5 chars; do not save it in a file):
`python3 -c "import sys; sys.path.insert(0,'/venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/daemon/app/services/bluetooth'); import bluetooth_service as b; print(b.get_pin())"`

### Step 1: `hub/ble_wifi.py` + tests
- `seal_password(ssid, psk, pin, robot_pk_b64, kid) -> dict` (pure).
- `ReachyBle` transport wrapper: `scan()`, `read_hardware_id()`,
  `command(text, timeout)` (subscribe → write → await the next non-`OK: working`
  notification).
- `provision(unit, pin, ssid, psk, on_step)` running the flow + traps 1–2.
- Tests (`tests/test_ble_wifi.py`): round-trip the seal against a copy of the
  daemon's `_open_sealed_psk` (copy it from the robot's `wifi_config.py` into a
  test helper); fake transport for: wrong PIN, hotspot not in scan (must NOT
  send connect), old daemon (`ECHO:`), timeout, success.
- `requirements.txt`: add `bleak`, `cryptography`.

### Step 2: API (`hub/main.py`, `hub/core.py`)
- `POST /api/reachy-setup/scan` → `[{unit_id, name, registered, mode, connected}]`.
- `POST /api/reachy-setup/join` `{unit_id, pin, ssid, password, remember_pin}`
  → runs `provision`, streams steps on the bus, returns ok/error sentence.
- Remembered PINs: new section in `keys.local.json` keyed by unit_id (via
  `hub/keys.py`), never echoed back in full to the page.
- One provisioning at a time (lock), like the NAO join.

### Step 3: UI (`web/index.html`, `web/app.js`, `web/style.css`)
- Replace the Reachy block in setup step 2 with the flow above; keep the
  `reachy-mini-ap` manual route as a collapsed "no Bluetooth?" fallback.

### Step 4: Fresh-laptop path
- `run.ps1` already reinstalls after a pull that changed `requirements.txt`.
  `run.sh` installs only when it creates the venv — give it the same
  requirements stamp so Mac users get `bleak` after `git pull`.
- `hub/doctor.py`: add a "Bluetooth LE available" check.
- README + `docs/SETUP.md`: "Put a Reachy on your hotspot" section.

### Step 5: Hardware acceptance (needs a second hotspot, e.g. the Galaxy)
Coordinate first: this moves reachy1 off "Tomer Iphone".
1. Laptop on hotspot B (2.4 GHz). reachy1 on "Tomer Iphone" → hub moves it to
   B → card lights → Launch works.
2. Tomer's hotspot off, reachy1 rebooted (hunting) → moved to B.
3. Hotspot B on 5 GHz → refused before sending, robot untouched.
4. Wrong PIN → clear message; correct PIN after → works.
5. Reboot reachy1 with both hotspots on → note which it picks (trap 4).
6. Same on reachy2/reachy3 after checking their daemon version (trap 2).
Then commit + push; students `git pull` and start the hub as usual.

### Later (not in this build)
- No-hub page: one static Web Bluetooth page (Chrome/Edge on Windows, Mac,
  Android; not iPhone browsers — Bluefy works) on GitHub Pages, QR on each robot.
- "Forget a hotspot" button (`WIFI_FORGET`) to keep the robot's list short.
- Label every robot with its name + PIN (Tomer, once per unit, incl. the 10 new ones).

## Until this is built (no-code fallback)

Tomer's hotspot off → power on reachy1 → after ~1 min it opens WiFi
`reachy-mini-ap` (password `reachy-mini`) → student joins it **from the
laptop** (the iPhone must keep hosting its hotspot) → browser
`http://10.42.0.1:8000/settings` → choose their hotspot, type the password →
laptop back on their hotspot → card lights. Not yet tried on daemon 1.11.
