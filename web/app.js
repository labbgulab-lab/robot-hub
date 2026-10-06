/* Robot Hub front end.
 *
 * One WebSocket in, REST out. The page never polls a robot and never waits on
 * one: a button press fires a request and the card updates when the hub says
 * so (PLAN.md 3, 9.2). That is what keeps the page responsive while a robot
 * takes 457 ms -- or thirty seconds -- to answer.
 */

'use strict';

const grid = document.getElementById('robots');
const logEl = document.getElementById('log');
const banner = document.getElementById('network-banner');
const bannerText = document.getElementById('network-text');
const wsState = document.getElementById('ws-state');
const wsText = document.getElementById('ws-text');
const autoConnect = document.getElementById('auto-connect');
const scanButton = document.getElementById('scan');
const updatedEl = document.getElementById('updated');
const rangeText = document.getElementById('range-text');
const toast = document.getElementById('toast');
const template = document.getElementById('card-template');

const ORDER = ['furhat', 'reachy_wireless', 'reachy_lite', 'naoqi'];
const PRESENT = ['DETECTED', 'CONNECTING', 'CONNECTED', 'RUNNING', 'DEGRADED', 'ERROR'];
const CONNECTED = ['CONNECTED', 'RUNNING', 'DEGRADED'];

const STATUS_TEXT = {
  ABSENT: 'Absent',
  DETECTED: 'Available',
  CONNECTING: 'Connecting',
  CONNECTED: 'Connected',
  RUNNING: 'Running',
  DEGRADED: 'Degraded',
  ERROR: 'Lost',
  DISABLED: 'Unavailable',
};

const keyList = document.getElementById('key-list');
const keyForm = document.getElementById('key-form');
const keyProvider = document.getElementById('key-provider');
const keyLabel = document.getElementById('key-label');
const keySecret = document.getElementById('key-secret');
const keysCount = document.getElementById('keys-count');

const logCopy = document.getElementById('log-copy');

const els = new Map();     // key -> card element
const state = new Map();   // key -> last robot event
const pendingLaunch = new Set();   // keys whose Launch request is in flight
// Public view of the speaking keys: labels and last four characters only.
let keys = { keys: [], assign: {}, providers: [], robots: {} };
let ws = null;
let backoff = 500;
let toastTimer = null;

/* ------------------------------------------------------------------ toast */

function announce(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add('visible');
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 4200);
}

/* --------------------------------------------------------------- rendering */

function cardFor(key) {
  let el = els.get(key);
  if (el) return el;
  el = template.content.firstElementChild.cloneNode(true);
  el.dataset.key = key;
  el.addEventListener('click', onCardClick);
  els.set(key, el);
  return el;
}

function reorder() {
  const sorted = [...state.values()].sort(
    (a, b) => ORDER.indexOf(a.type_id) - ORDER.indexOf(b.type_id));
  sorted.forEach(r => grid.appendChild(els.get(r.key)));
}

function renderRobot(r) {
  const fresh = !els.has(r.key);
  const el = cardFor(r.key);
  state.set(r.key, r);

  el.dataset.state = r.state;
  el.dataset.typeId = r.type_id;
  if (r.system_url) el.dataset.systemUrl = r.system_url; else delete el.dataset.systemUrl;

  const name = el.querySelector('.robot-name');
  name.textContent = r.name;
  // "Connected, but could not speak" is a real outcome and diagnostic in
  // itself -- on Furhat it usually means the speech engine is misconfigured.
  if (CONNECTED.includes(r.state) && r.can_speak === false) {
    name.insertAdjacentHTML('beforeend',
      ' <span class="silent" title="connected, but could not speak">' +
      '<svg aria-hidden="true"><use href="#mute"/></svg></span>');
  }

  el.querySelector('.robot-detail').textContent =
    r.disabled_reason || r.detail || (r.state === 'ABSENT' ? 'not on the network' : '');
  el.querySelector('.status-text').textContent = STATUS_TEXT[r.state] || r.state;

  renderRightMetric(el, r);

  const photo = el.querySelector('.robot-avatar');
  showPhoto(photo, r.type_id);

  const present = PRESENT.includes(r.state);
  const connected = CONNECTED.includes(r.state);
  const connect = el.querySelector('[data-action="connect"]');
  const disconnect = el.querySelector('[data-action="disconnect"]');

  connect.disabled = !present || connected || r.state === 'CONNECTING';
  disconnect.disabled = !connected && r.state !== 'ERROR';
  connect.querySelector('svg').classList.toggle('spinning', r.state === 'CONNECTING');

  renderLaunch(el, r);
  renderPosture(el, r);
  renderCardKey(el, r.key);
  if (fresh) reorder();
  updateSummary();
}

