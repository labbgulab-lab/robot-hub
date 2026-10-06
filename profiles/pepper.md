# pepper (Pepper)

Captured 2026-10-06, over the iPhone hotspot. Probe:
`tools/naoqi/pepper_detail.py` (read-only). Setup history and the cable/WiFi
procedure: `job/pepper/PEPPER-FIRST-CONNECTION.md` §11.

**Short version for whoever builds the hub card:** Pepper is a NAOqi **2.5**
robot. It is controlled exactly like NAO (Python 2.7 + pynaoqi, `ALProxy` on
port 9559, no password), but it has a **tablet you can drive from the laptop**,
**wheels**, **no Sit/Lying postures**, and a **vendor app (Humanizing
Technologies) running in the foreground** that we have to deal with.

## A. Identity

| | |
|---|---|
| **IP (WiFi, head)** | **`172.20.10.2`** on 2026-10-06, DHCP. It can change, so resolve via mDNS |
| **IP (WiFi, tablet)** | **`172.20.10.3`** on 2026-10-06, DHCP. The tablet is a separate network device |
| IP when cabled | `169.254.8.188` (link-local; only with the head cable plugged) |
| Head WiFi MAC | `48:a9:d2:8c:6e:e6` |
| Head Ethernet MAC | `00:13:95:1d:51:0c` |
| Tablet WiFi MAC | `cc:1b:e0:b0:1e:10` |
| mDNS | `Pepper.local`, `_naoqi._tcp` :9559, TXT **`RobotType=Pepper`**, `RobotMaterialization=Real`; also `_ssh._tcp` :22 |
| Robot name | `Pepper` |
| NAOqi | **2.5.10.7** |
| Body | type `Juliette`, BaseVersion `1.8A`, Version `1.7.1` |
| Head id (stable key) | **`AP990237I00Y65100931`** (`RobotConfig/Head/FullHeadId`). `RobotConfig/Body/...BodyId` is not available on this robot |
| Made | 05/2016, model AP990236 (label behind the neck cover) |
| OS | Gentoo, kernel `4.0.4-rt1-aldebaran`; `/data` 25 GB, 4% used |
| Timezone | UTC |
| SSH | `nao` / `nao` (factory, unchanged) |

**Hub keying:** use the head id, not the mDNS hostname. NAO is `nao.local`
and Pepper is `Pepper.local`, so they do not collide today, but the hub's NAO
cards are keyed by hostname and the head id is the stable one.

**Hub discovery today drops Pepper:** `hub/discovery/mdns.py` accepts only
`RobotType=nao`. Pepper advertises `RobotType=Pepper` (exact case).

## B. Reachability

- **WiFi: 19.6 ms average, 0% loss.**
- **Open ports: 22, 80, 9559 only.** 9503/9443 (open on NAO 2.8) are closed.
  There is no TLS/login route; this is the 2.5 "classic" stack.
- Port 80: nginx 1.4.7, the robot web page (`http://172.20.10.2/`).
- As with NAO, a successful `ALProxy` call is the liveness test, not an open
  socket. Retry once before declaring a failure.

## C. Control surface (NAOqi, same as NAO)

Run anything through `job/naoqi/run_naoqi.sh` (Python 2.7 + pynaoqi 2.8.6
client; it talks to the 2.5 robot fine). `connect_pepper.py`,
`connect_naoqi.py <ip>`, `pepper_detail.py` all work.

**Tested and working on 2026-10-06:**

| What | Call | Result |
|---|---|---|
| Speak | `ALTextToSpeech.say(text)` | spoke; a short sentence took 4.0 s (it blocks until done) |
| Camera | `ALVideoDevice.subscribeCamera(name, 0, 2, 11, 5)` + `getImageRemote` | 640x480 RGB frame over WiFi |
| Microphones | `ALAudioRecorder.startMicrophonesRecording(path, "wav", 48000, (1,1,1,1))`, then SFTP the file | 4 channels, all live, about −33 dBFS |
| Battery | `ALBattery.getBatteryCharge()`; charging = `Device/SubDeviceList/Battery/Current/Sensor/Value` > 0 | 9→14%, +5.7 A while charging |
| Tablet | `ALTabletService`, see §D | page shown, taps received |
| Head | `ALBasicAwareness.setEnabled(False)` → `ALMotion.angleInterpolation(["HeadYaw","HeadPitch"], [yaw,-0.1], [1.5,1.5], True)` → restore awareness | ±0.5 rad, sensor within 0.02 rad |
| Gesture | `ALAnimationPlayer.run("animations/Stand/Gestures/Hey_1")` | wave, 4.4 s, arms only |
| Speech + gestures | `ALAnimatedSpeech.say("^start(animations/Stand/Gestures/Explain_1) text ^wait(...)")` | 3.6 s, back to `StandInit` |

