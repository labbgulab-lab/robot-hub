from build_hub import *
import re

def cell(cap, html):
    return '<section><p class="cap">%s</p>%s</section>' % (cap, html)

sk = """<div class="card" aria-hidden="true">
      <div class="head"><div class="sk" style="width: 56px; height: 56px; border-radius: 12px;"></div><div class="who"><div class="sk" style="width: 90px; height: 16px;"></div><div class="sk" style="width: 60px; height: 14px;"></div></div></div>
      <div class="sk" style="height: 14px; width: 70%;"></div>
      <div class="sk" style="height: 44px; border-radius: 12px;"></div>
    </div>"""

def note(kind, icon, text, acts=""):
    a = '<div class="nacts">%s</div>' % acts if acts else ""
    return '<div class="note %s">%s<div>%s%s</div></div>' % (kind, ic(icon, 18), text, a)

SM = ' style="min-height: 34px; font-size: 13px; padding: 0 10px;"'
cells = [
 cell("Searching, first seconds", sk),
 cell("Not nearby", card(R, "reachy2", pill("off", "Not nearby"), "", "Last seen 12:40", "", btn("Connect", "quiet", "link", grow=True, disabled=True), "s-off")),
 cell("Connecting", card(R, "reachy6", pill("busy", "Connecting", spin=True), metric("ip", "10.0.4.26"), "Connecting", ai(DEF, [DEF], default=True), btn("Connecting…", "quiet", grow=True, disabled=True) + btn("Talk", "primary", grow=True, disabled=True), "s-busy")),
 cell("Connected, could not speak", card(F, "Furhat", pill("conn", "Connected"), metric("ip", "10.0.4.30"), "", note("warn", "micoff", "Connected, but it couldn't speak. Check its voice in Studio."), DISC + btn("Open Studio", "primary", "ext", grow=True), "s-conn", nameicon=ic("micoff", 16))),

 cell("Starting", card(P, "Pepper", pill("busy", "Starting 23 s", spin=True), metric("batt", "62%"), "Can take a couple of minutes", "", DISC + '<button class="btn btn-primary grow busy" type="button" disabled="{{yes}}">Starting… 23 s</button>', "s-busy")),
 cell("First Talk on a new Reachy", card(R, "reachy7", pill("busy", "Starting 1:40", spin=True), metric("ip", "10.0.4.27"), "Installing the Reachy app on the robot. First time only.", "", DISC + '<button class="btn btn-primary grow busy" type="button" disabled="{{yes}}">Starting… 1:40</button>', "s-busy")),
 cell("Start failed", card(P, "Pepper", pill("conn", "Connected"), metric("batt", "61%"), "", note("err", "alert", "Couldn't start: the dashboard didn't answer on port 8780.", '<a href="Logs.dc.html" style="font-size: 13px; font-weight: 600;">See log</a>'), DISC + btn("Try again", "primary", grow=True), "s-conn")),
 cell("Something else is using it", card(N, "NAO", pill("conn", "Connected"), metric("batt", "70%"), "", note("warn", "alert", "The microphone is in use by reachy1. Stop it first, or override.", btn("Override", "dark", extra=SM) + btn("Dismiss", "ghost", extra=SM)), DISC + naoapp(), "s-conn")),

 cell("About to stop", card(R, "reachy3", pill("warn", "Warning"), metric("ip", "10.0.4.23"), "Control loop errors (3). It usually stops about 7 s later.", "", DISC + btn("Open", "primary", grow=True), "s-warn")),
 cell("Old robot software", card(R, "reachy5", pill("warn", "Update needed"), metric("ip", "10.0.4.25"), "Daemon 1.9.2 is older than 1.10.0. Ask lab staff to update it.", "", btn("Connect", "quiet", "link", grow=True), "s-warn")),
 cell("Not answering yet", card(R, "reachy1", pill("warn", "Not answering"), metric("ip", "10.0.4.21"), "Not answering yet. Restarting?", "", DISC + btn("Open", "primary", grow=True), "s-warn")),
 cell("Lost, retrying", card(R, "reachy6", pill("lost", "Lost"), metric("ip", "10.0.4.26"), "Connect timed out. Trying again in 8 s.", "", DISC + btn("Connect now", "primary", "link", grow=True), "s-lost")),

 cell("Key that can't talk", card(R, "reachy3", pill("conn", "Connected"), metric("ip", "10.0.4.23"), "", ai("Lab ElevenLabs · ElevenLabs · …e01b", ["Lab ElevenLabs · ElevenLabs · …e01b"] + KEYS) + note("err", "key", "ElevenLabs is a voice only. Pick a Gemini or GPT key."), DISC + btn("Talk", "primary", grow=True, disabled=True), "s-conn")),
 cell("Pepper without a GPT key", card(P, "Pepper", pill("conn", "Connected"), metric("batt", "58%"), "", ai("No GPT key yet", ["No GPT key yet"], label="Speaks through (GPT)", default=True) + note("warn", "key", "The dashboard opens, but AI talk needs a GPT key.", btn("Add a key", "dark", href="Main.dc.html", extra=SM)), DISC + btn("Open dashboard", "primary", "ext", grow=True), "s-conn")),
 cell("In use by another laptop", card(R, "reachy4", pill("warn", "In use"), metric("ip", "10.0.4.24"), "Another laptop is talking with it.", "", btn("Talk", "primary", grow=True, disabled=True), "s-warn")),
 cell("Moved to a hotspot", card(R, "reachy8", pill("off", "Moved"), "", 'Now on "Lab Phone". Move this laptop there to see it.', "", "", "s-off")),

 cell("NAO moving", card(N, "NAO", pill("busy", "Sitting down", spin=True), metric("batt", "77%"), "", '<div class="postures"><button class="btn btn-quiet busy" type="button" disabled="{{yes}}">Sit</button><button class="btn btn-quiet" type="button" disabled="{{yes}}">Lie down</button><button class="btn btn-quiet" type="button" disabled="{{yes}}">Stand up</button></div>', DISC, "s-busy")),
 cell("NAO too hot", card(N, "NAO", pill("conn", "Connected"), metric("batt", "71%"), "", '<div class="postures"><button class="btn btn-quiet" type="button">Sit</button><button class="btn btn-quiet" type="button">Lie down</button><button class="btn btn-quiet" type="button">Stand up</button></div>' + note("err", "alert", "Not standing: left knee is 64&nbsp;°C, the limit is 60&nbsp;°C. Let it cool."), DISC, "s-conn")),
 cell("NAO stand, battery low", card(N, "NAO", pill("conn", "Connected"), metric("low", "12%"), "", '<div class="postures"><button class="btn btn-quiet" type="button">Sit</button><button class="btn btn-quiet" type="button">Lie down</button><button class="btn btn-arm" type="button">Confirm</button></div>' + note("warn", "battery", "Battery 12%. It may fall. Someone next to it? Confirm within 5 s."), DISC, "s-conn")),
 cell("NAO didn't finish", card(N, "NAO", pill("conn", "Connected"), metric("batt", "69%"), "", note("err", "alert", "NAO didn't reach Sit. Motors left on. Check on it."), DISC, "s-conn")),

 cell("Pepper key changed while running", card(P, "Pepper", pill("run", "Running"), metric("batt", "64%"), "Dashboard was already running", pepper_ai(PEP[2], sub="New key applies after Disconnect, then Open dashboard."), DISC + btn("Open dashboard", "primary", "ext", grow=True), "s-run")),
 cell("Reachy Mini Lite on USB", card(L, "Reachy Mini Lite", pill("conn", "Connected"), metric("usb", "USB"), "Daemon ready", "", DISC + btn("Open", "primary", "ext", grow=True), "s-conn")),
 cell("Needs setup", card(N, "NAO", pill("off", "Needs setup"), metric("ip", "10.0.4.40"), "Needs the Pepper and NAO kit", "", btn("Set up", "primary", href="Setup.dc.html", grow=True), "")),
 cell("Reachy blocked by another robot", card(R, "reachy3", pill("conn", "Connected"), metric("ip", "10.0.4.23"), "", note("warn", "alert", "The microphone is in use by NAO. Stop it first, or override.", btn("Override", "dark", extra=SM) + btn("Dismiss", "ghost", extra=SM)), DISC + btn("Talk", "primary", grow=True), "s-conn")),
 cell("NAO app, first start", card(N, "NAO", pill("busy", "Starting 0:40", spin=True), metric("batt", "80%"), "First run: downloading the speech model, about 140 MB", "", DISC + '<button class="btn btn-primary grow busy" type="button" disabled="{{yes}}">Starting… 0:40</button>', "s-busy")),
 cell("NAO app running", card(N, "NAO", pill("run", "Running"), metric("batt", "76%"), "NAO app on port 9600", '<div class="postures"><button class="btn btn-quiet" type="button">Sit</button><button class="btn btn-quiet" type="button">Lie down</button><button class="btn btn-quiet" type="button">Stand up</button></div>', DISC + naoapp("Open NAO app"), "s-run")),
 cell("NAO app can't start", card(N, "NAO", pill("conn", "Connected"), metric("batt", "75%"), "", note("err", "alert", "The NAO app needs its API keys. Ask lab staff.", '<a href="Logs.dc.html" style="font-size: 13px; font-weight: 600;">See log</a>'), DISC + naoapp("Try again"), "s-conn")),
 cell("NAO already there", card(N, "NAO", pill("conn", "Connected"), metric("batt", "74%"), "", '<div class="postures"><button class="btn btn-quiet" type="button">Sit</button><button class="btn btn-quiet" type="button">Lie down</button><button class="btn btn-quiet" type="button">Stand up</button></div>' + note("", "info", "Already sitting. Nothing moved."), DISC + naoapp(), "s-conn")),
 cell("Furhat needs its password", card(F, "Furhat", pill("warn", "Needs password"), metric("ip", "10.0.4.30"), "", note("warn", "key", "Furhat Studio asks for its password."), btn("Enter password", "primary", "key", grow=True), "s-warn")),
 cell("Windows blocks Pepper", card(P, "Pepper", pill("warn", "Blocked"), metric("batt", "62%"), "", note("warn", "alert", "Windows is blocking Pepper (port 8782)."), DISC + btn("Allow Pepper", "primary", grow=True), "s-warn")),
 cell("Battery low", card(N, "NAO", pill("conn", "Connected"), metric("low", "14%"), "", '<div class="postures"><button class="btn btn-quiet" type="button">Sit</button><button class="btn btn-quiet" type="button">Lie down</button><button class="btn btn-quiet" type="button">Stand up</button></div>' + note("warn", "battery", "Battery 14%. Plug it in soon."), DISC + naoapp(), "s-conn")),
 cell("Unknown robot", card("", "Robot", pill("off", "Not supported yet"), metric("ip", "10.0.4.51"), "", "", "", "s-off", morebtn=False)),
]