// The robot's logo replaces the glyph only once it has actually loaded, so
// a missing web/photos/<type_id>.png still leaves the glyph, never a blank.
const photoOk = new Map();
function showPhoto(slot, typeId) {
  const url = `/photos/${typeId}.png`;
  const apply = ok => {
    slot.classList.toggle('has-photo', ok);
    slot.style.backgroundImage = ok ? `url("${url}")` : '';
  };
  if (photoOk.has(typeId)) { apply(photoOk.get(typeId)); return; }
  const img = new Image();
  img.onload = () => { photoOk.set(typeId, true); apply(true); };
  img.onerror = () => { photoOk.set(typeId, false); apply(false); };
  img.src = url;
}

// A launch runs from ten seconds to over two minutes (code sync, then the
// robot's own start-up). The hub marks the card for that whole time, so the
// spinner survives a page refresh; `pendingLaunch` only covers the moment
// between the click and the hub's first word.
function renderLaunch(el, r) {
  const launch = el.querySelector('[data-action="launch"]');
  const note = el.querySelector('.launch-note');
  const busy = !!r.launching_since || pendingLaunch.has(r.key);

  launch.classList.toggle('busy', busy);
  launch.disabled = busy || !CONNECTED.includes(r.state);
  launch.querySelector('use').setAttribute('href', busy ? '#spinner' : '#launch');
  launch.querySelector('svg').classList.toggle('spinning', busy);
  launch.querySelector('span').textContent =
    busy ? 'Launching…' : (r.state === 'RUNNING' ? 'Open' : 'Launch');

  let elapsed = launch.querySelector('.elapsed');
  if (!elapsed) {
    elapsed = document.createElement('span');
    elapsed.className = 'elapsed';
    launch.append(elapsed);
  }
  elapsed.textContent = busy && r.launching_since
    ? `${Math.max(0, Math.round(Date.now() / 1000 - r.launching_since))} s` : '';

  note.classList.toggle('error', !busy && !!r.launch_error);
  note.classList.toggle('hidden', !busy && !r.launch_error);
  note.textContent = busy
    ? 'Starting its system — this can take a couple of minutes.'
    : (r.launch_error ? `Launch failed: ${r.launch_error}` : '');
}

/* ---------------------------------------------------------------- posture */

// NAO's Sit / Lie down / Stand up. The hub keeps the command in flight and
// its outcome on the card (posture_pending / posture_note), so every open page
// agrees; these maps only cover this page's own clicks.
const POSTURE_LABEL = { sit: 'Sit', lie: 'Lie down', stand: 'Stand up' };
const POSTURE_MOVING = { sit: 'Sitting down', lie: 'Lying down', stand: 'Standing up' };
const POSTURE_READY = ['CONNECTED', 'RUNNING'];
const STAND_ARM_MS = 5000;
const pendingPosture = new Map();  // key -> name, between the click and the hub's word
const armedStand = new Map();      // key -> timer: Stand up waits for a second tap
const postureRefusal = new Map();  // key -> a refusal the hub did not put on the card

function disarmStand(key) {
  clearTimeout(armedStand.get(key));
  armedStand.delete(key);
}

function renderPosture(el, r) {
  const row = el.querySelector('.card-posture');
  const note = el.querySelector('.posture-note');
  if (r.type_id !== 'naoqi') {
    row.classList.add('hidden');
    note.classList.add('hidden');
    return;
  }
  row.classList.remove('hidden');

  const moving = r.posture_pending || pendingPosture.get(r.key) || null;
  const launching = !!r.launching_since || pendingLaunch.has(r.key);
  const ready = POSTURE_READY.includes(r.state) && !launching && !moving;
  if (!ready) disarmStand(r.key);
  if (!POSTURE_READY.includes(r.state)) postureRefusal.delete(r.key);
  const armed = armedStand.has(r.key);

  row.querySelectorAll('[data-posture]').forEach(btn => {
    const name = btn.dataset.posture;
    btn.disabled = !ready;
    btn.classList.toggle('busy', moving === name);
    btn.classList.toggle('armed', armed && name === 'stand');
    btn.querySelector('span').textContent =
      armed && name === 'stand' ? 'Confirm' : POSTURE_LABEL[name];
  });

  note.textContent = '';
  note.classList.remove('error', 'warn');
  const refusal = postureRefusal.get(r.key);
  if (moving) {
    note.insertAdjacentHTML('afterbegin',
      '<svg class="spinning" aria-hidden="true"><use href="#spinner"/></svg>');
    note.append(`${POSTURE_MOVING[moving] || 'Moving'}…`);
  } else if (armed) {
    note.classList.add('warn');
    note.textContent = 'NAO will stand up, motors on — make sure someone is next to it, then tap Confirm.';
  } else if (refusal) {
    note.classList.add('error');
    note.textContent = refusal;
  } else if (r.posture_note) {
    note.classList.toggle('error', !!r.posture_failed);
    note.textContent = r.posture_note;
  }
  note.classList.toggle('hidden', !note.textContent);
}

