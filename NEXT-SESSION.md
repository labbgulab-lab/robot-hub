# Next session: start here

**Updated 2026-11-05, end of build phase 2.** We are building the downloadable **student app**: one-line install, keys popup, the new hub page, reachy_app and the Pepper dashboard, all to the design canvas, with full parity with today's tools.

## Where things are

| Repo | Branch | Last commit | Pushed? |
|---|---|---|---|
| robot-hub (this repo) | `student-app` | `7e7b97f` Student app: backend, hub page, reachy_app, Pepper, installer | **No**, local only |
| reachy_chat (`../reachy-mini/reachy_chat`) | `multi-provider` | `10c4be2` Typed Wizard of Oz lines, live captions, deploy without the heavy deps | **No**, local only |

- Tests: `.venv\Scripts\python.exe -m pytest tests -q`, with **521 passing** at the end of phase 2.
- Nothing has run on a real robot yet. Everything was verified with fakes, local servers and headless screenshots.
- `docs/CRAB-SWAP-PLAN.md` is untracked on purpose (kept out of this public repo). Never commit it.

## Read these first (in this order)

1. `docs/BUILD-PLAN.md`: decisions and answers, the no-admin/no-firewall rule, the install layout, the API contract and the work packages A-G.
2. `docs/STUDENT-APP-PLAN.md`: the what and why. Decision S19 is full parity.
3. `docs/parity/*.md`: every control of the old tools, the checklist.
4. `docs/design/`: the canvas boards (`*.dc.html`), renders (`renders/*.png`) and the CSS (`builder/*.py`). The live canvas is the "Robot Hub student app" artifact on claude.ai.

## What is built (phases 1-2)

- **Hub backend** (`hub/`):
  - data folder (`ROBOT_HUB_DATA`), `defaults.toml`, settings store, `/api/app` (version, update check, quit, update);
  - single instance, no console windows, log report;
  - key tests (`keycheck.py`) with per-robot slots, the setup items and the NAO kit download (`requirements.py`);
  - `network.py`, the in-use marker (`inuse.py`), the new robot fields, Add WiFi for open networks.
- **Hub page:** `web/index.html`, `app.js`, `style.css`, with a demo mode at `?demo=<state>`.
- **reachy_app:** `web/reachy.html` with `reachy-*.js`, tabs `#group`, `#talk/<key>`, `#woz/<key>`, the proxy `hub/reachy_proxy.py` and `hub/transcripts.py`. `/group.html` redirects to it.
- **Pepper** (`pepper_app/`):
  - inverted link: the agent listens on robot 8790 and the tablet page is served from the robot on 8791;
  - new dashboard;
  - web search in free conversation (`websearch.py`).
- **Packaging:** `tools/build_release.ps1`, `tools/install.ps1`, `launch/launch.pyw` (tray and Edge app window), `assets/labalab.ico`. A test build gave `dist/RobotHub-1.0.0.zip` at about 113 MB.

## Next steps, in order

1. **Phase 3, verification: DONE 2026-11-05 (commit 7175116).** The parity sweep and the demo-screenshot check found 57 issues. All are fixed and checked by a separate verifier, and the tests are **531 passing**. The three Pepper state hints came later, in 9db7123 (532 tests).
2. **Release build and install test: DONE on this laptop 2026-11-05, rebuilt from commit 9db7123.** The zip is 113.6 MB, sha256 f04918bf…a23637, and `dist\` holds it. These all passed: install in 5 s, the `--check` self-test (ready in 11.7 s), a tray start where the only listener is 127.0.0.1:8099, Quit leaving no processes, reinstall keeping app.old and the data, and uninstall with and without `-RemoveData`. **Still open: a clean laptop or VM as a standard user.** The original steps:
   - Build: `powershell -ExecutionPolicy Bypass -File tools\build_release.ps1 -FromWorkingTree`.
   - Install from the local zip into a temp root with `tools\install.ps1 -Zip ... -Root ...`, then run the app, quit it and uninstall.
   - Ideally also on a clean laptop or VM as a **standard (non-admin) user**.
3. **Push and release.** Ask Tomer first, every time. **2026-11-05: both branches are pushed. Tomer runs the v1.0.0 release himself (the permission check blocks `gh release create` for Claude). Merging into master waits for his call: lab laptops `git pull` master on every start.**
   - Push `student-app` and reachy_chat `multi-provider` (use `GH_TOKEN=$(gh auth token --user labbgulab-lab)`).
   - Publish release `v1.0.0` with `RobotHub-1.0.0.zip` and `install.ps1`, marked latest. Until then, the README's one-line install returns 404.
   - Merge `student-app` into master when Tomer agrees.
4. **Guides: DONE**, see `docs/guides/STUDENT.md` and `LAB-STAFF.md`, linked from the README. The plan was a student guide (install, add a key, talk to a Reachy) and a lab-staff guide (capped keys, staff tools, updating). README install block exists.
5. **Lab day, robots needed:**
   - Pepper: the outbound link on 8790, the tablet page from the robot on 8791, and the chip must never say "fallback".
   - Reachy: Talk through the proxy, Wizard of Oz Say (prepare/say), live captions.
   - The in-use marker, Add WiFi with the Knows list, NAO/Pepper charging.
   - The NAO kit download and verify on a clean laptop.
   - Furhat: the skill rebuild without a baked-in key, password `admin`.

## Known gaps (from the builders)

- The New Reachy bring-up row only explains `tools\reachy_bringup.py`; there's no button yet.
- "Windows blocks Pepper" appears only when a start error mentions the firewall or port 8782; it should be rare now.
- The first Talk on a factory Reachy guesses "Installing the Reachy app" after 45 s starting; the hub doesn't report it.
- Log filters per robot match robot names in the text, because log lines carry no robot field.
- Talk gesture tags come from reachy_chat's log lines, so there are no tags after a reload.
- Group live captions type each line at about 15 characters a second, because the hub sends lines whole.
- reachy_chat's own log is not copied into the transcripts folder after a Talk.
- Typed Wizard of Oz lines need a Gemini key on the robot (Gemini text-to-speech), otherwise the code is `NO_KEY`.

## Rules that stay

- Students are not admin: nothing may listen on anything but 127.0.0.1, and nothing may need UAC.
- Public repo: no secrets, no personal names, no absolute user paths. Never print key files.
- Commit when asked. Push and release only with Tomer's OK.
