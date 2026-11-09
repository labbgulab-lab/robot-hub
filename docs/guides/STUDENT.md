# Robot Hub: student guide

Robot Hub finds the lab's robots on the WiFi, connects them and starts their apps. It runs on your own Windows 10 or 11 laptop. You do not need admin rights, Python or Git.

## Install

1. Press Start, type `PowerShell` and press Enter.
2. Paste this line and press Enter:

   ```powershell
   irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1 | iex
   ```

3. Wait. It downloads about 114 MB, puts a **LabaLab Robot Hub** icon on your desktop and in the Start menu, and opens the app. You can close the PowerShell window.

**If the line is blocked:**

1. Open the [latest release](https://github.com/labbgulab-lab/robot-hub/releases/latest).
2. Download `RobotHub-<version>.zip` and unzip it.
3. Double-click `Install Robot Hub.cmd`.

## First start

The app opens in its own window and shows **Starting**. Then it asks **Add a key to get started**. Do the next section.

Every later day, double-click **LabaLab Robot Hub**. Closing the window does not stop the robots. To stop everything, use **Settings**, then **About**, then **Quit** and **Press again to quit**, or the tray icon, then **Quit**.

## Add a key

A key lets the robots talk. You need one from the lab (ask the lab manager for your own capped key) or your own OpenAI, Gemini or OpenRouter key. An ElevenLabs key adds nicer voices but cannot talk by itself.

1. In the **Add a key to get started** window, paste the key into **Your key**. The service name shows at the top right of the box.
2. Press **Test and save**. Wait for **It works**.
3. Press **Done**, or **Add another**.

Notes:

- If the app asks **Which service is it from?**, pick the service (OpenAI, Gemini, OpenRouter or ElevenLabs).
- **Later** closes the window. A bar stays at the top ("No key yet") until a key works. Press **Add a key** in the bar to come back.
- To add, check or remove keys later: **Settings**, then **Keys**. **Remove** needs a second press (**Press again**).
- The key stays on this laptop.

## Connect a robot

1. Join the robots' WiFi (the lab WiFi, HOT-WiFi). If the app shows **No robots nearby**, press **Open WiFi settings**.
2. Wait about 30 seconds. Each robot shows as a card. **Available** means it is found.
3. Press **Connect** on the card. Or turn on **Auto-connect** at the top, and robots connect when they show up.
4. The card changes to **Connected**. Press **Scan** at the top to look again.

Each robot has its own main button: **Talk** (Reachy), **Open Studio** (Furhat), **Open dashboard** (Pepper). On Reachy, Pepper and Furhat, **Speaks through** picks which key the robot uses. The default is your first working key.

**Pepper and NAO** need a one-time download. Their card says **Needs setup**. Press **Set up**, then **Get it** (about 360 MB). Wait for **Installed**, then press **Done**.

The **...** button on a card shows details: address, software version, battery, last seen. **Copy details** puts them on the clipboard.

## Talk to a Reachy

1. Connect the Reachy (see above).
2. Check that **Speaks through** shows a Gemini or GPT key. ElevenLabs cannot talk alone, and OpenRouter works in group talk only.
3. Press **Talk** on its card. The Reachy app opens in a new window, on the **Talk** tab.
4. If it shows **Start Talk**, press it. The first time, the robot installs its own app, which takes a few minutes.
5. Press **Start conversation**. The robot speaks first.
6. End it by saying "goodbye", or press **End conversation**.

Under **How it talks** you can change **Brain**, **Language**, the voice and **Camera vision**. **Character** changes who the Reachy is. These apply to the next conversation.

**Wizard of Oz** (the tab, or the button in the card's **...** details): you type a line, press **Say**, and the Reachy says it. Typed lines need a Gemini key on the robot, otherwise you get the code `NO_KEY`. **STOP** (or Esc) stops it.

## Group conversation

Two or more Reachys talk with each other and with the people in the room.

1. Connect at least two Reachys.
2. On the hub, in the **Reachy app** band, press **Group talk**, **Interrupt**, **Free talk**, **Choir** or **Open**. The Reachy app opens on the **Group** tab. (This works with an OpenRouter key too.)
3. Under **Robots**, make sure each Reachy you want has **Included** ticked.
4. Write a **Topic** (or leave it empty). Pick the **Language** and **Minutes**.
5. Press **Get ready**. It connects the robots and checks the services.
6. Optional: press **Choir** (under **Robots**) so all the robots speak as one voice. It is used from the next start. Press it again to make them individuals.
7. Press a mode:
   - **Group talk**: the robots debate, and people can join in.
   - **Interrupt**: a person talks and the robots cut in.
   - **Free talk**: no topic, chat about anything.
8. To nudge the next line, type in the **Steer** box and press **Enter**.
9. Press **Stop** to end it. The robots say a closing line. **Stop now** ends it at once.
10. Press **Disconnect** before you change the order of the robots, **Included** or **Listens**.

A conversation is saved as a transcript on this laptop while the **Saving transcript** mark shows. To see the files: **Settings**, then **Conversations**, then **Open folder**. Turn **Save transcripts** off there if you do not want them.

## Update

When you open the app and a new version is out, it updates itself: the logo spins, it says **Please wait**, and the app opens again in about two minutes. Press **Not now** to skip it once. If you skipped it:

1. When a new version is out, **New version** and an **Update** button appear at the top. Or open **Settings**, then **About**, and press **Check for updates**.
2. Press **Update**. A PowerShell window opens, the app closes, and the new version opens. Robots stop for about a minute.

Your keys and settings stay. You can also run the install line again.

## Uninstall

In PowerShell, paste this and press Enter:

```powershell
& ([scriptblock]::Create((irm https://github.com/labbgulab-lab/robot-hub/releases/latest/download/install.ps1))) -Uninstall
```

This removes the app and the shortcuts, and keeps your keys, settings and logs. To delete those too, add `-RemoveData` at the end of the line.

## When something fails

| What you see | What to do |
|---|---|
| **No robots nearby**, or the chip shows another WiFi | Join the lab WiFi: **Open WiFi settings**. Turn off auto-join for other WiFi. |
| **VPN on** | Turn the VPN off. Robots may not show up with it on. |
| A card says **Not nearby** | Switch the robot off and on, then press **Scan**. |
| **Lost** | Press **Connect now**. If it stays, press **See log**. |
| **In use** | Another laptop is talking with the robot. Ask that person, or lab staff. |
| **Update needed** (Reachy) | Ask lab staff to update the robot. |
| **Needs password** (Furhat) | Press **Enter password**, or open **Settings**, **Furhat password**, **Change**. |
| **No key yet** or **No working key** | Press **Add a key**. In **Settings**, **Check** tests a key again. A key marked **Used up** has no credit: ask the lab. |
| **Couldn't start** | Press **See log**, then **Try again** on the card. |
| **Robot Hub stopped** | Press **Restart**. |
| Nothing else helps | Press **Logs** at the top, then **Save a report for the lab**. The report goes to your Downloads folder, with keys taken out. Send it to the lab. |
