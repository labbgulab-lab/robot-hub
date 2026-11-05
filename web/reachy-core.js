/* Reachy app: shared parts (helpers, icons, transport, hub link, router,
 * logs drawer, tooltips, toasts, the robot link used by Talk and Wizard of Oz).
 *
 * Everything goes through RA.api() and RA.socket(), so demo mode
 * (?demo=<state>, web/demo-reachy.js) can answer from fake data instead of
 * the hub. Nothing here may throw on a missing field: a demo may be running.
 */
'use strict';

const RA = window.RA = window.RA || {};

/* ---------------------------------------------------------------- helpers */
RA.arr = (v) => (Array.isArray(v) ? v : []);
RA.obj = (v) => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
RA.str = (v) => (v === null || v === undefined ? '' : String(v));
RA.num = (v, fallback) => {
  const n = Number(v);
  return v !== null && v !== '' && v !== undefined && Number.isFinite(n) ? n : fallback;
};
RA.clock = (seconds) => {
  const s = Math.max(0, Math.floor(RA.num(seconds, 0)));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
RA.el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
};
RA.$ = (id) => document.getElementById(id);
// A name the people chose may be Hebrew inside an English sentence.
RA.bdi = (text) => RA.el('bdi', '', text);
RA.cap = (t) => { const s = RA.str(t); return s ? s[0].toUpperCase() + s.slice(1) : s; };
RA.plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
RA.ago = (at) => {
  const t = RA.num(at, 0);
  if (!t) return '';
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 45) return 'now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
};
RA.setValue = (input, value) => {
  if (!input || document.activeElement === input) return;   // never under the cursor
  const v = RA.str(value);
  if (input.value !== v) input.value = v;
};
// options: [[value, label], ...]. An open list stays as it is.
RA.fillOptions = (select, options, value) => {
  if (!select) return;
  const focused = document.activeElement === select;
  const sig = JSON.stringify(options);
  if (select.dataset.sig !== sig && !focused) {
    select.textContent = '';
    options.forEach(([id, label]) => {
      const o = RA.el('option', '', label);
      o.value = id;
      select.append(o);
    });
    select.dataset.sig = sig;
  }
  if (!focused) select.value = RA.str(value);
};
RA.on = (node, type, fn) => { if (node) node.addEventListener(type, fn); };

/* ------------------------------------------------------------------ icons */
// The design system's line icons (docs/design/builder), drawn inline.
const ICONS = {
  back: '<line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline>',
  logs: '<polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line>',
  check: '<polyline points="20 6 9 17 4 12"></polyline>',
  alert: '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"></rect>',
  play: '<polygon points="6 4 20 12 6 20 6 4"></polygon>',
  mic: '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line>',
  vol: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M15.54 8.46a5 5 0 0 1 0 7.07"></path><path d="M19.07 4.93a10 10 0 0 1 0 14.14"></path>',
  send: '<line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>',
  left: '<polyline points="15 18 9 12 15 6"></polyline>',
  right: '<polyline points="9 18 15 12 9 6"></polyline>',
  users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>',
  edit: '<path d="M12 20h9"></path><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"></path>',
  camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle>',
  clock: '<circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline>',
  down: '<line x1="12" y1="5" x2="12" y2="19"></line><polyline points="19 12 12 19 5 12"></polyline>',
  wifi: '<path d="M5 12.55a11 11 0 0 1 14.08 0"></path><path d="M1.42 9a16 16 0 0 1 21.16 0"></path><path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path><circle cx="12" cy="20" r="1"></circle>',
  refresh: '<polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path>',
  x: '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>',
  chev: '<polyline points="6 9 12 15 18 9"></polyline>',
  unlink: '<path d="M18.84 12.25l1.72-1.71a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M5.17 11.75l-1.71 1.71a5 5 0 0 0 7.07 7.07l1.71-1.71"></path><line x1="8" y1="2" x2="8" y2="5"></line><line x1="2" y1="8" x2="5" y2="8"></line><line x1="16" y1="19" x2="16" y2="22"></line><line x1="19" y1="16" x2="22" y2="16"></line>',
  info: '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"></circle><path d="m21 2-9.6 9.6"></path><path d="m15.5 7.5 3 3L22 7l-3-3"></path>',
  trash: '<polyline points="3 6 5 6 21 6"></polyline><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"></path><path d="M10 11v6M14 11v6"></path><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"></path>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path>',
};
RA.ic = (name, size = 18) => `<svg class="icon" style="width: ${size}px; height: ${size}px;" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ''}</svg>`;
RA.icNode = (name, size) => {
  const t = document.createElement('template');
  t.innerHTML = RA.ic(name, size);
  return t.content.firstChild;
};
RA.hydrateIcons = (root) => {
  root.querySelectorAll('i[data-ic]').forEach(i => {
    i.replaceWith(RA.icNode(i.dataset.ic, Number(i.dataset.s || 18)));
  });
};

