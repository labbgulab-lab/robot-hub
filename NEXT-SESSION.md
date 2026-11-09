# Next session: start here

**Updated 2026-11-09, evening.** **v1.0.9 is the published latest**, for Windows and for both kinds of Mac (Apple Silicon and Intel). Nothing is on hold. Each fix that is ready ships as its own patch version (1.0.7, 1.0.8, ...); several fixes are not held back for one release.

## Where things are

| Repo | Branch | Last commit | State |
|---|---|---|---|
| robot-hub (this repo) | `master` | `92b87e4` Robot Hub 1.0.8: one Quit closes the whole app | Pushed, tag `v1.0.8` |
| reachy_chat (`../reachy-mini/reachy_chat`) | `main` = `multi-provider` | `8a60d92` Deploy: pin google-genai, seed the show folder | Pushed; bundled in 1.0.7 and 1.0.8 |
| robot-lab (`job`) | `main` | `01431d2` reachy10 | Pushed |

- **Releases:**
  - **v1.0.9**, latest: the in-app Update works on Windows. It never had before: the app started the installer with its own folder (`appobot-hub`) as the current directory, and Windows will not rename a folder a process is in, so the swap always failed and the window closed blank. `install.ps1` now steps out of the install folder first. Apps of every version fetch the latest installer, so their Update works too. Built from `f5e04db`.
  - **v1.0.8**: one Quit closes the whole app. Built from `92b87e4`.
  - **v1.0.7**: robots on `.0` and `.255` addresses get their card (Furhat had `172.19.94.255` on HOT-WiFi), plus the first Intel Mac build. Built from `d155c50`.
  - Both carry all 8 assets: `RobotHub-<v>.zip`, `install.ps1`, `install-mac.sh`, `RobotHub-mac-arm64-<v>.tar.gz`, `RobotHub-mac-x86_64-<v>.tar.gz`, and the `.sha256` file of each archive.
  - **v1.0.6** stays an unpublished **draft**. It was the Apple Silicon-only Mac release, and 1.0.7 holds everything in it. It can be deleted.
- **Tests:** 715 pass on Windows (`.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider`).
- **Worktrees:** none left; all were removed on 2026-11-09 evening.
- **Main checkout `job/robot-hub`:** still on the old local `fix/v1.0.1` branch. It has the uncommitted `.0`/`.255` change, now redundant because it is on master, and a 4-line note in this file. Its `git pull --ff-only` fails because of them, so `Start Robot Hub.cmd` there runs old code. Move it to `master` and drop those changes. This laptop also has the **installed** app now, under `%LOCALAPPDATA%\LabaLab\RobotHub`. When both are started, the installed app holds port 8099.

## What was done on 2026-11-09 (evening)

1. **Intel Mac build fixed** (`b9adf75`): `tools/build_release_mac.sh` no longer stops when the Intel constraints file has no zeroconf pin.
2. **Mac release Action test builds** (`332392a`): with **Upload** off, the tag input may be a branch or a commit (for example `master`). Nothing goes to any release, and VERSION need not match. Use this to test the Mac build without making a tag.
3. **Network search** (`24bc983`, in 1.0.7): in a /24 block cut out of a bigger network (the /16 HOT-WiFi), `.0` and `.255` are ordinary hosts. Only the whole network's own first and last address are left out. `tools/reachy_bringup.py` shares the fix (`_block_hosts`).
4. **One-press Quit** (`bc906c4`, then review fixes `7642484`, in 1.0.8):
   - Settings > Quit used to need a second press ("Press again to quit"). Now one press quits.
   - The hub publishes `quitting`. Both the main window (`web/app.js`) and the Reachy window (`web/reachy-core.js`) close themselves when the hub is gone. The launcher closes only windows titled Robot Hub.
   - **Hard exit:** 60 s after Quit, longer than the shutdown's own limits, so a Reachy off the WiFi does not stop the others being put to sleep. Then 5 s more after the robots.
   - The tray's tree kill spares the Update installer (`install.ps1`).
   - The no-tray launcher (`wait_and_close`) waits for its hub. If another hub holds the port, it leaves that hub's window open.
   - `launch_mac.py --quit` waits until the hub is gone.
   - **Checked for real** on an installed 1.0.8, with the main window and a Reachy window open. 7 s after one Quit, both windows were gone, port 8099 was free and the launcher had exited with code 0.

## Open items

- **One press quits:** there's no confirm step any more (requested). A mis-click in Settings stops every robot.
- **Intel Mac** builds with no exact pins: pip takes the newest version that still has an Intel wheel (onnxruntime 1.19.2, for example). Only `launch_mac.py --check` and the installer tests cover it in CI. It has never run on a real Intel Mac.
- **On macOS,** 15 of the hub's tests (written on Windows, mostly `tests/test_hub_features.py`) fail. They are for information only and don't gate the Action.
- **On a Mac,** the page is a normal browser tab. A browser may refuse `window.close()` after Quit. The hub still ends, and the tab shows "Robot Hub stopped".
- **Not yet seen on a real screen:** the self-update popup (1.0.3+). Any installed 1.0.3 to 1.0.7 that opens with no robot connected should show it now.
- **Mac facts:**
  - Apple Silicon (M1 to M5) needs **macOS 14 or newer**; Intel needs **macOS 11 or newer**.
  - NAO and Pepper stay Windows-only.
  - Data lives in `~/Library/Application Support/LabaLab/RobotHub/data`.
  - The app is `~/Applications/LabaLab Robot Hub.app`.
  - Mac install line: `curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install-mac.sh | bash`.

## How to release (as done for 1.0.7 and 1.0.8)

1. Bump `VERSION` and commit it.
2. `tools\build_release.ps1 -ReachyChat ..\reachy-mini\reachy_chat`. The `-ReachyChat` path is needed when building from a worktree.
3. Test the build in a temp root with `tools\install.ps1 -Zip ... -Root ... -NoLaunch`, then `app\runtime\python.exe app\launch.pyw --check`.
4. Push `master`, then push the tag `v<version>`.
5. `gh release create v<version> --draft --verify-tag` with the zip, its `.sha256`, `install.ps1` and `install-mac.sh`.
6. Run `gh workflow run mac-release.yml -f tag=v<version> -f upload=true -f reachy_chat_ref=<the commit the Windows build printed>`.
7. When all three jobs are green and the draft has 8 assets: `gh release edit v<version> --draft=false --latest`.
8. The permission check has blocked Claude from creating a release or publishing it before. When it does, the user runs that step, or tells Claude to run it.

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
  - **Check for updates** now forces a check, at most once a minute.
  - **README:** a 3-step student install at the top.
- **Mac version** (1.0.6 draft, shipped in 1.0.7): `launch/launch_mac.py`, `tools/install-mac.sh`, `tools/build_release_mac.sh`, `.github/workflows/mac-release.yml`.

## Known gaps (from the builders)

- The New Reachy bring-up row only explains `tools\reachy_bringup.py`; there's no button yet.
- "Windows blocks Pepper" appears only when a start error mentions the firewall or port 8782; it should be rare now.
- The first Talk on a factory Reachy guesses "Installing the Reachy app" after 45 s of starting; the hub doesn't report it.
- Log filters per robot match robot names in the text, because log lines carry no robot field.
- Talk gesture tags come from reachy_chat's log lines, so there are no tags after a reload.
- Group live captions type each line at about 15 characters a second, because the hub sends lines whole.
- reachy_chat's own log is not copied into the transcripts folder after a Talk.
- Typed Wizard of Oz lines need a Gemini key on the robot (Gemini text-to-speech), otherwise the code is `NO_KEY`.

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
