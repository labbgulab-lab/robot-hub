/* Robot Hub: group conversation.
 *
 * Several Reachys and the people in the room talk together; the hub runs the
 * whole conversation (docs/GROUP-CONVERSATION.md, Contract 2). This page only
 * shows it and steers it: one WebSocket in (/ws/group), REST out, the same as
 * the main page. Every `group.state` is the whole truth and the page redraws
 * from it; the smaller messages (a turn, the status, mic levels) patch it in
 * between. Nothing here may throw on a missing field: a demo is running.
 *
 * Since 2026-10-21 every robot has its own settings (name, personality,
 * voice provider and voice, writer, interrupting level, gestures, camera,
 * volume), all changeable mid-conversation; the page saves them at once.
 */

'use strict';

const wsState = document.getElementById('ws-state');
const wsText = document.getElementById('ws-text');
const toast = document.getElementById('toast');
const errorBanner = document.getElementById('error-banner');
const errorText = document.getElementById('error-text');

const stage = document.getElementById('stage');
const phaseLabel = document.getElementById('phase-label');
const statusLineEl = document.getElementById('status-line');
const statusDetail = document.getElementById('status-detail');
const timerEl = document.getElementById('timer');
const timerTotal = document.getElementById('timer-total');
const timerBar = document.getElementById('timer-bar');
const timerFill = document.getElementById('timer-fill');
const modeBtns = Array.from(document.querySelectorAll('.mode-button'));
const readyBtn = document.getElementById('get-ready');
const micStateEl = document.getElementById('mic-state');
const micSwitchBtn = document.getElementById('mic-switch');
const readyChecksEl = document.getElementById('ready-checks');
const checksPill = document.getElementById('checks-pill');
const moreTimeBtn = document.getElementById('more-time');
let addingTime = false;          // a +1 on its way to the hub
const stopBtn = document.getElementById('stop');
const disconnectBtn = document.getElementById('disconnect');
const peopleLive = document.getElementById('people-live');
const startHint = document.getElementById('start-hint');

const configBadge = document.getElementById('config-badge');
const saveStateEl = document.getElementById('save-state');
const robotsSub = document.getElementById('robots-sub');
const seatList = document.getElementById('seats');
const seatsEmpty = document.getElementById('seats-empty');
const seatTemplate = document.getElementById('seat-template');

const topicEl = document.getElementById('topic');
const languageEl = document.getElementById('language');
const minutesEl = document.getElementById('minutes');
const gapEl = document.getElementById('listen-gap');
const voiceMinEl = document.getElementById('voice-min');
const bargeEl = document.getElementById('barge-in');
const slowEl = document.getElementById('slow-network');
const peopleMicEl = document.getElementById('people-mic');
const mirrorEl = document.getElementById('heads-mirror');
const simulateEl = document.getElementById('simulate');
// Robots that talk through this laptop's speaker, next to the real ones
// (the cards' + and X; 2026-10-25). The hub keeps at most these five.
const LAPTOP_KEYS = ['sim:1', 'sim:2', 'sim:3', 'sim:4', 'sim:5'];
const voiceNote = document.getElementById('voice-note');

const transcriptEl = document.getElementById('transcript');
const transcriptEmpty = document.getElementById('transcript-empty');
const turnCount = document.getElementById('turn-count');
const jumpBtn = document.getElementById('jump');
const nudgeForm = document.getElementById('nudge-form');
const nudgeText = document.getElementById('nudge-text');
const nudgeSend = document.getElementById('nudge-send');
const nudgeLast = document.getElementById('nudge-last');

const copyModal = document.getElementById('copy-modal');
const copyForm = document.getElementById('copy-form');
const copyTitle = document.getElementById('copy-title');
const copyTargets = document.getElementById('copy-targets');
const copyCancel = document.getElementById('copy-cancel');

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
const LANGUAGES = [['auto', 'Auto'], ['he', 'Hebrew'], ['en', 'English']];
const PHASE_LABEL = {
  idle: 'Not running',
  starting: 'Starting',
  speaking: 'Speaking',
  listening: 'Listening',
  human: 'People speaking',
  thinking: 'Thinking',
  stopping: 'Stopping',
  ready: 'Connected',
};
const MODE_NAME = { group: 'Group talk', interrupt: 'Interrupt mode', free: 'Free talk' };
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
// Which of a robot's fields holds the voice for each provider. Auto starts
// with ElevenLabs, so it shows (and sets) the ElevenLabs voice.
const VOICE_FIELD = { auto: 'voice_id', elevenlabs: 'voice_id', openai: 'openai_voice',
                      openrouter: 'openai_voice', gemini: 'gemini_voice' };
// Session settings the hub takes while they talk.
const LIVE_KEYS = ['topic', 'language', 'minutes', 'listen_gap_s', 'heads_mirror', 'voice_min_level',
                   'barge_in', 'slow_network'];
// The session clock runs only while the conversation itself does.
const LIVE_PHASES = ['speaking', 'listening', 'human', 'thinking'];
// One colour per seat, kept for the whole session, so a robot's lines and its
// card match at a glance. All readable on white.
const SEAT_COLORS = ['#2563eb', '#14884a', '#b4521a', '#7c3aed', '#0e7490', '#be185d'];
const SAVE_DELAY_MS = 700;       // typing
const QUICK_SAVE_MS = 150;       // a click: the robots should feel it at once
const FOLLOW_AFTER_MS = 20000;   // scrolled up in the transcript: follow again after this
const DEFAULT_SETTINGS = { topic: '', language: 'auto', minutes: 5, listen_gap_s: 0.6, simulate: false,
                           voice_min_level: 0.3, heads_mirror: false, barge_in: 'normal',
                           slow_network: true, voice_provider: 'auto',
                           director_model: 'google/gemini-3.5-flash', interrupt_level: 3,
                           vision: true, gestures: 'lively', people_mic: 'auto' };
const DEFAULT_STATUS = { phase: 'idle', speaker: null, elapsed_s: 0, detail: '' };

