# Pepper operator dashboard (`pepper_app`)

The hub's **Launch** on the Pepper card starts this and opens
http://127.0.0.1:8780/. It is for the person running the session, not for the
visitors: they only see what is on **Pepper's chest screen**.

## What it does

| Card | What it is |
|---|---|
| **Robot / Screen pills** (header) | Pepper itself, and its chest tablet. The tablet is a second device on the hotspot; it is green only while it really calls in (every 0.5 s). If it stops, the dashboard re-opens the page on it, or press **Reload**. |
| **Conversation** | Pick an experience, the engine, language and voice, then **Start conversation**: Pepper speaks first. **Vision**: the model gets a camera frame when the person answers. **AI drives screen**: the model shows choices, messages and slides itself. **Gestures**: arm movement while it talks. While it runs, a turn row shows **Waiting for an answer** with a timer, plus **Repeat question** and **Skip**. |
| **Wizard of Oz · Say** | One click on a quick phrase, or type English/Hebrew. **AI voice** = the conversation's voice (needs internet; the quick phrases are cached on disk, so they still play offline). **Pepper's** = the robot's own voice, English only, no internet needed; English falls back to it on its own when OpenAI does not answer. *pause AI*: the AI stops until **Resume AI**. *tell AI*: the AI is told what Pepper said. |
| **Wizard of Oz · Move** | Only movements that ran on this Pepper on 2026-10-06, with the exact values that ran: Wave (Hey_1), Nod yes, Shake no, Both arms up, Arms wide, Right / Left arm up, Open/close hands, head Left / Center / Right, Stand (StandInit), face tracking on/off. Arm moves hold for a second, then go back to StandInit. **Walking** (light purple): 1 m forward, turn 180 degrees, 1 m forward, turn 180 degrees, slowly; refused while charging (unplug, close the flap); Pepper stops by itself 0.40 m from obstacles, so keep about 1.5 m clear; Stop ends it. Explain and Cheer were removed (2026-10-12). No Rest, no other stock animations. |
| **Live conversation / Event log** | Who said what (Pepper, person, you, screen taps), and everything that happened. Speech that was heard but not taken as an answer (noise, "hmm", or said while Pepper was talking) shows as **Heard, not used**, with an **Accept** button. **Copy logs** for a bug report. |
| **Pepper's camera** | What the head camera sees (320×240, 2 fps), with face boxes. |
| **On Pepper's screen** | The same drawing the tablet shows. Click an option to tap it for someone who points instead. **Emoji test** puts all 45 candidate emoji on the tablet, numbered; **Mark broken** takes the numbers that show as empty boxes. Below: presentations. Upload or drop images or a PDF (each page becomes a slide; PowerPoint: save as PDF first). |

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

## How it is built

```
laptop (hub venv, Python 3)                         Pepper (Python 2.7, NAOqi 2.5)
pepper_app  :8780  dashboard + /screen  <-- tablet polls /screen/state, posts taps
            :8782  <=============== one TCP link ===== agent/pepper_agent.py
                   commands, speech audio ->            (uploaded + started over SSH
                   <- mic audio, camera, status          at every Launch)
            wss -> OpenAI gpt-realtime-2.1
            wss -> ElevenLabs Scribe v2 Realtime + Eleven v4 Turbo (engine B)
```

* The agent **connects out** to the laptop: the direction Pepper's head and
  tablet already reached the laptop on 2026-10-06. Pepper must be able to
  reach the laptop on ports **8780** (tablet) and **8782** (agent): the first
  Launch shows a **Windows Firewall** prompt for the hub's Python. Allow it on
  private networks.
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
* Settings, presentations and cached speech live in `pepper_app/data/` (git-ignored).

## Run it without the hub

```powershell
cd $HOME\Desktop\job\robot-hub
$env:OPENAI_API_KEY = "<key>"
$env:ELEVENLABS_API_KEY = "<key>"     # for the ElevenLabs engine (the hub passes both)
.venv\Scripts\python.exe -m pepper_app 172.20.10.2         # Pepper's IP
.venv\Scripts\python.exe -m pepper_app --robot ""          # no robot: the page only (Pepper does the talking and listening)
```

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
