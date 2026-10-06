# Robot Hub

One local page for the lab's four robots — **Furhat, Reachy-Mini,
Reachy-Mini-Lite, NAOqi**.

A card is dim when its robot is absent and lights up within seconds of that
robot appearing. **Connect** attaches to it and the robot *says a sentence out
loud* — voice proof the link is real, not just a green dot. **Launch** opens
that robot's own existing system in a new tab.

Any number of robots run at once, in any order, without interfering. A robot
you do not own is a dim card and costs you nothing.

```
┌─ Reachy-Mini ────────────┐
│ [Disconnect]  [Connect]  │
│                          │
│         (photo)          │
│                          │
│ ● Reachy-Mini            │
│ ready, control loop 49 Hz│
│ 172.20.10.10             │
│      [  Launch  ]        │
└──────────────────────────┘
```

## Set up on your own laptop

For lab members. Windows and macOS. About 15 minutes, most of it downloads.

### 1. Install once

- **Git**: <https://git-scm.com/downloads>. On a Mac, `git` installs on first use.
- **Python 3.11 or newer**: <https://www.python.org/downloads/>.
  - Windows: tick *Add python.exe to PATH* during install.
  - Mac: the built-in `python3` is too old. Install it from python.org or with `brew install python@3.12`.

### 2. Get the hub

Put everything in one folder, side by side.

Windows (PowerShell):

```powershell
mkdir $HOME\robot-lab; cd $HOME\robot-lab
git clone https://github.com/labbgulab-lab/robot-hub.git
cd robot-hub
.\run.ps1
```

If Windows says running scripts is disabled, use
`powershell -ExecutionPolicy Bypass -File .\run.ps1` instead.

macOS (Terminal):

```bash
mkdir -p ~/robot-lab && cd ~/robot-lab
git clone https://github.com/labbgulab-lab/robot-hub.git
cd robot-hub
./run.sh
```

The first run builds its own Python environment (a minute or two). Then the
hub opens at <http://127.0.0.1:8099/>. Start it the same way every time;
stop it with Ctrl+C. Get updates with `git pull` inside `robot-hub`.

### 3. Your phone's hotspot

Every robot joins **your phone's hotspot**, and your laptop joins it too. The
**Network setup** panel at the top of the hub page checks this for you. It
opens by itself the first time and whenever something is wrong.

- **2.4 GHz is required.** The robots can't see a 5 GHz hotspot.
  - iPhone: *Maximize Compatibility* on.
  - Android: AP band 2.4 GHz.
- **Name the hotspot simply**: letters, digits and spaces only. An iPhone's
  default "Name’s iPhone" has a curly apostrophe the Reachy app can't read.
- **Each robot learns your hotspot once**, then rejoins it by itself. The panel
  has the steps for Reachy Mini, NAO, Furhat and Pepper. Robots remember a
  network by name *and* password, so lab members who use the same hotspot
  name and password share every robot's memory.
- Turn the hotspot on **before** powering a robot.

### 4. Speaking keys

Open **Speaking keys** on the page and add the API keys you were given
(Gemini / GPT / ElevenLabs). They stay on your laptop. A robot gets one only
while it runs. For Furhat, also put its Studio password in a file called
`.env` inside `robot-hub` (copy `.env.example`): `FURHAT_PASSWORD=...`.

### 5. Each robot's own system

The hub launches each robot's own program. Clone the ones you need **next to
`robot-hub`**, in the same `robot-lab` folder; the hub looks there by default.

- **Furhat**: nothing to install.
  1. In **Robot files**, choose Furhat.
  2. Download `OpenAIChat_1.3.0.skill` *with* your GPT key.
  3. Import it in Furhat Studio.
- **Reachy Mini**: needs `reachy_chat` (ask Tomer for access):

  ```bash
  git clone -b multi-provider https://github.com/Tomer232/reachy-mini-conversation-app-bgu-lab.git reachy_chat
  cd reachy_chat
  python -m venv .venv
  # Windows: .venv\Scripts\python -m pip install -r requirements.txt
  # Mac:     .venv/bin/python -m pip install -r requirements.txt
  ```

  The first Launch on a robot installs it onto the robot (a few minutes).
