# Group conversation: several Reachys and the people in the room

Built 2026-10-19 for the 5-Reachy demo. The Reachys sit scattered on a table,
people sit around it, and everyone talks together for about 5 minutes. No
push-to-talk: the robots' own microphones hear the people.

## How it works

The hub runs the whole conversation. The robots are speakers and heads.

```
robot mics (SSH, 16 kHz) ──> VAD per robot ──> floor control ──> STT (people only)
                                                   │
                                     shared transcript (robot lines are known text)
                                                   │
               director LLM: one call -> {speaker, move, text}   (prepared while the
                                                   │              previous robot talks)
               ElevenLabs v4 turbo, one voice per robot (HTTP stream, pcm_16000)
                                                   │
               floor token ──> speaking robot plays it (robot_streaming_player.py)
                          └──> the others turn their heads toward it
```

- **One floor.** Only the conductor starts audio. A robot never speaks unless it
  holds the floor, so robots never overlap.
- **Robot speech is never transcribed.** Its text is already known.
- **People get the floor in the gaps.** While a robot speaks, the mics are
  ignored (they hear the robot). After each robot line there is a short
  listening gap (`listen_gap_s`, ~0.7 s). If a voice starts in that gap, the
  people have the floor until they stop (~0.8 s of silence), then STT, then the
  director answers them.
- **The robot that heard the person loudest** is a hint to the director about
  who they were facing.
- **Pipelining.** As soon as line N's text exists, the director writes line N+1
  and its audio is fetched. When line N finishes playing, N+1 starts after the
  listening gap. If a person talks, the prepared line is thrown away.

## Code layout

| File | Owner | What |
|---|---|---|
| `hub/group/robots.py` | robot link | SSH to each robot: player + mic stream; laptop simulation |
| `hub/group/conductor.py` | engine | floor, VAD, STT, director, TTS, transcript |
| `hub/group/api.py` | engine | FastAPI routes + `/ws/group`, mounted by `hub/main.py` |
| `web/group.html`, `web/group.js`, `web/group.css` | page | the group dashboard |
| `web/app.js` / `web/index.html` | page | the "Group conversation" button |

## Contract 1: `hub/group/robots.py`

```python
SAMPLE_RATE = 16000            # robot speaker and mic rate, mono
MIC_BLOCK = 512                # samples per on_mic call (32 ms)

class RobotLink:
    key: str; name: str
    on_mic: Callable[[str, np.ndarray], None] | None   # (key, int16 block), any thread
    connected: bool            # property
    last_error: str

    def __init__(self, key, name, host, user, password, *, listen=True): ...
    async def open(self) -> None        # clear leftovers on the robot, start the
                                        # player (+ mic if listen); RuntimeError(sentence) on failure
    async def close(self) -> None       # stop everything it started on the robot
    async def play(self, pcm: bytes) -> None   # int16 mono 16 kHz, any length, may be
                                        # called many times per line as TTS streams
    async def end_line(self) -> None    # end-of-turn marker after the last chunk
    async def wait_done(self) -> None   # returns when everything sent so far has
                                        # finished playing on the robot
    async def stop_audio(self) -> None  # cut playback now (clear frame)
    async def motion(self, cmd: dict) -> None  # player schema: {"type":"head","direction":
                                        # "left|right|up|down|front"}, {"type":"emotion","name":..},
                                        # {"type":"stop"}

class LaptopLink(RobotLink-compatible):  # simulation, no robot
    # speaker = laptop default output; mic = laptop default input (listen=True)
```

## Contract 2: HTTP + WebSocket (served by `hub/group/api.py`)

`GET /api/group/state` returns the whole state:

```json
{
  "running": false,
  "available": [{"key": "reachy_wireless:...", "name": "reachy2", "state": "CONNECTED"}],
  "seats": [{"key": "...", "name": "reachy2", "included": true, "listen": true,
             "character": "Noa", "persona": "free text", "voice_id": "..."}],
  "voices": [{"voice_id": "...", "name": "Roger - Laid-Back, Casual"}],
  "settings": {"topic": "", "language": "auto", "minutes": 5,
               "listen_gap_s": 0.7, "simulate": false},
  "status": {"phase": "idle", "speaker": null, "elapsed_s": 0, "detail": ""},
  "transcript": [{"id": 1, "t": 12.3, "who": "reachy2", "character": "Noa",
                  "kind": "robot", "text": "...", "move": "challenge",
                  "latency_ms": 640, "cut": false}],
  "error": null
}
```

