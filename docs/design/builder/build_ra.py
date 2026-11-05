# reachy_app boards: one app for one Reachy (Talk), a table of Reachys (Group talk, Interrupt, Free talk, Choir)
# and the Wizard of Oz operator board. Full parity with today's group page and reachy_chat dashboard.
from build_hub import *

I.update({
 "stop": '<rect x="6" y="6" width="12" height="12" rx="2"></rect>',
 "play": '<polygon points="6 4 20 12 6 20 6 4"></polygon>',
 "mic": '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line>',
 "vol": '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>',
 "send": '<line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>',
 "left": '<polyline points="15 18 9 12 15 6"></polyline>',
 "right": '<polyline points="9 18 15 12 9 6"></polyline>',
 "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>',
 "edit": '<path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path>',
 "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle>',
 "clock": '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>',
 "down": '<line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline>',
})

SEAT = ["#2563EB", "#C2410C", "#047857", "#BE185D", "#6D28D9", "#0E7490"]

RA_CSS = r"""
.ttl{font-weight:700;font-size:17px;letter-spacing:-.01em;margin:0 8px 0 4px;white-space:nowrap}
.tabs{display:flex;gap:4px;background:var(--sunken);padding:4px;border-radius:12px}
.tab{display:flex;flex-direction:column;justify-content:center;padding:3px 14px;border-radius:9px;font-weight:600;font-size:14px;line-height:18px;color:var(--ink);text-decoration:none;min-height:40px;box-sizing:border-box}
.tab small{font-size:11.5px;font-weight:500;color:var(--muted);line-height:14px}
.tab.on{background:#FFFFFF;box-shadow:0 1px 2px rgba(28,25,23,.10)}
a.tab:hover{color:var(--ink)}
.save{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--run);padding:0 8px;white-space:nowrap}
.save.warn{color:var(--warn)}
.save .icon{width:16px;height:16px}
.pnl{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px;display:flex;flex-direction:column;gap:12px;min-width:0;box-sizing:border-box}
.pnlh{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.pnlh h2,.pnlh h3{font-size:12px;line-height:16px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin:0}
.frow{display:grid;grid-template-columns:104px minmax(0,1fr);align-items:center;gap:8px 10px}
.frow>label,.frow>.fl{font-size:14px;font-weight:500;color:var(--ink)}
.frow .select,.frow .input{height:36px}
.srow{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:500}
.srow .grow{flex:1 1 auto;min-width:0}
.used{display:inline-flex;gap:4px;flex-wrap:wrap}
.used span{font-size:11px;font-weight:600;line-height:16px;padding:0 6px;border-radius:5px;background:var(--sunken);color:var(--muted);white-space:nowrap}
.ta{border:1px solid var(--ctrl);border-radius:10px;padding:8px 10px;font:inherit;font-size:14px;line-height:20px;resize:none;width:100%;box-sizing:border-box;color:var(--ink);background:#FFFFFF}
.cnt{font-size:12px;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.badge{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:8px;background:var(--sunken);font-size:13px;font-weight:500;white-space:nowrap;color:var(--ink)}
.badge .mono{font-size:12px}
.rng{display:flex;align-items:center;gap:8px;font-size:13px;font-variant-numeric:tabular-nums}
.rng input[type=range]{accent-color:#1C1917;width:120px}
.sub-badge{font-size:11px;font-weight:700;letter-spacing:.06em;padding:2px 8px;border-radius:6px;background:var(--ready-tint);color:var(--ready)}
.sub-badge.speak{background:#EEF4FF;color:#1D4ED8}
.sub-badge.listen{background:var(--run-tint);color:var(--run)}
.sub-badge.think{background:var(--busy-tint);color:var(--brand-text)}
.log{font-family:"JetBrains Mono",ui-monospace,Consolas,monospace;font-size:12px;line-height:19px;background:#171412;color:#E7E2DA;border-radius:10px;padding:10px 12px;overflow:hidden;flex:1 1 auto;min-height:0}
.log div{white-space:pre-wrap;overflow-wrap:anywhere}
.log .t{color:#9C948A}.log .w{color:#FFC56B}.log .e{color:#FF8A8A}.log .d{color:#8C847A}
.chat{display:flex;flex-direction:column;gap:10px;flex:1 1 auto;min-height:0;overflow:hidden}
.bub{max-width:78%;padding:10px 14px;border-radius:14px;font-size:16px;line-height:24px}
.bub.robot{align-self:flex-start;background:#FFF4E0;border-top-left-radius:4px}
.bub.person{align-self:flex-end;background:var(--sunken);border-top-right-radius:4px}
.bub .meta{display:flex;gap:8px;align-items:center;font-size:12px;color:var(--muted);margin-top:4px;flex-wrap:wrap}
.bub.saying{box-shadow:0 0 0 2px #FDB241}
.mbtn.on[disabled]{opacity:1;cursor:default}
.chk.wait{background:#FFFFFF;border:1px dashed #D6CFC5;color:var(--muted)}
.chk .spin{width:11px;height:11px}
.sys{align-self:center;font-size:12.5px;color:var(--muted);background:var(--sunken);border-radius:999px;padding:3px 12px}
.sys.err{background:var(--danger-tint);color:var(--danger)}
.cur{display:inline-block;width:.55em;color:#A84E00;animation:blink 1s steps(1) infinite}
@keyframes blink{50%{opacity:0}}
.mtag{font-size:11.5px;font-weight:600;padding:0 6px;line-height:18px;border-radius:5px;background:#FFFFFF;color:var(--muted);border:1px solid var(--border)}
.stage{display:grid;grid-template-columns:minmax(0,1.25fr) 230px minmax(0,1.6fr);gap:20px;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:14px 18px}
.phase{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;display:flex;align-items:center;gap:8px}
.pdot{width:9px;height:9px;border-radius:50%;background:currentColor}
.big{font-size:22px;line-height:28px;font-weight:700;letter-spacing:-.015em;margin:2px 0 0}
.det{font-size:14px;color:var(--muted);margin:2px 0 0}
.timer{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.bar{height:6px;border-radius:999px;background:var(--sunken);overflow:hidden;margin-top:6px}
.bar span{display:block;height:100%;background:#1C1917;border-radius:999px}
.modes2{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) auto auto;gap:8px}
.mbtn{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:0;min-height:52px;padding:6px 12px;border-radius:12px;border:1px solid var(--border);background:#FFFFFF;font:inherit;font-weight:600;font-size:15px;color:var(--ink);cursor:pointer;text-align:left}
.mbtn small{font-size:12px;font-weight:500;color:var(--muted)}
.mbtn.on{background:var(--run-tint);border-color:#86D9A4;color:var(--run)}
.mbtn.int{border-left:4px solid #C2410C}
.mbtn.free{border-left:4px solid #0E7490}
.mbtn.grp{border-left:4px solid #2563EB}
.mbtn[disabled]{opacity:.45;cursor:default}
.substrip{display:flex;align-items:center;gap:10px;flex-wrap:wrap;grid-column:1 / -1;border-top:1px solid var(--border);padding-top:10px;font-size:14px}
.okline{color:var(--run);font-weight:500;display:inline-flex;align-items:center;gap:6px}
.warnline{color:var(--warn);font-weight:500;display:inline-flex;align-items:center;gap:6px}
.chk{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 10px;border-radius:999px;font-size:13px;font-weight:500;background:var(--sunken);color:var(--ink);font-variant-numeric:tabular-nums;white-space:nowrap}
.chk.ok{background:var(--run-tint);color:var(--run)}
.chk.bad{background:var(--danger-tint);color:var(--danger)}
.chips2{display:flex;gap:6px;flex-wrap:wrap;grid-column:1 / -1}
.seat{background:var(--card);border:1px solid var(--border);border-top:4px solid var(--sc);border-radius:14px;padding:12px 14px;display:flex;flex-direction:column;gap:10px;min-width:0}
.seat.speaking{box-shadow:0 0 0 3px #BFD3FB;background:#FBFCFF}
.seat.out{opacity:.5}
.seathd{display:flex;align-items:center;gap:8px}
.sn{width:24px;height:24px;border-radius:7px;background:var(--sc);color:#FFFFFF;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.lab{flex:1 1 auto;min-width:0;height:34px;border:1px solid var(--ctrl);border-radius:9px;padding:0 10px;font:inherit;font-size:15px;font-weight:600;color:var(--ink);box-sizing:border-box}
.rtag{font-size:12px;color:var(--muted);background:var(--sunken);border-radius:6px;padding:1px 6px;white-space:nowrap}
.gtag{font-size:12px;font-weight:600;border-radius:6px;padding:1px 6px;white-space:nowrap}
.meter{height:6px;border-radius:999px;background:var(--sunken);overflow:hidden;flex:1 1 auto}
.meter span{display:block;height:100%;background:#15803D}
.meter.deaf span{background:#C9C2B8}
.ib{width:30px;height:30px;border-radius:8px;border:1px solid var(--border);background:#FFFFFF;display:inline-flex;align-items:center;justify-content:center;color:var(--ink);cursor:pointer;padding:0}
.ib[disabled]{opacity:.4}
.ib .icon{width:16px;height:16px}
.checks3{display:flex;gap:14px;flex-wrap:wrap;font-size:13.5px}
.checks3 label{display:inline-flex;align-items:center;gap:6px}
.checks3 input{width:16px;height:16px;accent-color:#1C1917;margin:0}
.seg{display:flex;border:1px solid var(--ctrl);border-radius:9px;overflow:hidden;height:32px}
.seg button{flex:1 1 0;border:0;background:#FFFFFF;font:inherit;font-size:13px;font-weight:600;color:var(--ink);cursor:pointer;padding:0 6px;font-variant-numeric:tabular-nums}
.seg button+button{border-left:1px solid var(--border)}
.seg button.on{background:#1C1917;color:#FFFFFF}
.seg.lvl button.on{background:#C2410C}
.vline{font-size:12.5px;color:var(--muted)}
.fl2{font-size:12px;font-weight:600;color:var(--muted);margin:0 0 -4px}
.tr{display:flex;flex-direction:column;justify-content:flex-end;gap:2px;overflow:hidden;flex:1 1 auto;min-height:0}
.ln2{display:grid;grid-template-columns:4px minmax(0,1fr);gap:10px;padding:8px 10px 8px 0;border-radius:8px}
.ln2 .cb{border-radius:4px;background:var(--sc)}
.ln2 .lh{display:flex;align-items:center;gap:8px;font-size:12.5px;color:var(--muted);flex-wrap:wrap;font-variant-numeric:tabular-nums}
.ln2 .who{font-weight:700;color:var(--sc);font-size:13.5px;display:inline;flex:none}
.ln2 .tx{font-size:17px;line-height:25px;color:var(--ink);margin-top:2px}
.ln2.now{background:#EEF4FF}
.ln2.cut .tx{text-decoration:line-through;color:var(--muted)}
.cuttag{font-size:11.5px;font-weight:700;color:var(--warn);background:var(--warn-tint);border-radius:5px;padding:0 6px}
.ln2.people{background:#FFFBF2}
.ln2.people .cb{background:#D97706}
.ln2.people .who{color:#8A3B00}
.note2{font-size:12.5px;color:var(--muted);font-style:italic;padding:3px 0 3px 14px;margin:0}
.plive{border:1px solid #F5C77E;background:#FFFBF2;border-radius:12px;padding:8px 12px;font-size:17px;line-height:25px}
.plive b{display:block;font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:#8A3B00}
.steer{display:flex;gap:8px;align-items:center}
.kbd{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 5px;border-radius:5px;border:1px solid var(--border);background:#FFFFFF;font-size:11.5px;font-weight:600;color:var(--muted);font-family:inherit;box-sizing:border-box}
.jump{align-self:center;display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 12px;border-radius:999px;background:#1C1917;color:#FFFFFF;font-size:13px;font-weight:600;border:0}
.fold{border-top:1px solid var(--border);padding-top:10px;display:flex;flex-direction:column;gap:10px}
.modal{position:absolute;background:#FFFFFF;border-radius:18px;box-shadow:0 24px 64px -16px rgba(28,25,23,.45);display:flex;flex-direction:column;gap:14px;padding:20px 22px}
.modal h2{font-size:19px;margin:0}
"""

