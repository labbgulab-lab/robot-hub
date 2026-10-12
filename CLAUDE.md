# Robot Hub: notes for Claude

## "Open the hub" / "start the hub" / "launch the robots"

**The hub must run on its own, not inside your session.** A hub you start from
your shell is a child of this Claude process. When the person closes Claude,
the hub stops, and every robot with it, maybe in the middle of a demo (lab
rule, 2026-10-12). So:

1. **Check first.** If the hub is already running, there is nothing to start:
   check `http://127.0.0.1:8099/` (the port is `port` in config.toml if set).
   If it answers, go straight to step 3.
2. **Give the person the command; they run it in their own CMD or PowerShell
   window. Do not run it yourself.**
   - CMD, in the setup layout:
     `"%USERPROFILE%\robot-lab\robot-hub\Start Robot Hub.cmd"`. Elsewhere,
     use the path of `Start Robot Hub.cmd` in this folder.
   - PowerShell: `& "$HOME\robot-lab\robot-hub\Start Robot Hub.cmd"`.
   - Or double-click the "Robot Hub" shortcut on the desktop.

   The command:
   - pulls the latest code: this repo, plus `..\reachy_chat` and `..\NAO_LLM`;
   - installs packages, but only when requirements.txt changed;
   - makes the desktop shortcut the first time;
   - starts the hub and opens the browser.

   Its window must stay open; it can be minimised. Closing that window stops
   the hub.
3. **Give the link.** Once `http://127.0.0.1:8099/` answers, reply with the
   link and one line, for example:
   **Robot Hub is open: [http://127.0.0.1:8099/](http://127.0.0.1:8099/)**.
   Click a robot's card, then Connect, then Launch.

After that, your job is to help check that everything works. Read
`logs/hub-<date>.log`, the hub page, and the robots' own dashboards.

## Facts that save time

- **The hotspot:** all the robots are on a phone hotspot that they have saved.
  If no robot cards appear, check that this laptop is on that same hotspot.
- **Keys:** they live in the hub's Keys panel (`keys.local.json`). They are per
  laptop and never in git, because the repo is public. Pepper's demo needs a
  GPT key and an ElevenLabs key.
- **Pepper:** its Launch opens `pepper_app`, its own dashboard on port 8780.
  The default is the scripted demo "Feelings Together (demo)" in Hebrew; see
  `pepper_app/README.md`.
- **Checks:** environment `.\run.ps1 -Doctor`; tests
  `.venv\Scripts\python.exe -m pytest tests -q`.