cs_css = """.app{padding:32px;box-sizing:border-box}
.cgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:24px 20px;align-items:start}
.sk{background:linear-gradient(90deg,#F4F1EC 0%,#EBE6DF 50%,#F4F1EC 100%);background-size:200% 100%;animation:sh 1.4s ease-in-out infinite;border-radius:8px}
@keyframes sh{from{background-position:100% 0}to{background-position:-100% 0}}
@media (prefers-reduced-motion:reduce){.sk{animation:none}}
.card{gap:12px}
"""
toasts = """<section style="grid-column: 1 / -1;"><p class="cap">Toasts</p><div style="display: flex; gap: 12px; flex-wrap: wrap;">
   <div class="toast" style="position: static; transform: none; background: #7F1D1D;">%sreachy3 lost: no answer within 6 s</div>
   <div class="toast" style="position: static; transform: none;">%sLaunched. Windows blocked the new window: press Open on the card.</div>
   <div class="toast" style="position: static; transform: none;">%sPepper will speak through Lab OpenAI</div>
   <div class="toast" style="position: static; transform: none;">%sKey added. Pick it on a robot's card.</div>
 </div></section>""" % (ic("alert", 18), ic("info", 18), ic("check", 18), ic("check", 18))
cs = '<div class="app"><div class="cgrid">\n%s\n%s\n</div></div>' % ("\n".join(cells), toasts)
write("CardStates.dc.html", page("Every robot card state", cs, "renderVals() { return { yes: true }; }", width=1640, height=2950, extra_css=cs_css))