function rerenderPosture(key) {
  const el = els.get(key);
  const r = state.get(key);
  if (el && r) renderPosture(el, r);
}

async function requestPosture(key, name) {
  disarmStand(key);
  postureRefusal.delete(key);
  pendingPosture.set(key, name);
  rerenderPosture(key);
  try {
    const res = await fetch(`/api/robots/${encodeURIComponent(key)}/posture`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const body = await res.json().catch(() => ({}));
    // A hub started before this button existed has no such route.
    if (!res.ok && body.ok === undefined) {
      body.ok = false;
      body.error = res.status === 404 || res.status === 405
        ? 'Restart the hub to use the posture buttons.'
        : `The hub answered ${res.status}.`;
    }
    const r = state.get(key);
    // A heat refusal is already on the card; "busy", "connect first" are not.
    if (body.ok === false && body.error && !(r && r.posture_note === body.error)) {
      postureRefusal.set(key, body.error);
    }
    if (body.ok === false && body.error) announce(body.error);
  } catch (err) {
    postureRefusal.set(key, `Request failed: ${err}`);
  } finally {
    pendingPosture.delete(key);
    rerenderPosture(key);
  }
}

function onPosture(key, name) {
  // Standing raises the robot with its motors on: one tap arms, the second
  // stands. No browser dialog -- the card says what is about to happen.
  if (name === 'stand' && !armedStand.has(key)) {
    postureRefusal.delete(key);
    armedStand.set(key, setTimeout(() => {
      armedStand.delete(key);
      rerenderPosture(key);
    }, STAND_ARM_MS));
    rerenderPosture(key);
    return;
  }
  requestPosture(key, name);
}

// The hub reports only a launch's start and end; the seconds are counted here.
setInterval(() => state.forEach(r => {
  if (r.launching_since && els.has(r.key)) renderLaunch(els.get(r.key), r);
}), 1000);

function renderRightMetric(el, r) {
  // Only NAO reports a battery -- never render an empty gauge for the others.
  const label = el.querySelector('[data-role="right-label"]');
  const value = el.querySelector('[data-role="right-value"]');
  const text = el.querySelector('[data-role="right-text"]');
  const use = el.querySelector('[data-role="right-icon"] use');

  if (typeof r.battery === 'number') {
    label.textContent = 'Battery';
    use.setAttribute('href', '#battery');
    text.textContent = `${r.battery}%`;
    value.classList.toggle('low', r.battery < 20);
  } else if (r.type_id === 'reachy_lite') {
    label.textContent = 'Link';
    use.setAttribute('href', '#plug');
    text.textContent = r.state === 'ABSENT' ? 'unplugged' : 'USB';
    value.classList.remove('low');
  } else {
    label.textContent = 'Address';
    use.setAttribute('href', '#pin');
    text.textContent = r.address || '—';
    value.classList.remove('low');
  }
}

/* -------------------------------------------------------------- keys */

function providerLabel(id) {
  const p = keys.providers.find(x => x.id === id);
  return p ? p.label : id;
}

function canSpeak(id) {
  const p = keys.providers.find(x => x.id === id);
  return !!(p && p.can_speak);
}

function keyText(k) {
  return `${k.label} · ${providerLabel(k.provider)} · …${k.tail}`;
}

function renderKeys(msg) {
  keys = {
    keys: msg.keys || [], assign: msg.assign || {},
    providers: msg.providers || [], robots: msg.robots || {},
  };

  if (!keyProvider.options.length) {
    keys.providers.forEach(p => {
      const o = document.createElement('option');
      o.value = p.id;
      o.textContent = p.can_speak ? p.label : `${p.label} (no speaking backend yet)`;
      keyProvider.append(o);
    });
  }

  keysCount.textContent = `(${keys.keys.length})`;
  keyList.textContent = '';
  if (!keys.keys.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No keys yet. Robots cannot speak until one is added.';
    keyList.append(li);
  }
  keys.keys.forEach(k => {
    const li = document.createElement('li');
    const badge = document.createElement('span');
    badge.className = 'key-provider' + (canSpeak(k.provider) ? '' : ' no-speech');
    badge.textContent = providerLabel(k.provider);
    const label = document.createElement('span');
    label.className = 'key-label';
    label.textContent = k.label;
    const t = document.createElement('span');
    t.className = 'key-tail';
    t.textContent = `…${k.tail}`;
    const users = document.createElement('span');
    users.className = 'key-users';
    const names = Object.entries(keys.assign)
      .filter(([, id]) => id === k.id)
      .map(([robot]) => (state.get(robot) || {}).name || robot);
    users.textContent = names.length ? names.join(', ') : '';
    const del = document.createElement('button');
    del.className = 'key-delete';
    del.title = 'Delete this key';
    del.innerHTML = '<svg aria-hidden="true"><use href="#trash"/></svg>';
    // Two presses, no browser dialog: the first arms, the second deletes.
    del.addEventListener('click', () => {
      if (del.dataset.armed) { deleteKey(k.id); return; }
      del.dataset.armed = '1';
      del.title = 'Press again to delete';
      announce(`Press the bin again to delete “${k.label}”.`);
      setTimeout(() => { delete del.dataset.armed; del.title = 'Delete this key'; }, 4000);
    });
    li.append(badge, label, t, users, del);
    keyList.append(li);
  });

  els.forEach((el, key) => renderCardKey(el, key));
  if (library) renderFiles();     // file rows offer the same keys
}

function renderCardKey(el, robotKey) {
  const row = el.querySelector('.card-key');
  if (!(robotKey in keys.robots)) { row.classList.add('hidden'); return; }
  row.classList.remove('hidden');

  const select = row.querySelector('.key-select');
  const using = keys.robots[robotKey];          // null when the hub has no key
  const assigned = keys.assign[robotKey] || '';
  select.textContent = '';

  const auto = document.createElement('option');
  auto.value = '';
  auto.textContent = using && !assigned
    ? `Default: ${keyText(using)}`
    : (keys.keys.length ? 'Default (first Gemini key)' : 'No keys — add one below');
  select.append(auto);
  keys.keys.forEach(k => {
    const o = document.createElement('option');
    o.value = k.id;
    o.textContent = keyText(k) + (canSpeak(k.provider) ? '' : ' — cannot speak yet');
    select.append(o);
  });
  select.value = assigned;
  row.classList.toggle('fallback', !assigned);

  if (!select.dataset.wired) {
    select.dataset.wired = '1';
    select.addEventListener('change', () => assignKey(robotKey, select.value || null));
  }
}

async function keyRequest(url, options) {
  try {
    const res = await fetch(url, options);
    const body = await res.json().catch(() => ({}));
    if (body.ok === false && body.error) announce(body.error);
    return body;
  } catch (err) {
    announce(`Request failed: ${err}`);
    return {};
  }
}

function assignKey(robotKey, keyId) {
  return keyRequest(`/api/robots/${encodeURIComponent(robotKey)}/key`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key_id: keyId }),
  });
}

