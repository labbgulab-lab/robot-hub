/* Reachy app, Group tab: Wizard of Oz for the whole table.
 *
 * The hub plays pre-recorded cues through the group's robot connections, so it
 * works with no conversation running and keeps working when the AI or the
 * internet is down. During a conversation a cue interrupts the current line
 * and the conversation goes on. Choir on: every cue plays on all robots as one
 * unit. Choir off: cues go to the target picked here (default Random).
 *
 * REST: /api/group/woz (state), /connect, /fire, /say, /stop. Live state comes
 * in on the /ws/group socket (reachy-group.js hands us `group.woz` events);
 * while the socket is down the panel polls every 5 s.
 */
'use strict';

(function () {
  const { $, el, str, num, obj, arr } = RA;

  const QUICK_KEYS = ['s', 'd', 'f'];
  const DEFAULT_QUICK = ['Sorry, can you say that again?', 'Let me think about that for a second.', 'That is a great question!'];
  const STORE_KEY = 'reachy.group.woz.open';
  const POLL_MS = 5000;
  const GROUP_LEVEL_KEYS = /^[0-5]$/;       // the Group tab's own keys (interrupting)

  const ERRORS = {
    NOT_CONNECTED: 'Connect the robots first.',
    NO_ROBOTS: 'No robot is available.',
    NO_AUDIO: 'That cue has no recording yet.',
    NO_CUE: 'That cue no longer exists.',
    NO_TARGET: 'That target is not available.',
    NO_VOICE: 'Typed lines need the internet. Recorded cues still work.',
  };

  let E = {};
  let W = { script: { sections: [] }, targets: [], choir: false, connected: [], preparing: false, playing: null, error: '' };
  let loaded = false;
  let missingEndpoint = false;
  let cues = {};                    // id -> cue
  let order = [];                   // cue ids in script order
  let byHotkey = {};                // key -> cue id
  let pointer = 0;
  let target = 'random';            // the picker's value while Choir is off
  let lastPoll = 0;
  let busy = false;

  function store(value) {
    try {
      if (value === undefined) { const v = localStorage.getItem(STORE_KEY); return v === null ? null : v === '1'; }
      localStorage.setItem(STORE_KEY, value ? '1' : '0');
    } catch (err) { /* private window: the panel still works */ }
    return null;
  }

  function choirNow() {
    // The table's own Choir button wins: it is what the next Start will use.
    if (RA.Group && typeof RA.Group.choir === 'function') return !!RA.Group.choir();
    return !!W.choir;
  }
  function isOpen() {
    const saved = store();
    return saved === null ? choirNow() : saved;
  }

  /* ---------------------------------------------------------------- state */
  function apply(state) {
    state = obj(state);
    if (!state.script && !state.targets && state.connected === undefined) return;
    W = {
      script: Array.isArray(obj(state.script).sections) ? obj(state.script) : { sections: [] },
      targets: arr(state.targets), choir: !!state.choir, connected: arr(state.connected),
      preparing: !!state.preparing, playing: state.playing || null,
      error: str(state.error),
    };
    cues = {}; order = []; byHotkey = {};
    arr(W.script.sections).forEach(sec => arr(obj(sec).cues).forEach(c => {
      c = obj(c);
      if (!c.id) return;
      cues[c.id] = c; order.push(c.id);
      if (c.hotkey) byHotkey[str(c.hotkey).toLowerCase()] = c.id;
    }));
    if (pointer >= order.length) pointer = 0;
    if (target !== 'random' && !W.targets.some(t => t.id === target)) target = 'random';
    loaded = true;
    missingEndpoint = false;
    render();
  }

  async function load() {
    lastPoll = performance.now();
    const r = await RA.get('/api/group/woz');
    if (!r.ok) {
      if (r.status === 404 || r.status === 405) { missingEndpoint = true; render(); }
      return;
    }
    apply(r.body);
  }

  function onEvent(m) {
    m = obj(m);
    if (m.state) { apply(m.state); return; }
    if ('playing' in m) { W.playing = m.playing || null; renderNow(); }
  }

  /* --------------------------------------------------------------- render */
  function quickLines() {
    const q = arr(RA.hub.settings.woz_quick);
    return q.length === 3 ? q.map(str) : DEFAULT_QUICK;
  }

  function targetValue() { return choirNow() ? 'auto' : target; }

  function renderPicker() {
    E.picker.textContent = '';
    if (choirNow()) {
      const all = el('option', '', 'All robots');
      all.value = 'auto';
      E.picker.append(all);
      E.picker.value = 'auto';
      E.picker.disabled = true;
      return;
    }
    E.picker.disabled = false;
    const rnd = el('option', '', 'Random');
    rnd.value = 'random';
    E.picker.append(rnd);
    W.targets.forEach(t => { const o = el('option', '', str(t.name || t.id)); o.value = str(t.id); E.picker.append(o); });
    E.picker.value = target;
  }

  function cueCard(cue) {
    const b = el('button', 'cue');
    b.type = 'button';
    b.dataset.cueId = cue.id;
    if (cue.ready === false) { b.style.opacity = '.5'; b.title = "The audio isn't recorded yet."; }
    const head = el('div', 'ch');
    if (cue.hotkey) head.append(el('span', 'k', str(cue.hotkey).toUpperCase()));
    head.append(el('span', 'lb', str(cue.label || cue.id)));
    const dur = num(cue.duration_s, 0);
    if (dur) head.append(el('span', 'du', `${dur.toFixed(1)} s`));
    b.append(head);
    const tx = el('div', 'tx', str(cue.text));
    tx.setAttribute('dir', 'auto');
    b.append(tx);
    b.addEventListener('click', () => { pointer = Math.max(0, order.indexOf(cue.id)); markPointer(); fire(cue.id, false); });
    return b;
  }

  function renderBoard() {
    E.board.textContent = '';
    arr(W.script.sections).forEach(sec => {
      sec = obj(sec);
      const wrap = el('div', 'gw-sec');
      wrap.append(el('h3', 'gw-st', str(sec.title)));
      const grid = el('div', 'cues');
      arr(sec.cues).forEach(c => grid.append(cueCard(obj(c))));
      wrap.append(grid);
      E.board.append(wrap);
    });
    markPointer();
  }

  function markPointer() {
    E.board.querySelectorAll('.cue').forEach(n => n.classList.toggle('next', n.dataset.cueId === order[pointer]));
  }

  function renderQuick() {
    if (!E.quick) return;
    E.quick.textContent = '';
    quickLines().forEach((line, i) => {
      const b = el('button', 'btn btn-sm gw-q');
      b.type = 'button';
      b.append(el('span', 'dk', QUICK_KEYS[i].toUpperCase()), document.createTextNode(` ${line}`));
      b.setAttribute('dir', 'auto');
      b.addEventListener('click', () => say(line));
      E.quick.append(b);
    });
  }

  let tick = 0;
  function renderNow() {
    clearInterval(tick);
    const p = W.playing;
    if (!p) { E.now.textContent = ''; E.count.textContent = ''; return; }
    const cue = cues[p.cue_id] || {};
    const what = str(cue.label || p.text || 'Typed line');
    E.now.textContent = `Now playing: ${what} on ${str(p.target_name || 'all robots')}`;
    const update = () => {
      const left = num(p.until, 0) - Date.now() / 1000;
      if (left <= 0) {
        clearInterval(tick);
        E.count.textContent = '';
        E.now.textContent = '';
        if (W.playing === p) W.playing = null;
        return;
      }
      E.count.textContent = `${left.toFixed(1)} s`;
    };
    update();
    if (W.playing === p) tick = setInterval(update, 100);
  }

  function render() {
    if (!E.panel) return;
    E.panel.hidden = missingEndpoint || !loaded;
    if (E.panel.hidden) return;
    const open = isOpen();
    E.body.hidden = !open;
    E.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    E.toggle.classList.toggle('open', open);
    E.connect.hidden = W.connected.length > 0;
    E.prep.hidden = !W.preparing;
    E.error.hidden = !W.error || arr(W.script.sections).length > 0;
    E.error.textContent = W.error;
    renderPicker();
    renderBoard();
    renderQuick();
    renderNow();
  }

  /* -------------------------------------------------------------- actions */
  function fail(r) {
    const b = obj(r.body);
    RA.toast(ERRORS[b.code] || RA.errorText(r) || 'That did not work.', true);
  }
  function afterOk(b) {
    const missing = arr(b.missing).map(str).filter(Boolean);
    if (missing.length) RA.toast(`${missing.join(', ')} did not get it.`, true);
    if (b.duration_s !== undefined && !W.playing) {
      // The socket event normally follows at once; show it meanwhile.
      W.playing = { text: '', target_name: b.target_name, target_id: b.target_id, until: Date.now() / 1000 + num(b.duration_s, 0) };
      renderNow();
    }
  }

  async function fire(cueId, advance) {
    if (!cues[cueId]) return;
    const node = E.board.querySelector(`[data-cue-id="${CSS.escape(cueId)}"]`);
    if (node) { node.classList.add('firing'); setTimeout(() => node.classList.remove('firing'), 250); }
    if (advance) {
      const idx = order.indexOf(cueId);
      if (idx >= 0 && idx + 1 < order.length) { pointer = idx + 1; markPointer(); }
    }
    const r = await RA.post('/api/group/woz/fire', { cue_id: cueId, target: targetValue() });
    if (!r.ok) { fail(r); return; }
    afterOk(r.body);
  }

  async function say(text) {
    text = str(text).trim();
    if (!text) return;
    const r = await RA.post('/api/group/woz/say', { text, target: targetValue() });
    if (!r.ok) { fail(r); return; }
    E.sayText.value = '';
    afterOk(r.body);
  }

  async function stopAll() {
    const r = await RA.post('/api/group/woz/stop', {});
    if (!r.ok) { fail(r); return; }
    W.playing = null;
    renderNow();
  }

  async function connect() {
    if (busy) return;
    busy = true;
    E.connect.disabled = true;
    const r = await RA.post('/api/group/woz/connect', {});
    busy = false;
    E.connect.disabled = false;
    if (!r.ok) { fail(r); return; }
    W.connected = arr(r.body.connected);
    const missing = arr(r.body.missing).map(str).filter(Boolean);
    if (missing.length) RA.toast(`${missing.join(', ')} did not connect.`, true);
    render();
  }

  /* ------------------------------------------------------------- keyboard */
  // Scoped to the Group tab, like the single-robot tab is scoped to its own,
  // so a key never reaches both. 0 to 5 stay the Group tab's interrupting keys.
  function onKey(ev) {
    if (RA.route.tab !== 'group' || !E.panel || E.panel.hidden || E.body.hidden) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (!$('groups-modal').hidden || !$('copy-modal').hidden) return;
    const t = ev.target;
    if (t && (['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || t.isContentEditable)) {
      if (t === E.sayText && ev.key === 'Escape') { ev.preventDefault(); stopAll(); }
      return;
    }
    if (ev.key === 'Escape') { ev.preventDefault(); stopAll(); return; }
    if (ev.key === ' ') {
      if (t && t.tagName === 'BUTTON') return;      // Space on a focused button presses it
      ev.preventDefault();
      if (order[pointer]) fire(order[pointer], true);
      return;
    }
    if (ev.key.startsWith('Arrow')) {
      if (!order.length) return;
      ev.preventDefault();
      const step = ev.key === 'ArrowDown' || ev.key === 'ArrowRight' ? 1 : -1;
      pointer = (pointer + step + order.length) % order.length;
      markPointer();
      const n = E.board.querySelector('.cue.next');
      if (n && n.scrollIntoView) n.scrollIntoView({ block: 'nearest' });
      return;
    }
    const k = str(ev.key).toLowerCase();
    // A digit with no cue on it is left to the Group tab (0-5 set interrupting).
    if (k.length !== 1 || (GROUP_LEVEL_KEYS.test(k) && !byHotkey[k])) return;
    if (byHotkey[k]) { ev.preventDefault(); fire(byHotkey[k], true); return; }
    const q = QUICK_KEYS.indexOf(k);
    if (q >= 0) { ev.preventDefault(); say(quickLines()[q]); }
  }

  /* ----------------------------------------------------------------- boot */
  function init() {
    const panel = $('gwoz');
    if (!panel) return;
    E = {
      panel, body: $('gwoz-body'), toggle: $('gwoz-toggle'), picker: $('gwoz-target'), connect: $('gwoz-connect'),
      stop: $('gwoz-stop'), now: $('gwoz-now'), count: $('gwoz-count'), prep: $('gwoz-prep'), error: $('gwoz-error'),
      board: $('gwoz-board'), quick: $('gwoz-quick'), sayForm: $('gwoz-say-form'), sayText: $('gwoz-say-text'),
    };
    E.toggle.addEventListener('click', () => { store(!isOpen()); render(); });
    E.picker.addEventListener('change', () => { target = E.picker.value; });
    E.connect.addEventListener('click', connect);
    E.stop.addEventListener('click', stopAll);
    E.sayForm.addEventListener('submit', (ev) => { ev.preventDefault(); say(E.sayText.value); });
    document.addEventListener('keydown', onKey);
    RA.onHub((kind) => { if (kind === 'settings' || kind === 'all') renderQuick(); });
    let lastChoir = null;
    // Loads when the Group tab first shows; polls only while the socket is down.
    setInterval(() => {
      if (RA.route.tab !== 'group' || missingEndpoint) return;
      const now = performance.now();
      if (!loaded) { if (now - lastPoll > 3000) load(); return; }
      if (RA.hub.groupLive === false && now - lastPoll >= POLL_MS) load();
      const c = choirNow();
      if (c !== lastChoir) { lastChoir = c; render(); }
    }, 500);
  }

  // The Group tab asks before using 0-5: a cue on that key, with the panel
  // open, wins.
  function ownsKey(key) {
    if (RA.route.tab !== 'group' || !E.panel || E.panel.hidden || !E.body || E.body.hidden) return false;
    return !!byHotkey[str(key).toLowerCase()];
  }

  RA.GroupWoz = { init, onEvent, reload: load, ownsKey };
})();