def head(tab="talk", save="Saved", savecls="", extra=""):
    def t(k, title, sub, href):
        return '<a class="tab%s" href="%s" role="tab" aria-selected="%s">%s<small>%s</small></a>' % (" on" if k == tab else "", href, "true" if k == tab else "false", title, sub)
    return """<header class="top" style="gap: 10px;">
    <a class="btn btn-ghost btn-sm" href="Hub.dc.html">%sRobots</a>
    <span class="ttl">Reachy app</span>
    <nav class="tabs" role="tablist">%s%s%s</nav>
    %s
    <span class="spacer"></span>
    <span class="save %s">%s%s</span>
    <span class="live" title="Robot Hub is running"><span class="ldot" aria-hidden="true"></span>Live</span>
    <a class="btn btn-ghost btn-sm" href="Logs.dc.html">%sLogs</a>
  </header>""" % (ic("back", 18), t("talk", "Talk", "one Reachy", "RATalk.dc.html"), t("table", "Group", "two or more Reachys", "RATable.dc.html"),
                 t("woz", "Wizard of Oz", "you drive it", "RAShow.dc.html"), extra, savecls, ic("check" if not savecls else "alert", 16), save, ic("logs", 18))

def sel(opts, selected=None, cls="select", aria="", style=""):
    o = "".join('<option%s>%s</option>' % (" selected" if x == selected else "", x) for x in opts)
    return '<select class="%s" aria-label="%s"%s>%s</select>' % (cls, aria, (' style="%s"' % style) if style else "", o)

