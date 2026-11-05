/* Reachy app, Group tab: several Reachys and the people in the room.
 *
 * The hub runs the whole conversation (docs/GROUP-CONVERSATION.md, Contract
 * 2); this tab shows and steers it, as web/group.js did until 2026-11-05.
 * One WebSocket in (/ws/group), REST out. Every `group.state` is the whole
 * truth and the tab redraws from it; the smaller messages (a turn, the
 * status, mic levels, the person's live words) patch it in between.
 *
 * Every robot has its own settings (label, personality, voice service and
 * voice, writer, interrupting level, gestures, camera, volume), all
 * changeable mid-conversation; the tab saves them at once (autosave).
 */
'use strict';

(function () {
  const { $, el, str, num, obj, arr, clock, bdi, setValue, fillOptions } = RA;

  const LAPTOP_KEYS = ['sim:1', 'sim:2', 'sim:3', 'sim:4', 'sim:5'];
  const LANGUAGES = [['auto', 'Auto'], ['he', 'Hebrew'], ['en', 'English']];
  const PHASE_LABEL = {
    idle: 'Not running', starting: 'Starting', speaking: 'Speaking', listening: 'Listening',
    human: 'People speaking', thinking: 'Thinking', stopping: 'Stopping', ready: 'Connected',
  };
  const MODE_NAME = { group: 'Group talk', interrupt: 'Interrupt', free: 'Free talk' };
  const MODE_SUB = { group: 'robots + people', interrupt: 'they cut you off', free: 'chat about anything' };
  const LEVEL_TEXT = ['never', 'rarely', 'now and then', 'regularly', 'often', 'every time'];
  const PROVIDERS = [['auto', 'Auto'], ['elevenlabs', 'ElevenLabs'], ['openai', 'OpenAI'],
                     ['openrouter', 'OpenRouter'], ['gemini', 'Gemini (daily cap)']];
  const PROVIDER_NAME = { eleven: 'ElevenLabs', elevenlabs: 'ElevenLabs', openai: 'OpenAI',
                          openrouter: 'OpenRouter', gemini: 'Gemini' };
  const WRITERS = [['google/gemini-3.5-flash', 'Gemini 3.5 Flash (smart, ~2.5 s)'],
                   ['openai/gpt-oss-120b', 'gpt-oss-120b (fastest, ~1.2 s)'],
                   ['openai/gpt-5.4-mini', 'GPT-5.4 mini (~2.8 s)'],
                   ['gpt-4.1-mini', 'GPT-4.1 mini (OpenAI key)'],
                   ['gemini-3.5-flash-lite', 'Flash-Lite (Gemini key)']];
  // Which of a robot's fields holds the voice for each service. Auto starts
  // with ElevenLabs, so it shows (and sets) the ElevenLabs voice.
  const VOICE_FIELD = { auto: 'voice_id', elevenlabs: 'voice_id', openai: 'openai_voice',
                        openrouter: 'openai_voice', gemini: 'gemini_voice' };
  // Session settings the hub takes while they talk.
  const LIVE_KEYS = ['topic', 'language', 'minutes', 'listen_gap_s', 'heads_mirror', 'voice_min_level',
                     'barge_in', 'slow_network', 'lab_intro', 'groups'];
  // The session clock runs only while the conversation itself does.
  const LIVE_PHASES = ['speaking', 'listening', 'human', 'thinking'];
  // One colour per seat, kept for the page's life (cards and transcript).
  const SEAT_COLORS = ['#2563EB', '#C2410C', '#047857', '#BE185D', '#6D28D9', '#0E7490'];
  const GROUP_COLORS = SEAT_COLORS;
  const GROUP_KINDS = [['both', 'Talk and move together'], ['talk', 'Talk together, each moves its own way'],
                       ['move', 'Move together, each says its own lines']];
  const SAVE_DELAY_MS = 700;       // typing
  const QUICK_SAVE_MS = 150;       // a click: the robots should feel it at once
  const FOLLOW_AFTER_MS = 20000;   // scrolled up in the transcript: follow again after this
  const SPEAK_CHARS_PER_S = 15;    // the robot's live caption types at about speaking pace
  const LOW_CREDITS = 1500;
  // The hub's real ranges (conductor.py clamps).
  const MINUTES_RANGE = [0.5, 60];
  const GAP_RANGE = [0.2, 3.0];
  const DEFAULT_SETTINGS = { topic: '', language: 'auto', minutes: 5, listen_gap_s: 0.6, simulate: false,
                             voice_min_level: 0.3, heads_mirror: false, barge_in: 'normal',
                             slow_network: true, lab_intro: true, voice_provider: 'auto',
                             director_model: 'google/gemini-3.5-flash', interrupt_level: 3,
                             vision: true, gestures: 'lively', people_mic: 'auto', groups: [] };
  const DEFAULT_STATUS = { phase: 'idle', speaker: null, elapsed_s: 0, detail: '' };

  let S = normalize({});           // the hub's last word on everything
  let draft = { settings: { ...DEFAULT_SETTINGS }, seats: [] };   // what the form shows
  let dirty = false;               // the form holds edits the hub has not saved yet
  let editSeq = 0;
  let saveTimer = null;
  let saveInFlight = null;
  let statusAt = performance.now();
  let localError = '';             // a refused request; the hub's own error wins
  let linkError = '';              // the hub could not be asked at all
  let loaded = false;
  let starting = '';               // the mode being started, '' when none
  let stopping = false;
  let gettingReady = false;
  let micSwitching = false;
  let addingTime = false;
  let levels = {};
  let peopleLiveText = '';
  let levelsTimer = null;
  let localIds = 0;
  let copyFrom = null;
  let checksOpen = false;
  const openCards = new Set();     // live cards opened with "Personality, camera, more"

  let E = {};                      // elements, filled by init()

  /* ---------------------------------------------------------------- state */
  function normalizeSeat(s, st) {
    const seat = obj(s);
    st = obj(st);
    return {
      ...seat,
      key: str(seat.key || seat.name),
      name: str(seat.name || seat.key),
      included: seat.included !== false,
      listen: seat.listen !== false,
      character: str(seat.character),
      persona: str(seat.persona),
      voice_provider: str(seat.voice_provider) || str(st.voice_provider) || 'auto',
      voice_id: str(seat.voice_id),
      openai_voice: str(seat.openai_voice),
      gemini_voice: str(seat.gemini_voice),
      writer: str(seat.writer) || str(st.director_model) || WRITERS[0][0],
      interrupt_level: Math.max(0, Math.min(5, Math.round(num(seat.interrupt_level, num(st.interrupt_level, 3))))),
      gestures: seat.gestures === 'calm' ? 'calm' : (seat.gestures === 'lively' ? 'lively' : (st.gestures || 'lively')),
      vision: seat.vision === undefined ? st.vision !== false : seat.vision !== false,
      loudness: num(seat.loudness, 150),
      default_voices: obj(seat.default_voices),
    };
  }

  function normalize(raw) {
    const st = obj(raw);
    const settings = { ...DEFAULT_SETTINGS, ...obj(st.settings) };
    return {
      running: !!st.running,
      connected: !!st.connected,
      mode: st.mode ? str(st.mode) : null,
      people_live: str(st.people_live),
      limit_s: st.limit_s === null || st.limit_s === undefined ? null : num(st.limit_s, null),
      closing: !!st.closing,
      eleven_credits: st.eleven_credits === null || st.eleven_credits === undefined ? null : num(st.eleven_credits, null),
      eleven_in_use: st.eleven_in_use === undefined ? null : st.eleven_in_use,
      connected_seats: arr(st.connected_seats).map(str),
      voice_backend: obj(st.voice_backend),
      brain: obj(st.brain),
      echo: obj(st.echo),
      available: arr(st.available).map(obj).filter(a => a.key),
      seats: arr(st.seats).map(s => normalizeSeat(s, settings)).filter(s => s.key),
      voices: arr(st.voices).map(obj).filter(v => v.voice_id),
      voice_options: obj(st.voice_options),
      providers: obj(st.providers),
      settings,
      status: { ...DEFAULT_STATUS, ...obj(st.status) },
      transcript: arr(st.transcript).filter(t => t && typeof t === 'object'),
      error: st.error ? str(st.error) : null,
      mics: arr(st.mics).map(str).filter(Boolean),
      people_mic_active: str(st.people_mic_active),
      mic: obj(st.mic),
      warm: obj(st.warm),
    };
  }

  // `group.state` may carry the object at the top level or under `state`.
  function unwrapState(msg) {
    const m = obj(msg);
    const inner = obj(m.state);
    if ('seats' in inner || 'settings' in inner || 'running' in inner) return inner;
    if ('seats' in m || 'settings' in m || 'running' in m) return m;
    return null;
  }

  function connectedKey(key) {
    const a = S.available.find(x => x.key === key);
    return !!a && (!a.state || RA.CONNECTED.includes(a.state));
  }

  // Robots the hub can use but has no seat for yet still get a card.
  function withAvailable(seats) {
    const out = seats.slice();
    S.available.forEach(a => {
      if (out.some(s => s.key === a.key)) return;
      out.push(normalizeSeat({ key: a.key, name: a.name || a.key, included: connectedKey(a.key), listen: true },
                             S.settings));
    });
    return out;
  }

  function copyGroups(list) {
    return arr(list).map(g => ({ ...obj(g), members: arr(obj(g).members).map(str) }));
  }

  function loadDraft() {
    draft = {
      settings: { ...S.settings, groups: copyGroups(S.settings.groups) },
      seats: withAvailable(S.seats.map(s => ({ ...s }))),
    };
  }

  function applyState(raw) {
    if (!raw) return;
    S = normalize(raw);
    if (!loaded && !saveNote.text) saveNote = { text: 'Saved.', kind: 'ok' };
    loaded = true;
    linkError = '';
    statusAt = performance.now();
    if (!dirty && !saveInFlight) loadDraft();
    else draft.seats = withAvailable(draft.seats);
    peopleLiveText = S.people_live;
    if (S.running && localError.startsWith("Couldn't start")) localError = '';
    renderConfig();
    renderStatus();
    renderTranscript();
    renderError();
  }

  /* ---------------------------------------------------------------- seats */
  function findSeat(who) {
    const w = str(who);
    if (!w) return null;
    for (const list of [S.seats, draft.seats]) {
      const hit = list.find(s => s.key === w) || list.find(s => s.name === w)
        || list.find(s => s.character && s.character === w);
      if (hit) return hit;
    }
    return null;
  }

  const seatColors = new Map();
  function seatColor(seat) {
    if (!seat) return '';
    if (!seatColors.has(seat.key)) {
      const used = new Set(seatColors.values());
      const free = SEAT_COLORS.find(c => !used.has(c));
      seatColors.set(seat.key, free || SEAT_COLORS[seatColors.size % SEAT_COLORS.length]);
    }
    return seatColors.get(seat.key);
  }

  function draftSeat(key) {
    return draft.seats.find(s => s.key === key) || null;
  }

  /* --------------------------------------------------------------- status */
  // The big line: who has the floor, in words a visitor understands.
  function statusParts(status) {
    const phase = str(status.phase) || 'idle';
    if (phase === 'speaking') {
      const seat = findSeat(status.speaker);
      const verb = status.detail === 'interrupting' ? ' cuts in' : ' is speaking';
      if (seat) {
        const live = draftSeat(seat.key) || seat;
        const parts = [bdi(live.character || live.name || live.key)];
        if (live.character && live.character !== live.name) {
          const robot = el('span', 'muted', ' (');
          robot.style.fontWeight = '600';
          robot.append(bdi(live.name), ')');
          parts.push(robot);
        }
        parts.push(verb);
        return parts;
      }
      return status.speaker ? [bdi(str(status.speaker)), ' is speaking'] : ['A robot is speaking'];
    }
    switch (phase) {
      case 'listening': return [S.mode === 'interrupt' ? 'Waiting for you to talk' : 'Listening to the room'];
      case 'human': return [S.mode === 'interrupt' ? 'You have the floor (for now)' : 'The people are speaking'];
      case 'ready': return ['Robots connected: pick a mode'];
      case 'thinking': return ['Thinking…'];
      case 'starting': return ['Starting…'];
      case 'stopping': return ['Stopping…'];
      case 'idle': return [S.running ? 'Running' : 'Not running'];
      default: return [phase];
    }
  }

  function renderStatus() {
    const status = S.status;
    const phase = str(status.phase) || 'idle';
    E.stage.dataset.phase = phase;
    E.phase.className = `phase ${PHASE_LABEL[phase] ? phase : 'idle'}`;
    E.phaseLabel.textContent = PHASE_LABEL[phase] || phase;
    E.statusLine.textContent = '';
    E.statusLine.append(...statusParts(status));
    // Shown on purpose since 2026-11-05: Get ready's progress ("getting
    // ready: checking every service", "connected, but X failed the check").
    const hidden = ['interrupting', 'the robots are listening'];
    let detail = hidden.includes(str(status.detail)) ? '' : str(status.detail);
    if (phase === 'ready' && /^robots connected/i.test(detail)) detail = '';
    const modeText = S.running && S.mode ? MODE_NAME[S.mode] || S.mode : '';
    const closing = S.running && S.closing ? 'closing: each robot says its last word' : '';
    const parts = [modeText, closing || detail].filter(Boolean);
    E.statusDetail.textContent = RA.cap(parts.join(' · '));
    E.statusDetail.hidden = !E.statusDetail.textContent;
    E.view.classList.toggle('g-live', S.running);
    E.seats.classList.toggle('compact', S.running);
    renderPeopleLive();
    renderTimer();
    renderButtons();
    renderSpeaking();
    renderLiveBits();
  }

  // Bits that read differently while a conversation runs.
  function renderLiveBits() {
    const live = S.running;
    document.querySelectorAll('#view-group .only-live').forEach(n => { n.hidden = !live; });
    document.querySelectorAll('#view-group .only-setup').forEach(n => { n.hidden = live; });
    E.roomLiveNote.hidden = !live || roomOpen();
    if (live && !E.view.dataset.wasLive) setRoomOpen(false);
    if (!live && E.view.dataset.wasLive) setRoomOpen(true);
    if (live) E.view.dataset.wasLive = '1'; else delete E.view.dataset.wasLive;
  }

  function roomOpen() { return E.roomFold.getAttribute('aria-expanded') === 'true'; }
  function setRoomOpen(open) {
    E.roomFold.setAttribute('aria-expanded', open ? 'true' : 'false');
    E.roomBody.hidden = !open;
    E.roomLiveNote.hidden = !S.running || open;
  }

  function elapsedNow() {
    const base = num(S.status.elapsed_s, 0);
    const live = S.running && LIVE_PHASES.includes(S.status.phase);
    return live ? base + (performance.now() - statusAt) / 1000 : base;
  }

  function renderTimer() {
    const minutes = num((S.running ? S.settings : draft.settings).minutes, 5);
    const total = S.running && S.limit_s ? S.limit_s : Math.max(0, minutes) * 60;
    const elapsed = elapsedNow();
    E.timer.textContent = clock(elapsed);
    E.timerTotal.textContent = clock(total);
    const share = total > 0 ? Math.min(1, elapsed / total) : 0;
    E.timerFill.style.width = `${(share * 100).toFixed(1)}%`;
    const over = total > 0 && elapsed >= total && S.running;
    E.timerBar.classList.toggle('over', over);
    E.timerWrap.classList.toggle('over', over);
  }

  // Exactly one real Reachy on the hub (laptop robots do not count): Talk.
  function soloReachy() {
    if (draft.settings.simulate) return null;
    const real = S.available.filter(a => !LAPTOP_KEYS.includes(a.key));
    return real.length === 1 ? real[0] : null;
  }

  function renderTalk() {
    const solo = soloReachy();
    E.talkBtn.hidden = !solo;
    E.modes.classList.toggle('solo', !!solo);
    if (!solo) return;
    E.talkBtn.disabled = !!starting || S.connected || S.running;
    E.talkBtn.querySelector('small').textContent = solo.state === 'RUNNING' ? 'open its app' : 'one robot, its own app';
    E.talkBtn.title = S.connected
      ? 'Disconnect first: the group conversation is holding the robot.'
      : `Start ${solo.name || 'this Reachy'}'s own app: one robot talking with the people (Gemini Live and the other voices, character, Wizard of Oz). It opens in the Talk tab.`;
  }

  function renderButtons() {
    renderTalk();
    const seats = draft.seats.filter(s => s.included);
    const simulate = !!draft.settings.simulate;
    const enough = seats.length >= 2 || simulate;
    const phase = S.status.phase;

    E.modeBtns.forEach(btn => {
      const mode = btn.dataset.mode;
      const active = S.running && S.mode === mode;
      btn.classList.toggle('on', active);
      btn.disabled = !!starting || !enough || active;
      const sub = btn.querySelector('small');
      if (starting === mode) sub.textContent = S.connected ? 'starting…' : 'connecting…';
      else if (active) sub.textContent = 'running';
      else if (S.running) sub.textContent = 'switch to this';
      else sub.textContent = MODE_SUB[mode] || '';
    });
    const warmBusy = !!S.warm.busy;
    const busyReady = gettingReady || warmBusy;
    const checks = Object.values(obj(S.warm.checks));
    const done = S.connected && checks.length > 0 && checks.every(c => obj(c).ok === true) && !busyReady;
    const showStop = S.running || phase === 'starting' || !!starting || phase === 'stopping';
    E.readyBtn.hidden = showStop;
    E.stopBtn.hidden = !showStop;
    E.readyBtn.disabled = !!starting || busyReady || S.running || !enough;
    E.readyBtn.textContent = '';
    if (done) E.readyBtn.append(RA.icNode('check', 18), `Ready · ${RA.plural(checks.length, 'check')} ok`);
    else E.readyBtn.append(busyReady ? 'Getting ready…' : 'Get ready');
    E.readyBtn.className = `btn ${busyReady ? 'btn-quiet busy' : (done ? 'btn-ready-done' : 'btn-primary')}`;
    E.readyBtn.title = !enough && !S.running
      ? 'Needs two included robots (or Simulate).'
      : (warmBusy ? 'The hub is checking the services now.'
        : 'Before the audience arrives: connect the robots, check every service with a real request and prepare the first line of each mode, so a mode button speaks at once.');
    renderMic();
    renderChecks();
    E.stopBtn.disabled = stopping || !(S.running || phase === 'starting' || !!starting);
    const closing = S.running && S.closing;
    E.stopBtn.lastChild.textContent = stopping || phase === 'stopping' ? 'Stopping…' : (closing ? 'Stop now' : 'Stop');
    E.stopBtn.classList.toggle('closing', closing);
    E.stopBtn.title = closing
      ? 'The robots are saying goodbye. Press to stop at once, without the rest of the closing lines.'
      : 'End the conversation: the robot that is talking finishes, then every robot says one closing line and goodbye. Press again to stop at once. The robots stay connected.';
    E.moreTime.disabled = !S.running || closing || addingTime;
    E.disconnect.disabled = stopping || !S.connected;

    let hint = '';
    if (S.connected && !S.running && !starting) hint = 'Robots connected and listening. A mode button starts at once.';
    else if (!S.running && !starting) {
      if (!enough && soloReachy()) hint = 'One Reachy: use the Talk tab. For the group modes, include a second Reachy or press + on its card for a laptop robot.';
      else if (!enough) hint = 'Include at least two Reachys, or press + on a card to add a laptop robot.';
      else if (simulate) hint = 'Simulation: this laptop speaks and listens.';
      else {
        const away = seats.filter(s => !connectedKey(s.key)).map(s => s.name || s.key);
        hint = away.length ? `Not connected: ${away.join(', ')}.` : `${RA.plural(seats.length, 'Reachy', 'Reachys')} at the table.`;
      }
    }
    E.startHint.textContent = '';
    const warn = /^Not connected|^Include/.test(hint);
    if (warn) E.startHint.append(RA.icNode('alert', 16), ` ${hint}`);
    else E.startHint.textContent = hint;
    E.startHint.className = `hint${warn ? ' warnline' : ''}`;
  }

  // Who hears the people. A dead or unplugged DJI switches by itself.
  function renderMic() {
    const m = S.mic;
    const health = str(m.health);
    let text;
    let cls = '';
    if (m.in_use === 'people') {
      text = `Mic: ${micLabel(m.people_mic)}`;
      if (health === 'ok') { text += ' · signal ok'; cls = 'okline'; }
      else if (health) { text += ` · ${health}`; cls = 'warnline'; }
    } else if (m.in_use === 'robots') {
      const robots = arr(m.robot_mics);
      text = `Mic: the robots' own${robots.length ? ` (${robots.join(', ')})` : ''}`;
      if (m.dji) text += ' · DJI mic plugged in';
    } else if (!loaded) {
      text = 'Mic: checking';
    } else {
      text = m.dji ? 'Mic: DJI mic plugged in (used when the robots connect)'
                   : "Mic: no DJI plugged in · the robots' own mics";
      cls = m.dji ? 'okline' : '';
    }
    E.micState.className = cls;
    E.micState.lastChild.textContent = text;
    const live = S.connected && (m.in_use === 'people' || m.in_use === 'robots');
    E.micSwitch.hidden = !live || (m.in_use === 'robots' && !m.dji);
    E.micSwitch.disabled = micSwitching;
    const back = m.in_use === 'robots';
    E.micSwitch.textContent = back ? 'Use the DJI mic' : "Use robots' mics";
    E.micSwitch.className = `btn ${back ? 'btn-quiet' : 'btn-ghost'}`;
  }

  // One chip per service checked with a real request (Get ready), folded into
  // one pill with the time of the last check. A check still running shows a
  // spinner.
  function renderChecks() {
    const checks = obj(S.warm.checks);
    const all = Object.entries(checks).map(([name, c]) => [name, obj(c)]);
    const bad = all.filter(([, c]) => c.ok === false).map(([name]) => name);
    const done = all.filter(([, c]) => c.ok === true).length;
    const when = RA.ago(S.warm.at);
    E.checksPill.hidden = all.length === 0;
    let text = bad.length ? `${bad.length} failed: ${bad.join(', ')}`
      : done === all.length ? `${RA.plural(done, 'check')} ok` : `checking ${done}/${all.length}`;
    if (when && !bad.length) text += done === all.length ? ` · ${when}` : ` · last checked ${when}`;
    E.checksPill.textContent = text;
    E.checksPill.className = `chk${bad.length ? ' bad' : (done === all.length && done > 0 ? ' ok' : '')}`;
    const sig = JSON.stringify(checks);
    if (bad.length && E.checks.dataset.badSig !== sig) checksOpen = true;   // opens by itself
    E.checks.dataset.badSig = bad.length ? sig : '';
    // While Get ready runs the chips show by themselves: they are its progress.
    const shown = (checksOpen || (!!S.warm.busy && done < all.length)) && all.length > 0;
    E.checks.hidden = !shown;
    E.checksPill.setAttribute('aria-expanded', shown ? 'true' : 'false');
    if (E.checks.dataset.sig === sig) return;
    E.checks.dataset.sig = sig;
    E.checks.textContent = '';
    all.forEach(([name, c]) => {
      const chip = el('span', `chk ${c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'wait'}`);
      if (c.ok === true) chip.textContent = `${name} ${(num(c.ms, 0) / 1000).toFixed(1)} s`;
      else if (c.ok === false) chip.textContent = `${name}: failed`;
      else { const sp = el('span', 'spin'); sp.setAttribute('aria-hidden', 'true'); chip.append(sp, name); }
      if (c.detail) chip.title = str(c.detail).slice(0, 200);
      E.checks.append(chip);
    });
  }

  function renderSpeaking() {
    const speaker = S.status.phase === 'speaking' ? findSeat(S.status.speaker) : null;
    seatRows.forEach((row, key) => row.classList.toggle('speaking', !!speaker && speaker.key === key));
  }

  function renderError() {
    RA.setBanner('group', S.error || localError || linkError);
  }

  // What the person is saying, typed out as it comes. A correction of
  // earlier words keeps what still matches and retypes the rest.
  let liveShown = '';
  let liveTyping = 0;
  function renderPeopleLive() {
    const target = S.running ? peopleLiveText.slice(-160) : '';
    if (!target) {
      clearInterval(liveTyping);
      liveTyping = 0;
      liveShown = '';
      E.peopleLiveText.textContent = '';
      E.peopleLive.hidden = true;
      return;
    }
    E.peopleLive.hidden = false;
    if (!target.startsWith(liveShown)) {
      let same = 0;
      while (same < liveShown.length && liveShown[same] === target[same]) same++;
      liveShown = target.slice(0, same);
    }
    clearInterval(liveTyping);
    liveTyping = setInterval(() => {
      if (liveShown.length >= target.length) { clearInterval(liveTyping); liveTyping = 0; return; }
      liveShown = target.slice(0, liveShown.length + 2);
      E.peopleLiveText.textContent = liveShown;
    }, 25);
  }

  /* --------------------------------------------------------------- levels */
  function paintLevels() {
    document.querySelectorAll('#view-group .level[data-key]').forEach(bar => {
      const v = Math.max(0, Math.min(1, num(levels[bar.dataset.key], 0)));
      const fill = bar.firstElementChild;
      if (fill) fill.style.width = `${(v * 100).toFixed(0)}%`;
    });
  }
  function applyLevels(map) {
    levels = obj(map);
    paintLevels();
    clearTimeout(levelsTimer);
    levelsTimer = setTimeout(() => { levels = {}; paintLevels(); }, 1500);
  }

  /* -------------------------------------------------------------- session */
  function renderConfig() {
    const st = draft.settings;
    setValue(E.topic, st.topic);
    fillOptions(E.language, LANGUAGES.some(([id]) => id === st.language) ? LANGUAGES
      : [...LANGUAGES, [str(st.language), str(st.language)]], str(st.language) || 'auto');
    setValue(E.minutes, st.minutes);
    setValue(E.gap, st.listen_gap_s);
    setValue(E.voiceMin, st.voice_min_level);
    if (document.activeElement !== E.barge) E.barge.value = str(st.barge_in) || 'normal';
    setSwitch(E.slow, st.slow_network !== false);
    setSwitch(E.labIntro, st.lab_intro !== false);
    renderPeopleMic(st);
    setSwitch(E.mirror, !!st.heads_mirror);
    setSwitch(E.simulate, !!st.simulate);
    E.simulate.disabled = S.connected;
    E.simulate.title = S.connected ? 'Disconnect first to switch simulation' : '';

    const credits = S.eleven_credits;
    const low = credits !== null && credits < LOW_CREDITS;
    let note = '';
    if (credits !== null) {
      note = `ElevenLabs credits: ${credits.toLocaleString('en-US')}`;
      if (low) note += '. Low: robots on Auto use OpenAI.';
      else if (S.eleven_in_use) note += ' · in use';
    }
    E.voiceNote.textContent = note;
    E.voiceNote.hidden = !note;
    E.voiceNote.classList.toggle('session-note', true);
    E.voiceNote.classList.toggle('warn', low);

    E.robotsSub.textContent = S.connected
      ? (S.running ? 'Left to right, as the people see them. Seats are locked until Disconnect; everything else changes at once.'
        : 'Left to right, as the people see them. Order, Included and Listens lock while connected.')
      : 'Left to right, as the people see them. Everything changes at once.';
    E.nudgeText.placeholder = S.running ? 'Steer: e.g. make them argue about it, or ask the people a question' : 'Steer: used once it runs';
    E.nudgeSend.className = `btn ${S.running ? 'btn-dark' : 'btn-quiet'} btn-sm`;
    renderSeats();
    renderSaveState();
  }

  function setSwitch(btn, on) {
    btn.classList.toggle('on', !!on);
    btn.setAttribute('aria-checked', on ? 'true' : 'false');
  }

  // Windows' names for the laptop's mics, as people say them.
  function micLabel(name) {
    const n = str(name);
    const low = n.toLowerCase();
    if (low.includes('dji') || low.includes('wireless mic rx')) return 'DJI mic';
    if (/realtek|intel|smart sound|microphone array/.test(low)) return "Laptop's built-in mic";
    const inner = n.match(/^\s*(?:microphone|mic|headset)[^(]*\((.+)\)\s*$/i);
    return inner ? inner[1].replace(/\(R\)|\(TM\)/gi, '').trim() : n;
  }

  function renderPeopleMic(st) {
    const choice = str(st.people_mic) || 'auto';
    const dji = str(S.mic.dji) || S.mics.find(n => micLabel(n) === 'DJI mic');
    const opts = [['auto', dji ? 'Auto (DJI mic, plugged in)' : 'Auto (DJI mic when plugged in)'],
                  ['robots', "Robots' own mics"],
                  ...S.mics.map(n => [n, micLabel(n)])];
    if (!opts.some(([id]) => id === choice)) opts.push([choice, `${micLabel(choice)} (not plugged in)`]);
    fillOptions(E.peopleMic, opts, choice);
    E.peopleMic.disabled = S.running;
    const active = S.people_mic_active;
    E.peopleMic.title = S.running ? 'While it runs, use the mic switch on the stage.'
      : S.connected
        ? (active ? `Hearing the audience through the ${micLabel(active)}` : "Hearing the audience through the robots' mics")
        : 'Used when the robots connect';
  }

  function editSetting(key, value, delay) {
    draft.settings[key] = value;
    markDirty(delay);
  }

  function clampInput(input, range, key) {
    const n = num(input.value, NaN);
    if (!(n >= 0)) return;
    editSetting(key, Math.min(range[1], Math.max(range[0], n)));
  }

  /* ---------------------------------------------------------------- cards */
  const seatRows = new Map();

  function renderSeats() {
    if (syncChoir()) markDirty(QUICK_SAVE_MS);
    const keep = new Set();
    draft.seats.forEach((seat, i) => {
      let row = seatRows.get(seat.key);
      if (!row) {
        row = makeSeatRow(seat.key);
        seatRows.set(seat.key, row);
      }
      keep.add(seat.key);
      fillSeatRow(row, seat, i);
      if (E.seats.children[i] !== row) E.seats.insertBefore(row, E.seats.children[i] || null);
    });
    seatRows.forEach((row, key) => {
      if (!keep.has(key)) { row.remove(); seatRows.delete(key); openCards.delete(key); }
    });
    const n = draft.seats.length;
    // Before the start: up to three cards a row. While it runs: every robot
    // side by side up to five, then two rows.
    const cols = S.running ? (n <= 5 ? n : Math.ceil(n / 2)) : (n === 4 ? 2 : Math.min(3, n));
    E.seats.style.setProperty('--cols', String(Math.max(1, cols)));
    renderGroupsHead();
    E.seatsEmpty.hidden = n > 0;
    paintLevels();
    renderSpeaking();
  }

  function voiceOptions(provider, seat) {
    const defaults = obj(seat.default_voices);
    if (provider === 'auto' || provider === 'elevenlabs') {
      const def = S.voices.find(v => v.voice_id === defaults.elevenlabs);
      const list = [['', `Default${def ? ` (${def.name})` : ''}`]];
      S.voices.forEach(v => list.push([str(v.voice_id), str(v.name) || str(v.voice_id)]));
      if (seat.voice_id && !S.voices.some(v => v.voice_id === seat.voice_id)) {
        list.push([seat.voice_id, `${seat.voice_id} (not in the list)`]);
      }
      if (list.length === 1 && !S.providers.elevenlabs) list[0][1] = 'Default (no ElevenLabs key)';
      return list;
    }
    const own = arr(obj(S.voice_options)[provider]).map(obj).filter(v => v.id);
    const def = provider === 'gemini' ? defaults.gemini : defaults.openai;
    const list = [['', `Default${def ? ` (${def})` : ''}`]];
    own.forEach(v => list.push([str(v.id), str(v.label) || str(v.id)]));
    const mine = str(seat[VOICE_FIELD[provider]]);
    if (mine && !own.some(v => v.id === mine)) list.push([mine, `${mine} (not here: uses Default)`]);
    return list;
  }

  function fillSeatRow(row, seat, i) {
    const last = draft.seats.length - 1;
    const locked = S.connected;    // order, Included and Listens wait for Disconnect
    const color = seatColor(seat);
    row.style.setProperty('--sc', color);
    row.classList.toggle('out', !seat.included);
    row.classList.toggle('open', openCards.has(seat.key));
    row.querySelector('.sn').textContent = String(i + 1);
    const real = row.querySelector('.seat-robot');
    const robotName = str(seat.name || seat.key);
    const squash = (t) => str(t).toLowerCase().replace(/[\s_-]+/g, '');
    const onLaptop = seat.key.startsWith('sim:');
    real.textContent = onLaptop ? 'laptop · talks through this laptop' : robotName;
    real.hidden = !onLaptop && !!seat.character && squash(seat.character) === squash(robotName);
    // Its group, if it is in one that counts (two included robots).
    const tag = row.querySelector('.seat-group');
    const mine = groupOf(seat.key);
    const counts = mine && arr(mine.g.members).filter(k => includedKeys().includes(k)).length > 1;
    tag.hidden = !counts || !seat.included;
    if (counts) {
      tag.textContent = groupLabel(mine.g, mine.i);
      tag.style.setProperty('--gc', GROUP_COLORS[mine.i % GROUP_COLORS.length]);
      tag.title = `In ${groupLabel(mine.g, mine.i)}: ${GROUP_KINDS.find(([id]) => id === groupKind(mine.g))[1].toLowerCase()}.`;
    }

    const a = S.available.find(x => x.key === seat.key);
    const stateEl = row.querySelector('.seat-state');
    const state = a ? str(a.state) : '';
    const sig = `${state}|${!!a}`;
    if (stateEl.dataset.sig !== sig) {
      stateEl.dataset.sig = sig;
      stateEl.textContent = '';
      const text = a ? (RA.STATUS_TEXT[state] || state || 'Connected') : 'Not connected';
      stateEl.append(RA.pill(a ? (RA.STATUS_PILL[state] || 'p-conn') : 'p-off', text, state === 'CONNECTING'));
    }

    const level = row.querySelector('.level');
    level.dataset.key = seat.key;
    level.classList.toggle('deaf', !seat.listen);
    const echo = obj(S.echo[seat.key]);
    const peak = num(echo.peak_excess_db, -99);
    row.querySelector('.meterwrap').title = peak > -90
      ? `Microphone level. Echo check: its own voice peaked ${peak.toFixed(1)} dB over the learned echo (keep well under 8 dB for Normal).`
      : (seat.listen ? 'Microphone level' : 'Microphone level. Listens is off.');

    const name = row.querySelector('.seat-character');
    setValue(name, seat.character);
    const twin = seat.character && draft.seats.some(s => s.key !== seat.key && s.included && seat.included
      && s.character.trim().toLowerCase() === seat.character.trim().toLowerCase());
    row.querySelector('.warnlab').hidden = !twin;

    const included = row.querySelector('.seat-included');
    const listen = row.querySelector('.seat-listen');
    included.checked = !!seat.included;
    listen.checked = !!seat.listen;
    included.disabled = locked;
    listen.disabled = locked;
    row.querySelector('.seat-vision').checked = !!seat.vision;
    const left = row.querySelector('[data-move="-1"]');
    const right = row.querySelector('[data-move="1"]');
    left.disabled = locked || i === 0;
    right.disabled = locked || i === last;
    left.title = locked ? 'Disconnect first to change the seats' : 'Move one seat to the left';
    right.title = locked ? 'Disconnect first to change the seats' : 'Move one seat to the right';
    const simulating = !!draft.settings.simulate;
    const add = row.querySelector('.seat-add');
    const remove = row.querySelector('.seat-remove');
    add.hidden = remove.hidden = simulating;
    add.disabled = locked || laptopKeys().length >= LAPTOP_KEYS.length;
    remove.disabled = locked || (!onLaptop && !seat.included);
    add.title = locked ? 'Disconnect first to add a robot'
      : (add.disabled ? 'No more robots fit' : "Add a robot here (it talks through this laptop's speaker)");
    remove.title = locked ? 'Disconnect first to remove a robot'
      : (onLaptop ? 'Remove this robot' : 'Take this Reachy off the table (tick Included to bring it back)');

    setValue(row.querySelector('.seat-persona'), seat.persona);

    const provider = seat.voice_provider || 'auto';
    fillOptions(row.querySelector('.seat-provider'),
                PROVIDERS.map(([id, label]) => [id, id === 'auto' || S.providers[id] !== false
                  ? label : `${label} (no key)`]), provider);
    fillOptions(row.querySelector('.seat-voice'), voiceOptions(provider, seat),
                str(seat[VOICE_FIELD[provider] || 'voice_id']));

    const writers = WRITERS.some(([id]) => id === seat.writer) ? WRITERS : [...WRITERS, [seat.writer, seat.writer]];
    fillOptions(row.querySelector('.seat-writer'), writers, seat.writer);

    row.querySelectorAll('.level-picker [data-level]').forEach(b => {
      const on = Number(b.dataset.level) === seat.interrupt_level;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });
    row.querySelector('.level-picker').title = `${seat.interrupt_level}: cuts in ${LEVEL_TEXT[seat.interrupt_level]} (interrupt mode)`;
    row.querySelectorAll('[data-gestures]').forEach(b => {
      const on = b.dataset.gestures === seat.gestures;
      b.classList.toggle('on', on);
      b.setAttribute('aria-checked', on ? 'true' : 'false');
    });

    const slider = row.querySelector('.seat-loudness');
    const loud = Math.round(num(seat.loudness, 150));
    if (document.activeElement !== slider) slider.value = String(loud);
    slider.style.accentColor = color;
    row.querySelector('.volume-value').textContent = `${slider.value}%`;
    row.querySelector('.volnum').textContent = `${slider.value}%`;

    // What this robot uses right now (the hub falls back when a key fails).
    const now = [];
    const vb = str(S.voice_backend[seat.key]);
    const br = str(S.brain[seat.key]);
    if (vb) now.push(`Voice: ${PROVIDER_NAME[vb] || vb}`);
    if (br) now.push(`writing via ${PROVIDER_NAME[br] || br}`);
    const nowEl = row.querySelector('.card-now');
    nowEl.textContent = now.join(', ');
    nowEl.title = nowEl.textContent;
    row.querySelector('.vline').hidden = !now.length && !S.running;
    row.querySelector('.less-wrap').hidden = !(S.running && openCards.has(seat.key));
    row.querySelector('.copy-button').disabled = draft.seats.length < 2;
  }

  function makeSeatRow(key) {
    const row = $('seat-template').content.firstElementChild.cloneNode(true);
    row.dataset.key = key;
    row.addEventListener('input', (event) => editSeat(key, event.target, 'input'));
    row.addEventListener('change', (event) => editSeat(key, event.target, 'change'));
    row.addEventListener('click', (event) => {
      const t = event.target;
      const move = t.closest('[data-move]');
      if (move && !move.disabled) { moveSeat(key, Number(move.dataset.move)); return; }
      const lvl = t.closest('[data-level]');
      if (lvl) { setSeat(key, { interrupt_level: Number(lvl.dataset.level) }, QUICK_SAVE_MS); return; }
      const g = t.closest('[data-gestures]');
      if (g) { setSeat(key, { gestures: g.dataset.gestures }, QUICK_SAVE_MS); return; }
      if (t.closest('.seat-add')) { addSeat(key); return; }
      if (t.closest('.seat-remove')) { removeSeat(key); return; }
      if (t.closest('.copy-button')) { openCopy(key); return; }
      if (t.closest('.more-link')) { openCards.add(key); renderSeats(); return; }
      if (t.closest('.less-link')) { openCards.delete(key); renderSeats(); }
    });
    return row;
  }

  function setSeat(key, fields, delay) {
    const seat = draftSeat(key);
    if (!seat) return;
    Object.assign(seat, fields);
    markDirty(delay);
    renderSeats();
  }

  function editSeat(key, target, kind) {
    const seat = draftSeat(key);
    if (!seat) return;
    const cls = target.classList;
    if (cls.contains('seat-included') || cls.contains('seat-listen')) {
      if (S.connected || kind !== 'change') return;
      seat[cls.contains('seat-included') ? 'included' : 'listen'] = target.checked;
      markDirty(QUICK_SAVE_MS);
      renderSeats();
      renderButtons();
    } else if (cls.contains('seat-character') && kind === 'input') {
      seat.character = target.value;
      markDirty();
      renderSeats();
    } else if (cls.contains('seat-persona') && kind === 'input') {
      seat.persona = target.value;
      markDirty();
    } else if (cls.contains('seat-vision') && kind === 'change') {
      setSeat(key, { vision: target.checked }, QUICK_SAVE_MS);
    } else if (cls.contains('seat-provider') && kind === 'change') {
      setSeat(key, { voice_provider: target.value }, QUICK_SAVE_MS);
    } else if (cls.contains('seat-voice') && kind === 'change') {
      setSeat(key, { [VOICE_FIELD[seat.voice_provider] || 'voice_id']: target.value }, QUICK_SAVE_MS);
    } else if (cls.contains('seat-writer') && kind === 'change') {
      setSeat(key, { writer: target.value }, QUICK_SAVE_MS);
    } else if (cls.contains('seat-loudness')) {
      seat.loudness = Number(target.value);
      const card = target.closest('.seat');
      card.querySelector('.volume-value').textContent = `${target.value}%`;
      card.querySelector('.volnum').textContent = `${target.value}%`;
      if (kind === 'change') markDirty(QUICK_SAVE_MS);     // heard when the drag ends
    }
  }

  function laptopKeys() {
    return draft.seats.map(s => s.key).filter(k => LAPTOP_KEYS.includes(k));
  }

  // +: a new robot on this laptop's speaker, right after this card.
  function addSeat(afterKey) {
    if (S.connected || draft.settings.simulate) return;
    const have = laptopKeys();
    const key = LAPTOP_KEYS.find(k => !have.includes(k));
    if (!key) return;
    const i = draft.seats.findIndex(s => s.key === afterKey);
    const seat = normalizeSeat({ key, name: 'laptop', included: true, listen: false }, draft.settings);
    seat.fresh = true;
    draft.seats.splice(i + 1, 0, seat);
    draft.settings.laptop_seats = laptopKeys();
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    renderButtons();
  }

  // x: a laptop robot goes away; a real Reachy only leaves the table.
  function removeSeat(key) {
    if (S.connected) return;
    if (LAPTOP_KEYS.includes(key)) {
      draft.seats = draft.seats.filter(s => s.key !== key);
      draft.settings.laptop_seats = laptopKeys();
    } else {
      const seat = draftSeat(key);
      if (!seat) return;
      seat.included = false;
    }
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    renderButtons();
  }

  function moveSeat(key, step) {
    const i = draft.seats.findIndex(s => s.key === key);
    const j = i + step;
    if (i < 0 || j < 0 || j >= draft.seats.length || S.connected) return;
    [draft.seats[i], draft.seats[j]] = [draft.seats[j], draft.seats[i]];
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    const row = seatRows.get(key);
    if (row) {
      const same = row.querySelector(`[data-move="${step}"]`);
      const other = row.querySelector(`[data-move="${-step}"]`);
      (same && !same.disabled ? same : other).focus();
    }
  }

  /* --------------------------------------------------------------- groups */
  function groups() {
    if (!Array.isArray(draft.settings.groups)) draft.settings.groups = [];
    return draft.settings.groups;
  }
  function groupKind(g) {
    if (g.talk && g.move) return 'both';
    return g.talk ? 'talk' : 'move';
  }
  function groupLabel(g, i) { return str(g.name).trim() || `Group ${i + 1}`; }
  function groupOf(key) {
    const list = groups();
    const i = list.findIndex(g => arr(g.members).includes(key));
    return i < 0 ? null : { g: list[i], i };
  }
  function includedKeys() { return draft.seats.filter(s => s.included).map(s => s.key); }
  function wholeTable(g) { return g.whole_table !== undefined ? !!g.whole_table : g.id === 'choir'; }
  function isChoir() {
    const list = groups();
    return list.length === 1 && wholeTable(list[0]) && list[0].talk && list[0].move && includedKeys().length > 1;
  }
  // The Choir's member list follows the ticks. True when it changed.
  function syncChoir() {
    const list = groups();
    const listed = new Set(list.filter(g => !wholeTable(g)).flatMap(g => arr(g.members)));
    let changed = false;
    list.filter(wholeTable).forEach(g => {
      const want = includedKeys().filter(k => !listed.has(k));
      if (want.join('|') !== arr(g.members).join('|')) { g.members = want; changed = true; }
    });
    return changed;
  }
  function setGroups(list, message) {
    draft.settings.groups = list;
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    if (!$('groups-modal').hidden) renderGroupsModal();
    if (message) RA.toast(message);
  }
  function choirGroups() {
    return [{ id: 'choir', name: 'Choir', members: includedKeys(), talk: true, move: true, whole_table: true }];
  }
  function renderGroupsHead() {
    const here = new Set(draft.seats.map(s => s.key));
    const list = groups().filter(g => arr(g.members).filter(k => here.has(k)).length > 1);
    const choir = isChoir();
    E.choirBtn.setAttribute('aria-pressed', choir ? 'true' : 'false');
    E.choirBtn.lastChild.textContent = choir ? 'Choir: on' : 'Choir';
    E.choirBtn.style.background = choir ? '#EEF4FF' : '';
    E.choirBtn.style.color = choir ? '#1D4ED8' : '';
    const kindWord = { both: '', talk: ': talk together', move: ': move together' };
    E.groupsSummary.textContent = choir ? 'All robots as one voice'
      : list.map(g => `${groupLabel(g, groups().indexOf(g))} (${g.members.length})${kindWord[groupKind(g)]}`).join(', ');
    const later = S.running ? ' Used from the next Start.' : '';
    E.groupsSummary.title = list.length || choir ? `Groups.${later}` : '';
  }

  function memberBox(g, seat, list) {
    const other = groupOf(seat.key);
    const label = el('label', 'check');
    label.style.alignItems = 'center';
    const box = el('input');
    box.type = 'checkbox';
    box.checked = arr(g.members).includes(seat.key);
    const real = [];
    if (seat.character && seat.name) real.push(seat.name);
    if (other && other.g !== g) {
      label.classList.add('taken');
      real.push(`taken by ${groupLabel(other.g, other.i)}`);
      label.title = `In ${groupLabel(other.g, other.i)}: ticking it here moves it to this group.`;
    }
    if (!seat.included) {
      label.classList.add('out');
      real.push('not included');
      label.title = 'Not included in the conversation: it sits this one out.';
    }
    label.append(box, ` ${seat.character || seat.name} `, el('span', 'muted', real.join(' · ')));
    box.addEventListener('change', () => {
      g.whole_table = false;   // picked by hand: no longer "every robot at the table"
      list.forEach(x => { x.members = arr(x.members).filter(k => k !== seat.key); });
      if (box.checked) {
        const order = draft.seats.map(s => s.key);
        g.members = order.filter(k => k === seat.key || arr(g.members).includes(k));
      }
      setGroups(list);
    });
    return label;
  }

  function renderGroupsModal() {
    const box = $('groups-list');
    box.textContent = '';
    const list = groups();
    $('groups-empty').hidden = list.length > 0;
    list.forEach((g, i) => {
      const row = el('div', 'pnl grp-row');
      row.style.setProperty('--gc', GROUP_COLORS[i % GROUP_COLORS.length]);
      const top = el('div', 'grow-row');
      const name = el('input', 'input grow');
      name.type = 'text';
      name.maxLength = 30;
      name.dir = 'auto';
      name.placeholder = `Group ${i + 1}`;
      name.value = str(g.name);
      name.setAttribute('aria-label', 'Group name');
      name.title = "The group's name in the transcript and for the writer, when it talks as one.";
      name.addEventListener('input', () => { g.name = name.value; markDirty(); renderSeats(); });
      const kind = el('select', 'select');
      kind.style.width = '300px';
      kind.setAttribute('aria-label', 'What the group does together');
      GROUP_KINDS.forEach(([id, label]) => { const o = el('option', '', label); o.value = id; kind.append(o); });
      kind.value = groupKind(g);
      kind.addEventListener('change', () => { g.talk = kind.value !== 'move'; g.move = kind.value !== 'talk'; setGroups(list); });
      const remove = el('button', 'ib');
      remove.type = 'button';
      remove.style.cssText = 'width: 40px; height: 40px;';
      remove.title = 'Remove this group (its robots go back to being on their own)';
      remove.setAttribute('aria-label', 'Remove this group');
      remove.append(RA.icNode('x', 16));
      remove.addEventListener('click', () => setGroups(list.filter(x => x !== g)));
      top.append(name, kind, remove);
      const members = el('div', 'checks3');
      members.style.gap = '18px';
      draft.seats.forEach(seat => members.append(memberBox(g, seat, list)));
      row.append(top, members);
      const inTable = arr(g.members).filter(k => includedKeys().includes(k));
      const lead = draftSeat(inTable[0] || arr(g.members)[0]);
      const leadName = lead ? (lead.character || lead.name) : 'its first robot';
      if (inTable.length < 2) {
        const note = el('p', 'sub', `Needs two included robots to count.${g.talk ? ` It would talk in ${leadName}'s voice and settings.` : ''}`);
        note.style.color = '#8A3B00';
        row.append(note);
      } else if (g.talk) {
        row.append(el('p', 'sub', `Talks in ${leadName}'s voice and settings.`));
      } else {
        row.append(el('p', 'sub', 'Moves together. Each says its own lines.'));
      }
      box.append(row);
    });
  }

  function openGroups() {
    renderGroupsModal();
    $('groups-modal').hidden = false;
    const first = $('groups-modal').querySelector('input, button');
    if (first) first.focus();
  }
  function closeGroups() {
    $('groups-modal').hidden = true;
    E.groupsBtn.focus();
  }

  /* ----------------------------------------------------------------- copy */
  function openCopy(key) {
    const from = draftSeat(key);
    if (!from) return;
    copyFrom = key;
    $('copy-title').textContent = `Copy ${from.character || from.name}'s settings`;
    const targets = $('copy-targets');
    targets.textContent = '';
    draft.seats.filter(s => s.key !== key).forEach(s => {
      const label = el('label', 'check');
      label.style.alignItems = 'center';
      const box = el('input');
      box.type = 'checkbox';
      box.value = s.key;
      box.checked = true;
      label.append(box, ` ${s.character || s.name} `);
      if (s.character && s.name) label.append(el('span', 'muted', s.name));
      targets.append(label);
    });
    $('copy-modal').hidden = false;
    const first = $('copy-form').querySelector('input');
    if (first) first.focus();
  }
  function closeCopy() {
    $('copy-modal').hidden = true;
    const row = seatRows.get(copyFrom);
    copyFrom = null;
    if (row) row.querySelector('.copy-button').focus();
  }
  function submitCopy(event) {
    event.preventDefault();
    const from = draftSeat(copyFrom);
    if (!from) { closeCopy(); return; }
    const targets = Array.from($('copy-targets').querySelectorAll('input:checked')).map(b => b.value);
    const what = Array.from($('copy-form').querySelectorAll('.copy-what input:checked')).map(b => b.value);
    const fields = what.flatMap(w => (w === 'voices' ? ['voice_id', 'openai_voice', 'gemini_voice'] : [w]));
    if (!targets.length || !fields.length) { RA.toast('Pick at least one robot and one setting.', true); return; }
    targets.forEach(key => {
      const seat = draftSeat(key);
      if (seat) fields.forEach(f => { seat[f] = from[f]; });
    });
    const names = targets.map(k => { const s = draftSeat(k); return s ? s.character || s.name : k; });
    closeCopy();
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    RA.toast(`Copied to ${names.join(', ')}.`);
  }

  /* ----------------------------------------------------------------- save */
  let saveNote = { text: '', kind: '' };
  function renderSaveState() {
    let badge = 'Saved';
    let kind = 'ok';
    if (!loaded) { badge = 'Loading'; kind = 'busy'; }
    else if (saveInFlight) { badge = 'Saving'; kind = 'busy'; }
    else if (dirty) { badge = 'Not saved yet'; kind = 'problem'; }
    else if (saveNote.kind === 'error') { badge = 'Not saved'; kind = 'problem'; }
    RA.setSave('group', badge, kind);
    E.saveState.textContent = '';
    if (saveNote.text) {
      E.saveState.append(RA.icNode(saveNote.kind === 'error' ? 'alert' : 'check', 14), saveNote.text);
      if (saveNote.kind !== 'ok' && saveNote.kind !== 'error') E.saveState.firstChild.style.visibility = 'hidden';
    }
    E.saveState.className = `save${saveNote.kind === 'error' ? ' warn' : ''}`;
    E.saveState.style.color = saveNote.kind === 'error' ? '#B91C1C' : (saveNote.kind === 'ok' ? '' : '#6B635A');
  }
  function setSaveNote(text, kind = '') {
    saveNote = { text, kind };
    renderSaveState();
  }
  function markDirty(delay = SAVE_DELAY_MS) {
    dirty = true;
    editSeq += 1;
    setSaveNote('Saving shortly…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, delay);
    renderButtons();
    renderTimer();
  }
  function errorFrom(r) {
    if (r && (r.status === 404 || r.status === 405)) return 'This Robot Hub has no Group yet. Restart Robot Hub.';
    return RA.errorText(r);
  }

  function seatPayload(s) {
    if (s.fresh) return { key: s.key, included: true, listen: false };
    const out = {};
    ['key', 'included', 'listen', 'character', 'persona', 'voice_provider', 'voice_id', 'openai_voice',
     'gemini_voice', 'writer', 'interrupt_level', 'gestures', 'vision', 'loudness'].forEach(k => {
      if (k in s) out[k] = s[k];
    });
    return out;
  }

  async function putConfig() {
    const seq = editSeq;
    const settings = {};
    if (S.running) LIVE_KEYS.forEach(k => { if (k in draft.settings) settings[k] = draft.settings[k]; });
    else Object.assign(settings, draft.settings);
    const body = { seats: draft.seats.map(seatPayload), settings };
    setSaveNote('Saving…');
    const r = await RA.put('/api/group/config', body);
    if (r.ok && r.body.ok !== false) {
      if (seq === editSeq) dirty = false;
      setSaveNote(dirty ? 'Saving shortly…' : 'Saved.', dirty ? '' : 'ok');
      const st = unwrapState(r.body);
      if (st) { saveInFlight = null; applyState(st); }
      return true;
    }
    if (r.status === 409) {
      if (seq === editSeq) dirty = false;
      setSaveNote(`Not saved: ${errorFrom(r)}. The hub's version is back.`, 'error');
      saveInFlight = null;
      loadDraft();
      renderConfig();
      return false;
    }
    setSaveNote(`Not saved: ${errorFrom(r)}. Trying again…`, 'error');
    retrySave();
    return false;
  }
  function retrySave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 3000);
  }
  async function save() {
    clearTimeout(saveTimer);
    saveTimer = null;
    while (saveInFlight) await saveInFlight;
    if (!dirty) return true;
    saveInFlight = putConfig();
    renderSaveState();
    try {
      return await saveInFlight;
    } finally {
      saveInFlight = null;
      renderSaveState();
      renderButtons();
    }
  }

  /* ----------------------------------------------------------- transcript */
  const turnEls = new Map();       // turn id -> row element
  let turnOrder = [];
  let following = true;
  let scrolledAt = 0;
  let programmatic = 0;
  let unseen = 0;
  // The robot's live caption: the current robot line types in at speaking
  // pace from the moment it starts.
  const captions = new Map();      // turn id -> {start, text}
  let captionTimer = 0;

  function nearBottom() {
    return E.transcript.scrollHeight - E.transcript.scrollTop - E.transcript.clientHeight < 60;
  }
  function scrollToEnd() {
    programmatic = performance.now();
    E.transcript.scrollTop = E.transcript.scrollHeight;
    following = true;
    unseen = 0;
    E.jump.hidden = true;
  }
  function turnId(t, i) { return t.id !== undefined && t.id !== null ? String(t.id) : `at-${i}`; }

  function renderTranscript() {
    const turns = S.transcript;
    const ids = turns.map(turnId);
    const prefix = turnOrder.length <= ids.length && turnOrder.every((id, i) => id === ids[i]);
    if (!prefix) {
      E.transcript.textContent = '';
      turnEls.clear();
      captions.clear();
      turnOrder = [];
    }
    const added = ids.length - turnOrder.length;
    for (let i = turnOrder.length; i < ids.length; i++) {
      const row = el('div', 'ln2');
      turnEls.set(ids[i], row);
      E.transcript.append(row);
    }
    turnOrder = ids;
    markCurrent();
    turns.forEach((t, i) => fillTurn(turnEls.get(ids[i]), t, ids[i]));

    E.transcriptEmpty.hidden = turns.length > 0;
    E.transcript.hidden = turns.length === 0;
    const said = turns.filter(t => t.kind !== 'note').length;
    E.turnCount.textContent = said ? `(${said})` : '';

    if (!following && performance.now() - scrolledAt > FOLLOW_AFTER_MS) following = true;
    if (following || !prefix) scrollToEnd();
    else if (added > 0) {
      unseen += added;
      E.jump.lastChild.textContent = `Jump to latest (${unseen} new)`;
      E.jump.hidden = false;
    }
  }

  // The line being said now: the last robot or people line while one speaks.
  let currentId = null;
  function markCurrent() {
    const phase = S.status.phase;
    let current = null;
    if (S.running && (phase === 'speaking' || phase === 'human')) {
      for (let i = S.transcript.length - 1; i >= 0; i--) {
        const t = S.transcript[i];
        if (t.kind === 'note') continue;
        if ((phase === 'speaking' && t.kind !== 'human') || (phase === 'human' && t.kind === 'human')) {
          current = turnId(t, i);
        }
        break;
      }
    }
    if (current !== currentId) {
      const before = currentId;
      currentId = current;
      [before, current].forEach(id => {
        const i = turnOrder.indexOf(id);
        if (id && i >= 0) fillTurn(turnEls.get(id), S.transcript[i], id, true);
      });
    }
  }

  function captionText(id, t) {
    const text = str(t.text);
    const typing = id === currentId && S.status.phase === 'speaking' && t.kind !== 'human' && !t.cut && text;
    if (!typing) { const c = captions.get(id); if (c) c.done = true; return { text, typing: false }; }
    let c = captions.get(id);
    if (!c || c.text !== text) {
      const shown = c && text.startsWith(c.text) ? c.shown : 0;
      c = { text, start: performance.now() - (shown / SPEAK_CHARS_PER_S) * 1000, shown, done: false };
      captions.set(id, c);
    }
    if (c.done) return { text, typing: false };
    const n = Math.min(text.length, Math.floor(((performance.now() - c.start) / 1000) * SPEAK_CHARS_PER_S));
    c.shown = n;
    if (n >= text.length) c.done = true;
    if (!c.done && !captionTimer) captionTimer = setInterval(tickCaptions, 60);
    return { text: text.slice(0, n), typing: !c.done };
  }
  function tickCaptions() {
    const id = currentId;
    const i = turnOrder.indexOf(id);
    const c = captions.get(id);
    if (!id || i < 0 || !c || c.done) { clearInterval(captionTimer); captionTimer = 0; if (i >= 0) fillTurn(turnEls.get(id), S.transcript[i], id, true); return; }
    fillTurn(turnEls.get(id), S.transcript[i], id, true);
  }

  function upsertTurn(raw) {
    const t = obj(raw);
    if (!Object.keys(t).length) return;
    const known = t.id !== undefined && t.id !== null;
    const i = known ? S.transcript.findIndex(x => x.id !== undefined && String(x.id) === String(t.id)) : -1;
    if (i >= 0) S.transcript[i] = { ...S.transcript[i], ...t };
    else S.transcript.push(known ? t : { ...t, id: `local-${++localIds}` });
    renderTranscript();
  }

  function robotNameOf(key) {
    const seat = findSeat(key);
    return (seat && seat.name) || str(key);
  }

  function fillTurn(row, t, id, force) {
    if (!row || !t) return;
    const kind = ['robot', 'human', 'note'].includes(t.kind) ? t.kind : (t.who === 'people' ? 'human' : 'robot');
    const seat = kind === 'robot' ? findSeat(t.who) : null;
    const color = seatColor(seat);
    const now = id === currentId;
    const cap = kind === 'robot' ? captionText(id, t) : { text: str(t.text), typing: false };
    const sig = JSON.stringify([t, color, seat && seat.name, now, cap.text, cap.typing]);
    if (row.dataset.sig === sig) return;
    row.dataset.sig = sig;
    row.textContent = '';
    row.style.removeProperty('--sc');

    if (kind === 'note') {
      row.className = 'note2';
      row.dir = 'auto';
      row.textContent = (t.t !== undefined && t.t !== null ? `${clock(t.t)} ` : '') + str(t.text);
      return;
    }
    row.className = `ln2${now ? ' now' : ''}${t.cut ? ' cut' : ''}${kind === 'human' ? ' people' : ''}`;
    row.removeAttribute('dir');
    row.style.setProperty('--sc', kind === 'human' ? '#D97706' : (color || '#6B635A'));
    const bar = el('span', 'cb');
    const body = el('div');
    const head = el('div', 'lh');
    const who = el('span', 'who');
    who.dir = 'auto';
    // The name it had when it said the line (a rename later does not rewrite it).
    who.textContent = kind === 'human' ? 'People'
      : str(t.character) || (seat && seat.character) || (seat && seat.name) || str(t.who) || 'Robot';
    head.append(who);
    if (kind === 'robot') {
      const robotName = (seat && seat.name) || str(t.who);
      if (robotName && robotName !== who.textContent) head.append(el('span', 'rtag', robotName));
      if (t.move) head.append(el('span', 'mtag', str(t.move)));
      if (t.latency_ms !== undefined && t.latency_ms !== null && Number.isFinite(Number(t.latency_ms))) {
        head.append(el('span', '', `${Math.round(Number(t.latency_ms))} ms`));
      }
    } else if (t.heard_by) {
      head.append(el('span', '', `heard closest to ${robotNameOf(t.heard_by)}`));
    }
    if (t.t !== undefined && t.t !== null) head.append(el('span', '', clock(t.t)));
    if (t.cut) head.append(el('span', 'cuttag', 'cut off'));
    const tx = el('div', 'tx');
    tx.dir = 'auto';
    const text = cap.text;
    if (kind === 'human' && !str(t.text)) {
      const i = el('i', 'muted', 'listening…');
      tx.append(i);
    } else if (kind === 'robot' && !str(t.text)) {
      tx.append(el('span', 'muted', '…'));
    } else {
      tx.append(document.createTextNode(text));
      if (cap.typing) {
        const cur = el('span', 'cur', '▌');
        cur.setAttribute('aria-hidden', 'true');
        tx.append(cur);
      }
    }
    body.append(head, tx);
    row.append(bar, body);
  }

  /* -------------------------------------------------------------- actions */
  async function post(url, payload) {
    const r = await RA.post(url, payload);
    const body = { ...r.body };
    if (body.ok === undefined) body.ok = r.ok;
    if (!body.ok && !body.error) body.error = errorFrom(r);
    return body;
  }

  async function startMode(mode) {
    starting = mode;
    renderButtons();
    try {
      if (dirty || saveInFlight) {
        const saved = await save();
        if (!saved || dirty) {
          localError = "The setup couldn't be saved, so the conversation didn't start.";
          return;
        }
      }
      const body = await post('/api/group/start', { mode });
      if (body.ok) localError = '';
      else {
        localError = `Couldn't start: ${body.error}`;
        RA.toast(localError, true);
      }
    } finally {
      starting = '';
      renderButtons();
      renderError();
    }
  }

  async function getReady() {
    if (E.readyBtn.disabled) return;
    gettingReady = true;
    renderButtons();
    try {
      if (dirty || saveInFlight) await save();
      const body = await post('/api/group/ready');
      if (!body.ok) {
        localError = `Couldn't get ready: ${body.error}`;
        RA.toast(localError, true);
      } else localError = '';
    } finally {
      gettingReady = false;
      renderButtons();
      renderError();
    }
  }

  async function moreTime() {
    if (E.moreTime.disabled) return;
    addingTime = true;
    renderButtons();
    try {
      const body = await post('/api/group/more_time', { seconds: 60 });
      if (body.ok && body.limit_s) { S.limit_s = num(body.limit_s, S.limit_s); renderTimer(); }
      else if (!body.ok) RA.toast(`Couldn't add time: ${body.error}`, true);
    } finally {
      addingTime = false;
      renderButtons();
    }
  }

  async function switchMic() {
    if (E.micSwitch.disabled) return;
    micSwitching = true;
    renderMic();
    try {
      const use = S.mic.in_use === 'robots' ? 'people' : 'robots';
      const body = await post('/api/group/mic', { use });
      if (!body.ok) RA.toast(`Couldn't switch the mic: ${body.error}`, true);
    } finally {
      micSwitching = false;
      renderMic();
    }
  }

  async function disconnect() {
    if (E.disconnect.disabled) return;
    stopping = true;
    renderButtons();
    try {
      const body = await post('/api/group/disconnect');
      if (!body.ok) RA.toast(`Couldn't disconnect: ${body.error}`, true);
    } finally {
      stopping = false;
      renderButtons();
    }
  }

  async function stop() {
    if (E.stopBtn.disabled) return;
    stopping = true;
    renderButtons();
    try {
      const body = await post('/api/group/stop', { now: !!(S.running && S.closing) });
      if (body.ok) localError = '';
      else {
        localError = `Couldn't stop: ${body.error}`;
        RA.toast(localError, true);
      }
    } finally {
      stopping = false;
      renderButtons();
      renderError();
    }
  }

  // 0-5 set every robot's interrupting level at once (a quick switch
  // mid-demo), on the Group tab, unless typing somewhere.
  function onKey(event) {
    if (RA.route.tab !== 'group') return;
    const t = event.target;
    if (!$('copy-modal').hidden) return;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (!/^[0-5]$/.test(event.key) || !draft.seats.length) return;
    const level = Number(event.key);
    draft.seats.forEach(s => { s.interrupt_level = level; });
    markDirty(QUICK_SAVE_MS);
    renderSeats();
    RA.toast(`Interrupting ${level} (${LEVEL_TEXT[level]}) for every robot.`);
  }

  async function nudge(event) {
    event.preventDefault();
    const text = E.nudgeText.value.trim();
    if (!text) { E.nudgeText.focus(); return; }
    E.nudgeSend.disabled = true;
    try {
      const body = await post('/api/group/nudge', { text });
      if (body.ok) {
        E.nudgeText.value = '';
        E.nudgeLast.textContent = `Last steer: ${text} · Enter sends · used for the next line`;
        RA.toast(S.running ? 'Sent. The next line follows it.' : 'Sent. It is used once the conversation runs.');
      } else {
        RA.toast(`Not sent: ${body.error}`, true);
      }
    } finally {
      E.nudgeSend.disabled = false;
      E.nudgeText.focus();
    }
  }

  /* ------------------------------------------------------------ transport */
  function handle(m) {
    m = obj(m);
    switch (m.type) {
      case 'group.state': applyState(unwrapState(m)); break;
      case 'group.turn': upsertTurn(m.turn); break;
      case 'group.status':
        S.status = { ...S.status, ...obj(m.status) };
        statusAt = performance.now();
        renderStatus();
        markCurrent();
        break;
      case 'group.levels': applyLevels(m.levels); break;
      case 'group.people': peopleLiveText = str(m.text); renderPeopleLive(); break;
      default: break;
    }
  }

  async function loadState() {
    const r = await RA.get('/api/group/state');
    const st = unwrapState(r.body);
    if (r.ok && st) { applyState(st); return; }
    linkError = r.status ? errorFrom(r) : `The hub didn't answer (${RA.errorText(r)}). The screen may be out of date.`;
    renderError();
  }

  /* ----------------------------------------------------------------- init */
  function init() {
    E = {
      view: $('view-group'), stage: $('stage'), phase: $('phase'), phaseLabel: $('phase-label'),
      statusLine: $('status-line'), statusDetail: $('status-detail'),
      timer: $('timer'), timerTotal: $('timer-total'), timerBar: $('timer-bar'), timerFill: $('timer-fill'),
      timerWrap: $('timer-wrap'), moreTime: $('more-time'),
      modes: $('modes'), modeBtns: Array.from(document.querySelectorAll('#modes .mode-button')),
      readyBtn: $('get-ready'), talkBtn: $('talk-one'), stopBtn: $('stop'), disconnect: $('disconnect'),
      micState: $('mic-state'), micSwitch: $('mic-switch'), startHint: $('start-hint'),
      checksPill: $('checks-pill'), checks: $('ready-checks'),
      topic: $('topic'), language: $('language'), minutes: $('minutes'), gap: $('listen-gap'),
      voiceMin: $('voice-min'), barge: $('barge-in'), slow: $('slow-network'), labIntro: $('lab-intro'),
      peopleMic: $('people-mic'), mirror: $('heads-mirror'), simulate: $('simulate'), voiceNote: $('voice-note'),
      roomFold: $('room-fold'), roomBody: $('room-body'), roomLiveNote: $('room-live-note'),
      robotsSub: $('robots-sub'), saveState: $('save-state'), groupsSummary: $('groups-summary'),
      choirBtn: $('choir-button'), groupsBtn: $('groups-button'), seats: $('seats'), seatsEmpty: $('seats-empty'),
      transcript: $('transcript'), transcriptEmpty: $('transcript-empty'), turnCount: $('turn-count'), jump: $('jump'),
      peopleLive: $('people-live'), peopleLiveText: $('people-live-text'),
      nudgeForm: $('nudge-form'), nudgeText: $('nudge-text'), nudgeSend: $('nudge-send'), nudgeLast: $('nudge-last'),
    };

    E.topic.addEventListener('input', () => editSetting('topic', E.topic.value));
    E.language.addEventListener('change', () => editSetting('language', E.language.value, QUICK_SAVE_MS));
    E.minutes.addEventListener('input', () => clampInput(E.minutes, MINUTES_RANGE, 'minutes'));
    E.minutes.addEventListener('change', () => { E.minutes.blur(); setValue(E.minutes, draft.settings.minutes); });
    E.gap.addEventListener('input', () => clampInput(E.gap, GAP_RANGE, 'listen_gap_s'));
    E.gap.addEventListener('change', () => { E.gap.blur(); setValue(E.gap, draft.settings.listen_gap_s); });
    E.voiceMin.addEventListener('input', () => {
      const n = num(E.voiceMin.value, NaN);
      if (n >= 0) editSetting('voice_min_level', Math.min(0.9, n));
    });
    E.barge.addEventListener('change', () => editSetting('barge_in', E.barge.value, QUICK_SAVE_MS));
    E.peopleMic.addEventListener('change', () => editSetting('people_mic', E.peopleMic.value, QUICK_SAVE_MS));
    [[E.slow, 'slow_network'], [E.labIntro, 'lab_intro'], [E.mirror, 'heads_mirror'], [E.simulate, 'simulate']].forEach(([btn, key]) => {
      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        const on = btn.getAttribute('aria-checked') !== 'true';
        setSwitch(btn, on);
        editSetting(key, on, QUICK_SAVE_MS);
      });
    });
    E.roomFold.addEventListener('click', () => setRoomOpen(!roomOpen()));

    E.modeBtns.forEach(btn => btn.addEventListener('click', () => { if (!btn.disabled) startMode(btn.dataset.mode); }));
    E.talkBtn.addEventListener('click', () => { const solo = soloReachy(); if (solo) RA.go('talk', solo.key); });
    E.readyBtn.addEventListener('click', getReady);
    E.moreTime.addEventListener('click', moreTime);
    E.micSwitch.addEventListener('click', switchMic);
    E.disconnect.addEventListener('click', disconnect);
    E.stopBtn.addEventListener('click', stop);
    E.checksPill.addEventListener('click', () => { checksOpen = !checksOpen; renderChecks(); });
    document.addEventListener('keydown', onKey);
    E.nudgeForm.addEventListener('submit', nudge);

    E.transcript.addEventListener('scroll', () => {
      if (performance.now() - programmatic < 200) return;
      if (nearBottom()) { following = true; unseen = 0; E.jump.hidden = true; }
      else { following = false; scrolledAt = performance.now(); }
    });
    E.jump.addEventListener('click', scrollToEnd);
    if (window.ResizeObserver) new ResizeObserver(() => { if (following) scrollToEnd(); }).observe(E.transcript);

    E.groupsBtn.addEventListener('click', openGroups);
    E.choirBtn.addEventListener('click', () => {
      if (isChoir()) setGroups([], 'Choir off: every robot is on its own (from the next Start).');
      else if (includedKeys().length < 2) RA.toast('Choir needs at least two included robots.', true);
      else setGroups(choirGroups(), 'Choir on: every robot at the table says the same line at once, also robots you tick later (from the next Start).');
    });
    $('groups-add').addEventListener('click', () => {
      setGroups([...groups(), { id: `g${Date.now().toString(36)}`, name: '', members: [], talk: true, move: true }]);
    });
    $('groups-choir').addEventListener('click', () => {
      if (includedKeys().length < 2) { RA.toast('Choir needs at least two included robots.', true); return; }
      setGroups(choirGroups());
    });
    $('groups-clear').addEventListener('click', () => setGroups([]));
    $('groups-done').addEventListener('click', closeGroups);
    $('groups-close').addEventListener('click', closeGroups);
    $('groups-modal').addEventListener('click', (event) => { if (event.target === $('groups-modal')) closeGroups(); });
    $('copy-form').addEventListener('submit', submitCopy);
    $('copy-cancel').addEventListener('click', closeCopy);
    $('copy-modal').addEventListener('click', (event) => { if (event.target === $('copy-modal')) closeCopy(); });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      if (!$('groups-modal').hidden) closeGroups();
      if (!$('copy-modal').hidden) closeCopy();
    });

    setInterval(renderTimer, 500);
    setInterval(() => { if (S.warm.at) renderChecks(); }, 30000);
    renderConfig();
    renderStatus();
    renderTranscript();
    renderSaveState();
    loadState();
    RA.socket('/ws/group', {
      message: handle,
      open() { RA.hub.groupLive = true; RA.renderLive(); },
      close() { RA.hub.groupLive = false; RA.renderLive(); },
    });
  }

  RA.Group = {
    init,
    state: () => S,
    // Talk asks: does the group conversation hold this robot right now?
    holds: (key) => S.connected && (S.connected_seats.length ? S.connected_seats.includes(key)
      : S.seats.some(s => s.key === key && s.included)),
    show() { renderSaveState(); renderError(); scrollToEnd(); },
    handle,          // demo mode feeds messages here
  };
})();
