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

## Quickstart

```powershell
git clone <this repo> && cd robot-hub
cp config.example.toml config.toml     # edit the paths for your machine
cp .env.example .env                   # your keys; never committed
.\run.ps1
```

Linux/macOS: `./run.sh`. The page opens at <http://127.0.0.1:8099/>.

Not sure your machine is set up? `.\run.ps1 -Doctor` (or
`python -m hub.doctor`) checks every prerequisite and prints the exact remedy
for each one it cannot find. The same report is in the UI at `/api/doctor`.

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
