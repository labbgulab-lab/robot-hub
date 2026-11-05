from build_ra import *

def cell(cap, html, span=1):
    st = ' style="grid-column: span %d;"' % span if span > 1 else ""
    return '<section%s><p class="cap">%s</p>%s</section>' % (st, cap, html)

def n(kind, icon, text, acts=""):
    a = '<div class="nacts">%s</div>' % acts if acts else ""
    return '<div class="note %s">%s<div>%s%s</div></div>' % (kind, ic(icon, 18), text, a)

SM = ' style="min-height: 32px; font-size: 13px; padding: 0 10px;"'

# ====================================================================== Dialogs: Groups and Copy
def cb(label, real, on, extra=""):
    return '<label class="check" style="align-items: center;"><input type="checkbox"%s%s>%s <span class="muted" style="font-size: 13px;">%s</span></label>' % (" checked" if on else "", extra, label, real)

groups = """<div class="modal" role="dialog" aria-label="Groups" style="left: 60px; top: 110px; width: 700px;">
    <div style="display: flex; align-items: center;"><h2 style="flex: 1 1 auto;">Groups</h2><button class="btn btn-ghost btn-sm btn-icon" type="button" aria-label="Close">%s</button></div>
    <p class="sub" style="font-size: 14px; line-height: 20px;">Talk together: one voice, the first robot's voice and settings, under the group's name. Move together: the same gestures. Used from the next Start.</p>
    <div class="pnl" style="border-left: 4px solid #2563EB;">
      <div style="display: flex; gap: 8px;"><input class="input" type="text" value="Group 1" maxlength="30" aria-label="Group name" style="flex: 1 1 auto;">%s<button class="ib" type="button" aria-label="Remove this group" style="width: 40px; height: 40px;">%s</button></div>
      <div class="checks3" style="gap: 18px;">%s%s%s</div>
      <p class="sub">Moves together. Each says its own lines.</p>
    </div>
    <div class="pnl" style="border-left: 4px solid #C2410C;">
      <div style="display: flex; gap: 8px;"><input class="input" type="text" value="Team B" maxlength="30" aria-label="Group name" style="flex: 1 1 auto;">%s<button class="ib" type="button" aria-label="Remove this group" style="width: 40px; height: 40px;">%s</button></div>
      <div class="checks3" style="gap: 18px;">%s%s%s</div>
      <p class="sub" style="color: #8A3B00;">Needs two included robots to count. It would talk in Reachy Mini 3's voice and settings.</p>
    </div>
    <div style="display: flex; gap: 8px; flex-wrap: wrap;">%s%s%s<span class="spacer"></span>%s</div>
  </div>""" % (ic("x", 18),
    sel(["Talk and move together", "Talk together, each moves its own way", "Move together, each says its own lines"], "Move together, each says its own lines", aria="What it does together", style="width: 300px;"), ic("x", 16),
    cb("Max", "reachy1", True), cb("Leo", "reachy3", True), cb("Reachy Mini 3", "reachy6 · taken by Team B", False),
    sel(["Talk and move together", "Talk together, each moves its own way", "Move together, each says its own lines"], "Talk and move together", aria="What it does together", style="width: 300px;"), ic("x", 16),
    cb("Max", "reachy1 · taken", False), cb("Leo", "reachy3 · taken", False), cb("Reachy Mini 3", "reachy6", True),
    btn("Add group", "quiet", "plus", extra=SM), btn("Everyone: one Choir", "quiet", "users", extra=SM), btn("No groups", "ghost", extra=SM), btn("Done", "dark", extra=' style="min-height: 36px;"'))