function deleteKey(keyId) {
  return keyRequest(`/api/keys/${encodeURIComponent(keyId)}`, { method: 'DELETE' });
}

keyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const body = await keyRequest('/api/keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      provider: keyProvider.value, label: keyLabel.value, key: keySecret.value,
    }),
  });
  if (body.ok) {
    keySecret.value = '';        // the secret leaves the page as soon as it is stored
    keyLabel.value = '';
    announce('Key added. Pick it on a robot’s card.');
  }
});

/* ---------------------------------------------------------- network setup */
// Each lab member brings their own phone hotspot. The panel says whether this
// laptop is on one the robots can join (2.4 GHz), and opens by itself on a
// first visit or when something is wrong.

const setupDetails = document.getElementById('setup-details');
const setupBadge = document.getElementById('setup-badge');
const setupStatus = document.getElementById('setup-status');
const setupCheck = document.getElementById('setup-check');

const HOTSPOT_KIND = { iphone: 'iPhone hotspot', android: 'Android hotspot', phone: 'phone hotspot' };

function firstVisit() {
  try {
    if (localStorage.getItem('hub.setupSeen')) return false;
    localStorage.setItem('hub.setupSeen', '1');
  } catch (err) { /* no storage: treat as seen, the badge still shows */ return false; }
  return true;
}
const showSetupFirst = firstVisit();

