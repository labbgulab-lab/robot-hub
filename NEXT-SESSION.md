# Robot Hub — where things stand

**Updated 2026-10-06, after the 2026-10-05 lab day.** Four robots — reachy2,
reachy3, Furhat and NAO — went detect → Connect (spoken line) → Launch from the
hub over WiFi, **running at the same time**: the headline requirement.
`PLAN.md` is still the design authority. The day's full summary is
`..\SESSION-2026-10-05.md`.

## Every robot joins the lab hotspot — and must save it

**SSID `Tomer Iphone`** (password: ask Tomer — it stays out of git). Each robot has to *save* it
(auto-connect), or it comes up off-network next time and the hub sees nothing.
On 2026-10-05 neither NAO nor Furhat had it saved.

- **NAOqi (NAO, Pepper):** cable once, `ping nao.local` (IPv6 is enough), SSH
  `nao`/`nao`, then interactive `connmanctl`: `agent on`, `connect <wifi_…_psk id
  of "Tomer Iphone">`, passphrase. It is then a connman favourite.
- **Furhat:** on its own screen (needs a keyboard).
- **Reachy Mini:** reachy2 and reachy3 already have it.
- **The laptop roams back to campus WiFi on its own** (it did mid-test). Turn
  off auto-connect for the campus network during lab sessions.

## Next lab session, in order

1. **Restart the hub**, then check the Launch button live: spinner + seconds,
   auto-open of the system tab, failure reason on the card, log Copy button.
2. **reachy2:** Relaunch and ask "what am I holding?" (camera vision, tested on
   photos only). Confirm the 0.35 s audio pre-buffer removed the cuts.
3. **NAO_LLM with a real voice** on the laptop mic (a full turn passed with a
   WAV file only).
4. **NAO Launch starts its speaker server itself** (`_ensure_speaker_server`
   runs `deploy_nao.py` when port 9600 is closed, then waits on the port, not
   on deploy_nao's 45 s). Built but not yet pressed on the robot.
5. **Disconnect during Launch** (fixed 2026-10-06, offline-tested): the
   in-flight sync / deploy child is killed, and an SSH start already on the
   wire lands before Disconnect clears the robot. Try it once on hardware.
6. **Robot files panel** (2026-10-06): OpenAIChat 1.3.0 is in the library,
   keyless. Download it with a GPT key from the page and import it on Furhat.
7. **reachy3 has a hardware fault** — Stewart leg 5 (motor ID 15) is stuck at
   22°; see TASKS.md. Avoid long sessions on it. Use reachy2 for demos.

## Status

| | |
|---|---|
| `pytest tests -q` | ✅ 102 passed |
| Wireless Reachy detect + Connect | ✅ reachy2 2026-09-23, reachy3 2026-10-05 |
| Wireless Reachy robot-side Launch | ✅ reachy3 2026-10-05 (first install + resyncs) |
| All three backends on the robot (Gemini / GPT-Live / ElevenLabs) | ✅ keys reach the robot; Gemini he/en/auto and GPT-Live he/en/auto talked |
| NAO wireless detect + Connect | ✅ 2026-10-05 (`172.20.10.14`) |
| NAO Launch (NAO_LLM panel opens) | ✅ after a manual `deploy_nao.py` |
| Several robots at once (Phase 5) | ✅ reachy2 + reachy3 + Furhat + NAO, 2026-10-05 |
| Network loss → auto-reconnect (Phase 6) | ✅ laptop roamed off the hotspot; reachy3 reconnected alone on return |
| Furhat on hardware | ✅ 2026-10-05 (Connect sets the English voice; skill OpenAIChat 1.3.0) |
| NAO posture buttons (Sit / Lie down / Stand up) | ✅ with a heat guard |
| Reachy Lite | ❌ not plugged in |
| Pepper card (detect, Connect speaks, battery, Launch = Say-It dashboard) | ✅ 2026-10-06 on hardware (NAOqi 2.5.10.7); the dashboard is in this repo, `pepper_dashboard/` (2026-10-07) |

## Run it

```powershell
cd $HOME\Desktop\job\robot-hub
.\run.ps1              # venv, deps, server, opens http://127.0.0.1:8099/
.\run.ps1 -Doctor      # environment check with exact remedies
```

## What changed on 2026-10-05

- **Launch sends every provider's key** (Gemini, OpenAI, ElevenLabs) on stdin
  into the robot app's environment, so reachy_chat's backend picker works on
  the robot. The Keys panel accepts ElevenLabs keys; GPT keys now speak.
- **Launch always syncs reachy_chat to the robot** (incremental). Before, a
  provisioned robot kept whatever code it was first given.
- **Robot-side start command bug, found on hardware:** `a && b && app &`
  backgrounded the whole chain, whose stdin is /dev/null, so the key reads got
  nothing and the app never started — while `echo started` still ran. Only the
  app is backgrounded now.
- **NAO key check** also accepts keys from NAO_LLM's own `.env`.
- **Launch UI** (spinner, elapsed seconds, auto-open, failure reason) and a log
  **Copy** button; backend fields `launching_since` / `launch_error`.
- **No-cache header** for the page's files (needs a restart to be live).

Known gaps found today: Disconnect does not cancel a Launch still in flight
(it killed a half-started robot app); the card gave no progress during Launch
(now fixed, untested live).

Elsewhere, same day: reachy_chat GPT-Live end-of-reply detection (the model
streams digital silence, which held turns open forever — now only audible
audio counts; end gap 2.0 s); reachy_chat dashboard log fits the window;
NAO_LLM web UI uses its own origin; `naoqi/rest.py` and `naoqi/lie_down.py`
(lie it down — the crouch made NAO fall).

## Deliberately not done

- **Phase 7 (AWS/remote).** Designed for, not built. Discovery is inherently
  local; remote means a local agent, never a cloud-only hub.
- **Furhat silent pre-warm.** Neither captured control path has a
  generate-without-speaking request, and `core.py` speaks right after
  `connect()`, so warming there would say the sentence twice. Instead the
  adapter allows a cold phrase its ~1.1 s and holds a warm one to 4 s.
- **Patching `NAO_LLM` to use NAO's own microphones.** Still the right fix —
  it removes the contention instead of managing it, and it is what lets NAO be
  in a different room from the laptop. That is a change to `NAO_LLM`, tracked
  against that project, not the hub. The hub arbitrates regardless.
- **Robot photos.** Drop squares into `web/photos/<type_id>.png`; the cards
  already look for them and fall back to a glyph.