# ---------------------------------------------------------------- Settings
def keyrow(prov, label, tail, pl, used, armed=False, extra=""):
    rm = btn("Press again", "stop", extra=' style="min-height: 36px; font-size: 14px; padding: 0 12px;"') if armed else btn("Remove", "ghost", "trash", extra=' style="min-height: 36px; font-size: 14px; padding: 0 12px;"')
    return """<div class="row">
          <span class="prov">%s</span>
          <div class="rowmain"><p class="rowtitle">%s <span class="mono">…%s</span>%s</p><p class="muted small" style="margin: 0;">%s</p></div>
          %s
          <button class="btn btn-ghost btn-sm" type="button">Check</button>
          %s
        </div>""" % (prov, label, tail, extra, used, pl, rm)

set_body = """<div class="app">
  <header class="top">
    <a class="btn btn-ghost btn-sm" href="Hub.dc.html">%sRobots</a>
    <span class="spacer"></span>
    <img class="logo" src="img/labalab-logo.png" alt="LabaLab">
  </header>
  <main class="main" style="max-width: 820px; gap: 28px;">
    <h1 class="h1">Settings</h1>

    <section class="sec" aria-labelledby="k">
      <div class="sechd"><h2 id="k" class="h2" style="flex: 1 1 auto;">Keys</h2><span class="muted small">On this laptop only. Pick one per robot on its card.</span></div>
      <div class="panel">
        %s
        %s
        %s
        %s
        <div class="row" style="background: #FAF8F5; align-items: flex-end;">
          <div class="field" style="flex: 0 0 170px;"><label for="prov">Service</label><select id="prov" class="select"><option>Find it from the key</option><option>Gemini</option><option>OpenAI (GPT)</option><option>OpenRouter</option><option>ElevenLabs</option><option>Qwen</option></select></div>
          <div class="field" style="flex: 0 0 170px;"><label for="lab">Name</label><input id="lab" class="input" type="text" placeholder="Lab Gemini 2"></div>
          <div class="field" style="flex: 1 1 200px;"><label for="kv">Key</label><input id="kv" class="input" type="password" placeholder="Paste the key"></div>
          <button class="btn btn-primary" type="button" style="min-height: 40px;">%sAdd</button>
        </div>
      </div>
    </section>

    <section class="sec" aria-labelledby="r">
      <h2 id="r" class="h2">Robots</h2>
      <div class="panel">
        <div class="row"><div class="rowmain"><p class="rowtitle">Auto-connect</p><p class="muted small" style="margin: 0;">Connect each robot when it shows up</p></div><button class="switch on" type="button" role="switch" aria-checked="true" aria-label="Auto-connect"><span></span></button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Furhat password</p><p class="muted small" style="margin: 0;">For Furhat Studio</p></div><span class="pill p-run"><span class="dot"></span>Works</span><button class="btn btn-ghost btn-sm" type="button">Change</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Lab WiFi</p><p class="muted small" style="margin: 0;">HOT-WiFi, open</p></div><a class="btn btn-ghost btn-sm" href="Network.dc.html">Network help</a></div>
      </div>
    </section>

    <section class="sec" aria-labelledby="x">
      <h2 id="x" class="h2">Extra robot software</h2>
      <div class="panel">
        <div class="row"><div class="rowmain"><p class="rowtitle">Pepper and NAO kit</p><p class="muted small" style="margin: 0;">2.8.7.4</p></div><span class="pill p-run"><span class="dot"></span>Ready</span><button class="btn btn-ghost btn-sm" type="button">Check</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Reachy Mini app (USB Reachy)</p></div><span class="pill p-off"><span class="dot"></span>Not set up</span><a class="btn btn-quiet btn-sm" href="Setup.dc.html">Set up</a></div>
      </div>
    </section>

    <section class="sec" aria-labelledby="c">
      <h2 id="c" class="h2">Conversations</h2>
      <div class="panel">
        <div class="row"><div class="rowmain"><p class="rowtitle">Save transcripts</p><p class="muted small" style="margin: 0;">On this laptop only</p></div><button class="switch on" type="button" role="switch" aria-checked="true" aria-label="Save transcripts"><span></span></button><button class="btn btn-ghost btn-sm" type="button">Open folder</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Demo on a phone hotspot</p></div><a class="btn btn-ghost btn-sm" href="Hotspot.dc.html">Plan</a></div>
      </div>
    </section>

    <section class="sec" aria-labelledby="s">
      <div class="sechd"><h2 id="s" class="h2" style="flex: 1 1 auto;">Lab staff tools</h2><button class="switch on" type="button" role="switch" aria-checked="true" aria-label="Show lab staff tools"><span></span></button></div>
      <div class="panel">
        <div class="row"><div class="rowmain"><p class="rowtitle">Robot files</p><p class="muted small" style="margin: 0;">Shared with the lab on GitHub</p></div><a class="btn btn-quiet btn-sm" href="Files.dc.html">Open</a></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">New Reachy</p><p class="muted small" style="margin: 0;">First WiFi, name, robot software</p></div><button class="btn btn-quiet btn-sm" type="button">Bring up</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Add WiFi</p><p class="muted small" style="margin: 0;">In each robot's details</p></div><span class="pill p-run"><span class="dot"></span>Shown</span></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">NAO app</p><p class="muted small" style="margin: 0;">Start button on the NAO card</p></div><span class="pill p-run"><span class="dot"></span>Shown</span></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Check this laptop</p><p class="muted small" style="margin: 0;">Python, kit, ports, firewall</p></div><button class="btn btn-quiet btn-sm" type="button">Run</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">In use</p><p class="muted small" style="margin: 0;">Microphone: reachy1 · Port 8780: Pepper</p></div></div>
      </div>
    </section>

    <section class="sec" aria-labelledby="a">
      <h2 id="a" class="h2">About</h2>
      <div class="panel">
        <div class="row"><div class="rowmain"><p class="rowtitle">LabaLab Robot Hub 1.0</p><p class="muted small" style="margin: 0;">Up to date</p></div><button class="btn btn-ghost btn-sm" type="button">Check for updates</button></div>
        <div class="row"><div class="rowmain"><p class="rowtitle">Quit Robot Hub</p><p class="muted small" style="margin: 0;">Stops all robots</p></div><button class="btn btn-ghost btn-sm" type="button" style="color: #B91C1C;">Quit</button></div>
      </div>
    </section>
  </main>
</div>""" % (ic("back", 18),
   keyrow("Gemini", "Lab Gemini", "a91f", pill("run", "Works"), "Used by reachy1, Furhat · Default"),
   keyrow("GPT", "Lab OpenAI", "5b12", pill("run", "Works"), "Used by Pepper"),
   keyrow("OpenRouter", "Lab OpenRouter", "7c20", pill("run", "$4.20 left"), "Not used yet", armed=True, extra=' <span class="tag">Groups only</span>'),
   keyrow("ElevenLabs", "Lab ElevenLabs", "e01b", pill("warn", "Used up"), "Voice for Pepper", extra=' <span class="tag">Voice only</span>'),
   ic("plus", 18))

