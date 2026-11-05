# Pepper dashboard (pepper_app on :8780) redrawn in the lab style. Full parity with today's Pepper Operator,
# plus one new control: Web search (free conversation only), with an info hover about longer answers.
from build_ra2 import *

I.update({
 "globe": '<circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path>',
 "tablet": '<rect x="4" y="2" width="16" height="20" rx="2"></rect><line x1="12" y1="18" x2="12.01" y2="18"></line>',
 "hand": '<path d="M18 11V6a2 2 0 0 0-4 0v5"></path><path d="M14 10V4a2 2 0 0 0-4 0v6"></path><path d="M10 10.5V6a2 2 0 0 0-4 0v8"></path><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"></path>',
})

P_CSS = r"""
.pchip{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 10px;border-radius:999px;background:var(--sunken);font-size:13px;font-weight:500;white-space:nowrap;font-variant-numeric:tabular-nums}
.pchip .pdot{width:8px;height:8px}
.st{font-size:11.5px;font-weight:700;letter-spacing:.06em;padding:3px 9px;border-radius:7px;white-space:nowrap}
.st.idle{background:var(--sunken);color:var(--muted)}
.st.wait{background:var(--run-tint);color:var(--run)}
.st.think{background:var(--busy-tint);color:var(--brand-text)}
.st.speak{background:#EEF4FF;color:#1D4ED8}
.st.paused{background:#FFE8CC;color:#8A3B00}
.st.stuck{background:var(--danger-tint);color:var(--danger)}
.tg2{display:flex;align-items:center;gap:10px;font-size:14px;font-weight:500;min-height:30px}
.tg2 .grow{flex:1 1 auto;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.tg2.off{opacity:.45}
.info{position:relative;display:inline-flex;width:18px;height:18px;border-radius:50%;align-items:center;justify-content:center;color:var(--muted);cursor:help}
.info .icon{width:16px;height:16px}
.tip{position:absolute;z-index:5;background:#1C1917;color:#F5F2EE;font-size:12.5px;line-height:17px;font-weight:500;padding:7px 10px;border-radius:8px;width:230px;box-shadow:0 10px 24px -10px rgba(0,0,0,.5)}
.tip::after{content:"";position:absolute;width:8px;height:8px;background:#1C1917;transform:rotate(45deg)}
.tip.up{bottom:26px;left:-12px}.tip.up::after{bottom:-4px;left:17px}
.newtag{font-size:10.5px;font-weight:700;letter-spacing:.05em;padding:1px 5px;border-radius:5px;background:#FFF4E0;color:#A84E00;text-transform:uppercase}
.chips4{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.qp{display:flex;align-items:center;gap:6px;text-align:left;padding:6px 9px;border-radius:9px;border:1px solid var(--border);background:#FFFFFF;font:inherit;font-size:13px;line-height:17px;color:var(--ink);cursor:pointer}
.qp b{font-size:10px;letter-spacing:.04em;color:var(--muted);background:var(--sunken);border-radius:4px;padding:0 4px;flex-shrink:0}
.mv{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}
.mv .btn{min-height:34px;font-size:12.5px;padding:0 4px;white-space:normal;line-height:15px}
.pb{max-width:84%;padding:8px 12px;border-radius:12px;font-size:15px;line-height:22px}
.pb .who2{display:block;font-size:11.5px;font-weight:600;color:var(--muted);margin-bottom:1px}
.pb.pep{align-self:flex-start;background:var(--sunken)}
.pb.pep.part{opacity:.65}
.pb.per{align-self:flex-end;background:#EEF4FF}
.pb.woz{align-self:flex-start;background:#FFFFFF;border:1.5px dashed #FD9903}
.ev{align-self:center;font-size:12px;font-weight:500;padding:2px 10px;border-radius:999px;background:var(--warn-tint);color:var(--warn)}
.ev.tap{background:var(--run-tint);color:var(--run)}
.ev.web{background:#EEF4FF;color:#1D4ED8}
.heard{align-self:stretch;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);border:1px dashed #D6CFC5;border-radius:10px;padding:5px 8px}
.wave{display:inline-flex;gap:2px;align-items:center;height:14px}
.wave span{width:3px;border-radius:2px;background:#15803D}
.cam{position:relative;border-radius:10px;overflow:hidden;aspect-ratio:4/3;background:linear-gradient(135deg,#3B342E,#57493E 40%,#6E5E50 70%,#2E2925)}
.fbox{position:absolute;border:2px solid #4ADE80;border-radius:4px}
.livebadge{position:absolute;left:8px;top:8px;background:rgba(0,0,0,.6);color:#FFFFFF;font-size:11px;font-weight:600;padding:2px 7px;border-radius:5px;letter-spacing:.03em}
.tabprev{position:relative;border-radius:12px;overflow:hidden;aspect-ratio:16/10;background:linear-gradient(160deg,#FFF7EB,#FFE7C2);border:6px solid #1C1917;box-sizing:border-box;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;padding:10px}
.tabprev .q{font-weight:700;font-size:15px;color:#1C1917;text-align:center}
.tabopts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;width:100%}
.tabopt{border-radius:10px;padding:12px 4px;text-align:center;font-weight:700;font-size:15px;color:#FFFFFF;cursor:pointer;border:0;font-family:inherit}
.thumbs{display:flex;gap:6px;overflow:hidden}
.thumb{width:62px;height:40px;border-radius:6px;background:linear-gradient(135deg,#E8E3DC,#F4F1EC);border:2px solid transparent;flex-shrink:0;font-size:10px;color:var(--muted);display:flex;align-items:flex-end;padding:2px 4px;box-sizing:border-box}
.thumb.on{border-color:#FD9903}
.drop{border:1.5px dashed #D6CFC5;border-radius:10px;padding:8px 10px;font-size:13px;color:var(--muted);display:flex;align-items:center;gap:8px}
"""

