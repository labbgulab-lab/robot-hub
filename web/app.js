/* Robot Hub, the student app's main page (work package E).

   One page: the robots (default), #settings, #files (lab staff), #hotspot
   (the demo planner); sheets for a robot's details, the network and a setup
   item; the logs drawer; the first-run key popup. Everything comes from the
   hub's REST API and its /ws events (docs/BUILD-PLAN.md "Hub API contract").

   ?demo=<state> renders from fake data (web/demo-hub.js, loaded only then),
   so every design board can be screenshotted without a hub.

   Copy is short and plain, no emoji. The page never asks the browser to
   confirm(): a destructive action is "press twice". */
(function () {
  'use strict';

  /* ------------------------------------------------------------ constants */
  const PRESENT = ['DETECTED', 'CONNECTING', 'CONNECTED', 'RUNNING', 'DEGRADED', 'ERROR'];
  const CONNECTED = ['CONNECTED', 'RUNNING', 'DEGRADED'];
  const TYPE_ORDER = ['reachy_wireless', 'furhat', 'reachy_lite', 'naoqi', 'pepper'];
  const TYPE_LABEL = {
    reachy_wireless: 'Reachy Mini (wireless)', reachy_lite: 'Reachy Mini Lite (USB)',
    furhat: 'Furhat', naoqi: 'NAO', pepper: 'Pepper',
  };
  const TYPE_IMG = {
    reachy_wireless: 'robot-reachy-wireless.png', reachy_lite: 'robot-reachy-lite.png',
    furhat: 'robot-furhat.png', naoqi: 'robot-naoqi.png', pepper: 'robot-pepper.png',
  };
  const PROV = { gemini: 'Gemini', gpt: 'GPT', elevenlabs: 'ElevenLabs', openrouter: 'OpenRouter', qwen: 'Qwen' };
  const PROV_LONG = { gemini: 'Gemini', gpt: 'OpenAI (GPT)', elevenlabs: 'ElevenLabs', openrouter: 'OpenRouter', qwen: 'Qwen' };
  const TALKS = ['gemini', 'gpt'];
  const DEFAULT_PROV = {
    'reachy_wireless/main': 'Gemini', 'pepper/main': 'GPT', 'pepper/voice': 'ElevenLabs',
    'furhat/main': 'GPT',
  };
  const NET_PROBLEMS = ['no_network', 'wrong_network', 'hotspot_5ghz', 'vpn_on', 'isolated'];
  const REACHY_WINDOW = 'robot-hub-reachy';
  const LOG_MAX = 500;

  const params = new URLSearchParams(location.search);
  const DEMO_STATE = params.get('demo');
  let DEMO = null;              // window.HubDemo, set when ?demo= is used

  /* ------------------------------------------------------------ icons */
  const I = {
    wifi: '<path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1"/>',
    logs: '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    settings: '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    refresh: '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    battery: '<rect x="2" y="7" width="17" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/>',
    bolt: '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    unlink: '<path d="M18.84 12.25l1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M5.17 11.75l-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71"/><line x1="8" y1="2" x2="8" y2="5"/><line x1="2" y1="8" x2="5" y2="8"/><line x1="16" y1="19" x2="16" y2="22"/><line x1="19" y1="16" x2="22" y2="16"/>',
    link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    micoff: '<line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 0 0 5.12 2.12M15 9.34V4a3 3 0 0 0-5.94-.6"/><path d="M17 16.95A7 7 0 0 1 5 12v-2m14 0v2a7 7 0 0 1-.11 1.23"/><line x1="12" y1="19" x2="12" y2="23"/>',
    key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6"/><path d="m15.5 7.5 3 3L22 7l-3-3"/>',
    plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    trash: '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>',
    alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    check: '<polyline points="20 6 9 17 4 12"/>',
    back: '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    usb: '<circle cx="12" cy="20" r="2"/><path d="M12 18V4"/><path d="m9 7 3-3 3 3"/><path d="M8 13l4 2 4-3"/>',
    info: '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    chev: '<polyline points="6 9 12 15 18 9"/>',
    radar: '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>',
    ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
    lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    xcircle: '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    phone: '<rect x="7" y="2" width="10" height="20" rx="2"/><line x1="12" y1="18" x2="12.01" y2="18"/>',
    wifioff: '<line x1="1" y1="1" x2="23" y2="23"/><path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"/><path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"/><path d="M10.71 5.05A16 16 0 0 1 22.58 9"/><path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12.01" y2="20"/>',
  };
  function ic(name, size, extra) {
    const s = size || 20;
    return `<svg class="icon${extra ? ' ' + extra : ''}" style="width:${s}px;height:${s}px" viewBox="0 0 24 24" aria-hidden="true">${I[name] || ''}</svg>`;
  }

  /* ------------------------------------------------------------ helpers */
  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  const $ = (sel, root) => (root || document).querySelector(sel);
  const img = name => `/photos/${name}`;
  const typeImg = t => img(TYPE_IMG[t] || 'robot-reachy-wireless.png');
  function clock(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  function secondsText(s) {
    s = Math.max(0, Math.floor(s));
    return s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
  function agoText(s) {
    s = Math.max(0, Math.floor(s));
    if (s < 60) return `${s} s ago`;
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    return `${Math.floor(s / 3600)} h ago`;
  }
  function sizeText(bytes) {
    if (bytes >= 1 << 20) { const mb = bytes / (1 << 20); return `${mb < 10 ? mb.toFixed(1) : Math.round(mb)} MB`; }
    if (bytes >= 1 << 10) return `${Math.round(bytes / (1 << 10))} KB`;
    return `${bytes || 0} B`;
  }
  function cap(text) { text = String(text || ''); return text ? text[0].toUpperCase() + text.slice(1) : ''; }
  function sentence(text) {
    text = cap(String(text || '').trim()).replace(/\s+--\s+/g, '. ');
    return text && !/[.!?]$/.test(text) ? text + '.' : text;
  }
  function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + 's')}`; }
  function listText(items) {
    if (items.length <= 1) return items.join('');
    return items.slice(0, -1).join(', ') + ' and ' + items[items.length - 1];
  }
  function natural(a, b) { return String(a).localeCompare(String(b), undefined, { numeric: true }); }

  /* ------------------------------------------------------------ state */
  const S = {
    robots: new Map(),
    keys: { keys: [], providers: [], assign: {}, slots: {} },
    settings: { auto_connect: false, staff_tools: false, save_transcripts: true, setup_seen: true,
                lab_wifi: { name: '', open: true }, passwords: { furhat: { set: true, works: null } } },
    network: { state: 'searching', kind: 'none', ranges: [], hotspot: { devices: 1, limit: 5 } },
    setup: [],
    log: [],
    app: { version: '', update: { available: false } },
    live: 'connecting',       // connecting | live | reconnecting | stopped
    snapshotAt: 0,
    lastEvent: null,
    gotSnapshot: false,
  };
  const ui = {
    view: 'robots', sheet: null, logs: false, logFilter: 'all', logUnseen: false, logPinned: true,
    popup: null,              // {key, provider, phase, result, chips}
    conflicts: {}, armed: {}, pending: {}, wifi: {}, wifiNote: {}, wifiBusy: {}, moved: {}, known: {},
    postureErr: {}, barDismissed: {}, keyArm: null, quitting: false, scanBusy: false,
    netChecking: false, keyChecking: {}, addKey: { provider: 'auto', label: '', key: '', busy: false, result: null },
    pwEdit: false, pw: '', pwBusy: false, labEdit: false, lab: null, doctor: null, doctorBusy: false,
    resources: null, bringup: false, updating: false, stopped: false, stopReason: '',
    files: { robot: null, list: null, error: '', loading: false, arm: null, replaceArm: '', note: null,
             upload: null, busy: false, dl: {}, keyPick: {} },
    hotspot: { picked: null, checks: {} },
    copied: false, firstNetPending: false, netWas: null, inUseTake: {}, changedRunning: {},
  };

  /* ------------------------------------------------------------ transport */
  async function api(method, path, body) {
    if (DEMO) return DEMO.api(method, path, body);
    const opt = { method, headers: {} };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opt);
    } catch (err) {
      return { ok: false, code: 'HUB_DOWN', error: "Couldn't ask the hub. Is Robot Hub running?", status: 0 };
    }
    const data = await res.json().catch(() => ({}));
    if (data.ok === undefined) data.ok = res.ok;
    data.status = res.status;
    if (!res.ok && !data.error) data.error = `The hub answered ${res.status}.`;
    return data;
  }

  let ws = null;
  let backoff = 500;
  let stopTimer = null;
  function connectWs() {
    if (DEMO) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    try { ws = new WebSocket(`${proto}://${location.host}/ws`); } catch (err) { scheduleReconnect(); return; }
    ws.onopen = () => {
      backoff = 500;
      S.live = 'live';
      ui.stopped = false;
      ui.quitting = false;
      // A reason from an earlier stop must not label the next one (a Quit
      // from Settings sets its own just before the hub hears it).
      ui.stopReason = '';
      clearTimeout(stopTimer);
      stopTimer = null;
      refreshApp();
      render();
    };
    ws.onmessage = e => { try { handle(JSON.parse(e.data)); } catch (err) { /* a bad frame */ } };
    ws.onclose = () => {
      if (ui.quitting) {
        // The hub is gone after a Quit: close this window too. The launcher
        // closes the app window anyway; a browser may refuse for a tab.
        S.live = 'stopped';
        render();
        setTimeout(() => { try { window.close(); } catch (err) { /* not ours to close */ } }, 300);
        scheduleReconnect();
        return;
      }
      S.live = S.gotSnapshot ? 'reconnecting' : 'connecting';
      // A dropped link for a few seconds is a hub restart; longer is a stop.
      if (!stopTimer && S.gotSnapshot) {
        stopTimer = setTimeout(() => { ui.stopped = !ui.updating; render(); }, 4000);
      }
      render();
      scheduleReconnect();
    };
    ws.onerror = () => { try { ws.close(); } catch (err) { /* closed */ } };
  }
  function scheduleReconnect() {
    setTimeout(connectWs, backoff);
    backoff = Math.min(backoff * 2, 10000);
  }

  async function refreshApp() {
    const a = await api('GET', '/api/app');
    if (a && a.version !== undefined) { S.app = a; render(); maybeAutoUpdate(); }
  }

  // Right after the installed app starts, a newer version on GitHub installs
  // itself: a 5-second countdown with Not now, then the installer (the app
  // opens again by itself). Never while a robot is connected, and later only
  // the Update button, so a demo is never cut.
  const AUTO_UPDATE_COUNTDOWN_MS = 5000;
  function skippedUpdate() { try { return sessionStorage.getItem('hub.skipUpdate') || ''; } catch (err) { return ''; } }
  function maybeAutoUpdate() {
    const up = S.app.update || {};
    if (!S.app.auto_update || !up.latest || ui.updating || ui.autoUpd || skippedUpdate() === up.latest) return;
    if (realRobots().some(r => CONNECTED.includes(r.state) || r.state === 'CONNECTING')) return;
    ui.autoUpd = { version: up.latest, end: Date.now() + AUTO_UPDATE_COUNTDOWN_MS };
    const tick = () => {
      if (!ui.autoUpd) return;
      if (Date.now() >= ui.autoUpd.end) { ui.autoUpd = null; startUpdate(); return; }
      render();
      setTimeout(tick, 250);
    };
    tick();
  }
  async function startUpdate() {
    ui.updating = true;
    render();
    const r = await api('POST', '/api/app/update');
    if (!r.ok) { ui.updating = false; toast(sentence(r.error || "Couldn't start the update."), 'err'); render(); }
  }
  // The hub asks GitHub as it starts; the answer comes a few seconds later.
  // Ask the hub again every 4 s for the first minutes so the page hears it.
  function watchStartupUpdate() {
    let tries = 0;
    const again = () => {
      tries += 1;
      if (tries > 45 || ui.updating || ui.autoUpd) return;
      const up = S.app.update || {};
      if (S.app.version !== undefined && (!S.app.installed || up.available
          || Number(S.app.uptime_s || 0) > 180)) return;
      refreshApp().finally(() => setTimeout(again, 4000));
    };
    setTimeout(again, 4000);
  }

  /* ------------------------------------------------------------ events */
  function handle(msg) {
    switch (msg.type) {
      case 'snapshot': onSnapshot(msg); break;
      case 'robot': upsertRobot(msg); break;
      case 'robot_removed': S.robots.delete(msg.key); break;
      case 'log': addLog(msg, true); break;
      case 'network': onNetwork(msg); break;
      case 'conflict':
        ui.conflicts[msg.key] = msg.message;
        break;
      case 'settings': S.settings = Object.assign({}, S.settings, strip(msg)); break;
      case 'keys': S.keys = Object.assign({ slots: {} }, strip(msg)); break;
      case 'setup': onSetup(msg.item); break;
      case 'quitting': // Quit from Settings, the tray or the installer
        if (ui.updating) return;
        ui.quitting = true; ui.stopped = true;
        if (!ui.stopReason) ui.stopReason = 'Start it again from its desktop icon.';
        break;
      case 'update_failed': // a Mac update that stopped while the hub still runs
        ui.updating = false;
        toast(sentence(msg.message || "The update didn't finish."), 'err');
        break;
      case 'heartbeat': return;
      default: return;
    }
    render();
  }
  function strip(msg) { const o = Object.assign({}, msg); delete o.type; delete o.ts; delete o.seq; return o; }

  function onSnapshot(msg) {
    const first = !S.gotSnapshot;
    S.robots.clear();
    (msg.robots || []).forEach(upsertRobot);
    S.network = msg.network || S.network;
    S.settings = Object.assign({}, S.settings, msg.settings || {});
    if (msg.keys) S.keys = Object.assign({ slots: {} }, strip(msg.keys));
    S.setup = msg.setup || [];
    S.log = [];
    (msg.log || []).forEach(e => addLog(e, false));
    S.lastEvent = null;
    S.gotSnapshot = true;
    S.snapshotAt = Date.now();
    ui.netWas = S.network.state;
    if (!DEMO) backfillLog();
    if (first) {
      // First run: the key popup, then the network panel (it opens by itself
      // on a first visit and on any problem).
      if (!S.keys.keys.length && !sessionGet('hub.keyLater')) openPopup();
      if (!S.settings.setup_seen) {
        if (ui.popup) ui.firstNetPending = true; else openNetworkFirst();
      } else if (NET_PROBLEMS.includes(S.network.state) && !ui.popup) {
        ui.sheet = { kind: 'network' };
      }
    }
  }
  async function backfillLog() {
    const r = await api('GET', `/api/log?limit=${LOG_MAX}`);
    if (r && Array.isArray(r.log)) {
      S.log = [];
      r.log.forEach(e => addLog(e, false));
      render();
    }
  }
  function openNetworkFirst() {
    ui.sheet = { kind: 'network' };
    api('PUT', '/api/settings', { setup_seen: true });
    S.settings.setup_seen = true;
  }

  function upsertRobot(r) {
    const old = S.robots.get(r.key);
    S.robots.set(r.key, Object.assign({ _detail: old && old._detail }, r, { _rx: Date.now() }));
    if (old && old.state !== r.state) {
      // A robot that came back after Add WiFi moved it is no longer "moved".
      if (PRESENT.includes(r.state)) delete ui.moved[r.key];
      if (!CONNECTED.includes(r.state) && r.state !== 'CONNECTING') delete ui.armed[r.key];
    }
    if (old && old.launching_since && !r.launching_since) delete ui.pending[r.key];
    if (r.state !== 'RUNNING') delete ui.changedRunning[r.key];
  }

  function onNetwork(msg) {
    const was = S.network.state;
    S.network = Object.assign({}, S.network, strip(msg));
    const now = S.network.state;
    if (now !== was && NET_PROBLEMS.includes(now) && !NET_PROBLEMS.includes(was || '')) {
      if (!ui.sheet && !ui.popup) ui.sheet = { kind: 'network' };
      delete ui.barDismissed.net;
    }
  }

  function onSetup(item) {
    if (!item) return;
    const i = S.setup.findIndex(x => x.id === item.id);
    if (i >= 0) S.setup[i] = item; else S.setup.push(item);
  }

  function addLog(e, live) {
    S.log.push(e);
    if (S.log.length > LOG_MAX) S.log.splice(0, S.log.length - LOG_MAX);
    if (!live) return;
    S.lastEvent = e.ts || Date.now() / 1000;
    if (e.level === 'error') {
      if (!ui.logs) ui.logUnseen = true;
    }
  }

  /* ------------------------------------------------------------ toast */
  let toastTimer = null;
  function toast(text, kind) {
    ui.toast = { text: String(text || ''), kind: kind || 'ok' };
    clearTimeout(toastTimer);
    if (!DEMO_STATE) toastTimer = setTimeout(() => { ui.toast = null; renderToast(); }, kind === 'err' ? 4200 : 3200);
    renderToast();
  }
  function renderToast() {
    const el = $('#toast');
    if (!ui.toast) { el.hidden = true; el.innerHTML = ''; return; }
    const t = ui.toast;
    el.hidden = false;
    el.className = 'toast' + (t.kind === 'err' ? ' err' : '');
    el.innerHTML = ic(t.kind === 'err' ? 'alert' : (t.kind === 'info' ? 'info' : 'check'), 18) + `<span>${esc(t.text)}</span>`;
  }

  /* ------------------------------------------------------------ storage (per-viewer conveniences) */
  function sessionGet(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
  function sessionSet(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* private window */ } }
  function localGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }

  /* ------------------------------------------------------------ derived */
  function realRobots() { return [...S.robots.values()].filter(r => !r.key.startsWith('placeholder:')); }
  function robotName(key) { const r = S.robots.get(key); return r ? r.name : key; }
  function isReachy(r) { return r.type_id === 'reachy_wireless'; }
  function staff() { return !!S.settings.staff_tools; }
  function setupItem(id) { return S.setup.find(x => x.id === id) || null; }
  function launchingSeconds(r) {
    if (r.launching_since) return (Date.now() / 1000) - r.launching_since;
    if (ui.pending[r.key]) return (Date.now() - ui.pending[r.key]) / 1000;
    return null;
  }
  function keyById(id) { return S.keys.keys.find(k => k.id === id) || null; }
  function keyUsable(k) { return k && !['bad', 'no_credit'].includes((k.status || {}).state); }
  function hasTalkingKey() {
    return S.keys.keys.some(k => ['gemini', 'gpt', 'openrouter'].includes(k.provider) && keyUsable(k));
  }
  function slotsFor(r) { return (S.keys.slots || {})[r.key] || null; }
  function effectiveKey(r, slot) {
    const s = (slotsFor(r) || {})[slot || 'main'];
    return s && s.key ? s.key : null;
  }
  function optText(k, slot) {
    const extra = slot === 'voice' ? '' : (k.provider === 'openrouter' ? ' · groups only' : '');
    return slot === 'voice' ? `${k.label} · …${k.tail}` : `${k.label} · ${PROV[k.provider] || k.provider} · …${k.tail}${extra}`;
  }
  function netName() {
    const n = S.network;
    return n.ssid || (n.kind === 'none' ? 'No WiFi' : 'this network');
  }
  function labWifi() { return (S.settings.lab_wifi || {}).name || ''; }
  function expectedWifi() { return S.network.expected || labWifi() || 'the lab WiFi'; }

  /* ------------------------------------------------------------ render scheduling */
  let raf = 0;
  let pointerDown = false;
  function render() {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; if (pointerDown) { pendingAfterPointer = true; return; } renderNow(); });
  }
  // A click is a press and a release on the same element: never rebuild the
  // page between the two, or the click is lost.
  let pendingAfterPointer = false;
  document.addEventListener('pointerdown', () => { pointerDown = true; }, true);
  const release = () => {
    pointerDown = false;
    setTimeout(() => { if (pendingAfterPointer) { pendingAfterPointer = false; render(); } flushDeferred(); }, 0);
  };
  document.addEventListener('pointerup', release, true);
  document.addEventListener('pointercancel', release, true);

  // Replace an element's HTML only when it changed, and never under the
  // student's focus (an open select or a field being typed into). Scroll
  // positions inside ([data-scroll]) survive the swap.
  const deferred = new Set();
  function put(el, html) {
    if (!el) return;
    if (el.__html === html) { el.__deferred = null; return; }
    const active = document.activeElement;
    if (active && active !== document.body && el.contains(active) &&
        (active.tagName === 'SELECT' || active.tagName === 'INPUT' || active.tagName === 'TEXTAREA') &&
        active.type !== 'checkbox' && active.type !== 'file') {
      el.__deferred = html;
      deferred.add(el);
      return;
    }
    const focusId = active && el.contains(active) ? active.getAttribute('data-fid') : null;
    const scrolls = {};
    el.querySelectorAll('[data-scroll]').forEach(s => { scrolls[s.dataset.scroll] = s.scrollTop; });
    el.innerHTML = html;
    el.__html = html;
    el.__deferred = null;
    deferred.delete(el);
    el.querySelectorAll('[data-scroll]').forEach(s => { if (scrolls[s.dataset.scroll] != null) s.scrollTop = scrolls[s.dataset.scroll]; });
    if (focusId) {
      const again = el.querySelector(`[data-fid="${CSS.escape(focusId)}"]`);
      if (again) again.focus();
    }
  }
  function flushDeferred() {
    if (pointerDown) return;
    deferred.forEach(el => {
      if (!el.isConnected) { deferred.delete(el); return; }
      if (el.__deferred != null && !el.contains(document.activeElement)) put(el, el.__deferred);
    });
  }
  document.addEventListener('focusout', () => setTimeout(flushDeferred, 0));
  // A shell (scrim + panel, with its entrance animation) is built once per
  // sheet; later renders only replace what is inside the panel.
  function shell(host, id, outer) {
    if (host.__shell !== id) {
      host.innerHTML = outer;
      host.__shell = id;
      host.__html = null;
    }
    return host.querySelector('[data-inner]');
  }

  function renderNow() {
    $('#boot').hidden = S.gotSnapshot && !DEMO_STATE_FLAGS.boot;
    renderTop();
    renderBar();
    const v = ui.view;
    $('#top').hidden = v !== 'robots';
    $('#view-robots').hidden = v !== 'robots';
    $('#view-settings').hidden = v !== 'settings';
    $('#view-files').hidden = v !== 'files';
    $('#view-hotspot').hidden = v !== 'hotspot';
    if (v === 'robots') renderRobots();
    if (v === 'settings') renderSettings();
    if (v === 'files') renderFiles();
    if (v === 'hotspot') renderHotspot();
    renderSheet();
    renderLogs();
    renderPopup();
    renderOverlays();
    renderToast();
  }
  const DEMO_STATE_FLAGS = {};

  /* ------------------------------------------------------------ top bar */
  function netChip() {
    const n = S.network;
    const st = n.state;
    const hs = n.hotspot || { devices: 1, limit: 5 };
    let cls = 'chip', inner, title = 'Network';
    if (st === 'no_network') { cls += ' chip-err'; inner = `${ic('wifioff', 16)}<span class="ctext">No WiFi</span><span class="cdot"></span>`; }
    else if (st === 'vpn_on') { cls += ' chip-warn'; inner = `${ic('wifi', 16)}<span class="ctext">VPN on</span><span class="cdot"></span>`; }
    else if (st === 'hotspot_5ghz') { cls += ' chip-warn'; inner = `${ic('phone', 16)}<span class="ctext">Hotspot on ${esc(n.band || '5 GHz')}: turn on 2.4 GHz</span><span class="cdot"></span>`; }
    else if (st === 'wrong_network' || st === 'isolated') { cls += ' chip-warn'; inner = `${ic('wifi', 16)}<span class="ctext">${esc(n.ssid || 'Another WiFi')}</span><span class="cdot"></span>`; }
    else if (n.kind === 'hotspot') {
      const full = hs.devices >= hs.limit;
      if (full) cls += ' chip-warn';
      inner = `${ic('phone', 16)}<span class="ctext">Phone hotspot ${hs.devices}/${hs.limit}</span>${full ? '<span class="cdot"></span>' : ''}`;
    } else if (st === 'searching' && !n.ssid) {
      inner = `${ic('wifi', 16)}<span class="ctext">Looking</span>`;
    } else {
      inner = `${ic('wifi', 16)}<span class="ctext">${esc(n.ssid || 'Network')}</span>${n.band ? `<span class="muted">${esc(n.band)}</span>` : ''}<span class="cdot"></span>`;
    }
    title = NET_PROBLEMS.includes(st) ? 'Network: needs attention' : 'Network: ready';
    return `<button class="${cls}" type="button" data-act="net-open" title="${title}" aria-label="${title}">${inner}</button>`;
  }
  function renderTop() {
    put($('#net-slot'), netChip());
    const auto = $('#auto');
    auto.setAttribute('aria-checked', S.settings.auto_connect ? 'true' : 'false');
    auto.classList.toggle('on', !!S.settings.auto_connect);
    const scan = $('#scan');
    scan.disabled = ui.scanBusy;
    put(scan, `${ic('refresh', 16, ui.scanBusy ? 'spinning' : '')}<span>${ui.scanBusy ? 'Scanning…' : 'Scan'}</span>`);
    const live = $('#live');
    const word = { live: 'Live', connecting: 'Connecting', reconnecting: 'Reconnecting', stopped: 'Stopped' }[S.live] || 'Live';
    live.className = 'live' + (S.live === 'live' ? '' : (ui.stopped ? ' bad' : ' off'));
    put(live, `<span class="ldot" aria-hidden="true"></span><span class="ltext">${word}</span>`);
    const logs = $('#logs-btn');
    logs.setAttribute('aria-pressed', ui.logs ? 'true' : 'false');
    put(logs, `${ic('logs', 18)}Logs${ui.logUnseen ? '<span class="newdot" aria-label="New error"></span>' : ''}`);
    const up = S.app.update || {};
    $('#upd').hidden = !up.available;
    $('#upd-text').textContent = up.latest ? `New version ${up.latest}` : 'New version';
  }

  /* ------------------------------------------------------------ message bar (one at a time) */
  function barModel() {
    const n = S.network;
    if (n.on_robot_subnet === false && realRobots().length) {
      return { id: 'net', kind: 'err', icon: 'wifioff', text: `<b>This laptop left the robots' network.</b> Robots look dead until you rejoin.`, act: 'net-open', label: 'Network', block: true };
    }
    if (NET_PROBLEMS.includes(n.state)) {
      const t = {
        no_network: '<b>No WiFi.</b> Join the robots\' WiFi.',
        wrong_network: `This laptop is on <b>${esc(n.ssid || 'another WiFi')}</b>. The robots are on <b>${esc(expectedWifi())}</b>.`,
        hotspot_5ghz: `<b>Your hotspot is on ${esc(n.band || '5 GHz')}.</b> Robots only see 2.4 GHz.`,
        vpn_on: '<b>A VPN is on.</b> Robots may not show up until you turn it off.',
        isolated: '<b>This WiFi keeps devices apart.</b> Robots can\'t be reached on it.',
      }[n.state];
      return { id: 'net', kind: n.state === 'no_network' ? 'err' : 'warn', icon: 'wifi', text: t, act: 'wifi-settings', label: 'Open WiFi settings', block: true };
    }
    if (!hasTalkingKey()) {
      const text = S.keys.keys.length ? '<b>No working key.</b> Robots can\'t talk.' : '<b>No key yet.</b> Robots can\'t talk.';
      return { id: 'key', kind: 'warn', icon: 'key', text, act: 'add-key', label: 'Add a key', block: true };
    }
    const lost = realRobots().find(r => r.state === 'ERROR');
    if (lost) return { id: 'lost:' + lost.key, kind: 'err', icon: 'alert', text: `<b>${esc(lost.name)} lost.</b> ${esc(sentence(lost.detail || ''))}`, act: 'seelog', key: lost.key, label: 'See log' };
    const flat = realRobots().find(r => typeof r.battery === 'number' && r.battery <= 10 && !r.charging && PRESENT.includes(r.state));
    if (flat) return { id: 'batt:' + flat.key, kind: 'err', icon: 'battery', text: `<b>${esc(flat.name)} battery ${flat.battery}%.</b> Plug it in now.` };
    const hs = n.hotspot || {};
    if (n.kind === 'hotspot' && hs.devices >= hs.limit) return { id: 'hotspot', kind: 'warn', icon: 'phone', text: '<b>Hotspot full.</b> Another device won\'t join.', act: 'hotspot', label: 'Plan' };
    return null;
  }
  function renderBar() {
    const el = $('#bar');
    let b = ui.view === 'robots' ? barModel() : null;
    // "No robots nearby" already says what the network bar would.
    if (b && b.id === 'net' && gridState().empty) b = null;
    if (!b || ui.barDismissed[b.id]) { put(el, ''); return; }
    const act = b.act ? `<button class="btn btn-bar" type="button" data-act="${b.act}"${b.key ? ` data-key="${esc(b.key)}"` : ''}>${esc(b.label)}</button>` : '';
    const x = b.block ? '' : `<button class="btn bar-x" type="button" data-act="bar-x" data-id="${esc(b.id)}" aria-label="Dismiss">${ic('x', 16)}</button>`;
    put(el, `<div class="warnbar${b.kind === 'err' ? ' err' : ''}" role="status">${ic(b.icon, 18)}<span>${b.text}</span><span class="spacer"></span>${act}${x}</div>`);
  }

  /* ------------------------------------------------------------ robots view */
  function sortRobots(list) {
    return list.sort((a, b) => {
      const ta = TYPE_ORDER.indexOf(a.type_id), tb = TYPE_ORDER.indexOf(b.type_id);
      if (ta !== tb) return (ta < 0 ? 99 : ta) - (tb < 0 ? 99 : tb);
      return natural(a.name, b.name);
    });
  }
  function inGrid(r) {
    if (r.key.startsWith('placeholder:')) return r.state === 'DISABLED';
    if (r.state === 'ABSENT') return !!ui.moved[r.key];
    return true;
  }
  function gridState() {
    const all = realRobots();
    const present = all.filter(r => PRESENT.includes(r.state));
    const inGridList = [...S.robots.values()].filter(inGrid);
    // Demo captions (CardStates board) keep the board's order.
    const grid = DEMO_STATE_FLAGS.captions ? inGridList : sortRobots(inGridList);
    const searching = !present.length && !grid.length && (S.network.state === 'searching' || Date.now() - S.snapshotAt < 10000);
    return { all, present, grid, searching, empty: !grid.length && !searching };
  }
  function renderRobots() {
    const all = realRobots();
    const present = all.filter(r => PRESENT.includes(r.state));
    const connected = all.filter(r => CONNECTED.includes(r.state));
    const running = all.filter(r => r.state === 'RUNNING');
    const updated = S.lastEvent ? `Updated ${clock(S.lastEvent)}` : 'Watching for robots';
    const emptyNow = gridState().empty;
    put($('#counts'), emptyNow ? '' : `<span><b>${present.length}</b> of ${all.length} nearby</span>` +
      (connected.length ? `<span><span class="d" style="background:#1D4ED8"></span><b>${connected.length}</b> connected</span>` : '') +
      (running.length ? `<span><span class="d" style="background:#15803D"></span><b>${running.length}</b> running</span>` : '') +
      `<span>${updated}</span>`);

    // The Reachy app band: Talk, groups, Choir and Wizard of Oz live there.
    const reachys = all.filter(isReachy);
    if (reachys.length && !emptyNow) {
      const run = reachys.filter(r => r.state === 'RUNNING').map(r => r.name);
      const near = reachys.filter(r => PRESENT.includes(r.state)).length;
      const status = run.length ? `${listText(run)} running` : (near ? plural(near, 'Reachy', 'Reachys') + ' nearby' : 'No Reachys nearby');
      const tiles = reachys.slice(0, 3).map(() => `<img src="${typeImg('reachy_wireless')}" alt="">`).join('');
      put($('#band'), `<section class="band" aria-labelledby="rapp">
        <div class="tiles" aria-hidden="true">${tiles}</div>
        <div style="flex:1 1 260px;display:flex;flex-direction:column;gap:4px">
          <h2 id="rapp" class="h2">Reachy app</h2>
          <div class="modes">${['Talk', 'Group talk', 'Interrupt', 'Free talk', 'Choir'].map(m => `<button class="mode" type="button" data-act="${m === 'Talk' ? 'reachy-talk' : 'reachy-group'}" title="Open the Reachy app">${m}</button>`).join('')}<button class="mode" type="button" data-act="reachy-woz" title="Open Wizard of Oz">Wizard of Oz</button></div>
        </div>
        <span class="muted small">${esc(status)}</span>
        <button class="btn btn-quiet" type="button" data-act="reachy-group">Open</button>
      </section>`);
    } else put($('#band'), '');

    const { grid, searching, empty } = gridState();
    $('#grid').hidden = empty;
    $('#empty').hidden = !empty;
    $('#robots-main').classList.toggle('democap', !!DEMO_STATE_FLAGS.captions);
    if (searching) {
      put($('#grid'), [0, 1, 2].map(() => `<div class="card" aria-hidden="true">
        <div class="head"><div class="sk" style="width:56px;height:56px;border-radius:12px"></div><div class="who"><div class="sk" style="width:90px;height:16px"></div><div class="sk" style="width:60px;height:14px"></div></div></div>
        <div class="sk" style="height:14px;width:70%"></div><div class="sk" style="height:44px;border-radius:12px"></div></div>`).join('')
        + '<p class="sr" role="status">Looking for robots</p>');
    } else {
      renderGrid(grid);
    }
    if (empty) renderEmpty();

    // Not nearby, and the setup rows ("More robots").
    const away = sortRobots(all.filter(r => r.state === 'ABSENT' && !ui.moved[r.key]));
    const ghosts = away.map(r => `<button class="ghost" type="button" data-act="details" data-key="${esc(r.key)}" title="Last seen ${esc(agoText(Date.now() / 1000 - r.last_seen))}"><img src="${typeImg(r.type_id)}" alt="">${esc(r.name)}</button>`);
    const kitRow = (setupItem('naoqi_kit') || {}).state;
    const liteRow = (setupItem('reachy_lite_app') || {}).state;
    const hasRow = t => (['naoqi', 'pepper'].includes(t) && kitRow && kitRow !== 'ok') || (t === 'reachy_lite' && liteRow && liteRow !== 'ok');
    const waiting = sortRobots([...S.robots.values()].filter(r => r.key.startsWith('placeholder:') && r.state === 'ABSENT' && !r.needs_setup && !hasRow(r.type_id)))
      .map(r => {
        // On a Mac, NAO, Pepper and the USB Lite say why they will not show up.
        const winOnly = /windows laptop only/i.test(r.detail || '');
        const why = winOnly ? r.detail : 'Waiting for this robot to appear';
        return `<span class="ghost${winOnly ? ' ghost-off' : ''}" title="${esc(why)}"><img src="${typeImg(r.type_id)}" alt="">${esc(r.name)}${winOnly ? '<small class="ghost-note">Windows only</small>' : ''}</span>`;
      });
    const rows = [];
    const kit = setupItem('naoqi_kit');
    if (kit && kit.state !== 'ok') rows.push(setupRow('naoqi_kit', ['pepper', 'naoqi'], 'Pepper and NAO'));
    const lite = setupItem('reachy_lite_app');
    if (lite && lite.state !== 'ok') rows.push(setupRow('reachy_lite_app', ['reachy_lite'], 'Reachy Mini Lite (USB)'));
    const any = ghosts.length || waiting.length || rows.length;
    put($('#away'), any && !empty ? `${ghosts.length || waiting.length ? '<span>Not nearby</span>' : ''}${ghosts.join('')}${waiting.join('')}<span class="spacer"></span>${rows.join('')}` : '');
  }
  function setupRow(id, types, label) {
    return `<span class="setuprow"><img src="${typeImg(types[0])}" alt="">${esc(label)}<button class="btn btn-quiet btn-sm" type="button" data-act="setup" data-id="${id}">Set up</button></span>`;
  }

  function renderEmpty() {
    const n = S.network;
    put($('#empty'), `<section class="empty" aria-labelledby="e-title">
      <div class="ghosts" aria-hidden="true"><img src="${typeImg('reachy_wireless')}" alt=""><img src="${typeImg('furhat')}" alt=""><img src="${typeImg('pepper')}" alt=""></div>
      <div style="display:flex;flex-direction:column;gap:6px"><h1 id="e-title" class="h1x">No robots nearby</h1><p class="muted" style="margin:0">Join the robots' WiFi.</p></div>
      <div class="net"><div><p class="netlabel">This laptop is on</p><p class="netname">${esc(n.kind === 'none' ? 'No WiFi' : (n.ssid || 'a network without a name'))}</p></div>
        <div><p class="netlabel">The lab robots are on</p><p class="netname">${esc(expectedWifi())}</p></div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn btn-primary" type="button" data-act="wifi-settings">${ic('wifi', 20)}Open WiFi settings</button>
        <span class="searching" role="status"><span class="spin" aria-hidden="true"></span>Still looking</span>
      </div>
      <p class="muted small" style="margin:0">At a demo? One phone hotspot for both. <a href="#hotspot">How</a> · <a href="#" data-act="net-open">Network help</a></p>
    </section>`);
  }

  // Grid cards are keyed: only a card whose HTML changed is replaced.
  function renderGrid(list) {
    const grid = $('#grid');
    if (grid.querySelector('.sk')) { grid.innerHTML = ''; grid.__html = null; }
    const want = list.map(r => r.key);
    [...grid.children].forEach(el => { if (!want.includes(el.dataset.key)) el.remove(); });
    let prev = null;
    list.forEach(r => {
      let el = [...grid.children].find(c => c.dataset.key === r.key);
      if (!el) {
        el = document.createElement('div');
        el.className = 'cell';
        el.dataset.key = r.key;
      }
      const where = prev ? prev.nextSibling : grid.firstChild;
      if (where !== el) grid.insertBefore(el, where);
      put(el, (DEMO_STATE_FLAGS.captions && r._caption ? `<p class="cap">${esc(r._caption)}</p>` : '') + cardHtml(r));
      prev = el;
    });
  }

  /* ------------------------------------------------------------ one robot card */
  function pillHtml(kind, text, spin) {
    return `<span class="pill p-${kind}" role="status">${spin ? '<span class="spin" aria-hidden="true"></span>' : '<span class="dot"></span>'}${esc(text)}</span>`;
  }
  function metricHtml(r) {
    if (typeof r.battery === 'number') {
      const low = r.battery_low || r.battery < 20;
      return `<span class="metric batt${low ? ' low' : ''}" title="Battery${r.charging ? ', charging' : ''}">${ic('battery', 16)}${r.battery}%${r.charging ? ic('bolt', 12, 'bolt') + '<span class="sr">charging</span>' : ''}</span>`;
    }
    if (r.type_id === 'reachy_lite') return `<span class="metric">${ic('usb', 16)}${r.state === 'ABSENT' ? 'unplugged' : 'USB'}</span>`;
    return `<span class="metric">${esc(r.address || '—')}</span>`;
  }
  const btn = (text, kind, act, key, opts) => {
    opts = opts || {};
    return `<button class="btn btn-${kind}${opts.grow ? ' grow' : ''}${opts.busy ? ' busy' : ''}${opts.cls ? ' ' + opts.cls : ''}" type="button" data-act="${act}"${key ? ` data-key="${esc(key)}"` : ''}${opts.data || ''}${opts.disabled ? ' disabled' : ''}${opts.title ? ` title="${esc(opts.title)}"` : ''}${opts.style ? ` style="${opts.style}"` : ''}>${opts.icon ? ic(opts.icon, 18) : ''}${opts.html || esc(text)}</button>`;
  };
  const STAFF_TAG = '<span class="tag tag-dark" style="margin-left:2px">Staff</span>';
  const noteHtml = (kind, icon, text, acts) =>
    `<div class="note ${kind}">${icon === 'spin' ? '<span class="spin" aria-hidden="true"></span>' : (icon ? ic(icon, 18) : '')}<div>${text}${acts ? `<div class="nacts">${acts}</div>` : ''}</div></div>`;

  function retryText(r) {
    const s = r.retry_at ? Math.ceil(r.retry_at - Date.now() / 1000) : 0;
    return s > 0 ? ` Trying again in ${s} s.` : ' Trying again soon.';
  }
  function oldDaemon(r) {
    const m = /daemon ([\d.]+) is older than ([\d.]+)/i.exec(r.detail || '');
    return m ? { have: m[1], need: m[2] } : null;
  }

  function cardModel(r) {
    const m = { cls: '', pill: null, notes: [], detail: r.detail || '', actions: [], body: '' };
    const st = r.state;
    const ph = r.key.startsWith('placeholder:');
    const secs = launchingSeconds(r);
    const launching = secs !== null;
    const connected = CONNECTED.includes(st);
    const known = TYPE_ORDER.includes(r.type_id);
    const pw = ((S.settings.passwords || {}).furhat || {});
    const old = oldDaemon(r);

    // ---- status pill and card outline
    if (!known) { m.cls = 's-off'; m.pill = pillHtml('off', 'Not supported yet'); m.detail = ''; }
    else if (ph || (st === 'DISABLED' && r.needs_setup)) {
      if (r.needs_setup) { m.pill = pillHtml('off', 'Needs setup'); m.detail = r.needs_setup === 'naoqi_kit' ? 'Needs the Pepper and NAO kit' : (r.disabled_reason || 'Needs setup'); }
      else { m.cls = 's-off'; m.pill = pillHtml('off', 'Unavailable'); m.detail = r.disabled_reason || r.detail; }
    } else if (st === 'ABSENT' && ui.moved[r.key]) {
      m.cls = 's-off'; m.pill = pillHtml('off', 'Moved');
      m.detail = `Now on "${ui.moved[r.key]}". Move this laptop there to see it.`;
    } else if (st === 'ABSENT') { m.cls = 's-off'; m.pill = pillHtml('off', 'Not nearby'); m.detail = `Last seen ${clockOrAgo(r.last_seen)}`; }
    else if (st === 'DISABLED') { m.cls = 's-off'; m.pill = pillHtml('off', 'Unavailable'); m.detail = r.disabled_reason || r.detail; }
    else if (launching) { m.cls = 's-busy'; m.pill = pillHtml('busy', `Starting ${secondsText(secs)}`, true); }
    else if (r.posture_pending) {
      m.cls = 's-busy';
      m.pill = pillHtml('busy', { sit: 'Sitting down', lie: 'Lying down', stand: 'Standing up' }[r.posture_pending] || 'Moving', true);
    } else if (st === 'CONNECTING') { m.cls = 's-busy'; m.pill = pillHtml('busy', 'Connecting', true); }
    else if (st === 'ERROR') { m.cls = 's-lost'; m.pill = pillHtml('lost', 'Lost'); }
    else if (old && !connected) { m.cls = 's-warn'; m.pill = pillHtml('warn', 'Update needed'); }
    else if (st === 'DEGRADED') {
      m.cls = 's-warn';
      m.pill = pillHtml('warn', /not answering|no answer/i.test(r.detail || '') ? 'Not answering' : 'Warning');
    } else if (r.in_use_by && !connected) { m.cls = 's-warn'; m.pill = pillHtml('warn', 'In use'); }
    else if (r.type_id === 'furhat' && (pw.works === false || r._pwBad) && st !== 'RUNNING') { m.cls = 's-warn'; m.pill = pillHtml('warn', 'Needs password'); }
    else if (st === 'RUNNING') { m.cls = 's-run'; m.pill = pillHtml('run', 'Running'); }
    else if (connected) { m.cls = 's-conn'; m.pill = pillHtml('conn', 'Connected'); }
    else { m.pill = pillHtml('near', 'Available'); }
    if (r.in_use_by && connected && st !== 'RUNNING') { m.cls = 's-warn'; m.pill = pillHtml('warn', 'In use'); }

    // ---- detail line rewrites (the whole sentence, never cut)
    if (old) m.detail = `Daemon ${old.have} is older than ${old.need}. Ask lab staff to update it.`;
    if (r.in_use_by && st !== 'RUNNING') m.detail = `Another laptop${r.in_use_by ? ` (${r.in_use_by})` : ''} is talking with it.`;
    if (launching) {
      m.detail = isReachy(r) && secs > 45 ? 'Installing the Reachy app on the robot. First time only.'
        : (r.type_id === 'naoqi' && secs > 30 ? 'First run: downloading the speech model, about 140 MB' : 'Can take a couple of minutes');
    }
    if (st === 'ERROR' && r.detail) m.detail = sentence(detailText(r.detail)) + (S.settings.auto_connect ? retryText(r) : '');
    m.detail = detailText(m.detail);

    // ---- notes (a problem: one short sentence and one button)
    if (connected && r.can_speak === false) {
      if (/could not speak/.test(m.detail)) m.detail = '';
      m.nameIcon = `<span title="Connected, but it couldn't speak">${ic('micoff', 16)}</span>`;
      m.notes.push(noteHtml('warn', 'micoff', r.type_id === 'furhat'
        ? "Connected, but it couldn't speak. Check its voice in Studio." : "Connected, but it couldn't speak. Check its speaker and volume."));
    }
    if (ui.conflicts[r.key]) {
      m.notes.push(noteHtml('warn', 'alert', esc(sentence(ui.conflicts[r.key])),
        btn('Override', 'dark', 'override', r.key, { cls: 'btn-xs' }) + btn('Dismiss', 'ghost', 'dismiss', r.key, { cls: 'btn-xs' })));
    }
    if (r.launch_error && !launching) {
      let text = r.launch_error;
      if (/NAO_LLM refuses|API key|\.env/i.test(text) && r.type_id === 'naoqi') text = 'The NAO app needs its API keys. Ask lab staff.';
      else if (/firewall|8782/i.test(text)) text = `Windows is blocking ${r.name} (port 8782).`;
      else text = "Couldn't start: " + text;
      m.notes.push(noteHtml('err', 'alert', esc(sentence(text)), `<a href="#" data-act="seelog" data-key="${esc(r.key)}">See log</a>`));
    }
    if (r.connect_error && st === 'DETECTED') {
      m.notes.push(noteHtml('err', 'alert', esc(sentence("Couldn't connect: " + r.connect_error)), `<a href="#" data-act="seelog" data-key="${esc(r.key)}">See log</a>`));
    }
    if (r.type_id === 'furhat' && (pw.works === false || r._pwBad) && st !== 'RUNNING') {
      m.notes.push(noteHtml('warn', 'key', 'Furhat Studio asks for its password.'));
    }
    if (ui.wifiNote[r.key] && (!ui.sheet || ui.sheet.key !== r.key) && !ui.moved[r.key]) {
      const w = ui.wifiNote[r.key];
      m.notes.push(noteHtml(w.kind, w.kind === 'ok' ? 'check' : (w.icon || (w.kind === 'warn' ? 'info' : 'alert')), esc(w.text)));
    }

    // ---- key pickers (Reachy, Pepper, Furhat)
    const slots = slotsFor(r);
    if (slots && known && !ph && st !== 'ABSENT') m.body += keyPicker(r, slots, 'card');
    if (slots && isReachy(r)) {
      const k = effectiveKey(r, 'main');
      if (k && !TALKS.includes(k.provider)) {
        m.notes.push(noteHtml('err', 'key', {
          elevenlabs: 'ElevenLabs is a voice only. Pick a Gemini or GPT key.',
          openrouter: 'OpenRouter works in group talk only. Pick a Gemini or GPT key to talk alone.',
        }[k.provider] || `${esc(PROV[k.provider] || k.provider)} can't talk yet. Pick a Gemini or GPT key.`));
        m.cantTalk = true;
      }
      if (!k) m.cantTalk = true;
    }
    if (slots && r.type_id === 'pepper' && !effectiveKey(r, 'main') && st !== 'ABSENT') {
      m.notes.push(noteHtml('warn', 'key', 'The dashboard opens, but AI talk needs a GPT key.', btn('Add a key', 'dark', 'add-key', null, { cls: 'btn-xs' })));
    }

    // ---- NAO postures (safety: the two-tap Stand and every note)
    if (r.type_id === 'naoqi' && !ph && st !== 'ABSENT' && st !== 'DISABLED' && !launching) m.body += postureHtml(r, launching);

    // ---- battery low
    if (r.battery_low && typeof r.battery === 'number' && !ui.armed[r.key] && PRESENT.includes(st)) {
      m.notes.push(noteHtml('warn', 'battery', `Battery ${r.battery}%. ${r.charging ? 'Charging.' : 'Plug it in soon.'}`));
    }

    // ---- actions: Disconnect / Connect, then the main action
    const acts = [];
    if (!known || (st === 'ABSENT' && ui.moved[r.key])) { m.actions = []; return m; }
    if (ph || (st === 'DISABLED' && r.needs_setup)) {
      if (r.needs_setup) acts.push(btn('Set up', 'primary', 'setup', null, { grow: true, data: ` data-id="${esc(r.needs_setup)}"` }));
      m.actions = acts; return m;
    }
    if (st === 'ABSENT') { acts.push(btn('Connect', 'quiet', 'connect', r.key, { grow: true, icon: 'link', disabled: true })); m.actions = acts; return m; }
    if (st === 'DISABLED') { m.actions = []; return m; }
    if (st === 'CONNECTING') acts.push(btn('Connecting…', 'quiet', 'connect', r.key, { grow: true, disabled: true }));
    else if (connected || st === 'ERROR') acts.push(btn('Disconnect', 'quiet', 'disconnect', r.key, { icon: 'unlink' }));
    else if (st === 'DETECTED') acts.push(btn('Connect', 'quiet', 'connect', r.key, { grow: true, icon: 'link' }));

    const main = mainAction(r, m, { launching, secs, connected });
    if (main) acts.push(main);
    if (st === 'ERROR' && !main) acts.push(btn('Connect now', 'primary', 'connect', r.key, { grow: true, icon: 'link' }));
    m.actions = acts;
    return m;
  }
  function detailText(t) {
    t = String(t || '').trim().replace(/\s+--\s+/g, '. ').replace(/\s+—\s+/g, '. ');
    const found = /^detected at (\S+)$/.exec(t);
    if (found) return S.network.ssid ? `Found on ${S.network.ssid}` : `Found at ${found[1]}`;
    return cap(t);
  }
  function clockOrAgo(ts) {
    if (!ts) return 'a while ago';
    const d = new Date(ts * 1000);
    return d.toDateString() === new Date().toDateString()
      ? d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }

  function takeOverBtn(r, label) {
    return staff() ? btn('Take over', 'quiet', 'override', r.key, { grow: true, title: 'Lab staff: take this robot from the other laptop' })
      : btn(label, 'primary', 'launch', r.key, { grow: true, disabled: true, title: `In use by ${r.in_use_by}` });
  }

  function mainAction(r, m, c) {
    const st = r.state;
    const ready = c.connected && !c.launching && !r.posture_pending;
    const busyBtn = () => btn('', 'primary', 'noop', r.key, { grow: true, busy: true, disabled: true, html: `Starting… ${secondsText(c.secs)}` });
    if (c.launching) return busyBtn();
    if (st === 'ERROR') return btn('Connect now', 'primary', 'connect', r.key, { grow: true, icon: 'link' });
    switch (r.type_id) {
      case 'reachy_wireless': {
        if (r.in_use_by && st !== 'RUNNING') {
          return staff() ? btn('Take over', 'quiet', 'override', r.key, { grow: true, title: 'Lab staff: take this robot from the other laptop' })
            : btn('Talk', 'primary', 'talk', r.key, { grow: true, disabled: true });
        }
        if (r.launch_error) return btn('Try again', 'primary', 'talk', r.key, { grow: true });
        if (oldDaemon(r) && st !== 'RUNNING') return null;
        const label = st === 'RUNNING' ? 'Open' : 'Talk';
        return btn(label, 'primary', 'talk', r.key, { grow: true, disabled: m.cantTalk || st === 'CONNECTING',
          title: 'Opens the Reachy app: Talk with this Reachy, or a group' });
      }
      case 'furhat': {
        const pw = ((S.settings.passwords || {}).furhat || {});
        if ((pw.works === false || r._pwBad) && st !== 'RUNNING') return btn('Enter password', 'primary', 'password', r.key, { grow: true, icon: 'key' });
        if (st === 'RUNNING' && r.system_url) return btn('Open Studio', 'primary', 'open', r.key, { grow: true, icon: 'ext' });
        return btn(r.launch_error ? 'Try again' : 'Open Studio', 'primary', 'launch', r.key, { grow: true, icon: 'ext', disabled: !ready });
      }
      case 'pepper':
        if (r.in_use_by && st !== 'RUNNING') return takeOverBtn(r, 'Open dashboard');
        if (st === 'RUNNING' && r.system_url) return btn('Open dashboard', 'primary', 'open', r.key, { grow: true, icon: 'ext' });
        return btn(r.launch_error ? 'Try again' : 'Open dashboard', 'primary', 'launch', r.key, { grow: true, icon: 'ext', disabled: !ready });
      case 'naoqi':
        if ((r.staff_only_actions || ['nao_app']).includes('nao_app') && !staff()) return null;
        if (r.posture_pending || r.posture_failed || ui.armed[r.key]) return null;
        if (r.in_use_by && st !== 'RUNNING') return takeOverBtn(r, 'NAO app');
        if (st === 'RUNNING' && r.system_url) return btn('', 'primary', 'open', r.key, { grow: true, icon: 'ext', html: 'Open NAO app' + STAFF_TAG, title: 'Lab staff tool' });
        return btn('', 'primary', 'launch', r.key, { grow: true, icon: 'ext', html: (r.launch_error ? 'Try again' : 'NAO app') + STAFF_TAG, disabled: !ready, title: 'Lab staff tool' });
      case 'reachy_lite':
        if (st === 'RUNNING' && r.system_url) return btn('Open', 'primary', 'open', r.key, { grow: true, icon: 'ext' });
        return btn(r.launch_error ? 'Try again' : 'Open', 'primary', 'launch', r.key, { grow: true, icon: 'ext', disabled: !ready });
      default: return null;
    }
  }

  function keyPicker(r, slots, where) {
    const pepper = r.type_id === 'pepper';
    const out = [];
    Object.keys(slots).forEach(slot => {
      const s = slots[slot];
      const provs = s.providers || [];
      const keys = S.keys.keys.filter(k => provs.includes(k.provider));
      const defProv = DEFAULT_PROV[`${r.type_id}/${slot}`] || (slot === 'voice' ? 'ElevenLabs' : 'Gemini');
      let defText;
      if (!s.key) defText = pepper && slot === 'main' ? 'No GPT key yet' : (slot === 'voice' ? 'No voice key yet' : 'No key yet');
      else if (!s.assigned) defText = 'Default: ' + optText(s.key, slot);
      else defText = `Default: first ${defProv} key`;
      const label = slot === 'voice' ? 'Voice key' : (pepper ? 'Speaks through (GPT)' : 'Speaks through');
      const opts = [`<option value=""${!s.assigned ? ' selected' : ''}>${esc(defText)}</option>`]
        .concat(keys.map(k => `<option value="${esc(k.id)}"${s.assigned === k.id ? ' selected' : ''}>${esc(optText(k, slot))}${slot === 'main' && !TALKS.includes(k.provider) && r.type_id === 'reachy_wireless' && k.provider !== 'openrouter' ? " · can't talk" : ''}</option>`));
      const id = `ks-${where}-${r.key}-${slot}`;
      out.push(`<p class="lbl"${slot === 'voice' ? ' style="margin-top:4px"' : ''}><label for="${esc(id)}">${label}</label></p>` +
        `<select id="${esc(id)}" data-fid="${esc(id)}" class="select${!s.assigned ? ' def' : ''}" data-act="pick-key" data-key="${esc(r.key)}" data-slot="${slot}" title="Which key this robot speaks through; sent when it starts">${opts.join('')}</select>`);
    });
    // One short line under the picker(s).
    const main = slots.main || {};
    let sub = '';
    if (isReachy(r)) {
      const how = /first (\w+) key/.exec(main.how || '');
      if (!main.assigned && main.key) sub = `<span class="tag">Default</span>${how ? `First ${esc(how[1])} key.` : ''} Used when it talks alone.`;
      else if (main.key) sub = where === 'sheet' ? "Used when it talks alone. Groups use each robot's voice service. Applies next Talk." : 'Used when it talks alone. Applies next Talk.';
    } else if (pepper) {
      sub = r.state === 'RUNNING' && (ui.changedRunning[r.key] || r._changedRunning) ? 'New key applies after Disconnect, then Open dashboard.' : 'Applies next start';
    } else if (r.state === 'RUNNING') sub = 'Applies next start';
    const noKey = !S.keys.keys.length;
    const add = noKey || where === 'sheet' ? `<p class="sub"><a href="#" data-act="add-key">Add a key</a></p>` : '';
    return `<div class="ai">${out.join('')}${sub ? `<p class="sub">${sub}</p>` : ''}${add}</div>`;
  }

  function postureHtml(r, launching) {
    const ready = ['CONNECTED', 'RUNNING'].includes(r.state) && !launching && !r.posture_pending;
    const armed = !!ui.armed[r.key];
    const p = r.posture_pending;
    const b = (name, text, title) => `<button class="btn ${name === 'stand' && armed ? 'btn-arm' : 'btn-quiet'}${p === name ? ' busy' : ''}" type="button" data-act="posture" data-key="${esc(r.key)}" data-name="${name}" title="${esc(title)}"${ready ? '' : ' disabled'}>${text}</button>`;
    let html = `<div class="postures">${b('sit', 'Sit', 'Sit on the floor, then motors off')}${b('lie', 'Lie down', 'Lie on its back, then motors off')}${b('stand', armed ? 'Confirm' : 'Stand up', 'Stand up, motors stay on. Someone should be next to it')}</div>`;
    if (armed) {
      html += r.battery_low && typeof r.battery === 'number'
        ? noteHtml('warn', 'battery', `Battery ${r.battery}%. It may fall. Someone next to it? Confirm within 5 s.`)
        : noteHtml('warn', 'alert', 'Motors stay on. Someone next to NAO? Tap Confirm.');
    } else if (ui.postureErr[r.key]) {
      html += noteHtml('err', 'alert', esc(sentence(ui.postureErr[r.key])));
    } else if (r.posture_note && !p) {
      const note = r.posture_note;
      if (r.posture_failed) html += noteHtml('err', 'alert', esc(postureText(note)));
      else if (/already|nothing moved/i.test(note)) html += noteHtml('', 'info', esc(postureText(note)));
      else html += `<p class="note ok">${esc(postureText(note))}</p>`;
    }
    return html;
  }
  function postureText(note) {
    let t = String(note || '').trim();
    t = t.replace(/^NAO is (sitting|lying down|lying|standing)(.*?)\s*\(hottest joint: (.+?)\)\.?$/i,
      (_, a, b, c) => `${cap(a)}${b.replace(/[,\s]+$/, '')}. Hottest joint: ${c}`);
    t = t.replace(/(\d) °C/g, '$1 °C');
    return cap(t.replace(/\s+—\s+/g, '. ').replace(/ -- /g, '. '));
  }

  function cardHtml(r) {
    const m = cardModel(r);
    const side = `<div class="side">${r.key.startsWith('placeholder:') && r.state !== 'DISABLED' ? '' :
      `<button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="details" data-key="${esc(r.key)}" aria-label="${esc(r.name)} details">${ic('more', 18)}</button>`}${ui.moved[r.key] && r.state === 'ABSENT' ? '' : (TYPE_ORDER.includes(r.type_id) ? metricHtml(r) : `<span class="metric">${esc(r.address || '')}</span>`)}</div>`;
    const tile = TYPE_ORDER.includes(r.type_id) ? `<img class="tile" src="${typeImg(r.type_id)}" alt="" onerror="this.removeAttribute('src')">` : '<div class="tile"></div>';
    return `<article class="card ${m.cls}" aria-label="${esc(r.name)}">
      <div class="head">${tile}<div class="who"><p class="name">${esc(r.name)}${m.nameIcon || ''}</p>${m.pill}</div>${side}</div>
      ${m.detail ? `<p class="detail">${esc(m.detail)}</p>` : ''}${m.body}${m.notes.join('')}
      ${m.actions.length ? `<div class="actions">${m.actions.join('')}</div>` : ''}
    </article>`;
  }

  /* ------------------------------------------------------------ sheets */
  function renderSheet() {
    const layer = $('#sheet-layer');
    const s = ui.sheet;
    if (!s) { if (layer.__shell) { layer.innerHTML = ''; layer.__shell = null; } return; }
    let html = '';
    if (s.kind === 'robot') html = robotSheet(s.key);
    else if (s.kind === 'network') html = networkSheet();
    else if (s.kind === 'setup') html = setupSheet(s.id);
    if (!html) { ui.sheet = null; layer.innerHTML = ''; layer.__shell = null; return; }
    // html = '<aside ...attrs>inner</aside>': keep the aside, swap the inside.
    const open = html.indexOf('>');
    const tag = html.slice(0, open + 1).replace('<aside', '<aside data-inner');
    const inner = html.slice(open + 1, html.lastIndexOf('</aside>'));
    const id = `${s.kind}:${s.key || s.id || ''}`;
    put(shell(layer, id, `<div class="scrim" data-act="close-sheet" aria-hidden="true"></div>${tag}</aside>`), inner);
  }

  function robotSheet(key) {
    const r = S.robots.get(key);
    if (!r) return '';
    const m = cardModel(r);
    const f = r.facts || {};
    const n = S.network;
    const facts = [['Robot', TYPE_LABEL[r.type_id] || r.type_id]];
    if (r.address) facts.push(['Address', r.address + (n.ssid && r.type_id !== 'reachy_lite' ? ` on ${n.ssid}` : '')]);
    else if (r.type_id === 'reachy_lite') facts.push(['Link', r.state === 'ABSENT' ? 'Unplugged' : 'USB']);
    if (f.mic || r.mic) facts.push(['Listens with', f.mic || r.mic]);
    if (f.robot_software || r.daemon_version) facts.push(['Robot software', f.robot_software || r.daemon_version]);
    if (typeof r.battery === 'number') facts.push(['Battery', `${r.battery}%${r.charging ? ', charging' : ''}`]);
    if (r.system_url) facts.push(['App', appText(r)]);
    if ((f.holds || []).length) facts.push(['Uses on this laptop', f.holds.join(', ')]);
    if (r.in_use_by) facts.push(['In use by', r.in_use_by]);
    facts.push(['Seen', r.state === 'ABSENT' ? `Last seen ${clockOrAgo(r.last_seen)}` : seenText(r)]);
    const dl = facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');
    const canDis = CONNECTED.includes(r.state) || r.state === 'ERROR';
    const extra = isReachy(r) ? btn('Wizard of Oz', 'ghost', 'woz', r.key, { icon: 'ext', style: 'min-height:40px', title: 'Type lines for the robot to say' }) : '';
    const slots = slotsFor(r);
    const keySec = slots ? `<section class="sec">${keyPicker(r, slots, 'sheet')}</section>` : '';
    const wifiSec = wifiSection(r);
    return `<aside class="sheet" role="dialog" aria-modal="true" aria-label="${esc(r.name)} details">
      <div class="sheet-head">
        <img class="tile" src="${typeImg(r.type_id)}" alt="">
        <div class="who"><p class="name">${esc(r.name)}${m.nameIcon || ''}</p>${m.pill}</div>
        ${typeof r.battery === 'number' ? metricHtml(r) : ''}
        <button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="close-sheet" aria-label="Close">${ic('x', 18)}</button>
      </div>
      <div class="sheet-body" data-scroll="sheet">
        <section class="sec">
          ${m.detail || r.detail ? `<p class="detail" style="color:#1C1917;font-size:15px">${esc(m.detail || detailText(r.detail))}</p>` : ''}
          <dl class="facts">${dl}</dl>
          <div style="display:flex;gap:8px;flex-wrap:wrap">${canDis ? btn('Disconnect', 'quiet', 'disconnect', r.key, { icon: 'unlink', style: 'min-height:40px' }) : ''}${btn(ui.copied ? 'Copied' : 'Copy details', 'ghost', 'copy-details', r.key, { icon: ui.copied ? 'check' : 'copy', style: 'min-height:40px' })}${extra}</div>
          ${m.notes.length ? m.notes.join('') : ''}
        </section>
        ${keySec}
        ${wifiSec}
      </div>
    </aside>`;
  }
  function seenText(r) {
    // facts.seen_ago is exact when the event or GET /api/robots/{key} left
    // the hub; the probe keeps a present robot fresh without publishing.
    const d = r._detail && r._detail._at > (r._rx || 0) ? r._detail : null;
    const base = d ? (d.facts || {}).seen_ago : (r.facts || {}).seen_ago;
    const at = d ? d._at : r._rx;
    if (base == null) return 'Just now';
    const secs = base + (Date.now() - (at || Date.now())) / 1000;
    return secs < 5 ? 'Just now' : agoText(Math.floor(secs / 5) * 5);
  }
  function appText(r) {
    const u = r.system_url || '';
    const port = /:(\d+)\/?/.exec(u.replace(/^https?:\/\//, ''));
    if (/^https?:\/\/(127\.0\.0\.1|localhost)/.test(u)) {
      return (r.type_id === 'pepper' ? 'Dashboard' : r.type_id === 'naoqi' ? 'NAO app' : 'App') + ` on this laptop${port ? ', port ' + port[1] : ''}`;
    }
    return u;
  }

  function wifiSection(r) {
    const detail = r._detail || {};
    const has = detail.has_wifi !== undefined ? detail.has_wifi : ['naoqi', 'pepper', 'reachy_wireless'].includes(r.type_id);
    if (!has || !staff() || r.key.startsWith('placeholder:')) return '';
    const f = ui.wifi[r.key] || (ui.wifi[r.key] = { ssid: '', pw: '', open: false, save: false });
    const reachy = isReachy(r);
    const busy = !!ui.wifiBusy[r.key];
    const note = ui.wifiNote[r.key];
    const k = ui.known[r.key];
    let knows = '';
    if (k && k.loading) knows = '<p class="sub">Knows: <span class="spin" aria-hidden="true"></span> asking the robot…</p>';
    else if (k && k.error) knows = `<p class="sub">Knows: couldn't ask (${esc(k.error)}) <a href="#" data-act="known-refresh" data-key="${esc(r.key)}">Ask again</a></p>`;
    else if (k && k.networks) {
      const list = k.networks.map(nw => (nw.current ? `<b style="color:#1C1917">${esc(nw.ssid)}</b> (connected now)` : esc(nw.ssid)) + (nw.note ? ` (${esc(nw.note)})` : ''));
      knows = `<p class="sub" style="font-size:13.5px;display:block">Knows: ${list.length ? list.join(' · ') : 'nothing saved yet'}</p>`;
    }
    const id = s => `wf-${s}-${r.key}`;
    return `<section class="sec" aria-label="Add WiFi">
      <div class="sechd"><h3 class="lbl" style="flex:1 1 auto">Add WiFi</h3><span class="tag tag-dark">Lab staff</span></div>
      <div class="field"><label for="${esc(id('ssid'))}">WiFi name</label><input id="${esc(id('ssid'))}" data-fid="${esc(id('ssid'))}" class="input" type="text" maxlength="32" autocomplete="off" spellcheck="false" data-bind="wifi" data-key="${esc(r.key)}" data-field="ssid" value="${esc(f.ssid)}"${busy ? ' disabled' : ''}></div>
      ${f.open ? '' : `<div class="field"><label for="${esc(id('pw'))}">Password</label><input id="${esc(id('pw'))}" data-fid="${esc(id('pw'))}" class="input" type="password" maxlength="63" autocomplete="off" data-bind="wifi" data-key="${esc(r.key)}" data-field="pw" value="${esc(f.pw)}"${busy ? ' disabled' : ''}></div>`}
      <label class="check"><input type="checkbox" data-bind="wifi" data-key="${esc(r.key)}" data-field="open"${f.open ? ' checked' : ''}${busy ? ' disabled' : ''}>Open WiFi, no password</label>
      ${reachy ? `<label class="check"><input type="checkbox" data-bind="wifi" data-key="${esc(r.key)}" data-field="save"${f.save ? ' checked' : ''}${busy ? ' disabled' : ''}>Save only, don't move now (lab WiFi fallback) <span class="muted">(Reachy only)</span></label>` : ''}
      ${knows}
      <p class="sub">${f.open ? '' : '8 to 63 characters. '}Turn the hotspot on first, 2.4 GHz.</p>
      <div style="display:flex"><button class="btn btn-dark${busy ? ' busy' : ''}" type="button" data-act="wifi-join" data-key="${esc(r.key)}"${busy ? ' disabled' : ''}>${busy ? (f.save ? 'Saving…' : 'Joining…') : 'Join'}</button></div>
      ${busy ? `<p class="note"><span class="spin" aria-hidden="true"></span><span>${f.save ? `Saving "${esc(f.ssid)}" as the lab WiFi…` : `Joining "${esc(f.ssid)}"… up to a minute. Keep that hotspot on.`}</span></p>` : ''}
      ${!busy && note ? `<p class="note ${note.kind}">${ic(note.kind === 'ok' ? 'check' : (note.icon || (note.kind === 'warn' ? 'info' : 'alert')), 18)}<span>${esc(note.text)}</span></p>` : ''}
    </section>`;
  }

  function steps(items) { return items.map(i => `<li>${i}</li>`).join(''); }
  function accordion(id, imgName, title, items, ordered) {
    const open = ui.acc ? ui.acc[id] !== false : true;
    const tag = ordered === false ? 'ul' : 'ol';
    return `<div class="acc${open ? ' open' : ''}"><button class="acchd" type="button" data-act="acc" data-id="${id}" aria-expanded="${open}">${imgName ? `<img src="${img(imgName)}" alt="">` : ''}${title}${ic('chev', 16)}</button>${open ? `<div class="accbody"><${tag}>${steps(items)}</${tag}></div>` : ''}</div>`;
  }
  function networkSheet() {
    const n = S.network;
    const lab = esc(labWifi() || 'the lab WiFi');
    const problem = NET_PROBLEMS.includes(n.state);
    const searching = n.state === 'searching';
    const hs = n.hotspot || { devices: 1, limit: 5 };
    let status;
    if (problem) status = `<p class="note ${n.state === 'no_network' ? 'err' : 'warn'}">${ic('alert', 18)}<span>${networkProblemText(n)}</span></p>`;
    else if (searching) status = `<p class="note"><span class="spin" aria-hidden="true"></span><span>Looking for robots${n.ssid ? ` on <b>${esc(n.ssid)}</b>` : ''}.</span></p>`;
    else {
      const kind = n.kind === 'hotspot' ? `phone hotspot, ${hs.devices} of ${hs.limit} devices` : (n.kind === 'lab' ? 'the lab WiFi' : '');
      status = `<p class="note ok">${ic('check', 18)}<span>This laptop is on <b>${esc(n.ssid || 'a network')}</b>${kind ? ` · ${esc(kind)}` : ''}${n.band ? ` · ${esc(n.band)}` : ''}. Robots can join it.</span></p>`;
    }
    const ranges = (n.ranges || []).join(', ');
    const range = n.on_robot_subnet === false ? "off the robots' network" : (ranges || 'this network');
    const pill = problem ? pillHtml('warn', 'Needs attention') : (searching ? pillHtml('busy', 'Checking', true) : pillHtml('run', 'Ready'));
    return `<aside class="sheet wide" role="dialog" aria-modal="true" aria-label="Network">
      <div class="sheet-head">
        <span class="htile${problem ? ' warn' : ''}">${ic('wifi', 20)}</span>
        <div class="who"><p class="name">Network</p>${pill}</div>
        <button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="close-sheet" aria-label="Close">${ic('x', 18)}</button>
      </div>
      <div class="sheet-body" data-scroll="sheet">
        <section class="sec" aria-live="polite">
          ${status}
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn ${problem ? 'btn-primary' : 'btn-quiet'}" style="min-height:40px" type="button" data-act="wifi-settings">${ic('wifi', 18)}Open WiFi settings</button>
            <button class="btn btn-quiet" style="min-height:40px" type="button" data-act="net-check"${ui.netChecking ? ' disabled' : ''}>${ic('refresh', 18, ui.netChecking ? 'spinning' : '')}${ui.netChecking ? 'Checking…' : 'Check again'}</button>
          </div>
          <p class="sub">${ic('radar', 14)}Looking on ${esc(range)} · <a href="#" data-act="scan">Scan now</a></p>
          ${n.vpn && n.vpn.length ? `<p class="sub">VPN: ${esc(n.vpn.join(', '))}</p>` : ''}
        </section>
        <section class="sec">
          <h3 class="lbl">Set up</h3>
          <ol class="steps">
            <li><span class="num">1</span><div class="stepbody"><b>This laptop on ${lab}</b><ul><li>Turn off auto-join for other WiFi.</li><li>Robots show up in about 30 s.</li><li>The hub looks for robots by address; this WiFi drops their name announcements.</li></ul></div></li>
            <li><span class="num">2</span><div class="stepbody"><b>Each robot on ${lab}, once</b>
              ${accordion('reachy', 'robot-reachy-wireless.png', 'Reachy Mini', [
                'New robot: lab staff bring it up (<code>tools\\reachy_bringup.py</code>).',
                'Older robot: run the bring-up with its own name (<code>--name reachyN</code>) from its <code>reachy-mini-ap</code> WiFi.',
                'Still on a hotspot you have: Add WiFi in its details, tick Save only.'])}
              ${accordion('nao', 'robot-naoqi.png', 'NAO', [
                'Plug NAO into this laptop with a cable.',
                'Press its chest button: it says its address.',
                `Open that address, Network, pick ${lab}.`,
                'No luck? Lab staff: connmanctl over SSH.'])}
              ${accordion('furhat', 'robot-furhat.png', 'Furhat', [
                `On Furhat's own screen: Settings, WiFi, ${lab}.`,
                'Turn it off and on. It looks for WiFi only while it starts.'])}
              ${accordion('pepper', 'robot-pepper.png', 'Pepper', [
                `On the tablet: Settings, WiFi, ${lab}.`,
                'Never use Advanced Settings.'])}
            </div></li>
            <li><span class="num">3</span><div class="stepbody"><b>Still missing?</b><ul><li>A robot's address starts like this laptop's. The hub looks 4 numbers either side.</li><li><a href="#" data-act="scan">Scan now</a>.</li><li>Turn the robot off and on.</li></ul></div></li>
          </ol>
        </section>
        <section class="sec">
          <h3 class="lbl">Outside the lab</h3>
          <p class="detail" style="color:#1C1917">One phone hotspot for the laptop and the robots. 2.4 GHz, a plain name, up to 5 devices.</p>
          ${accordion('hotspot', '', 'Phone hotspot tips', [
            'iPhone: Personal Hotspot, Allow Others to Join and Maximize Compatibility on. Keep that screen open while a robot joins.',
            'Android: hotspot band 2.4 GHz.',
            'A plain name: letters, digits and spaces only.',
            'Same name and password on every lab phone: a robot that knows one knows them all.',
            'Teach a robot your hotspot in the lab first: Add WiFi in its details (lab staff).',
            `On a hotspot, "not ${lab}" is expected.`], false)}
          <div style="display:flex"><a class="btn btn-quiet btn-sm" href="#hotspot">Plan a hotspot demo</a></div>
        </section>
      </div>
    </aside>`;
  }
  function networkProblemText(n) {
    switch (n.state) {
      case 'no_network': return 'This laptop is not on any network.';
      case 'wrong_network': return `This laptop is on <b>${esc(n.ssid || 'another WiFi')}</b>. The robots are on <b>${esc(expectedWifi())}</b>.`;
      case 'hotspot_5ghz': return `Your hotspot is on ${esc(n.band || '5 GHz')}. Robots only see 2.4 GHz. Turn on Maximize Compatibility.`;
      case 'vpn_on': return 'A VPN is on. Robots may not show up until you turn it off.';
      case 'isolated': return `<b>${esc(n.ssid || 'This WiFi')}</b> keeps devices apart. Robots can't be reached on it.`;
      default: return esc(n.detail || '');
    }
  }

  const SETUP_TEXT = {
    naoqi_kit: { title: 'Set up Pepper and NAO', sub: 'One free download. Once.', size: "360 MB, from the robots' maker", types: ['pepper', 'naoqi'] },
    reachy_lite_app: { title: 'Set up Reachy Mini Lite', sub: "Pollen's Reachy Mini Control app, for the USB Reachy.", size: 'From Pollen Robotics', types: ['reachy_lite'] },
    furhat_password: { title: 'Furhat password', sub: 'For Furhat Studio.', size: '', types: ['furhat'] },
  };
  function setupFailure(item) {
    switch (item.code) {
      case 'DOWNLOAD_BROKE': return { html: '<b>Download stopped.</b> Check the internet.', act: 'download', label: 'Try again', kind: 'primary' };
      case 'WRONG_ZIP': return { html: "<b>That's not the kit.</b> Pick the zip whose name starts with pynaoqi.", act: 'choose_zip', label: 'Choose again', kind: 'quiet' };
      case 'DISK_FULL': return { html: '<b>Not enough space.</b> Free 1.5 GB, then try again.', act: 'download', label: 'Try again', kind: 'quiet' };
      case 'PERMISSION': case 'ADMIN_REFUSED': return { html: '<b>Windows said no.</b> The lab needs to allow it once.', act: 'check', label: 'Check again', kind: 'quiet', report: true };
      default: return { html: esc(sentence(item.detail || "It didn't work.")), act: 'download', label: 'Try again', kind: 'primary' };
    }
  }
  function setupSheet(id) {
    const item = setupItem(id);
    if (!item) return '';
    const t = SETUP_TEXT[id] || { title: item.label, sub: '', size: '', types: item.for || [] };
    const p = item.progress || {};
    const pct = p.total ? Math.min(100, Math.round(100 * p.done / p.total)) : 0;
    const acts = item.actions || [];
    let body = '';
    if (item.state === 'downloading') {
      body = `<div style="display:flex;flex-direction:column;gap:8px" role="status"><div class="pbar"><span style="width:${pct}%"></span></div>
        <div class="prog"><span>Downloading${p.total ? `, ${Math.round(p.done / 1048576)} of ${Math.round(p.total / 1048576)} MB` : ''}</span><span>${pct}%</span></div></div>
        <div>${btn('Cancel', 'ghost', 'setup-act', null, { data: ` data-id="${id}" data-action="cancel"` })}</div>`;
    } else if (item.state === 'unpacking') {
      body = `<div style="display:flex;flex-direction:column;gap:8px" role="status"><div class="pbar"><span style="width:${pct}%"></span></div>
        <div class="prog"><span>Unpacking</span><span>${p.total ? pct + '%' : ''}</span></div></div>
        ${acts.includes('cancel') ? `<div>${btn('Cancel', 'ghost', 'setup-act', null, { data: ` data-id="${id}" data-action="cancel"` })}</div>` : ''}`;
    } else if (item.state === 'verifying') {
      body = `<div style="display:flex;flex-direction:column;gap:8px" role="status"><div class="prog"><span>Checking it works</span><span></span></div><div class="pbar grey"><span style="width:100%"></span></div></div>`;
    } else if (item.state === 'failed') {
      const f = setupFailure(item);
      body = `<div class="res bad" role="alert"><span>${f.html}</span></div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">${acts.includes(f.act) || f.act === 'check' ? btn(f.label, f.kind, 'setup-act', null, { data: ` data-id="${id}" data-action="${f.act}"` }) : ''}${f.report ? btn('Save a report for the lab', 'ghost', 'report') : ''}${f.act !== 'choose_zip' && acts.includes('choose_zip') ? btn('I have the zip', 'ghost', 'setup-act', null, { data: ` data-id="${id}" data-action="choose_zip"` }) : ''}</div>`;
    } else if (item.state === 'missing') {
      const get = acts.includes('download')
        ? btn('Get it', 'primary', 'setup-act', null, { icon: 'download', data: ` data-id="${id}" data-action="download"` })
        : btn('Get it', 'primary', 'setup-act', null, { icon: 'ext', data: ` data-id="${id}" data-action="open"` });
      body = `<div style="display:flex;gap:8px;flex-wrap:wrap">${get}${acts.includes('choose_zip') ? btn('I have the zip', 'ghost', 'setup-act', null, { data: ` data-id="${id}" data-action="choose_zip"` }) : ''}${!acts.includes('download') ? btn('Check again', 'ghost', 'setup-act', null, { data: ` data-id="${id}" data-action="check"` }) : ''}</div>`;
    }
    const done = item.state === 'ok';
    return `<aside class="sheet ssheet" role="dialog" aria-modal="true" aria-labelledby="s-title">
      <div style="display:flex;align-items:flex-start;gap:12px">
        <div class="robots-row" aria-hidden="true">${t.types.map(x => `<img src="${typeImg(x)}" alt="">`).join('')}</div>
        <span class="spacer"></span>
        <button class="btn btn-ghost btn-icon" type="button" data-act="close-sheet" aria-label="Close">${ic('x', 20)}</button>
      </div>
      <div style="display:flex;flex-direction:column;gap:6px"><h2 id="s-title" class="h2x">${esc(t.title)}</h2><p class="muted" style="margin:0">${esc(t.sub)}</p></div>
      <div class="step${done ? ' done' : ''}">
        <div class="stephead"><div style="flex:1 1 auto;min-width:0"><p class="title">${esc(item.label)}</p><p class="muted small" style="margin:2px 0 0">${esc(done ? item.detail || 'Installed.' : t.size)}</p></div>
          ${done ? `<span class="found">${ic('check', 16)}Installed</span>` : ''}</div>
        ${body}
      </div>
      <div class="sfoot">
        ${acts.includes('open') ? `<a href="#" class="small" style="font-weight:500" data-act="setup-act" data-id="${id}" data-action="open">Stuck?</a>` : ''}
        <span class="spacer"></span>
        ${done ? btn('Done', 'primary', 'close-sheet') : ''}
      </div>
    </aside>`;
  }

  /* ------------------------------------------------------------ logs drawer */
  function logSource(e) {
    const text = e.text || '';
    // A line belongs to a robot only when it starts with the name, or the
    // backend said so; a line that merely lists robots is the Hub's.
    for (const r of realRobots()) {
      const n = r.name;
      if (!n) continue;
      if (e.source === n || text === n || text.startsWith(n + ':') || text.startsWith(n + ' ')) return n;
    }
    if (e.source) return e.source === 'group' || /group/.test(e.source) ? 'Reachy app' : e.source;
    return 'Hub';
  }
  function logText(x) {
    const t = String(x.e.text || '');
    const p = x.src + ':';
    return t.startsWith(p) ? cap(t.slice(p.length).trim()) : t;
  }
  function renderLogs() {
    const host = $('#logs-layer');
    if (!ui.logs) { if (host.__shell) { host.innerHTML = ''; host.__shell = null; } return; }
    const names = sortRobots(realRobots()).map(r => r.name);
    const filters = ['all'].concat(names, ['Hub']);
    if (ui.logFilter !== 'all' && !filters.includes(ui.logFilter) && ui.logFilter !== 'Reachy app') ui.logFilter = 'all';
    const lines = S.log.map(e => ({ e, src: logSource(e) }))
      .filter(x => ui.logFilter === 'all' || x.src === ui.logFilter);
    const cls = { ok: 'ok', warn: 'warn', error: 'err', info: '' };
    const body = lines.length ? lines.map(x => `<div class="ln"><span class="t">${clock(x.e.ts)}</span><span class="src">${esc(x.src)}</span><span class="${cls[x.e.level] || ''}">${esc(logText(x))}</span></div>`).join('')
      : '<div class="ln none">Nothing yet.</div>';
    const html = `
      <div class="grab" aria-hidden="true"></div>
      <div class="dhead">
        <h2 class="dhtitle"><span class="pulse" aria-hidden="true"></span>Live logs</h2>
        <span style="width:8px"></span>
        ${filters.map(f => `<button class="filter${ui.logFilter === f ? ' on' : ''}" type="button" aria-pressed="${ui.logFilter === f}" data-act="log-filter" data-f="${esc(f)}">${f === 'all' ? 'All' : esc(f)}</button>`).join('')}
        <span class="spacer"></span>
        <button class="dbtn" type="button" data-act="log-copy">${ic(ui.logCopied ? 'check' : 'copy', 16)}${ui.logCopied ? 'Copied' : 'Copy all'}</button>
        <button class="dbtn" type="button" data-act="report"${ui.reportBusy ? ' disabled' : ''}>${ui.reportBusy ? '<span class="spin" aria-hidden="true"></span>' : ic('download', 16)}Save a report for the lab</button>
        <button class="dbtn" type="button" data-act="logs" aria-label="Close logs" style="padding:0 10px">${ic('x', 16)}</button>
      </div>
      <div class="lines" id="log-lines" role="log" aria-live="polite" tabindex="0">${body}</div>
      ${ui.logPinned ? '' : `<button class="dbtn jump" type="button" data-act="log-jump">Jump to latest</button>`}`;
    const prevLines = $('#log-lines');
    const keep = prevLines ? prevLines.scrollTop : 0;
    put(shell(host, 'logs', '<section class="drawer" aria-label="Live logs" data-inner></section>'), html);
    const el = $('#log-lines');
    if (el) {
      if (ui.logPinned) el.scrollTop = el.scrollHeight; else el.scrollTop = keep;
      if (!el.__wired) {
        el.__wired = true;
        el.addEventListener('scroll', () => {
          const pinned = el.scrollTop + el.clientHeight >= el.scrollHeight - 8;
          if (pinned !== ui.logPinned) { ui.logPinned = pinned; render(); }
        });
      }
    }
  }

  /* ------------------------------------------------------------ key popup (first open) */
  function detectProvider(k) {
    const s = (k || '').trim().replace(/^bearer\s+/i, '').replace(/^["']|["']$/g, '');
    if (!s) return null;
    if (s.startsWith('AIza')) return 'gemini';
    if (s.startsWith('sk-or-')) return 'openrouter';
    if (s.startsWith('sk_')) return 'elevenlabs';
    if (s.startsWith('sk-')) return 'gpt';
    return 'unknown';
  }
  function openPopup() {
    ui.popup = { key: '', provider: 'auto', phase: 'idle', result: null, help: false };
  }
  function keyResult(res, provider) {
    // -> {kind, html, chips?} for the popup and the Settings add row
    if (res.ok) {
      const k = res.key || {};
      const st = (k.status || {}).state;
      if (st === 'no_credit') return { kind: 'warn', icon: 'info', html: '<b>Works, but no credit left.</b> Ask the lab for a top-up.', saved: true };
      if (st === 'offline') return { kind: 'info', icon: 'wifioff', html: "<b>Saved.</b> No internet, so it's checked later.", saved: true };
      if (k.provider === 'elevenlabs' && !hasTalkingKey()) return { kind: 'warn', icon: 'info', html: '<b>Voices only.</b> Add an OpenAI, Gemini or OpenRouter key to talk.', saved: true };
      if (k.provider === 'elevenlabs') return { kind: 'ok', icon: 'check', html: '<b>It works.</b> Nicer voices on.', saved: true };
      if (k.provider === 'openrouter') return { kind: 'ok', icon: 'check', html: '<b>It works.</b> Group talk can use it.', saved: true };
      return { kind: 'ok', icon: 'check', html: '<b>It works.</b> All robots can talk.', saved: true };
    }
    switch (res.code) {
      case 'DUPLICATE': return { kind: 'warn', html: res.label ? `<b>Already added</b> as "${esc(res.label)}".` : '<b>Already added.</b> It is in Settings.' };
      case 'NOT_A_KEY': return { kind: 'warn', html: "<b>That doesn't look like a key.</b> Paste the whole key." };
      case 'UNKNOWN_PROVIDER': return { kind: 'chips', html: 'Which service is it from?', chips: ['gpt', 'gemini', 'openrouter', 'elevenlabs'] };
      case 'KEY_REFUSED': return { kind: 'bad', icon: 'xcircle', html: "<b>That key didn't work.</b> Copy it again, all of it." };
      case 'HUB_DOWN': return { kind: 'bad', icon: 'xcircle', html: "<b>Couldn't ask the hub.</b> Is Robot Hub running?" };
      default: return { kind: 'bad', icon: 'xcircle', html: esc(sentence(res.error || "That key didn't work.")) };
    }
  }
  function resultHtml(r) {
    if (!r) return '';
    if (r.kind === 'chips') {
      return `<p class="title" style="font-size:14px;margin:0">${r.html}</p><div class="kchips">${r.chips.map(p => `<button class="kchip" type="button" data-act="key-prov" data-p="${p}">${p === 'gpt' ? 'OpenAI' : PROV[p]}</button>`).join('')}</div>`;
    }
    return `<div class="res ${r.kind}" role="${r.kind === 'bad' || r.kind === 'warn' ? 'alert' : 'status'}">${r.icon ? ic(r.icon, 18) : ''}<span>${r.html}</span></div>`;
  }
  function renderPopup() {
    const host = $('#popup-layer');
    const p = ui.popup;
    if (!p) { if (host.__shell) { host.innerHTML = ''; host.__shell = null; } return; }
    const d = detectProvider(p.key);
    const label = d === 'unknown' ? 'Unknown key' : (d === 'gpt' ? 'OpenAI' : PROV[d]);
    const chosen = p.provider !== 'auto' ? (p.provider === 'gpt' ? 'OpenAI' : PROV[p.provider]) : label;
    const ok = p.result && p.result.saved;
    let res = '';
    if (p.phase === 'checking') res = `<div class="res checking" role="status"><span class="spin" aria-hidden="true"></span><span>Checking with ${esc(chosen && d !== 'unknown' ? chosen : 'the service')}…</span></div>`;
    else res = resultHtml(p.result);
    put(shell(host, 'popup', '<div class="mscrim"><section class="dialog enter" role="dialog" aria-modal="true" aria-labelledby="k-title" data-inner></section></div>'), `
        <div style="display:flex;flex-direction:column;gap:6px">
          <h2 id="k-title" class="dtitle">Add a key to get started</h2>
          <p class="muted" style="margin:0">From the lab, or your own. Any OpenAI, Gemini or OpenRouter key works.</p>
        </div>
        <div style="display:flex;flex-direction:column;gap:8px">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:26px">
            <label class="klabel" for="k-input">Your key</label>
            ${d ? `<span class="detect">${esc(p.provider !== 'auto' ? chosen : label)}</span>` : ''}
          </div>
          <input id="k-input" data-fid="k-input" class="kinput" type="password" autocomplete="off" spellcheck="false" placeholder="Paste it here" data-bind="popup" value="${esc(p.key)}"${p.phase === 'checking' ? ' disabled' : ''}>
          <p class="muted" style="margin:0;font-size:13px;display:flex;gap:6px;align-items:center">${ic('lock', 14)}Stays on this laptop.</p>
        </div>
        ${res}
        ${p.help ? `<p class="muted small" style="margin:0">Ask the lab manager for your own capped key, or make one on your AI service's site: OpenAI, Google AI Studio (Gemini) or OpenRouter. ElevenLabs keys add nicer voices.</p>` : ''}
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <a href="#" data-act="key-help" style="font-size:14px;font-weight:500">Where do I get a key?</a>
          <span class="spacer"></span>
          ${ok ? '' : btn('Later', 'ghost', 'key-later')}
          ${ok ? btn('Add another', 'ghost', 'key-another') + btn('Done', 'primary', 'key-done')
               : btn('Test and save', 'primary', 'key-test', null, { disabled: !d || p.phase === 'checking' })}
        </div>`);
    if (!ui.popupFocused) { ui.popupFocused = true; setTimeout(() => { const i = $('#k-input'); if (i) i.focus(); }, 30); }
  }

  /* ------------------------------------------------------------ overlays */
  function renderOverlays() {
    const host = $('#over-layer');
    if (ui.updating) {
      const v = (S.app.update || {}).latest || '';
      put(host, `<div class="over boot" role="status"><div class="center"><img class="mark spin" src="${img('labalab-mark.png')}" alt="">
        <p class="h" style="margin:0">Updating Robot Hub${v ? ` to ${esc(v)}` : ''}</p>
        <p class="muted" style="margin:0">Please wait, about two minutes. It opens again by itself.</p></div></div>`);
      return;
    }
    if (ui.autoUpd) {
      const left = Math.max(0, Math.ceil((ui.autoUpd.end - Date.now()) / 1000));
      put(host, `<div class="over boot" role="alertdialog" aria-labelledby="au-title"><div class="center"><img class="mark spin" src="${img('labalab-mark.png')}" alt="">
        <p id="au-title" class="h" style="margin:0">Robot Hub ${esc(ui.autoUpd.version)} is out</p>
        <p class="muted" style="margin:0">Updating in ${left} s. Please wait, it opens again by itself.</p>
        <div class="row" style="gap:8px;justify-content:center"><button class="btn btn-primary" type="button" data-act="update-now">Update now</button>
        <button class="btn btn-ghost" type="button" data-act="update-later">Not now</button></div></div></div>`);
      return;
    }
    if (ui.stopped) {
      put(host, `<div class="over"><div class="stopscrim"><div class="box" role="alertdialog" aria-labelledby="st-title">
        <p id="st-title" class="h">Robot Hub stopped</p>
        <p class="muted">Robots that were talking have stopped too.</p>
        ${ui.stopReason ? `<p class="muted small">${esc(ui.stopReason)}</p>` : ''}
        <button class="btn btn-primary" type="button" data-act="restart">Restart</button>
      </div></div></div>`);
      return;
    }
    put(host, '');
  }

  /* ------------------------------------------------------------ settings view */
  function statusPill(k) {
    const s = k.status || {};
    const credit = s.credit;
    switch (s.state) {
      case 'works':
        if (credit && credit.unit === 'usd' && typeof credit.left === 'number') return pillHtml('run', `$${credit.left.toFixed(2)} left`);
        if (credit && credit.unit === 'characters' && typeof credit.left === 'number') return pillHtml('run', `${credit.left.toLocaleString()} chars left`);
        return pillHtml('run', 'Works');
      case 'no_credit': return pillHtml('warn', 'Used up');
      case 'bad': return pillHtml('lost', "Didn't work");
      case 'offline': return pillHtml('off', 'Checked later');
      case 'checking': return pillHtml('busy', 'Checking', true);
      default: return pillHtml('off', 'Not checked');
    }
  }
  function usedText(k) {
    const used = k.used_by || [];
    const defaultFor = Object.values(S.keys.slots || {}).some(sl => Object.values(sl).some(x => x.key && x.key.id === k.id && !x.assigned));
    if (k.provider === 'elevenlabs' && used.length) return `Voice for ${listText(used)}`;
    if (!used.length) return 'Not used yet';
    return `Used by ${used.join(', ')}${defaultFor ? ' · Default' : ''}`;
  }
  function renderSettings() {
    const s = S.settings;
    const keys = S.keys.keys.map(k => {
      const armed = ui.keyArm === k.id;
      const checking = ui.keyChecking[k.id] || (k.status || {}).state === 'checking';
      const tag = k.groups_only ? ' <span class="tag">Groups only</span>' : (k.voice_only ? ' <span class="tag">Voice only</span>' : '');
      return `<div class="row">
        <span class="prov${k.provider === 'qwen' ? ' mute' : ''}">${esc(PROV[k.provider] || k.provider)}</span>
        <div class="rowmain"><p class="rowtitle">${esc(k.label)} <span class="mono">…${esc(k.tail)}</span>${tag}</p><p class="rowsub" title="${esc((k.status || {}).detail || '')}">${esc(usedText(k))}</p></div>
        ${statusPill(k)}
        <button class="btn btn-ghost btn-sm" type="button" data-act="key-check" data-id="${esc(k.id)}"${checking ? ' disabled' : ''}>${checking ? 'Checking…' : 'Check'}</button>
        ${armed ? `<button class="btn btn-stop btn-sm" type="button" data-act="key-remove" data-id="${esc(k.id)}">Press again</button>`
                : `<button class="btn btn-ghost btn-sm" type="button" data-act="key-remove" data-id="${esc(k.id)}" title="Remove this key">${ic('trash', 18)}Remove</button>`}
      </div>`;
    }).join('');
    const a = ui.addKey;
    const provOpts = [['auto', 'Find it from the key']].concat(['gemini', 'gpt', 'openrouter', 'elevenlabs', 'qwen'].map(p => [p, PROV_LONG[p]]))
      .map(([v, t]) => `<option value="${v}"${a.provider === v ? ' selected' : ''}>${esc(t)}</option>`).join('');
    const pw = (s.passwords || {}).furhat || {};
    const pwPill = pw.works === true ? pillHtml('run', 'Works') : pw.works === false ? pillHtml('lost', "Didn't work") : pillHtml('off', pw.set ? 'Not tried yet' : 'Not set');
    const lw = s.lab_wifi || {};
    const kit = setupItem('naoqi_kit');
    const lite = setupItem('reachy_lite_app');
    const setupRowS = (it, title) => {
      if (!it) return '';
      const st = { ok: pillHtml('run', 'Ready'), missing: pillHtml('off', 'Not set up'), failed: pillHtml('lost', 'Needs a fix'),
        downloading: pillHtml('busy', 'Downloading', true), unpacking: pillHtml('busy', 'Unpacking', true), verifying: pillHtml('busy', 'Checking', true) }[it.state] || '';
      const actBtn = it.state === 'ok'
        ? `<button class="btn btn-ghost btn-sm" type="button" data-act="setup-act" data-id="${it.id}" data-action="check">Check</button>`
        : `<button class="btn btn-quiet btn-sm" type="button" data-act="setup" data-id="${it.id}">${it.state === 'missing' ? 'Set up' : 'Open'}</button>`;
      return `<div class="row"><div class="rowmain"><p class="rowtitle">${esc(title)}</p>${it.state === 'ok' && it.id === 'naoqi_kit' ? '<p class="rowsub">2.8.7.4</p>' : (it.state !== 'missing' && it.detail && it.state !== 'ok' ? `<p class="rowsub">${esc(it.detail)}</p>` : '')}</div>${st}${actBtn}</div>`;
    };
    const res = ui.resources;
    const inUse = res ? ((res.resources || []).map(h => `${holdLabel(h.resource)}: ${h.owner}`).concat((res.ports && Object.entries(res.ports).map(([p, o]) => `Port ${p}: ${typeof o === 'string' ? o : (o && o.owner) || ''}`)) || [])) : null;
    const up = S.app.update || {};
    const doc = ui.doctor;
    const html = `
      <h1 class="h1">Settings</h1>
      <section class="sec" aria-labelledby="set-k">
        <div class="sechd"><h2 id="set-k" class="h2" style="flex:1 1 auto">Keys</h2><span class="muted small">On this laptop only. Pick one per robot on its card.</span></div>
        <div class="panel">
          ${keys || '<div class="row"><p class="rowsub" style="margin:0">No keys yet. Robots can\'t talk until one is added.</p></div>'}
          <div class="row form">
            <div class="field" style="flex:0 0 184px"><label for="ak-prov">Service</label><select id="ak-prov" data-fid="ak-prov" class="select" data-bind="addkey" data-field="provider">${provOpts}</select></div>
            <div class="field" style="flex:0 0 170px"><label for="ak-label">Name</label><input id="ak-label" data-fid="ak-label" class="input" type="text" placeholder="Lab Gemini 2" data-bind="addkey" data-field="label" value="${esc(a.label)}"></div>
            <div class="field" style="flex:1 1 200px"><label for="ak-key">Key</label><input id="ak-key" data-fid="ak-key" class="input" type="password" autocomplete="off" spellcheck="false" placeholder="Paste the key" data-bind="addkey" data-field="key" value="${esc(a.key)}"></div>
            <button class="btn btn-primary" type="button" style="min-height:40px" data-act="key-add"${a.busy || !a.key.trim() ? ' disabled' : ''}>${a.busy ? '<span class="spin" aria-hidden="true"></span>Checking…' : ic('plus', 18) + 'Add'}</button>
          </div>
          ${a.result ? `<div class="row" style="flex-direction:column;align-items:stretch">${resultHtml(a.result)}</div>` : ''}
        </div>
      </section>

      <section class="sec" aria-labelledby="set-r">
        <h2 id="set-r" class="h2">Robots</h2>
        <div class="panel">
          <div class="row"><div class="rowmain"><p class="rowtitle" id="auto2-l">Auto-connect</p><p class="rowsub">Connect each robot when it shows up</p></div><button class="switch${s.auto_connect ? ' on' : ''}" type="button" role="switch" aria-checked="${!!s.auto_connect}" aria-labelledby="auto2-l" data-act="auto"><span></span></button></div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Furhat password</p><p class="rowsub">For Furhat Studio. Used at the next Connect.</p></div>${pwPill}<button class="btn btn-ghost btn-sm" type="button" data-act="pw-edit">${ui.pwEdit ? 'Cancel' : 'Change'}</button>
            ${ui.pwEdit ? `<div class="inlineform"><div class="field" style="flex:1 1 220px"><label for="pw-in">New password</label><input id="pw-in" data-fid="pw-in" class="input" type="password" autocomplete="off" data-bind="pw" value="${esc(ui.pw)}"></div><button class="btn btn-dark" style="min-height:40px" type="button" data-act="pw-save"${ui.pwBusy ? ' disabled' : ''}>Save</button></div>` : ''}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Lab WiFi</p><p class="rowsub">${esc(lw.name || 'Not set')}${lw.name ? (lw.open ? ', open' : ', with a password') : ''}</p></div><button class="btn btn-ghost btn-sm" type="button" data-act="lab-edit">${ui.labEdit ? 'Cancel' : 'Change'}</button><button class="btn btn-ghost btn-sm" type="button" data-act="net-open">Network help</button>
            ${ui.labEdit ? `<div class="inlineform"><div class="field" style="flex:1 1 220px"><label for="lab-in">WiFi name</label><input id="lab-in" data-fid="lab-in" class="input" type="text" maxlength="32" data-bind="lab" data-field="name" value="${esc((ui.lab || {}).name || '')}"></div><label class="check" style="align-self:center"><input type="checkbox" data-bind="lab" data-field="open"${(ui.lab || {}).open ? ' checked' : ''}>Open, no password</label><button class="btn btn-dark" style="min-height:40px" type="button" data-act="lab-save">Save</button></div>` : ''}</div>
        </div>
      </section>

      <section class="sec" aria-labelledby="set-x">
        <h2 id="set-x" class="h2">Extra robot software</h2>
        <div class="panel">${setupRowS(kit, 'Pepper and NAO kit')}${setupRowS(lite, 'Reachy Mini app (USB Reachy)')}</div>
      </section>

      <section class="sec" aria-labelledby="set-c">
        <h2 id="set-c" class="h2">Conversations</h2>
        <div class="panel">
          <div class="row"><div class="rowmain"><p class="rowtitle" id="tr-l">Save transcripts</p><p class="rowsub">On this laptop only${s.save_transcripts ? '. Saving now.' : ''}</p></div><button class="switch${s.save_transcripts ? ' on' : ''}" type="button" role="switch" aria-checked="${!!s.save_transcripts}" aria-labelledby="tr-l" data-act="transcripts"><span></span></button><button class="btn btn-ghost btn-sm" type="button" data-act="transcripts-open">Open folder</button></div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Demo on a phone hotspot</p></div><a class="btn btn-ghost btn-sm" href="#hotspot">Plan</a></div>
        </div>
      </section>

      <section class="sec" aria-labelledby="set-s">
        <div class="sechd"><h2 id="set-s" class="h2" style="flex:1 1 auto">Lab staff tools</h2><button class="switch${s.staff_tools ? ' on' : ''}" type="button" role="switch" aria-checked="${!!s.staff_tools}" aria-label="Show lab staff tools" data-act="staff"><span></span></button></div>
        ${s.staff_tools ? `<div class="panel">
          <div class="row"><div class="rowmain"><p class="rowtitle">Robot files</p><p class="rowsub">Shared with the lab on GitHub</p></div><a class="btn btn-quiet btn-sm" href="#files">Open</a></div>
          <div class="row"><div class="rowmain"><p class="rowtitle">New Reachy</p><p class="rowsub">First WiFi, name, robot software</p></div><button class="btn btn-quiet btn-sm" type="button" data-act="bringup">Bring up</button>
            ${ui.bringup ? `<p class="note" style="width:100%">${ic('info', 18)}<span>On a lab laptop with the repo: run <code>tools\\reachy_bringup.py</code>, or <code>/reachy-set-up</code> in Claude Code. A button for it here comes later.</span></p>` : ''}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Add WiFi</p><p class="rowsub">In each robot's details</p></div>${pillHtml('run', 'Shown')}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">NAO app</p><p class="rowsub">Start button on the NAO card</p></div>${pillHtml('run', 'Shown')}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Check this laptop</p><p class="rowsub">Python, kit, ports, firewall</p></div><button class="btn btn-quiet btn-sm" type="button" data-act="doctor"${ui.doctorBusy ? ' disabled' : ''}>${ui.doctorBusy ? '<span class="spin" aria-hidden="true"></span>Running' : 'Run'}</button>
            ${doc ? `<ul class="doctor">${doc.map(c => `<li><span class="${c.ok ? 'ok' : 'bad'}">${ic(c.ok ? 'check' : 'alert', 16)}</span><span><b>${esc(c.name)}</b> <span class="muted">${esc(c.detail || '')}</span>${!c.ok && c.remedy ? `<br><span>${esc(c.remedy)}</span>` : ''}</span></li>`).join('')}</ul>` : ''}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">In use</p><p class="rowsub">${inUse === null ? 'Checking…' : (inUse.length ? esc(inUse.join(' · ')) : 'Nothing on this laptop is held by a robot.')}</p></div><button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="resources" aria-label="Check again">${ic('refresh', 16)}</button></div>
        </div>` : ''}
      </section>

      <section class="sec" aria-labelledby="set-a">
        <h2 id="set-a" class="h2">About</h2>
        <div class="panel">
          <div class="row"><div class="rowmain"><p class="rowtitle">LabaLab Robot Hub ${esc(S.app.version || '')}</p><p class="rowsub">${up.available ? `New version ${esc(up.latest || '')} is out` : 'Up to date'}</p></div>
            ${up.available ? `<button class="btn btn-primary btn-sm" type="button" data-act="update">Update</button>` : `<button class="btn btn-ghost btn-sm" type="button" data-act="update-check">Check for updates</button>`}</div>
          <div class="row"><div class="rowmain"><p class="rowtitle">Quit Robot Hub</p><p class="rowsub">Stops all robots</p></div><button class="btn btn-ghost btn-sm btn-danger-text" type="button" data-act="quit">Quit</button></div>
        </div>
      </section>`;
    put($('#settings-main'), html);
  }
  function holdLabel(res) {
    const [kind, value] = String(res || '').split(/:(.*)/);
    if (kind === 'audio_in') return value ? `Microphone (${value})` : 'Microphone';
    if (kind === 'audio_out') return value ? `Speaker (${value})` : 'Speaker';
    if (kind === 'port') return `Port ${value}`;
    return value || kind;
  }

  /* ------------------------------------------------------------ files view (lab staff) */
  async function loadFiles() {
    const f = ui.files;
    f.loading = true;
    render();
    const r = await api('GET', '/api/files');
    f.loading = false;
    if (r.ok && Array.isArray(r.files)) {
      f.list = r; f.error = '';
      if (!f.robot) {
        const saved = localGet('hub.filesRobot');
        f.robot = saved && r.robots.some(x => x.id === saved) ? saved : (r.robots[0] || {}).id;
      }
    } else f.error = r.error || 'GitHub didn\'t answer.';
    render();
  }
  function renderFiles() {
    const f = ui.files;
    const L = f.list;
    if (!L && !f.loading && !f.error) { loadFiles(); }
    const robots = L ? L.robots : [];
    const sel = robots.map(r => {
      const n = L.files.filter(x => x.robot === r.id).length;
      return `<option value="${esc(r.id)}"${f.robot === r.id ? ' selected' : ''}>${esc(r.label)} (${n})</option>`;
    }).join('');
    const label = (robots.find(r => r.id === f.robot) || {}).label || f.robot || '';
    let rows = '';
    if (f.error) rows = `<div class="row">${noteHtml('err', 'alert', `Couldn't load the files: ${esc(f.error)}`, btn('Reload', 'dark', 'files-reload', null, { cls: 'btn-xs' })).replace('class="note', 'style="width:100%" class="note')}</div>`;
    else if (!L) rows = '<div class="row" style="justify-content:center;padding:24px 16px"><span class="muted"><span class="spin" aria-hidden="true"></span> Loading…</span></div>';
    else {
      const files = L.files.filter(x => x.robot === f.robot);
      rows = files.length ? files.map(file => fileRow(file)).join('')
        : `<div class="row" style="justify-content:center;padding:24px 16px"><span class="muted">No files for ${esc(label)} yet. Upload the first one.</span></div>`;
    }
    const up = f.upload;
    const html = `
      <div class="pagehead"><h1 class="h1">Robot files</h1><span class="tag tag-dark">Lab staff</span></div>
      <p class="muted" style="margin:-12px 0 0">Shared with the lab on GitHub${L ? ` (${esc(L.repo)})` : ''}. Keys are taken out before upload.</p>
      <div style="display:flex;gap:8px;align-items:center">
        <select class="select" style="width:260px" aria-label="Robot" data-act="files-robot" data-fid="files-robot"${L ? '' : ' disabled'}>${sel}</select>
        <button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="files-reload" aria-label="Reload the list">${ic('refresh', 18, f.loading ? 'spinning' : '')}</button>
      </div>
      <div class="panel">${rows}</div>
      <section class="sec">
        <h2 class="h2">Upload</h2>
        <div class="panel"><div class="row" style="align-items:center">
          <span class="drop">${ic('upload', 18)}<span class="fname">${up ? esc(up.name) : 'No file chosen'}</span>${up ? `<span class="muted small">${sizeText(up.size)}</span>` : ''}<span class="spacer"></span><label class="btn btn-ghost btn-sm" for="file-in">Choose</label><input id="file-in" type="file" class="sr" data-act="file-pick"></span>
          <button class="btn btn-primary" type="button" data-act="file-upload"${!up || f.busy || !L ? ' disabled' : ''}>${ic('upload', 18)}Upload</button>
        </div></div>
        ${f.note ? (f.note.kind === 'busy' ? `<p class="note"><span class="spin" aria-hidden="true"></span><span>${esc(f.note.text)}</span></p>` : `<p class="note ${f.note.kind}">${ic(f.note.kind === 'ok' ? 'check' : 'alert', 18)}<span>${esc(f.note.text)}</span></p>`) : ''}
      </section>`;
    put($('#files-main'), html);
  }
  function fileRow(file) {
    const f = ui.files;
    const when = file.updated ? new Date(file.updated).toLocaleDateString([], { day: 'numeric', month: 'short' }) : '';
    const needs = file.needs || [];
    const meta = [sizeText(file.size), file.uploader && `by ${file.uploader}`, when, needs.length ? `needs a ${needs.map(p => PROV[p] || p).join(' / ')} key` : ''].filter(Boolean).join(' · ');
    let keySel = '';
    if (needs.length) {
      const ks = S.keys.keys.filter(k => needs.includes(k.provider));
      const pick = f.keyPick[file.id] !== undefined ? f.keyPick[file.id] : (ks[0] ? ks[0].id : '');
      keySel = `<select class="select sm" aria-label="Key to put into ${esc(file.name)}" data-act="file-key" data-id="${esc(file.id)}" data-fid="fk-${esc(file.id)}">${ks.map(k => `<option value="${esc(k.id)}"${pick === k.id ? ' selected' : ''}>With ${esc(k.label)} · …${esc(k.tail)}</option>`).join('')}<option value=""${pick === '' ? ' selected' : ''}>Without a key</option></select>`;
    }
    const dl = f.dl[file.id];
    const dlBtn = dl
      ? `<button class="btn btn-quiet dl" type="button" disabled style="background:linear-gradient(90deg,#FDD9A0 ${dl.pct || 0}%,#F4F1EC ${dl.pct || 0}%)" aria-label="Downloading">${esc(dl.text)}</button>`
      : `<button class="btn btn-quiet dl" type="button" data-act="file-dl" data-id="${esc(file.id)}">${ic('download', 18)}Download</button>`;
    const armed = f.arm === file.id;
    const bin = armed ? `<button class="btn btn-stop btn-sm" type="button" data-act="file-del" data-id="${esc(file.id)}">Press again</button>`
      : `<button class="btn btn-ghost btn-sm btn-icon" type="button" data-act="file-del" data-id="${esc(file.id)}" aria-label="Delete for everyone" title="Delete from the lab library">${ic('trash', 18)}</button>`;
    return `<div class="row"><span class="ftile">${ic('file', 18)}</span><div class="rowmain"><p class="rowtitle">${esc(file.name)}</p><p class="rowsub">${esc(meta)}</p></div>${keySel}${dlBtn}${bin}</div>`;
  }
  async function downloadFile(id) {
    const f = ui.files;
    const file = (f.list.files || []).find(x => String(x.id) === String(id));
    if (!file) return;
    const needs = file.needs || [];
    const ks = S.keys.keys.filter(k => needs.includes(k.provider));
    const keyId = needs.length ? (f.keyPick[id] !== undefined ? f.keyPick[id] : (ks[0] ? ks[0].id : '')) : '';
    f.dl[id] = { text: keyId ? 'Adding key…' : 'Getting it…', pct: 0 };
    render();
    try {
      if (DEMO) { await DEMO.wait(800); toast(`Downloaded ${file.name}.`); return; }
      const res = await fetch(`/api/files/${id}/download` + (keyId ? `?key_id=${encodeURIComponent(keyId)}` : ''));
      if (!res.ok) { const b = await res.json().catch(() => ({})); toast(b.error || `Download failed (${res.status}).`, 'err'); return; }
      const total = Number(res.headers.get('Content-Length')) || file.size;
      const reader = res.body.getReader();
      const parts = [];
      let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value);
        got += value.length;
        const pct = total ? Math.min(99, Math.round(100 * got / total)) : 0;
        f.dl[id] = { text: total ? `${pct}%` : sizeText(got), pct };
        render();
      }
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob(parts));
      link.download = file.name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      toast(keyId ? `${file.name} has your key in it. Keep that copy to yourself.` : `Downloaded ${file.name}.`);
    } catch (err) {
      toast(`Download failed: ${err}`, 'err');
    } finally {
      delete f.dl[id];
      render();
    }
  }
  async function uploadFile() {
    const f = ui.files;
    const up = f.upload;
    if (!up || f.busy || !f.robot) return;
    const target = `${f.robot}/${up.name}`;
    const replace = f.replaceArm === target;
    f.replaceArm = '';
    f.busy = true;
    const started = Date.now();
    const tick = () => { f.note = { kind: 'busy', text: `Checking it for keys, then sending it to GitHub… ${Math.round((Date.now() - started) / 1000)} s` }; render(); };
    tick();
    const timer = setInterval(tick, 1000);
    let body;
    try {
      if (DEMO) body = await DEMO.api('POST', '/api/files', { name: up.name });
      else {
        const res = await fetch(`/api/files?robot=${encodeURIComponent(f.robot)}&name=${encodeURIComponent(up.name)}&replace=${replace}`,
          { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: up.file });
        body = await res.json().catch(() => ({ ok: false, error: `Upload failed (${res.status}).` }));
      }
    } catch (err) { body = { ok: false, error: `Upload failed: ${err}` }; }
    clearInterval(timer);
    f.busy = false;
    if (body.ok) {
      const removed = (body.removed || []).length;
      f.note = { kind: 'ok', text: `${up.name} is shared${removed ? '. Its key was taken out first.' : '.'}` };
      f.upload = null;
      const input = $('#file-in'); if (input) input.value = '';
      loadFiles();
    } else if (body.exists) {
      f.replaceArm = target;
      f.note = { kind: 'warn', text: `${up.name} is already shared. Press Upload again to replace it for everyone.` };
    } else {
      f.note = { kind: 'err', text: sentence(body.error || 'Upload failed.') };
    }
    render();
  }

  /* ------------------------------------------------------------ hotspot planner */
  function renderHotspot() {
    const h = ui.hotspot;
    const robots = sortRobots(realRobots().filter(r => r.type_id !== 'reachy_lite'));
    if (!h.picked) h.picked = robots.filter(r => PRESENT.includes(r.state)).map(r => r.key);
    const picked = robots.filter(r => h.picked.includes(r.key));
    const limit = (S.network.hotspot || {}).limit || 5;
    const labels = ['Laptop'];
    picked.forEach(r => { labels.push(r.name); if (r.type_id === 'pepper') labels.push(`${r.name} tablet`); });
    const used = labels.length;
    const n = Math.max(limit, used);
    const slots = [];
    for (let i = 0; i < n; i++) slots.push(`<div class="slot ${i === 0 ? 'lap' : (i >= limit ? 'over' : (labels[i] ? 'used' : ''))}">${esc(labels[i] || 'Free')}</div>`);
    const over = used - limit;
    const chk = (id, html) => `<li><label><input type="checkbox" data-act="hs-check" data-id="${id}"${h.checks[id] ? ' checked' : ''}><span>${html}</span></label></li>`;
    const hs = S.network.hotspot || {};
    put($('#hotspot-chip'), S.network.kind === 'hotspot' ? `<span class="chip">${ic('phone', 16)}Phone hotspot ${hs.devices}/${hs.limit}</span>` : `<span class="chip">${ic('phone', 16)}Phone hotspot ${used}/${limit}</span>`);
    put($('#hotspot-main'), `
      <div><h1 class="h1x">Demo on a phone hotspot</h1><p class="muted" style="margin:6px 0 0">A phone hotspot takes ${limit} devices. This laptop is one.</p></div>
      <section aria-labelledby="hs-bring">
        <h2 id="hs-bring" class="label">Bringing</h2>
        <div class="picks">${robots.length ? robots.map(r => {
          const on = h.picked.includes(r.key);
          return `<button class="pick${on ? ' on' : ''}" type="button" aria-pressed="${on}" data-act="hs-pick" data-key="${esc(r.key)}"><img src="${typeImg(r.type_id)}" alt="">${esc(r.name)}${r.type_id === 'pepper' ? '<small>2 spots</small>' : ''}</button>`;
        }).join('') : '<span class="muted small">No robots known yet. Robots show up here once the hub has seen them.</span>'}</div>
      </section>
      <section aria-labelledby="hs-spots">
        <div style="display:flex;align-items:baseline;gap:8px"><h2 id="hs-spots" class="label" style="margin:0">Spots</h2><span class="spacer"></span><span class="hcount">${used} of ${limit}</span></div>
        <div class="slots" style="margin-top:10px">${slots.join('')}</div>
      </section>
      ${over > 0 ? `<div class="res bad" role="alert">${ic('alert', 18)}<span><b>${over} too many.</b> Leave a robot, or bring a second phone.</span></div>`
                 : `<div class="res ok" role="status">${ic('check', 18)}<span>Fits.</span></div>`}
      <section aria-labelledby="hs-before">
        <h2 id="hs-before" class="label">Before you go</h2>
        <ul class="list">
          ${chk('max', 'Hotspot: <b>Maximize Compatibility</b> on')}
          ${chk('knows', 'Every robot knows this hotspot (set up in the lab)')}
          ${chk('tablet', "Pepper's tablet knows it too")}
          ${chk('furhat', 'Hotspot on <b>before</b> Furhat starts')}
          ${chk('charger', 'Phone on a charger')}
        </ul>
      </section>`);
  }

  /* ------------------------------------------------------------ actions */
  function openWaitingTab(name) {
    if (DEMO) return null;
    const tab = window.open('about:blank', '_blank');
    if (!tab) return null;
    try {
      tab.opener = null;
      const doc = tab.document;
      doc.title = `Starting ${name}…`;
      doc.body.style.cssText = 'font: 16px Inter, "Segoe UI", sans-serif; color: #6B635A; background: #FAF8F5; padding: 40px;';
      doc.body.textContent = `Starting ${name}… This window opens its system as soon as it is ready.`;
    } catch (err) { /* cosmetic */ }
    return tab;
  }
  function openSystem(url, tab) {
    if (tab && !tab.closed) { tab.location.href = url; return; }
    if (DEMO) return;
    const w = window.open(url, '_blank');
    if (w) w.opener = null;
    else toast('Launched. Windows blocked the new window: press Open on the card.', 'info');
  }
  function reachyUrl(route, key) {
    return '/reachy.html#' + route + (key ? '/' + String(key).replace(/[#%\s]/g, c => encodeURIComponent(c)) : '');
  }
  function openReachy(route, key) {
    if (DEMO) { toast(`Opens ${reachyUrl(route, key)}`, 'info'); return; }
    const w = window.open(reachyUrl(route, key), REACHY_WINDOW);
    if (!w) toast('The browser blocked the new window. Allow pop-ups for the hub.', 'err');
  }

  async function robotPost(key, action) {
    const res = await api('POST', `/api/robots/${encodeURIComponent(key)}/${action}`);
    return res;
  }
  async function doLaunch(key, override) {
    const r = S.robots.get(key);
    if (!r) return;
    const tab = isReachy(r) ? null : openWaitingTab(r.name);
    ui.pending[key] = Date.now();
    delete ui.conflicts[key];
    render();
    const res = await robotPost(key, override ? 'override' : 'launch');
    delete ui.pending[key];
    if (res.url && !isReachy(r)) openSystem(res.url, tab);
    else if (tab) tab.close();
    if (res.conflict) ui.conflicts[key] = res.error;
    else if (res.code === 'IN_USE') toast(res.error, 'info');
    else if (!res.ok && res.error && res.code !== 'CONNECT_FIRST') toast(sentence(res.error), 'err');
    else if (!res.ok && res.code === 'CONNECT_FIRST') toast(`Connect ${r.name} first.`, 'info');
    render();
  }
  async function doConnect(key) {
    const res = await robotPost(key, 'connect');
    if (!res.ok && res.error && res.code !== 'CONNECT_FAILED') toast(sentence(res.error), 'err');
  }
  async function doDisconnect(key) {
    delete ui.conflicts[key];
    delete ui.armed[key];
    delete ui.postureErr[key];
    const res = await robotPost(key, 'disconnect');
    if (!res.ok && res.error) toast(sentence(res.error), 'err');
    else if (res.warning) toast(sentence('Disconnected. ' + res.warning), 'info');
  }
  async function doPosture(key, name) {
    const r = S.robots.get(key);
    if (!r) return;
    if (name === 'stand' && !ui.armed[key]) {
      ui.armed[key] = setTimeout(() => { delete ui.armed[key]; render(); }, 5000);
      delete ui.postureErr[key];
      render();
      return;
    }
    if (name === 'stand') { clearTimeout(ui.armed[key]); delete ui.armed[key]; }
    delete ui.postureErr[key];
    render();
    const res = await api('POST', `/api/robots/${encodeURIComponent(key)}/posture`, { name });
    if (!res.ok) {
      let msg = res.error || `The hub answered ${res.status}.`;
      if (res.status === 404 || res.status === 405) msg = 'Restart the hub to use the posture buttons.';
      if (res.code === 'HUB_DOWN') msg = 'Request failed: the hub did not answer.';
      // The hub keeps a refusal on the card too; this covers a refusal it
      // did not store (busy, launching, not connected) and a failed request.
      ui.postureErr[key] = msg;
      setTimeout(() => { if (ui.postureErr[key] === msg) { delete ui.postureErr[key]; render(); } }, 10000);
      toast(sentence(msg), 'err');
    }
    render();
  }
  async function pickKey(robotKey, slot, keyId) {
    const r = S.robots.get(robotKey);
    const res = await api('PUT', `/api/robots/${encodeURIComponent(robotKey)}/key`, { key_id: keyId || null, slot });
    if (res.ok) {
      if (res.keys) S.keys = Object.assign({ slots: {} }, strip(res));
      if (r && r.state === 'RUNNING') ui.changedRunning[robotKey] = true;
      const k = keyById(keyId);
      const name = r ? r.name : robotKey;
      toast(slot === 'voice' ? `${name} will use ${k ? k.label : 'the default voice key'} for its voice` : `${name} will speak through ${k ? k.label : 'the default key'}`);
    } else toast(sentence(res.error || "Couldn't change the key."), 'err');
    render();
  }

  async function joinWifi(key) {
    const r = S.robots.get(key);
    const f = ui.wifi[key] || {};
    const ssid = (f.ssid || '').trim();
    if (!ssid) { ui.wifiNote[key] = { kind: 'warn', icon: 'alert', text: 'Type the hotspot name.' }; render(); return; }
    if (!f.open && (f.pw || '').length < 8) { ui.wifiNote[key] = { kind: 'warn', icon: 'alert', text: 'A WiFi password has at least 8 characters.' }; render(); return; }
    ui.wifiBusy[key] = true;
    delete ui.wifiNote[key];
    render();
    const res = await api('POST', `/api/robots/${encodeURIComponent(key)}/wifi`,
      { ssid, password: f.open ? '' : f.pw, open: !!f.open, save_only: !!f.save });
    delete ui.wifiBusy[key];
    if (res.ok) {
      const msg = res.message || `${r ? r.name : 'The robot'} joined "${ssid}".`;
      const kept = /cannot see it|stays on|already on|as the lab WiFi|fallback/i.test(msg);
      ui.wifiNote[key] = { kind: /cannot see it/i.test(msg) ? 'warn' : 'ok', text: wifiText(msg) };
      if (!kept && !f.save) ui.moved[key] = ssid;
      f.pw = '';
      f.save = false;
      toast(wifiText(msg));
      fetchKnown(key);
    } else {
      ui.wifiNote[key] = { kind: 'err', text: res.code === 'HUB_DOWN' ? "Couldn't ask the hub. Is Robot Hub running?" : wifiText(res.error || `Failed (${res.status}).`) };
    }
    render();
  }
  function wifiText(t) {
    t = String(t || '').replace(/[“”]/g, '"');
    t = t.replace(/ -- it is back on/, '. It is back on').replace(/ -- /g, '. ').replace(/; its password/, '. Its password')
      .replace(/Connect this laptop to "([^"]+)" to see it again\./, 'Move this laptop there too.');
    t = t.replace(/^"(.+?)" is set up as an open WiFi: leave the password empty/, '"$1" is an open WiFi: leave the password empty');
    t = t.replace(/^that is the robot's own setup network/, "That is the robot's own setup network");
    return sentence(t);
  }
  async function fetchKnown(key) {
    ui.known[key] = { loading: true };
    render();
    const res = await api('GET', `/api/robots/${encodeURIComponent(key)}/wifi`);
    if (res.ok && res.supported !== false) ui.known[key] = { networks: res.networks || [] };
    else if (res.ok) ui.known[key] = null;
    else ui.known[key] = { error: (res.error || 'no answer').replace(/^Couldn't ask [^:]+: /, '') };
    render();
  }
  async function openDetails(key) {
    ui.sheet = { kind: 'robot', key };
    ui.copied = false;
    render();
    const r = S.robots.get(key);
    const d = await api('GET', `/api/robots/${encodeURIComponent(key)}`);
    if (d.ok && S.robots.get(key)) { d._at = Date.now(); S.robots.get(key)._detail = d; }
    if (r && staff() && d.has_wifi && PRESENT.includes(r.state) && !ui.known[key]) fetchKnown(key);
    render();
  }
  function detailsText(r) {
    const f = r.facts || {};
    return [
      `${r.name} (${TYPE_LABEL[r.type_id] || r.type_id})`,
      `State: ${r.state}${r.detail ? ' - ' + r.detail : ''}`,
      r.address && `Address: ${r.address}`,
      (f.robot_software || r.daemon_version) && `Robot software: ${f.robot_software || r.daemon_version}`,
      (f.mic || r.mic) && `Listens with: ${f.mic || r.mic}`,
      typeof r.battery === 'number' && `Battery: ${r.battery}%${r.charging ? ' (charging)' : ''}`,
      r.system_url && `App: ${r.system_url}`,
      (f.holds || []).length && `Uses: ${f.holds.join(', ')}`,
      r.in_use_by && `In use by: ${r.in_use_by}`,
      r.launch_error && `Last start failed: ${r.launch_error}`,
      r.connect_error && `Last connect failed: ${r.connect_error}`,
      S.app.version && `Robot Hub ${S.app.version}`,
    ].filter(Boolean).join('\n');
  }
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (err) { /* fall back */ }
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.cssText = 'position:fixed;top:0;opacity:0';
    document.body.append(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
    area.remove();
    return ok;
  }

  async function testPopupKey() {
    const p = ui.popup;
    if (!p || !p.key.trim()) return;
    p.phase = 'checking';
    p.result = null;
    render();
    const res = await api('POST', '/api/keys', { key: p.key, provider: p.provider || 'auto' });
    if (res.ok && res.keys) S.keys = Object.assign({ slots: {} }, strip(res));
    p.phase = 'idle';
    p.result = keyResult(res, p.provider);
    if (res.ok) p.key = '';
    render();
  }
  async function addKeyFromSettings() {
    const a = ui.addKey;
    if (!a.key.trim() || a.busy) return;
    a.busy = true; a.result = null; render();
    const res = await api('POST', '/api/keys', { key: a.key, provider: a.provider || 'auto', label: a.label });
    a.busy = false;
    if (res.ok && res.keys) S.keys = Object.assign({ slots: {} }, strip(res));
    a.result = keyResult(res, a.provider);
    if (res.ok) { a.key = ''; a.label = ''; a.provider = 'auto'; toast("Key added. Pick it on a robot's card."); }
    render();
  }
  function closePopup() {
    ui.popup = null;
    ui.popupFocused = false;
    if (ui.firstNetPending) { ui.firstNetPending = false; openNetworkFirst(); }
    render();
  }

  async function setupAct(id, action) {
    const res = await api('POST', `/api/setup/${encodeURIComponent(id)}/${action}`);
    if (res.ok && res.item) onSetup(res.item);
    else if (!res.ok) toast(sentence(res.error || "That didn't work."), 'err');
    render();
  }

  async function saveReport() {
    ui.reportBusy = true; render();
    const res = await api('POST', '/api/log/report');
    ui.reportBusy = false;
    if (res.ok) toast(`Report saved: ${String(res.path || '').split(/[\\/]/).pop()} in ${res.where || 'Downloads'}`);
    else toast(sentence(res.error || "Couldn't save the report."), 'err');
    render();
  }

  async function setSetting(changes) {
    Object.assign(S.settings, changes);
    render();
    const res = await api('PUT', '/api/settings', changes);
    if (res.ok && res.auto_connect !== undefined) { const o = strip(res); delete o.ok; delete o.status; S.settings = Object.assign({}, S.settings, o); }
    else if (!res.ok) toast(sentence(res.error || "Couldn't save that."), 'err');
    render();
  }

  /* ------------------------------------------------------------ input wiring */
  document.addEventListener('click', async e => {
    const el = e.target.closest('[data-act]');
    if (!el || el.disabled) return;
    const act = el.dataset.act;
    const key = el.dataset.key;
    if (el.tagName === 'SELECT' || (el.tagName === 'INPUT' && el.type !== 'checkbox' && el.type !== 'button')) return;
    if (el.tagName === 'A' || act === 'close-sheet') e.preventDefault();
    switch (act) {
      case 'net-open': ui.sheet = { kind: 'network' }; if (ui.view !== 'robots') location.hash = ''; render(); refreshNetwork(); break;
      case 'auto': setSetting({ auto_connect: !S.settings.auto_connect }); break;
      case 'scan': scan(); break;
      case 'logs': toggleLogs(); break;
      case 'settings': location.hash = '#settings'; break;
      case 'update': await startUpdate(); break;
      case 'update-now': ui.autoUpd = null; await startUpdate(); break;
      case 'update-later': try { sessionStorage.setItem('hub.skipUpdate', (ui.autoUpd || {}).version || ''); } catch (err) { /* private window */ } ui.autoUpd = null; render(); break;
      case 'update-check': { const r = await api('GET', '/api/app?refresh=1'); if (r.version !== undefined) S.app = r; toast(r.update && r.update.available ? `New version ${r.update.latest}` : 'Checking for updates. It can take a few seconds.', 'info'); setTimeout(refreshApp, 5000); render(); } break;
      case 'bar-x': ui.barDismissed[el.dataset.id] = true; render(); break;
      case 'wifi-settings': { const r = await api('POST', '/api/network/open_wifi_settings'); if (!r.ok) toast(sentence(r.error || "Couldn't open the WiFi settings."), 'err'); } break;
      case 'add-key': openPopup(); ui.sheet = null; render(); break;
      case 'hotspot': location.hash = '#hotspot'; break;
      case 'seelog': ui.logs = true; ui.logUnseen = false; ui.logFilter = key && S.robots.get(key) ? S.robots.get(key).name : 'all'; ui.logPinned = true; render(); break;
      case 'details': openDetails(key); break;
      case 'connect': doConnect(key); break;
      case 'disconnect': doDisconnect(key); break;
      case 'launch': doLaunch(key, false); break;
      case 'override': doLaunch(key, true); break;
      case 'dismiss': delete ui.conflicts[key]; render(); break;
      case 'open': { const r = S.robots.get(key); if (r && r.system_url) openSystem(r.system_url, null); } break;
      case 'talk': openReachy('talk', key); break;
      case 'woz': openReachy('woz', key); break;
      case 'reachy-talk': openReachy('talk'); break;
      case 'reachy-group': openReachy('group'); break;
      case 'reachy-woz': openReachy('woz'); break;
      case 'posture': doPosture(key, el.dataset.name); break;
      case 'password': location.hash = '#settings'; ui.pwEdit = true; render(); break;
      case 'setup': ui.sheet = { kind: 'setup', id: el.dataset.id }; if (ui.view !== 'robots') location.hash = ''; render(); break;
      case 'setup-act': setupAct(el.dataset.id, el.dataset.action); break;
      case 'close-sheet': ui.sheet = null; render(); break;
      case 'copy-details': { const r = S.robots.get(key); if (r && await copyText(detailsText(r))) { ui.copied = true; render(); setTimeout(() => { ui.copied = false; render(); }, 1500); } else toast("Couldn't copy. Select the text and press Ctrl+C.", 'err'); } break;
      case 'wifi-join': joinWifi(key); break;
      case 'known-refresh': fetchKnown(key); break;
      case 'net-check': refreshNetwork(true); break;
      case 'acc': ui.acc = ui.acc || {}; ui.acc[el.dataset.id] = !(ui.acc[el.dataset.id] !== false); render(); break;
      case 'log-filter': ui.logFilter = el.dataset.f; ui.logPinned = true; render(); break;
      case 'log-copy': {
        const text = S.log.map(x => `${clock(x.ts)}  ${logSource(x)}  ${x.text}`).join('\n');
        if (!text) { toast('Nothing in the log yet.', 'info'); break; }
        if (await copyText(text)) { ui.logCopied = true; render(); setTimeout(() => { ui.logCopied = false; render(); }, 1500); }
        else toast("Couldn't copy. Select the log and press Ctrl+C.", 'err');
      } break;
      case 'log-jump': ui.logPinned = true; render(); break;
      case 'report': saveReport(); break;
      case 'key-test': testPopupKey(); break;
      case 'key-later': sessionSet('hub.keyLater', '1'); closePopup(); toast('Add a key any time in Settings.', 'info'); break;
      case 'key-done': closePopup(); break;
      case 'key-another': ui.popup = { key: '', provider: 'auto', phase: 'idle', result: null }; ui.popupFocused = false; render(); break;
      case 'key-help': if (ui.popup) { ui.popup.help = !ui.popup.help; render(); } break;
      case 'key-prov':
        if (ui.popup) { ui.popup.provider = el.dataset.p; testPopupKey(); }
        else { ui.addKey.provider = el.dataset.p; addKeyFromSettings(); }
        break;
      case 'key-check': ui.keyChecking[el.dataset.id] = true; render(); { const r = await api('POST', `/api/keys/${encodeURIComponent(el.dataset.id)}/check`); delete ui.keyChecking[el.dataset.id]; if (r.ok && r.keys) S.keys = Object.assign({ slots: {} }, strip(r)); else if (!r.ok) toast(sentence(r.error), 'err'); render(); } break;
      case 'key-remove': {
        const id = el.dataset.id;
        if (ui.keyArm !== id) { ui.keyArm = id; render(); setTimeout(() => { if (ui.keyArm === id) { ui.keyArm = null; render(); } }, 4000); break; }
        ui.keyArm = null;
        const r = await api('DELETE', `/api/keys/${encodeURIComponent(id)}`);
        if (r.ok) { if (r.keys) S.keys = Object.assign({ slots: {} }, strip(r)); toast('Key removed.'); } else toast(sentence(r.error), 'err');
        render();
      } break;
      case 'key-add': addKeyFromSettings(); break;
      case 'pw-edit': ui.pwEdit = !ui.pwEdit; ui.pw = ''; render(); if (ui.pwEdit) setTimeout(() => { const i = $('#pw-in'); if (i) i.focus(); }, 30); break;
      case 'pw-save': {
        ui.pwBusy = true; render();
        const r = await api('PUT', '/api/settings/password/furhat', { password: ui.pw });
        ui.pwBusy = false;
        if (r.ok) { const o = strip(r); delete o.ok; delete o.status; S.settings = Object.assign({}, S.settings, o); ui.pwEdit = false; ui.pw = ''; toast('Furhat password saved. Used at the next Connect.'); }
        else toast(sentence(r.error), 'err');
        render();
      } break;
      case 'lab-edit': ui.labEdit = !ui.labEdit; ui.lab = Object.assign({}, S.settings.lab_wifi || {}); render(); break;
      case 'lab-save': await setSetting({ lab_wifi: { name: (ui.lab.name || '').trim(), open: !!ui.lab.open } }); ui.labEdit = false; render(); break;
      case 'transcripts': setSetting({ save_transcripts: !S.settings.save_transcripts }); break;
      case 'transcripts-open': { const r = await api('POST', '/api/transcripts/open'); if (!r.ok) toast(sentence(r.error), 'err'); } break;
      case 'staff': setSetting({ staff_tools: !S.settings.staff_tools }); if (S.settings.staff_tools) loadResources(); break;
      case 'bringup': ui.bringup = !ui.bringup; render(); break;
      case 'doctor': ui.doctorBusy = true; render(); { const r = await api('GET', '/api/doctor'); ui.doctorBusy = false; ui.doctor = r.checks || [{ name: 'Check', ok: false, detail: r.error || 'no answer' }]; render(); } break;
      case 'resources': loadResources(); break;
      case 'quit':
        // One press quits: the hub stops the robots and ends, and the window
        // closes when it is gone.
        ui.quitting = true; ui.stopped = true;
        ui.stopReason = 'You quit it in Settings. Start it again from its desktop icon.';
        render();
        await api('POST', '/api/app/quit');
        break;
      case 'restart':
        ui.quitting = false;
        ui.stopReason = 'Trying to reach it…';
        render();
        backoff = 500;
        if (ws) { try { ws.close(); } catch (err) { /* closed */ } } else connectWs();
        setTimeout(() => { if (ui.stopped) { ui.stopReason = 'Still not running. Start it from the Robot Hub icon on the desktop.'; render(); } }, 3000);
        break;
      case 'files-reload': loadFiles(); break;
      case 'file-dl': downloadFile(el.dataset.id); break;
      case 'file-del': {
        const f = ui.files, id = el.dataset.id;
        if (f.arm !== id) { f.arm = id; render(); setTimeout(() => { if (f.arm === id) { f.arm = null; render(); } }, 4000); break; }
        f.arm = null;
        const file = (f.list.files || []).find(x => String(x.id) === String(id));
        const r = await api('DELETE', `/api/files/${encodeURIComponent(id)}`);
        if (r.ok) toast(`Deleted ${file ? file.name : 'it'}.`); else toast(sentence(r.error), 'err');
        loadFiles();
      } break;
      case 'file-upload': uploadFile(); break;
      case 'hs-pick': { const h = ui.hotspot; const i = h.picked.indexOf(key); if (i >= 0) h.picked.splice(i, 1); else h.picked.push(key); render(); } break;
      case 'hs-check': ui.hotspot.checks[el.dataset.id] = el.checked; break;
      default: break;
    }
  });

  document.addEventListener('change', e => {
    const el = e.target;
    const act = el.dataset.act;
    if (act === 'pick-key') pickKey(el.dataset.key, el.dataset.slot, el.value);
    else if (act === 'files-robot') { ui.files.robot = el.value; ui.files.replaceArm = ''; localSet('hub.filesRobot', el.value); render(); }
    else if (act === 'file-key') { ui.files.keyPick[el.dataset.id] = el.value; }
    else if (act === 'file-pick') {
      const file = el.files && el.files[0];
      ui.files.upload = file ? { name: file.name, size: file.size, file } : null;
      ui.files.replaceArm = '';
      ui.files.note = null;
      render();
    } else if (el.dataset.bind) bind(el);
  });
  document.addEventListener('input', e => { if (e.target.dataset && e.target.dataset.bind) bind(e.target); });
  function bind(el) {
    const v = el.type === 'checkbox' ? el.checked : el.value;
    switch (el.dataset.bind) {
      case 'wifi': {
        const f = ui.wifi[el.dataset.key] || (ui.wifi[el.dataset.key] = { ssid: '', pw: '', open: false, save: false });
        f[el.dataset.field] = v;
        if (el.type === 'checkbox') { if (el.dataset.field === 'open' && v) f.pw = ''; render(); }
        break;
      }
      case 'popup':
        if (ui.popup) {
          ui.popup.key = v; ui.popup.result = null; ui.popup.provider = 'auto';
          renderPopupLight();
        }
        break;
      case 'addkey': ui.addKey[el.dataset.field] = v; if (el.tagName === 'SELECT') render(); else renderAddKeyButton(); break;
      case 'pw': ui.pw = v; break;
      case 'lab': ui.lab = ui.lab || {}; ui.lab[el.dataset.field] = v; break;
      default: break;
    }
  }
  // Typing must not rebuild the field under the caret: only the detected
  // chip, the result and the button follow the text.
  function renderPopupLight() {
    const p = ui.popup;
    const host = $('#popup-layer [data-inner]');
    if (!host) return;
    const d = detectProvider(p.key);
    const label = d === 'unknown' ? 'Unknown key' : (d === 'gpt' ? 'OpenAI' : PROV[d]);
    const row = host.querySelector('.klabel').parentElement;
    const chip = row.querySelector('.detect');
    if (d && !chip) row.insertAdjacentHTML('beforeend', `<span class="detect">${esc(label)}</span>`);
    else if (!d && chip) chip.remove();
    else if (chip) chip.textContent = label;
    host.querySelectorAll('.res, .kchips, :scope > p.title').forEach(n => n.remove());
    const test = host.querySelector('[data-act="key-test"]');
    if (test) test.disabled = !d;
    host.__html = null;
  }
  function renderAddKeyButton() {
    const b = document.querySelector('[data-act="key-add"]');
    if (b && !ui.addKey.busy) b.disabled = !ui.addKey.key.trim();
  }
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (ui.popup) { if (!ui.popup.result || !ui.popup.result.saved) sessionSet('hub.keyLater', '1'); closePopup(); }
      else if (ui.sheet) { ui.sheet = null; render(); }
      else if (ui.logs) { ui.logs = false; render(); }
      else if (ui.view !== 'robots') location.hash = '';
      return;
    }
    if (e.key === 'Enter' && e.target && e.target.dataset) {
      const b = e.target.dataset.bind;
      if (b === 'popup') { e.preventDefault(); testPopupKey(); }
      else if (b === 'addkey' && e.target.tagName === 'INPUT') { e.preventDefault(); addKeyFromSettings(); }
      else if (b === 'wifi' && e.target.type !== 'checkbox') { e.preventDefault(); joinWifi(e.target.dataset.key); }
      else if (b === 'pw') { e.preventDefault(); document.querySelector('[data-act="pw-save"]').click(); }
    }
  });

  function toggleLogs() {
    ui.logs = !ui.logs;
    if (ui.logs) { ui.logUnseen = false; ui.logPinned = true; }
    render();
  }
  async function scan() {
    if (ui.scanBusy) return;
    ui.scanBusy = true; render();
    const r = await api('POST', '/api/rescan');
    if (r.ok === false) toast(`Scan failed: ${r.error || 'no answer'}`, 'err');
    setTimeout(() => { ui.scanBusy = false; render(); }, 1200);
  }
  async function refreshNetwork(button) {
    if (button) { ui.netChecking = true; render(); }
    const r = await api('GET', '/api/network');
    if (r && r.state) { const o = strip(r); delete o.ok; delete o.status; S.network = Object.assign({}, S.network, o); }
    ui.netChecking = false;
    render();
  }
  async function loadResources() {
    const r = await api('GET', '/api/resources');
    ui.resources = r.ok !== false ? r : { resources: [] };
    render();
  }

  /* ------------------------------------------------------------ routing */
  function route() {
    const h = location.hash.replace(/^#/, '');
    const v = ['settings', 'files', 'hotspot'].includes(h) ? h : 'robots';
    if (v === 'files' && !staff() && S.gotSnapshot) { location.hash = '#settings'; return; }
    if (ui.view !== v) {
      ui.view = v;
      if (v !== 'robots') ui.sheet = null;
      if (v === 'settings' && staff()) loadResources();
      if (v === 'hotspot') ui.hotspot.picked = null;
      window.scrollTo(0, 0);
    }
    render();
  }
  window.addEventListener('hashchange', route);

  // Live seconds ("Starting… n s"), "seen n s ago", the searching skeleton.
  setInterval(() => {
    const sh = ui.sheet;
    if (sh && sh.kind === 'robot' && !DEMO) {
      const r = S.robots.get(sh.key);
      if (r && (!r._detail || Date.now() - r._detail._at > 5000) && !r._fetching) {
        r._fetching = true;
        api('GET', `/api/robots/${encodeURIComponent(sh.key)}`).then(d => {
          const now = S.robots.get(sh.key);
          if (now) { now._fetching = false; if (d.ok) { d._at = Date.now(); now._detail = d; } }
        });
      }
    }
    const ticking = [...S.robots.values()].some(r => r.launching_since) || Object.keys(ui.pending).length
      || (ui.sheet && ui.sheet.kind === 'robot') || (S.gotSnapshot && Date.now() - S.snapshotAt < 11000);
    if (ticking) render();
  }, 1000);
  // The update line: GET /api/app also nudges the hub's background check.
  setInterval(() => { if (!DEMO) refreshApp(); }, 10 * 60 * 1000);

  /* ------------------------------------------------------------ demo hooks and start */
  window.Hub = {
    S, ui, handle, render, toast, openDetails, openPopup, keyResult, flags: DEMO_STATE_FLAGS,
    setView(v) { location.hash = v === 'robots' ? '' : '#' + v; route(); },
  };

  function start() {
    route();
    if (DEMO_STATE) {
      const s = document.createElement('script');
      s.src = '/demo-hub.js';
      s.onload = () => { DEMO = window.HubDemo; DEMO.start(DEMO_STATE, window.Hub); };
      document.body.append(s);
      return;
    }
    refreshApp();
    connectWs();
    watchStartupUpdate();
  }
  start();
})();
