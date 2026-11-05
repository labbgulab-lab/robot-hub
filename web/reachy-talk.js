/* Reachy app, Talk tab: one Reachy running its own app (reachy_chat on the
 * robot), reached through the hub's proxy (/api/reachy/<key>/..., the relay
 * /ws/reachy/<key>). This is today's reachy_chat dashboard in the lab style:
 * the robot, how it talks (backend picker), its character (persona), the
 * conversation with live captions, and the event log.
 *
 * Also here: the "gate" Talk and Wizard of Oz share while the robot's app is
 * not up (Connect, Start, take over, held by the Group).
 */
'use strict';

(function () {
  const { $, el, str, num, obj, arr, fillOptions } = RA;

  const STATE_LABEL = {
    STARTING: 'Starting…', IDLE_BREATHING: 'Idle', CONVERSATION_RUNNING: 'In conversation',
    STOPPED: 'Stopped', SHUTTING_DOWN: 'Shutting down', ERROR: 'Error',
  };
  const STATE_PILL = {
    STARTING: 'p-busy', IDLE_BREATHING: 'p-run', CONVERSATION_RUNNING: 'p-conn',
    STOPPED: 'p-off', SHUTTING_DOWN: 'p-warn', ERROR: 'p-lost',
  };
  const SUB_CLASS = { LISTENING: 'listen', THINKING: 'think', SPEAKING: 'speak' };
  const END_REASON = {
    user: 'Conversation ended.', end_phrase: 'Conversation ended: the person said goodbye.',
    cancelled: 'Conversation ended: it was stopped.', crash: 'The conversation stopped with an error. See the event log.',
  };
  const PERSONA_MAX = 1500;

  let E = {};
  let key = '';
  let current = 'STARTING';        // reachy_chat's system state
  let robotLink = { connected: null, ip: '', daemon: '' };
  let identity = {};
  let persona = {};
  let personaDirty = false;
  let backend = null;
  let elVoicesLoaded = false;
  let startError = '';             // a refused start, as a sentence
  let systemError = '';            // why the system stopped (startup fatal)
  let systemBusy = '';             // 'start' | 'stop'
  let ending = false;
  let starting = false;
  let timerTurn = null;
  let timerStart = null;
  let timerInterval = 0;
  let convId = '';
  let ended = null;                // {reason, summary}
  let logLines = [];
  let partial = { robot: null, user: null };   // live caption bubbles
  let lastTurn = 0;
  const gestures = new Map();      // turn -> gesture name
  let volumeTimer = 0;
  let missedBeats = 0;

  /* ----------------------------------------------------------- the gate */
  // While the robot's app is not up: what to press, in one place.
  const launching = new Map();     // key -> started at (ms)
  const takeover = new Map();      // key -> sentence (IN_USE or a conflict)
  const launchErr = new Map();     // key -> sentence

  async function connectRobot(k) {
    launchErr.delete(k);
    const r = await RA.post(`/api/robots/${encodeURIComponent(k)}/connect`);
    if (!r.ok) launchErr.set(k, `Couldn't connect: ${RA.errorText(r)}`);
    RA.refreshGates();
  }

  async function launchRobot(k, override) {
    launching.set(k, Date.now());
    launchErr.delete(k);
    takeover.delete(k);
    RA.refreshGates();
    const r = await RA.post(`/api/robots/${encodeURIComponent(k)}/${override ? 'override' : 'launch'}`);
    launching.delete(k);
    const b = r.body;
    if (r.ok && b.ok !== false) {
      if (RA.link && RA.link.key === k) { RA.link.lastRetry = 0; RA.link.retryNow(); }
    } else if (b.code === 'IN_USE' || b.conflict) {
      takeover.set(k, str(b.error) || 'Another app is using this robot.');
    } else if (b.code === 'CONNECT_FIRST') {
      launchErr.set(k, 'Connect it first.');
    } else {
      launchErr.set(k, str(b.error) || "The robot's app didn't start.");
    }
    RA.refreshGates();
  }

  // Draws the gate into `box`; true when the robot's app is up (no gate).
  RA.renderGate = (box, k, tab) => {
    const link = RA.link && RA.link.key === k ? RA.link : null;
    if (link && link.state === 'open') { box.hidden = true; box.textContent = ''; return true; }
    box.hidden = false;
    box.textContent = '';
    const r = RA.robot(k);
    const name = RA.robotName(k);
    const what = tab === 'woz' ? 'Wizard of Oz' : 'Talk';
    if (!r) {
      if (!RA.hub.loaded) { box.append(RA.el('p', 'sub', 'Looking for the robot…')); return false; }
      box.append(RA.note('warn', 'wifi', `${name} isn't nearby.`,
        [RA.button('Pick another Reachy', 'btn-dark btn-sm', () => RA.go(tab, ''))]));
      return false;
    }
    if (RA.Group && RA.Group.holds(k)) {
      box.append(RA.note('warn', 'users', `${name} is in a Group conversation. Disconnect it there first.`,
        [RA.button('Go to Group', 'btn-dark btn-sm', () => RA.go('group'))]));
      return false;
    }
    if (launching.has(k) || r.launching_since) {
      const since = launching.get(k) || num(r.launching_since, 0) * 1000;
      const secs = Math.max(0, Math.round((Date.now() - since) / 1000));
      const n = RA.el('p', 'note');
      const sp = RA.el('span', 'spin'); sp.style.marginTop = '3px';
      n.append(sp, RA.el('span', '', `Starting ${name}'s app… ${secs} s`));
      box.append(n);
      return false;
    }
    if (takeover.has(k)) {
      box.append(RA.note('warn', 'alert', takeover.get(k), [
        RA.button('Take over', 'btn-dark btn-sm', () => launchRobot(k, true)),
        RA.button('Cancel', 'btn-ghost btn-sm', () => { takeover.delete(k); RA.refreshGates(); }),
      ]));
      return false;
    }
    if (launchErr.has(k)) box.append(RA.note('err', 'alert', launchErr.get(k)));
    if (r.state === 'CONNECTING') {
      box.append(RA.pill('p-busy', 'Connecting…', true));
      return false;
    }
    if (!RA.CONNECTED.includes(r.state)) {
      if (r.connect_error) box.append(RA.note('err', 'alert', `Couldn't connect: ${r.connect_error}`));
      const b = RA.button('Connect', 'btn-primary', () => connectRobot(k), 'link');
      box.append(RA.el('p', 'sub', `${name} isn't connected to Robot Hub yet.`), b);
      return false;
    }
    if (r.in_use_by) box.append(RA.note('warn', 'alert', `Another laptop (${r.in_use_by}) is using ${name}.`));
    if (r.state === 'RUNNING' && link) {
      // The hub says the app runs: the relay is (re)connecting by itself.
      const n = RA.el('p', 'note');
      const sp = RA.el('span', 'spin'); sp.style.marginTop = '3px';
      n.append(sp, RA.el('span', '', link.state === 'connecting' ? `Opening ${name}'s app…`
        : `Reconnecting to ${name}'s app… If it stopped, start it again.`));
      box.append(n);
      if (link.state === 'connecting') return false;
    }
    if (r.launch_error && !launchErr.has(k)) box.append(RA.note('err', 'alert', `Last start failed: ${r.launch_error}`));
    const b = RA.button(`Start ${what}`, 'btn-primary', () => launchRobot(k, false), 'play');
    b.title = `Starts ${name}'s own app on the robot. The first time it installs itself, which takes a few minutes.`;
    box.append(b);
    return false;
  };
  RA.refreshGates = () => { if (RA.Talk) RA.Talk.render(); if (RA.Woz) RA.Woz.render(); };
  setInterval(() => { if (launching.size || RA.reachys().some(r => r.launching_since)) RA.refreshGates(); }, 1000);

  /* --------------------------------------------------------- rendering */
  function setSwitch(btn, on) {
    btn.classList.toggle('on', !!on);
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  function msg(box, text, tone, icon) {
    box.textContent = '';
    if (!text) return;
    if (tone === 'err' || tone === 'warn') box.append(RA.note(tone, icon || 'alert', text));
    else {
      const p = RA.el('p', `sub${tone === 'ok' ? ' okline' : ''}`);
      if (icon) p.append(RA.icNode(icon, 14));
      p.append(document.createTextNode(text));
      box.append(p);
    }
  }

  function render() {
    if (!E.view) return;
    const up = RA.renderGate(E.gate, key, 'talk');
    const r = RA.robot(key);
    E.robotName.textContent = RA.robotName(key);
    if (RA.route.tab === 'talk' && RA.route.key) document.title = `${RA.robotName(key)}: Talk`;
    E.view.querySelectorAll('.talk-needs, .talk-mid').forEach(n => {
      n.classList.toggle('dimmed', !up);
      n.inert = !up;
    });
    E.systemButtons.hidden = !up;
    E.badges.hidden = !up || RA.route.tab !== 'talk';
    // The robot's link and address.
    const conn = up ? robotLink.connected : (r ? RA.CONNECTED.includes(r.state) : null);
    E.robotConn.className = conn === null ? 'sub' : (conn ? 'okline' : 'warnline');
    E.robotConn.lastChild.textContent = conn === null ? 'Unknown' : (conn ? 'Connected' : (up ? 'Disconnected' : 'Not connected'));
    E.robotConn.style.color = conn === false ? (up ? '#B91C1C' : '#6B635A') : '';
    E.robotIp.lastChild.textContent = (up && robotLink.ip) || (r && r.address) || '—';
    // State pill and substate.
    E.systemPill.textContent = '';
    if (up) {
      E.systemPill.append(RA.pill(STATE_PILL[current] || 'p-off', STATE_LABEL[current] || current,
        current === 'STARTING' || current === 'SHUTTING_DOWN'));
    } else if (r) {
      E.systemPill.append(RA.pill(RA.STATUS_PILL[r.state] || 'p-off', RA.STATUS_TEXT[r.state] || r.state, r.state === 'CONNECTING'));
    }
    if (!up || current !== 'CONVERSATION_RUNNING') E.substate.hidden = true;
    E.daemon.textContent = up ? (robotLink.connected === false
      ? `Daemon ${robotLink.daemon || 'unreachable'}${missedBeats >= 2 ? ' · 2 missed checks' : ''}`
      : `Daemon ${robotLink.daemon || 'unknown'}`) : '';
    renderSystemNote(up);
    renderButtons(up);
    renderBackend();
    renderPersona();
  }

  function renderSystemNote(up) {
    E.systemNote.textContent = '';
    if (!up) return;
    if (robotLink.connected === false && current !== 'STOPPED') {
      E.systemNote.append(RA.note('warn', 'wifi', `${RA.robotName(key)} stopped answering. It reconnects by itself when it's back.`));
    }
    if (current === 'STOPPED' && systemError) {
      E.systemNote.append(RA.note('err', 'alert', `Couldn't start: ${systemError}`, [
        RA.button('See log', 'btn-ghost btn-sm', () => { E.log.scrollTop = E.log.scrollHeight; E.copyLogs.focus(); }),
      ]));
    } else if (current === 'ERROR' && systemError) {
      E.systemNote.append(RA.note('err', 'alert', systemError));
    }
  }

  function renderButtons(up) {
    E.startSystem.disabled = !up || current !== 'STOPPED' || !!systemBusy;
    E.stopSystem.disabled = !up || !(current === 'IDLE_BREATHING' || current === 'CONVERSATION_RUNNING') || !!systemBusy;
    E.startSystem.classList.toggle('busy', systemBusy === 'start');
    E.startSystem.classList.toggle('btn-primary', up && current === 'STOPPED');
    E.startSystem.classList.toggle('btn-quiet', !(up && current === 'STOPPED'));
    renderChatEmpty(up);
    const b = E.actionBtn;
    const label = b.querySelector('span');
    const icon = b.querySelector('.icon');
    if (current === 'CONVERSATION_RUNNING') {
      b.className = `btn btn-stop${ending ? ' busy' : ''}`;
      label.textContent = ending ? 'Ending… the robot finishes its line' : 'End conversation';
      b.disabled = !up || ending;
      icon.replaceWith(RA.icNode('stop', 18));
      E.endHint.textContent = ending ? 'Up to 40 s.' : 'Or the person says "goodbye" or "להתראות".';
    } else {
      b.className = `btn btn-primary${starting ? ' busy' : ''}`;
      label.textContent = 'Start conversation';
      b.disabled = !up || current !== 'IDLE_BREATHING' || starting;
      icon.replaceWith(RA.icNode('play', 18));
      E.endHint.textContent = 'The robot speaks first. The person ends it by saying "goodbye" or "להתראות".';
    }
  }

  /* ----------------------------------------------------------- backend */
  function renderBackend() {
    const b = backend;
    if (!b || !arr(b.brains).length) return;
    fillOptions(E.brain, b.brains.map(x => [x.id, x.label + (x.key_ok ? '' : ' (no key)')]), b.brain);
    fillOptions(E.language, arr(b.languages).map(x => [x.id, x.label]), b.language);
    const elv = obj(b.elevenlabs);
    fillOptions(E.voice, [['', `Default (${b.default_voice || "provider's"})`], ...arr(b.voices).map(v => [v, v])], b.voice || '');
    setSwitch(E.el, !!elv.enabled);
    const showVoice = !elv.enabled && arr(b.voices).length > 0;
    E.voice.hidden = !showVoice;
    E.voiceLabel.hidden = !showVoice;
    E.elRow.hidden = !elv.enabled;
    E.elWarning.textContent = '';
    E.elWarning.hidden = !(b.el_not_recommended && elv.enabled);
    if (!E.elWarning.hidden) E.elWarning.append(RA.note('err', 'alert', 'ElevenLabs stutters with GPT-Live-1. Use it with Gemini.'));
    const vis = obj(b.vision);
    setSwitch(E.vision, !!vis.enabled);
    E.visionNote.hidden = !vis.enabled;
    const note = !vis.enabled ? '' : vis.available ? `${RA.cap(str(vis.source))} · ${str(vis.how)}`
      : `No camera here: ${str(vis.source) || "the app isn't running on the robot"}.`;
    E.visionNote.lastChild.textContent = note;
    E.visionNote.title = note;
    E.visionNote.style.color = vis.enabled && !vis.available ? '#8A3B00' : '';
    if (elv.enabled && !elVoicesLoaded) loadElVoices(false);
    else if (elv.enabled) E.elVoice.value = str(elv.voice_id);
    describeBackend();
  }

  // The honest line under the picker: what the next conversation will be,
  // and anything that would stop it.
  function describeBackend(extra) {
    const b = backend;
    if (!b) return;
    if (startError) { msg(E.backendMsg, startError, 'err', 'key'); return; }
    if (extra) { msg(E.backendMsg, extra, 'err'); return; }
    const brain = arr(b.brains).find(x => x.id === b.brain) || {};
    const elv = obj(b.elevenlabs);
    const problems = [];
    if (!brain.key_ok) problems.push(brain.key_error || 'No key for this brain yet. Add one in Settings.');
    if (elv.enabled && !elv.key_ok) problems.push(`ElevenLabs: ${elv.key_error || 'no key'}`);
    E.backendMsg.textContent = '';
    if (problems.length) {
      problems.forEach(p => { const line = RA.el('p', 'sub', p); line.style.color = '#B91C1C'; E.backendMsg.append(line); });
      return;
    }
    if (brain.note) E.backendMsg.append(RA.note('warn', 'info', 'Hebrew is untested on GPT-Live. Its gestures come a moment late.'));
    if (current === 'CONVERSATION_RUNNING') {
      const p = RA.el('p', 'sub');
      p.append(RA.icNode('clock', 14), 'Applies to the next conversation.');
      E.backendMsg.append(p);
    }
  }

  async function loadElVoices(refresh) {
    const r = await RA.link.api('GET', `backend/elevenlabs/voices${refresh ? '?refresh=true' : ''}`);
    if (!r.ok) { describeBackend("Couldn't load the ElevenLabs voices."); return; }
    const voices = arr(r.body.voices);
    const cur = obj(backend && backend.elevenlabs);
    fillOptions(E.elVoice, [['', voices.length ? 'First voice in the account' : 'No voices (check the key)'],
      ...voices.map(v => [v.voice_id, v.name + (v.language ? ` (${v.language})` : '')])], str(cur.voice_id));
    elVoicesLoaded = voices.length > 0;
  }

  async function sendBackend(body) {
    if (!RA.link) return;
    const r = await RA.link.api('PUT', 'backend', body);
    if (!r.ok) {
      describeBackend(r.status === 409 ? `${RA.robotName(key)}'s app is not running.` : `Couldn't change that: ${RA.errorText(r)}`);
      RA.setSave('talk', 'Not saved', 'problem');
      renderBackend();
      return;
    }
    startError = '';
    backend = r.body;
    RA.setSave('talk', 'Saved', 'ok');
    renderBackend();
  }

  /* ----------------------------------------------------------- persona */
  function renderPersona() {
    const p = persona;
    if (!p || !('enabled' in p)) return;
    setSwitch(E.personaToggle, !!p.enabled);
    E.personaPanel.hidden = !p.enabled;
    if (!personaDirty) {
      RA.setValue(E.personaText, p.overlay || '');
      fillOptions(E.personaPreset, [['', 'Write my own'], ...arr(p.presets).map(x => [x.id, x.label || x.id])], p.preset_id || '');
      fillOptions(E.personaVoice, [['', `Default voice (${p.default_voice || '—'})`], ...arr(p.voices).map(v => [v, v])], p.voice || '');
    }
    if (p.active) {
      const what = p.preset_id ? (arr(p.presets).find(x => x.id === p.preset_id) || {}).label || p.preset_id : 'Custom';
      E.personaSummary.textContent = `In character: ${what}`;
      E.personaSummary.style.cssText = 'color: #15803D; font-weight: 600; font-size: 14px;';
    } else {
      E.personaSummary.textContent = p.enabled ? 'Switched on, but nothing written yet' : 'Base persona';
      E.personaSummary.style.cssText = 'font-size: 14px;';
    }
    E.personaHint.textContent = current === 'CONVERSATION_RUNNING' ? 'Applies to the next conversation.' : '';
    updateCount(p.max_chars);
  }

  function updateCount(max) {
    const limit = max || persona.max_chars || PERSONA_MAX;
    const n = E.personaText.value.length;
    E.personaCount.textContent = n ? `${n.toLocaleString('en-US')} / ${limit.toLocaleString('en-US')}` : '';
    E.personaCount.className = `cnt${n > limit ? ' over' : ''}`;
  }

  let personaMsgTimer = 0;
  function personaMessage(text, ok) {
    E.personaMsg.textContent = text || '';
    E.personaMsg.style.color = ok ? '#15803D' : '#B91C1C';
    clearTimeout(personaMsgTimer);
    if (text) personaMsgTimer = setTimeout(() => { if (E.personaMsg.textContent === text) E.personaMsg.textContent = ''; }, 4000);
  }

  async function sendPersona(body) {
    if (!RA.link) return null;
    const r = await RA.link.api('PUT', 'persona', body);
    if (!r.ok) {
      personaMessage(r.status === 0 ? "Couldn't reach the robot." : (r.body.detail || "Couldn't save that."), false);
      RA.setSave('talk', 'Not saved', 'problem');
      return null;
    }
    personaDirty = false;
    persona = r.body;
    RA.setSave('talk', 'Saved', 'ok');
    renderPersona();
    return r.body;
  }

  /* ------------------------------------------------------- conversation */
  function stick(node) { return node.scrollHeight - node.scrollTop - node.clientHeight < 40; }
  function scrollIf(node, was) { if (was) node.scrollTop = node.scrollHeight; }

  function renderChatEmpty(up) {
    let empty = E.chat.querySelector('.empty');
    const has = Array.from(E.chat.children).some(c => !c.classList.contains('empty'));
    if (has || !up) { if (empty) empty.remove(); return; }
    if (!empty) {
      empty = RA.el('p', 'empty');
      E.chat.append(empty);
    }
    empty.textContent = current === 'IDLE_BREATHING' ? 'No conversation yet. Press Start conversation.' : 'The robot is not ready for a conversation yet.';
  }

  function clearChat() {
    E.chat.textContent = '';
    partial = { robot: null, user: null };
    gestures.clear();
  }

  function bubble(role, turn, text) {
    const b = RA.el('div', `bub ${role === 'user' ? 'person' : 'robot'}`);
    b.dataset.turn = String(turn);
    const tx = RA.el('div', 'tx');
    tx.dir = 'auto';
    if (text) tx.textContent = text;
    else tx.append(RA.el('i', 'muted', '(no transcript)'));
    const meta = RA.el('div', 'meta');
    meta.append(RA.el('span', '', `Turn ${turn}`));
    b.append(tx, meta);
    if (role === 'robot' && gestures.has(String(turn))) meta.append(RA.el('span', 'mtag', gestures.get(String(turn))));
    return b;
  }

  function appendLine(role, turn, text) {
    const was = stick(E.chat);
    renderChatEmpty(false);
    // The live caption of this side is replaced by the final line.
    const live = partial[role];
    if (live) { live.remove(); partial[role] = null; }
    const b = bubble(role, turn, text);
    E.chat.append(b);
    scrollIf(E.chat, was);
  }

  function appendSys(text, err) {
    const was = stick(E.chat);
    renderChatEmpty(false);
    const line = RA.el('span', `sys${err ? ' err' : ''}`, text);
    line.dir = 'auto';
    E.chat.append(line);
    scrollIf(E.chat, was);
  }

  function appendAborted(turn, reason) {
    appendSys(reason === 'gemini_silent' ? `Turn ${turn} aborted: Gemini went silent` : `Turn ${turn} aborted`, true);
  }

  // conversation.partial: the whole turn so far (replace, don't append).
  function onPartial(m) {
    const who = m.who === 'user' ? 'user' : 'robot';
    const turn = m.turn_id !== undefined ? m.turn_id : m.turn;
    const text = str(m.text);
    if (!text) return;
    const was = stick(E.chat);
    let b = partial[who];
    renderChatEmpty(false);
    if (!b || b.dataset.turn !== String(turn)) {
      if (b) b.remove();
      b = RA.el('div', `bub ${who === 'user' ? 'person' : 'robot'} saying`);
      b.dataset.turn = String(turn);
      b.setAttribute('aria-live', 'polite');
      const tx = RA.el('div', 'tx');
      tx.dir = 'auto';
      const meta = RA.el('div', 'meta', `Turn ${turn} · ${who === 'user' ? 'listening' : 'speaking now'}`);
      b.append(tx, meta);
      partial[who] = b;
      E.chat.append(b);
    }
    const tx = b.querySelector('.tx');
    tx.textContent = text;
    const cur = RA.el('span', 'cur', '▌');
    cur.setAttribute('aria-hidden', 'true');
    tx.append(cur);
    if (who === 'robot' && gestures.has(String(turn)) && !b.querySelector('.mtag')) {
      b.querySelector('.meta').append(RA.el('span', 'mtag', gestures.get(String(turn))));
    }
    scrollIf(E.chat, was);
  }

  // The gesture the robot played, read from its tool log line.
  const GESTURE_RE = /\[tool\]\s+(play_emotion|dance|move_head)\((?:name|direction)=([^,)]+)[^)]*\)\s*->\s*queued/;
  function noteGesture(text) {
    const m = GESTURE_RE.exec(text);
    if (!m) return;
    const name = m[1] === 'move_head' ? `look ${m[2]}` : (m[1] === 'dance' ? `dance: ${m[2]}` : m[2]);
    const turn = String(lastTurn);
    if (gestures.has(turn)) return;
    gestures.set(turn, name);
    E.chat.querySelectorAll(`.bub.robot[data-turn="${CSS.escape(turn)}"] .meta`).forEach(meta => {
      if (!meta.querySelector('.mtag')) meta.append(RA.el('span', 'mtag', name));
    });
  }

  function setConvHeader(id) {
    convId = id || '';
    E.convId.textContent = id || '—';
  }

  function resetTimer() {
    timerStart = Date.now();
    E.turnDuration.textContent = '0:00';
    if (!timerInterval) timerInterval = setInterval(tickTimer, 1000);
  }
  function tickTimer() { if (timerStart != null) E.turnDuration.textContent = RA.clock((Date.now() - timerStart) / 1000); }
  function freezeTimer() { clearInterval(timerInterval); timerInterval = 0; }
  function clearTimer() { freezeTimer(); timerTurn = null; timerStart = null; E.turnDuration.textContent = '0:00'; }

  function renderEnded() {
    E.ended.textContent = '';
    if (!ended || current === 'CONVERSATION_RUNNING') return;
    const s = obj(ended.summary);
    const tc = obj(s.turn_count);
    const lat = obj(obj(s.latency).gemini_first_chunk_ms);
    const parts = [];
    if (convId) parts.push(`Session ${convId}`);
    if (tc.total !== undefined) parts.push(RA.plural(num(tc.total, 0), 'turn'));
    if (lat.median !== undefined) parts.push(`answers ${(num(lat.median, 0) / 1000).toFixed(1)} s on average`);
    if (num(tc.aborted, 0)) parts.push(`${tc.aborted} aborted`);
    const crash = ended.reason === 'crash';
    E.ended.append(RA.note(crash ? 'err' : 'ok', crash ? 'alert' : 'check', END_REASON[ended.reason] || 'Conversation ended.'));
    if (parts.length) E.ended.append(RA.el('p', 'sub', parts.join(' · ')));
  }

  /* --------------------------------------------------------------- log */
  function pushLog(text, level) {
    logLines.push(text);
    if (logLines.length > 1000) logLines.shift();
    const was = stick(E.log);
    const div = RA.el('div', { WARNING: 'w', ERROR: 'e', CRITICAL: 'e', DEBUG: 'd' }[level] || '');
    const m = /^(\d{2}:\d{2}:\d{2}\.\d{3})(.*)$/s.exec(text);
    if (m) div.append(RA.el('span', 't', m[1]), document.createTextNode(m[2]));
    else div.textContent = text;
    E.log.append(div);
    while (E.log.childElementCount > 1000) E.log.firstChild.remove();
    scrollIf(E.log, was);
  }
  function nowTs() {
    const d = new Date();
    const p = (n, w) => String(n).padStart(w, '0');
    return `${p(d.getHours(), 2)}:${p(d.getMinutes(), 2)}:${p(d.getSeconds(), 2)}.${p(d.getMilliseconds(), 3)}`;
  }
  function logLine(level, logger, text, ts) {
    pushLog(`${ts || nowTs()} ${String(level).padEnd(5)} ${logger}  ${text}`, level);
  }
  const LEVEL_RE = /^\d{2}:\d{2}:\d{2}\.\d{3}\s+(\w+)\s/;

  /* ----------------------------------------------------------- events */
  function setState(state) {
    current = state;
    if (state !== 'CONVERSATION_RUNNING') { ending = false; E.substate.hidden = true; }
    if (['IDLE_BREATHING', 'STOPPED', 'ERROR', 'SHUTTING_DOWN'].includes(state)) freezeTimer();
    if (state === 'IDLE_BREATHING' || state === 'CONVERSATION_RUNNING') systemBusy = '';
    if (state !== 'STOPPED' && state !== 'ERROR') systemError = state === 'STARTING' ? systemError : '';
    E.chat.classList.toggle('dimmed', false);
    render();
    renderEnded();
  }

  function setIdentity(info) {
    identity = obj(info);
    const provider = obj(identity.provider);
    const k = obj(identity.key);
    E.brainBadge.textContent = provider.display_name || '…';
    E.brainBadge.className = `badge${provider.implemented === false ? ' amber' : ''}`;
    E.keyBadge.textContent = '';
    if (k.error) {
      E.keyBadge.className = 'badge bad';
      E.keyBadge.textContent = 'No key';
      E.keyBadge.title = k.error;
    } else if (k.label) {
      E.keyBadge.className = 'badge';
      E.keyBadge.append(RA.el('span', 'mono', `${k.label} ··${k.key_tail || ''}`));
      E.keyBadge.title = 'The key this brain uses (label and last four only).';
    } else {
      E.keyBadge.className = 'badge';
      E.keyBadge.append(RA.el('span', 'mono', '…'));
    }
  }

  function showVolume(v) {
    v = obj(v);
    if (v.level === undefined || v.level === null) return;
    E.volume.max = String(v.max || 150);
    if (document.activeElement !== E.volume) E.volume.value = String(v.level);
    E.volumeValue.textContent = `${v.level}%`;
    E.volumeValue.className = num(v.level, 0) > 100 ? 'boost' : '';
  }

  function handle(m) {
    m = obj(m);
    switch (m.event) {
      case 'proxy.open':
        logLine('INFO', 'hub', `connected to ${RA.robotName(key)}'s app`);
        loadVolume();
        render();
        break;
      case 'proxy.error':
      case 'proxy.closed':
        render();
        break;
      case 'state.snapshot': {
        robotLink = { connected: obj(m.robot).connected, ip: str(obj(m.robot).ip), daemon: str(obj(m.robot).daemon_status) };
        setIdentity(m.identity);
        persona = obj(m.persona);
        backend = obj(m.backend);
        elVoicesLoaded = false;
        systemError = str(m.error_message);
        E.log.textContent = '';
        logLines = [];
        arr(m.recent_log).forEach(l => { const mm = LEVEL_RE.exec(l); pushLog(str(l), mm ? mm[1] : 'INFO'); });
        E.log.scrollTop = E.log.scrollHeight;
        clearChat();
        const conv = m.conversation ? obj(m.conversation) : null;
        setConvHeader(conv ? conv.id : '');
        E.turns.textContent = conv ? String(num(conv.turn_count, 0)) : '0';
        if (conv && conv.backend) appendSys(str(conv.backend));
        arr(m.transcript).forEach(t => {
          t = obj(t);
          lastTurn = num(t.turn_id, lastTurn);
          if (t.role === 'aborted') appendAborted(t.turn_id, t.reason);
          else if (t.role === 'user' || t.role === 'robot') appendLine(t.role, t.turn_id, t.text);
        });
        setState(str(m.state) || 'STARTING');
        if (!RA.saves.talk.text) RA.setSave('talk', 'Saved', 'ok');
        break;
      }
      case 'state.change': setState(str(m.state)); break;
      case 'robot.status':
        robotLink = { ...robotLink, connected: m.connected, ip: str(m.ip) || robotLink.ip, daemon: str(m.daemon_status) || robotLink.daemon };
        if (m.connected) missedBeats = 0;
        render();
        break;
      case 'robot.heartbeat':
        if (m.ok) { missedBeats = 0; if (m.daemon_status) robotLink.daemon = str(m.daemon_status); }
        else { missedBeats += 1; robotLink.daemon = 'unreachable'; }
        render();
        break;
      case 'conversation.started':
        clearChat();
        clearTimer();
        ended = null;
        renderEnded();
        startError = '';
        setConvHeader(str(m.id));
        E.turns.textContent = '0';
        lastTurn = 0;
        if (m.backend) {
          appendSys(str(m.backend));
          logLine('INFO', 'client', `conversation on ${m.backend}`);
        }
        break;
      case 'conversation.ended':
        logLine('INFO', 'client', `conversation ended (${m.reason})`);
        freezeTimer();
        ending = false;
        ended = { reason: str(m.reason), summary: obj(m.summary) };
        ['robot', 'user'].forEach(w => { if (partial[w]) { partial[w].classList.remove('saying'); partial[w].querySelector('.cur')?.remove(); partial[w] = null; } });
        renderEnded();
        render();
        break;
      case 'transcript.user': lastTurn = num(m.turn_id, lastTurn); appendLine('user', m.turn_id, str(m.text)); break;
      case 'transcript.robot': lastTurn = num(m.turn_id, lastTurn); appendLine('robot', m.turn_id, str(m.text)); break;
      case 'conversation.partial': onPartial(m); break;
      case 'turn.substate':
        if (current === 'CONVERSATION_RUNNING') {
          E.substate.textContent = str(m.state);
          E.substate.className = `sub-badge ${SUB_CLASS[m.state] || ''}`;
          E.substate.hidden = false;
        }
        lastTurn = num(m.turn_id, lastTurn);
        E.turns.textContent = String(m.turn_id);
        if (m.state === 'LISTENING' && m.turn_id !== timerTurn) { timerTurn = m.turn_id; resetTimer(); }
        break;
      case 'turn.aborted': appendAborted(m.turn_id, m.reason); break;
      case 'volume.change': showVolume(m); break;
      case 'backend.change': backend = m; renderBackend(); break;
      case 'identity.change': setIdentity(m); break;
      case 'persona.change':
        // Another tab changed it; a half-typed text here is not overwritten.
        persona = m;
        renderPersona();
        break;
      case 'log':
        logLine(m.level, m.logger, str(m.msg), m.ts);
        if (str(m.logger).includes('tools')) noteGesture(str(m.msg));
        break;
      case 'show.cue.started':
        logLine('INFO', 'show', `${m.said ? 'said' : 'cue'}: ${m.said ? str(m.text) : str(m.label)}`);
        break;
      case 'error':
        logLine('ERROR', m.where || 'system', str(m.message));
        if (m.where === 'startup') { systemError = str(m.message); render(); }
        break;
      default: break;
    }
  }

  /* ---------------------------------------------------------- actions */
  // reachy_chat's raw 409/503 start errors, as sentences.
  function startRefusal(r) {
    const b = obj(r.body);
    if (r.status === 409 && b.error === 'already_running') return 'Already talking. End this conversation first.';
    if (r.status === 503) return 'Still starting. Try again in a few seconds.';
    if (r.status === 409 && b.code === 'NOT_RUNNING') return `${RA.robotName(key)}'s app is not running.`;
    if (b.detail) return `Couldn't start: ${b.detail}`;
    return `Couldn't start: ${RA.errorText(r)}`;
  }

  async function startConversation() {
    starting = true;
    render();
    const r = await RA.link.api('POST', 'conversation/start');
    starting = false;
    if (!r.ok) {
      startError = startRefusal(r);
      logLine('ERROR', 'client', `start failed: ${startError}`);
    } else startError = '';
    render();
  }

  async function endConversation() {
    ending = true;
    render();
    const r = await RA.link.api('POST', 'conversation/end');
    if (!r.ok) {
      ending = false;
      logLine('ERROR', 'client', `end failed: ${RA.errorText(r)}`);
      render();
    }
  }

  async function startSystem() {
    systemBusy = 'start';
    render();
    const r = await RA.link.api('POST', 'system/start');
    systemBusy = '';
    if (!r.ok) {
      const why = r.body.error === 'invalid_state' ? `it is ${STATE_LABEL[r.body.state] || r.body.state}` : RA.errorText(r);
      systemError = `Couldn't start the system: ${why}.`;
      logLine('ERROR', 'client', `start system failed: ${why}`);
    }
    render();
  }

  async function stopSystem() {
    systemBusy = 'stop';
    render();
    const r = await RA.link.api('POST', 'system/stop');
    systemBusy = '';
    if (!r.ok) {
      const why = r.body.error === 'invalid_state' ? "it isn't running" : RA.errorText(r);
      E.systemNote.append(RA.note('err', 'alert', `Couldn't stop the system: ${why}.`));
      logLine('ERROR', 'client', `stop system failed: ${why}`);
    }
    render();
  }

  async function loadVolume() {
    if (!RA.link) return;
    const r = await RA.link.api('GET', 'volume');
    if (r.ok) showVolume(r.body);
  }

  function onVolume() {
    const level = Number(E.volume.value);
    E.volumeValue.textContent = `${level}%`;
    E.volumeValue.className = level > 100 ? 'boost' : '';
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(async () => {
      const r = await RA.link.api('PUT', 'volume', { level });
      if (r.ok) showVolume(r.body);
      else RA.toast("The robot didn't take the volume change.", true);
    }, 250);
  }

  async function copyLogs() {
    const text = logLines.join('\n');
    const feedback = (t) => { E.copyStatus.textContent = t; setTimeout(() => { E.copyStatus.textContent = ''; }, 2500); };
    if (!text) { feedback('Nothing to copy'); return; }
    feedback(await RA.copyText(text) ? 'Copied' : 'Copy failed: select the log and press Ctrl+C.');
  }

  /* ---------------------------------------------------------- details */
  async function openDetails() {
    const r = await RA.get(`/api/robots/${encodeURIComponent(key)}`);
    const card = r.ok ? r.body : obj(RA.robot(key));
    $('details-title').textContent = RA.robotName(key);
    $('details-sub').textContent = RA.STATUS_TEXT[card.state] || str(card.state);
    const facts = obj(card.facts);
    const rows = [
      ['Address', card.address || '—'],
      ['Robot software', facts.robot_software || '—'],
      ['Microphone', facts.mic || card.mic || '—'],
      ['App', card.system_url || (RA.link && RA.link.state === 'open' ? 'running' : 'not running')],
      ['Holds on this laptop', arr(facts.holds).join(', ') || 'nothing'],
      ['Last seen', facts.seen_ago !== undefined ? (facts.seen_ago < 10 ? 'now' : `${facts.seen_ago} s ago`) : '—'],
    ];
    if (card.in_use_by) rows.push(['In use by', card.in_use_by]);
    const dl = $('details-facts');
    dl.textContent = '';
    rows.forEach(([k, v]) => { dl.append(RA.el('dt', '', k), RA.el('dd', '', str(v))); });
    $('details-copy').onclick = async () => {
      const ok = await RA.copyText([RA.robotName(key), ...rows.map(([k, v]) => `${k}: ${v}`)].join('\n'));
      RA.toast(ok ? 'Copied' : "Couldn't copy.", !ok);
    };
    $('details-disconnect').onclick = async () => {
      const res = await RA.post(`/api/robots/${encodeURIComponent(key)}/disconnect`);
      RA.toast(res.ok ? `${RA.robotName(key)} disconnected.` : `Couldn't disconnect: ${RA.errorText(res)}`, !res.ok);
      RA.closeDrawer('details-drawer');
    };
    const staff = !!RA.hub.settings.staff_tools;
    $('wifi-sec').hidden = !staff;
    $('wifi-msg').textContent = '';
    RA.openDrawer('details-drawer');
    if (staff) loadWifi();
  }

  async function loadWifi() {
    const known = $('wifi-known');
    known.textContent = '';
    if (!RA.link || RA.link.state !== 'open') {
      wifiMsg('err', `WiFi can only be set while ${RA.robotName(key)}'s app runs. Start it first.`);
      $('wifi-save').disabled = true;
      return;
    }
    const r = await RA.link.api('GET', 'wifi');
    if (!r.ok) { wifiMsg('err', `Couldn't ask the robot: ${RA.errorText(r)}`); return; }
    if (!r.body.available) {
      wifiMsg('err', r.body.reason === 'only when reachy_chat runs on the robot'
        ? 'WiFi can only be set when the app runs on the robot.' : str(r.body.reason) || 'WiFi settings are not available here.');
      $('wifi-save').disabled = true;
    } else $('wifi-save').disabled = false;
    const nets = arr(r.body.networks);
    known.append('Knows: ');
    if (!nets.length) known.append('nothing yet');
    nets.forEach((n, i) => {
      n = obj(n);
      const name = RA.el(n.active ? 'b' : 'span', '', str(n.ssid || n.name));
      if (n.active) name.style.color = '#1C1917';
      known.append(name);
      if (n.active) known.append(' (connected now)');
      else if (n.setup) known.append(' (its own setup network)');
      else if (n.autoconnect === false) known.append(" (won't join by itself)");
      if (i < nets.length - 1) known.append(' · ');
    });
  }
  function wifiMsg(kind, text) {
    const box = $('wifi-msg');
    box.textContent = '';
    if (!text) return;
    if (kind === 'busy') {
      const n = RA.el('p', 'note');
      const sp = RA.el('span', 'spin'); sp.style.marginTop = '3px';
      n.append(sp, RA.el('span', '', text));
      box.append(n);
    } else box.append(RA.note(kind, kind === 'ok' ? 'check' : 'alert', text));
  }
  async function saveWifi() {
    const ssid = $('wifi-ssid').value.trim();
    const password = $('wifi-pass').value;
    if (!ssid) { wifiMsg('warn', "Type the hotspot's name first."); return; }
    if (password.length < 8) { wifiMsg('warn', 'A WiFi password has at least 8 characters.'); return; }
    $('wifi-save').disabled = true;
    wifiMsg('busy', 'Saving on the robot…');
    const r = await RA.link.api('POST', 'wifi', { ssid, password });
    $('wifi-save').disabled = false;
    if (!r.ok) { wifiMsg('err', r.status ? (str(r.body.error) || `Failed (${r.status}).`) : `Couldn't reach the robot: ${RA.errorText(r)}`); return; }
    $('wifi-pass').value = '';
    wifiMsg('ok', `"${ssid}" saved. The robot stays on its current WiFi for now; turn that one off and it moves over within a minute.`);
    loadWifi();
  }

  /* -------------------------------------------------------------- init */
  function init() {
    E = {
      view: $('view-talk'), gate: $('talk-gate'), robotName: $('robot-name'), robotConn: $('robot-conn'),
      robotIp: $('robot-ip'), systemPill: $('system-pill'), substate: $('substate-badge'), daemon: $('robot-daemon'),
      systemNote: $('system-note'), systemButtons: $('system-buttons'),
      startSystem: $('start-system-btn'), stopSystem: $('stop-system-btn'),
      brain: $('backend-brain'), language: $('backend-language'), voice: $('backend-voice'), voiceLabel: $('backend-voice-label'),
      el: $('backend-el'), elRow: $('el-voice-row'), elVoice: $('backend-el-voice'), elWarning: $('el-warning'),
      vision: $('backend-vision'), visionNote: $('vision-note'), backendMsg: $('backend-msg'),
      personaToggle: $('persona-toggle'), personaSummary: $('persona-summary'), personaPanel: $('persona-panel'),
      personaPreset: $('persona-preset'), personaText: $('persona-text'), personaHint: $('persona-hint'),
      personaCount: $('persona-count'), personaVoice: $('persona-voice'), personaSave: $('persona-save'),
      personaReset: $('persona-reset'), personaMsg: $('persona-msg'),
      convId: $('conv-id'), turns: $('conv-turns'), turnDuration: $('turn-duration'), chat: $('chat'),
      ended: $('talk-ended'), actionBtn: $('action-btn'), endHint: $('end-hint'),
      log: $('log'), copyLogs: $('copy-logs-btn'), copyStatus: $('copy-logs-status'),
      badges: $('talk-badges'), brainBadge: $('brain-badge'), keyBadge: $('key-badge'),
      volume: $('volume'), volumeValue: $('volume-value'),
    };
    // backend-msg is a box of notes and lines.
    const box = RA.el('div');
    box.id = 'backend-msg';
    box.setAttribute('aria-live', 'polite');
    box.style.cssText = 'display: flex; flex-direction: column; gap: 8px;';
    E.backendMsg.replaceWith(box);
    E.backendMsg = box;

    E.brain.addEventListener('change', () => sendBackend({ brain: E.brain.value }));
    E.language.addEventListener('change', () => sendBackend({ language: E.language.value }));
    E.voice.addEventListener('change', () => sendBackend({ voice: E.voice.value }));
    E.el.addEventListener('click', () => sendBackend({ elevenlabs: E.el.getAttribute('aria-checked') !== 'true' }));
    E.vision.addEventListener('click', () => sendBackend({ vision: E.vision.getAttribute('aria-checked') !== 'true' }));
    E.elVoice.addEventListener('change', () => {
      const opt = E.elVoice.selectedOptions[0];
      sendBackend({ el_voice_id: E.elVoice.value, el_voice_name: E.elVoice.value && opt ? opt.textContent : '' });
    });

    E.personaToggle.addEventListener('click', async () => {
      const on = E.personaToggle.getAttribute('aria-checked') !== 'true';
      setSwitch(E.personaToggle, on);
      E.personaPanel.hidden = !on;
      // Switching on saves nothing by itself; off is the reset, at once, and keeps the text.
      const body = { enabled: on };
      if (on && E.personaText.value.trim()) body.overlay = E.personaText.value;
      const data = await sendPersona(body);
      if (data) personaMessage(on ? '' : 'Back to the base persona. Your text is kept.', true);
    });
    E.personaPreset.addEventListener('change', async () => {
      const id = E.personaPreset.value;
      if (!id) return;              // "Write my own" sends nothing
      personaDirty = false;
      await sendPersona({ preset_id: id, enabled: true });
    });
    E.personaText.addEventListener('input', () => { personaDirty = true; updateCount(); });
    E.personaVoice.addEventListener('change', () => { personaDirty = true; });
    E.personaSave.addEventListener('click', async () => {
      const max = persona.max_chars || PERSONA_MAX;
      if (E.personaText.value.length > max) {
        personaMessage(`That character is ${E.personaText.value.length.toLocaleString('en-US')} characters. The limit is ${max.toLocaleString('en-US')}.`, false);
        return;
      }
      const data = await sendPersona({ overlay: E.personaText.value, voice: E.personaVoice.value, enabled: true });
      if (data) personaMessage('Saved.', true);
    });
    E.personaReset.addEventListener('click', async () => {
      const r = await RA.link.api('POST', 'persona/reset');
      if (!r.ok) { personaMessage("Couldn't reach the robot.", false); return; }
      personaDirty = false;
      persona = r.body;
      renderPersona();
      personaMessage('Cleared: back to the base persona.', true);
    });

    E.actionBtn.addEventListener('click', () => {
      if (E.actionBtn.disabled) return;
      if (current === 'CONVERSATION_RUNNING') endConversation(); else startConversation();
    });
    E.startSystem.addEventListener('click', startSystem);
    E.stopSystem.addEventListener('click', stopSystem);
    E.copyLogs.addEventListener('click', copyLogs);
    E.volume.addEventListener('input', onVolume);
    $('details-btn').addEventListener('click', openDetails);
    $('wifi-save').addEventListener('click', saveWifi);

    RA.onLink((m) => { if (RA.link && RA.link.key === key) handle(m); });
    RA.onHub(() => { if (RA.route.tab === 'talk') render(); });
  }

  function show(k) {
    if (k !== key) {
      key = k;
      current = 'STARTING';
      robotLink = { connected: null, ip: '', daemon: '' };
      persona = {};
      backend = null;
      identity = {};
      ended = null;
      startError = '';
      systemError = '';
      clearChat();
      clearTimer();
      setConvHeader('');
      E.log.textContent = '';
      logLines = [];
      E.ended.textContent = '';
      // The link may already be open (Wizard of Oz used it): replay its snapshot.
      if (RA.link && RA.link.key === k && RA.link.snapshot) handle(RA.link.snapshot);
    }
    render();
  }

  RA.Talk = { init, show, render, handle, state: () => current };
})();