copyd = """<div class="modal" role="dialog" aria-label="Copy settings" style="left: 820px; top: 110px; width: 520px;">
    <h2>Copy Max's settings</h2>
    <p class="fl2" style="margin: 0;">To</p>
    <div class="checks3" style="gap: 18px;">%s%s</div>
    <p class="fl2" style="margin: 0;">What</p>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px;">%s</div>
    <p class="sub">"The voice itself" copies the saved voice for every service.</p>
    <div style="display: flex; gap: 8px; justify-content: flex-end;">%s%s</div>
  </div>""" % (cb("Leo", "reachy3", True), cb("Reachy Mini 3", "reachy6", True),
    "".join(cb(a, "", b) for a, b in [("Interrupting (0-5)", True), ("Voice service", True), ("The voice itself", False), ("Writer", True), ("Gestures", True), ("Camera", True), ("Volume", True), ("Personality", False)]),
    btn("Cancel", "ghost", extra=' style="min-height: 38px;"'), btn("Copy", "dark", "copy", extra=' style="min-height: 38px;"'))

dlg = """<div class="app">
  %s
  <main class="dim" style="padding: 14px 18px;"><div class="ph" style="height: 200px;"></div><div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px;"><div class="ph" style="height: 560px;"></div><div class="ph" style="height: 560px;"></div><div class="ph" style="height: 560px;"></div></div></main>
  <div class="scrim" aria-hidden="true"></div>
  %s
  %s
</div>""" % (head("table"), groups, copyd)
write("RADialogs.dc.html", page("reachy_app: Groups and Copy dialogs", dlg, width=1400, height=900, extra_css=RA_CSS, mono=True))

# ====================================================================== Wizard of Oz: operator board
SHOW_CSS = r"""
.dark{background:#171412;color:#EDE8E1}
.dark .pnl{background:#221E1B;border-color:#35302B}
.dark .pnlh h2,.dark .pnlh h3{color:#A79F95}
.dark .sub{color:#A79F95}
.cue{position:relative;display:flex;flex-direction:column;gap:6px;text-align:left;background:#2A2521;border:1px solid #3A342E;border-radius:12px;padding:10px 12px;color:#EDE8E1;font:inherit;cursor:pointer;min-height:96px;box-sizing:border-box}
.cue:hover{background:#312B26}
.cue.next{outline:2px solid #FDB241;outline-offset:2px}
.cue.motion{background:#201C19;border-style:dashed}
.cue .ch{display:flex;align-items:center;gap:8px}
.cue .k{min-width:22px;height:22px;border-radius:6px;background:#EDE8E1;color:#171412;font-weight:700;font-size:12px;display:inline-flex;align-items:center;justify-content:center}
.cue .lb{font-weight:600;font-size:14px;flex:1 1 auto}
.cue .du{font-size:12px;color:#A79F95;font-variant-numeric:tabular-nums}
.cue .tx{font-size:14px;line-height:20px;color:#D8D1C7}
.cue .tags{display:flex;gap:6px;flex-wrap:wrap}
.cue .tg{font-size:11.5px;font-weight:600;padding:0 6px;border-radius:5px;background:#3A342E;color:#D8D1C7;line-height:18px}
.cue .tg.bad{background:#5A1D1D;color:#FFB4B4}
.cue .ed{position:absolute;right:8px;bottom:8px;font-size:12px;color:#A79F95;background:none;border:0;font:inherit;cursor:pointer;text-decoration:underline}
.addcue{border:1px dashed #4A433C;border-radius:12px;background:transparent;color:#A79F95;font:inherit;font-size:14px;min-height:96px;cursor:pointer}
.now{display:grid;grid-template-columns:auto 1fr auto;gap:16px;align-items:center}
.nowbar{height:6px;border-radius:999px;background:#3A342E;overflow:hidden;grid-column:1 / -1}
.nowbar span{display:block;height:100%;background:#7DD3FC}
.dk{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 5px;border-radius:5px;border:1px solid #4A433C;font-size:11.5px;font-weight:600;color:#D8D1C7}
.say{background:#2A2521;border:1px solid #4A433C;color:#EDE8E1}
.hist{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px;font-size:14px}
.hist li{display:flex;gap:10px;align-items:center}
.hist .tm{color:#A79F95;font-variant-numeric:tabular-nums;font-size:12.5px}
.hist button{margin-left:auto;background:none;border:0;color:#FDB241;font:inherit;font-size:13px;font-weight:600;cursor:pointer}
"""