write("Settings.dc.html", page("Settings", set_body, height=1900, mono=True))

# ---------------------------------------------------------------- Robot files (lab staff)
def frow(name, meta, keysel, action, binbtn):
    return """<div class="row">
          <span style="width: 36px; height: 36px; border-radius: 10px; background: #F4F1EC; display: flex; align-items: center; justify-content: center; color: #6B635A;">%s</span>
          <div class="rowmain"><p class="rowtitle">%s</p><p class="muted small" style="margin: 0;">%s</p></div>
          %s%s%s
        </div>""" % (ic("file", 18), name, meta, keysel, action, binbtn)

def ksel(opts):
    return '<select class="select sm" aria-label="Key to put in">%s</select>' % "".join("<option>%s</option>" % o for o in opts)

BIN = '<button class="btn btn-ghost btn-sm btn-icon" type="button" aria-label="Delete for everyone">%s</button>' % ic("trash", 18)
files_body = """<div class="app">
  <header class="top">
    <a class="btn btn-ghost btn-sm" href="Settings.dc.html">%sSettings</a>
    <span class="spacer"></span>
    <img class="logo" src="img/labalab-logo.png" alt="LabaLab">
  </header>
  <main class="main" style="max-width: 960px;">
    <div class="pagehead"><h1 class="h1">Robot files</h1><span class="tag tag-dark">Lab staff</span></div>
    <p class="muted" style="margin: -12px 0 0;">Shared with the lab on GitHub. Keys are taken out before upload.</p>
    <div style="display: flex; gap: 8px; align-items: center;">
      <select class="select" style="width: 260px;" aria-label="Robot"><option>Furhat (3)</option><option selected>Reachy Mini (4)</option><option>Reachy Mini Lite (0)</option><option>NAO (2)</option><option>Pepper (1)</option></select>
      <button class="btn btn-ghost btn-sm btn-icon" type="button" aria-label="Reload the list">%s</button>
    </div>
    <div class="panel">
      %s
      %s
      %s
      %s
    </div>

    <section class="sec">
      <h2 class="h2">Upload</h2>
      <div class="panel"><div class="row" style="align-items: center;">
        <span style="flex: 1 1 auto; display: flex; align-items: center; gap: 10px; height: 44px; padding: 0 12px; border: 1px dashed #D6CFC5; border-radius: 12px;">%s<span>persona-pack.zip</span><span class="muted small">2.1 MB</span><span class="spacer"></span><button class="btn btn-ghost btn-sm" type="button">Choose</button></span>
        %s
      </div></div>
      <p class="note warn">%spersona-pack.zip is already shared. Press Upload again to replace it for everyone.</p>
      <p class="note">%sChecking it for keys, then sending it to GitHub… 12 s</p>
    </section>

    <section class="sec">
      <h2 class="h2">Other states</h2>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
        <div class="panel"><div class="row" style="justify-content: center; padding: 24px 16px;"><span class="muted">No files for Reachy Mini Lite yet. Upload the first one.</span></div></div>
        <div class="note err">%s<div>Couldn't load the files: GitHub didn't answer.<div class="nacts"><button class="btn btn-dark" type="button" style="min-height: 32px; font-size: 13px; padding: 0 10px;">Reload</button></div></div></div>
        <div class="note err">%s<div>bundle.jar has a key in compiled code. Rebuild it without the key, then upload.</div></div>
        <div class="note err">%s<div>Uploading needs a GitHub sign-in with write access.</div></div>
      </div>
    </section>
  </main>
  <div class="toast" role="status">%sgroup-demo.json has your key in it. Keep that copy to yourself.</div>
</div>""" % (ic("back", 18), ic("refresh", 18),
   frow("group-demo.json", "4 KB · by labbgulab-lab · 3 Nov · needs a Gemini key", ksel(["With Lab Gemini · …a91f", "Without a key"]), btn("Download", "quiet", "download", extra=' style="min-height: 36px; font-size: 14px;"'), BIN),
   frow("persona-pack.zip", "2.1 MB · by labbgulab-lab · 28 Oct · needs a Gemini key", ksel(["With Lab Gemini · …a91f", "Without a key"]), '<button class="btn btn-quiet" type="button" aria-label="Downloading, 42%, press to cancel" style="min-height: 36px; font-size: 14px; min-width: 112px; font-variant-numeric: tabular-nums; background: linear-gradient(90deg, #FDD9A0 42%, #F4F1EC 42%);">42%</button>', BIN),
   frow("video-bank-clips.zip", "380 MB · by labbgulab-lab · 19 Oct", "", btn("Download", "quiet", "download", extra=' style="min-height: 36px; font-size: 14px;"'), BIN),
   frow("old-voices.json", "2 KB · by labbgulab-lab · 2 Oct", "", btn("Download", "quiet", "download", extra=' style="min-height: 36px; font-size: 14px;"'), btn("Press again", "stop", extra=' style="min-height: 36px; font-size: 14px;"')),
   ic("upload", 18), btn("Upload", "primary", "upload"), ic("alert", 18), '<span class="spin" style="margin-top: 3px;" aria-hidden="true"></span>', ic("alert", 18), ic("key", 18), ic("alert", 18), ic("check", 18))