Movement was tested with Autonomous Life left `interactive`. Only basic
awareness was paused, and only around the head moves, because face tracking
otherwise overrides head commands. Animations and animated speech need no
pausing. The stock library is under `animations/Stand/...` (Gestures,
Emotions, ...).

**Arms (tested, Tomer watched, all good):** both arms up, out to the
sides, a "V", hands open/close, one arm at a time and both together, via
`ALMotion.angleInterpolationWithSpeed(names, angles, 0.35)` with
`setBreathEnabled("Arms", False)` during the moves, then
`goToPosture("StandInit", 0.4)` (4.8 s). Head: a big yes (pitch −0.40..+0.50)
and a big no (yaw ±0.90) work too.

**Base/wheels (tested, works, but stops early near obstacles):**
`ALMotion.moveTo(0.20, 0, 0, [["MaxVelXY",0.15],["MaxAccXY",0.2]])` drove
11 cm forward, then the reverse move drove 3 cm back. Both returned `False`,
with `ALMotion/MoveFailed = ['Internal stop', 0, None]`.
- Pepper keeps an orthogonal security distance of **0.40 m** (tangential
  0.10 m). The front sonar read 0.42 m, so the forward move stopped at the
  boundary.
- Reversing stopped after 3 cm with 0.83 m clear behind. The back has
  sonar only, no lasers. The reason is not identified.
- **Preconditions:** the charger must be unplugged and the charging flap
  closed (battery current < 0). A dashboard should check this and refuse
  moves while charging.
- `moveTo` returns `False` rather than raising. Always check it and read
  `ALMotion/MoveFailed`.
- Pause basic awareness during base moves (it can turn the base toward
  people).