- **NAO** (Windows recommended): needs `NAO_LLM`. Follow its
  [Quick Start](https://github.com/Tomer232/antagonistic-robot#quick-start):

  ```bash
  git clone https://github.com/Tomer232/antagonistic-robot.git NAO_LLM
  ```

  The NAO card also needs Python 2.7 and the pynaoqi 2.8.6 SDK. Set both paths in
  `config.toml` (copy `config.example.toml`); see `docs/SETUP.md`.

### 6. Something wrong?

Run `.\run.ps1 -Doctor` (Mac: `./run.sh --doctor`). It checks everything and
prints the fix for each problem. A card that stays dim is almost always the
network: press **Check again** in Network setup, then **Scan now**.

## What it does and does not do

The hub **supervises**; it never reimplements. Each robot's own system stays
in its own folder and is launched unchanged — the hub only finds the robot,
proves the link works, arbitrates the resources the systems fight over, and
opens the right tab.

It arbitrates two things that have actually broken demos:

- **Microphones.** `NAO_LLM` opens the Windows *default* input device without
  naming it, which may be the same K11 that Reachy is listening through. The
  symptom is indistinguishable from a broken microphone. The hub resolves every
  audio claim to a concrete device name and refuses the second claim, naming
  the holder — with an override if you want it anyway.
- **Ports.** Anything the hub starts gets an allocated port from 9100–9199,
  bind-tested, avoiding the ranges the Reachy desktop app and `reachy_chat`
  reserve.

It also watches **its own network**. When this laptop silently roams off the
robots' hotspot, every robot goes unreachable at once and it reads exactly like
four hung robots. The hub says so in a banner instead.

## Robot files

The **Robot files** panel shares skills, apps and configs with the lab. Pick a
robot in the dropdown to see its files, then upload or download. The files are
assets of the `robot-files` release on this repo (too big for git: a Furhat
skill is 85 MB). Every hub whose GitHub sign-in can see the repo sees the same
list. Sign-in comes from `GITHUB_TOKEN` in `.env`, or else from `gh auth login`.

**No key ever goes up.** On upload the hub removes the secret values it finds in
an archive's `.properties` / `.env` files (for example the `apiKey` a Furhat
skill build writes in). It refuses the upload if anything key-shaped is left,
or if any of this laptop's own keys appears anywhere in the file. A file whose
key was removed shows "needs a GPT key". Download it **with** one of your
Speaking keys to get a working copy. That copy has your key in it, so don't
pass it on; share through the panel instead.

## Layout

```
hub/
  main.py        FastAPI: static page, REST, one WebSocket
  core.py        the orchestrator and the card state machine
  discovery/     three detectors for four robots
  adapters/      one file per robot; base.py is the contract
  resources.py   audio + exclusive-resource arbitration
  ports.py       bind-tested port allocator
  supervisor.py  child processes: start, stop, verify-zero
  doctor.py      environment preflight
  library.py     Robot files: the shared GitHub-release library
  wifi.py        Network setup: which WiFi, which band, is it a hotspot
  keyscrub.py    keeps keys out of it (remove on upload, refill on download)
web/             index.html + app.js + style.css, no build step
docs/            SETUP.md, ADAPTERS.md, and the measured robot profiles
tools/           hardware probes used to write the profiles
```

`PLAN.md` is the build plan. Its §2 is *measured* hardware behaviour — every
line was observed on real robots, and several overturned a confident guess.
Read it before changing anything about health, discovery, or identity.

## Adding a fifth robot

Implement `RobotAdapter` in `hub/adapters/`, add a detector if it needs one,
and register it. `docs/ADAPTERS.md` walks through it.

## Requirements

Python 3.11+ for the hub itself. Per robot, only if you own it:

| Robot | Needs |
|---|---|
| Reachy-Mini-Lite | Reachy Mini Control desktop app, daemon ≥ 1.10.0 (Windows) |
| Reachy-Mini | `reachy_chat` checkout and its venv; daemon ≥ 1.10.0 |
| Furhat | nothing local; optionally a Realtime API key |
| NAOqi | Python 2.7 + pynaoqi SDK 2.8.6, and `NAO_LLM` with its venv |