write("Files.dc.html", page("Robot files", files_body, "renderVals() { return { yes: true }; }", height=1180))

# ---------------------------------------------------------------- Closed without a key
NOKEY = "No key yet"
kl = [
  card(R, "reachy1", pill("conn", "Connected"), metric("ip", "10.0.4.21"), "Ready", ai(NOKEY, [NOKEY], default=True) + '<p class="sub"><a href="Main.dc.html">Add a key</a></p>', DISC + btn("Talk", "primary", grow=True, disabled=True), "s-conn"),
  card(R, "reachy3", pill("near", "Available"), metric("ip", "10.0.4.23"), "Found on HOT-WiFi", ai(NOKEY, [NOKEY], default=True) + '<p class="sub"><a href="Main.dc.html">Add a key</a></p>', btn("Connect", "quiet", "link", grow=True) + btn("Talk", "primary", grow=True, disabled=True), ""),
  card(F, "Furhat", pill("conn", "Connected"), metric("ip", "10.0.4.30"), "Studio running", ai(NOKEY, [NOKEY], default=True) + '<p class="sub"><a href="Main.dc.html">Add a key</a></p>', DISC + btn("Open Studio", "primary", "ext", grow=True), "s-conn"),
]
kl_body = """<div class="app">
  %s
  <div class="warnbar" role="status">%s<span><b>No key yet.</b> Robots can't talk.</span><span class="spacer"></span><a class="btn btn-bar" href="Main.dc.html">Add a key</a></div>
  <main class="main">
    <div class="pagehead"><h1 class="h1">Robots</h1><div class="counts"><span><b>3</b> of 3 nearby</span><span><span class="d" style="background: #1D4ED8;"></span><b>2</b> connected</span></div></div>
    <div class="grid">%s</div>
  </main>
  <div class="toast" role="status">%sAdd a key any time in Settings.</div>
</div>""" % (topbar(), ic("key", 18), "\n".join(kl), ic("info", 18))
write("KeyLater.dc.html", page("Closed without a key", kl_body, "renderVals() { return { yes: true }; }"))

