# Pepper operator dashboard (`pepper_app`)

The hub's **Launch** on the Pepper card starts this and opens
http://127.0.0.1:8780/. It is for the person running the session, not for the
visitors: they only see what is on **Pepper's chest screen**.

## What it does

| Card | What it is |
|---|---|
| **Top bar** | The **robot** chip (address, battery, charging) and the **tablet** chip: the tablet is a second device on the WiFi; it is green only while it really calls in (every 0.5 s). If it stops, the dashboard re-opens the page on it, or press **Reload**. Volume, the **GPT** and **ElevenLabs** key badges (the keys picked on the hub's Pepper card; a new pick applies at the next Launch), **More**, **Logs** and **Stop everything**. |
| **Conversation** | Pick an experience, the engine, language and voice, then **Start conversation**: Pepper speaks first. **Vision**: the model gets a camera frame when the person answers. **AI drives screen**: the model shows choices, messages and slides itself. **Gestures**: arm movement while it talks. **Web search** (free conversation only): Pepper can look things up online. A toggle the chosen experience ignores is greyed, with the reason. While a conversation runs, Experience, Engine, Language and Voice apply at the next Start. A turn row shows **Waiting for an answer** with a timer, plus **Repeat question** and **Skip**. The label at the top right is the model that answers now. |
| **Wizard of Oz · Say** | One click on a quick phrase, or type English/Hebrew. Pepper speaks in the conversation's voice (needs internet; the quick phrases are cached on disk, so they still play offline). English falls back to Pepper's own voice when OpenAI does not answer. *pause AI*: the AI stops until **Resume AI**. *tell AI*: the AI is told what Pepper said. **Pause AI** pauses it without saying anything. |
| **Wizard of Oz · Move** | Only movements that ran on this Pepper on 2026-10-06, with the exact values that ran: Wave (Hey_1), Nod yes, Shake no, Both arms up, Arms wide, Right / Left arm up, Open/close hands, head Left / Center / Right, Stand (StandInit), face tracking (the switch shows what the robot is really doing). Arm moves hold for a second, then go back to StandInit. **Walking**: 1 m forward, turn 180 degrees, 1 m forward, turn 180 degrees, slowly; refused while charging (unplug, close the flap); Pepper stops by itself 0.40 m from obstacles, so keep about 1.5 m clear; Stop motion ends it. Explain and Cheer were removed (2026-10-12). No Rest, no other stock animations. |
| **Live conversation / Event log** | Who said what (Pepper, person, you, screen taps, web searches), and everything that happened. Speech that was heard but not taken as an answer (noise, "hmm", or said while Pepper was talking) shows as **Heard, not used**, with an **Accept** button. **Copy logs** for a bug report. |
| **Pepper's camera** | What the head camera sees (320×240), with face boxes; Top/Bottom camera; Save. |
| **On Pepper's screen** | The same drawing the tablet shows. Click an option to tap it for someone who points instead. Below: presentations. Upload or drop images or a PDF (each page becomes a slide; PowerPoint: save as PDF first). Uploaded slides are also the AI's pictures for choices. |
| **More** | **Tablet emoji check** (the 45 candidate emoji on the tablet, numbered; type the ones that show as empty boxes), **Put a message or choice on the screen**, **Lab facts** (what Pepper may say about the lab: `lab_facts.md`), **Rehearse without the robot** (`python -m pepper_app.sim`). |

## Experiences, engines, turns

**Experiences** (three, since 2026-10-12):

* **Feelings Together (demo) · scripted**, the default and the one for demos.
  Every question, screen and reaction is written in `script.py` (Hebrew and
  English); the screen changes as Pepper starts each question; the code decides
  which option was meant (tap, number, ordinal, Hebrew sound-alike) and, when it
  cannot tell, Pepper asks for a tap instead of guessing. The AI only re-words
  the written reaction. 9 steps: welcome, how to answer, is my voice
  comfortable, happy face, surprised face, Dana's tower, look at the screen,
  feedback, bye.
* **Feelings Together (research demo) · with emoji**: the same idea led by the
  AI (it chooses the wording and the screens). Kept as a fallback. A demo of a
  protocol the lab *could* study, inspired by robot-assisted autism research
  (Kouroupa 2022 meta-analysis; DREAM; Scassellati 2018), framed as a demo,
  never as therapy, a test or a diagnosis.
* **Free conversation**.

**Engines.** Both use gpt-realtime-2.1 to decide what Pepper says.

| | GPT Realtime | ElevenLabs ears + voice |
|---|---|---|
| Hears | GPT's built-in transcription | **Scribe v2 Realtime**: Hebrew or English, detected per sentence |
| Speaks | GPT voice (marin...) | **Eleven v4 Turbo**, voice picked from the lab account |
| Answer to first sound (measured 2026-10-07, synthetic speech) | about 1.5 to 3 s | about 1.8 s after Scribe closes the sentence (+0.9 s of silence it waits for) |

Wizard of Oz speaks in the engine's voice. If the ElevenLabs voice fails mid-
conversation, that line is spoken with the OpenAI voice instead.

**Strict turns.** The model never takes the turn by itself:
* Pepper speaks, and when its audio has finished playing it **waits**.
* Only a tap, or speech that is a real answer, starts Pepper's next turn. Empty
  speech, "hmm" or "אה" does not, and neither does speech during Pepper's turn.
* A question with no answer for 12 s is asked again **once**. After that Pepper
  waits for as long as it takes, or until the operator presses **Skip**.
* The mic is shut except while Pepper is waiting for an answer.

**Emoji.** The tablet is an old Android, so only the oldest emoji (Unicode
6.0/6.1, the 45 on the test card) are candidates. The AI may use only the
ones not marked broken, and only in a choice's or message's emoji field; the
server removes any other. The day before a demo: **Emoji test** on the robot,
take a photo, **Mark broken**.

## Web search (free conversation, 2026-11-05)

With **Web search** on, the free conversation's Realtime session gets one
tool, `web_search(query)`. The laptop runs it through the OpenAI Responses API
with its built-in web search (`gpt-4.1-mini`, the same GPT key) and hands a
2-3 sentence answer back to the model, which says it. While it searches,
Pepper says a pre-made "Let me check…" in the conversation's voice, the badge
reads SEARCHING, the "AI stopped answering" alarm waits, and the chat gets a
pill `Searched the web: "<query>" · 2.8 s`. After 8 s Pepper answers without
it and says so. Questions about the lab still come only from `lab_facts.md`.
Not in the scripted demo: it is a closed flow and never makes things up.

## How it is built

```
laptop (Python 3, 127.0.0.1 only)                     Pepper (Python 2.7, NAOqi 2.5)
pepper_app  127.0.0.1:8780  dashboard
            ================ one TCP link ==========>  agent/pepper_agent.py  :8790
            commands, speech audio, screen state ->     (uploaded + started over SSH
            <- mic audio, camera, status,               at every Launch)
               tablet heartbeat, taps, slide requests
                                                       tablet page           :8791
                                       chest tablet -> http://198.18.0.1:8791/screen
            wss -> OpenAI gpt-realtime-2.1
            wss -> ElevenLabs Scribe v2 Realtime + Eleven v4 Turbo (engine B)
```

* **The laptop connects out** to the agent on Pepper (robot port 8790, token
  checked, one laptop at a time), and **the agent serves the chest tablet's
  page** (robot port 8791). Nothing on the laptop listens on the network, so
  Windows never asks a student about the firewall (students are not admins).
  The tablet's state, taps, heartbeat and slide files travel over the one link;
  slides are cached on the robot (`/home/nao/.pepper_app/media`).
* **Fallback**: if the laptop cannot reach port 8790 within 15 s, the agent is
  restarted to connect back to the laptop on port 8782 (the way before
  2026-11-05). The robot chip says "fallback: Pepper connects back; Windows may
  ask about the firewall".
* Speech goes to Pepper as audio (24 kHz), so Hebrew works even though Pepper
  has no Hebrew voice. The agent plays it with `ALAudioDevice.sendRemoteBufferToOutput`,
  or with `aplay` if NAOqi will not take a buffer from Python. The log says which.
* Audio is **always Pepper's own mic and speaker**; there is no laptop audio route.
* The microphone is half-duplex: shut while Pepper speaks, so the model never
  answers itself. There is no barge-in.
* While a conversation runs, the vendor app's dialog topics are paused, so its
  own chatbot does not answer people too. They are restored at the end, and
  by the agent itself if the laptop disappears for 45 s. The agent then also
  hides the page on the tablet and exits.
* The page needs no internet: no CDN, and pdf.js is bundled in `static/vendor/`
  (pdfjs-dist 3.11.174).
* Settings, presentations and cached speech live in `pepper_app/data/`
  (git-ignored), or in `<ROBOT_HUB_DATA>/pepper` for the student app.

## Run it without the hub

```powershell
cd $HOME\Desktop\job\robot-hub
$env:OPENAI_API_KEY = "<key>"
$env:ELEVENLABS_API_KEY = "<key>"     # for the ElevenLabs engine (the hub passes both)
.venv\Scripts\python.exe -m pepper_app 172.20.10.2         # Pepper's IP
.venv\Scripts\python.exe -m pepper_app --robot ""          # no robot: the page only (Pepper does the talking and listening)
.venv\Scripts\python.exe -m pepper_app.sim                  # rehearse without the robot (a stand-in agent on 127.0.0.1)
```

## Status (2026-11-05)

* The laptop-connects-out link, the tablet page served from Pepper and web
  search are tested **without the robot** only:
  * `tests/test_pepper_link.py`: both link directions and the fallback with fake
    agents, and the real agent run under Python 2.7 with a fake `naoqi`
    (listen mode, token check, the tablet page, taps, slide files and their cache);
  * `tests/test_pepper_websearch.py`: the search against a fake Responses
    endpoint, the session's tool, the flow while it searches, the toggle's rules.
* **First run on Pepper, check:** the tablet opens `http://198.18.0.1:8791/screen`
  (the head's address on Pepper's internal network), slides show on it, and
  the robot chip never says "fallback".

## Status (2026-10-07)

* Tested **without** the robot:
  * the link protocol (fake agent over a real socket);
  * the screen, taps and emoji rules;
  * presentations;
  * the laptop-only guard;
  * the turn manager (`tests/test_pepper_app.py`).
* Live, against the real services, with synthetic speech in place of a visitor:
  * **ElevenLabs engine:** Scribe heard a Hebrew answer exactly; noise was ignored;
    Pepper answered in Hebrew with the ElevenLabs voice.
  * **GPT Realtime engine:** the same flow. Pepper follows the Feelings Together
    script and waits after each question.
* **Not yet run on Pepper.** The agent compiles under Python 2.7 and its PNG and
  audio code were checked there, but every NAOqi call in it is untested on this
  robot except the ones `profiles/pepper.md` lists. First lab session: see
  `NEXT-SESSION.md`.