def tgl(label, on, note="", off=False, extra=""):
    import re as _re
    plain = _re.sub(r"<[^>]+>", "", label).replace(" new", "").strip()
    return '<div class="tg2%s"><span class="grow">%s%s</span>%s%s</div>' % (" off" if off else "", label, extra, ('<span class="sub">%s</span>' % note) if note else "", sw(on, plain))

WEBTIP = '<span class="info" tabindex="0" aria-label="About web search">%s<span class="tip up" role="tooltip">Pepper can look things up online. Answers may take a few seconds longer.</span></span>' % ic("info", 16)
WEBTIP_CLOSED = '<span class="info" tabindex="0" aria-label="About web search" title="Pepper can look things up online. Answers may take a few seconds longer.">%s</span>' % ic("info", 16)

def phead(stop_label="Stop everything"):
    return """<header class="top" style="gap: 10px;">
    <img src="img/robot-pepper.png" alt="" style="width: 34px; height: 34px; border-radius: 9px;">
    <span class="ttl" style="margin-left: 0;">Pepper</span>
    <span class="pchip" title="Pepper · NAOqi 2.5.10.7 · Stand · speaker: robot"><span class="pdot" style="background: #15803D;"></span>10.0.4.41 · %s 62%%, charging</span>
    <span class="pchip" title="Pepper's chest tablet"><span class="pdot" style="background: #15803D;"></span>%sTablet live · 1 s</span>
    <span class="rng" title="Pepper's speaker volume">%s<input type="range" min="0" max="100" step="5" value="60" aria-label="Volume"><b>60%%</b></span>
    <span class="spacer"></span>
    <span class="badge" title="GPT key, picked on the Pepper card. A new pick applies at the next Launch."><span class="mono">GPT ··5b12</span></span>
    <span class="badge" title="ElevenLabs key. A new pick applies at the next Launch."><span class="mono">ElevenLabs ··e01b</span></span>
    <button class="btn btn-ghost btn-sm" type="button" aria-haspopup="menu">More</button>
    <a class="btn btn-ghost btn-sm" href="Logs.dc.html">%sLogs</a>
    <button class="btn" type="button" style="background: #B91C1C; color: #FFFFFF; min-height: 40px;">%s%s</button>
  </header>""" % (ic("battery", 14), ic("tablet", 14), ic("vol", 16), ic("logs", 18), ic("stop", 18), stop_label)

QP = [("EN", "Sorry, I didn't catch that. Can you say it again?"), ("EN", "Please look at my screen and choose one."), ("EN", "Great choice!"),
      ("EN", "Hello! I am Pepper. Nice to meet you."), ("EN", "Take your time."), ("EN", "Thank you for talking with me!"),
      ("HE", "סליחה, לא שמעתי. אפשר שוב?"), ("HE", "תסתכלו על המסך שלי ובחרו."), ("HE", "בחירה מצוינת!"), ("HE", "תודה שדיברתם איתי!")]
GVOICES = ["marin", "cedar", "alloy", "ash", "ballad", "coral", "echo", "sage", "shimmer", "verse"]
ELV2 = ["Rachel (English)", "Noa (Hebrew)", "Sarah (English)"]
EXPS = ["Feelings Together (demo) · scripted", "Feelings Together (research demo) · with emoji (not for the demo)", "Free conversation"]

