/* Reachy app, Wizard of Oz tab: you drive the robot.
 *
 * reachy_chat's Operator Board through the hub's proxy: the cue script by
 * section (hotkeys, durations, motion chips, the next cue outlined, Space /
 * arrows / Esc / hotkeys as on the board), Now playing, Reload script,
 * Rebuild audio, STOP, the cue editor; plus Say anything (a typed line is
 * recorded while you type, so Say is instant), quick saves on S / D / F
 * (Settings key woz_quick) and the Said history with Again.
 */
'use strict';

(function () {
  const { $, el, str, num, obj, arr } = RA;

  const PREPARE_DEBOUNCE_MS = 600;
  const QUICK_KEYS = ['s', 'd', 'f'];
  const DEFAULT_QUICK = ['Sorry, can you say that again?', 'Let me think about that for a second.', 'That is a great question!'];

  let E = {};
  let key = '';
  let cues = {};                   // id -> cue
  let order = [];                  // cue ids in script order
  let byHotkey = {};               // key -> cue id
  let pointer = 0;
  let playTimer = 0;
  let systemState = '';
  let editing = null;              // {cue, sectionId} while the editor is open
  let motions = null;
  let loadedFor = '';
  let prepTimer = 0;
  let prepared = new Map();        // text -> {ready}
  let said = [];                   // [{id, text, ms, prepared, at, kind}]
  let errorTimer = 0;
  let confirmDelete = false;

  function esc(s) { return str(s); }

  /* ---------------------------------------------------------------- board */
  function motionName(m) {
    m = obj(m);
    if (!m.type) return '';
    if (m.type === 'head') return `look ${m.direction || m.name || ''}`.trim();
    if (m.type === 'dance') return `dance: ${m.name || ''}`;
    return str(m.name || m.type);
  }

  function cueCard(cue) {
    // A div, not a button: the card carries its own edit button.
    const node = el('div', `cue${cue.has_audio ? '' : ' motion'}`);
    node.dataset.cueId = cue.id;
    node.setAttribute('role', 'button');
    node.tabIndex = 0;
    const head = el('span', 'ch');
    head.append(el('span', 'k', esc(cue.hotkey ? cue.hotkey.toUpperCase() : '·')), el('span', 'lb', esc(cue.label)),
                el('span', 'du', cue.duration_s ? `${Number(cue.duration_s).toFixed(1)}s` : ''));
    if (!cue.hotkey) { head.firstChild.style.background = '#4A433C'; head.firstChild.style.color = '#D8D1C7'; }
    node.append(head);
    if (cue.text) { const tx = el('span', 'tx', cue.text); tx.dir = 'auto'; node.append(tx); }
    const tags = el('span', 'tags');
    const motion = motionName(cue.motion);
    if (motion) tags.append(el('span', 'tg', motion));
    if (!cue.has_audio) tags.append(el('span', 'tg', 'motion only'));
    if (cue.has_audio && !cue.audio_ready) tags.append(el('span', 'tg bad', 'no audio: press Rebuild'));
    node.append(tags);
    const edit = el('button', 'ed', 'edit');
    edit.type = 'button';
    edit.title = 'Edit this cue (it does not fire)';
    edit.setAttribute('aria-label', `Edit ${cue.label}`);
    edit.addEventListener('click', (ev) => { ev.stopPropagation(); openEditor(cue); });
    node.append(edit);
    node.addEventListener('click', () => { fire(cue.id, false); node.blur(); });
    node.addEventListener('keydown', (ev) => {
      if (ev.target !== node) return;
      // Enter fires this card; Space always fires the outlined cue (page handler).
      if (ev.key === 'Enter') {
        ev.preventDefault();
        fire(cue.id, false);
      }
    });
    return node;
  }

  function renderBoard(catalog) {
    catalog = obj(catalog);
    cues = {};
    order = arr(catalog.order);
    byHotkey = {};
    E.board.textContent = '';
    arr(catalog.sections).forEach(section => {
      section = obj(section);
      const card = el('section', 'pnl');
      card.style.gap = '10px';
      const head = el('div', 'pnlh');
      const h = el('h2', '', section.title || section.id);
      h.dir = 'auto';
      const list = arr(section.cues);
      head.append(h, el('span', 'sub', RA.plural(list.length, 'cue')));
      card.append(head);
      const grid = el('div', 'cues');
      list.forEach(cue => {
        cue = obj(cue);
        cues[cue.id] = cue;
        if (cue.hotkey) byHotkey[str(cue.hotkey).toLowerCase()] = cue.id;
        grid.append(cueCard(cue));
      });
      const add = el('button', 'addcue', '+ add cue');
      add.type = 'button';
      add.title = 'A new cue in this section';
      add.addEventListener('click', () => openEditor(null, section.id));
      grid.append(add);
      card.append(grid);
      E.board.append(card);
    });
    if (!arr(catalog.sections).length) E.board.append(el('p', 'sub', 'This robot has no cue script yet. Put one in reachy_chat show/cues.json, then press Reload script.'));
    if (pointer >= order.length) pointer = Math.max(0, order.length - 1);
    markPointer(false);
    renderQuick();
  }

  function markPointer(scroll = true) {
    E.board.querySelectorAll('.cue.next').forEach(n => n.classList.remove('next'));
    const id = order[pointer];
    if (!id) return;
    const node = E.board.querySelector(`[data-cue-id="${CSS.escape(id)}"]`);
    if (node) {
      node.classList.add('next');
      if (scroll) node.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    }
  }

  function movePointer(delta) {
    if (!order.length) return;
    pointer = Math.max(0, Math.min(order.length - 1, pointer + delta));
    markPointer();
  }

  async function loadCues() {
    if (!RA.link || RA.link.state !== 'open') return;
    const r = await RA.link.api('GET', 'show/cues');
    if (!r.ok) { showError(RA.errorText(r)); return; }
    loadedFor = key;
    renderBoard(r.body);
    if (r.body.state) systemStateChanged(str(r.body.state));
    // Opening mid-cue: say what is playing.
    if (r.body.playing && cues[r.body.playing]) {
      E.npLabel.textContent = cues[r.body.playing].label;
      E.npText.textContent = cues[r.body.playing].text || '';
    }
    loadSaid();
  }

  /* --------------------------------------------------------------- firing */
  async function fire(cueId, advance) {
    const cue = cues[cueId];
    if (!cue) return;
    const node = E.board.querySelector(`[data-cue-id="${CSS.escape(cueId)}"]`);
    if (node) { node.classList.add('firing'); setTimeout(() => node.classList.remove('firing'), 250); }
    const r = await RA.link.api('POST', `show/fire/${encodeURIComponent(cueId)}`);
    if (!r.ok) {
      showError(r.body.error === 'invalid_state' ? `the robot isn't ready (${STATE_WORD[r.body.state] || r.body.state})` : RA.errorText(r));
      return;
    }
    addSaid({ text: cue.text || `(${motionName(cue.motion) || cue.label})`, label: cue.label, cue: cueId, at: Date.now() / 1000, kind: 'cue' });
    if (advance) {
      const idx = order.indexOf(cueId);
      if (idx >= 0 && idx + 1 < order.length) { pointer = idx + 1; markPointer(); }
    }
  }

  async function stopAll() {
    const r = await RA.link.api('POST', 'show/stop');
    if (!r.ok) showError(RA.errorText(r));
  }

  function showError(message) {
    E.npLabel.textContent = `error: ${message}`;
    E.npLabel.classList.add('err');
    clearTimeout(errorTimer);
    errorTimer = setTimeout(() => E.npLabel.classList.remove('err'), 3000);
  }

  function startPlaying(p) {
    clearInterval(playTimer);
    const cue = cues[p.cue_id] || {};
    E.npLabel.classList.remove('err');
    E.npLabel.textContent = p.said ? 'Said' : (p.label || p.cue_id);
    E.npText.textContent = cue.text || p.text || '';
    const total = num(p.duration_s, 0);
    if (!total) { E.npBar.style.width = '0%'; E.npCount.textContent = ''; return; }
    const t0 = performance.now();
    playTimer = setInterval(() => {
      const elapsed = (performance.now() - t0) / 1000;
      E.npBar.style.width = `${Math.min(100, (elapsed / total) * 100)}%`;
      const left = Math.max(0, total - elapsed);
      E.npCount.textContent = `${left.toFixed(1)} s`;
      if (left <= 0) clearInterval(playTimer);
    }, 50);
  }
  function endPlaying() {
    clearInterval(playTimer);
    E.npBar.style.width = '0%';
    E.npCount.textContent = '';
  }

  const STATE_WORD = {
    STARTING: 'Starting', IDLE_BREATHING: 'Idle', CONVERSATION_RUNNING: 'In conversation',
    STOPPED: 'Stopped', SHUTTING_DOWN: 'Shutting down', ERROR: 'Error',
  };
  const STATE_PILL = {
    STARTING: 'p-busy', IDLE_BREATHING: 'p-run', CONVERSATION_RUNNING: 'p-run',
    STOPPED: 'p-off', SHUTTING_DOWN: 'p-warn', ERROR: 'p-lost',
  };
  function systemStateChanged(state) {
    systemState = state;
    E.state.textContent = '';
    if (state) {
      const p = RA.pill(STATE_PILL[state] || 'p-off', STATE_WORD[state] || state, state === 'STARTING' || state === 'SHUTTING_DOWN');
      p.style.height = '24px';
      p.title = state;
      E.state.append(p);
    }
    E.convWarning.hidden = state !== 'CONVERSATION_RUNNING';
    const usable = state === 'CONVERSATION_RUNNING' || state === 'IDLE_BREATHING';
    E.board.classList.toggle('off', !usable);
    E.notReady.hidden = usable || !state || !RA.link || RA.link.state !== 'open';
  }

  /* ------------------------------------------------------------ the editor */
  async function loadMotions() {
    if (motions) return motions;
    const r = await RA.link.api('GET', 'show/motions');
    motions = r.ok ? { emotions: arr(r.body.emotions), dances: arr(r.body.dances), directions: arr(r.body.directions) }
      : { emotions: [], dances: [], directions: [] };
    return motions;
  }

  function fillMotionNames(type, selected) {
    const sel = $('ed-motion-name');
    let opts = [];
    if (type === 'emotion') opts = motions.emotions;
    else if (type === 'dance') opts = motions.dances;
    else if (type === 'head') opts = motions.directions;
    RA.fillOptions(sel, opts.length ? opts.map(n => [n, n]) : [['', '(none)']], selected || (opts[0] || ''));
    sel.disabled = opts.length === 0;
    sel.style.opacity = opts.length ? '' : '.5';
  }

  async function openEditor(cue, sectionId) {
    await loadMotions();
    editing = { cue: cue || null, sectionId: sectionId || (cue && cue.section) };
    confirmDelete = false;
    const m = obj(cue && cue.motion);
    $('ed-title').textContent = cue ? `Edit: ${cue.label}` : 'New cue';
    $('ed-label').value = cue ? str(cue.label) : '';
    $('ed-text').value = cue ? str(cue.text) : '';
    $('ed-hotkey').value = cue ? str(cue.hotkey) : '';
    $('ed-boss').value = cue ? str(cue.boss_cue) : '';
    $('ed-motion-type').value = m.type || '';
    fillMotionNames(m.type || '', m.name || m.direction || '');
    $('ed-delete').hidden = !cue;
    $('ed-confirm').hidden = true;
    editorError('');
    $('ed-modal').hidden = false;
    setTimeout(() => $('ed-text').focus(), 30);
  }

  function closeEditor() {
    editing = null;
    $('ed-modal').hidden = true;
  }

  function editorError(text) {
    const box = $('ed-error');
    box.textContent = '';
    if (text) {
      const n = RA.note('err', 'alert', text);
      n.style.padding = '8px 10px';
      box.append(n);
    }
  }

  // Hotkeys must differ from every other cue and from the quick saves.
  function hotkeyClash(hotkey) {
    const k = str(hotkey).toLowerCase();
    if (!k) return '';
    if (editing && editing.cue && str(editing.cue.hotkey).toLowerCase() === k) return '';   // unchanged
    if (QUICK_KEYS.includes(k)) return `Hotkey "${k.toUpperCase()}" is a quick save. Hotkeys must differ from every cue and quick save (S, D, F).`;
    if (k === ' ') return 'Space fires the outlined cue. Pick another key.';
    const other = byHotkey[k];
    if (other && (!editing.cue || other !== editing.cue.id)) {
      return `Hotkey "${k.toUpperCase()}" is already used by "${cues[other].label}". Hotkeys must differ from every cue and quick save (S, D, F).`;
    }
    return '';
  }

  function editorPayload() {
    const type = $('ed-motion-type').value;
    const name = $('ed-motion-name').value;
    let motion = null;
    if (type === 'head') motion = { type: 'head', direction: name };
    else if (type) motion = { type, name };
    return { label: $('ed-label').value, text: $('ed-text').value, hotkey: $('ed-hotkey').value,
             boss_cue: $('ed-boss').value, motion };
  }

  async function saveEditor() {
    if (!editing) return;
    const payload = editorPayload();
    const clash = hotkeyClash(payload.hotkey);
    if (clash) { editorError(clash); $('ed-hotkey').focus(); return; }
    if (!payload.label.trim()) { editorError('Give the cue a name so you can find it.'); $('ed-label').focus(); return; }
    if (!payload.text.trim() && !payload.motion) { editorError('A cue needs a line to speak, a motion, or both.'); return; }
    const btn = $('ed-save');
    btn.disabled = true;
    btn.textContent = payload.text.trim() ? 'saving + re-recording…' : 'saving…';
    btn.classList.add('busy');
    editorError('');
    const r = editing.cue
      ? await RA.link.api('PUT', `show/cue/${encodeURIComponent(editing.cue.id)}`, payload)
      : await RA.link.api('POST', 'show/cue', { ...payload, section_id: editing.sectionId });
    btn.disabled = false;
    btn.textContent = 'Save';
    btn.classList.remove('busy');
    if (!r.ok) {
      editorError(r.status === 500 ? `Couldn't re-record the line: ${RA.errorText(r)}. Nothing was saved.` : RA.errorText(r));
      return;
    }
    renderBoard(r.body);
    closeEditor();
  }

  async function deleteEditing() {
    if (!editing || !editing.cue) return;
    const label = editing.cue.label || editing.cue.id;
    if (!confirmDelete) {
      confirmDelete = true;
      const box = $('ed-confirm');
      box.textContent = '';
      box.append(RA.note('warn', 'trash', `Delete "${label}"? Its recording is deleted too.`, [
        RA.button('Delete', 'btn-stop btn-sm', deleteEditing, 'trash'),
        RA.button('Cancel', 'btn-ghost btn-sm', () => { confirmDelete = false; box.hidden = true; }),
      ]));
      box.hidden = false;
      return;
    }
    const r = await RA.link.api('DELETE', `show/cue/${encodeURIComponent(editing.cue.id)}`);
    confirmDelete = false;
    $('ed-confirm').hidden = true;
    if (!r.ok) {
      editorError(r.status === 409 ? 'That cue is playing right now. Stop it first.' : RA.errorText(r));
      return;
    }
    renderBoard(r.body);
    closeEditor();
  }

  async function rebuild() {
    const btn = E.rebuild;
    btn.disabled = true;
    btn.classList.add('busy');
    btn.querySelector('span').textContent = 'rebuilding…';
    const r = await RA.link.api('POST', 'show/rebuild');
    btn.disabled = false;
    btn.classList.remove('busy');
    btn.querySelector('span').textContent = 'Rebuild audio';
    if (!r.ok) { showError(RA.errorText(r)); return; }
    renderBoard(r.body);
    const n = arr(r.body.built).length;
    const failed = arr(r.body.failed).length;
    E.npLabel.classList.remove('err');
    E.npLabel.textContent = failed ? `Rebuilt ${n}, ${failed} failed: see the log`
      : (n ? `Rebuilt ${RA.plural(n, 'line')}` : 'Everything is already up to date');
  }

  async function reload() {
    const r = await RA.link.api('POST', 'show/reload');
    if (!r.ok) { showError(`Couldn't reload the script: ${RA.errorText(r)}`); return; }
    renderBoard(r.body);
    E.npLabel.classList.remove('err');
    E.npLabel.textContent = `Reloaded ${RA.plural(order.length, 'cue')}`;
  }

  /* -------------------------------------------------------- say anything */
  function sayStatus(text, err) {
    E.sayStatus.textContent = text || '';
    E.sayStatus.classList.toggle('err', !!err);
  }

  function onSayInput() {
    clearTimeout(prepTimer);
    const text = E.sayText.value.trim();
    sayStatus('');
    if (!text) return;
    if (prepared.get(text)) { sayStatus('ready'); return; }
    // Recorded while you type (debounced), so Say is instant.
    prepTimer = setTimeout(async () => {
      sayStatus('recording…');
      const r = await RA.link.api('POST', 'show/prepare', { text, wait: false });
      if (E.sayText.value.trim() !== text) return;          // typed on meanwhile
      if (!r.ok) { sayStatus(RA.errorText(r), true); return; }
      if (r.body.ready) { prepared.set(text, true); sayStatus('ready'); }
      else sayStatus('recording…');
    }, PREPARE_DEBOUNCE_MS);
  }

  async function say(text, kind) {
    text = str(text).trim();
    if (!text || !RA.link) return;
    clearTimeout(prepTimer);
    const ready = prepared.get(text);
    sayStatus(ready ? 'saying…' : 'recording… then saying it');
    const r = await RA.link.api('POST', 'show/say', { text });
    if (!r.ok) {
      const b = obj(r.body);
      sayStatus('');
      const why = b.code === 'INVALID_STATE' ? `the robot isn't ready (${STATE_WORD[b.state] || b.state})`
        : b.code === 'NO_KEY' ? `Say isn't working: ${b.error || 'no key for the voice'}` : RA.errorText(r);
      showError(why);
      return;
    }
    prepared.set(text, true);
    sayStatus(r.body.prepared ? '' : `recorded in ${(num(r.body.waited_ms, 0) / 1000).toFixed(1)} s`);
    if (kind !== 'again' && kind !== 'quick') E.sayText.value = '';
  }

  /* ------------------------------------------------------------ quick saves */
  function quickLines() {
    const q = arr(RA.hub.settings.woz_quick);
    return q.length === 3 ? q.map(str) : DEFAULT_QUICK;
  }

  function renderQuick() {
    E.quickList.textContent = '';
    quickLines().forEach((line, i) => {
      const b = el('button', 'cue');
      b.type = 'button';
      b.style.minHeight = '0';
      const head = el('span', 'ch');
      const taken = byHotkey[QUICK_KEYS[i]];   // a cue with this hotkey wins on the keyboard
      head.append(el('span', 'k', taken ? '·' : QUICK_KEYS[i].toUpperCase()), el('span', 'lb', line || '(empty: press Edit)'));
      head.lastChild.dir = 'auto';
      b.append(head);
      b.disabled = !line;
      b.title = !line ? 'Empty. Press Edit to give it a line.'
        : taken ? `Say it. ${QUICK_KEYS[i].toUpperCase()} fires the cue "${str(obj(cues[taken]).label)}".` : `Say it (${QUICK_KEYS[i].toUpperCase()})`;
      b.addEventListener('click', () => { say(line, 'quick'); b.blur(); });
      E.quickList.append(b);
    });
    // Ready ahead of time, like a typed line.
    if (RA.link && RA.link.state === 'open') {
      quickLines().filter(Boolean).forEach(line => {
        if (!prepared.has(line)) {
          prepared.set(line, false);
          RA.link.api('POST', 'show/prepare', { text: line, wait: false }).then(r => { if (r.ok && r.body.ready) prepared.set(line, true); });
        }
      });
    }
  }

  function openQuick() {
    const lines = quickLines();
    lines.forEach((l, i) => { $(`quick-${i}`).value = l; });
    $('quick-error').textContent = '';
    $('quick-modal').hidden = false;
    $('quick-0').focus();
  }
  async function saveQuick(event) {
    event.preventDefault();
    const lines = [0, 1, 2].map(i => $(`quick-${i}`).value);
    RA.setSave('woz', 'Saving', 'busy');
    const r = await RA.put('/api/settings', { woz_quick: lines });
    if (!r.ok) {
      RA.setSave('woz', 'Not saved', 'problem');
      $('quick-error').textContent = '';
      $('quick-error').append(RA.note('err', 'alert', RA.errorText(r)));
      return;
    }
    RA.hub.settings = { ...RA.hub.settings, ...r.body };
    RA.setSave('woz', 'Saved', 'ok');
    $('quick-modal').hidden = true;
    E.quickEdit.focus();
    renderQuick();
  }

  /* ----------------------------------------------------------------- said */
  async function loadSaid() {
    const r = await RA.link.api('GET', 'show/said');
    if (!r.ok) return;
    const typed = arr(r.body.said).map(s => ({ ...obj(s), kind: 'said' }));
    const cuesFired = said.filter(s => s.kind === 'cue');
    said = [...typed, ...cuesFired].sort((a, b) => num(a.at, 0) - num(b.at, 0)).slice(-50);
    renderSaid();
  }

  function addSaid(entry) {
    if (entry.id && said.some(s => s.id === entry.id)) return;
    said.push(entry);
    if (said.length > 50) said.shift();
    renderSaid();
  }

  function renderSaid() {
    E.saidList.textContent = '';
    E.saidEmpty.hidden = said.length > 0;
    said.slice().reverse().forEach(s => {
      const li = el('li');
      const when = s.at ? new Date(num(s.at, 0) * 1000).toTimeString().slice(0, 5) : '';
      const tx = el('span', 'tx', s.kind === 'cue' ? s.label : s.text);
      tx.dir = 'auto';
      li.append(el('span', 'tm', when), tx);
      const again = el('button', '', 'Again');
      again.type = 'button';
      again.title = 'Say it again';
      again.setAttribute('aria-label', `Again: ${s.kind === 'cue' ? s.label : s.text}`);
      again.addEventListener('click', () => (s.kind === 'cue' ? fire(s.cue, false) : say(s.text, 'again')));
      li.append(again);
      E.saidList.append(li);
    });
  }

  /* ------------------------------------------------------------ keyboard */
  function onKey(ev) {
    if (RA.route.tab !== 'woz' || !RA.link || RA.link.state !== 'open') return;
    // While the editor is open the keyboard belongs to it.
    if (editing) {
      if (ev.key === 'Escape') { ev.preventDefault(); closeEditor(); }
      if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); saveEditor(); }
      return;
    }
    if (!$('quick-modal').hidden) { if (ev.key === 'Escape') { $('quick-modal').hidden = true; } return; }
    if (!$('logs-drawer').hidden || !$('details-drawer').hidden) return;
    const t = ev.target;
    if (t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return;
    if (ev.key === 'Escape') { ev.preventDefault(); stopAll(); return; }
    if (ev.key === ' ') {
      ev.preventDefault();                        // always the outlined cue, whatever has focus
      const id = order[pointer];
      if (id) fire(id, true);
      return;
    }
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowRight') { ev.preventDefault(); movePointer(1); return; }
    if (ev.key === 'ArrowUp' || ev.key === 'ArrowLeft') { ev.preventDefault(); movePointer(-1); return; }
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    // Hotkeys by the key itself, so a Hebrew keyboard layout still works.
    const k = ev.key.length === 1 ? ev.key.toLowerCase()
      : '';
    const physical = /^Key([A-Z])$/.exec(ev.code || '');
    const letter = physical ? physical[1].toLowerCase() : (/^Digit(\d)$/.exec(ev.code || '') || [])[1] || k;
    const id = byHotkey[letter] || byHotkey[k];
    if (id) { ev.preventDefault(); fire(id, false); return; }   // a cue hotkey beats a quick save
    const qi = QUICK_KEYS.indexOf(letter);
    if (qi >= 0) {
      ev.preventDefault();
      const line = quickLines()[qi];
      if (line) say(line, 'quick');
      return;
    }
  }

  // A focused button would also click on Space key-up; Space belongs to the outlined cue.
  function onKeyUp(ev) {
    if (ev.key !== ' ' || RA.route.tab !== 'woz' || !RA.link || RA.link.state !== 'open' || editing) return;
    if (!$('quick-modal').hidden || !$('logs-drawer').hidden || !$('details-drawer').hidden) return;
    const t = ev.target;
    if (t && ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName)) return;
    ev.preventDefault();
  }

  /* ---------------------------------------------------------------- link */
  function handle(m) {
    m = obj(m);
    switch (m.event) {
      case 'proxy.open': render(); break;
      case 'proxy.error': case 'proxy.closed': render(); break;
      case 'state.snapshot':
        systemStateChanged(str(m.state));
        if (loadedFor !== key) loadCues();
        renderQuick();
        break;
      case 'state.change': systemStateChanged(str(m.state)); break;
      case 'show.cue.started':
        if (m.has_audio || m.said) startPlaying(m);
        else { E.npLabel.classList.remove('err'); E.npLabel.textContent = str(m.label); E.npText.textContent = ''; endPlaying(); }
        break;
      case 'show.cue.ended': if (m.has_audio || m.said) endPlaying(); break;
      case 'show.stopped':
        endPlaying();
        E.npLabel.classList.remove('err');
        E.npLabel.textContent = 'Stopped';
        E.npText.textContent = '';
        break;
      case 'show.line.ready': prepared.set(str(m.text), true); if (E.sayText.value.trim() === str(m.text)) sayStatus('ready'); break;
      case 'show.said': addSaid({ ...m, kind: 'said' }); break;
      default: break;
    }
  }

  function render() {
    if (!E.view) return;
    const up = RA.renderGate(E.gate, key, 'woz');
    E.robot.textContent = RA.robotName(key);
    E.board.hidden = !up;
    E.view.querySelectorAll('.pnl').forEach(n => { if (!E.gate.contains(n)) n.inert = !up; });
    E.gate.inert = false;
    if (!up) { E.state.textContent = ''; E.convWarning.hidden = true; E.notReady.hidden = true; }
    if (up && loadedFor !== key) loadCues();
  }

  function init() {
    E = {
      view: $('view-woz'), gate: $('woz-gate'), board: $('board'), robot: $('woz-robot'), state: $('woz-state'),
      convWarning: $('conv-warning'), npLabel: $('np-label'), npText: $('np-text'), npBar: $('np-bar'),
      npCount: $('np-countdown'), rebuild: $('rebuild-btn'), sayText: $('say-text'), sayStatus: $('say-status'),
      quickList: $('quick-list'), quickEdit: $('quick-edit'), saidList: $('said-list'), saidEmpty: $('said-empty'),
    };
    E.notReady = el('p', 'sub', 'Cues are off until the robot is ready. STOP always works.');
    E.notReady.hidden = true;
    E.board.before(E.notReady);
    $('stop-btn').addEventListener('click', stopAll);
    $('reload-btn').addEventListener('click', reload);
    E.rebuild.addEventListener('click', rebuild);
    $('ed-save').addEventListener('click', saveEditor);
    $('ed-cancel').addEventListener('click', closeEditor);
    $('ed-delete').addEventListener('click', deleteEditing);
    $('ed-motion-type').addEventListener('change', (ev) => fillMotionNames(ev.target.value, ''));
    $('ed-hotkey').addEventListener('input', () => editorError(hotkeyClash($('ed-hotkey').value)));
    $('ed-modal').addEventListener('click', (ev) => { if (ev.target === $('ed-modal')) closeEditor(); });
    $('say-form').addEventListener('submit', (ev) => { ev.preventDefault(); say(E.sayText.value, 'typed'); });
    E.sayText.addEventListener('input', onSayInput);
    E.sayText.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { ev.preventDefault(); stopAll(); } });
    E.quickEdit.addEventListener('click', openQuick);
    $('quick-form').addEventListener('submit', saveQuick);
    $('quick-cancel').addEventListener('click', () => { $('quick-modal').hidden = true; E.quickEdit.focus(); });
    $('quick-modal').addEventListener('click', (ev) => { if (ev.target === $('quick-modal')) $('quick-modal').hidden = true; });
    document.addEventListener('keydown', onKey);
    document.addEventListener('keyup', onKeyUp);
    RA.onLink((m) => { if (RA.link && RA.link.key === key) handle(m); });
    RA.onHub((kind) => {
      if (kind === 'settings' || kind === 'all') {
        renderQuick();
        if (!RA.saves.woz.text) RA.setSave('woz', 'Saved', 'ok');
      }
      if (RA.route.tab === 'woz') render();
    });
    renderQuick();
    renderSaid();
  }

  function show(k) {
    if (k !== key) {
      key = k;
      loadedFor = '';
      cues = {};
      order = [];
      pointer = 0;
      said = [];
      prepared = new Map();
      E.board.textContent = '';
      E.npLabel.textContent = '—';
      E.npText.textContent = '';
      endPlaying();
      renderSaid();
    }
    render();
  }

  RA.Woz = { init, show, render, handle, systemState: systemStateChanged };
})();