async function checkWifi() {
  setupCheck.disabled = true;
  setupCheck.querySelector('svg').classList.add('spinning');
  let info = null;
  try {
    const res = await fetch('/api/wifi');
    info = await res.json();
  } catch (err) {
    info = { ok: false, problem: `Could not ask the hub (${err}).` };
  }
  setupCheck.disabled = false;
  setupCheck.querySelector('svg').classList.remove('spinning');

  const parts = [];
  if (info.ssid) parts.push(`“${info.ssid}”`);
  if (HOTSPOT_KIND[info.hotspot]) parts.push(HOTSPOT_KIND[info.hotspot]);
  if (info.band) parts.push(info.band);
  const where = parts.length ? `This laptop is on ${parts.join(' · ')}.` : '';

  setupStatus.className = `setup-status ${info.ok ? 'ok' : 'problem'}`;
  setupStatus.textContent = '';
  setupStatus.insertAdjacentHTML('beforeend',
    `<svg aria-hidden="true"><use href="#${info.ok ? 'radar' : 'alert'}"/></svg>`);
  const text = document.createElement('span');
  text.textContent = info.ok
    ? `${where} Robots can join it.`
    : `${where} ${info.problem || ''}`.trim();
  setupStatus.append(text);

  setupBadge.className = `setup-badge ${info.ok ? 'ok' : 'problem'}`;
  setupBadge.textContent = info.ok
    ? (info.band ? `${info.ssid || 'hotspot'} · ${info.band}` : 'ready')
    : 'needs attention';
  if (!info.ok || showSetupFirst) setupDetails.open = true;
}

setupCheck.addEventListener('click', checkWifi);
checkWifi();

/* ------------------------------------------------------------- files */
// The lab's shared robot files (hub/library.py). Loaded when the panel is
// first opened, and again after every change -- GitHub is the only copy.

const filesDetails = document.getElementById('files-details');
const filesRobot = document.getElementById('files-robot');
const filesRefresh = document.getElementById('files-refresh');
const filesCount = document.getElementById('files-count');
const filesRepo = document.getElementById('files-repo');
const fileList = document.getElementById('file-list');
const fileForm = document.getElementById('file-form');
const fileInput = document.getElementById('file-input');
const fileUpload = document.getElementById('file-upload');
const filesStatus = document.getElementById('files-status');

let library = null;            // last listing: { robots, files, repo }
let libraryError = '';
let replaceArmed = '';         // "robot/name" a second Upload press replaces
let filesBusy = false;

function sizeText(bytes) {
  if (bytes >= 1 << 20) return `${(bytes / (1 << 20)).toFixed(1)} MB`;
  if (bytes >= 1 << 10) return `${Math.round(bytes / (1 << 10))} KB`;
  return `${bytes} B`;
}

function filesNote(text, kind = '', spinning = false) {
  filesStatus.className = `files-status${kind ? ' ' + kind : ''}`;
  filesStatus.textContent = '';
  if (!text) { filesStatus.classList.add('hidden'); return; }
  if (spinning) {
    filesStatus.insertAdjacentHTML('beforeend',
      '<svg class="spinning" aria-hidden="true"><use href="#spinner"/></svg>');
  }
  const span = document.createElement('span');
  span.textContent = text;
  filesStatus.append(span);
}

async function loadFiles() {
  filesRefresh.querySelector('svg').classList.add('spinning');
  try {
    const res = await fetch('/api/files');
    const body = await res.json().catch(() => ({}));
    if (body.ok) { library = body; libraryError = ''; }
    else libraryError = body.error || `the hub answered ${res.status}`;
  } catch (err) {
    libraryError = `the hub did not answer (${err})`;
  }
  filesRefresh.querySelector('svg').classList.remove('spinning');
  renderFiles();
}

function renderFiles() {
  if (library && !filesRobot.options.length) {
    library.robots.forEach(r => {
      const o = document.createElement('option');
      o.value = r.id;
      filesRobot.append(o);
    });
    let saved = null;
    try { saved = localStorage.getItem('hub.filesRobot'); } catch (err) { /* private window */ }
    if (saved && library.robots.some(r => r.id === saved)) filesRobot.value = saved;
  }
  if (library) {
    filesRepo.textContent = library.repo;
    [...filesRobot.options].forEach(o => {
      const r = library.robots.find(x => x.id === o.value);
      const n = library.files.filter(f => f.robot === o.value).length;
      o.textContent = n ? `${r.label} (${n})` : r.label;
    });
    filesCount.textContent = `(${library.files.length})`;
  }

  fileList.textContent = '';
  if (libraryError) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = `Could not load the files: ${libraryError}`;
    fileList.append(li);
    return;
  }
  if (!library) return;
  const robot = filesRobot.value;
  const label = (library.robots.find(r => r.id === robot) || {}).label || robot;
  const files = library.files.filter(f => f.robot === robot);
  if (!files.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = `No files for ${label} yet. Upload the first one below.`;
    fileList.append(li);
  }
  files.forEach(f => fileList.append(fileRow(f)));
}