def conv_card(exp="Free conversation", running=True, scripted=False):
    web_off = scripted
    web_note = "Not in the scripted demo" if scripted else ""
    return """<section class="pnl" style="gap: 10px;">
      <div class="pnlh" style="gap: 8px;"><h2>Conversation</h2><span class="st %s">%s</span><span class="spacer"></span><span class="sub" title="The model that answers right now">%s</span></div>
      <div class="frow"><label>Experience</label>%s
        <label>Engine</label>%s
        <label>Language</label>%s
        <label>Voice</label>%s</div>
      %s
      %s
      %s
      %s
      %s
      <div style="display: flex; gap: 8px;">%s%s</div>
      %s
      <div class="srow" style="font-size: 13px; font-weight: 500; color: #6B635A; gap: 14px;"><span>Turns <b style="color: #1C1917;">%s</b></span><span>%s<b style="color: #1C1917;">%s</b></span><span>~<b style="color: #1C1917;">%s</b> ms</span><span>Step <b style="color: #1C1917;">%s</b></span></div>
    </section>""" % (
        "speak" if running else "idle", "SPEAKING" if running else "IDLE",
        "gpt-4.1 reacts · ElevenLabs voice" if scripted else "GPT Realtime 2.1",
        sel(EXPS, exp, aria="Experience").replace("<option>Feelings Together (research demo) · with emoji (not for the demo)</option>", '<option disabled>Feelings Together (research demo) · with emoji (not for the demo)</option>'),
        sel(["ElevenLabs ears + voice, GPT brain", "GPT Realtime (speech to speech)"], "ElevenLabs ears + voice, GPT brain", aria="Engine"),
        sel(["Hebrew", "English", "Auto"], "Hebrew", aria="Language"),
        sel(ELV2, ELV2[1], aria="Voice"),
        '<p class="sub" style="margin-top: -4px; display: block;">%s Experience, Engine, Language and Voice apply at the next Start. Wizard of Oz uses a new voice at once.</p>' % ic("clock", 14) if running else "",
        tgl("Vision", not scripted, "Not in the scripted demo" if scripted else "", off=scripted),
        tgl("AI drives screen", True, "Not in free conversation" if not scripted else "The script drives it", off=True),
        tgl("Gestures", True, "Not in free conversation" if not scripted else "", off=not scripted),
        tgl('Web search <span class="newtag">new</span>', not scripted, web_note, off=web_off, extra=WEBTIP_CLOSED),
        btn("End conversation", "stop", "stop", extra=' style="min-height: 44px; flex: 1 1 auto;"') if running else btn("Start conversation", "primary", "play", extra=' style="min-height: 44px; flex: 1 1 auto;"'),
        btn("Resume AI", "quiet", "play", disabled=True, extra=' style="min-height: 44px;" title="Shown after you speak for Pepper with pause AI on"'),
        ('<div class="srow" style="font-size: 13px; font-weight: 500; color: #6B635A; gap: 8px; flex-wrap: wrap;"><span class="grow">%s</span>%s%s</div>' % (
            "Waiting for an answer · 0:09 · asks again at 0:12" if scripted else "Pepper is speaking",
            btn("Repeat question", "quiet", extra=' style="min-height: 28px; font-size: 12.5px; padding: 0 8px;"'), btn("Skip", "ghost", extra=' style="min-height: 28px; font-size: 12.5px; padding: 0 8px;"'))) if running else "",
        "12" if running else "0", ic("clock", 13), "04:31" if running else "00:00", "840" if running else "–", ("2/9 Choice" if scripted else "–") if running else "–")

woz_card = """<section class="pnl" style="gap: 8px;">
      <div class="pnlh"><h2 style="flex: 1 1 auto;">Wizard of Oz · Say</h2><span class="sub">10 offline</span></div>
      <div class="checks3"><label title="When you talk, the AI stops and waits for Resume AI"><input type="checkbox" checked>pause AI</label><label title="The AI is told what Pepper said"><input type="checkbox" checked>tell AI</label><span class="spacer"></span>%s</div>
      <div class="chips4">%s</div>
      <textarea class="ta" rows="2" dir="auto" placeholder="Type what Pepper says. Enter talks, Shift+Enter is a new line." maxlength="600"></textarea>
      <div style="display: flex; gap: 8px;">%s%s</div>
    </section>""" % (btn("Pause AI", "ghost", extra=' style="min-height: 26px; font-size: 12.5px; padding: 0 8px;" title="Pause the AI without saying anything"'),
                     "".join('<button class="qp" type="button"><b>%s</b><span dir="auto">%s</span></button>' % (l, t) for l, t in QP),
                     btn("Talk", "dark", extra=' style="min-height: 38px; flex: 1 1 auto;"'), btn("Stop", "quiet", "stop", extra=' style="min-height: 38px;" title="Stop speech now"'))

GEST = ["Wave", "Nod yes", "Shake no", "Both arms up", "Arms wide", "Right arm up", "Left arm up", "Open/close hands"]
move_card = """<section class="pnl" style="gap: 8px;">
      <div class="pnlh"><h2 style="flex: 1 1 auto;">Wizard of Oz · Move</h2>%s</div>
      <div class="mv">%s<button class="btn btn-dark" type="button" title="1 m forward, turn, 1 m back, turn. Unplug the charger first; keep 1.5 m clear.">Walking</button></div>
      <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;"><span class="sub">Head</span>%s%s%s<span class="spacer"></span>%s</div>
      <div class="tg2"><span class="grow">Face tracking</span><span class="sub">On now</span>%s</div>
    </section>""" % (btn("Stop motion", "quiet", "stop", extra=' style="min-height: 28px; font-size: 12.5px; padding: 0 8px;"'),
                     "".join('<button class="btn btn-quiet" type="button">%s</button>' % g for g in GEST),
                     *[btn(x, "quiet", extra=' style="min-height: 30px; font-size: 13px; padding: 0 10px;"') for x in ["Left", "Center", "Right"]],
                     btn("Stand", "quiet", extra=' style="min-height: 30px; font-size: 13px; padding: 0 10px;"'), sw(True, "Face tracking"))