def sw(on=True, label=""):
    return '<button class="switch%s" type="button" role="switch" aria-checked="%s" aria-label="%s"><span></span></button>' % (" on" if on else "", "true" if on else "false", label)

def used(*modes):
    return '<span class="used">%s</span>' % "".join("<span>%s</span>" % m for m in modes)

# ====================================================================== Talk (one Reachy)
BRAINS = ["Gemini 3.8 Live", "Gemini 3.1 Flash Live (previous)", "OpenAI GPT-Live-1 (no key)"]
GVO = ["Default (Aoede)", "Aoede", "Kore", "Charon", "Puck", "Leda"]
PRESETS = ["Scientist", "Write my own", "Cowboy", "Jokes only", "Pirate", "Shy"]

talk_left = """<div style="display: flex; flex-direction: column; gap: 12px; min-height: 0;">
      <section class="pnl">
        <div class="pnlh"><h2 style="flex: 1 1 auto;">Robot</h2><a class="btn btn-ghost btn-sm" href="RobotPanel.dc.html" style="min-height: 28px; padding: 0 8px; font-size: 13px;">Details</a></div>
        <div class="srow"><img src="img/%s" alt="" style="width: 40px; height: 40px; border-radius: 10px;">%s
          <span class="okline" style="margin-left: auto; font-size: 13px;"><span class="pdot" style="width: 8px; height: 8px;"></span>Connected</span><span class="metric">%s 10.0.4.23</span></div>
        <div class="srow" style="font-size: 13.5px; font-weight: 400; color: #6B635A;"><span class="pill p-run"><span class="dot"></span>In conversation</span><span class="sub-badge speak">SPEAKING</span><span style="margin-left: auto;">Daemon active</span></div>
        <div style="display: flex; gap: 8px;">%s%s</div>
      </section>

      <section class="pnl">
        <div class="pnlh"><h2>How it talks</h2></div>
        <div class="frow"><label>Brain</label>%s
          <label>Language</label>%s
          <label>Brain voice</label>%s</div>
        <div class="srow"><span class="grow">ElevenLabs v4 voice</span>%s</div>
        <div class="srow"><span class="grow">Camera vision</span>%s</div>
        <p class="sub" style="margin-top: -6px;">%sRobot camera · the model sees the frames</p>
        <p class="sub">%sApplies to the next conversation.</p>
      </section>

      <section class="pnl">
        <div class="pnlh"><h2 style="flex: 1 1 auto;">Character</h2>%s</div>
        <p class="sub" style="color: #15803D; font-weight: 600; font-size: 14px;">In character: Scientist</p>
        <div class="frow"><label>Start from</label>%s</div>
        <textarea class="ta" rows="4" aria-label="Who should this Reachy be?">You are a curious scientist. You explain things with small experiments the person can try at home, and you get excited about numbers.</textarea>
        <div style="display: flex; align-items: center; gap: 8px;"><span class="sub">Applies to the next conversation.</span><span class="cnt" style="margin-left: auto;">131 / 1500</span></div>
        <div class="frow"><label>Voice</label>%s</div>
        <p class="sub" style="margin-top: -6px;">Used while Brain voice is Default. Saved with Save.</p>
        <div style="display: flex; gap: 8px;">%s%s</div>
      </section>
    </div>""" % (
    R, '<span style="font-weight: 600; font-size: 16px;">reachy3</span>', ic("wifi", 14),
    btn("Stop system", "quiet", "stop", extra=' style="min-height: 36px; font-size: 14px; flex: 1 1 0;"'),
    btn("Start system", "quiet", "play", disabled=True, extra=' style="min-height: 36px; font-size: 14px; flex: 1 1 0;"'),
    sel(BRAINS, BRAINS[0], aria="Brain"), sel(["English", "עברית", "Auto (עברית / English)"], "English", aria="Language"), sel(GVO, GVO[0], aria="Voice"),
    sw(False, "ElevenLabs v4 voice"), sw(True, "Camera vision"), ic("camera", 14), ic("clock", 14),
    sw(True, "Character on"), sel(PRESETS, "Scientist", aria="Start from"), sel(["Default voice (Aoede)", "Aoede", "Kore", "Charon", "Puck", "Leda"], "Default voice (Aoede)", aria="Character voice"),
    btn("Save", "dark", extra=' style="min-height: 36px; font-size: 14px;"'), btn("Clear", "ghost", extra=' style="min-height: 36px; font-size: 14px;" title="Clear the text and go back to the base persona"'))

