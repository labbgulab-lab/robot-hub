from build_hub import *

# ---------------------------------------------------------------- Hub (every day)
nao_body = """<div class="postures">
            <button class="btn btn-quiet" type="button" onClick="{{sit}}" title="Sit on the floor, then motors off">Sit</button>
            <button class="btn btn-quiet" type="button" onClick="{{lie}}" title="Lie on its back, then motors off">Lie down</button>
            <button class="btn {{standCls}}" type="button" onClick="{{stand}}" title="Stand up, motors stay on">{{standText}}</button>
          </div>
          <p class="note {{pnCls}}">{{pnText}}</p>"""

cards = [
  card(R, "reachy1", pill("run", "Running"), metric("ip", "10.0.4.21"), "Ready, control loop 50 Hz",
       ai(KEYS[0], KEYS, "Used when it talks alone. Applies next Talk."), DISC + btn("Open", "primary", grow=True, href="RATalk.dc.html"), "s-run", delay=0),
  card(R, "reachy3", pill("conn", "Connected"), metric("ip", "10.0.4.23"), "Ready",
       """<div class="ai"><p class="lbl">Speaks through</p><select class="select def" aria-label="Speaks through" onChange="{{pickKey}}"><option selected>%s</option>%s</select><p class="sub"><span class="tag">Default</span>First Gemini key. Used when it talks alone.</p></div>""" % (DEF, "".join("<option>%s</option>" % k for k in KEYS)),
       DISC + btn("Talk", "primary", grow=True, href="RATalk.dc.html"), "s-conn", delay=40),
  card(R, "reachy6", pill("near", "Available"), metric("ip", "10.0.4.26"), "Found on HOT-WiFi",
       ai(DEF, [DEF] + KEYS, default=True),
       btn("Connect", "quiet", "link", grow=True) + btn("Talk", "primary", grow=True, href="RATalk.dc.html"), "", delay=80),
  card(F, "Furhat", pill("conn", "Connected"), metric("ip", "10.0.4.30"), "Studio running. Voice: Matthew",
       ai(KEYS[0], KEYS), DISC + btn("Open Studio", "primary", "ext", grow=True), "s-conn", delay=120),
  card(N, "NAO", pill("conn", "Connected"), metric("batt", "78%"), "Broker answering",
       nao_body, DISC + naoapp(), "s-conn", delay=160),
  card(P, "Pepper", pill("run", "Running"), metric("batt", "62%"), "System running",
       pepper_ai(sub="Applies next start"),
       DISC + btn("Open dashboard", "primary", "ext", grow=True, href="PepperDash.dc.html"), "s-run", delay=200),
]

hub_body = """<div class="app">
  %s
  <main class="main">
    <div class="pagehead">
      <h1 class="h1">Robots</h1>
      <div class="counts"><span><b>6</b> of 9 nearby</span><span><span class="d" style="background: #1D4ED8;"></span><b>5</b> connected</span><span><span class="d" style="background: #15803D;"></span><b>2</b> running</span><span>Updated 14:06:41</span></div>
    </div>

    <section class="band" aria-labelledby="rapp">
      <div class="tiles" aria-hidden="true"><img src="img/%s" alt=""><img src="img/%s" alt=""><img src="img/%s" alt=""></div>
      <div style="flex: 1 1 260px; display: flex; flex-direction: column; gap: 4px;">
        <h2 id="rapp" class="h2">Reachy app</h2>
        <div class="modes"><span class="mode">Talk</span><span class="mode">Group talk</span><span class="mode">Interrupt</span><span class="mode">Free talk</span><span class="mode">Choir</span><span class="mode">Wizard of Oz</span></div>
      </div>
      <span class="muted small">reachy1 running</span>
      <a class="btn btn-quiet" href="RATable.dc.html">Open</a>
    </section>

    <div class="grid">
        %s
    </div>

    <div class="away">
      <span>Not nearby</span>
      <span class="ghost"><img src="img/%s" alt="">reachy2</span>
      <span class="ghost"><img src="img/%s" alt="">reachy5</span>
      <span class="spacer"></span>
      <span class="setuprow"><img src="img/%s" alt="">Reachy Mini Lite (USB)<a class="btn btn-quiet btn-sm" href="Setup.dc.html">Set up</a></span>
    </div>
  </main>
  <sc-if value="{{toast}}" hint-placeholder-val="{{false}}">
    <div class="toast" role="status">%s{{toastText}}</div>
  </sc-if>
</div>""" % (topbar(interactive=True), R, R, R, "\n        ".join(cards), R, R, L, ic("check", 18))