chat = """<section class="pnl" style="min-height: 0; flex: 1 1 auto;">
      <div class="pnlh"><h2 style="flex: 1 1 auto;">Live conversation</h2></div>
      <div class="srow" style="font-size: 13.5px; font-weight: 500; color: #6B635A;">%sPepper speaking · mic shut</div>
      <div class="chat" style="gap: 8px;">
        <span class="ev">Conversation started</span>
        <div class="pb pep"><span class="who2">Pepper</span><span dir="rtl" style="display: block;">שלום! אני פפר. איך קוראים לכם?</span></div>
        <div class="pb per"><span class="who2">Person</span>Hi Pepper, I'm visiting from Haifa.</div>
        <div class="pb pep"><span class="who2">Pepper</span>Welcome to Laba Lab! How was the drive?</div>
        <span class="ev">You put slide 2 on the screen</span>
        <div class="heard"><span>Heard, not used: "hmm yeah" (too short)</span><span class="spacer"></span>%s</div>
        <div class="pb per"><span class="who2">Person</span>Who won the football game last night?</div>
        <span class="ev web">%sSearched the web: "football result last night" · 2.8 s</span>
        <div class="pb pep"><span class="who2">Pepper</span>Let me check… Maccabi won 2-1, with a late goal.</div>
        <div class="pb woz"><span class="who2">Pepper · you (Wizard of Oz)</span>Great question! Do you play football too?</div>
        <div class="pb per"><span class="who2">Person</span>Yes, every Friday.</div>
        <span class="ev">You resumed the AI</span>
        <div class="pb pep part"><span class="who2">Pepper</span>Nice! Which position do you</div>
      </div>
    </section>
    <section class="pnl" style="flex: 0 0 210px; min-height: 0;">
      <div class="pnlh"><h2 style="flex: 1 1 auto;">Event log</h2>%s</div>
      <div class="log" role="log">
        <div><span class="t">14:31:02</span> INFO  options: web_search on</div>
        <div><span class="t">14:31:40</span> INFO  options: vision on</div>
        <div><span class="t">14:32:15</span> INFO  web_search "football result last night" 2.8 s, 3 sources</div>
        <div class="w"><span class="t">14:32:30</span> WARNING heard, not used: "hmm yeah" (too short)</div>
        <div><span class="t">14:32:51</span> INFO  woz: say "Great question!..." via ElevenLabs voice · AI paused</div>
        <div><span class="t">14:33:02</span> INFO  woz: resume AI</div>
      </div>
    </section>""" % (ic("mic", 15), btn("Accept", "quiet", extra=' style="min-height: 26px; font-size: 12.5px; padding: 0 8px;"'), ic("globe", 13),
                     btn("Copy logs", "ghost", "copy", extra=' style="min-height: 26px; font-size: 12.5px; padding: 0 8px;"'))

right = """<section class="pnl" style="gap: 8px;">
      <div class="pnlh" style="gap: 8px;"><h2 style="flex: 1 1 auto;">Pepper's camera</h2><span class="sub">frame sent to AI 2 s ago</span></div>
      <div class="cam"><span class="livebadge">LIVE · 640×480 · top</span><span class="fbox" style="left: 38%%; top: 24%%; width: 22%%; height: 30%%;"></span></div>
      <div style="display: flex; gap: 8px; align-items: center;">%s<label class="check" style="align-items: center;"><input type="checkbox" checked>faces</label><span class="spacer"></span>%s</div>
    </section>
    <section class="pnl" style="gap: 8px;">
      <div class="pnlh" style="gap: 8px;"><h2 style="flex: 1 1 auto;">On Pepper's screen</h2><span class="sub">by you · last tap: none yet</span></div>
      <div class="tabprev" style="background: #000000; padding: 0;"><div style="width: 100%%; height: 100%%; background: linear-gradient(135deg,#FDE3B8,#F6C27A 60%%,#D98B2B); display: flex; align-items: flex-end; padding: 10px; box-sizing: border-box; color: #1C1917; font-weight: 700;">Slide 2: Our robots</div></div>
      <p class="sub">On a choice page, click an option to tap for the person.</p>
      <div style="display: flex; gap: 6px; align-items: center;">%s%s</div>
      <div style="display: flex; gap: 6px; align-items: center;">%s<span class="badge" style="height: 30px;">2/6</span>%s<span class="spacer"></span>%s%s</div>
      <div class="thumbs"><span class="thumb">1</span><span class="thumb on">2</span><span class="thumb">3</span><span class="thumb">4</span><span class="thumb">5</span><span class="thumb">6</span></div>
      <div class="drop">%s<span>Drop images or a PDF here, or <a href="#upload">upload</a>. The AI can also use them as pictures.</span></div>
    </section>""" % (sel(["Top", "Bottom"], "Top", aria="Camera", style="width: 110px; height: 32px;"), btn("Save", "ghost", "download", extra=' style="min-height: 30px; font-size: 13px; padding: 0 8px;"'),
                     sel(["Lab tour · 6 slides", "Feelings faces · 4 slides"], "Lab tour · 6 slides", aria="Presentation", style="height: 34px;"), btn("Delete", "ghost", "trash", extra=' style="min-height: 32px; font-size: 13px; padding: 0 8px;"'),
                     btn("Prev", "quiet", "left", extra=' style="min-height: 30px; font-size: 13px; padding: 0 8px;"'), btn("Next", "quiet", extra=' style="min-height: 30px; font-size: 13px; padding: 0 8px;"'),
                     btn("Home", "ghost", extra=' style="min-height: 30px; font-size: 13px; padding: 0 8px;"'), btn("Clear", "ghost", extra=' style="min-height: 30px; font-size: 13px; padding: 0 8px;"'), ic("upload", 16))

