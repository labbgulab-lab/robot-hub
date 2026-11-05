# Next session: start here

**Updated 2026-11-05, end of day: the student app is released.** v1.0.0 is published, both main branches carry it, and lab laptops get it on their next start. What's left needs the robots or another laptop.

## Where things are

| Repo | Branch | Last commit | State |
|---|---|---|---|
| robot-hub (this repo) | `master` = `student-app` | `ffddedd` HOT-WiFi has internet: fix the staff guide, README and comments | Pushed. `master` was fast-forwarded to `student-app` on 2026-11-05 |
| reachy_chat (`../reachy-mini/reachy_chat`) | `main` = `multi-provider` | `10c4be2` Typed Wizard of Oz lines, live captions, deploy without the heavy deps | Pushed. `main` was fast-forwarded to `multi-provider` on 2026-11-05 |

- **Release:** [v1.0.0](https://github.com/labbgulab-lab/robot-hub/releases/tag/v1.0.0), marked latest. It was built from `9db7123`, and its assets are `RobotHub-1.0.0.zip` (113.6 MB, sha256 `f04918bf…a23637`) and `install.ps1`. Later commits only change docs and comments, so no rebuild is needed.
- **Tests:** `.venv\Scripts\python.exe -m pytest tests -q` gives **532 passing**.
- **Not run on a real robot yet.** Everything was verified with fakes, local servers, headless screenshots and real installs on this laptop.
- **Lab laptops** run `tools/start-hub.ps1`, which runs `git pull` on robot-hub and reachy_chat. So their next start runs the new app against the real robots.
- `docs/CRAB-SWAP-PLAN.md` is untracked on purpose, to keep it out of this public repo. Never commit it.

## What was done on 2026-11-05

1. **Phase 3, verification.**
   - A parity sweep and a demo-screenshot check found 57 issues. Each was fixed and then checked by a separate verifier (`7175116`).
   - The verifiers' second round found more problems, also fixed:
     - a null-seat crash in the group transcript;
     - a "Disconnected" pill shown in the Stopped and Starting states;
     - the Pepper rehearsal simulator left running. It is now killed with pepper_app through a Windows Job Object.
2. **Pepper state hints** from the PepperStates board (`9db7123`):
   - the key line under the badges;
   - "Moves, volume and camera wait for the robot";
   - an amber note when Walking is refused while charging.
3. **Guides:** `docs/guides/STUDENT.md` and `docs/guides/LAB-STAFF.md`, linked from the README.
4. **Release build and install tests:**
   - On this laptop: install from the zip, the `--check` self-test, a tray start that listens on 127.0.0.1:8099 only, Quit with no processes left, reinstall (keeps `app.old` and the data), and uninstall with and without `-RemoveData`.
   - After publishing: the one-line install from GitHub end to end (download 114 MB, then the self-test). The in-app update check sees v1.0.0.
5. **HOT-WiFi has internet.** Every "no internet" claim in the guides, the README and the comments is fixed (`ffddedd`).
6. **Handover:**
   - The Hebrew docs in `job/handoff` are rewritten for the student app (`04_Robots/01_Robot_Hub.md` and a new `06_Student_guides/Robot_Hub_app.md`), and the book is rebuilt.
   - The handover board has U28 (release, done), U29 (first run on robots) and U30 (clean-laptop install).

## Next steps, in order

1. **Lab day, robots needed (board U29).** This is the first real-robot run of the new app:
   - **Pepper:** the outbound link on 8790, the tablet page from the robot on 8791, and the chip must never say "fallback". Also Rehearse, and the charging refusal note.
   - **Reachy:** Talk through the proxy, Wizard of Oz Say (prepare/say), live captions, and group talk. Check that the group time limits added on 3.11 stop a hang.
   - **Every robot:** the in-use marker and **Take over**, Add WiFi with the Knows list, and NAO/Pepper charging.
   - **NAO:** postures, plus the NAO kit download and verify on a clean laptop.
   - **Furhat:** the password from Settings, and the skill rebuild without a baked-in key. The password is in Bitwarden.
   - **reachy0** cannot use the installed app: its mic cable is broken, and the app listens through the robot's mic only. Use a lab checkout with the laptop mic until the cable arrives.
   - Only reachy6-8 are recorded as knowing HOT-WiFi. Check the others.
2. **Clean-laptop test (board U30).** Run the one-line install on a laptop that never had the lab setup, as a **standard (non-admin) user**: install, add a key, connect a robot, Quit, uninstall. This laptop can't do it: Windows Home has no Sandbox, and making a test user needs admin.
3. **Fix what the lab day finds**, then release `v1.0.1`:
   - bump `VERSION`, build with `tools\build_release.ps1` from a commit;
   - test it in a temp root (`docs/guides/LAB-STAFF.md`, "Build a release");
   - publish it marked latest, with the full commit SHA as the target (`gh release create` rejects a short SHA).
   - The permission check may block `gh release create` for Claude. If it does, the user runs it.
4. **After 2026-11-11** the lab's interim owner takes over: hand over whatever is left of steps 1-3, with this file and the board.

## Known gaps (from the builders)

- The New Reachy bring-up row only explains `tools\reachy_bringup.py`; there's no button yet.
- "Windows blocks Pepper" appears only when a start error mentions the firewall or port 8782; it should be rare now.
- The first Talk on a factory Reachy guesses "Installing the Reachy app" after 45 s of starting; the hub doesn't report it.
- Log filters per robot match robot names in the text, because log lines carry no robot field.
- Talk gesture tags come from reachy_chat's log lines, so there are no tags after a reload.
- Group live captions type each line at about 15 characters a second, because the hub sends lines whole.
- reachy_chat's own log is not copied into the transcripts folder after a Talk.
- Typed Wizard of Oz lines need a Gemini key on the robot (Gemini text-to-speech), otherwise the code is `NO_KEY`.
- **Check for updates** doesn't force a new check: right after a release, a running app shows "Up to date" for up to 6 hours, or until it restarts.

## Read these for background

1. `docs/guides/STUDENT.md` and `docs/guides/LAB-STAFF.md`: how the app is used and released.
2. `docs/BUILD-PLAN.md`: decisions, the no-admin/no-firewall rule, the install layout and the API contract.
3. `docs/STUDENT-APP-PLAN.md`: the what and why. Decision S19 is full parity.
4. `docs/parity/*.md` and `docs/design/`: the parity checklists and the design boards and renders.

## Rules that stay

- Students are not admin: nothing may listen on anything but 127.0.0.1, and nothing may need UAC.
- Public repo: no secrets, no personal names, no absolute user paths. Never print key files.
- Commit when asked. Push and release only with the lab engineer's OK.
- Push with `GH_TOKEN=$(gh auth token --user labbgulab-lab)`; the active gh account is a personal one.