talk_mid = """<section class="pnl" style="min-height: 0;">
      <div class="pnlh" style="gap: 12px;">
        <h2>Conversation</h2><span class="mono">1105-1412-a3</span>
        <span class="spacer"></span>
        <span class="badge">Turn <b>7</b></span><span class="badge">%sThis turn <b>0:12</b></span>
      </div>
      <div class="chat">
        <span class="sys">Gemini 3.8 Live · en-US · Gemini Live voice Aoede · Character: Scientist</span>
        <div class="bub robot">Hi, I'm Reachy Mini. Want to see something cool with a glass of water?<div class="meta">Turn 0<span class="mtag">nod</span></div></div>
        <div class="bub person">Yes! What do I need?<div class="meta">Turn 1</div></div>
        <div class="bub robot">Just a glass, some water and a sheet of paper. Fill it to the top, cover it, then flip it over.<div class="meta">Turn 1<span class="mtag">look up</span></div></div>
        <span class="sys err">Turn 4 aborted: Gemini went silent</span>
        <div class="bub person" dir="auto">מה אתה רואה עכשיו?<div class="meta">Turn 6</div></div>
        <div class="bub robot">I see a blue mug on the table and someone waving at me. Hello there!<div class="meta">Turn 6<span class="mtag">happy</span>%s</div></div>
        <div class="bub robot saying" aria-live="polite">{{caption}}<span class="cur" aria-hidden="true">▌</span><div class="meta">Turn 7 · speaking now</div></div>
      </div>
      <div style="display: flex; gap: 10px; align-items: center;">
        <button class="btn btn-stop" type="button" style="min-height: 48px; padding: 0 22px;" onClick="{{end}}">%sEnd conversation</button>
        <span class="sub">Or the person says "goodbye" or "להתראות".</span>
        <span class="spacer"></span>
        <button class="btn btn-ghost btn-sm" type="button" onClick="{{replay}}">Replay caption</button>
      </div>
    </section>""" % (ic("clock", 14), '<span class="mtag">%s saw: mug, person</span>' % "", ic("stop", 18))

talk_right = """<section class="pnl" style="min-height: 0;">
      <div class="pnlh"><h2 style="flex: 1 1 auto;">Event log</h2><span class="sub">Copied</span>%s</div>
      <div class="log" role="log">
        <div><span class="t">14:12:02.114</span> INFO  client  conversation on Gemini 3.8 Live</div>
        <div><span class="t">14:12:02.480</span> INFO  conversation  opener: hi + one question</div>
        <div><span class="t">14:12:05.031</span> INFO  vision  frame 512x288, 1/s</div>
        <div><span class="t">14:12:21.903</span> INFO  motion  play_emotion nod</div>
        <div class="w"><span class="t">14:13:40.227</span> WARNING conversation  turn 4: Gemini silent, aborted</div>
        <div><span class="t">14:14:02.660</span> INFO  motion  play_emotion happy</div>
        <div class="d"><span class="t">14:14:03.012</span> DEBUG vad  speech end, 0.8 s hangover</div>
        <div><span class="t">14:14:11.540</span> INFO  conversation  turn 7 listening</div>
        <div><span class="t">14:14:13.901</span> INFO  conversation  turn 7 speaking</div>
      </div>
    </section>""" % btn("Copy logs", "ghost", "copy", extra=' style="min-height: 28px; padding: 0 8px; font-size: 13px;"')

vol = '<span class="rng" title="0-100 sets the speaker. Above 100 boosts the voice.">%s<input type="range" min="0" max="150" step="5" value="120" aria-label="Volume"><b style="color: #8A3B00;">120%%</b></span>' % ic("vol", 16)
badges = '<span class="badge">Gemini 3.8 Live</span><span class="badge"><span class="mono">Lab Gemini ··a91f</span></span>' + vol
talk_body = """<div class="app">
  %s
  <main style="flex: 1 1 auto; display: grid; grid-template-columns: 400px minmax(0,1fr) 380px; gap: 14px; padding: 14px 18px 18px; min-height: 0; box-sizing: border-box; height: 936px;">
    %s
    %s
    %s
  </main>
</div>""" % (head("talk", extra=badges), talk_left, talk_mid, talk_right)

CAP = "Now flip the glass fast, and pull the paper away slowly. The air pushes up harder than the water pushes down, so nothing spills."
talk_logic = """constructor(props) { super(props); this.state = { n: 38 }; }
  componentDidMount() { this.go(); }
  componentWillUnmount() { clearInterval(this.timer); }
  go() { var self = this; clearInterval(this.timer); this.setState({ n: 0 }); this.timer = setInterval(function () { var n = self.state.n + 2; if (n >= %d) { clearInterval(self.timer); n = %d; } self.setState({ n: n }); }, 45); }
  renderVals() {
    var self = this, full = %s;
    return { caption: full.slice(0, this.state.n), replay: function () { self.go(); }, end: function () {} };
  }""" % (len(CAP), len(CAP), repr(CAP))

