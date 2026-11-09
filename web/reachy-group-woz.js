/* Reachy app, Group tab: Wizard of Oz for the whole table.
 *
 * The hub plays pre-recorded cues through the group's robot connections, so it
 * works with no conversation running and keeps working when the AI or the
 * internet is down. During a conversation a cue interrupts the current line
 * and the conversation goes on. Choir on: every cue plays on all robots as one
 * unit. Choir off: cues go to the target picked here (default Random).
 *
 * REST: /api/group/woz (state), /connect, /fire, /say, /stop. Live state comes
 * in on the /ws/group socket (reachy-group.js hands us `group.woz` events and
 * asks for a fresh state on every `group.state` and when the socket opens
 * again); while the socket is down the panel polls every 5 s.
 *
 * Keys go by the key's place (ev.code), so a Hebrew layout still works, and a
 * held key fires once. The panel stays folded until the operator opens it:
 * only then do the digits with cues stop setting interrupting.
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
  let loadSeq = 0;                  // only the newest state counts
  let refreshTimer = 0;
  let sigs = { picker: '', board: '', quick: '' };   // rebuild only what changed

  // Kept in memory too: with browser storage blocked the panel still opens.
  let openMem = null;
  function store(value) {
    if (value !== undefined) openMem = !!value;
    try {
      if (value === undefined) { const v = localStorage.getItem(STORE_KEY); return v === null ? null : v === '1'; }
      localStorage.setItem(STORE_KEY, value ? '1' : '0');
      return null;
    } catch (err) { /* storage blocked: the in-memory value holds */ }
    return value === undefined ? openMem : null;
  }

  function choirNow() {
    // The table's own Choir button wins: it is what the next Start will use.
    if (RA.Group && typeof RA.Group.choir === 'function') return !!RA.Group.choir();
    return !!W.choir;
  }
  // Only the operator's own open: an open panel takes the digits that have
  // cues, so it never opens by itself (Choir on included).
  function isOpen() { return store() === true; }

  // The Group tab's own state (running, seats), when that page is there.
  function groupState() {
    return RA.Group && typeof RA.Group.state === 'function' ? obj(RA.Group.state()) : {};
  }

  /* ---------------------------------------------------------------- state */
  function apply(state) {
    state = obj(state);
    if (!state.script && !state.targets && state.connected === undefined) return;
    W = {
      script: Array.isArray(obj(state.script).sections) ? obj(state.script) : { sections: [] },
      targets: arr(state.targets), choir: !!state.choir, connected: arr(state.connected),
      preparing: !!state.preparing, playing: state.playing || null,
      error: str(state.error), note: str(state.note),
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
    const seq = ++loadSeq;
    const r = await RA.get('/api/group/woz');
    if (seq !== loadSeq) return;                  // a newer state came in meanwhile
    if (!r.ok) {
      if (r.status === 404 || r.status === 405) { missingEndpoint = true; render(); }
      return;
    }
    apply(r.body);
  }

  function onEvent(m) {
    m = obj(m);
    if (m.state) { loadSeq++; apply(m.state); return; }
    if ('playing' in m) { W.playing = m.playing || null; renderNow(); }
    refresh();
  }

  // Ask the hub again soon (many events in a row make one request), so who is
  // connected is never stale: robots that dropped, a hub that restarted.
  function refresh() {
    if (missingEndpoint || refreshTimer) return;
    refreshTimer = setTimeout(() => { refreshTimer = 0; load(); }, 300);
  }

  /* --------------------------------------------------------------- render */
  function quickLines() {
    const q = arr(RA.hub.settings.woz_quick);
    return q.length === 3 ? q.map(str) : DEFAULT_QUICK;
  }

  function targetValue() { return choirNow() ? 'auto' : target; }

  // The keys a cue has taken win; a quick line only gets the keys left over.
  function quickKey(i) { const k = QUICK_KEYS[i]; return byHotkey[k] ? '' : k; }

  // Robots the cues would play on that are not connected now. Out of a
  // conversation that is every ticked robot too: one that was ticked after
  // Connect, or could not be reached then, is in no target yet.
  function notConnected() {
    const want = new Set();
    W.targets.forEach(t => arr(obj(t).members).forEach(k => want.add(str(k))));
    const g = groupState();
    if (!g.running) arr(g.seats).forEach(s => { s = obj(s); if (s.key && s.included !== false) want.add(str(s.key)); });
    const have = new Set(W.connected.map(str));
    return [...want].filter(k => !have.has(k));
  }

  function renderPicker() {
    const sig = JSON.stringify([choirNow(), W.targets, target]);
    if (sig === sigs.picker) return;              // an open list stays open
    sigs.picker = sig;
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
    const lb = el('span', 'lb', str(cue.label || cue.id));
    lb.setAttribute('dir', 'auto');
    head.append(lb);
    const dur = num(cue.duration_s, 0);
    if (dur) head.append(el('span', 'du', `${dur.toFixed(1)} s`));
    b.append(head);
    const tx = el('div', 'tx', str(cue.text));
    tx.setAttribute('dir', 'auto');
    b.append(tx);
    b.addEventListener('click', () => { pointer = Math.max(0, order.indexOf(cue.id)); markPointer(); fire(cue.id, false); b.blur(); });
    return b;
  }

  function renderBoard() {
    const sig = JSON.stringify(W.script.sections);
    if (sig !== sigs.board) {                     // a click in flight keeps its button
      sigs.board = sig;
      buildBoard();
    }
    markPointer();
  }

  function buildBoard() {
    E.board.textContent = '';
    arr(W.script.sections).forEach(sec => {
      sec = obj(sec);
      const wrap = el('div', 'gw-sec');
      const title = el('h3', 'gw-st', str(sec.title));
      title.setAttribute('dir', 'auto');
      wrap.append(title);
      const grid = el('div', 'cues');
      arr(sec.cues).forEach(c => grid.append(cueCard(obj(c))));
      wrap.append(grid);
      E.board.append(wrap);
    });
  }

  function markPointer() {
    E.board.querySelectorAll('.cue').forEach(n => n.classList.toggle('next', n.dataset.cueId === order[pointer]));
  }

  function renderQuick() {
    if (!E.quick) return;
    const lines = quickLines();
    const keys = QUICK_KEYS.map((k, i) => quickKey(i));
    const sig = JSON.stringify([lines, keys]);
    if (sig === sigs.quick) return;
    sigs.quick = sig;
    E.quick.textContent = '';
    lines.forEach((line, i) => {
      const b = el('button', 'btn btn-sm gw-q');
      b.type = 'button';
      if (keys[i]) b.append(el('span', 'dk', keys[i].toUpperCase()), document.createTextNode(' '));
      b.append(document.createTextNode(line));
      b.setAttribute('dir', 'auto');
      b.title = keys[i] ? `Say it (${keys[i].toUpperCase()})` : 'Say it';
      b.addEventListener('click', () => { say(line); b.blur(); });
      E.quick.append(b);
    });
    // The hint names only the keys that really reach a quick line.
    const free = keys.filter(Boolean);
    E.qkeys.textContent = free.length ? ' ·' : '';
    free.forEach(k => E.qkeys.append(' ', el('span', 'kbd', k.toUpperCase())));
    if (free.length) E.qkeys.append(' quick lines');
    E.qkeys.hidden = !free.length;
  }

  // While open, the panel takes the digits that have cues: say so here, and
  // the Group tab's "0 to 5 set interrupting" hints step aside meanwhile.
  function renderDigits(open) {
    const taken = open ? ['0', '1', '2', '3', '4', '5'].filter(k => byHotkey[k]) : [];
    E.digits.textContent = '';
    taken.forEach(k => E.digits.append(el('span', 'kbd', k), ' '));
    if (taken.length) E.digits.append('fire cues here, not interrupting');
    E.digits.hidden = !taken.length;
    holdDigits(taken.length > 0);
  }
  function holdDigits(on) {
    if (document.body && document.body.classList) document.body.classList.toggle('gwoz-digits', !!on);
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
    if (E.panel.hidden) { holdDigits(false); return; }
    const open = isOpen();
    E.body.hidden = !open;
    E.toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    E.toggle.classList.toggle('open', open);
    // Connect also brings back robots that dropped out.
    E.connect.hidden = W.connected.length > 0 && !notConnected().length;
    E.prep.hidden = !W.preparing;
    const hasCues = arr(W.script.sections).length > 0;
    // Why cues are grey (no voice: offline, no key), while any still is.
    const note = W.note && order.some(id => cues[id].ready === false) ? W.note : '';
    const msg = !hasCues ? W.error : note;
    E.error.hidden = !msg;
    E.error.textContent = msg;
    renderPicker();
    renderBoard();
    renderQuick();
    renderDigits(open);
    renderNow();
  }

  /* -------------------------------------------------------------- actions */
  // The hub's own reason is short and says what to do; ours only as a fallback.
  function fail(r) {
    const b = obj(r.body);
    const own = str(b.error || (typeof b.detail === 'string' ? b.detail : '')).trim();
    RA.toast(RA.cap(own) || ERRORS[b.code] || RA.errorText(r) || 'That did not work.', true);
    if (b.code === 'NOT_CONNECTED' || b.code === 'NO_ROBOTS' || !r.status) refresh();
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
  // The key by its place on the keyboard: KeyS is 's' on a Hebrew layout too.
  function keyOf(ev) {
    const code = str(ev && ev.code);
    let m = /^Key([A-Z])$/.exec(code);
    if (m) return m[1].toLowerCase();
    m = /^(?:Digit|Numpad)(\d)$/.exec(code);
    if (m) return m[1];
    const k = str(ev && ev.key);
    return k.length === 1 ? k.toLowerCase() : '';
  }
  const isSpace = (ev) => ev.code === 'Space' || ev.key === ' ';
  const isEsc = (ev) => ev.key === 'Escape' || ev.code === 'Escape';

  // A dialog or drawer open: the keyboard is its own (Esc closes it, no STOP).
  function dialogOpen() {
    return !!document.querySelector('.modal-wrap:not([hidden]), .drawer-wrap:not([hidden])');
  }

  // Typing somewhere. The target picker is not: the keys stay the panel's.
  const TEXT_TYPES = ['', 'text', 'search', 'number', 'email', 'password', 'url', 'tel', 'range', 'date', 'time'];
  function typing(t) {
    if (!t || t === E.picker) return false;
    if (t.isContentEditable || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') return true;
    return t.tagName === 'INPUT' && TEXT_TYPES.includes(str(t.type).toLowerCase());
  }

  // Focus back to the page, so Space never presses the last-used control.
  function release(t) {
    if (t && t.blur && (t.tagName === 'BUTTON' || t.tagName === 'INPUT' || t === E.picker)) t.blur();
  }

  function active() {
    return RA.route.tab === 'group' && !!E.panel && !E.panel.hidden;
  }

  // Scoped to the Group tab, like the single-robot tab is scoped to its own,
  // so a key never reaches both. 0 to 5 stay the Group tab's interrupting keys
  // unless a cue is on them. Listens in the capture phase, so a dialog that
  // this Esc is about to close still counts as open here.
  function onKey(ev) {
    if (!active() || dialogOpen()) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    const t = ev.target;
    if (E.body.hidden) {
      // Folded: only STOP (its button stays in view), while there is something
      // to silence: a cue, or the conversation's line.
      if (isEsc(ev) && (W.playing || groupState().running) && !typing(t)) {
        ev.preventDefault();
        if (!ev.repeat) stopAll();
      }
      return;
    }
    if (typing(t)) {
      if (t === E.sayText && isEsc(ev)) { ev.preventDefault(); if (!ev.repeat) stopAll(); }
      return;
    }
    if (isEsc(ev)) { ev.preventDefault(); if (!ev.repeat) stopAll(); return; }
    if (isSpace(ev)) {
      ev.preventDefault();                        // always the outlined cue, whatever has focus
      release(t);
      if (!ev.repeat && order[pointer]) fire(order[pointer], true);   // a held key fires once
      return;
    }
    if (str(ev.key).startsWith('Arrow')) {
      if (t === E.picker) ev.preventDefault();    // never moves the target picker
      if (!order.length) return;                  // no cues: arrows scroll the page
      ev.preventDefault();
      release(t);
      const step = ev.key === 'ArrowDown' || ev.key === 'ArrowRight' ? 1 : -1;
      pointer = (pointer + step + order.length) % order.length;
      markPointer();
      const n = E.board.querySelector('.cue.next');
      if (n && n.scrollIntoView) n.scrollIntoView({ block: 'nearest' });
      return;
    }
    const k = keyOf(ev);
    if (!k) return;
    // A digit with no cue on it is left to the Group tab (0-5 set interrupting).
    if (GROUP_LEVEL_KEYS.test(k) && !byHotkey[k]) return;
    const q = QUICK_KEYS.indexOf(k);
    if (!byHotkey[k] && q < 0) {
      if (t === E.picker) ev.preventDefault();    // no type-to-pick on the picker
      return;
    }
    ev.preventDefault();
    release(t);
    if (ev.repeat) return;                        // a held key fires once
    if (byHotkey[k]) { fire(byHotkey[k], true); return; }   // a script cue wins
    say(quickLines()[q]);
  }

  // A focused button would also click on Space key-up; Space belongs to the outlined cue.
  function onKeyUp(ev) {
    if (!isSpace(ev) || !active() || E.body.hidden || dialogOpen() || typing(ev.target)) return;
    ev.preventDefault();
  }

  /* ----------------------------------------------------------------- boot */
  function init() {
    const panel = $('gwoz');
    if (!panel) return;
    E = {
      panel, body: $('gwoz-body'), toggle: $('gwoz-toggle'), picker: $('gwoz-target'), connect: $('gwoz-connect'),
      stop: $('gwoz-stop'), now: $('gwoz-now'), count: $('gwoz-count'), prep: $('gwoz-prep'), error: $('gwoz-error'),
      board: $('gwoz-board'), quick: $('gwoz-quick'), sayForm: $('gwoz-say-form'), sayText: $('gwoz-say-text'),
      qkeys: $('gwoz-qkeys'), digits: $('gwoz-digits'),
    };
    E.toggle.addEventListener('click', () => { store(!isOpen()); render(); E.toggle.blur(); });
    E.picker.addEventListener('change', () => { target = E.picker.value; E.picker.blur(); });
    E.connect.addEventListener('click', () => { E.connect.blur(); connect(); });
    E.stop.addEventListener('click', () => { E.stop.blur(); stopAll(); });
    E.sayForm.addEventListener('submit', (ev) => { ev.preventDefault(); say(E.sayText.value); });
    document.addEventListener('keydown', onKey, true);
    document.addEventListener('keyup', onKeyUp, true);
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
  // open, wins. Takes the key event (or a key).
  function ownsKey(ev) {
    if (!active() || !E.body || E.body.hidden || dialogOpen()) return false;
    const k = ev && typeof ev === 'object' ? keyOf(ev) : str(ev).toLowerCase();
    return !!byHotkey[k];
  }

  RA.GroupWoz = { init, onEvent, reload: load, refresh, ownsKey };
})();