**Speech settings:** inline TTS tags (`\rspd=70\`, `\vct=135\`) are **read
aloud** on this robot, so don't use them. Use
`ALTextToSpeech.setParameter("speed", 70..140)` (default 100) and
`setParameter("pitchShift", 0.8..1.3)` (default 1.17), and restore them
afterwards. Volume via `ALAudioDevice.setOutputVolume` (default 50) works.
German and Chinese via `setLanguage` work.

**Listening (2026-10-06):**
- **The vendor app owns the recognizer.** `ALSpeechRecognition` subscribers
  are `ALDialogWordRecognized`, `ALFrameManagerSpeechDetected` and
  **`ht_cms_1_5`**. Its dialog topic `ht_cms_1_5-custom` is active.
- Our own `ALSpeechRecognition.setVocabulary` worked once, then failed with
  `A grammar named "modifiable_grammar" already exists` after the vendor app
  restarted. `removeContext` did not help. **Do not use
  ALSpeechRecognition directly while the vendor app runs.**
- `ALAutonomousLife.stopFocus()` did **not** stop the vendor app; it stayed
  focused.
- **What works:** `ALDialog`. `loadTopicContent(topic)` →
  `deactivateTopic("ht_cms_1_5-custom")` → `activateTopic(ours)` →
  `subscribe` → `setFocus`. A rule
  `u:(_[yes no red ...]) $LabQuiz/Answer=$1` writes the heard word to
  ALMemory, and Python polls it. Afterwards, unload ours and reactivate the
  vendor topic (restored cleanly).
- The first question got nothing on two tries, probably because the topic
  was still compiling after `activateTopic`. Wait a few seconds before the
  first question.
- Built-in recognition is **closed vocabulary**, English/German only. Free
  conversation (and Hebrew) means recording on the robot's 4 mics and doing
  STT + LLM on the laptop.

**Not yet tested:** the depth camera; streaming robot audio to the laptop.

### Speech
- TTS languages: **English, German, Chinese.** Voices `naoenu`, `anna`,
  `naomnc`. **No Hebrew.** Hebrew speech would have to be laptop TTS played
  on the robot (e.g. `ALAudioPlayer` on an uploaded file). Not tried.
- TTS volume 1.0; `ALAudioDevice` output volume 50.
- ASR (`ALSpeechRecognition`): English and German.
- `ALDialog` language English; loaded topic `ht_cms_1_5-custom` (the vendor's).

### Cameras
`[0, 1, 2]` = `CameraTop`, `CameraBottom` (model 3), **`CameraDepth`**
(model 4, a 3D sensor). The 3D camera is the Pepper 1.7 setup.

### Body
- Joints: `HeadYaw, HeadPitch, L/R ShoulderPitch, ShoulderRoll, ElbowYaw,
  ElbowRoll, WristYaw, Hand, HipRoll, HipPitch, KneePitch` + wheels
  `WheelFL, WheelFR, WheelB`.
- **Postures: `Crouch`, `Stand`, `StandInit`, `StandZero`. No Sit, no
  LyingBack.** NAO's `sit`/`lie` buttons and `lie_down.py` must not be used.
  Rest = `ALMotion.rest()`.
- External collision protection: **on**. Leave it on.
- Sensors present: front/back sonar, base lasers, bumpers, head and hand
  touch.

### Autonomous Life and the vendor app ⚠️
- State **`interactive`**. All autonomous abilities on (blinking, background
  movement, basic awareness, listening/speaking movement). It tracks faces
  and moves its head by itself.
- **Focused activity: `ht_cms_1_5/behavior_1`**, the Humanizing
  Technologies CMS app. It owns the dialog and normally the tablet. 20+
  `ht_*` packages are installed (cms, chatbot_connector, mqtt, analytics,
  tictactoe, welcoming, presentation, ...). They match the vendor
  whitelist doc in `Downloads\Pepper and NAO AI Whitelist.docx`.
- **For our own app:** our `showWebview` call took over the screen while
  the vendor app was running. We have **not** tested whether it fights back
  for the tablet, dialog or microphones. The usual way to take full control
  is `ALAutonomousLife.stopFocus()` (keeps Life on, stops the app) or
  `setState("disabled")`. **Untested on this robot.** `disabled` also stops
  its awareness, so only do it with someone watching.
- **Do not uninstall the `ht_*` packages.** They may be the lab's paid
  vendor setup.

## D. The tablet (chest screen) — how to drive it

The tablet is an Android device with its own WiFi. NAOqi 2.5 controls it
through **`ALTabletService`** on the head.

**Network (done 2026-10-06):** the tablet joined "Tomer Iphone" with
```
tab.enableWifi(); tab.configureWifi("wpa", "Tomer Iphone", <psk>); tab.connectWifi("Tomer Iphone")
```
`getWifiStatus()` → `CONNECTED` in 4 s. Tablet version `3.3.24`. Inside the
robot the tablet sees the head as **`198.18.0.1`**.

**The pattern that works (tested):**
1. The laptop serves a page over HTTP (tested: `0.0.0.0:8765`; Windows
   firewall allowed it, and both head and tablet fetched from `172.20.10.4`).
2. `ALTabletService.showWebview("http://172.20.10.4:8765/")` → `True`, and
   the page appears full-screen.
3. **Taps come back over plain HTTP:** the page's button does
   `GET /touch?b=A` to the laptop. Received both taps within a second, from
   `172.20.10.3`.

So a hub dashboard can **own the screen end-to-end from the laptop**. It serves
the page, gets touches as HTTP requests, and drives speech and motion through
NAOqi. No app needs to be installed on the robot.

**What did not work:** the in-page NAOqi JS bridge
(`http://198.18.0.1/libs/qimessaging/2/qimessaging.js` + `QiSession(...,
'198.18.0.1')`) stayed on "connecting" when the page came from the laptop.
It is cross-origin; it is meant for pages served from the robot itself
(`/apps/<package>/`). Not needed with the HTTP pattern above.

**Other `ALTabletService` calls** (2.5 API, not all tried): `hideWebview()`,
`loadUrl(url)`, `reloadPage(bypassCache)`, `executeJS(js)`,
`showImage(url)`, `hideImage()`, `playVideo(url)`, `stopVideo()`,
`setBrightness(0..1)` (now 1.0), `getWifiStatus()`, `robotIp()`. The
`onTouchDown` signal on the head gives raw screen coordinates when no webview
is consuming touches.

**If the tablet goes dark:** press the tablet's own power button (on its
edge).

## E. Ownership on the laptop

The same as NAO (see `naoqi.md` §D). Python 2.7 + pynaoqi through
`run_naoqi.sh`, so the hub shells out to a subprocess. Pepper and NAO can
share the same agent code with a `pepper` type and a different posture list.

**Microphones:** Pepper records on its own 4 mics (above), so a Pepper app
does not need the laptop's default input. That avoids the NAO_LLM
default-mic trap, as long as the app is written to use the robot's mics.

## F. What a `pepper` hub card needs (from the plan, now with real values)

1. Discovery: map `RobotType=Pepper` → type `pepper` in `mdns.py`.
2. Key: `RobotConfig/Head/FullHeadId` = `AP990237I00Y65100931`.
3. Adapter: NAOqi 2.5, `ALProxy` on 9559, no auth. Postures `stand`/`rest`
   only. Battery via `ALBattery`, plus a "charging" flag from battery
   current > 0.
4. A screen panel: `showWebview(<hub url>)`, `hideWebview()`, HTTP touch
   endpoint.
5. A decision on the vendor app (§C): leave it running, or `stopFocus()`
   when our app launches.
6. Announce "I am Pepper". `web/photos/pepper.png` already exists.

## G. Safety reminders (Pepper is not NAO)

29.6 kg, wheels, falls forward. Keep 90 cm clear when it wakes. Do not drive
the base until the floor is known to be clear. Never insert the hip/knee
pins while it is on. **Battery arrived at 9%.** Charge for several hours,
and do not let it run flat, or it locks for good.

## H. Giving Pepper "life" with an LLM: where the software can run (checked 2026-10-06)

**On the robot (possible, but a poor home for the brain):**
- Intel Atom E3845, 4 cores, 4 GB RAM (about 2.7 GB free), `/data` 23 GB free.
  **No local LLM** is realistic on this.
- **Python 2.7.6 only** (no python3). OpenSSL **1.0.1h (2014)**. The root
  filesystem is **read-only**, sudo does not work, so nothing can be
  installed system-wide. Our code can live under `/home/nao`, or as a
  Choregraphe `.pkg` with an `autorun` service (the vendor's `ht_*` apps
  are installed this way).
- **Internet from the robot:** `curl` reaches api.openai.com (401),
  generativelanguage.googleapis.com (404) and api.anthropic.com (405), so
  TLS works through curl. **Python 2's `urllib2` fails on OpenAI**
  (`sslv3 alert handshake failure`, no SNI in 2.7.6) but works on Google.
  On-robot code would have to shell out to `curl`.
- The vendor's `ht_chatbot_connector` is a 4-line loader around compiled
  code, and `ht_analytics` reports to `staging.humanizing.com`. **Nothing
  reusable** for our own LLM.

**On the laptop (recommended): Pepper is the body, the laptop is the brain.**
This is the same split NAO_LLM uses, and it fits the hub's subprocess model:
```
Pepper 4 mics --(ALAudioRecorder file / ALAudioDevice stream)--> laptop
laptop: VAD -> STT (faster-whisper / Whisper API; Hebrew OK) -> LLM -> reply
reply -> Pepper: ALAnimatedSpeech.say (English/German, with gestures)
               or laptop TTS -> wav -> ALAudioPlayer (Hebrew, any voice)
       + ALTabletService.showWebview (laptop-served page) for the screen
       + ALMotion / ALAnimationPlayer for body language
```
- Every robot-side piece above is **tested today** except streaming
  audio and `ALAudioPlayer` playback of an uploaded wav.
- Existing code to reuse: `job/naoqi/NAO_LLM` (VAD + faster-whisper + LLM +
  robot TTS, web UI) and `NAO_LLM_v2` (continuous ASR, OpenAI TTS). Both
  capture from the **laptop's** default mic; for Pepper, switch the
  capture to the robot's mics.
- Leave the vendor topic active when we are idle, and deactivate it while
  our session runs (§C, Listening).