def cue(k, label, dur, text, motion=None, next_=False, motion_only=False, noaudio=False):
    tags = ""
    if motion: tags += '<span class="tg">%s</span>' % motion
    if motion_only: tags += '<span class="tg">motion only</span>'
    if noaudio: tags += '<span class="tg bad">no audio: press Rebuild</span>'
    return '<button class="cue%s%s" type="button"><span class="ch"><span class="k">%s</span><span class="lb">%s</span><span class="du">%s</span></span>%s<span class="tags">%s</span><span class="ed" role="button">edit</span></button>' % (
        " next" if next_ else "", " motion" if motion_only else "", k, label, dur, '<span class="tx">%s</span>' % text if text else "", tags)

def section(title, cues):
    return '<section class="pnl" style="gap: 10px;"><div class="pnlh"><h2>%s</h2><span class="sub">%d cues</span></div><div style="display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 10px;">%s<button class="addcue" type="button">+ add cue</button></div></section>' % (title, len(cues), "".join(cues))

show = """<div class="app">
  %s
  <main class="dark" style="flex: 1 1 auto; display: grid; grid-template-columns: minmax(0,1fr) 400px; gap: 14px; padding: 14px 18px 18px; box-sizing: border-box;">
    <div style="display: flex; flex-direction: column; gap: 12px; min-width: 0;">
      <section class="pnl" style="gap: 10px;">
        <div class="pnlh" style="gap: 10px;">
          <img src="img/%s" alt="" style="width: 28px; height: 28px; border-radius: 7px;"><b style="color: #EDE8E1;">reachy3</b>
          <span class="pill p-run" style="height: 24px;"><span class="dot"></span>In conversation</span>
          <span class="pill p-warn" style="height: 24px;">Audio cues cut into the conversation</span>
          <span class="spacer"></span>
          <button class="btn btn-sm" type="button" style="background: #2A2521; color: #EDE8E1;">%sReload script</button>
          <button class="btn btn-sm" type="button" style="background: #2A2521; color: #EDE8E1;" title="Re-record any line whose text changed">%sRebuild audio</button>
          <button class="btn" type="button" style="background: #DC2626; color: #FFFFFF; min-height: 40px;">%sSTOP <span class="dk" style="border-color: rgba(255,255,255,.5); color: #FFFFFF;">Esc</span></button>
        </div>
        <div class="now">
          <span style="font-size: 12px; font-weight: 700; letter-spacing: .06em; color: #A79F95;">NOW</span>
          <span style="font-size: 18px; font-weight: 700;">Glass trick, part 2</span>
          <span style="font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; color: #7DD3FC;">2.4 s</span>
          <div class="nowbar"><span style="width: 62%%;"></span></div>
          <p style="grid-column: 1 / -1; margin: 0; font-size: 18px; line-height: 26px;">Pull the paper away slowly. The air holds the water in.</p>
        </div>
        <p class="sub"><span class="dk">Space</span> fires the outlined cue and moves on · <span class="dk">↑</span> <span class="dk">↓</span> move without firing · <span class="dk">Esc</span> stop · letter keys fire directly</p>
      </section>
      %s
      %s
      %s
    </div>
    <div style="display: flex; flex-direction: column; gap: 12px;">
      <section class="pnl">
        <div class="pnlh"><h2>Say anything</h2></div>
        <div class="steer"><input class="input say" type="text" placeholder="Type a line, press Enter" aria-label="Say"><button class="btn btn-primary btn-sm" type="button">Say</button></div>
        <p class="sub">Reachy says it in its own voice, then goes back to breathing.</p>
        <div class="pnlh" style="margin-top: 6px;"><h3>Quick saves</h3></div>
        <div style="display: flex; flex-direction: column; gap: 6px;">
          <button class="cue" type="button" style="min-height: 0;"><span class="ch"><span class="k">S</span><span class="lb">Sorry, can you say that again?</span></span></button>
          <button class="cue" type="button" style="min-height: 0;"><span class="ch"><span class="k">D</span><span class="lb">Let me think about that for a second.</span></span></button>
          <button class="cue" type="button" style="min-height: 0;"><span class="ch"><span class="k">F</span><span class="lb">That is a great question!</span></span></button>
        </div>
      </section>
      <section class="pnl" style="flex: 1 1 auto;">
        <div class="pnlh"><h2>Said</h2></div>
        <ul class="hist">
          <li><span class="tm">14:21</span><span>Glass trick, part 2</span><button type="button">Again</button></li>
          <li><span class="tm">14:20</span><span>Do you have a glass of water?</span><button type="button">Again</button></li>
          <li><span class="tm">14:19</span><span>(nod)</span><button type="button">Again</button></li>
          <li><span class="tm">14:18</span><span>Hi, I'm Reachy. What's your name?</span><button type="button">Again</button></li>
        </ul>
      </section>
    </div>
  </main>
</div>""" % (head("woz"), R, ic("refresh", 16), ic("refresh", 16), ic("stop", 18),
    section("Opening", [cue("1", "Hello", "2.1s", "Hi, I'm Reachy. What's your name?", "happy"), cue("2", "Nice to meet you", "1.8s", "Nice to meet you! Want to see a trick?", "dance: groovy"), cue("N", "Nod", "", "", "nod", motion_only=True)]),
    section("Topic", [cue("G", "Glass trick, part 1", "3.4s", "Fill the glass to the top and put the paper on it.", "look down"), cue("H", "Glass trick, part 2", "2.6s", "Pull the paper away slowly. The air holds the water in.", "look up"), cue("J", "Why it works", "", "Air presses on everything, about one kilo on each fingernail.", None, next_=True, noaudio=True)]),
    section("Closing", [cue("B", "Goodbye", "1.6s", "Thank you for playing with me. Bye!", "wave"), cue("K", "Sleep", "", "", "sleep", motion_only=True)]))
