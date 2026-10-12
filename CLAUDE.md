# Robot Hub: notes for Claude

## "Open the hub" / "start the hub" / "launch the robots"

Lab members usually ask you to open the hub for them. Do it like this. They do
not need PowerShell, and they do not need to do anything first.

1. If the hub is already running, there is nothing to start: check
   `http://127.0.0.1:8099/` (the port is `port` in config.toml if set). If it
   answers, go straight to step 3.
2. Otherwise run `tools\start-hub.ps1` from this folder **in the background**.
   It keeps running, and stopping it stops the hub. It:
   - pulls the latest code (this repo, plus `..\reachy_chat` and `..\NAO_LLM`
     if they are there);
   - installs Python packages only when requirements.txt changed;
   - makes a "Robot Hub" desktop shortcut the first time;
   - starts the hub and opens the browser.

   From PowerShell:
   `powershell -NoProfile -ExecutionPolicy Bypass -File tools\start-hub.ps1`.
   Wait until `http://127.0.0.1:8099/` answers. That takes a few seconds, or
   about a minute on the very first run.
3. Answer the person with the link and one line, for example:
   **Robot Hub is open: [http://127.0.0.1:8099/](http://127.0.0.1:8099/)**.
   Click a robot's card, then Connect, then Launch.

Do not ask the person to run commands. The double-click alternative for them is
`Start Robot Hub.cmd` in this folder, or the "Robot Hub" shortcut on the desktop.

## Facts that save time

- The robots are reached over a phone hotspot that all of them have saved. If no
  robot cards appear, check that this laptop is on that same hotspot.
- API keys live in the hub's Keys panel (`keys.local.json`, per laptop, never in
  git; the repo is public). Pepper's demo needs a GPT key and an ElevenLabs key.
- Pepper's Launch opens `pepper_app` (its own dashboard, port 8780). Its default
  is the scripted demo "Feelings Together (demo)" in Hebrew; see
  `pepper_app/README.md`.
- Environment check: `.\run.ps1 -Doctor`. Tests: `.venv\Scripts\python.exe -m pytest tests -q`.