- `seats` is ordered left to right as the people see the table.
- `phase` is one of `idle | starting | speaking | listening | human | thinking | stopping`.
- `kind` is `robot | human | note`. A `human` line has `who: "people"`.
- `PUT /api/group/config` with `{"seats": [...], "settings": {...}}` saves and
  returns the state (409 while running, except `settings.topic`).
- `POST /api/group/start`, `POST /api/group/stop` return `{"ok": bool, "error"?}`.
- `POST /api/group/nudge` with `{"text": "..."}` steers the next line.
- `WS /ws/group` sends `group.state` (the full object above) on connect and on
  every change, `group.turn` (`{"turn": {...}}`; same `id` = update),
  `group.status` (`{"status": {...}}`), `group.levels` (`{"levels": {"<key>": 0..1}}`,
  ~8/s), and `heartbeat`.

## The hub button

"Group conversation" on the main page, enabled when at least two Reachy
(`reachy_wireless`) cards are connected (CONNECTED, RUNNING or DEGRADED).
It opens `/group.html` in a new tab. Starting a group session stops each
robot's own conversation app first, because both would use the speaker.

## Two modes, one connection (2026-10-21)

The page has two mode buttons and Stop. **The robots stay connected between
conversations**: Stop makes them quiet (heads to the middle) and keeps the SSH
links, players, mics and cameras up, so either mode starts again at once.
Pressing the other mode while one runs is the switch (well under a second).
Disconnect releases the robots; it is needed only to change the seats.

- **Group talk** (`group`): as before, plus people can talk *whenever* they
  like. A voice heard over a robot cuts that robot off (`cut: true`,
  `spoken` = roughly what it got out) and the people get the floor.
- **Interrupt mode** (`interrupt`): a robot dares the person to talk; while
  they talk the robots cut in (oppose, approve, mock, correct, grab the
  floor, now and then one defends the person). `interrupt_level` 0-5
  (0 never: they wait for the end; 5 every time, ~2 s in). At 4-5 a second
  robot sometimes piles on with an interjection. The person's words are
  transcribed in pieces while they talk (`group.people` on the socket, shown
  live on the page). An interruption starts with a cached interjection
  ("Wait, wait, wait!", "רגע, רגע, רגע!" - `hub/group/phrases.py`, voiced once
  per voice into `cache/group_phrases/`) and the written line follows.
  Quiet robots react with gestures while the person talks. Silence for 8 s:
  a robot pokes the person.

### Hearing people over the robots (`hub/group/ears.py`)

Each robot's mic hears the robot that talks. Ears is told what every robot
plays and when; per (mic, speaking robot) it learns the echo level (85th
percentile of mic/played, from ~1 s of that robot's speech). Over a talking
robot a block is a person only if it is a voice AND louder than the predicted
echo by `barge_db` (page: "People cut in": off / careful 14 dB / normal 10 dB /
eager 7 dB). An unlearned pair borrows the loudest learned robot at that mic,
then the map saved from the last session (`cache/group_echo.json`), then a
guess too high to cut anyone. The setup panel shows the echo check: the
loudest a robot's own voice got over its learned echo at each mic. If that is
near the threshold, robots may cut themselves off: choose Careful or Off.

### Body language (`hub/group/moves.py`, `assets/group_moves.json`)

The director picks, in the same call as the line, the speaker's gesture from
the 61 short emotions + 6 dances of Pollen's library (what Gemini picks from
in the single-robot chat) and 0-2 listeners' reactions. Gesturing robots are
left alone by the head-turn keeper for the length of the move.

### Seeing (`RobotLink.snapshot`)

