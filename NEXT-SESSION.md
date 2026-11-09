# Next session: start here

**Updated 2026-11-09, end of the last lab day.** Windows students are on **v1.0.5** (latest). The **Mac version is built but on hold** as the **v1.0.6 draft**. The next job is finishing the Mac release.

## Where things are

| Repo | Branch | Last commit | State |
|---|---|---|---|
| robot-hub (this repo) | `master` | `97d9cb8` Mac build: no exact pins on Intel | Pushed. `fix/v1.0.1` = `master` |
| reachy_chat (`../reachy-mini/reachy_chat`) | `main` = `multi-provider` | `8a60d92` Deploy: pin google-genai, seed the show folder | Pushed |
| robot-lab (`job`) | `main` | `01431d2` reachy10 | Pushed |

- **Releases:**
  - **v1.0.5** is the published latest. Its Windows zip was built from `51df373`.
  - **v1.0.6** is a **DRAFT**, tagged `v1.0.6` -> `7f33b91`. It holds the Windows zip, `install.ps1`, `install-mac.sh` and `RobotHub-mac-arm64-1.0.6.tar.gz`. **No Intel tarball yet.**
- **Tests:** 700 pass on Windows (`.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`).
- **Worktrees:**
  - `job/rh-release` is a worktree on branch `mac-integration`, the same commit as `master`. Delete it when done.
  - In the main checkout `job/robot-hub`, someone else's **uncommitted** change to `hub/discovery/netscan.py`, `tests/test_discovery.py` and `tools/reachy_bringup.py` makes the sweep also try `.0`/`.255` addresses (a Furhat got one ending in .255). It is not ours: ask before committing it. That checkout's local `fix/v1.0.1` is behind `origin`.

## Finish the Mac release (do this first)

1. **Intel build.** The Mac Action (`.github/workflows/mac-release.yml`, run with `gh workflow run mac-release.yml -f tag=<tag> -f upload=true`) passes on Apple Silicon: build, install, and `launch_mac.py --check` on a real Mac. On Intel (`macos-15-intel`) it fails because PyPI has no Intel Mac wheels for current zeroconf, cryptography or onnxruntime.
   - zeroconf is fixed: it is built as plain Python.
   - The fix for the rest (`97d9cb8`: no exact pins on Intel, so pip takes the newest version that still has an Intel wheel) is pushed but **has not run yet**.
2. **The tag.** Moving `v1.0.6` to the fix needs a force-push, which the permission check blocked on 2026-11-09. Pick one:
   - (a) The user approves `git push -f origin v1.0.6`. Then rerun the Action and publish v1.0.6 with Intel.
   - (b) Publish v1.0.6 as it is (Windows + Apple Silicon), then do Intel as **v1.0.7** under a new tag, which needs no force. For v1.0.7: bump `VERSION`, run `tools\build_release.ps1 -ReachyChat <reachy_chat>`, push the tag, create the release as a draft with the Windows assets, run the Action, then publish as latest.
   - The user chose to wait. Ask them first.
3. **Before publishing,** check that the draft has `RobotHub-mac-<arch>-<v>.tar.gz` (+ `.sha256`) for each arch, plus `install-mac.sh`. Publish with `gh release edit <tag> --draft=false --latest`.
4. **The link for Mac users** works only once a published latest release carries the Mac files: `curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install-mac.sh | bash`. It is already in the README and the release notes.
5. **Mac facts:**
   - Apple Silicon (M1 to M5) needs **macOS 14 or newer**.
   - NAO and Pepper stay Windows-only.
   - The hub runs with `-c "from hub.main import main; main()"`.
   - The data folder is `~/Library/Application Support/LabaLab/RobotHub/data`.
   - The app is installed as `~/Applications/LabaLab Robot Hub.app`.

## What was done on 2026-11-09 (lab day)

- **Robots:**
  - **reachy9** and **reachy10** were built and set up on HOT-WiFi. Their details are in the private fleet list.
  - Talk, group, Choir and Wizard of Oz were tried on both.
- **Fixed and released (1.0.1 to 1.0.5, all pushed):**
  - **The hub froze on HOT-WiFi.** The search started about 100 `ping.exe` a second from the event loop, and one CreateProcess hung. Now: `hub/discovery/icmp.py` (IcmpSendEcho on daemon threads).
  - **New Reachys got google-genai 3.0.0**, so every Talk returned HTTP 404. reachy_chat's deploy now pins 2.23.0.
  - **New Reachys had no Wizard of Oz cues.** The deploy now seeds `show/`.
  - **Group-tab Wizard of Oz for the whole table** (`hub/group/woz.py`, `web/reachy-group-woz.js`): Choir is one unit, otherwise a random or chosen target; it works offline. The review's 42 findings are all fixed.
  - **Self-update on start (1.0.3+):** the installed app only, in its first 3 minutes, with no robot connected; a 5 s countdown and **Not now**.
  - **README:** a 3-step student install at the top.
- **Not yet seen on a real screen:** the self-update popup. Opening a 1.0.3 or 1.0.4 install should show it.

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