dash = """<div class="app">
  %s
  <main style="display: grid; grid-template-columns: 420px minmax(0,1fr) 400px; gap: 14px; padding: 14px 18px 18px; box-sizing: border-box; height: 1336px;">
    <div style="display: flex; flex-direction: column; gap: 12px; min-height: 0;">%s%s%s</div>
    <div style="display: flex; flex-direction: column; gap: 12px; min-height: 0;">%s</div>
    <div style="display: flex; flex-direction: column; gap: 12px; min-height: 0;">%s</div>
  </main>
</div>""" % (phead(), conv_card(), woz_card, move_card, chat, right)
write("PepperDash.dc.html", page("Pepper dashboard", dash, "renderVals() { return { yes: true }; }", width=1680, height=1400, extra_css=RA_CSS + P_CSS, mono=True))

# ---------------------------------------------------------------- states
def pc(dot, text, extra=""):
    return '<span class="pchip"><span class="pdot" style="background: %s;"></span>%s%s</span>' % (dot, text, extra)

st_cells = [
 cell("Web search: the hover", '<div class="pnl" style="padding-top: 64px; padding-right: 70px;">%s</div>' % tgl('Web search <span class="newtag">new</span>', True, extra=WEBTIP)),
 cell("Web search: looking it up", '<div class="pnl" style="gap: 8px;"><div class="srow"><span class="st think">SEARCHING</span><span class="sub">Pepper is looking it up online · 2 s</span></div><div class="pb pep" style="max-width: 100%;"><span class="who2">Pepper</span>Let me check…</div><span class="ev web">' + ic("globe", 13) + 'Searched the web: "Beer Sheva weather today" · 3.1 s</span></div>'),
 cell("Web search: not available", '<div class="pnl" style="gap: 8px;">%s%s%s</div>' % (
     tgl('Web search', False, "Not in the scripted demo", off=True, extra=WEBTIP_CLOSED),
     tgl('Web search', False, "No internet on this network", off=True, extra=WEBTIP_CLOSED),
     tgl('Web search', False, "This key can't search", off=True, extra=WEBTIP_CLOSED))),
 cell("Web search: failed", '<div class="pnl" style="gap: 8px;"><span class="ev web" style="background: #FEF2F2; color: #B91C1C;">Web search failed: timeout. Pepper answered without it.</span><p class="sub">Pepper never waits more than 8 s; it answers from what it knows and says so.</p></div>'),
 cell("Robot link", '<div class="pnl" style="gap: 8px; align-items: flex-start;">%s%s%s%s</div>' % (
     pc("#A84E00", "Starting its agent… up to 60 s"), pc("#B91C1C", "The agent's connection dropped · trying again in 20 s"),
     pc("#B91C1C", "Dashboard server stopped · retrying"), n("err", "alert", "The agent never called back on port 8782. Is Windows Firewall blocking Python on this network?", btn("Allow Pepper", "dark", extra=SM)))),
 cell("Tablet link", '<div class="pnl" style="gap: 8px; align-items: flex-start;">%s%s<span class="pchip">%sTablet lost · 6 s ago · people see nothing%s</span></div>' % (
     pc("#15803D", "Tablet live · 1 s"), pc("#B91C1C", "Tablet not connected yet · people see nothing", btn("Reload", "dark", extra=' style="min-height: 24px; font-size: 12px; padding: 0 8px; margin-left: 4px;"')), "", btn("Reload", "dark", extra=' style="min-height: 24px; font-size: 12px; padding: 0 8px; margin-left: 4px;"'))),
 cell("Keys", '<div class="pnl" style="gap: 8px;"><span class="badge" style="background: #FEF2F2; color: #B91C1C;">No GPT key · add one on the Pepper card</span><span class="badge" style="background: #FFF1D6; color: #8A3B00;">No ElevenLabs key · Wizard of Oz uses the OpenAI voice</span><p class="sub">The scripted demo needs both keys. Free conversation needs GPT.</p></div>'),
 cell("Start refused", '<div class="pnl" style="gap: 6px;">%s%s%s</div>' % (n("err", "key", "The scripted demo listens with ElevenLabs. Add an ElevenLabs key."), n("err", "alert", "Pepper isn't connected yet. Wait for the robot chip to turn green."), n("warn", "info", "Pick an ElevenLabs voice first."))),
 cell("AI stuck", '<div class="pnl" style="gap: 8px;"><div class="warnbar err" style="border-radius: 10px; border: 1px solid #F2C4C4; padding: 10px 12px;">%s<span>The AI stopped answering. Speak for Pepper from Wizard of Oz.</span><span class="spacer"></span>%s</div><div class="srow"><span class="st stuck">AI STUCK</span><span class="sub">The Wizard of Oz cards flash</span></div></div>' % (ic("alert", 18), btn("Restart AI", "dark", extra=SM)), span=2),
 cell("Paused by you", '<div class="pnl" style="gap: 8px;"><div class="srow"><span class="st paused">PAUSED · YOU</span><span class="sub">AI paused · you have the floor</span></div>%s</div>' % btn("Resume AI", "primary", "play", extra=' style="min-height: 40px;"')),
 cell("Turn info (scripted demo)", '<div class="pnl" style="gap: 8px;"><div class="srow"><span class="st wait">WAITING FOR ANSWER</span></div><p class="sub">Waiting for an answer · 0:09 · asks again at 0:12</p><div style="display: flex; gap: 6px;">%s%s</div></div>' % (btn("Repeat question", "quiet", extra=SM), btn("Skip", "ghost", extra=SM))),
 cell("Scripted demo: what's used", '<div class="pnl" style="gap: 8px;">%s%s%s%s<p class="sub">Settings it ignores are greyed with the reason. Engine picks only the voice: the demo always listens with ElevenLabs.</p></div>' % (
     tgl("Vision", False, "Not in the scripted demo", off=True), tgl("AI drives screen", True, "The script drives it", off=True), tgl("Gestures", True), tgl("Web search", False, "Not in the scripted demo", off=True, extra=WEBTIP_CLOSED)), span=2),
 cell("Walking while charging", '<div class="pnl">%s</div>' % n("warn", "battery", "Pepper is charging. Unplug the charger and close the flap, then press Walking again.")),
 cell("Empty states", '<div class="pnl" style="gap: 8px;"><p class="muted" style="margin: 0; text-align: center;">Press Start conversation and Pepper begins talking.</p><div class="cam" style="background: #2A2521; display: flex; align-items: center; justify-content: center; color: #A79F95; font-size: 13px; aspect-ratio: 16/7;">No camera picture yet</div><p class="sub">No presentations yet: upload one.</p><p class="sub">No ElevenLabs voices (key?)</p></div>'),
 cell("Tablet not connected", '<div class="pnl"><div class="tabprev" style="background: #2A2521; border-color: #1C1917;"><span style="color: #FFFFFF; font-weight: 700;">Screen not connected</span><span style="color: #D8D1C7; font-size: 13px;">People in front of Pepper see nothing</span></div></div>'),
 cell("Tablet emoji check (More menu)", '<div class="pnl" style="gap: 8px;"><div style="display: flex; gap: 6px;">%s%s</div><div class="field"><label>Which numbers show as empty boxes or wrong?</label><input class="input" type="text" value="4, 17, 30"></div><p class="sub">45 candidates · 42 allowed now</p></div>' % (btn("Emoji test", "quiet", extra=SM), btn("Mark broken", "dark", extra=SM))),
 cell("More menu", '<div class="pnl" style="gap: 2px; padding: 6px;">%s</div>' % "".join('<button class="btn btn-ghost" type="button" style="justify-content: flex-start; min-height: 36px; font-size: 14px;">%s</button>' % t for t in ["Tablet emoji check", "Put a message or choice on the screen", "Lab facts (what Pepper may say about the lab)", "Rehearse without the robot"])),
 cell("Put on the screen yourself", '<div class="pnl" style="gap: 8px;"><div class="seg"><button type="button" class="on">Message</button><button type="button">Choice</button></div><input class="input" type="text" value="Welcome to Laba Lab!" maxlength="300"><div style="display: flex; justify-content: flex-end;">%s</div></div>' % btn("Show", "dark", extra=SM)),
 cell("Uploads and deletes", '<div class="pnl" style="gap: 6px;"><p class="sub">Turning tour.pdf into slides… 7/12</p>%s%s<div class="note"><div>Delete "Lab tour" (6 slides) from this laptop?<div class="nacts">%s%s</div></div></div></div>' % (
     n("err", "alert", "Only images and PDFs. Save PowerPoint as PDF first."), n("err", "alert", "hero.png is over 15 MB."), btn("Delete", "stop", extra=SM), btn("Cancel", "ghost", extra=SM))),
 cell("Toasts", '<div style="display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start;">%s</div>' % "".join('<div class="toast" style="position: static; transform: none;%s">%s</div>' % (' background: #7F1D1D;' if b else "", t) for t, b in [
     ("No conversation is running.", 1), ("Pepper isn't connected.", 1), ("Couldn't speak it: the voice service timed out.", 1), ("Only Stand was tested on this robot.", 1), ("42 emoji allowed on Pepper's screen", 0), ("No camera picture yet", 0), ("The dashboard server isn't answering", 1)]), span=3),
]