function fileRow(f) {
  const li = document.createElement('li');
  li.insertAdjacentHTML('beforeend', '<svg aria-hidden="true"><use href="#file"/></svg>');

  const main = document.createElement('div');
  main.className = 'file-main';
  const name = document.createElement('span');
  name.className = 'file-name';
  name.textContent = f.name;
  const meta = document.createElement('span');
  meta.className = 'file-meta';
  const when = f.updated
    ? new Date(f.updated).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })
    : '';
  meta.textContent = [sizeText(f.size), f.uploader && `by ${f.uploader}`, when,
    f.needs.length ? `needs a ${f.needs.map(providerLabel).join(' / ')} key` : '']
    .filter(Boolean).join(' · ');
  main.append(name, meta);
  li.append(main);

  // A file whose key was removed on upload can get one of this laptop's own
  // keys back on the way down. The page only sends the key's id.
  let keySelect = null;
  if (f.needs.length) {
    keySelect = document.createElement('select');
    keySelect.className = 'file-key';
    keySelect.setAttribute('aria-label', `Key to put into ${f.name}`);
    const none = document.createElement('option');
    none.value = '';
    none.textContent = 'Without a key';
    keySelect.append(none);
    keys.keys.filter(k => f.needs.includes(k.provider)).forEach(k => {
      const o = document.createElement('option');
      o.value = k.id;
      o.textContent = `With ${keyText(k)}`;
      keySelect.append(o);
    });
    if (keySelect.options.length > 1) keySelect.value = keySelect.options[1].value;
    li.append(keySelect);
  }

  const get = document.createElement('button');
  get.type = 'button';
  get.className = 'file-download';
  get.innerHTML = '<svg aria-hidden="true"><use href="#download"/></svg><span>Download</span>';
  get.addEventListener('click', () => downloadFile(f, keySelect ? keySelect.value : '', get));
  li.append(get);

  const del = document.createElement('button');
  del.type = 'button';
  del.className = 'key-delete';
  del.title = 'Delete from the lab library';
  del.innerHTML = '<svg aria-hidden="true"><use href="#trash"/></svg>';
  // Two presses, no browser dialog -- the same as deleting a key.
  del.addEventListener('click', async () => {
    if (!del.dataset.armed) {
      del.dataset.armed = '1';
      del.title = 'Press again to delete it for everyone';
      announce(`Press the bin again to delete “${f.name}” for the whole lab.`);
      setTimeout(() => { delete del.dataset.armed; del.title = 'Delete from the lab library'; }, 4000);
      return;
    }
    del.disabled = true;
    const body = await keyRequest(`/api/files/${f.id}`, { method: 'DELETE' });
    if (body.ok) announce(`Deleted ${f.name}.`);
    loadFiles();
  });
  li.append(del);
  return li;
}

async function downloadFile(f, keyId, button) {
  const span = button.querySelector('span');
  button.disabled = true;
  // The first download of a file comes from GitHub through the hub, which
  // can take minutes on the lab's link; after that the hub has its own copy.
  span.textContent = keyId ? 'Getting it, adding your key…' : 'Getting it…';
  try {
    const url = `/api/files/${f.id}/download` + (keyId ? `?key_id=${encodeURIComponent(keyId)}` : '');
    const res = await fetch(url);
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      announce(body.error || `Download failed (${res.status}).`);
      return;
    }
    // Read it here rather than navigating, so a failure stays a message on
    // this page instead of replacing it.
    const total = Number(res.headers.get('Content-Length')) || f.size;
    const reader = res.body.getReader();
    const parts = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      parts.push(value);
      got += value.length;
      span.textContent = total ? `${Math.min(99, Math.round(100 * got / total))}%` : sizeText(got);
    }
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob(parts));
    link.download = f.name;
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(link.href), 60000);
    announce(keyId ? `${f.name} has your key in it — keep that copy to yourself.`
                   : `Downloaded ${f.name}.`);
  } catch (err) {
    announce(`Download failed: ${err}`);
  } finally {
    button.disabled = false;
    span.textContent = 'Download';
  }
}

fileForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file || filesBusy || !filesRobot.value) return;
  const robot = filesRobot.value;
  const target = `${robot}/${file.name}`;
  const replace = replaceArmed === target;
  replaceArmed = '';
  filesBusy = true;
  fileUpload.disabled = true;
  const started = Date.now();
  const tick = () => filesNote(
    `Uploading ${file.name}: checking it for keys, then sending it to GitHub… ` +
    `${Math.round((Date.now() - started) / 1000)} s`, '', true);
  tick();
  const timer = setInterval(tick, 1000);
  try {
    const res = await fetch(`/api/files?robot=${encodeURIComponent(robot)}` +
      `&name=${encodeURIComponent(file.name)}&replace=${replace}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream' },
      body: file,
    });
    const body = await res.json().catch(() => ({}));
    if (body.ok) {
      const removed = (body.removed || []).length;
      filesNote(`${file.name} is shared` + (removed ? ' — its key was removed first.' : '.'), 'ok');
      fileInput.value = '';
      loadFiles();
    } else if (body.exists) {
      replaceArmed = target;
      filesNote(`${body.error}. Press Upload again to replace it for everyone.`, 'error');
    } else {
      filesNote(body.error || `Upload failed (${res.status}).`, 'error');
    }
  } catch (err) {
    filesNote(`Upload failed: ${err}`, 'error');
  } finally {
    clearInterval(timer);
    filesBusy = false;
    fileUpload.disabled = false;
  }
});

fileInput.addEventListener('change', () => { replaceArmed = ''; filesNote(''); });
filesRobot.addEventListener('change', () => {
  replaceArmed = '';
  try { localStorage.setItem('hub.filesRobot', filesRobot.value); } catch (err) { /* ignore */ }
  renderFiles();
});
filesRefresh.addEventListener('click', loadFiles);
filesDetails.addEventListener('toggle', () => {
  if (filesDetails.open && !library) loadFiles();
});

function removeRobot(key) {
  const el = els.get(key);
  if (el) el.remove();
  els.delete(key);
  state.delete(key);
  updateSummary();
}

function updateSummary() {
  const all = [...state.values()];
  const present = all.filter(r => PRESENT.includes(r.state));
  document.getElementById('present-count').textContent = present.length;
  document.getElementById('total-count').textContent = all.length;
  document.getElementById('connected-count').textContent =
    all.filter(r => CONNECTED.includes(r.state)).length;
  document.getElementById('running-count').textContent =
    all.filter(r => r.state === 'RUNNING').length;
  document.getElementById('robots-count').textContent = `(${all.length})`;
}

function renderLog(entry) {
  const li = document.createElement('li');
  const t = document.createElement('time');
  t.textContent = new Date((entry.ts || Date.now() / 1000) * 1000)
    .toLocaleTimeString([], { hour12: false });
  const span = document.createElement('span');
  span.className = entry.level || 'info';
  span.textContent = entry.text;
  li.append(t, span);
  logEl.prepend(li);
  while (logEl.children.length > 300) logEl.lastElementChild.remove();
}

function renderNetwork(info) {
  const where = (info.interfaces || []).join(', ');
  if (info.on_robot_subnet === false) {
    bannerText.textContent =
      'This laptop is not on the robots’ network' +
      (where ? ` — currently on ${where}` : ' — no usable interface') +
      '. Robots will look dead until you rejoin.';
    banner.classList.remove('hidden');
    rangeText.textContent = 'off the robots’ network';
  } else {
    banner.classList.add('hidden');
    rangeText.textContent = where || 'this network';
  }
}

function showConflict(key, message) {
  const el = els.get(key);
  if (!el) return;
  el.querySelector('.conflict-text').textContent = message;
  el.querySelector('.card-conflict').classList.remove('hidden');
}

function stamp(text) {
  updatedEl.textContent = text;
}

/* ----------------------------------------------------------------- actions */

// A tab opened after a two-minute await counts as a popup and is blocked; one
// opened inside the click is not. So Launch opens a waiting tab right away and
// points it at the robot's system when the hub answers.
function openWaitingTab(name) {
  const tab = window.open('about:blank', '_blank');
  if (!tab) return null;
  try {
    tab.opener = null;
    const doc = tab.document;
    doc.title = `Launching ${name}…`;
    doc.body.style.cssText = 'font: 16px "Segoe UI", Arial, sans-serif; color: #65738a; padding: 40px;';
    doc.body.textContent =
      `Launching ${name}… This tab opens its system as soon as it is ready.`;
  } catch (err) { /* the message is cosmetic */ }
  return tab;
}

function openSystem(url, tab) {
  if (tab && !tab.closed) { tab.location.href = url; return; }
  const w = window.open(url, '_blank');
  if (w) w.opener = null;
  else announce('Launched. The browser blocked the new tab — press Open on the card.');
}

async function post(key, action, tab = null) {
  try {
    const res = await fetch(`/api/robots/${encodeURIComponent(key)}/${action}`,
                            { method: 'POST' });
    const body = await res.json().catch(() => ({}));
    if (body.url) openSystem(body.url, tab);
    else if (tab) tab.close();
    if (body.conflict) showConflict(key, body.error);
    else if (body.ok === false && body.error) announce(body.error);
    return body;
  } catch (err) {
    if (tab) tab.close();
    announce(`Request failed: ${err}`);
  }
}

function launch(el, key, action) {
  const r = state.get(key);
  const tab = openWaitingTab(r ? r.name : 'the robot');
  pendingLaunch.add(key);
  if (r) { renderLaunch(el, r); renderPosture(el, r); }
  post(key, action, tab).finally(() => {
    pendingLaunch.delete(key);
    const now = state.get(key);
    if (now) { renderLaunch(el, now); renderPosture(el, now); }
  });
}

function onCardClick(event) {
  const btn = event.target.closest('[data-action]');
  if (!btn || btn.disabled) return;
  const el = event.currentTarget;
  const key = el.dataset.key;
  const action = btn.dataset.action;

  if (action === 'dismiss') {
    el.querySelector('.card-conflict').classList.add('hidden');
    return;
  }
  if (action === 'posture') {
    onPosture(key, btn.dataset.posture);
    return;
  }
  // Already running: just reopen the tab, do not restart the system.
  if (action === 'launch' && el.dataset.state === 'RUNNING' && el.dataset.systemUrl) {
    window.open(el.dataset.systemUrl, '_blank', 'noopener');
    return;
  }
  if (action === 'override') el.querySelector('.card-conflict').classList.add('hidden');
  if (action === 'launch' || action === 'override') launch(el, key, action);
  else post(key, action);
}

/* ------------------------------------------------------------- log copy */

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) { /* not a secure context, or refused: fall back below */ }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position: fixed; top: 0; opacity: 0;';
  document.body.append(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (err) { ok = false; }
  area.remove();
  return ok;
}

logCopy.addEventListener('click', async (event) => {
  event.preventDefault();     // inside <summary>: copy, do not fold the log
  const text = [...logEl.children].map(li =>
    `${li.querySelector('time').textContent}  ${li.querySelector('span').textContent}`)
    .join('\n');
  if (!text) { announce('Nothing in the log yet.'); return; }
  if (!(await copyText(text))) {
    announce('Could not copy — select the log and press Ctrl+C.');
    return;
  }
  logCopy.classList.add('copied');
  logCopy.querySelector('span').textContent = 'Copied';
  setTimeout(() => {
    logCopy.classList.remove('copied');
    logCopy.querySelector('span').textContent = 'Copy';
  }, 1500);
});

autoConnect.addEventListener('change', () => {
  fetch('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ auto_connect: autoConnect.checked }),
  });
});

scanButton.addEventListener('click', async () => {
  // Discovery is always running; this only asks it to sweep again now.
  scanButton.disabled = true;
  scanButton.querySelector('svg').classList.add('spinning');
  scanButton.querySelector('span').textContent = 'Scanning…';
  try {
    await fetch('/api/rescan', { method: 'POST' });
  } catch (err) {
    announce(`Scan failed: ${err}`);
  }
  setTimeout(() => {
    scanButton.disabled = false;
    scanButton.querySelector('svg').classList.remove('spinning');
    scanButton.querySelector('span').textContent = 'Scan now';
  }, 1200);
});

/* --------------------------------------------------------------- transport */

function handle(msg) {
  switch (msg.type) {
    case 'snapshot':
      grid.textContent = '';
      els.clear();
      state.clear();
      logEl.textContent = '';
      msg.robots.forEach(renderRobot);
      (msg.log || []).forEach(renderLog);
      renderNetwork(msg.network || {});
      if (msg.keys) renderKeys(msg.keys);
      autoConnect.checked = !!(msg.settings && msg.settings.auto_connect);
      stamp('watching for robots…');
      break;
    case 'robot': renderRobot(msg); break;
    case 'robot_removed': removeRobot(msg.key); break;
    case 'log':
      renderLog(msg);
      if (msg.level === 'error') announce(msg.text);
      stamp(`last update ${new Date().toLocaleTimeString([], { hour12: false })}`);
      break;
    case 'network': renderNetwork(msg); checkWifi(); break;
    case 'conflict': showConflict(msg.key, msg.message); announce(msg.message); break;
    case 'settings': autoConnect.checked = !!msg.auto_connect; break;
    case 'keys': renderKeys(msg); break;
    case 'heartbeat': break;
  }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => {
    backoff = 500;
    wsState.classList.add('live');
    wsText.textContent = 'live';
  };
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    wsState.classList.remove('live');
    wsText.textContent = 'reconnecting';
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 10000);
  };
  ws.onerror = () => ws.close();
}

connect();