write("RATalk.dc.html", page("reachy_app: Talk with one Reachy", talk_body, talk_logic, width=1600, height=1000, extra_css=RA_CSS, mono=True))

# ====================================================================== Group: seat card
PROV = ["Auto", "ElevenLabs", "OpenAI", "OpenRouter", "Gemini (daily cap)"]
WRITERS = ["Gemini 3.5 Flash (smart, ~2.5 s)", "gpt-oss-120b (fastest, ~1.2 s)", "GPT-5.4 mini (~2.8 s)", "GPT-4.1 mini (OpenAI key)", "Flash-Lite (Gemini key)"]

def seat(i, label, name, state, prov, voice, voices, writer, lvl, gest, volv, pers, meter=40, locked=False, speaking=False, out=False, group=None, compact=False, inc=True, listens=True, cam=True, vline="Voice: ElevenLabs, writing via OpenRouter"):
    c = SEAT[i]
    st = {"Connected": "conn", "Available": "near", "Running": "run", "Not connected": "off"}.get(state, "near")
    lockd = ' disabled="{{yes}}" title="Disconnect first to change the seats"' if locked else ""
    gt = '<span class="gtag" style="background: %s1A; color: %s;">%s</span>' % (group[1], group[1], group[0]) if group else ""
    levels = "".join('<button type="button" class="%s" title="%s">%d</button>' % ("on" if n == lvl else "", ["Never", "Rarely", "Now and then", "Regularly", "Often, and piles on", "Every time"][n], n) for n in range(6))
    hd = """<div class="seathd"><span class="sn">%d</span><input class="lab" type="text" value="%s" maxlength="30" aria-label="Label"><button class="ib" type="button" aria-label="Move left"%s>%s</button><button class="ib" type="button" aria-label="Move right"%s>%s</button></div>
          <div class="seathd" style="gap: 6px; flex-wrap: wrap;"><span class="rtag">%s</span>%s<span class="pill p-%s" style="height: 22px; font-size: 12px;"><span class="dot"></span>%s</span><span class="spacer"></span><span title="Mic level. Echo check: its own voice peaked 4 dB over the learned echo." style="display: flex; align-items: center; gap: 6px; width: 90px;">%s<span class="meter%s"><span style="width: %d%%;"></span></span></span></div>""" % (
        i + 1, label, lockd, ic("left", 16), lockd, ic("right", 16), name, gt, st, state, ic("mic", 14), "" if listens else " deaf", meter)
    vsel = sel(voices, voice, aria="Voice")
    body_full = """<div class="checks3"><label title="Takes part in the conversation. Unticked, it stays connected to the hub."><input type="checkbox"%s%s>Included</label><label title="Its mic hears the people when the DJI mic is not in use."><input type="checkbox"%s%s>Listens</label><label title="It can look through its camera when someone asks what it sees."><input type="checkbox"%s>Camera</label></div>
          <p class="fl2">Personality %s</p>
          <textarea class="ta" rows="3" maxlength="800" aria-label="Personality">%s</textarea>
          <p class="fl2">Voice</p>
          <div style="display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 6px;">%s%s</div>
          <p class="fl2">Writer</p>%s
          <p class="fl2">Interrupting %s</p><div class="seg lvl">%s</div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; align-items: end;">
            <div><p class="fl2" style="margin-bottom: 4px;">Gestures</p><div class="seg"><button type="button" class="%s" title="Moves on almost every line, and reacts while the others talk.">Lively</button><button type="button" class="%s" title="Moves on about half of its lines, rarely reacts.">Calm</button></div></div>
            <div><p class="fl2" style="margin-bottom: 4px;">Volume <b style="color: #1C1917;">%d%%</b></p><input type="range" min="0" max="250" step="5" value="%d" aria-label="Volume" title="100 = natural level. The speaker is already at its maximum; above 100 the hub boosts the audio." style="width: 100%%; accent-color: %s;"></div>
          </div>
          <p class="vline">%s</p>
          <div style="display: flex; gap: 6px;"><button class="btn btn-ghost btn-sm" type="button" style="min-height: 30px; font-size: 13px; padding: 0 8px;">%sCopy to others</button><span class="spacer"></span><button class="ib" type="button" aria-label="Add a laptop robot here"%s>%s</button><button class="ib" type="button" aria-label="Take off the table"%s>%s</button></div>""" % (
        " checked" if inc else "", lockd, " checked" if listens else "", lockd, " checked" if cam else "",
        used("Group", "Interrupt"), pers, sel(PROV, prov, aria="Voice service"), vsel, sel(WRITERS, writer, aria="Writer"), used("Interrupt only"), levels,
        "on" if gest == "Lively" else "", "on" if gest == "Calm" else "", volv, volv, c, vline, ic("copy", 14), lockd, ic("plus", 16), lockd, ic("x", 16))
    body_compact = """<div style="display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 6px;">%s%s</div>
          %s
          <div style="display: grid; grid-template-columns: 1.4fr 1fr auto; gap: 8px; align-items: center;"><div class="seg lvl" title="Interrupting, used in Interrupt mode">%s</div><input type="range" min="0" max="250" step="5" value="%d" aria-label="Volume" title="100 = natural level; above 100 the hub boosts the audio" style="width: 100%%; accent-color: %s;"><b style="font-size: 13px; font-variant-numeric: tabular-nums;">%d%%</b></div>
          <p class="vline">%s · <a href="RATable.dc.html">Personality, camera, more</a></p>""" % (
        sel(PROV, prov, aria="Voice service"), vsel, sel(WRITERS, writer, aria="Writer"), levels, volv, c, volv, vline)
    cls = "seat" + (" speaking" if speaking else "") + (" out" if out else "")
    return '<article class="%s" style="--sc: %s;">%s%s</article>' % (cls, c, hd, body_compact if compact else body_full)

