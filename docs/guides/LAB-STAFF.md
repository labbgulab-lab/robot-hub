# Robot Hub: lab staff guide

For the lab manager and lab members who hand out keys, set robots up and release new versions. Students use [STUDENT.md](STUDENT.md).

## Capped lab keys

Each student gets their own key with a spending cap. Delete it when the student leaves.

1. Make an OpenAI project key on the OpenAI site, with a monthly budget. It runs every robot and group talk. For now this is the only capped lab key. OpenRouter lab keys, with a credit limit, come later. Students can also add their own Gemini, OpenRouter or ElevenLabs key (ElevenLabs is optional, for nicer voices, and cannot talk alone).
2. Give the key to the student privately.
3. The student pastes it into **Add a key to get started**, or into **Settings**, **Keys**. The app tests it with a free call and shows **It works**, **Works, but no credit left** or **That key didn't work**.
4. In **Settings**, a key with credit left shows **$ left** or **chars left**. **Used up** means the cap is reached.

Keys never go into the repo, a release or a robot file. The release build stops if a key-shaped string is in the bundle.

## Staff tools

Staff tools are off by default. Turn them on in **Settings**, **Lab staff tools**, with the **Show lab staff tools** switch. Then these appear:

| Tool | Where | When to use it |
|---|---|---|
| **Robot files** | **Settings**, **Lab staff tools**, **Open** | Share or fetch files for a robot (see below). |
| **New Reachy** | **Bring up** | Shows how to bring up a new Reachy: run `tools\reachy_bringup.py` on a lab laptop with the repo. There is no button for it yet. |
| **Add WiFi** | Each robot's **...** details | Teach a robot a WiFi (see below). |
| **NAO app** | Button on the NAO card | Start the NAO app. It is a staff tool and needs the lab's own NAO folder. |
| **Check this laptop** | **Run** | Checks Python, the kit, ports and the firewall. Shows a remedy for each failure. |
| **In use** | Shown in the list | Shows which microphone, speaker and ports robots hold on this laptop. |
| **Take over** | On a card marked **In use** | Takes a robot from another laptop. Students cannot do this. |

## Robot files library

The library holds files for the robots (for example Furhat skills). They are shared through the `robot-files` release of the repo on GitHub.

1. Turn on staff tools, then open **Settings**, **Lab staff tools**, **Robot files**, **Open**.
2. Pick the robot in the list. The number is how many files it has.
3. To fetch a file, press **Download**. If the file needs a key, pick **With** a key name or **Without a key** first. A copy with your key in it is for you only.
4. To share a file, press **Choose**, pick the file, then press **Upload**. Keys are taken out before upload. If the file already exists, press **Upload** again to replace it for everyone.
5. To delete a file for everyone, press the bin, then **Press again**.

Reading and downloading need no sign-in while the repo is public. Uploading and deleting need GitHub access with write rights to the repo. The hub uses `GITHUB_TOKEN` from the `.env` file next to the code, or else the account signed in with `gh auth login`. On an installed laptop the app folder is replaced on every update, so sign in with `gh` rather than keeping a `.env` there.

## Add WiFi and the lab network

The lab WiFi is HOT-WiFi. It is open (no password) and has internet. The hub finds robots by scanning addresses, because this WiFi drops the robots' name announcements. **Settings**, **Lab WiFi** shows the name. **Change** edits it (**Open, no password** is a tick box), and **Network help** opens the setup steps.