TABPAGES = ''.join([
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px; gap: 4px;"><b style="font-size: 12px;">Hi, I\'m Pepper!</b><span style="font-size: 10px;">Come closer and say hello</span><img src="img/labalab-logo.png" alt="" style="height: 9px; position: absolute; bottom: 4px;"></div><span class="sub">Welcome</span></div>',
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px; gap: 4px;"><b style="font-size: 18px;">★</b><span style="font-size: 11px;">Welcome to Laba Lab!</span><img src="img/labalab-logo.png" alt="" style="height: 9px; position: absolute; bottom: 4px;"></div><span class="sub">Message</span></div>',
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px; background: #000000;"><span style="color: #FFFFFF; font-size: 11px;">slide, no logo</span></div><span class="sub">Slide</span></div>',
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px; background: #000000;"></div><span class="sub">Blank</span></div>',
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px; display: grid; grid-template-columns: repeat(5,1fr); padding: 6px; gap: 2px; font-size: 9px;">' + ''.join('<span>%d</span>' % k for k in range(1, 16)) + '</div><span class="sub">Emoji test</span></div>',
 '<div style="display: flex; flex-direction: column; gap: 4px;"><div class="tabprev" style="border-width: 4px;"><b style="font-size: 12px;">Hi, I\'m Pepper!</b><span style="position: absolute; right: 6px; bottom: 6px; width: 7px; height: 7px; border-radius: 50%; background: #DC2626;"></span></div><span class="sub">Lost link: a red dot, no text</span></div>'])