ELV = ["Default (Daniel)", "Daniel", "Adam", "Josh", "Brian", "Callum"]
OAV = ["Default (ash)", "ash (male)", "ballad (male)", "cedar (male)", "echo (male)", "onyx (male, deep)", "fable (male, British)", "verse (male)"]
GEV = ["Default (Charon)", "Achird", "Algenib", "Algieba", "Alnilam", "Charon", "Enceladus", "Fenrir", "Iapetus", "Orus", "Puck", "Rasalgethi", "Sadachbia", "Sadaltager", "Schedar", "Umbriel", "Zubenelgenubi"]

def stage(phase, phcol, big, det, timer, pct, modes, sub, chips=""):
    return """<section class="stage">
      <div><div class="phase" style="color: %s;"><span class="pdot"></span>%s</div><p class="big">%s</p><p class="det">%s</p></div>
      <div><div style="display: flex; align-items: baseline; gap: 10px;"><span class="timer">%s</span>%s</div><div class="bar"><span style="width: %d%%;"></span></div></div>
      <div class="modes2">%s</div>
      <div class="substrip">%s</div>
      %s
    </section>""" % (phcol, phase, big, det, timer, btn("+1 min", "quiet", extra=' style="min-height: 30px; font-size: 13px; padding: 0 10px;"' + (' disabled="{{yes}}"' if pct == 0 else "")), pct, modes, sub, chips)

def mb(title, subt, cls, on=False, dis=False):
    return '<button class="mbtn %s%s" type="button"%s>%s<small>%s</small></button>' % (cls, " on" if on else "", ' disabled="{{yes}}"' if dis else "", title, subt)

def session(locked=False, connected=True):
    lk = ' disabled="{{yes}}" title="Disconnect first to switch simulation"' if connected else ""
    return """<section class="pnl" style="gap: 10px;">
      <div class="pnlh"><h2>This conversation</h2></div>
      <div><p class="fl2" style="margin-bottom: 6px;">Topic %s</p><textarea class="ta" rows="2" maxlength="500" placeholder="What they talk about (empty: they choose)">Should AI write music?</textarea></div>
      <div class="frow"><label>Language</label>%s<label>Minutes</label><input class="input" type="number" min="0.5" max="60" step="1" value="6"></div>
      <div class="srow"><span class="grow">Lab intro %s</span>%s</div>
      <p class="sub">ElevenLabs credits: 41,220 · in use</p>
      <div class="fold">
        <div class="pnlh"><h3 style="flex: 1 1 auto;">Room and network</h3>%s</div>
        <div class="frow"><label>Gap</label><div class="rng"><input class="input" type="number" min="0.2" max="3" step="0.1" value="0.6" style="width: 80px; height: 36px;"> s</div>
          <label>Voice threshold</label><input class="input" type="number" min="0" max="0.9" step="0.05" value="0.3">
          <label>People cut in</label>%s
          <label>Audience mic</label><div style="display: flex; flex-direction: column; gap: 4px;">%s<span class="meter" style="flex: none; height: 5px;"><span style="width: 35%%;"></span></span></div></div>
        <div class="srow"><span class="grow">Slow network</span>%s</div>
        <div class="srow"><span class="grow">Heads turn the other way</span>%s</div>
        <div class="srow"><span class="grow">Simulate on this laptop</span><button class="switch" type="button" role="switch" aria-checked="false" aria-label="Simulate"%s><span></span></button></div>
      </div>
    </section>""" % (used("Group", "Interrupt"), sel(["Auto", "Hebrew", "English"], "English", aria="Language"), used("Group only"), sw(True, "Lab intro"), ic("chev", 16),
                     sel(["Off (only in the gaps)", "Careful", "Normal", "Eager"], "Normal", aria="People cut in"),
                     sel(["Auto (DJI mic, plugged in)", "Robots' own mics", "DJI mic", "Laptop's built-in mic"], "Auto (DJI mic, plugged in)", aria="Audience mic", style="opacity: .5;" if locked else ""),
                     sw(True, "Slow network"), sw(False, "Heads turn the other way"), lk)

def robots_head(saved="Saved."):
    return """<div class="pnlh" style="gap: 10px;">
        <h2>Robots</h2><span class="sub">Left to right, as the people see them. Order, Included and Listens lock while connected.</span>
        <span class="spacer"></span>
        <span class="save" style="padding: 0;">%s%s</span>
        <span class="sub" title="Groups. Used from the next Start.">Group 1 (2): move together</span>
        <button class="btn btn-quiet btn-sm" type="button" style="min-height: 32px; font-size: 13px;" aria-pressed="false">%sChoir</button>
        <a class="btn btn-quiet btn-sm" href="RADialogs.dc.html" style="min-height: 32px; font-size: 13px;">Groups…</a>
      </div>""" % (ic("check", 14), saved, ic("users", 14))

# ====================================================================== Group: before start
modes_ready = (mb("Group talk", "robots + people", "grp") + mb("Interrupt", "they cut you off", "int") + mb("Free talk", "chat about anything", "free")
               + '<button class="btn btn-quiet busy" type="button" disabled="{{yes}}" style="min-height: 52px;">Getting ready…</button>'
               + btn("Disconnect", "ghost", "unlink", extra=' style="min-height: 52px;"'))
