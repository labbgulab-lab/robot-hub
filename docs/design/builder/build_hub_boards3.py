from build_hub import *

def n(kind, icon, text):
    return '<p class="note %s">%s<span>%s</span></p>' % (kind, ic(icon, 18), text)

left = """<main class="main" style="max-width: none; margin: 0; width: 720px; padding: 32px 40px; box-sizing: border-box;">
    <h1 class="h1" style="font-size: 20px;">Add WiFi: every result</h1>
    <div style="display: flex; flex-direction: column; gap: 10px;">
      <p class="cap" style="margin: 8px 0 0;">Before Join</p>
      %s
      %s
      <p class="cap" style="margin: 8px 0 0;">Joining</p>
      <p class="note"><span class="spin" style="margin-top: 3px;" aria-hidden="true"></span><span>Joining "Lab Phone"… up to a minute. Keep that hotspot on.</span></p>
      <p class="note"><span class="spin" style="margin-top: 3px;" aria-hidden="true"></span><span>Saving "HOT-WiFi" as the lab WiFi…</span></p>
      <p class="cap" style="margin: 8px 0 0;">Done</p>
      %s
      %s
      %s
      <p class="cap" style="margin: 8px 0 0;">Didn't work</p>
      %s
      %s
      %s
      %s
    </div>
  </main>""" % (
    n("warn", "alert", "Type the hotspot name."),
    n("warn", "alert", "A WiFi password has at least 8 characters."),
    n("ok", "check", 'Pepper joined "Lab Phone" and will remember it. Move this laptop there too.'),
    n("ok", "check", 'reachy3 is already on "Lab Phone". Its password is updated.'),
    n("warn", "info", 'reachy3 saved "Lab Phone" but can\'t see it now, so it stays on "HOT-WiFi".'),
    n("err", "alert", 'Pepper couldn\'t join "Lab Phone". Wrong password? It is back on "HOT-WiFi".'),
    n("err", "alert", "Pepper is starting its app. Wait for it, then try again."),
    n("err", "alert", '"reachy-mini-ap" is the robot\'s own setup network.'),
    n("err", "alert", "Couldn't ask the hub. Is Robot Hub running?"))

sheet = """<div class="app" style="flex-direction: row;">
  %s
  <aside class="sheet" style="position: absolute;" aria-label="Pepper details">
    <div class="sheet-head">
      <img class="tile" src="img/%s" alt="">
      <div class="who"><p class="name">Pepper</p>%s</div>
      <span class="metric batt">%s62%%</span>
      <a class="btn btn-ghost btn-sm btn-icon" href="Hub.dc.html" aria-label="Close">%s</a>
    </div>
    <div class="sheet-body">
      <section class="sec">
        <p class="detail" style="color: #1C1917; font-size: 15px;">System running</p>
        <dl class="facts">
          <dt>Robot</dt><dd>Pepper</dd>
          <dt>Address</dt><dd>10.0.4.41 on HOT-WiFi</dd>
          <dt>Robot software</dt><dd>NAOqi 2.5.10.7</dd>
          <dt>Listens with</dt><dd>Pepper's own four microphones</dd>
          <dt>Battery</dt><dd>62%%</dd>
          <dt>App</dt><dd>Dashboard on this laptop, port 8780</dd>
          <dt>Seen</dt><dd>1 s ago</dd>
        </dl>
        <div style="display: flex; gap: 8px;">%s%s</div>
      </section>
      <section class="sec">%s</section>
      <section class="sec">
        <div class="sechd"><h3 class="lbl" style="flex: 1 1 auto;">Add WiFi</h3><span class="tag tag-dark">Lab staff</span></div>
        <div class="field"><label for="ssid2">WiFi name</label><input id="ssid2" class="input" type="text" value="Lab Phone"></div>
        <div class="field"><label for="pw2">Password</label><input id="pw2" class="input" type="password" value="password1"></div>
        <p class="sub">8 to 63 characters. Turn the hotspot on first, 2.4 GHz.</p>
        <div style="display: flex;"><button class="btn btn-dark busy" type="button" disabled="{{yes}}">Joining…</button></div>
        <p class="note"><span class="spin" style="margin-top: 3px;" aria-hidden="true"></span><span>Joining "Lab Phone"… up to a minute. Keep that hotspot on.</span></p>
      </section>
    </div>
  </aside>
</div>""" % (left, P, pill("run", "Running"), ic("battery", 16), ic("x", 18),
             btn("Disconnect", "quiet", "unlink", extra=' style="min-height: 40px;"'), btn("Copy details", "ghost", "copy", extra=' style="min-height: 40px;"'),
             pepper_ai(sub="Applies next start"))

write("RobotPanel2.dc.html", page("Pepper details and WiFi results", sheet, "renderVals() { return { yes: true }; }", height=1000))