extra_cells = [
 cell("Before Start", conv_card(exp="Free conversation", running=False) + '<p class="sub" style="margin-top: 6px;">Start is busy while it opens the mic and the screen.</p>'),
 cell("Scripted demo running", conv_card(exp="Feelings Together (demo) · scripted", running=True, scripted=True)),
 cell("Mic line", '<div class="pnl" style="gap: 8px;"><div class="srow" style="font-size: 13.5px; color: #15803D;"><span class="wave"><span style="height: 6px;"></span><span style="height: 12px;"></span><span style="height: 9px;"></span><span style="height: 14px;"></span></span>listening</div><div class="meter" style="flex: none; height: 5px;"><span style="width: 42%;"></span></div><span class="sub" style="color: #15803D;">hearing: "and what\'s the weather like in Beer Sh"</span><span class="sub">Pepper speaking · mic shut</span><span class="sub">Pepper\'s turn · mic shut</span><span class="sub">AI paused · you have the floor</span></div>'),
 cell("Robot not connected", '<div class="pnl" style="gap: 8px;"><div style="display: flex; gap: 6px; flex-wrap: wrap;">%s%s</div><div class="mv" style="opacity: .45;">%s</div><span class="rng" style="opacity: .45;">%s<input type="range" disabled value="60" aria-label="Volume"></span><p class="sub">Moves, volume and camera wait for the robot.</p></div>' % (pc("#B91C1C", "Started without a robot address"), pc("#A84E00", "Laptop audio only (test mode)"), "".join('<button class="btn btn-quiet" type="button" disabled="{{yes}}">%s</button>' % g for g in ["Wave", "Nod yes", "Shake no", "Walking", "Stand"]), ic("vol", 16))),
 cell("Voice list follows the Engine", '<div class="pnl" style="gap: 8px;"><div class="frow"><label>Engine</label>%s<label>Voice</label>%s</div></div>' % (sel(["GPT Realtime (speech to speech)"], aria="Engine"), sel(GVOICES, "marin", aria="Voice"))),
 cell("Tablet pages", '<div class="pnl"><div style="display: grid; grid-template-columns: repeat(6, minmax(0,1fr)); gap: 8px;">%s</div></div>' % TABPAGES, span=3),
 cell("Choice on the screen yourself", '<div class="pnl" style="gap: 8px;"><div class="seg"><button type="button">Message</button><button type="button" class="on">Choice</button></div><input class="input" type="text" value="Which robot do you like?" maxlength="120"><div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px;"><input class="input" type="text" value="Pepper" maxlength="40"><input class="input" type="text" value="NAO" maxlength="40"><input class="input" type="text" placeholder="Option 3 (optional)" maxlength="40"><input class="input" type="text" placeholder="Option 4 (optional)" maxlength="40"></div><div style="display: flex; justify-content: flex-end;">%s</div></div>' % btn("Show", "dark", extra=SM)),
 cell("Walking", '<div class="pnl" style="gap: 8px;"><div class="pb woz" style="max-width: 100%;"><span class="who2">Pepper · you (Wizard of Oz)</span><span dir="rtl" style="display: block;">אני הולך להסתובב קצת, תפנו לי מקום!</span></div><span class="ev" style="align-self: flex-start;">Gesture: walking</span><span class="sub" style="color: #8A3B00;">The walk line couldn\'t be made; Pepper walks anyway.</span></div>'),
 cell("No speaker", n("warn", "vol", "Pepper\'s speaker can\'t play audio: the AI can\'t talk. Wizard of Oz still works in Pepper\'s own voice (English).")),
 cell("Web search rules", '<div class="pnl" style="gap: 6px;"><span class="sub">Questions about the lab still use only the lab facts.</span><span class="sub">Applies at once, also mid-conversation.</span><span class="sub">While it searches, the "AI stopped answering" alarm waits.</span>%s</div>' % tgl("Web search", False, "No GPT key", off=True, extra=WEBTIP_CLOSED)),
 cell("Log and AI recovery", '<div class="pnl" style="gap: 6px;"><span class="sub">Copied</span><span class="sub" style="color: #B91C1C;">Copy failed</span><span class="ev" style="align-self: flex-start;">The connection dropped and was restored (last 20 turns kept)</span></div>'),
 cell("More upload messages", '<div style="display: flex; flex-direction: column; gap: 8px; align-items: flex-start;">%s</div>' % "".join('<div class="toast" style="position: static; transform: none;%s">%s</div>' % (' background: #7F1D1D;' if b else "", t) for t, b in [("Couldn\'t read tour.pdf: it is password protected.", 1), ("Upload a presentation first", 0), ("Lab tour (12 slides) is ready and selected", 0), ("No presentation selected: the AI has no slides now", 1)])),
]
st_cells = st_cells + extra_cells
write("PepperStates.dc.html", page("Pepper dashboard states", '<div class="app" style="padding: 32px; box-sizing: border-box;"><div style="display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 24px 20px; align-items: start;">%s</div></div>' % "\n".join(st_cells),
                                   "renderVals() { return { yes: true }; }", width=1600, height=3150, extra_css=RA_CSS + P_CSS, mono=True))