write("RAShow.dc.html", page("reachy_app: Wizard of Oz", show, width=1600, height=1080, extra_css=RA_CSS + SHOW_CSS, mono=True))

# ====================================================================== Talk states + cue editor
editor = """<div class="pnl" style="box-shadow: 0 24px 64px -16px rgba(28,25,23,.35); gap: 12px;">
      <div class="pnlh"><h2 style="flex: 1 1 auto; font-size: 17px; text-transform: none; letter-spacing: 0; color: #1C1917;">Edit: Why it works</h2>%s</div>
      <div class="field"><label>Name, on the card</label><input class="input" type="text" value="Why it works"></div>
      <div class="field"><label>What Reachy says <span class="muted">(empty: motion only)</span></label><textarea class="ta" rows="3" dir="auto">Air presses on everything, about one kilo on each fingernail.</textarea><span class="sub">Changing it re-records the line. Up to 600 characters.</span></div>
      <div style="display: grid; grid-template-columns: 90px 1fr 1fr; gap: 10px;">
        <div class="field"><label>Hotkey</label><input class="input" type="text" value="J" maxlength="1"></div>
        <div class="field"><label>Motion</label>%s</div>
        <div class="field"><label>Which</label>%s</div>
      </div>
      <div class="field"><label>Cue line for the presenter <span class="muted">(printed, not spoken)</span></label><input class="input" type="text" value="Ask: why doesn't the water fall?"></div>
      <p class="note err" style="padding: 8px 10px;">%sHotkey "J" is already used by "Jump". Hotkeys must differ from every cue and quick save (S, D, F).</p>
      <div style="display: flex; gap: 8px; align-items: center;"><span class="sub">Ctrl+Enter saves · Esc closes</span><span class="spacer"></span>%s%s</div>
    </div>""" % (btn("Delete", "stop", "trash", extra=SM), sel(["none", "emotion", "dance", "head"], "head", aria="Motion"), sel(["left", "right", "up", "down", "front"], "up", aria="Which"),
                 ic("alert", 16), btn("Cancel", "ghost", extra=' style="min-height: 38px;"'), btn("Save", "dark", extra=' style="min-height: 38px;"'))

