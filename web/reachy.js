/* Reachy app: start-up, the tabs and the robot picker.
 *
 * URL scheme (shared with the hub page): /reachy.html#group, #talk/<robotKey>,
 * #woz/<robotKey>; a tab without a key shows the robot picker. /group.html
 * redirects to #group. With ?demo=<state> the page loads web/demo-reachy.js
 * and renders from fake data, without the hub.
 */
'use strict';

(function () {
  const { $, el, str } = RA;
  const TABS = ['talk', 'group', 'woz'];
  let lastKey = '';

  /* --------------------------------------------------------------- banner */
  const banners = { group: '', talk: '', woz: '' };
  RA.setBanner = (tab, text) => {
    banners[tab] = str(text);
    renderBanner();
  };
  function renderBanner() {
    const text = banners[RA.route.tab] || '';
    $('error-text').textContent = text;
    $('error-banner').hidden = !text;
  }

  /* --------------------------------------------------------------- picker */
  function renderPicker(tab) {
    const list = $('pick-list');
    list.textContent = '';
    const robots = RA.reachys().filter(r => r.state !== 'ABSENT');
    $('picker-title').textContent = tab === 'woz' ? 'Which Reachy do you drive?' : 'Which Reachy?';
    $('picker-sub').textContent = tab === 'woz'
      ? 'Wizard of Oz works one robot at a time. Pick it here.'
      : 'Talk is one Reachy with its own app. Pick it here.';
    const order = { RUNNING: 0, CONNECTED: 1, DEGRADED: 2, CONNECTING: 3, DETECTED: 4, ERROR: 5, DISABLED: 6 };
    robots.sort((a, b) => (order[a.state] ?? 9) - (order[b.state] ?? 9) || str(a.name).localeCompare(str(b.name)));
    robots.forEach(r => {
      const b = el('button', 'pick');
      b.type = 'button';
      const img = el('img');
      img.src = r.type_id === 'reachy_lite' ? '/photos/robot-reachy-lite.png' : '/photos/robot-reachy-wireless.png';
      img.alt = '';
      const who = el('span', 'who');
      who.append(el('b', '', r.name || r.key),
                 RA.pill(RA.STATUS_PILL[r.state] || 'p-off', r.state === 'RUNNING' ? 'App running' : (RA.STATUS_TEXT[r.state] || r.state), r.state === 'CONNECTING'));
      b.append(img, who);
      if (r.address) { const a = el('span', 'metric', r.address); a.style.marginLeft = 'auto'; b.append(a); }
      b.addEventListener('click', () => RA.go(tab, r.key));
      list.append(b);
    });
    $('picker-empty').hidden = robots.length > 0 || !RA.hub.loaded;
    if (!RA.hub.loaded) list.append(el('p', 'sub', 'Looking for robots…'));
  }

  /* --------------------------------------------------------------- routing */
  function applyRoute() {
    const route = RA.parseRoute();
    RA.route = route;
    if (route.key) lastKey = route.key;
    TABS.forEach(t => {
      const tab = $(`tab-${t}`);
      const on = t === route.tab;
      tab.classList.toggle('on', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      if (t !== 'group') tab.href = lastKey ? `#${t}/${encodeURIComponent(lastKey)}` : `#${t}`;
    });
    const picking = route.tab !== 'group' && !route.key;
    $('view-picker').hidden = !picking;
    $('view-group').hidden = route.tab !== 'group';
    $('view-talk').hidden = picking || route.tab !== 'talk';
    $('view-woz').hidden = picking || route.tab !== 'woz';
    $('app').classList.toggle('woz-on', route.tab === 'woz' && !picking);
    $('talk-badges').hidden = true;
    // Talk and Wizard of Oz follow the same robot, so both keep up with its link.
    const key = route.tab === 'group' ? lastKey : route.key;
    if (key) {
      RA.Talk.show(key);
      RA.Woz.show(key);
      if (route.tab !== 'group') RA.useLink(key);
    }
    if (picking) { renderPicker(route.tab); document.title = 'Reachy app'; }
    else if (route.tab === 'group') { RA.Group.show(); document.title = 'Group: Reachy app'; }
    else if (route.tab === 'talk') RA.Talk.render();
    else { RA.Woz.render(); document.title = `${RA.robotName(route.key)}: Wizard of Oz`; }
    RA.renderSave();
    RA.renderLive();
    renderBanner();
  }

  /* ------------------------------------------------------------------ boot */
  function boot() {
    RA.hydrateIcons(document);
    document.querySelectorAll('template').forEach(t => RA.hydrateIcons(t.content));
    RA.Group.init();
    if (RA.GroupWoz) RA.GroupWoz.init();
    RA.Talk.init();
    RA.Woz.init();
    RA.startTips();

    $('logs-btn').addEventListener('click', RA.openLogs);
    $('logs-copy').addEventListener('click', async () => {
      const text = RA.hub.log.map(e => `${new Date((e.ts || 0) * 1000).toTimeString().slice(0, 8)} ${str(e.level).padEnd(5)} ${str(e.text)}`).join('\n');
      const ok = text ? await RA.copyText(text) : false;
      RA.toast(ok ? 'Copied' : 'Nothing to copy', !ok);
    });
    document.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', () => RA.closeDrawer(b.dataset.close)));
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      ['logs-drawer', 'details-drawer'].forEach(id => { if (!$(id).hidden) { e.stopImmediatePropagation(); RA.closeDrawer(id); } });
    }, true);
    RA.onHub(() => { if (!$('view-picker').hidden) renderPicker(RA.route.tab); });
    window.addEventListener('hashchange', applyRoute);
    RA.startHub();
    applyRoute();
    if (RA.demo && RA.demo.after) RA.demo.after();
  }

  const demo = new URLSearchParams(location.search).get('demo');
  if (demo) {
    const s = document.createElement('script');
    s.src = '/demo-reachy.js?v=2026-11-05a';
    s.onload = () => { RA.demo.install(demo); boot(); };
    s.onerror = () => { document.body.prepend(el('p', 'note err', 'Demo data is missing (demo-reachy.js).')); boot(); };
    document.head.append(s);
  } else {
    boot();
  }
})();