Each robot runs a camera reader over SSH (the daemon's IPC socket, as
reachy_chat's vision.py) that keeps the newest frame, two a second, and sends
one 512x288 JPEG only when asked. When the people ask what a robot sees /
holds / wears (Hebrew or English keywords), the named robot's (else the
nearest mic's) frame goes to the director with the line. The opening line of
group talk also gets a picture of the room. "Cameras" on the page turns it off.

### Voices, and Gemini when OpenAI is out

`voice_provider`: Auto (ElevenLabs while it has 1500+ characters, else OpenAI
gpt-4o-mini-tts, else Gemini), ElevenLabs, OpenAI or Gemini
(gemini-3.8-flash-lite-tts, streamed, first audio ~0.9 s).

On 2026-10-21 the lab OpenAI key ran out of credits in the middle of the
night's testing. Since then, an OpenAI refusal that retrying cannot fix (429
with "credits"/"quota", or 401) switches the session to Gemini for writing
(gemini-3.5-flash-lite, ~0.9 s), hearing (~1.5 s) and voices, with a note in
the transcript. The page shows what is in use ("Voices now", "Writing and
hearing"); "Writer" can also pick Gemini on purpose. Gemini's voice model
allows only a few requests a minute per key, so every Gemini key in the Keys
panel is used in turn (a refused key rests a minute). Slow requests are raced
by a second identical one (voice after 1.8 s with no audio, writer after 2.6 s):
about one OpenAI voice request in eight hung for 10+ s that night.

Gemini's voice models have a small DAILY cap per key and per model (that
night: 100 a day on the lab key, 10 on the free key; the day turns at 10:00
Israel time). The session walks through four voice models and both keys, but
a long morning on Gemini voices can still run dry: top up OpenAI. Gemini voices
are never raced, and interjections are not voiced on Gemini during a session
(`tools/group_warm_phrases.py` does it ahead of time; Noa, Dov and Maya have
theirs, Eli and Tamar fall back to the line alone). OpenAI voices get per-line acting
instructions from the director's `tone`. A voice with no audio in 6 s is
retried once on OpenAI; a stream that stalls 5 s ends the line (the 2026-10-21
dry run had an OpenAI stream stall for 30 s).

### Rehearsing without robots

`tools/group_dryrun.py` runs everything for real except the robots and the
room: fake robots play into a virtual room, fake mics hear them with per-pair
echo plus a scripted virtual person. Silent; prints the transcript and a
summary. `--plan quiet` checks for robots cutting themselves off.

Contract additions: `POST /api/group/start {"mode": ...}`, `POST
/api/group/disconnect`; state has `connected`, `mode`, `people_live`,
`eleven_credits`, `eleven_in_use`, `echo`; phase `ready` = connected, not
talking; socket message `group.people {"text"}`.

## 2026-10-21 morning: OpenRouter, variety, idle life, slow network

- **Writer via OpenRouter** (key "OpenRouter" in the Keys panel): default
  google/gemini-3.5-flash (best Hebrew, ~2.5 s, ~$0.004/line); a slow answer
  is raced by openai/gpt-oss-120b on Cerebras (~1-1.5 s) after 3.5 s
  (Flash-Lite for lines with a camera picture). The gesture menu is now
  grouped names only: the prompt was ~40% smaller and every model faster.
- **Interruptions vary**: ~53 interjections per language + 3 per character
  (`phrases.py`), none reused within 14 interruptions; only half of the
  interruptions use one, the rest open in the robot's own words (told the
  recent openings to avoid). Timing is log-normal around the level's base
  (0.4x-2.6x), 35% wait for the person to take a breath, the lone first blurt
  at levels 4-5 happens about half the time.
- **Idle life** (`Session.keep_heads`): every robot that is not speaking, at
  its own random pace, looks at whoever has the floor, lets go and breathes
  (player "stop"), makes a small listening gesture, or glances away. A long
  line gets a second gesture of the same feeling half way.
- **Slow network** (page switch, on by default): OpenAI voices come as Opus,
  ElevenLabs as 32 kbps MP3, decoded here. On the phone hotspot (~30 KB/s
  down that morning) raw voice audio (OpenRouter, Gemini: 48-64 KB/s) arrives
  slower than it plays: those voices hang there. Compressed voices need
  OpenAI or ElevenLabs credits.