let S = normalize({});           // the hub's last word on everything
let draft = { settings: { ...DEFAULT_SETTINGS }, seats: [] };   // what the form shows
let dirty = false;               // the form holds edits the hub has not saved yet
let editSeq = 0;                 // bumped by every edit; tells a save what it covered
let saveTimer = null;
let saveInFlight = null;
let statusAt = performance.now();   // when S.status.elapsed_s was true
let localError = '';             // a refused request; the hub's own error wins
let linkError = '';              // the hub could not be asked at all
let loaded = false;              // a first state has arrived
let starting = '';               // the mode being started, '' when none
let stopping = false;
let gettingReady = false;        // Get ready pressed, not answered yet
let micSwitching = false;        // the mic button pressed, not answered yet
let levels = {};
let peopleLiveText = '';
let levelsTimer = null;
let localIds = 0;
let ws = null;
let backoff = 500;
let toastTimer = null;
let copyFrom = null;             // the robot whose settings the copy dialog copies

/* ---------------------------------------------------------------- helpers */

// Declarations, not arrows: the state above is built with them before this
// point in the file runs.
function arr(v) { return Array.isArray(v) ? v : []; }
function obj(v) { return v && typeof v === 'object' && !Array.isArray(v) ? v : {}; }
function str(v) { return v === null || v === undefined ? '' : String(v); }
function num(v, fallback) {
  const n = Number(v);
  return v !== null && v !== '' && Number.isFinite(n) ? n : fallback;
}

function announce(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add('visible');
  toastTimer = setTimeout(() => toast.classList.remove('visible'), 4200);
}

function clock(seconds) {
  const s = Math.max(0, Math.floor(num(seconds, 0)));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// A name the people chose may be Hebrew inside an English sentence; <bdi>
// keeps the brackets around it where they belong.
function bdi(text) {
  return el('bdi', '', text);
}

function setValue(input, value) {
  if (document.activeElement === input) return;      // never under the cursor
  const v = str(value);
  if (input.value !== v) input.value = v;
}

function fillOptions(select, options, value) {
  const focused = document.activeElement === select;   // an open list stays as it is
  const sig = JSON.stringify(options);
  if (select.dataset.sig !== sig && !focused) {
    select.textContent = '';
    options.forEach(([id, label]) => {
      const o = el('option', '', label);
      o.value = id;
      select.append(o);
    });
    select.dataset.sig = sig;
  }
  if (!focused) select.value = value;
}

/* ------------------------------------------------------------------ state */

// `st`: the session settings, whose values are a robot's defaults.
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
  return out;
}

// `group.state` may carry the object at the top level (like the main page's
// snapshot) or under `state`; a PUT may answer either way too.
function unwrapState(msg) {
  const m = obj(msg);
  const inner = obj(m.state);
  if ('seats' in inner || 'settings' in inner || 'running' in inner) return inner;
  if ('seats' in m || 'settings' in m || 'running' in m) return m;
  return null;
}