hub_logic = """constructor(props) {
    super(props);
    this.state = { auto: true, armed: false, pn: 'ok', pt: 'Sitting, motors off. Hottest joint: left knee 54&nbsp;°C', toast: '' };
  }
  renderVals() {
    var self = this, s = this.state;
    function say(t) { self.setState({ toast: t }); }
    return {
      yes: true,
      autoCls: s.auto ? 'on' : '', autoOn: s.auto ? 'true' : 'false',
      toggleAuto: function () { self.setState({ auto: !self.state.auto }); },
      standCls: s.armed ? 'btn-arm' : 'btn-quiet',
      standText: s.armed ? 'Confirm' : 'Stand up',
      pnCls: s.pn, pnText: s.pt,
      sit: function () { self.setState({ armed: false, pn: 'ok', pt: 'Sitting, motors off. Hottest joint: left knee 54&nbsp;°C' }); },
      lie: function () { self.setState({ armed: false, pn: 'ok', pt: 'Lying down, motors off. Hottest joint: left hip 51&nbsp;°C' }); },
      stand: function () {
        if (!self.state.armed) { self.setState({ armed: true, pn: 'warn', pt: 'Motors stay on. Someone next to NAO? Tap Confirm.' }); }
        else { self.setState({ armed: false, pn: 'ok', pt: 'Standing, motors on. Hottest joint: right ankle 57&nbsp;°C' }); }
      },
      pickKey: function (e) { say('reachy3 will speak through ' + e.target.value.split(' · ')[0]); },
      toast: !!s.toast, toastText: s.toast
    };
  }"""

write("Hub.dc.html", page("Every day: robots", hub_body, hub_logic, height=1000))

# ---------------------------------------------------------------- Robot panel (per robot)
bg = """<main class="main dim" aria-hidden="true">
    <div class="pagehead"><h1 class="h1">Robots</h1></div>
    <div class="grid"><div class="ph"></div><div class="ph"></div><div class="ph"></div><div class="ph"></div><div class="ph"></div><div class="ph"></div></div>
  </main>"""

panel = """<div class="app">
  %s
  %s
  <div class="scrim" aria-hidden="true"></div>
  <aside class="sheet" aria-label="reachy1 details">
    <div class="sheet-head">
      <img class="tile" src="img/%s" alt="">
      <div class="who"><p class="name">reachy1</p>%s</div>
      <a class="btn btn-ghost btn-sm btn-icon" href="Hub.dc.html" aria-label="Close">%s</a>
    </div>
    <div class="sheet-body">
      <section class="sec">
        <p class="detail" style="color: #1C1917; font-size: 15px;">Ready, control loop 50 Hz</p>
        <dl class="facts">
          <dt>Robot</dt><dd>Reachy Mini (wireless)</dd>
          <dt>Address</dt><dd>10.0.4.21 on HOT-WiFi</dd>
          <dt>Listens with</dt><dd>Wireless Mic Rx (this laptop)</dd>
          <dt>Robot software</dt><dd>Daemon 1.13.0 · reachy_chat on the robot</dd>
          <dt>Uses on this laptop</dt><dd>Microphone</dd>
          <dt>Seen</dt><dd>2 s ago</dd>
        </dl>
        <div style="display: flex; gap: 8px;">%s%s</div>
      </section>

      <section class="sec">
        %s
        <p class="sub"><a href="Settings.dc.html">Add a key</a></p>
      </section>

      <section class="sec">
        <div class="sechd"><h3 class="lbl" style="flex: 1 1 auto;">Add WiFi</h3><span class="tag tag-dark">Lab staff</span></div>
        <div class="field"><label for="ssid">WiFi name</label><input id="ssid" class="input" type="text" value="Lab Phone"></div>
        <div class="field"><label for="pw">Password</label><input id="pw" class="input" type="password" value="password1"></div>
        <label class="check"><input type="checkbox">Open WiFi, no password <span class="muted">(Reachy only)</span></label>
        <label class="check"><input type="checkbox">Save only, don't move now (lab WiFi fallback) <span class="muted">(Reachy only)</span></label>
        <p class="sub" style="font-size: 13.5px;">Knows: <b style="color: #1C1917;">HOT-WiFi</b> (connected now) · Lab Phone · Old Phone (won't join by itself) · reachy-mini-ap (its own setup network)</p>
        <p class="sub">Turn the hotspot on first, 2.4 GHz.</p>
        <div style="display: flex;"><button class="btn btn-dark" type="button">Join</button></div>
        <p class="note ok">%sreachy1 joined "Lab Phone" and will remember it. Move this laptop there too.</p>
      </section>
    </div>
  </aside>
</div>""" % (topbar(), bg, R, pill("run", "Running"), ic("x", 18),
             btn("Disconnect", "quiet", "unlink", extra=' style="min-height: 40px;"'), btn("Copy details", "ghost", "copy", extra=' style="min-height: 40px;"'),
             ai(KEYS[0], KEYS, "Used when it talks alone. Groups use each robot's voice service. Applies next Talk."), ic("check", 18))