# ---------------------------------------------------------------- simulator (rehearse without the robot)
sim = """<div class="app">
  <header class="top" style="gap: 10px;">
    <img src="img/robot-pepper.png" alt="" style="width: 34px; height: 34px; border-radius: 9px;"><span class="ttl" style="margin-left: 0;">Pepper rehearsal</span><span class="pchip">No robot</span>
    <span class="spacer"></span><a class="btn btn-ghost btn-sm" href="PepperDash.dc.html">%sOperator dashboard</a>
  </header>
  <main style="display: grid; grid-template-columns: 460px minmax(0,1fr); gap: 14px; padding: 14px 18px 18px; box-sizing: border-box;">
    <div style="display: flex; flex-direction: column; gap: 12px;">
      <section class="pnl"><div class="pnlh"><h2>Pepper's chest tablet</h2><span class="sub">tap like a visitor</span></div>
        <div class="tabprev"><span class="q">How do you feel today?</span><div class="tabopts"><button class="tabopt" type="button" style="background: #15803D;">Happy</button><button class="tabopt" type="button" style="background: #1D4ED8;">Sad</button><button class="tabopt" type="button" style="background: #A84E00;">Surprised</button></div></div></section>
      <section class="pnl" style="gap: 6px;"><div class="pnlh"><h2>Pepper's body</h2><span class="sub">empty: No movements yet.</span></div><p class="sub">14:40:02 wave</p><p class="sub">14:40:15 nod yes</p><p class="sub">14:40:31 arms wide</p></section>
    </div>
    <div style="display: flex; flex-direction: column; gap: 12px;">
      <section class="pnl" style="gap: 10px;">
        <div style="display: grid; grid-template-columns: 1.4fr 1.2fr 1fr; gap: 8px;">%s%s%s</div>
        <div style="display: flex; gap: 8px;">%s%s%s%s</div>
        <p class="sub">Waiting for the visitor's answer · 6 s · Step 2 of 9: Choice · turns 3</p>
      </section>
      <section class="pnl" style="flex: 1 1 auto;"><div class="pnlh"><h2>Conversation</h2></div>
        <div class="chat" style="gap: 8px;"><div class="pb pep"><span class="who2">Pepper</span>Hi! I'm Pepper. How do you feel today? Choose on my screen.</div><div class="heard"><span>Heard, not used: "hmm"</span></div><span class="ev tap">Tapped the screen: Happy</span><div class="pb per"><span class="who2">Visitor</span>Happy, it's my birthday!</div><div class="pb woz"><span class="who2">Pepper (operator)</span>Happy birthday!</div></div>
        <p class="sub">Held until Pepper finishes talking: "I feel great"</p>
        <p class="sub">Typed text counts as a finished sentence; fillers like "hmm" are ignored. Other states: Off · Pepper is thinking… · Pepper is talking · AI paused · AI is stuck (see the dashboard log).</p>
        <p class="sub" style="color: #B91C1C;">Start a conversation first.</p>
        <div class="steer"><input class="input" type="text" placeholder="The visitor says…" aria-label="The visitor says"><button class="btn btn-dark btn-sm" type="button">Say</button></div>
      </section>
    </div>
  </main>
</div>""" % (ic("ext", 16), sel(["Feelings Together (demo) · scripted", "Free conversation"], aria="Experience"), sel(["ElevenLabs ears + voice, GPT brain", "GPT Realtime (speech to speech)"], aria="Engine"),
             sel(["Auto (English, Hebrew if spoken to)", "English", "Hebrew"], aria="Language"),
             btn("Start conversation", "primary", "play", disabled=True, extra=' style="min-height: 38px;" title="Running"'), btn("Stop", "quiet", "stop", extra=' style="min-height: 38px;"'),
             btn("Repeat question", "quiet", extra=' style="min-height: 38px;"'), btn("Skip", "ghost", extra=' style="min-height: 38px;"'))
write("PepperSim.dc.html", page("Pepper rehearsal without the robot", sim, "renderVals() { return { yes: true }; }", width=1400, height=700, extra_css=RA_CSS + P_CSS, mono=True))