wifi_rc = """<div class="pnl">
      <div class="field"><label>Hotspot name</label><input class="input" type="text" value="Lab Phone"></div>
      <div class="field"><label>Password</label><input class="input" type="password" value="password1"></div>
      <div style="display: flex;">%s</div>
      %s
      <p class="sub" style="font-size: 13.5px;">Knows: <b style="color: #1C1917;">HOT-WiFi</b> (connected now) · Lab Phone · reachy-mini-ap (its own setup network)</p>
    </div>""" % (btn("Save on robot", "dark", extra=' style="min-height: 36px;"'), n("ok", "check", '"Lab Phone" saved. It stays on HOT-WiFi for now; turn HOT-WiFi off and it moves over within a minute.'))

ts_cells = [
 cell("Cue editor (Wizard of Oz)", editor, span=2),
 cell("Start refused", '<div class="pnl"><div class="frow"><label>Brain</label>%s</div>%s</div>' % (sel(["OpenAI GPT-Live-1 (no key)"], aria="Brain"), n("err", "key", "Couldn't start: GPT-Live-1 needs an OpenAI key. Add one in Settings, or pick Gemini."))),
 cell("ElevenLabs with GPT-Live", '<div class="pnl"><div class="srow"><span class="grow">ElevenLabs v4 voice</span>%s</div><div class="frow"><label>EL voice</label>%s</div>%s%s</div>' % (sw(True, "ElevenLabs"), sel(["Daniel (English)", "First voice in the account"], aria="ElevenLabs voice"), n("err", "alert", "ElevenLabs stutters with GPT-Live-1. Use it with Gemini."), n("warn", "info", "Hebrew is untested on GPT-Live. Its gestures come a moment late."))),
 cell("System stopped, with the reason", '<div class="pnl"><div class="srow"><span class="pill p-off"><span class="dot"></span>Stopped</span></div>%s<div style="display: flex; gap: 8px;">%s%s</div></div>' % (n("err", "alert", "Couldn't start: microphone unavailable on the robot."), btn("Start system", "primary", "play", extra=' style="min-height: 36px;"'), btn("See log", "ghost", extra=' style="min-height: 36px;"'))),
 cell("Robot lost", '<div class="pnl"><div class="srow"><span class="pill p-lost"><span class="dot"></span>Disconnected</span><span class="sub">Daemon unreachable · 2 missed checks</span></div>%s</div>' % n("warn", "wifi", "reachy3 stopped answering. It reconnects by itself when it's back.")),
 cell("Conversation ended", '<div class="pnl">%s<p class="sub">Session 1105-1412-a3 · 9 turns · answers 1.1 s on average · 1 aborted</p>%s</div>' % (n("ok", "check", "Conversation ended: the person said goodbye."), btn("Start conversation", "primary", "play", extra=' style="min-height: 40px;"'))),
 cell("Character states", '<div class="pnl" style="gap: 8px;"><p class="sub">Switched on, but nothing written yet</p><p class="sub" style="color: #15803D; font-weight: 600;">In character: Custom</p><div style="display: flex;"><span class="cnt" style="color: #B91C1C; font-weight: 600;">1,620 / 1,500</span></div>%s%s</div>' % (n("err", "alert", "That character is 1,620 characters. The limit is 1,500."), n("ok", "check", "Back to the base persona. Your text is kept."))),
 cell("Volume", '<div class="pnl"><span class="rng">%s<input type="range" min="0" max="150" value="140" aria-label="Volume"><b style="color: #8A3B00;">140%%</b></span><p class="sub">Above 100: speaker at max, voice boosted.</p>%s</div>' % (ic("vol", 16), n("err", "alert", "The robot didn't take the volume change."))),
 cell("Camera off here", '<div class="pnl"><div class="srow"><span class="grow">Camera vision</span>%s</div><p class="sub" style="color: #8A3B00;">No camera here: the app isn\'t running on the robot.</p></div>' % sw(True, "Camera vision")),
 cell("Robot is at the Group", '<div class="pnl">%s</div>' % n("warn", "users", "reachy3 is in a Group conversation. Disconnect it there first.", btn("Go to Group", "dark", href="RATableLive.dc.html", extra=SM))),
 cell("Taken by another app", '<div class="pnl">%s</div>' % n("warn", "alert", "reachy3 is in use by the Reachy Mini desktop app.", btn("Take over", "dark", extra=SM) + btn("Cancel", "ghost", extra=SM))),
 cell("Robot WiFi", '<div class="pnl"><p class="sub" style="font-size: 14px;">One Add WiFi panel per robot, in its details (Robots board 5). Its states are on board 6.</p></div>', span=2),
]
ts = '<div class="app" style="padding: 32px; box-sizing: border-box;"><div style="display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 24px 20px; align-items: start;">%s</div></div>' % "\n".join(ts_cells)
write("RATalkStates.dc.html", page("reachy_app: Talk and Wizard of Oz states", ts, "renderVals() { return { yes: true }; }", width=1600, height=1460, extra_css=RA_CSS + SHOW_CSS, mono=True))