write("RobotPanel.dc.html", page("Robot details", panel, height=900))

# ---------------------------------------------------------------- Network panel
def acc(img, title, items, open_=False, ordered=True):
    tag = "ol" if ordered else "ul"
    body = '<div class="accbody"><%s>%s</%s></div>' % (tag, "".join("<li>%s</li>" % i for i in items), tag) if open_ else ""
    chev = ic("chev", 16, extra=" margin-left: auto;%s" % (" transform: rotate(180deg);" if open_ else ""))
    return '<div class="acc"><div class="acchd"><img src="img/%s" alt="">%s%s</div>%s</div>' % (img, title, chev, body)

net = """<div class="app">
  %s
  %s
  <div class="scrim" aria-hidden="true"></div>
  <aside class="sheet" style="width: 540px;" aria-label="Network">
    <div class="sheet-head">
      <span style="width: 40px; height: 40px; border-radius: 10px; background: #FFF1D6; color: #8A3B00; display: flex; align-items: center; justify-content: center;">%s</span>
      <div class="who"><p class="name">Network</p><span class="pill p-warn"><span class="dot"></span>Needs attention</span></div>
      <a class="btn btn-ghost btn-sm btn-icon" href="Hub.dc.html" aria-label="Close">%s</a>
    </div>
    <div class="sheet-body">
      <section class="sec">
        <p class="note warn">%s<span>This laptop is on <b>eduroam</b>. The robots are on <b>HOT-WiFi</b>.</span></p>
        <div style="display: flex; gap: 8px; flex-wrap: wrap;">%s%s</div>
        <p class="sub">%sLooking on 10.0.4.0/24 · <a href="#scan">Scan now</a></p>
      </section>

      <section class="sec">
        <h3 class="lbl">Set up</h3>
        <ol class="steps">
          <li><span class="num">1</span><div class="stepbody"><b>This laptop on HOT-WiFi</b><ul><li>Turn off auto-join for other WiFi.</li><li>Robots show up in about 30 s.</li></ul></div></li>
          <li><span class="num">2</span><div class="stepbody"><b>Each robot on HOT-WiFi, once</b>
            %s%s%s%s
          </div></li>
          <li><span class="num">3</span><div class="stepbody"><b>Still missing?</b><ul><li>Scan now.</li><li>Turn the robot off and on.</li></ul></div></li>
        </ol>
      </section>

      <section class="sec">
        <h3 class="lbl">Outside the lab</h3>
        <p class="detail" style="color: #1C1917;">One phone hotspot for the laptop and the robots. 2.4 GHz, a plain name, up to 5 devices.</p>
        <div style="display: flex;"><a class="btn btn-quiet btn-sm" href="Hotspot.dc.html">Plan a hotspot demo</a></div>
      </section>
    </div>
  </aside>
</div>""" % (topbar(net="bad"), bg, ic("wifi", 20), ic("x", 18), ic("alert", 18),
             btn("Open WiFi settings", "primary", "wifi", extra=' style="min-height: 40px;"'), btn("Check again", "quiet", "refresh", extra=' style="min-height: 40px;"'), ic("radar", 14),
             acc(R, "Reachy Mini", ["New robot: lab staff bring it up.", "Older robot: Add WiFi in its details, tick Lab WiFi."], open_=True),
             acc(N, "NAO", ["Plug NAO into this laptop with a cable.", "Press its chest button: it says its address.", "Open that address, Network, pick HOT-WiFi.", "No luck? Lab staff: connmanctl over SSH."], open_=True),
             acc(F, "Furhat", ["On Furhat's own screen: Settings, WiFi, HOT-WiFi.", "Turn it off and on."], open_=True),
             acc(P, "Pepper", ["On the tablet: Settings, WiFi, HOT-WiFi.", "Never use Advanced Settings."], open_=True))

write("Network.dc.html", page("Network", net, height=1240))