**Add WiFi** (a robot's **...** details, staff tools on) works for Reachy, Pepper and NAO:

1. Turn the hotspot on first, at 2.4 GHz. On an iPhone, turn on **Maximize Compatibility** and keep that screen open.
2. Type the **WiFi name** and the **Password** (8 to 63 characters), or tick **Open WiFi, no password**.
3. Press **Join**. It can take up to a minute. The robot moves to that WiFi, and the app says to move this laptop there too.
4. For a Reachy you can tick **Save only, don't move now (lab WiFi fallback)** before **Join**. The robot saves the WiFi and keeps its current one.
5. **Knows** lists the WiFi the robot has saved. It loads by itself. **Ask again** shows only when the robot could not be asked.

Teach every robot the demo hotspot in the lab before a demo. **Settings**, **Demo on a phone hotspot**, **Plan** counts devices: a hotspot takes 5, the laptop is one, and Pepper is two.

Each robot also needs the lab WiFi once. The network chip at the top opens the steps for each robot type.

## Build a release

Do this on a Windows lab laptop with robot-hub and reachy_chat side by side.

1. Change `VERSION` (for example `1.0.1`) and commit it. The build uses committed files only.
2. Make sure the reachy_chat `multi-provider` branch has the commit you want.
3. Run, from the robot-hub folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\build_release.ps1
   ```

   `-FromWorkingTree` adds uncommitted work, for testing. Never publish a build made that way.
4. Wait for the `done` line. It writes to `dist\`:
   - `RobotHub-<version>.zip` (about 114 MB) and its `.sha256` file
   - `install.ps1`
5. Quit Robot Hub first, and any hub running from a checkout: a second start only opens the hub that is already running. Then test it in a temp folder, so the real install and shortcuts stay untouched:

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Zip dist\RobotHub-<version>.zip -Root <temp folder>\root -DesktopDir <temp folder> -StartMenuDir <temp folder>
   ```

   The app opens by itself. Press **Settings**, **About**, **Quit**, **Press again to quit**. Then remove the test install with the same folder:

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall -RemoveData -Root <temp folder>\root -DesktopDir <temp folder> -StartMenuDir <temp folder>
   ```

## Build the Mac app

The Mac app is built on GitHub's own Macs, by the **Mac release** GitHub Action (`.github/workflows/mac-release.yml`). You do not need a Mac. For each Mac type (Apple Silicon `arm64` and Intel `x86_64`) it:

1. builds `RobotHub-mac-<arch>-<version>.tar.gz` with `tools/build_release_mac.sh`, from the tag's robot-hub and reachy_chat's `main` branch (the same Python 3.12 as Windows; Windows-only packages are left out);
2. installs it into a temp folder with `install-mac.sh --tar ... --no-launch`;
3. runs the installed app's self-test (`launch_mac.py --check`). The run fails unless the hub starts and reports the tag's version;
4. runs the hub's tests on macOS. A failure there is shown in the run's summary and marks the run red at the end, but the assets are still uploaded: read it and decide;
5. uploads `RobotHub-mac-arm64-<version>.tar.gz`, `RobotHub-mac-x86_64-<version>.tar.gz`, their `.sha256` files and `install-mac.sh` to the release. They are also kept for 14 days as the run's artifact.

On a Mac with both repos side by side you can build by hand: `bash tools/build_release_mac.sh arm64` (or `x86_64`), then test with `bash dist/install-mac.sh --tar dist/RobotHub-mac-arm64-<version>.tar.gz --root /tmp/rh --apps-dir /tmp/apps --no-launch` and `/tmp/rh/app/runtime/bin/python3 /tmp/rh/app/launch_mac.py --check`.

The build picks packages for the oldest macOS it can (11 first). The result is in the app as `MACOS_MIN`; the installer refuses an older Mac with a clear line.

## Publish a release

Windows and Mac assets go into the same release. Students on a Mac only get a release that has the Mac tarball for their Mac, so a release published without them is never offered to Macs. But the Mac install line downloads the **latest** release's `install-mac.sh`, so always add the Mac assets before you publish.

1. Push the tag: `git tag v<version>` then `git push origin v<version>` (for example `v1.0.6`). The tag must be on the commit that has the new `VERSION`.
2. On GitHub, open the repo's releases and make a new release on that tag. Upload `dist\RobotHub-<version>.zip` and `dist\install.ps1`. Press **Save draft**, not **Publish**.
3. Open **Actions**, **Mac release**, **Run workflow**. Type the tag (`v<version>`), leave **Upload** ticked and press **Run workflow**. It takes about 15 minutes. Both jobs (arm64 and x86_64) must be green. If the Intel job cannot start because GitHub has no `macos-15-intel` machine any more, change that label in the workflow (see the comment there).
4. Open the draft again. It now also has `RobotHub-mac-arm64-<version>.tar.gz`, `RobotHub-mac-x86_64-<version>.tar.gz`, their `.sha256` files and `install-mac.sh`.
5. Publish it and mark it as the latest release. The student install lines and the **Update** button use the latest release's `install.ps1` and `install-mac.sh`. The `robot-files` release must not be the latest.
6. Test the install line on a second laptop, and on a Mac if you have one.

If you forgot the Mac step and already published, run **Mac release** for that tag anyway: it uploads to a published release too.

## How the in-app update check works

- The hub asks GitHub for the repo's releases at most every 6 hours (also when the app starts). **Check for updates** asks GitHub at once (at most once a minute), so right after you publish, press it and a running app offers **Update**. It picks the highest version among the published releases whose tag starts with `v` and which has the app for this computer: a `RobotHub-*.zip` on Windows, a `RobotHub-mac-arm64-*.tar.gz` or `RobotHub-mac-x86_64-*.tar.gz` on a Mac. Drafts, pre-releases and `robot-files` are skipped.
- If that version is newer than the installed one, students see **New version** and **Update** at the top, and **Update** in **Settings**, **About**.
- **Updates itself on start (1.0.3 and later):** when the installed app finds a newer release in its first 3 minutes and no robot is connected, it shows the spinning logo, "Robot Hub <version> is out", and counts down 5 s (**Update now**, **Not now**). Then it installs the update and opens again. A lab checkout never does this. Apps older than 1.0.3 need one manual **Update** to get this.
- **Update** opens PowerShell, runs the install line, stops the hub, swaps the app folder and opens the app again. On a Mac it runs the Mac install line in the background instead (no window; its output goes to `data/logs/update.log`). If the network is down, the check fails quietly and tries again later.
- The previous app stays as `app.old` until the next install.

## Where student data lives

Everything is under `%LOCALAPPDATA%\LabaLab\RobotHub`, per Windows user:

- `app\` is the program. Every install or update replaces it.
- `data\` is the student's. Install and update never touch it:
  - `keys.local.json`: the keys
  - `settings.json`, `config.toml`, `group.local.json`: settings
  - `transcripts\`: saved conversations
  - `logs\`, `cache\`, `pepper\`, `edge-profile\`
- The Pepper and NAO kit is in `C:\LabaLab\naoqi-sdk`, or in `%PUBLIC%\LabaLab\naoqi-sdk` if `C:\` is not writable.

On a Mac the same folders are under `~/Library/Application Support/LabaLab/RobotHub` (`app/`, `app.old/`, `data/`), and the icon is `~/Applications/LabaLab Robot Hub.app`. The Mac app opens the hub in the default web browser. Pepper and NAO cards say they need a Windows laptop: their kit is Windows only.

The hub listens on 127.0.0.1 only (port 8099). It needs no admin rights and no firewall rule.

To help a student, ask for the report from **Logs**, **Save a report for the lab**. Keys are taken out of it.

## Uninstall

On the student's laptop, in PowerShell:

```powershell
& ([scriptblock]::Create((irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1))) -Uninstall
```

This closes the app and removes `app\`, `app.old` and both shortcuts. The `data\` folder stays. Add `-RemoveData` to delete it too (keys, settings, transcripts, logs). The NAO kit in `C:\LabaLab` is not removed.

With a saved copy of the installer: `powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall -RemoveData`.

On a Mac, in Terminal:

```bash
curl -fsSL https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install-mac.sh | bash -s -- --uninstall
```

This closes the app and removes `app/`, `app.old/` and `~/Applications/LabaLab Robot Hub.app`. Add ` --remove-data` at the end to delete `data/` too.