function connectedKey(key) {
  const a = S.available.find(x => x.key === key);
  return !!a && (!a.state || CONNECTED.includes(a.state));
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

function loadDraft() {
  draft = {
    settings: { ...S.settings },
    seats: withAvailable(S.seats.map(s => ({ ...s }))),
  };
}

function applyState(raw) {
  if (!raw) return;
  S = normalize(raw);
  loaded = true;
  linkError = '';
  statusAt = performance.now();
  if (!dirty && !saveInFlight) loadDraft();
  else draft.seats = withAvailable(draft.seats);
  peopleLiveText = S.people_live;
  if (S.running) localError = localError.startsWith('Could not start') ? '' : localError;

  renderConfig();
  renderStatus();
  renderTranscript();
  renderError();
}

/* ------------------------------------------------------------------ seats */

// The seat for a speaker or a transcript line, however the hub named it.
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

// A robot keeps its colour for as long as the page is open, also when
// another robot drops out or the seats are reordered.
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

/* ----------------------------------------------------------------- status */

// The big line: who has the floor, in words a visitor understands.
function statusParts(status) {
  const phase = str(status.phase) || 'idle';
  if (phase === 'speaking') {
    const seat = findSeat(status.speaker);
    const verb = status.detail === 'interrupting' ? ' cuts in' : ' is speaking';
    if (seat) {
      const live = draftSeat(seat.key) || seat;
      const parts = [bdi(live.character || live.name || live.key)];
      if (live.character && live.character !== live.name) parts.push(' (', bdi(live.name), ')');
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
  stage.dataset.phase = phase;
  phaseLabel.textContent = PHASE_LABEL[phase] || phase;
  statusLineEl.textContent = '';
  statusLineEl.append(...statusParts(status));
  // Ready already says it all in the big line.
  const detail = ['interrupting', 'the robots are listening'].includes(str(status.detail))
    || phase === 'ready' ? '' : str(status.detail);
  const modeText = S.running && S.mode ? MODE_NAME[S.mode] || S.mode : '';
  const closing = S.running && S.closing ? 'closing: each robot says its last word' : '';
  statusDetail.textContent = [modeText, closing || detail].filter(Boolean).join(' - ');
  statusDetail.classList.toggle('hidden', !statusDetail.textContent);
  renderPeopleLive();
  renderTimer();
  renderButtons();
  renderSpeaking();
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
  timerEl.textContent = clock(elapsed);
  timerTotal.textContent = clock(total);
  const share = total > 0 ? Math.min(1, elapsed / total) : 0;
  timerFill.style.width = `${(share * 100).toFixed(1)}%`;
  timerBar.classList.toggle('over', total > 0 && elapsed >= total);
}

function renderButtons() {
  const seats = draft.seats.filter(s => s.included);
  const simulate = !!draft.settings.simulate;
  const enough = seats.length >= 2 || simulate;
  const phase = S.status.phase;

  modeBtns.forEach(btn => {
    const mode = btn.dataset.mode;
    const active = S.running && S.mode === mode;
    btn.classList.toggle('active', active);
    btn.disabled = !!starting || !enough || active;
    const sub = btn.querySelector('.mode-sub');
    if (starting === mode) sub.textContent = S.connected ? 'starting…' : 'connecting…';
    else if (active) sub.textContent = 'running';
    else if (S.running) sub.textContent = 'switch to this';
    else sub.textContent = MODE_SUB[mode] || '';
  });
  const warmBusy = !!S.warm.busy;
  readyBtn.disabled = !!starting || gettingReady || warmBusy || S.running || !enough;
  readyBtn.textContent = gettingReady || warmBusy ? 'Getting ready…' : 'Get ready';
  const checks = Object.values(obj(S.warm.checks));
  readyBtn.classList.toggle('done', S.connected && checks.length > 0
    && checks.every(c => obj(c).ok === true) && !gettingReady && !warmBusy);
  renderMic();
  renderChecks();
  stopBtn.disabled = stopping || !(S.running || phase === 'starting');
  const closing = S.running && S.closing;
  stopBtn.textContent = stopping || phase === 'stopping' ? 'Stopping…' : (closing ? 'Stop now' : 'Stop');
  stopBtn.classList.toggle('closing', closing);
  stopBtn.title = closing
    ? 'The robots are saying goodbye. Press to stop at once, without the rest of the closing lines.'
    : 'End the conversation: the robot that is talking finishes, then every robot says one closing line and goodbye. Press again to stop at once. The robots stay connected.';
  moreTimeBtn.disabled = !S.running || closing || addingTime;
  disconnectBtn.disabled = stopping || !S.connected;

  let hint = '';
  if (S.connected && !S.running && !starting) hint = 'Robots connected and listening. A mode button starts at once.';
  else if (!S.running && !starting) {
    if (!enough) hint = 'Include at least two Reachys, or press + on a card to add a laptop robot.';
    else if (simulate) hint = 'Simulation: this laptop speaks and listens.';
    else {
      const away = seats.filter(s => !connectedKey(s.key)).map(s => s.name || s.key);
      hint = away.length
        ? `Not connected: ${away.join(', ')}.`
        : `${seats.length} Reachys at the table.`;
    }
  }
  startHint.textContent = hint;
  startHint.classList.toggle('warn', /^Not connected|^Include/.test(hint));
}

// Who hears the people. The DJI's battery cannot be read over USB, so what is
// shown is its signal: a dead or unplugged mic switches by itself.
function renderMic() {
  const m = S.mic;
  const health = str(m.health);
  let text;
  let cls = '';
  if (m.in_use === 'people') {
    text = `Mic: ${str(m.people_mic)}`;
    if (health === 'ok') { text += ' · signal ok'; cls = 'ok'; }
    else if (health) { text += ` · ${health}`; cls = 'warn'; }
  } else if (m.in_use === 'robots') {
    const robots = arr(m.robot_mics);
    text = `Mic: the robots' own${robots.length ? ` (${robots.join(', ')})` : ''}`;
    if (m.dji) text += ` · ${str(m.dji)} plugged in`;
  } else {
    text = m.dji ? `Mic: ${str(m.dji)} plugged in (used when the robots connect)`
                 : "Mic: no DJI plugged in · the robots' own mics";
    cls = m.dji ? 'ok' : '';
  }
  micStateEl.textContent = text;
  micStateEl.className = `mic-state ${cls}`.trim();
  const live = S.connected && (m.in_use === 'people' || m.in_use === 'robots');
  micSwitchBtn.hidden = !live || (m.in_use === 'robots' && !m.dji);
  micSwitchBtn.disabled = micSwitching;
  const back = m.in_use === 'robots';
  micSwitchBtn.textContent = back ? `Use ${str(m.dji) || 'the DJI mic'}` : "Use robots' mics";
  micSwitchBtn.classList.toggle('back', back);
}

// One chip per service checked with a real request (hub start, Get ready),
// folded into one pill: "8 checks ok", or what failed (2026-10-25).
function renderChecks() {
  const checks = obj(S.warm.checks);
  const sig = JSON.stringify(checks);
  if (readyChecksEl.dataset.sig === sig) return;
  readyChecksEl.dataset.sig = sig;
  const all = Object.entries(checks).map(([name, c]) => [name, obj(c)]);
  const bad = all.filter(([, c]) => c.ok === false).map(([name]) => name);
  const done = all.filter(([, c]) => c.ok === true).length;
  checksPill.classList.toggle('hidden', all.length === 0);
  checksPill.classList.toggle('bad', bad.length > 0);
  checksPill.classList.toggle('ok', !bad.length && done === all.length && done > 0);
  checksPill.textContent = bad.length ? `${bad.length} failed: ${bad.join(', ')}`
    : done === all.length ? `${done} checks ok` : `checking ${done}/${all.length}`;
  if (bad.length) readyChecksEl.classList.remove('hidden');
  readyChecksEl.textContent = '';
  Object.entries(checks).forEach(([name, c]) => {
    c = obj(c);
    const li = el('li', c.ok === true ? 'ok' : c.ok === false ? 'bad' : '',
      c.ok === false ? `${name}: failed` : `${name} ${(num(c.ms, 0) / 1000).toFixed(1)} s`);
    if (c.detail) li.title = str(c.detail);
    readyChecksEl.append(li);
  });
}

checksPill.addEventListener('click', () => {
  const open = readyChecksEl.classList.toggle('hidden') === false;
  checksPill.setAttribute('aria-expanded', open ? 'true' : 'false');
});

// +1: the running conversation ends a minute later (press again for more).
moreTimeBtn.addEventListener('click', async () => {
  if (moreTimeBtn.disabled) return;
  addingTime = true;
  renderButtons();
  try {
    const body = await post('/api/group/more_time', { seconds: 60 });
    if (body.ok && body.limit_s) { S.limit_s = num(body.limit_s, S.limit_s); renderTimer(); }
    else if (!body.ok) announce(`Could not add time: ${body.error}`);
  } finally {
    addingTime = false;
    renderButtons();
  }
});

readyBtn.addEventListener('click', async () => {
  if (readyBtn.disabled) return;
  gettingReady = true;
  renderButtons();
  try {
    if (dirty || saveInFlight) await save();
    const body = await post('/api/group/ready');
    if (!body.ok) {
      localError = `Could not get ready: ${body.error}`;
      announce(localError);
    } else localError = '';
  } finally {
    gettingReady = false;
    renderButtons();
    renderError();
  }
});

micSwitchBtn.addEventListener('click', async () => {
  if (micSwitchBtn.disabled) return;
  micSwitching = true;
  renderMic();
  try {
    const use = S.mic.in_use === 'robots' ? 'people' : 'robots';
    const body = await post('/api/group/mic', { use });
    if (!body.ok) announce(`Could not switch the mic: ${body.error}`);
  } finally {
    micSwitching = false;
    renderMic();
  }
});

// The card of the robot with the floor is lit.
function renderSpeaking() {
  const speaker = S.status.phase === 'speaking' ? findSeat(S.status.speaker) : null;
  seatRows.forEach((row, key) => row.classList.toggle('speaking', !!speaker && speaker.key === key));
}

function renderError() {
  const message = S.error || localError || linkError;
  errorText.textContent = message || '';
  errorBanner.classList.toggle('hidden', !message);
}

// What the person is saying, typed out as it comes (2026-10-25). The hub
// sends everything said so far every second or so; new words are typed in,
// a correction of earlier words just replaces them.
let liveShown = '';
let liveTyping = 0;

function renderPeopleLive() {
  const target = S.running ? peopleLiveText.slice(-160) : '';
  if (!target) {
    clearInterval(liveTyping);
    liveTyping = 0;
    liveShown = '';
    peopleLive.textContent = '';
    peopleLive.classList.add('hidden');
    return;
  }
  peopleLive.classList.remove('hidden');
  if (!target.startsWith(liveShown)) {
    // Keep what still matches, retype the rest.
    let same = 0;
    while (same < liveShown.length && liveShown[same] === target[same]) same++;
    liveShown = target.slice(0, same);
  }
  clearInterval(liveTyping);
  liveTyping = setInterval(() => {
    if (liveShown.length >= target.length) { clearInterval(liveTyping); liveTyping = 0; return; }
    liveShown = target.slice(0, liveShown.length + 2);
    peopleLive.textContent = `${liveShown}\u258c`;
  }, 25);
}

// Twice a second: the clock runs on between the hub's status messages.
setInterval(renderTimer, 500);

/* ----------------------------------------------------------------- levels */

function paintLevels() {
  document.querySelectorAll('.level[data-key]').forEach(bar => {
    const v = Math.max(0, Math.min(1, num(levels[bar.dataset.key], 0)));
    const fill = bar.firstElementChild;
    if (fill) fill.style.transform = `scaleX(${v})`;
  });
}

// ~8 a second while the session runs. Bars drop to zero when they stop.
function applyLevels(map) {
  levels = obj(map);
  paintLevels();
  clearTimeout(levelsTimer);
  levelsTimer = setTimeout(() => { levels = {}; paintLevels(); }, 1500);
}

/* ---------------------------------------------------------------- session */

function renderConfig() {
  const st = draft.settings;
  setValue(topicEl, st.topic);
  fillOptions(languageEl, LANGUAGES.some(([id]) => id === st.language) ? LANGUAGES
    : [...LANGUAGES, [str(st.language), str(st.language)]], str(st.language) || 'auto');
  setValue(minutesEl, st.minutes);
  setValue(gapEl, st.listen_gap_s);
  setValue(voiceMinEl, st.voice_min_level);
  if (document.activeElement !== bargeEl) bargeEl.value = str(st.barge_in) || 'normal';
  slowEl.checked = st.slow_network !== false;
  renderPeopleMic(st);
  mirrorEl.checked = !!st.heads_mirror;
  simulateEl.checked = !!st.simulate;
  simulateEl.disabled = S.connected;

  const credits = S.eleven_credits;
  let note = credits !== null ? `ElevenLabs credits: ${credits.toLocaleString()}` : '';
  if (credits !== null && credits < 1500) note += ' (low: robots on Auto use OpenAI)';
  voiceNote.textContent = note;
  voiceNote.classList.toggle('warn', credits !== null && credits < 1500);

  robotsSub.textContent = S.connected
    ? 'left to right, as the people see the table. Order, Included and Listens are fixed until Disconnect; everything else changes at once.'
    : 'left to right, as the people see the table. Everything here changes at once, also mid-conversation.';
  renderSeats();
  renderSaveState();
}

// Auto (a DJI mic if one is plugged in), the robots' own mics, or a laptop mic.
function renderPeopleMic(st) {
  const choice = str(st.people_mic) || 'auto';
  const dji = S.mics.find(n => n.toLowerCase().includes('dji'));
  const opts = [['auto', dji ? `Auto: ${dji}` : 'Auto: DJI mic (not plugged in)'],
                ['robots', "Robots' own mics"],
                ...S.mics.map(n => [n, n])];
  if (!opts.some(([id]) => id === choice)) opts.push([choice, `${choice} (not plugged in)`]);
  fillOptions(peopleMicEl, opts, choice);
  peopleMicEl.disabled = S.running;
  const active = S.people_mic_active;
  peopleMicEl.title = S.connected
    ? (active ? `Hearing the people through ${active}` : "Hearing the people through the robots' mics")
    : 'Used when the robots connect';
}

function editSetting(key, value, delay) {
  draft.settings[key] = value;
  markDirty(delay);
}

topicEl.addEventListener('input', () => editSetting('topic', topicEl.value));
languageEl.addEventListener('change', () => editSetting('language', languageEl.value, QUICK_SAVE_MS));
minutesEl.addEventListener('input', () => {
  const n = num(minutesEl.value, NaN);
  if (n > 0) editSetting('minutes', n);
});
gapEl.addEventListener('input', () => {
  const n = num(gapEl.value, NaN);
  if (n >= 0) editSetting('listen_gap_s', n);
});
voiceMinEl.addEventListener('input', () => {
  const n = num(voiceMinEl.value, NaN);
  if (n >= 0) editSetting('voice_min_level', n);
});
bargeEl.addEventListener('change', () => editSetting('barge_in', bargeEl.value, QUICK_SAVE_MS));
slowEl.addEventListener('change', () => editSetting('slow_network', slowEl.checked, QUICK_SAVE_MS));
peopleMicEl.addEventListener('change', () => editSetting('people_mic', peopleMicEl.value, QUICK_SAVE_MS));
mirrorEl.addEventListener('change', () => editSetting('heads_mirror', mirrorEl.checked, QUICK_SAVE_MS));
simulateEl.addEventListener('change', () => editSetting('simulate', simulateEl.checked, QUICK_SAVE_MS));

/* ------------------------------------------------------------------ cards */

const seatRows = new Map();      // seat key -> card element

function renderSeats() {
  const keep = new Set();
  draft.seats.forEach((seat, i) => {
    let row = seatRows.get(seat.key);
    if (!row) {
      row = makeSeatRow(seat.key);
      seatRows.set(seat.key, row);
    }
    keep.add(seat.key);
    fillSeatRow(row, seat, i);
    // Move a card only when it is out of place: moving the card under the
    // cursor would drop the focus mid-word.
    if (seatList.children[i] !== row) seatList.insertBefore(row, seatList.children[i] || null);
  });
  seatRows.forEach((row, key) => {
    if (!keep.has(key)) { row.remove(); seatRows.delete(key); }
  });
  // All the robots side by side when they fit (up to 5), else two rows.
  const n = draft.seats.length;
  seatList.style.setProperty('--cols', String(Math.max(1, n <= 5 ? n : Math.ceil(n / 2))));
  seatList.toggleAttribute('data-many', n >= 4);
  seatList.closest('.board').toggleAttribute('data-many', n >= 4);
  seatList.closest('.board').dataset.robots = String(n);
  seatsEmpty.classList.toggle('hidden', n > 0);
  paintLevels();
  renderSpeaking();
}

function voiceOptions(provider, seat) {
  const defaults = obj(seat.default_voices);
  if (provider === 'auto' || provider === 'elevenlabs') {
    const def = S.voices.find(v => v.voice_id === defaults.elevenlabs);
    const list = [['', `Default${def ? ` (${def.name})` : ''}`]];
    S.voices.forEach(v => list.push([str(v.voice_id), str(v.name) || str(v.voice_id)]));
    // A voice the hub no longer lists is kept, not silently swapped.
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
  // OpenRouter takes fewer voices than OpenAI (same field): say so.
  const mine = str(seat[VOICE_FIELD[provider]]);
  if (mine && !own.some(v => v.id === mine)) list.push([mine, `${mine} (not here: uses Default)`]);
  return list;
}

function fillSeatRow(row, seat, i) {
  const last = draft.seats.length - 1;
  const locked = S.connected;    // order, Included and Listens wait for Disconnect
  row.style.setProperty('--seat-color', seatColor(seat));
  row.classList.toggle('excluded', !seat.included);
  row.querySelector('.seat-pos').textContent = String(i + 1);
  row.querySelector('.seat-robot').textContent = seat.name || seat.key;

  const a = S.available.find(x => x.key === seat.key);
  const stateEl = row.querySelector('.seat-state');
  stateEl.textContent = a ? (STATUS_TEXT[a.state] || str(a.state) || 'Connected') : 'Not connected';
  stateEl.classList.toggle('ok', connectedKey(seat.key));

  const level = row.querySelector('.level');
  level.dataset.key = seat.key;
  level.classList.toggle('deaf', !seat.listen);
  const echo = obj(S.echo[seat.key]);
  const peak = num(echo.peak_excess_db, -99);
  level.title = peak > -90
    ? `Microphone level. Echo check: its own voice peaked ${peak.toFixed(1)} dB over the learned echo (keep well under 8 dB for Normal).`
    : 'Microphone level';

  const name = row.querySelector('.seat-character');
  setValue(name, seat.character);
  const twin = seat.character && draft.seats.some(s => s.key !== seat.key && s.included && seat.included
    && s.character.trim().toLowerCase() === seat.character.trim().toLowerCase());
  row.querySelector('.name-warn').classList.toggle('hidden', !twin);

  const included = row.querySelector('.seat-included');
  const listen = row.querySelector('.seat-listen');
  included.checked = !!seat.included;
  listen.checked = !!seat.listen;
  included.disabled = locked;
  listen.disabled = locked;
  row.querySelector('.seat-vision').checked = !!seat.vision;
  row.querySelector('[data-move="-1"]').disabled = locked || i === 0;
  row.querySelector('[data-move="1"]').disabled = locked || i === last;
  const simulating = !!draft.settings.simulate;
  const onLaptop = seat.key.startsWith('sim:');
  const add = row.querySelector('.seat-add');
  const remove = row.querySelector('.seat-remove');
  add.hidden = remove.hidden = simulating;
  add.disabled = locked || laptopKeys().length >= LAPTOP_KEYS.length;
  remove.disabled = locked || (!onLaptop && !seat.included);
  add.title = locked ? 'Disconnect first to add a robot'
    : (add.disabled ? 'No more robots fit' : 'Add a robot here (it talks through this laptop\'s speaker)');
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
  row.querySelectorAll('.segmented [data-gestures]').forEach(b => {
    const on = b.dataset.gestures === seat.gestures;
    b.classList.toggle('on', on);
    b.setAttribute('aria-checked', on ? 'true' : 'false');
  });

  const slider = row.querySelector('.seat-loudness');
  const loud = Math.round(num(seat.loudness, 150));
  if (document.activeElement !== slider) slider.value = String(loud);
  row.querySelector('.volume-value').textContent = `${slider.value}%`;
  slider.closest('.cfield').title = '100 = natural level; the robot\'s speaker is already at its maximum, above 100 the hub boosts the audio';

  // What this robot uses right now (the hub falls back when a key fails).
  const now = [];
  const vb = str(S.voice_backend[seat.key]);
  const br = str(S.brain[seat.key]);
  if (vb) now.push(`Voice: ${PROVIDER_NAME[vb] || vb}`);
  if (br) now.push(`writing via ${PROVIDER_NAME[br] || br}`);
  const nowEl = row.querySelector('.card-now');
  nowEl.textContent = now.join(', ');
  nowEl.title = nowEl.textContent;
  row.querySelector('.copy-button').disabled = draft.seats.length < 2;
}

function makeSeatRow(key) {
  const row = seatTemplate.content.firstElementChild.cloneNode(true);
  row.dataset.key = key;
  row.addEventListener('input', (event) => editSeat(key, event.target, 'input'));
  row.addEventListener('change', (event) => editSeat(key, event.target, 'change'));
  row.addEventListener('click', (event) => {
    const move = event.target.closest('[data-move]');
    if (move && !move.disabled) { moveSeat(key, Number(move.dataset.move)); return; }
    const lvl = event.target.closest('[data-level]');
    if (lvl) { setSeat(key, { interrupt_level: Number(lvl.dataset.level) }, QUICK_SAVE_MS); return; }
    const g = event.target.closest('[data-gestures]');
    if (g) { setSeat(key, { gestures: g.dataset.gestures }, QUICK_SAVE_MS); return; }
    if (event.target.closest('.seat-add')) { addSeat(key); return; }
    if (event.target.closest('.seat-remove')) { removeSeat(key); return; }
    if (event.target.closest('.copy-button')) openCopy(key);
  });
  return row;
}

// Change one robot's own settings: kept in the draft and saved shortly.
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
    target.closest('.card').querySelector('.volume-value').textContent = `${target.value}%`;
    // The level is heard when the drag ends.
    if (kind === 'change') markDirty(QUICK_SAVE_MS);
  }
}

function laptopKeys() {
  return draft.seats.map(s => s.key).filter(k => LAPTOP_KEYS.includes(k));
}

// +: a new robot on this laptop's speaker, right after this card. The hub
// gives it a label, a position and a voice no other robot has.
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

// X: a laptop robot goes away; a real Reachy only leaves the table.
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
  // Keep the keyboard on the same robot's button, or its twin at an end.
  const row = seatRows.get(key);
  if (row) {
    const same = row.querySelector(`[data-move="${step}"]`);
    const other = row.querySelector(`[data-move="${-step}"]`);
    (same && !same.disabled ? same : other).focus();
  }
}

/* ------------------------------------------------------------------- copy */

function openCopy(key) {
  const from = draftSeat(key);
  if (!from) return;
  copyFrom = key;
  copyTitle.textContent = `Copy ${from.character || from.name}'s settings`;
  copyTargets.textContent = '';
  draft.seats.filter(s => s.key !== key).forEach(s => {
    const label = el('label', 'check');
    const box = el('input');
    box.type = 'checkbox';
    box.value = s.key;
    box.checked = true;
    label.append(box, ` ${s.character || s.name}`);
    if (s.character && s.name) label.append(el('span', 'seat-state', ` ${s.name}`));
    copyTargets.append(label);
  });
  copyModal.classList.remove('hidden');
  const first = copyForm.querySelector('input');
  if (first) first.focus();
}

function closeCopy() {
  copyModal.classList.add('hidden');
  const row = seatRows.get(copyFrom);
  copyFrom = null;
  if (row) row.querySelector('.copy-button').focus();
}

copyForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const from = draftSeat(copyFrom);
  if (!from) { closeCopy(); return; }
  const targets = Array.from(copyTargets.querySelectorAll('input:checked')).map(b => b.value);
  const what = Array.from(copyForm.querySelectorAll('.copy-what input:checked')).map(b => b.value);
  const fields = what.flatMap(w => (w === 'voices' ? ['voice_id', 'openai_voice', 'gemini_voice'] : [w]));
  if (!targets.length || !fields.length) { announce('Pick at least one robot and one setting.'); return; }
  targets.forEach(key => {
    const seat = draftSeat(key);
    if (seat) fields.forEach(f => { seat[f] = from[f]; });
  });
  const names = targets.map(k => { const s = draftSeat(k); return s ? s.character || s.name : k; });
  closeCopy();
  markDirty(QUICK_SAVE_MS);
  renderSeats();
  announce(`Copied to ${names.join(', ')}.`);
});
copyCancel.addEventListener('click', closeCopy);
copyModal.addEventListener('click', (event) => { if (event.target === copyModal) closeCopy(); });
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !copyModal.classList.contains('hidden')) closeCopy();
});