/* -------------------------------------------------------------- transport */
// {ok, status, body}. Never throws: a failed request is {ok:false, status:0}.
RA.api = async (method, url, payload) => {
  if (RA.demo) return RA.demo.api(method, url, payload);
  try {
    const res = await fetch(url, {
      method,
      headers: payload === undefined ? {} : { 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const body = await res.json().catch(() => ({}));
    return { ok: res.ok, status: res.status, body: RA.obj(body) };
  } catch (err) {
    return { ok: false, status: 0, body: { error: `the hub did not answer (${err.message || err})` } };
  }
};
RA.get = (url) => RA.api('GET', url);
RA.post = (url, payload) => RA.api('POST', url, payload);
RA.put = (url, payload) => RA.api('PUT', url, payload);
RA.del = (url) => RA.api('DELETE', url);

// The sentence from a failed answer, in the hub's or reachy_chat's shape.
RA.errorText = (r) => {
  const b = RA.obj(r && r.body);
  if (typeof b.detail === 'string' && b.detail) return b.detail;
  if (b.error) return RA.str(b.error);
  if (Array.isArray(b.detail) && b.detail.length) return RA.str(RA.obj(b.detail[0]).msg) || 'invalid settings';
  if (r && (r.status === 404 || r.status === 405)) return 'This Robot Hub is too old for this. Restart Robot Hub.';
  return r && r.status ? `the hub answered ${r.status}` : "the hub didn't answer";
};

// A WebSocket that reconnects by itself (0.5 s, doubling to 10 s).
// handlers: {open, message, close}; returns {close(), send(), live}.
RA.socket = (path, handlers) => {
  if (RA.demo) return RA.demo.socket(path, handlers);
  let ws = null;
  let backoff = 500;
  let stopped = false;
  let timer = 0;
  const link = { live: false, close, send };
  function connect() {
    if (stopped) return;
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}${path}`);
    ws.onopen = () => { backoff = 500; link.live = true; if (handlers.open) handlers.open(); };
    ws.onmessage = (e) => {
      let msg = null;
      try { msg = JSON.parse(e.data); } catch (err) { return; }
      try { handlers.message(msg); } catch (err) { console.error('reachy app:', err); }
    };
    ws.onclose = () => {
      link.live = false;
      if (handlers.close) handlers.close();
      if (stopped) return;
      const again = handlers.retry ? handlers.retry() : true;
      if (again === false) return;
      timer = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 10000);
    };
    ws.onerror = () => { try { ws.close(); } catch (err) { /* closing anyway */ } };
  }
  function close() {
    stopped = true;
    clearTimeout(timer);
    if (ws) try { ws.close(); } catch (err) { /* gone */ }
  }
  function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
  link.reconnect = () => { if (!stopped && (!ws || ws.readyState > 1)) { clearTimeout(timer); backoff = 500; connect(); } };
  connect();
  return link;
};

/* ------------------------------------------------------------------ toast */
let toastTimer = 0;
RA.toast = (message, bad) => {
  const t = RA.$('toast');
  if (!t) return;
  clearTimeout(toastTimer);
  t.textContent = message;
  t.classList.toggle('bad', !!bad);
  t.classList.add('visible');
  toastTimer = setTimeout(() => t.classList.remove('visible'), 4200);
};

/* ------------------------------------------------------------------- copy */
// navigator.clipboard needs a secure origin; the textarea way always works here.
RA.copyText = async (text) => {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) { /* fall through */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.cssText = 'position: fixed; top: -1000px; opacity: 0;';
  document.body.append(ta);
  try { ta.select(); return document.execCommand('copy'); } catch (err) { return false; } finally { ta.remove(); }
};

/* ---------------------------------------------------------------- the hub */
// The main /ws: robots (picker, Talk), settings (quick saves, staff tools,
// transcripts), the log, and the Live dot.
RA.hub = { robots: new Map(), settings: {}, live: false, loaded: false, log: [], listeners: [] };
RA.onHub = (fn) => RA.hub.listeners.push(fn);
function hubChanged(kind) {
  RA.hub.listeners.forEach(fn => { try { fn(kind); } catch (err) { console.error(err); } });
}
RA.isReachy = (r) => RA.str(RA.obj(r).type_id).startsWith('reachy');
RA.reachys = () => Array.from(RA.hub.robots.values()).filter(RA.isReachy);
RA.robot = (key) => RA.hub.robots.get(key) || null;
RA.CONNECTED = ['CONNECTED', 'RUNNING', 'DEGRADED'];

function hubMessage(m) {
  switch (m.type) {
    case 'snapshot':
      RA.hub.robots = new Map(RA.arr(m.robots).map(r => [r.key, r]));
      RA.hub.settings = RA.obj(m.settings);
      RA.hub.loaded = true;
      RA.arr(m.log).forEach(addLog);
      renderLogs();
      hubChanged('all');
      break;
    case 'robot':
      if (m.key) RA.hub.robots.set(m.key, m);
      hubChanged('robot');
      break;
    case 'robot_removed':
      RA.hub.robots.delete(m.key);
      hubChanged('robot');
      break;
    case 'settings':
      RA.hub.settings = { ...RA.hub.settings, ...m };
      hubChanged('settings');
      break;
    case 'log':
      addLog(m);
      renderLogs(true);
      break;
    case 'transcripts':
      RA.transcripts = m;
      renderTranscriptMark();
      break;
    default:
      break;
  }
}

function renderLive() {
  const live = RA.$('ws-state');
  if (!live) return;
  // On the Group tab the group conversation's own link counts too.
  const on = RA.hub.live && (RA.route.tab !== 'group' || RA.hub.groupLive !== false);
  live.classList.toggle('off', !on);
  live.querySelector('.spin').hidden = on;
  RA.$('ws-text').textContent = on ? 'Live' : (RA.hub.everLive ? 'Reconnecting' : 'Connecting');
  live.title = on ? 'Robot Hub is running' : 'Waiting for Robot Hub. The screen may be out of date.';
}

RA.renderLive = renderLive;
RA.startHub = () => {
  RA.socket('/ws', {
    open() { RA.hub.live = true; RA.hub.everLive = true; renderLive(); loadTranscripts(); },
    message: hubMessage,
    close() { RA.hub.live = false; renderLive(); },
  });
  renderLive();
  loadTranscripts();
};

/* ----------------------------------------------------------- transcripts */
// The "Saving transcript" mark: shown while a conversation is being saved;
// nothing at all when Settings > Save transcripts is off.
RA.transcripts = { enabled: false, active: [] };
async function loadTranscripts() {
  const r = await RA.get('/api/transcripts/current');
  if (r.ok) { RA.transcripts = r.body; renderTranscriptMark(); }
}
function renderTranscriptMark() {
  const mark = RA.$('transcript-mark');
  if (!mark) return;
  const t = RA.obj(RA.transcripts);
  const active = RA.arr(t.active);
  mark.hidden = !t.enabled || !active.length;
  mark.title = active.length
    ? `Saving to the transcripts folder: ${active.map(a => a.file).join(', ')}`
    : '';
}
RA.renderTranscriptMark = renderTranscriptMark;

/* ------------------------------------------------------------------- logs */
function addLog(e) {
  RA.hub.log.push(e);
  if (RA.hub.log.length > 600) RA.hub.log.splice(0, RA.hub.log.length - 600);
}
function logTime(ts) {
  const d = ts ? new Date(ts * 1000) : new Date();
  return d.toTimeString().slice(0, 8);
}
function renderLogs(append) {
  const list = RA.$('logs-list');
  if (!list || RA.$('logs-drawer').hidden) return;
  const near = list.scrollHeight - list.scrollTop - list.clientHeight < 40;
  const items = append ? RA.hub.log.slice(-1) : RA.hub.log;
  if (!append) list.textContent = '';
  items.forEach(e => {
    const row = RA.el('div', RA.str(e.level));
    row.append(RA.el('span', 't', `${logTime(e.ts)}  `), document.createTextNode(RA.str(e.text)));
    list.append(row);
  });
  if (!RA.hub.log.length && !append) list.append(RA.el('div', 't', 'Nothing yet.'));
  if (near || !append) list.scrollTop = list.scrollHeight;
}
RA.openLogs = async () => {
  RA.openDrawer('logs-drawer');
  if (!RA.hub.logBackfilled) {
    const r = await RA.get('/api/log?limit=500');
    if (r.ok && RA.arr(r.body.log).length) { RA.hub.log = RA.arr(r.body.log); RA.hub.logBackfilled = true; }
  }
  renderLogs();
};

/* ---------------------------------------------------------- modals/drawers */
let lastFocus = null;
RA.openDrawer = (id) => {
  lastFocus = document.activeElement;
  const d = RA.$(id);
  d.hidden = false;
  const first = d.querySelector('button, input, select, textarea');
  if (first) first.focus();
};
RA.closeDrawer = (id) => {
  const d = RA.$(id);
  if (!d || d.hidden) return;
  d.hidden = true;
  if (lastFocus && lastFocus.focus) lastFocus.focus();
};

/* ---------------------------------------------------------------- tooltips */
// Every control explains itself when the mouse rests on it (300 ms). Titles
// move into data-tip, so the browser's own slow tooltip never shows; titles
// the code sets later are caught the same way.
RA.startTips = () => {
  const tip = RA.el('div', 'tip');
  tip.setAttribute('role', 'tooltip');
  document.body.append(tip);
  let tipFor = null;
  let tipTimer = 0;
  const adopt = (node) => {
    if (node && node.hasAttribute && node.hasAttribute('title')) {
      const t = node.getAttribute('title');
      node.removeAttribute('title');
      if (t) { node.dataset.tip = t; if (!node.getAttribute('aria-label') && !node.textContent.trim()) node.setAttribute('aria-label', t); }
      else delete node.dataset.tip;
    }
  };
  const adoptAll = (root) => root.querySelectorAll('[title]').forEach(adopt);
  adoptAll(document);
  document.querySelectorAll('template').forEach(t => adoptAll(t.content));
  new MutationObserver(records => records.forEach(r => {
    if (r.type === 'attributes') adopt(r.target);
    else r.addedNodes.forEach(n => { if (n.nodeType === 1) { adopt(n); adoptAll(n); } });
  })).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] });
  const hide = () => { clearTimeout(tipTimer); tipFor = null; tip.classList.remove('on'); };
  document.addEventListener('mouseover', (event) => {
    const target = event.target.closest && event.target.closest('[data-tip]');
    if (target === tipFor) return;
    hide();
    if (!target || !target.dataset.tip) return;
    tipFor = target;
    tipTimer = setTimeout(() => {
      if (tipFor !== target || !target.isConnected) return;
      tip.textContent = target.dataset.tip;
      const r = target.getBoundingClientRect();
      const w = tip.offsetWidth;
      const h = tip.offsetHeight;
      const x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
      let y = r.bottom + 8;
      if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
      tip.style.left = `${x}px`;
      tip.style.top = `${y}px`;
      tip.classList.add('on');
    }, 300);
  });
  document.addEventListener('mousedown', hide);
  document.addEventListener('scroll', hide, true);
};

/* -------------------------------------------------------------- the robot */
// One live link to the chosen Reachy's reachy_chat, through the hub
// (/ws/reachy/<key>). Talk and Wizard of Oz share it.
RA.link = null;
RA.Link = class {
  constructor(key) {
    this.key = key;
    this.state = 'connecting';     // connecting | open | down
    this.code = '';
    this.error = '';
    this.snapshot = null;
    this.listeners = [];
    this.sock = RA.socket(`/ws/reachy/${encodeURIComponent(key)}`, {
      message: (m) => this.message(m),
      close: () => {
        if (this.state === 'open') { this.state = 'down'; this.code = 'NOT_RUNNING'; this.emit({ event: 'proxy.closed' }); }
      },
      // Keep trying while the hub says the app runs (or someone else's might).
      retry: () => {
        const r = RA.robot(this.key);
        if (!r) return false;        // the hub's robot events bring it back (below)
        return r.state === 'RUNNING' || !!r.in_use_by || this.state === 'open';
      },
    });
  }
  on(fn) { this.listeners.push(fn); }
  emit(m) { this.listeners.forEach(fn => { try { fn(m); } catch (err) { console.error(err); } }); }
  message(m) {
    m = RA.obj(m);
    if (m.event === 'proxy.open') { this.state = 'open'; this.code = ''; this.error = ''; }
    else if (m.event === 'proxy.error' || m.event === 'proxy.closed') {
      this.state = 'down'; this.code = RA.str(m.code); this.error = RA.str(m.error);
    } else if (m.event === 'state.snapshot') {
      this.snapshot = m;
      this.state = 'open';
    }
    this.emit(m);
  }
  retryNow() {
    if (Date.now() - (this.lastRetry || 0) < 3000) return;
    this.lastRetry = Date.now();
    this.sock.reconnect();
  }
  api(method, path, payload) {
    return RA.api(method, `/api/reachy/${encodeURIComponent(this.key)}/${path}`, payload);
  }
  close() { this.sock.close(); this.listeners = []; }
};
RA.useLink = (key) => {
  if (!key) { if (RA.link) { RA.link.close(); RA.link = null; } return null; }
  if (RA.link && RA.link.key === key) return RA.link;
  if (RA.link) RA.link.close();
  RA.link = new RA.Link(key);
  RA.linkListeners.forEach(fn => RA.link.on(fn));
  return RA.link;
};
RA.linkListeners = [];
// The robot's app came up (ours or another laptop's): connect at once.
RA.onHub(() => {
  const link = RA.link;
  if (!link || link.state === 'open') return;
  const r = RA.robot(link.key);
  if (r && (r.state === 'RUNNING' || r.in_use_by)) link.retryNow();
});
RA.onLink = (fn) => { RA.linkListeners.push(fn); if (RA.link) RA.link.on(fn); };

/* --------------------------------------------------------- shared details */
// The robot's name as people say it, and its card on the hub.
RA.robotName = (key) => {
  const r = RA.robot(key);
  return (r && r.name) || RA.str(key);
};
RA.STATUS_TEXT = {
  ABSENT: 'Absent', DETECTED: 'Available', CONNECTING: 'Connecting', CONNECTED: 'Connected',
  RUNNING: 'Running', DEGRADED: 'Degraded', ERROR: 'Lost', DISABLED: 'Unavailable',
};
RA.STATUS_PILL = {
  ABSENT: 'p-off', DETECTED: 'p-near', CONNECTING: 'p-busy', CONNECTED: 'p-conn',
  RUNNING: 'p-run', DEGRADED: 'p-warn', ERROR: 'p-lost', DISABLED: 'p-off',
};
RA.pill = (cls, text, spin) => {
  const p = RA.el('span', `pill ${cls}`);
  p.append(spin ? RA.el('span', 'spin') : RA.el('span', 'dot'), document.createTextNode(text));
  if (spin) p.firstChild.setAttribute('aria-hidden', 'true');
  return p;
};
RA.note = (kind, icon, text, actions) => {
  const n = RA.el('div', `note ${kind}`);
  n.append(RA.icNode(icon, 18));
  const body = RA.el('div');
  body.append(typeof text === 'string' ? document.createTextNode(text) : text);
  if (actions && actions.length) {
    const a = RA.el('div', 'nacts');
    actions.forEach(x => a.append(x));
    body.append(a);
  }
  n.append(body);
  return n;
};
RA.button = (text, cls, onClick, icon) => {
  const b = RA.el('button', `btn ${cls || 'btn-quiet'}`);
  b.type = 'button';
  if (icon) b.append(RA.icNode(icon, 16));
  b.append(document.createTextNode(text));
  if (onClick) b.addEventListener('click', onClick);
  return b;
};

/* -------------------------------------------------------- the save state */
// The top bar's save state follows the tab: Group autosave, Talk's last
// change, Wizard of Oz's quick saves.
RA.saves = { group: { text: 'Loading', kind: '' }, talk: { text: '', kind: '' }, woz: { text: '', kind: '' } };
RA.setSave = (tab, text, kind) => {
  RA.saves[tab] = { text, kind: kind || '' };
  RA.renderSave();
};
RA.renderSave = () => {
  const node = RA.$('config-badge');
  if (!node) return;
  const picking = RA.route.tab !== 'group' && !RA.route.key;
  const s = picking ? { text: '' } : (RA.saves[RA.route.tab] || { text: '' });
  node.hidden = !s.text;
  node.className = `save${s.kind === 'problem' ? ' warn' : ''}${s.kind === 'busy' ? ' busy-save' : ''}`;
  node.textContent = '';
  if (s.text) {
    node.append(RA.icNode(s.kind === 'problem' ? 'alert' : 'check', 16), document.createTextNode(s.text));
    if (s.kind === 'busy' || s.kind === '') node.firstChild.style.visibility = s.kind === 'busy' ? 'hidden' : '';
  }
};

/* ------------------------------------------------------------------ route */
// #group, #talk/<robotKey>, #woz/<robotKey>; no key = pick a robot.
RA.route = { tab: 'group', key: '' };
RA.parseRoute = () => {
  const h = decodeURIComponent(location.hash.replace(/^#/, ''));
  const [tab, ...rest] = h.split('/');
  const key = rest.join('/');
  if (tab === 'talk' || tab === 'woz') return { tab, key };
  return { tab: 'group', key: '' };
};
RA.go = (tab, key) => {
  const h = key ? `#${tab}/${encodeURIComponent(key)}` : `#${tab}`;
  if (location.hash !== h) location.hash = h;
  else window.dispatchEvent(new HashChangeEvent('hashchange'));
};