chips_ready = """<div class="chips2"><span class="chk ok">OpenAI 0.6 s</span><span class="chk ok">Writer gemini-3.5-flash 1.9 s</span><span class="chk ok">Writer gpt-oss-120b 1.1 s</span><span class="chk wait"><span class="spin" aria-hidden="true"></span>Writer gemini-3.5-flash-lite</span><span class="chk ok">Hearing (speech to text) 0.8 s</span><span class="chk ok">Voice of Max 0.7 s</span><span class="chk wait"><span class="spin" aria-hidden="true"></span>Voice of Leo</span><span class="chk ok">Voice detection 0.2 s</span></div>"""
sub_ready = """<span class="okline">%sMic: DJI mic · signal ok</span>%s<span class="muted">3 Reachys at the table.</span><span class="spacer"></span><button class="chk" type="button" aria-expanded="true">checking 6/8 · last checked now</button>""" % (
    ic("mic", 16), btn("Use robots' mics", "ghost", extra=' style="min-height: 30px; font-size: 13px; padding: 0 10px;"'))
st_ready = stage("Connected", "#15803D", "Robots connected: pick a mode", "Getting ready: checking every service", "0:00 / 6:00", 0, modes_ready, sub_ready, chips_ready)

seats_setup = [
  seat(0, "Max", "reachy1", "Connected", "ElevenLabs", "Daniel", ELV, WRITERS[0], 3, "Lively", 150, "For AI music: optimistic, brings examples of tools musicians already use.", meter=55, locked=True, group=("Group 1", "#2563EB")),
  seat(1, "Leo", "reachy3", "Connected", "OpenAI", "onyx (male, deep)", OAV, WRITERS[1], 4, "Calm", 130, "Against: skeptical, asks who gets paid and what makes music human.", meter=20, locked=True, group=("Group 1", "#2563EB"), vline="Voice: OpenAI, writing via OpenRouter"),
  seat(2, "Reachy Mini 3", "reachy6", "Connected", "Gemini (daily cap)", "Default (Charon)", GEV, WRITERS[0], 2, "Lively", 150, "Precise: brings facts and numbers.", meter=0, locked=True, listens=False, vline="Voice: Gemini, writing via OpenRouter"),
]

conv_setup = """<section class="pnl" style="min-height: 0;">
      <div class="pnlh"><h2>Conversation</h2></div>
      <p class="muted" style="margin: auto 0; text-align: center; font-size: 14px;">Nothing said yet.<br>Press a mode when everyone is seated.</p>
      <div class="steer"><input class="input" type="text" placeholder="Steer: used once it runs" aria-label="Steer"><button class="btn btn-quiet btn-sm" type="button" disabled="{{yes}}">%sSend</button></div>
    </section>""" % ic("send", 16)

table_setup = """<div class="app">
  %s
  <main style="display: flex; flex-direction: column; gap: 14px; padding: 14px 18px 18px; box-sizing: border-box;">
    %s
    <div style="display: grid; grid-template-columns: 330px minmax(0,1fr) 300px; gap: 14px; align-items: start;">
      %s
      <section class="pnl" style="background: transparent; border: 0; padding: 0;">
        %s
        <div style="display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px;">%s</div>
        <p class="sub">%sKeys %s to %s set every robot's interrupting at once.</p>
      </section>
      %s
    </div>
  </main>
</div>""" % (head("table"), st_ready, session(), robots_head(), "".join(seats_setup), ic("info", 14), '<span class="kbd">0</span>', '<span class="kbd">5</span>', conv_setup)

write("RATable.dc.html", page("reachy_app: Group, before start", table_setup, "renderVals() { return { yes: true }; }", width=1680, height=1180, extra_css=RA_CSS, mono=True))

# ====================================================================== Group: live
modes_live = (mb("Group talk", "running", "grp", on=True, dis=True) + mb("Interrupt", "switch to this", "int") + mb("Free talk", "switch to this", "free")
              + btn("Stop", "stop", "stop", extra=' style="min-height: 52px;" title="The one talking finishes, then each robot says goodbye. Press again to stop now."')
              + btn("Disconnect", "ghost", "unlink", extra=' style="min-height: 52px;"'))
sub_live = """<span class="okline">%sMic: DJI mic · signal ok</span>%s<span class="spacer"></span><button class="chk ok" type="button" aria-expanded="false">8 checks ok · 3 min ago</button>""" % (
    ic("mic", 16), btn("Use robots' mics", "ghost", extra=' style="min-height: 30px; font-size: 13px; padding: 0 10px;"'))
st_live = stage("Speaking", "#1D4ED8", 'Leo <span class="muted" style="font-weight: 600;">(reachy3)</span> is speaking', "Group talk · answering the room", "3:12 / 6:00", 53, modes_live, sub_live)

def line(i, who, robot, move, ms, t, text, now=False, cut=False):
    rt = ' <span class="rtag">%s</span>' % robot if robot else ""
    mv = '<span class="mtag">%s</span>' % move if move else ""
    lat = '<span>%s ms</span>' % ms if ms else ""
    cutt = '<span class="cuttag">cut off</span>' if cut else ""
    return '<div class="ln2%s%s" style="--sc: %s;"><span class="cb"></span><div><div class="lh"><span class="who">%s</span>%s%s%s<span>%s</span>%s</div><div class="tx">%s</div></div></div>' % (
        " now" if now else "", " cut" if cut else "", SEAT[i], who, rt, mv, lat, t, cutt, text)

tr = "".join([
  '<p class="note2">0:00 Group talk started · lab intro: every robot says a line about the lab</p>',
  line(0, "Max", "reachy1", "intro", 820, "0:01", "Welcome to Laba Lab, where robots learn to listen. Today: should AI write music?"),
  line(1, "Leo", "reachy3", "challenge", 640, "0:14", "Write it, maybe. But who gets paid when a model copies a style it learned from a real band?"),
  line(0, "Max", "reachy1", "yes-but", 910, "0:31", "Fair, but musicians already use these tools to sketch ideas faster, and the song is still theirs.", cut=True),
  '<div class="ln2 people" style="--sc: #D97706;"><span class="cb"></span><div><div class="lh"><span class="who">People</span><span>heard closest to reachy6</span><span>0:44</span></div><div class="tx">But can a machine feel sad when it writes a sad song?</div></div></div>',
  line(2, "Reachy Mini 3", "reachy6", "people", 1120, "0:47", "Feel it? No. Measure it? Sad songs are slower, 20% on average, and lean on minor keys."),
  '<p class="note2">2:58 operator: ask the people who their favourite band is</p>',
  line(1, "Leo", "reachy3", "people", 700, "3:05", "{{caption}}<span class=\"cur\" aria-hidden=\"true\">▌</span>", now=True),
])

