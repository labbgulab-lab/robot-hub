# One Reachy app: merging reachy_chat into the group conversation

Status: plan, 2026-11-03. Nothing here is built yet except what "Done" says.
The student-facing screens for this merge (Conversation, Talk live, Group live,
robot settings, Wizard of Oz) are in `docs/STUDENT-APP-PLAN.md` section 6b and on
the "Robot Hub student app" design canvas, row 4.

## Why

Today a lab member has two Reachy apps and has to know which one to open:

| | **reachy_chat** (one robot) | **Group conversation** (the hub's `/group.html`) |
|---|---|---|
| Runs | **on each robot** (`laptop_chat.py --local-robot`), dashboard at `http://<robot>:8765/` | **on the laptop**, inside the hub; streams audio and moves to each robot's player over SSH |
| Talks with | the people, one robot | the people and each other, 2+ robots |
| Brain / voice | its backend picker (Gemini Live, GPT Realtime, ElevenLabs) -- speech-to-speech, low latency | writer (OpenRouter/Gemini/OpenAI) + TTS per robot (ElevenLabs/OpenAI/Gemini) |
| Has | persona switch, voice picker, volume, Show mode (cue board + editor), vision, Add WiFi, conversation logs, summaries | modes (group, interrupt, free), per-robot settings, people mic (DJI), echo-aware ears, gestures and idle life, **groups and Choir** (2026-11-03), transcript |
| Shared | `robot_streaming_player.py` on the robot (speech + moves) -- both drive it | |

Goal: **one app for the Reachys** that adapts to how many are connected:
one robot gets the one-robot experience, two or more get group modes, and
groups/Choir are there whenever there are two or more.

## Done (2026-11-03)

- Groups and Choir in the group conversation (docs/GROUP-CONVERSATION.md,
  "Robot groups and Choir"); the player's `clock` / `start_at` commands.
- Cards show the robot's real name under its label; the page grows with the
  number of robots.
- Step 3, simple form: the main page has no "Group conversation" button any
  more; a Reachy card's Launch opens the Reachy page, which shows **Talk**
  (that robot's reachy_chat, started and opened from the page) when exactly
  one Reachy is connected, and the group modes with two or more.
- Choir is every robot at the table, also robots ticked after it was
  switched on (`whole_table`).

## Target shape

One page in the hub, `/reachy` (the current `/group.html` grown up), with:

1. **Robots strip** -- the cards as now, one per connected Reachy, groups as tags.
2. **Mode bar that follows the count**
   - 1 robot: **Talk** (the one-robot conversation), **Show** (cue board).
   - 2+ robots: Group talk, Interrupt, Free talk, **Choir**, plus Talk/Show on
     any single robot picked from its card.
3. **Per-robot panel** (a card's "More"): persona, voice, volume, Add WiFi,
   Show cues -- what reachy_chat's dashboard has today.
4. **One transcript** and one log folder for everything.

## Two ways to get there

### A. Bridge first (recommended for the hand-over)

Keep reachy_chat's engine where it is (on the robot) and put its controls in
the hub page, through the hub:

- The hub already starts/stops reachy_chat per robot (`adapters/reachy_wireless.py`,
  `start_system` / `stop_system`). Add a thin proxy in the hub,
  `/api/reachy/<key>/...` -> `http://<robot>:8765/api/...` (status, conversation
  start/end, persona, backend, volume, show cues, identity), and a WebSocket
  relay for its `/ws` events (transcript, state).
- The page shows those controls when a robot is in "Talk"/"Show"; Group modes
  stop the robot's own app first, as they already do (`Session.open`).
- Cost: small (a proxy + UI), no change to either engine, no regression in the
  one-robot voice quality (Gemini Live stays speech-to-speech).
- Downside: two engines remain under one page; a fix in one does not help the other.

### B. One engine (later)

Move the one-robot conversation into the hub's conductor as a "Talk" mode with
one speaker, and retire the on-robot app (keep only the player).

- The conductor already runs with one speaker (Choir is exactly that), the
  people mic, ears, gestures and vision. Missing: speech-to-speech backends
  (Gemini Live / GPT Realtime) -- the conductor is writer + TTS, slower to
  answer (~1-2 s more) and must be measured in Hebrew before replacing them.
- Show mode (cue board, `show_player.py`, `show_editor.py`) ports almost as is:
  it plays pre-made audio + moves on the player, which the hub can do.
- Persona switch -> per-robot Personality (exists); its safety layering (typed
  persona on top of the base prompt) must be kept.
- Cost: large (weeks); do it after A has run in the lab for a while.

## Steps for A (in order)

1. Hub proxy for one robot's reachy_chat API + WebSocket relay; tests with a fake robot server.
2. `/reachy` page: the group page plus a per-robot panel (persona, voice, volume, Show).
   The count-aware mode bar; keep `/group.html` as a redirect.
3. Main hub page: one "Reachy" entry instead of per-robot "Launch" + "Group conversation".
4. One log folder: the hub copies each robot's conversation log/summary when
   its Talk ends (reachy_chat already writes them on the robot).
5. Update the hand-over docs and the lab guide screenshots.

## Open questions (for whoever takes this on)

- Is Gemini Live's latency worth keeping two engines (A) for, or is writer+TTS
  good enough in Hebrew to go straight to B? Measure with the lab's usual questions.
- Show mode: keep cue editing on the page, or files only?
- Should Choir also exist for one-robot Talk (several robots answering one
  person as one voice)? It is free in B, needs work in A.

## Risks

- reachy_chat on the robot and the hub's player connection both want the
  speaker: never run Talk on a robot that is in a group session (the page must
  disable it; `Session.open` already stops the robot's app).
- The player is shared: change it only with both apps in mind, and deploy with
  `reachy_chat\tools\deploy_robot_player.py --robot-host <ips>`.