/* ------------------------------------------------------------------- save */

let saveNote = { text: '', kind: '' };

function renderSaveState() {
  let badge = 'saved';
  let kind = 'ok';
  if (!loaded) { badge = 'loading'; kind = ''; }
  else if (saveInFlight) { badge = 'saving'; kind = ''; }
  else if (dirty) { badge = 'not saved yet'; kind = 'problem'; }
  else if (saveNote.kind === 'error') { badge = 'not saved'; kind = 'problem'; }
  configBadge.textContent = badge;
  configBadge.className = `save-badge${kind ? ' ' + kind : ''}`;
  saveStateEl.textContent = saveNote.text;
  saveStateEl.className = `save-state${saveNote.kind ? ' ' + saveNote.kind : ''}`;
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

function errorFrom(body, res) {
  const b = obj(body);
  if (b.error) return str(b.error);
  if (typeof b.detail === 'string') return b.detail;
  if (Array.isArray(b.detail) && b.detail.length) return str(obj(b.detail[0]).msg) || 'invalid settings';
  if (res && (res.status === 404 || res.status === 405)) {
    return 'This hub has no group conversation yet. Restart the hub with the new code.';
  }
  return res ? `the hub answered ${res.status}` : 'no answer';
}

// The robots' own settings always go; while they talk the hub keeps the
// order, Included and Listens as they are, and takes only the session
// settings it can change live.
function seatPayload(s) {
  // A robot just added with +: the hub fills in its label, position and voice.
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
  try {
    const res = await fetch('/api/group/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => null);
    if (res.ok && obj(data).ok !== false) {
      if (seq === editSeq) dirty = false;
      setSaveNote(dirty ? 'Saving shortly…' : 'Saved.', dirty ? '' : 'ok');
      const st = unwrapState(data);
      if (st) { saveInFlight = null; applyState(st); }
      return true;
    }
    if (res.status === 409) {
      if (seq === editSeq) dirty = false;
      setSaveNote(`Not saved: ${errorFrom(data, res)}`, 'error');
      saveInFlight = null;
      loadDraft();
      renderConfig();
      return false;
    }
    setSaveNote(`Not saved: ${errorFrom(data, res)}. Trying again…`, 'error');
    retrySave();
    return false;
  } catch (err) {
    setSaveNote(`Not saved: the hub did not answer (${err.message || err}). Trying again…`, 'error');
    retrySave();
    return false;
  }
}

// The hub restarting or a network blip: the edit is still wanted, so it is
// sent again (else the cards would stop following the hub).
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

/* ------------------------------------------------------------- transcript */

const turnEls = new Map();       // turn id -> line element
let turnOrder = [];
// Follow the newest line, unless the operator scrolled up to read; then
// follow again when they are back at the bottom or after a while.
let following = true;
let scrolledAt = 0;
let programmatic = 0;
let unseen = 0;

function nearBottom() {
  return transcriptEl.scrollHeight - transcriptEl.scrollTop - transcriptEl.clientHeight < 60;
}

function scrollToEnd() {
  programmatic = performance.now();
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
  following = true;
  unseen = 0;
  jumpBtn.classList.add('hidden');
}

function turnId(t, i) {
  return t.id !== undefined && t.id !== null ? String(t.id) : `at-${i}`;
}

function renderTranscript() {
  const turns = S.transcript;
  const ids = turns.map(turnId);
  // The usual case is lines added at the end: keep the old ones as they are.
  const prefix = turnOrder.length <= ids.length && turnOrder.every((id, i) => id === ids[i]);
  if (!prefix) {
    transcriptEl.textContent = '';
    turnEls.clear();
    turnOrder = [];
  }
  const added = ids.length - turnOrder.length;
  for (let i = turnOrder.length; i < ids.length; i++) {
    const li = el('li', 'turn');
    turnEls.set(ids[i], li);
    transcriptEl.append(li);
  }
  turnOrder = ids;
  turns.forEach((t, i) => fillTurn(turnEls.get(ids[i]), t));
  markCurrent();

  transcriptEmpty.classList.toggle('hidden', turns.length > 0);
  const said = turns.filter(t => t.kind !== 'note').length;
  turnCount.textContent = said ? `(${said})` : '';

  if (!following && performance.now() - scrolledAt > FOLLOW_AFTER_MS) following = true;
  if (following || !prefix) scrollToEnd();
  else if (added > 0) {
    unseen += added;
    jumpBtn.textContent = `Jump to latest (${unseen} new)`;
    jumpBtn.classList.remove('hidden');
  }
}

// The line being said now: the last robot or people line while one speaks.
function markCurrent() {
  const phase = S.status.phase;
  let current = null;
  if (S.running && (phase === 'speaking' || phase === 'human')) {
    for (let i = S.transcript.length - 1; i >= 0; i--) {
      const t = S.transcript[i];
      if (t.kind === 'note') continue;
      if ((phase === 'speaking' && t.kind !== 'human') || (phase === 'human' && t.kind === 'human')) {
        current = turnEls.get(turnId(t, i));
      }
      break;
    }
  }
  turnEls.forEach(li => li.classList.toggle('current', li === current));
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

function fillTurn(li, t) {
  if (!li) return;
  const kind = ['robot', 'human', 'note'].includes(t.kind)
    ? t.kind : (t.who === 'people' ? 'human' : 'robot');
  const seat = kind === 'robot' ? findSeat(t.who) : null;
  const color = seatColor(seat);
  const sig = JSON.stringify([t, color, seat && seat.name]);
  if (li.dataset.sig === sig) return;
  li.dataset.sig = sig;

  const current = li.classList.contains('current');
  li.className = `turn turn-${kind}` + (t.cut ? ' turn-cut' : '') + (current ? ' current' : '');
  li.style.setProperty('--seat-color', color || '');
  li.textContent = '';
  const text = str(t.text);

  if (kind === 'note') {
    const p = el('p', 'turn-text', text);
    p.dir = 'auto';
    if (t.t !== undefined && t.t !== null) p.prepend(el('time', 'turn-time', clock(t.t)));
    li.append(p);
    return;
  }

  const head = el('div', 'turn-head');
  const who = el('span', 'turn-who');
  who.dir = 'auto';
  // The name it had when it said the line (a rename later does not rewrite it).
  if (kind === 'human') who.textContent = 'People';
  else who.textContent = str(t.character) || (seat && seat.character) || (seat && seat.name) || str(t.who) || 'Robot';
  head.append(who);
  if (kind === 'robot') {
    const robotName = (seat && seat.name) || str(t.who);
    if (robotName && robotName !== who.textContent) head.append(el('span', 'turn-robot-name', robotName));
    if (t.move) head.append(el('span', 'turn-move', str(t.move)));
  }
  const meta = el('span', 'turn-meta');
  if (t.latency_ms !== undefined && t.latency_ms !== null && Number.isFinite(Number(t.latency_ms))) {
    meta.append(el('span', 'turn-latency', `${Math.round(Number(t.latency_ms))} ms`));
  }
  if (t.t !== undefined && t.t !== null) meta.append(el('time', 'turn-time', clock(t.t)));
  head.append(meta);

  const p = el('p', 'turn-text' + (text ? '' : ' pending'));
  p.dir = 'auto';
  p.append(el('span', 'said', text || (kind === 'human' ? 'listening…' : '…')));
  if (t.cut) p.append(el('span', 'cut-tag', '(cut off)'));
  li.append(head, p);
}

transcriptEl.addEventListener('scroll', () => {
  if (performance.now() - programmatic < 200) return;   // our own scroll
  if (nearBottom()) {
    following = true;
    unseen = 0;
    jumpBtn.classList.add('hidden');
  } else {
    following = false;
    scrolledAt = performance.now();
  }
});
jumpBtn.addEventListener('click', scrollToEnd);
// The transcript's height changes with the window: stay at the bottom.
if (window.ResizeObserver) {
  new ResizeObserver(() => { if (following) scrollToEnd(); }).observe(transcriptEl);
}

/* ---------------------------------------------------------------- actions */

// A route this hub does not have yet answers 404; say so in words.
async function post(url, payload) {
  try {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const body = obj(await res.json().catch(() => ({})));
    if (body.ok === undefined) body.ok = res.ok;
    if (!body.ok && !body.error) body.error = errorFrom(body, res);
    return body;
  } catch (err) {
    return { ok: false, error: `the hub did not answer (${err.message || err})` };
  }
}

async function startMode(mode) {
  starting = mode;
  renderButtons();
  try {
    if (dirty || saveInFlight) {
      const saved = await save();
      if (!saved || dirty) {
        localError = 'The setup could not be saved, so the conversation did not start.';
        return;
      }
    }
    const body = await post('/api/group/start', { mode });
    if (body.ok) localError = '';
    else {
      localError = `Could not start: ${body.error}`;
      announce(localError);
    }
  } finally {
    starting = '';
    renderButtons();
    renderError();
  }
}

modeBtns.forEach(btn => btn.addEventListener('click', () => {
  if (!btn.disabled) startMode(btn.dataset.mode);
}));

disconnectBtn.addEventListener('click', async () => {
  if (disconnectBtn.disabled) return;
  stopping = true;
  renderButtons();
  try {
    const body = await post('/api/group/disconnect');
    if (!body.ok) announce(`Could not disconnect: ${body.error}`);
  } finally {
    stopping = false;
    renderButtons();
  }
});

stopBtn.addEventListener('click', async () => {
  if (stopBtn.disabled) return;
  stopping = true;
  renderButtons();
  try {
    const body = await post('/api/group/stop', { now: !!(S.running && S.closing) });
    if (body.ok) localError = '';
    else {
      localError = `Could not stop: ${body.error}`;
      announce(localError);
    }
  } finally {
    stopping = false;
    renderButtons();
    renderError();
  }
});

// 0-5 on the keyboard set every robot's interrupting level at once (a quick
// switch mid-demo), unless typing somewhere.
document.addEventListener('keydown', (event) => {
  const t = event.target;
  if (!copyModal.classList.contains('hidden')) return;
  if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (!/^[0-5]$/.test(event.key) || !draft.seats.length) return;
  const level = Number(event.key);
  draft.seats.forEach(s => { s.interrupt_level = level; });
  markDirty(QUICK_SAVE_MS);
  renderSeats();
  announce(`Interrupting ${level} (${LEVEL_TEXT[level]}) for every robot.`);
});

nudgeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = nudgeText.value.trim();
  if (!text) { nudgeText.focus(); return; }
  nudgeSend.disabled = true;
  try {
    const body = await post('/api/group/nudge', { text });
    if (body.ok) {
      nudgeText.value = '';
      nudgeLast.textContent = `Last steer: ${text}`;
      nudgeLast.classList.remove('hidden');
      announce('Sent. The next line follows it.');
    } else {
      announce(`Not sent: ${body.error}`);
    }
  } finally {
    nudgeSend.disabled = false;
    nudgeText.focus();
  }
});

/* -------------------------------------------------------------- transport */

function handle(msg) {
  const m = obj(msg);
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
    case 'heartbeat': break;
  }
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/group`);

  ws.onopen = () => {
    backoff = 500;
    wsState.classList.add('live');
    wsText.textContent = 'live';
  };
  ws.onmessage = (e) => {
    let msg = null;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    try { handle(msg); } catch (err) { console.error('group page:', err); }
  };
  ws.onclose = () => {
    wsState.classList.remove('live');
    wsText.textContent = 'reconnecting';
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 10000);
  };
  ws.onerror = () => ws.close();
}

// The socket sends the whole state on connect; this first fetch only makes
// a hub without the group routes say so instead of showing an empty page.
async function loadState() {
  try {
    const res = await fetch('/api/group/state');
    const data = await res.json().catch(() => null);
    if (res.ok && unwrapState(data)) {
      applyState(unwrapState(data));
      return;
    }
    linkError = errorFrom(data, res);
  } catch (err) {
    linkError = `The hub did not answer (${err.message || err}).`;
  }
  renderError();
}

renderConfig();
renderStatus();
renderTranscript();
loadState();
connect();

/* --------------------------------------------------------------- tooltips */
// Every control explains itself when the mouse rests on it (Tomer,
// 2026-10-25). The explanations are the elements' titles; they move into
// data-tip so the browser's own slow tooltip never shows, and one quick
// tooltip of ours shows them instead. Titles set later by the code are
// caught the same way.
const tipEl = document.createElement('div');
tipEl.className = 'tip';
tipEl.setAttribute('role', 'tooltip');
document.body.append(tipEl);
let tipFor = null;
let tipTimer = 0;

function adoptTitle(node) {
  if (node && node.hasAttribute && node.hasAttribute('title')) {
    const t = node.getAttribute('title');
    node.removeAttribute('title');
    if (t) node.dataset.tip = t;
  }
}

function adoptAll(root) {
  root.querySelectorAll('[title]').forEach(adoptTitle);
}

adoptAll(document);
document.querySelectorAll('template').forEach(t => adoptAll(t.content));
new MutationObserver(records => records.forEach(r => {
  if (r.type === 'attributes') adoptTitle(r.target);
  else r.addedNodes.forEach(n => { if (n.nodeType === 1) { adoptTitle(n); adoptAll(n); } });
})).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] });

function placeTip(target) {
  const r = target.getBoundingClientRect();
  const w = tipEl.offsetWidth;
  const h = tipEl.offsetHeight;
  let x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
  let y = r.bottom + 8;
  if (y + h > window.innerHeight - 8) y = Math.max(8, r.top - h - 8);
  tipEl.style.left = `${x}px`;
  tipEl.style.top = `${y}px`;
}

function hideTip() {
  clearTimeout(tipTimer);
  tipFor = null;
  tipEl.classList.remove('on');
}

document.addEventListener('mouseover', (event) => {
  const target = event.target.closest && event.target.closest('[data-tip]');
  if (target === tipFor) return;
  hideTip();
  if (!target || !target.dataset.tip) return;
  tipFor = target;
  tipTimer = setTimeout(() => {
    if (tipFor !== target || !target.isConnected) return;
    tipEl.textContent = target.dataset.tip;
    placeTip(target);
    tipEl.classList.add('on');
  }, 300);
});
document.addEventListener('mousedown', hideTip);
document.addEventListener('scroll', hideTip, true);