conv_live = """<section class="pnl" style="min-height: 0; flex: 1 1 auto;">
      <div class="pnlh"><h2>Conversation (6)</h2><span class="spacer"></span><span class="sub">Seat colours match the cards</span></div>
      <div class="tr">%s</div>
      <div class="plive" aria-live="polite"><b>People, live</b>{{people}}<span class="cur" aria-hidden="true">▌</span></div>
      <div class="steer"><input class="input" type="text" value="" placeholder="Steer: e.g. make them argue about it, or ask the people a question" aria-label="Steer" style="height: 40px;"><button class="btn btn-dark btn-sm" type="button">%sSend</button></div>
      <p class="sub" style="margin-top: -6px;">Last steer: ask the people who their favourite band is · Enter sends · used for the next line</p>
    </section>""" % (tr, ic("send", 16))

seats_live = [
  seat(0, "Max", "reachy1", "Running", "ElevenLabs", "Daniel", ELV, WRITERS[0], 3, "Lively", 150, "", meter=12, compact=True, locked=True, group=("Group 1", "#2563EB")),
  seat(1, "Leo", "reachy3", "Running", "OpenAI", "onyx (male, deep)", OAV, WRITERS[1], 4, "Calm", 130, "", meter=78, compact=True, speaking=True, locked=True, group=("Group 1", "#2563EB"), vline="Voice: OpenAI, writing via OpenRouter"),
  seat(2, "Reachy Mini 3", "reachy6", "Running", "Gemini (daily cap)", "Default (Charon)", GEV, WRITERS[0], 2, "Lively", 150, "", meter=0, compact=True, listens=False, locked=True, vline="Voice: Gemini, writing via OpenRouter"),
]
live_seats = """<section style="display: flex; flex-direction: column; gap: 10px;">%s<div style="display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px;">%s</div></section>"""
live_side = """<div style="display: flex; flex-direction: column; gap: 12px; min-width: 0;">
      <section class="pnl" style="gap: 8px;">
        <div class="pnlh"><h2 style="flex: 1 1 auto;">Conversation settings</h2><span class="sub">Change any time</span></div>
        <div class="frow"><label>Topic</label><input class="input" type="text" value="Should AI write music?"><label>Language</label>%s<label>Minutes</label><input class="input" type="number" min="0.5" max="60" step="1" value="6"><label>People cut in</label>%s</div>
        <div class="srow"><span class="grow">Lab intro <span class="used"><span>Group only</span></span></span>%s</div>
        <p class="sub">ElevenLabs credits: 40,980 · in use</p>
        <div class="fold"><div class="pnlh"><h3 style="flex: 1 1 auto;">Room and network</h3>%s</div><p class="sub">Gap, voice threshold, slow network and heads change live. Audience mic and Simulate wait until Stop.</p></div>
      </section>
      <section class="pnl" style="gap: 8px;">
        <div class="pnlh"><h2>Shortcuts</h2></div>
        <p class="sub"><span class="kbd">0</span>…<span class="kbd">5</span> every robot's interrupting · <span class="kbd">Enter</span> sends a steer</p>
      </section>
    </div>""" % (sel(["Auto", "Hebrew", "English"], "English", aria="Language"), sel(["Off (only in the gaps)", "Careful", "Normal", "Eager"], "Normal", aria="People cut in"), sw(True, "Lab intro"), '<span style="transform: rotate(-90deg); display: inline-flex;">' + ic("chev", 16) + '</span>')

table_live = """<div class="app">
  %s
  <main style="display: flex; flex-direction: column; gap: 14px; padding: 14px 18px 18px; box-sizing: border-box; height: 1176px;">
    %s
    %s
    <div style="display: grid; grid-template-columns: minmax(0,1fr) 380px; gap: 14px; flex: 1 1 auto; min-height: 0;">
      %s
      %s
    </div>
  </main>
</div>""" % (head("table"), st_live, live_seats % (robots_head().replace("Order, Included and Listens lock while connected.", "Seats are locked until Disconnect; everything else changes at once."), "".join(seats_live)), conv_live, live_side)

LIVE = "Before we vote: who here has a favourite band? Shout it out, and I will tell you whether a model could ever copy them."
PEOPLE = "Radiohead! And honestly I don't think a computer could write Creep"
live_logic = """constructor(props) { super(props); this.state = { n: 30, p: 20 }; }
  componentDidMount() { this.go(); }
  componentWillUnmount() { clearInterval(this.timer); }
  go() { var self = this; clearInterval(this.timer); this.setState({ n: 0, p: 0 }); this.timer = setInterval(function () { var n = Math.min(self.state.n + 2, %d), p = Math.min(self.state.p + 1, %d); self.setState({ n: n, p: p }); if (n >= %d && p >= %d) clearInterval(self.timer); }, 50); }
  renderVals() { return { yes: true, caption: %s.slice(0, this.state.n), people: %s.slice(0, this.state.p) }; }""" % (len(LIVE), len(PEOPLE), len(LIVE), len(PEOPLE), repr(LIVE), repr(PEOPLE))

write("RATableLive.dc.html", page("reachy_app: Group, live", table_live, live_logic, width=1680, height=1240, extra_css=RA_CSS, mono=True))