# ---------------------------------------------------------------- new top bar on Logs and NoRobots
for name, net in (("Logs.dc.html", "ok"), ("NoRobots.dc.html", "bad")):
    p = os.path.join(ROOT, name)
    s = open(p, encoding="utf-8").read()
    s = re.sub(r'<header class="top">.*?</header>', lambda m: topbar(net=net), s, count=1, flags=re.S)
    extra = """
.top{gap:6px;padding:0 20px 0 24px}
.chip{color:#1C1917;text-decoration:none;font-variant-numeric:tabular-nums}
.chip .cdot{width:7px;height:7px;border-radius:50%;background:#15803D}
.chip-warn{background:#FFF1D6;color:#8A3B00}.chip-warn .cdot{background:#8A3B00}
.tgl{display:inline-flex;align-items:center;gap:8px;font-size:14px;font-weight:500;padding:0 8px;white-space:nowrap}
.switch{position:relative;width:40px;height:24px;border-radius:999px;border:0;background:#D6CFC5;cursor:pointer;flex-shrink:0;padding:0}
.switch span{position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#FFFFFF;box-shadow:0 1px 2px rgba(0,0,0,.2)}
.switch.on{background:#1C1917}.switch.on span{transform:translateX(16px)}
.live{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:#6B635A;padding:0 8px}
.ldot{width:8px;height:8px;border-radius:50%;background:#15803D}
.btn-sm{min-height:36px;font-size:14px;padding:0 12px;border-radius:10px}
.btn-sm.btn-icon{width:36px;padding:0}
.logo{margin-right:8px}
a.btn{text-decoration:none;color:#1C1917}
.muted{color:#6B635A}
"""
    if "/* topbar v2 */" not in s:
        s = s.replace("</style>", "/* topbar v2 */" + extra + "</style>", 1)
    if name == "Logs.dc.html":
        s = s.replace('<a class="btn btn-ghost btn-sm" href="Logs.dc.html">', '<a class="btn btn-ghost btn-sm" href="Hub.dc.html" style="background: #F4F1EC;" aria-pressed="true">', 1)
    if name == "NoRobots.dc.html":
        s = s.replace('<a href="#hotspot">How</a>', '<a href="Hotspot.dc.html">How</a>').replace('href="#wifi-settings"', 'href="Network.dc.html"')
    open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("topbar", name)