# ====================================================================== Group states
def mini_stage(phase, col, big, det, extra=""):
    return '<div class="pnl" style="gap: 6px;"><div class="phase" style="color: %s;"><span class="pdot"></span>%s</div><p class="big" style="font-size: 19px; line-height: 25px;">%s</p><p class="det">%s</p>%s</div>' % (col, phase, big, det, extra)

tb_cells = [
 cell("Start refused (banner)", '<div class="warnbar err" style="border-radius: 12px; border: 1px solid #F2C4C4;">%s<span>Couldn\'t start: include at least two connected Reachys.</span></div>' % ic("alert", 18), span=2),
 cell("Not saved", '<div class="pnl"><span class="save warn" style="padding: 0;">%sNot saved: the hub didn\'t answer. Trying again…</span></div>' % ic("alert", 16), span=2),
 cell("A check failed", '<div class="pnl" style="gap: 8px;"><div class="srow"><button class="chk bad" type="button" aria-expanded="true">1 failed: Voice of Leo</button></div><div class="chips2"><span class="chk ok">OpenAI 0.6 s</span><span class="chk bad" title="ElevenLabsError: voice not found">Voice of Leo: failed</span></div><p class="det">Connected, but Voice of Leo failed the check.</p></div>', span=2),
 cell("Closing", mini_stage("Stopping", "#8A3B00", "Closing: each robot says its last word", "Group talk", '<div style="display: flex; gap: 8px;">%s</div>' % btn("Stop now", "stop", "stop", extra=' style="min-height: 40px; background: #B91C1C; color: #FFFFFF;"'))),
 cell("Over time", '<div class="pnl"><span class="timer" style="color: #8A3B00;">6:12 / 6:00</span><div class="bar"><span style="width: 100%; background: #D97706;"></span></div><p class="sub">Every robot says a closing line now.</p></div>'),
 cell("Interrupt mode", mini_stage("People speaking", "#B45309", "You have the floor (for now)", "Interrupt · waiting for the person")),
 cell("Interrupt: a robot cuts in", mini_stage("Speaking", "#1D4ED8", 'Leo <span class="muted" style="font-weight: 600;">(reachy3)</span> cuts in', "Interrupt")),
 cell("Start hints", '<div class="pnl" style="gap: 8px;"><span class="warnline">%sInclude at least two Reachys, or press + on a card for a laptop robot.</span><span class="warnline">%sNot connected: reachy6.</span><span class="sub">One Reachy: use the Talk tab.</span><span class="sub">Simulation: this laptop speaks and listens.</span></div>' % (ic("alert", 16), ic("alert", 16)), span=2),
 cell("Mic", '<div class="pnl" style="gap: 8px;"><div class="srow" style="flex-wrap: wrap;"><span class="warnline">%sMic: DJI mic · stalled</span>%s</div><div class="srow" style="flex-wrap: wrap; font-weight: 400;"><span>Mic: the robots\' own (reachy1, reachy3) · DJI mic plugged in</span>%s</div><span class="sub">Mic: no DJI plugged in · the robots\' own mics</span></div>' % (ic("mic", 16), btn("Use robots' mics", "ghost", extra=SM), btn("Use the DJI mic", "quiet", extra=SM)), span=2),
 cell("Seat while connected", '<div class="seat" style="--sc: #BE185D;"><div class="seathd"><span class="sn">4</span><input class="lab" type="text" value="Leo" aria-label="Label"><button class="ib" type="button" disabled="{{yes}}" title="Disconnect first to change the seats">%s</button><button class="ib" type="button" disabled="{{yes}}">%s</button></div><p class="sub" style="color: #B91C1C;">Another robot has this label.</p><div class="checks3"><label><input type="checkbox" checked disabled>Included</label><label><input type="checkbox" disabled>Listens</label><label><input type="checkbox" checked>Camera</label></div><span class="rtag" style="align-self: flex-start;">laptop · talks through this laptop</span></div>' % (ic("left", 16), ic("right", 16))),
 cell("No Reachys", '<div class="pnl"><p class="muted" style="margin: 0; text-align: center;">No Reachys yet.<br><a href="Hub.dc.html">Connect them on Robots</a> and they show up here.</p></div>'),
 cell("ElevenLabs credits low", '<div class="pnl"><p class="sub" style="color: #8A3B00; font-weight: 600;">ElevenLabs credits: 1,120. Low: robots on Auto use OpenAI.</p><p class="sub">Voice list: (no key) and (not in the list) marks</p>%s</div>' % sel(["Auto", "ElevenLabs (no key)", "OpenAI", "OpenRouter", "Gemini (daily cap)"], "ElevenLabs (no key)", aria="Voice service")),
 cell("Transcript notes, scrolled up", '<div class="pnl" style="gap: 4px;"><p class="note2">4:10 Leo\'s voice failed: timeout. It goes on.</p><p class="note2">4:31 the people are heard through the robots\' mics now</p><p class="note2">5:02 +1 min: it now ends at 7:00</p><p class="note2">6:00 the conversation is over</p><button class="jump" type="button">%sJump to latest (3 new)</button></div>' % ic("down", 14), span=2),
 cell("Ended", mini_stage("Connected", "#15803D", "Robots connected: pick a mode", "The robots stay connected. Press a mode to go again.")),
 cell("Toasts", '<div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start;"><div class="toast" style="position: static; transform: none;">Interrupting 3 (regularly) for every robot.</div><div class="toast" style="position: static; transform: none;">Sent. The next line follows it.</div><div class="toast" style="position: static; transform: none;">Choir on: every robot says the same line (from the next Start).</div><div class="toast" style="position: static; transform: none;">Copied to Leo, Reachy Mini 3.</div><div class="toast" style="position: static; transform: none; background: #7F1D1D;">Couldn\'t add time: the robots are already saying goodbye.</div></div>', span=2),
]
tb = '<div class="app" style="padding: 32px; box-sizing: border-box;"><div style="display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 24px 20px; align-items: start;">%s</div></div>' % "\n".join(tb_cells)
write("RATableStates.dc.html", page("reachy_app: Group states", tb, "renderVals() { return { yes: true }; }", width=1600, height=1300, extra_css=RA_CSS, mono=True))