### Stands, openers, robot-on-robot defending (2026-10-21, later)

- Dov is now **Dor** (דור).
- Every robot has a **stand** on what the person argues, for the whole turn:
  Noa backs the person, Dor is against, Maya corrects, Eli mocks, Tamar backs
  the person. The writer interrupts from that stand (it may change it if the
  person really convinces the robot), and the listener gestures, blurts and
  pile-ons follow it too.
- The **writer picks the opener** from the bank (same call as the line), so
  it fits what the robot is about to say, or leaves it empty and opens in the
  robot's own words (about half). Recently used openers are left out of the
  menu. An opener with a recording plays at once; one without is spoken as
  part of the line.
- **Defending is robot against robot**: after a hostile interruption (oppose,
  mock, grab the floor), sometimes (15-25%, by level) a robot on the person's
  side (Tamar first) cuts that robot off mid-line: "Let him finish!". The
  writer never picks "defend" for a first interruption.
## Each robot its own settings; one-screen page (2026-10-21, afternoon)

Tomer: every robot configurable by itself, live, with a button to copy one
robot's settings to the others; voices chosen from the provider picked; the
whole page one screen with no scrolling; the transcript follows the line
being said.

- **Per robot** (`seats[]` in `group.local.json`, `SEAT_LIVE` in conductor.py):
  `character` (the name), `persona`, `voice_provider`
  (`auto | elevenlabs | openai | openrouter | gemini`), the voice for each
  provider (`voice_id` ElevenLabs, `openai_voice` for OpenAI and OpenRouter,
  `gemini_voice`), `writer` (one of `DIRECTOR_MODELS`), `interrupt_level`
  0-5, `gestures` (`lively | calm`), `vision` (camera on/off), `loudness`.
  All of it changes at once, also mid-conversation. Order, `included` and
  `listen` stay fixed while connected (Disconnect to change them).
- The old table-wide `interrupt_level`, `voice_provider`, `director_model`,
  `gestures` and `vision` settings are now only the defaults for a robot that
  has none (an older `group.local.json` is read that way).
- **Voices**: each robot speaks with its own provider. Auto = ElevenLabs while
  it has 1500+ characters, then OpenAI; ElevenLabs refusing moves every
  ElevenLabs/Auto robot to OpenAI. OpenRouter's voice takes only OpenAI's
  realtime voices (no fable/nova/onyx): another one falls back to the robot's
  default. `state` adds `voice_options` (the lists per provider), `providers`
  (which keys the hub has), and per robot `voice_backend` and `brain` (what it
  uses right now) and `default_voices`.
- **Writers**: if every robot has the same writer, the director picks the
  speaker as before. If they differ, the conductor picks the speaker first
  (named by the people, else nearest to them, else mostly the quietest who
  did not just speak) and that robot's writer writes its line.
- **Interrupting per robot**: the pace is the average of the robots that cut
  in at all (all at 3 = the old table-wide 3); who cuts in is weighted by
  level (a level-0 robot never does). Blurts and pile-ons only from robots at
  4-5; a defender's chance and a follow-up's chance come from that robot's
  own level. The style text in the prompt is the speaker's level.
- **Gestures per robot**: the prompt tells lively and calm robots apart; calm
  robots also skip about half their reactions and idle gestures.
- **Page**: conversation on the left, one card per robot on the right (in
  seat order), session settings under the cards. The page never scrolls on a
  laptop screen (1100x620 and up); 4-5 robots get narrow, compact cards.
  "Copy to others" on each card copies chosen settings (by default: level,
  provider, writer, gestures, camera, volume; the voice itself and the
  personality only if ticked) to the robots picked. Keys 0-5 set every
  robot's level at once. The transcript follows the newest line and lights
  the one being said; scrolling up stops that until the bottom is reached,
  Jump is pressed, or 20 s pass.
- `PUT /api/group/config` while a conversation runs takes each robot's own
  settings and the live session settings; it no longer answers 409 for them.

## 2026-10-22: after the 2026-10-21 lab runs

**The people's own mic.** Setting `people_mic` (page: "People's mic", next to
the level bar `mic:people`): `auto` (default) = the first laptop input with
"DJI" in its name, else the robots' mics; `robots` = the robots' mics; any
other value = a laptop input by name. When a laptop mic is used, the robots'
mics are not opened and Ears has the one key `mic:people`; it learns how loud
each robot arrives there (`mic:people|<robot>` in cache/group_echo.json) and
barge-in works on it as on a robot mic. Stereo receivers (DJI with two
transmitters) give the louder channel per block. Changing it reconnects the
robots at the next start (it is part of the session signature).

**ElevenLabs.** The compressed (MP3) voice is decoded while it downloads
(`StreamDecoder`: re-decode the bytes so far every ~1.2 KB, send what is new
minus the last two frames). `ElevenGate` keeps ElevenLabs at 3 requests at
once (Starter plan); the interjection warm-up runs only when no live line is
waiting or running, and only one warm-up runs per session. A busy (429
concurrent / 5xx) answer is retried after 0.3, 0.6, 1.0 s. A line that still
fails is voiced by the next provider, and ElevenLabs stays for the next line;
only `eleven_gone` refusals (401/402/403, quota) move the session off it.

**Log.** Robot lines are written to the jsonl when they have been spoken or
cut (a Stop writes the ones it interrupted), so `latency_ms`, `cut` and
`spoken` are real. New fields: `writer_ms` (the writer call), `voice` (the
provider that voiced it) and `voice_first_ms` (request to first audio).

## 2026-10-22 (later): demo readiness for 2026-10-26

**Voice lock.** A robot whose voice provider is ElevenLabs only ever speaks
with ElevenLabs (`voice_backend` ignores `eleven_down` for it). A line it
cannot get is raced after 2 s (`ELEVEN_HEDGE_S`), asked again up to 3 times
within 15 s, and otherwise skipped (`unspoken`, left out of the writer's
history) -- never voiced by another provider. "Auto" keeps the old fallback.
Every voice menu offers male voices only (`MALE_VOICES_ONLY`).

**Playback never outruns the download.** `Audio.can_start`: with audio
arriving at r seconds per second and `rest` still to come, a line starts once
buffered >= rest * (1/r - 1) * 1.25 + 0.35 s (1 s while r is unknown, at once
when r >= 1.4 or the clip is complete). Logged per line: `buffer_ms` (waited
before the first sound), `gaps` / `gap_ms` (the robot ran dry anyway).

**The people's mic.** `hub/laptop_mic.py`: the hub watches the laptop's mics
every 3 s (restarting PortAudio only while no stream is open, so a mic
plugged in later is seen). The group conversation opens the DJI if one is
there; the robots' mics run on the robots in standby (the Python recorder,
switched by a byte on its stdin, sends nothing) and `Ears.set_active`
chooses which are heard. Page button / `POST /api/group/mic {"use":
"robots"|"people"}` switches at once mid-conversation. `guard_people_mic`
switches by itself when the DJI stops sending for 1.5 s (unplugged) or sends
only digital zeros for 6 s (transmitter off / flat battery / out of range).
The DJI does not report its battery over USB, so the signal is what is shown.
reachy_chat: `mic_mode = "auto"` launches it in laptop mode with
`--mic-match <the DJI's name>` when the DJI is plugged in, else on the robot.

**Warm before Start.** At hub start (main() only, never in tests) and on
**Get ready** (`POST /api/group/ready`): every service is checked with one
real, tiny request -- each writer the robots use plus the racers, hearing
(speech to text), each robot's ElevenLabs voice ("Ready."), voice detection
-- shown as chips on the page. One `Services` lives as long as the hub
(`shared_services`), its connections kept 120 s and touched every 30 s
(`keepalive`): before this httpx closed a connection idle for 5 s, so most
lines paid a new TLS handshake over the hotspot. Get ready also connects the
robots, writes and voices the first line of both modes (`premake`; again
after every Stop and settings change) and records the interjections for the
robots' voices (first time only; kept on disk). Start then speaks at once.
STT is told the fixed language ("en") instead of "Hebrew or English".
