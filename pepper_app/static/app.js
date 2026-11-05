// Pepper dashboard. State arrives on /api/ws (a snapshot, then events); every
// control is a POST to /api/*. The look follows docs/design/PepperDash.dc.html;
// every control of the old Pepper Operator page is here (docs/parity/pepper.md).
const $ = id => document.getElementById(id);
const ICON = name => `<svg class="icon"><use href="#i-${name}"/></svg>`;
// Only movements tested on this Pepper (agent/pepper_agent.py has the exact values).
const MOVES = [['wave', 'Wave'], ['yes', 'Nod yes'], ['no', 'Shake no'], ['arms_up', 'Both arms up'],
               ['arms_wide', 'Arms wide'], ['right_arm_up', 'Right arm up'], ['left_arm_up', 'Left arm up'],
               ['hands', 'Open/close hands'], ['walk', 'Walking']];
const STATE = {
  off: ['IDLE', 'idle'], waiting: ['WAITING FOR ANSWER', 'wait'], thinking: ['THINKING', 'think'],
  speaking: ['SPEAKING', 'speak'], paused: ['PAUSED · YOU', 'paused'], stuck: ['AI STUCK', 'stuck'],
  searching: ['SEARCHING', 'think'],
};
const FALLBACK = 'fallback: Pepper connects back';
let S = { cfg: {}, health: {}, ai: { state: 'off' }, screen: null, decks: [], el_voices: [], voices: [],
          hearing: '', web: {}, keys: {}, emoji_candidates: [] };
let slideIdx = 0, lastFrame = 0, visionAt = 0, wsUp = false;
const pepperBubbles = new Map();
const hhmmss = ts => new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString('en-GB');
const mmss = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
const esc = t => String(t == null ? '' : t).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// ------------------------------------------------------------ helpers
function sentence(msg) {
  msg = String(msg || '').trim().replace(/\s+--\s+(\S)/g, (_, c) => '. ' + c.toUpperCase());
  if (!msg) return msg;
  msg = msg[0].toUpperCase() + msg.slice(1);
  return /[.!?…:)]$/.test(msg) ? msg : msg + '.';
}
async function api(path, body, method = 'POST') {
  try {
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                                  body: body === undefined ? undefined : JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { toast(sentence(j.detail || j.error || ('HTTP ' + r.status)), true); return null; }
    return j;
  } catch (e) { toast("The dashboard server isn't answering.", true); return null; }
}
let toastTimer;
function toast(msg, bad = false) {
  const el = $('toast');
  el.textContent = msg; el.classList.toggle('bad', bad); el.hidden = false; el.style.opacity = 1;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.opacity = 0; setTimeout(() => { el.hidden = true; }, 250); }, 4500);
}
function setOpt(key, value) { S.cfg[key] = value; renderCfg(); return api('/api/options', { [key]: value }); }
function stick(box) { return box.scrollTop + box.clientHeight >= box.scrollHeight - 40; }

// ------------------------------------------------------------ event log
function addLog(l) {
  const d = document.createElement('div');
  if (l.level === 'WARNING') d.className = 'w';
  else if (l.level === 'ERROR' || l.level === 'CRITICAL') d.className = 'e';
  const t = document.createElement('span'); t.className = 't'; t.textContent = hhmmss(l.t);
  d.append(t, ` ${l.level.padEnd(7)} ${l.msg}`);
  const box = $('log'), keep = stick(box);
  box.append(d);
  while (box.childElementCount > 600) box.firstChild.remove();
  if (keep) box.scrollTop = 1e9;
}
$('copy').onclick = () => navigator.clipboard?.writeText($('log').innerText).then(
  () => { $('copied').textContent = 'Copied'; setTimeout(() => { $('copied').textContent = ''; }, 1500); },
  () => { $('copied').textContent = 'Copy failed'; });
$('logs-btn').onclick = () => {
  $('logpnl').scrollIntoView({ behavior: 'smooth', block: 'center' });
  flash($('logpnl'));
};
function flash(el) { el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }

// ------------------------------------------------------------ chat
function pill(cls, html) {
  const d = document.createElement('span');
  d.className = 'ev' + (cls ? ' ' + cls : '');
  d.innerHTML = html;
  return d;
}
function addChat(e) {
  const c = $('chat'), keep = stick(c);
  c.querySelector('.ev.hint')?.remove();
  if (e.role === 'heard') {
    const d = document.createElement('div');
    d.className = 'heard'; d.dir = 'auto'; d.title = e.text;
    d.innerHTML = '<span class="t"></span><button class="btn btn-quiet btn-xs" type="button">Accept</button>';
    d.querySelector('.t').textContent = `Heard, not used: “${e.text}” (${e.why || 'not an answer'})`;
    d.querySelector('button').onclick = async () => { if (await api('/api/turn/accept', { text: e.text })) d.remove(); };
    c.append(d);
  } else if (e.role === 'web') {
    const d = pill('web' + (e.ok === false ? ' fail' : ''), ICON('globe') + '<span></span>');
    d.lastChild.textContent = e.text;
    c.append(d);
  } else if (e.role === 'event' || e.role === 'tap') {
    const d = pill(e.role === 'tap' ? 'tap' : '', '');
    d.textContent = e.role === 'tap' ? `Tapped the screen: ${e.text}` : e.text;
    c.append(d);
  } else if (e.role === 'hint') {
    const d = pill('hint', ''); d.textContent = e.text; c.append(d);
  } else {
    let b = e.role === 'pepper' && e.id ? pepperBubbles.get(e.id) : null;
    if (!b) {
      b = document.createElement('div');
      b.className = 'pb ' + (e.role === 'user' ? 'per' : e.role === 'woz' ? 'woz' : 'pep');
      // The text gets its own direction: a Hebrew line under the English name reads right to left.
      b.innerHTML = '<span class="who2"></span><span class="txt" dir="auto"></span>';
      b.firstChild.textContent = { pepper: 'Pepper', user: 'Person', woz: 'Pepper · you (Wizard of Oz)' }[e.role] || e.role;
      c.append(b);
      if (e.role === 'pepper' && e.id) pepperBubbles.set(e.id, b);
    }
    b.querySelector('.txt').textContent = e.text;
    b.classList.toggle('part', !!e.partial);
  }
  while (c.childElementCount > 300) c.firstChild.remove();
  if (keep) c.scrollTop = 1e9;
}

// ------------------------------------------------------------ top bar
function chip(dot, text, cls) {
  $(dot).className = 'pdot ' + cls;
  return text;
}
function renderHealth() {
  const h = S.health || {}, r = h.robot || {}, st = r.status || {}, sc = h.screen || {};
  const ok = r.state === 'connected';
  $('charge-note').hidden = !(ok && st.charging);
  let text, cls;
  if (!wsUp) { text = 'Dashboard server stopped · retrying'; cls = 'bad'; }
  else if (ok) {
    const bat = st.battery == null ? '' : ` · ${ICON('battery')} ${Math.round(+st.battery)}%${st.charging ? ', charging' : ''}`;
    text = `${esc(r.ip)}${bat}${r.mode === 'connect_back' ? ' · fallback link' : ''}`; cls = 'ok';
  } else if (r.state === 'deploying' || r.state === 'starting') {
    text = (r.detail || '').startsWith(FALLBACK) ? 'Fallback: Pepper connects back' : 'Starting its agent… up to 60 s';
    cls = 'warn';
  } else if (r.state === 'lost') { text = "The agent's connection dropped · trying again in 20 s"; cls = 'bad'; }
  else if ((r.detail || '').includes('without a robot address')) { text = 'Started without a robot address · test mode'; cls = 'bad'; }
  else { text = 'Pepper is not connected'; cls = 'bad'; }
  chip('robot-dot', '', cls);
  $('robot-text').innerHTML = text;     // built here from numbers and the address the hub gave
  const info = r.info || {};
  $('robot-chip').title = ok
    ? `${info.name || 'Pepper'} · NAOqi ${info.naoqi || '?'} · ${st.posture || '?'} · speaker: ${r.speaker_mode || '?'}`
      + (r.mode === 'connect_back' ? `\n${r.detail}` : '')
    : (r.detail || '');
  // The full reason when Pepper could not be reached (the firewall hint, a robot log line).
  const longNote = wsUp && r.state === 'failed' && r.detail && !r.detail.includes('without a robot address');
  const fallbackNote = wsUp && r.state === 'deploying' && (r.detail || '').startsWith(FALLBACK);
  const noSpeaker = wsUp && ok && (r.speaker_mode == null || r.speaker_mode === 'none');
  $('robot-note').hidden = !(longNote || fallbackNote || noSpeaker);
  $('robot-note').className = 'warnbar' + (longNote ? ' err' : '');
  $('robot-note-text').textContent = longNote || fallbackNote ? sentence(r.detail)
    : noSpeaker ? "Pepper's speaker can't play audio: the AI can't talk. Wizard of Oz still works in Pepper's own voice (English)." : '';
  // The tablet
  let tt;
  if (sc.connected) { tt = `Tablet live · ${Math.round(sc.seen_s || 0)} s`; chip('tablet-dot', '', 'ok'); }
  else {
    tt = sc.seen_s == null ? 'Tablet not connected yet · people see nothing'
                           : `Tablet lost · ${Math.round(sc.seen_s)} s ago · people see nothing`;
    chip('tablet-dot', '', 'bad');
  }
  $('tablet-text').textContent = tt;
  $('tablet-chip').title = tt;
  $('tablet-reload').hidden = !!sc.connected;
  $('screen-off').hidden = !!sc.connected;
  document.querySelectorAll('.needs-robot').forEach(b => { b.disabled = !ok; });
  document.querySelectorAll('#moves .btn').forEach(b => { b.disabled = !ok; });
  if (st.volume != null && document.activeElement !== $('vol')) { $('vol').value = st.volume; $('volv').textContent = st.volume + '%'; }
  if (!ok) $('volv').textContent = '–';
  // Face tracking: the robot's real state (ALBasicAwareness), not a guess.
  const aw = ok ? st.awareness : null;
  $('tracking').classList.toggle('on', aw === true);
  $('tracking').setAttribute('aria-checked', aw === true ? 'true' : 'false');
  $('tracking-now').textContent = aw == null ? '–' : aw ? 'On now' : 'Off now';
  $('phrases-ready').textContent = h.phrases_ready ? `${h.phrases_ready} offline` : '';
  $('phrases-ready').title = 'Quick phrases made ahead in the current voice: they play without the network';
  renderMic();
}
function renderKeys() {
  const k = S.keys || {}, g = k.gpt || { has: S.has_key }, e = k.eleven || { has: S.has_eleven };
  const gb = $('key-gpt'), eb = $('key-eleven');
  const mono = text => { const m = document.createElement('span'); m.className = 'mono'; m.textContent = text; return m; };
  if (g.has) { gb.className = 'badge'; gb.replaceChildren(mono(`GPT${g.tail ? ' ··' + g.tail : ' key'}`)); }
  else { gb.className = 'badge bad'; gb.textContent = 'No GPT key · add one on the Pepper card'; }
  gb.title = g.has ? 'GPT key, picked on the Pepper card. A new pick applies at the next Launch.' : 'No GPT key: add one on the Pepper card in the hub. Free conversation needs it; the scripted demo needs it and an ElevenLabs key.';
  if (e.has) { eb.className = 'badge'; eb.replaceChildren(mono(`ElevenLabs${e.tail ? ' ··' + e.tail : ' key'}`)); }
  else { eb.className = 'badge warn'; eb.textContent = 'No ElevenLabs key · Wizard of Oz uses the OpenAI voice'; }
  eb.title = e.has ? 'ElevenLabs key. A new pick applies at the next Launch.' : 'No ElevenLabs key: Wizard of Oz and the walk line use the OpenAI voice, and the scripted demo cannot start.';
}

// ------------------------------------------------------------ mic line
function renderMic() {
  const h = S.health || {}, ai = S.ai || {}, m = $('mic');
  m.className = 'srow micline';
  if (!ai.running) { m.innerHTML = ''; return; }
  const line = (text, cls = '') => { m.className = 'srow micline ' + cls; m.innerHTML = ICON('mic') + '<span class="hear"></span>'; m.lastChild.textContent = text; };
  if (h.speaking) return line('Pepper speaking · mic shut');
  if (ai.paused) return line('AI paused · you have the floor');
  if (ai.state === 'searching') return line('Pepper is looking it up online · mic shut');
  if (ai.turn !== 'waiting') return line("Pepper's turn · mic shut");
  if (S.hearing) { line(`hearing: “${S.hearing}”`, 'listen'); m.lastChild.dir = 'auto'; return; }
  const lvl = Math.min(1, (h.mic_level || 0) / 8000);
  m.className = 'srow micline listen';
  m.innerHTML = `<span class="wave"><span></span><span></span><span></span><span></span></span>listening
    <span class="meter"><span style="width:${Math.round(lvl * 100)}%"></span></span>`;
}

// ------------------------------------------------------------ conversation
function modelLabel(ai) {
  const m = ai.model || '';
  if (/^gpt-realtime/.test(m)) return 'GPT Realtime ' + m.replace(/^gpt-realtime-?/, '');
  if (!m) return '–';
  const c = S.cfg, eleven = c.engine === 'eleven' && c.el_voice && (S.keys.eleven || {}).has;
  return `${m} reacts · ${eleven ? 'ElevenLabs' : 'GPT'} voice`;
}
let clockTimer = null, turnTimer = null;
function renderAI() {
  const ai = S.ai || { state: 'off' };
  const [label, cls] = STATE[ai.state] || STATE.off;
  $('state').textContent = label; $('state').className = 'st ' + cls;
  $('model').textContent = modelLabel(ai);
  const cb = $('convbtn');
  if (!cb.classList.contains('busy')) {
    cb.className = 'btn ' + (ai.running ? 'btn-stop' : 'btn-primary');
    cb.innerHTML = ai.running ? ICON('stop') + 'End conversation' : ICON('play') + 'Start conversation';
  }
  const canResume = !!(ai.running && ai.paused);
  $('resume').disabled = !canResume;
  $('resume').className = 'btn ' + (canResume ? 'btn-primary' : 'btn-quiet');
  $('pause-btn').disabled = !(ai.running && !ai.paused);
  $('turns').textContent = ai.turns || 0;
  $('latency').textContent = ai.latency_ms ? ai.latency_ms : '–';
  $('step').textContent = ai.running && ai.steps ? `${ai.step || '–'}/${ai.steps}${ai.step_title ? ' ' + ai.step_title : ''}` : '–';
  $('turnrow').hidden = !(ai.running && !ai.paused);
  $('next-start').hidden = !ai.running;
  $('next-start-text').textContent = String((S.cfg || {}).experience || '').startsWith('feelings')
    ? "Voice and Engine change Pepper's voice at once. Experience and Language apply at the next Start."
    : 'Experience, Engine, Language and Voice apply at the next Start. Wizard of Oz uses a new voice at once.';
  renderTurn();
  const banner = !!(ai.running && ai.stuck);
  if (banner && $('ai-banner').hidden) ['woz-speech', 'woz-move'].forEach(id => flash($(id)));
  $('ai-banner').hidden = !banner;
  clearInterval(clockTimer);
  const tick = () => {
    if (!ai.started_at || !ai.running) { $('clock').textContent = '00:00'; return; }
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ai.started_at));
    $('clock').textContent = String(s / 60 | 0).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  };
  tick(); if (ai.running) clockTimer = setInterval(tick, 1000);
  renderMic();
}
function renderTurn() {
  const ai = S.ai || {};
  clearInterval(turnTimer);
  const draw = () => {
    let txt = '';
    if (ai.state === 'searching') {
      const since = ai.search && ai.search.since;
      txt = `Pepper is looking it up online${since ? ' · ' + Math.max(0, Math.round(Date.now() / 1000 - since)) + ' s' : ''}`;
    } else if (ai.turn === 'waiting') {
      const s = ai.waiting_t ? Math.max(0, Math.floor(Date.now() / 1000 - ai.waiting_t)) : 0;
      txt = `Waiting for an answer · ${mmss(s)}`;
      txt += !ai.expects ? ' · no question open' : ai.reasked ? ' · asked again, waiting' : ` · asks again at ${mmss(ai.reask_s || 12)}`;
    } else if (ai.state === 'thinking') txt = 'Pepper is thinking';
    else if (ai.state === 'speaking') txt = 'Pepper is speaking';
    $('turninfo').textContent = txt;
  };
  draw();
  if (ai.turn === 'waiting' || ai.state === 'searching') turnTimer = setInterval(draw, 1000);
}
$('t-repeat').onclick = () => api('/api/turn/repeat');
$('t-skip').onclick = () => api('/api/turn/skip');

function renderVoices() {
  const c = S.cfg, el = c.engine === 'eleven';
  const sel = $('voice');
  sel.innerHTML = '';
  const list = el ? S.el_voices.map(v => [v.id, v.name + (v.language ? ` (${v.language})` : '')])
                  : S.voices.map(v => [v, v]);
  if (el && !list.length) sel.innerHTML = '<option value="">No ElevenLabs voices (key?)</option>';
  list.forEach(([v, label]) => { const o = document.createElement('option'); o.value = v; o.textContent = label; sel.append(o); });
  sel.value = el ? (c.el_voice || '') : c.voice;
  if (sel.selectedIndex < 0 && sel.options.length) sel.selectedIndex = 0;
}
// Which toggles the chosen experience uses (parity C1): the others are greyed, with the reason.
function toggleReasons() {
  const exp = S.cfg.experience, web = S.web || {};
  const r = { vision: '', ai_screen: '', gestures: '', web_search: web.available === false ? web.reason || '' : '' };
  if (exp === 'feelings:script') { r.vision = 'Not in the scripted demo'; r.ai_screen = 'The script drives it'; }
  if (exp === 'free') { r.ai_screen = 'Not in free conversation'; r.gestures = 'Not in free conversation'; }
  return r;
}
function renderCfg() {
  const c = S.cfg;
  $('exp').value = c.experience; $('lang').value = c.language; $('engine').value = c.engine;
  renderVoices();
  $('pause-ai').checked = !!c.pause_ai; $('tell-ai').checked = !!c.tell_ai;
  $('camsel').value = String(c.camera || 0);
  const why = toggleReasons();
  document.querySelectorAll('.tg2[data-opt]').forEach(row => {
    const k = row.dataset.opt, sw = row.querySelector('.switch'), reason = why[k] || '';
    sw.classList.toggle('on', !!c[k]);
    sw.setAttribute('aria-checked', c[k] ? 'true' : 'false');
    sw.disabled = !!reason;
    row.classList.toggle('off', !!reason);
    row.querySelector('.why').textContent = reason || (k === 'web_search' && (S.web || {}).check === 'checking' ? 'Checking…' : '');
  });
  const nOk = (S.emoji_candidates || []).length - (c.emoji_broken || []).length;
  $('emoji-count').textContent = `${(S.emoji_candidates || []).length} candidates · ${nOk} allowed now`;
  $('model').textContent = modelLabel(S.ai || {});
  renderDecks();
}
document.querySelectorAll('.tg2[data-opt] .switch').forEach(sw => {
  sw.onclick = () => { const k = sw.closest('.tg2').dataset.opt; setOpt(k, !S.cfg[k]); };
});
$('exp').onchange = () => setOpt('experience', $('exp').value);
$('lang').onchange = () => setOpt('language', $('lang').value);
$('voice').onchange = () => setOpt(S.cfg.engine === 'eleven' ? 'el_voice' : 'voice', $('voice').value);
$('engine').onchange = () => setOpt('engine', $('engine').value);
$('pause-ai').onchange = () => setOpt('pause_ai', $('pause-ai').checked);
$('tell-ai').onchange = () => setOpt('tell_ai', $('tell-ai').checked);

let noteTimer;
$('convbtn').onclick = async () => {
  const b = $('convbtn'), starting = !S.ai.running;
  b.disabled = true; b.classList.add('busy');
  $('start-note').hidden = true;
  try {
    const r = await fetch(starting ? '/api/conversation/start' : '/api/conversation/stop', { method: 'POST' });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) {
      // Why Start was refused stays in the card (key missing, robot not connected, …).
      $('start-note').lastChild.textContent = sentence(j.detail || j.error || 'HTTP ' + r.status);
      $('start-note').hidden = false;
      clearTimeout(noteTimer); noteTimer = setTimeout(() => { $('start-note').hidden = true; }, 15000);
    }
  } catch (e) { toast("The dashboard server isn't answering.", true); }
  b.disabled = false; b.classList.remove('busy');
  renderAI();
};
$('resume').onclick = () => api('/api/ai/resume');
$('pause-btn').onclick = () => api('/api/ai/pause');
$('ai-restart').onclick = () => api('/api/ai/restart');
$('estop').onclick = () => api('/api/stop_all');

// ------------------------------------------------------------ wizard of oz
function wozSay(text) {
  text = (text || '').trim(); if (!text) return;
  return api('/api/say', { text, pause_ai: $('pause-ai').checked, tell_ai: $('tell-ai').checked });
}
$('woz-say').onclick = () => { wozSay($('woz-text').value); $('woz-text').value = ''; $('woz-text').focus(); };
$('woz-text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('woz-say').click(); } });
$('woz-stop').onclick = () => api('/api/stop_speech');

MOVES.forEach(([name, label]) => {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'btn ' + (name === 'walk' ? 'btn-dark' : 'btn-quiet'); b.textContent = label;
  if (name === 'walk') b.title = '1 m forward, turn, 1 m back, turn. Unplug the charger first; keep 1.5 m clear.';
  b.onclick = () => api('/api/move', { name });
  $('moves').append(b);
});
document.querySelectorAll('[data-head]').forEach(b => { b.onclick = () => api('/api/head', { dir: b.dataset.head }); });
document.querySelectorAll('[data-posture]').forEach(b => { b.onclick = () => api('/api/posture', { name: b.dataset.posture }); });
$('tracking').onclick = () => api('/api/face_tracking', { on: !((S.health.robot || {}).status || {}).awareness });
$('stop-motion').onclick = () => api('/api/stop_motion');
let volTimer;
$('vol').oninput = () => {
  $('volv').textContent = $('vol').value + '%';
  clearTimeout(volTimer); volTimer = setTimeout(() => api('/api/volume', { value: +$('vol').value }), 250);
};

// ------------------------------------------------------------ the screen
function renderScreen() {
  const s = S.screen; if (!s) return;
  PepperScreen.render($('screen'), s, i => api('/screen/tap', { v: s.v, i }));
  const by = s.by === 'ai' ? 'by the AI' : s.by === 'you' ? 'by you' : '';
  const tap = S.lastTap ? `last tap: ${S.lastTap}` : 'last tap: none yet';
  $('screen-sub').textContent = by ? `${by} · ${tap}` : tap;
  if (s.item?.kind === 'slide' && s.item.deck === S.cfg.deck) { slideIdx = s.item.index; markThumb(); }
}
new ResizeObserver(() => S.screen && renderScreen()).observe($('screen'));

function currentDeck() { return S.decks.find(d => d.id === $('deck').value); }
function renderDecks() {
  const sel = $('deck'), before = sel.value; sel.innerHTML = '';
  if (!S.decks.length) sel.innerHTML = '<option value="">No presentations yet: upload one</option>';
  S.decks.forEach(d => {
    const o = document.createElement('option');
    o.value = d.id; o.textContent = `${d.name} · ${d.slides.length} slides`;
    sel.append(o);
  });
  sel.value = S.cfg.deck || (S.decks[0]?.id ?? '');
  const deck = currentDeck();
  if (sel.value !== before) $('thumbs').dataset.deck = '';
  if ($('thumbs').dataset.deck !== (deck ? deck.id + ':' + deck.slides.length : '')) {
    $('thumbs').innerHTML = '';
    (deck?.slides || []).forEach((s, i) => {
      const th = document.createElement('button');
      th.type = 'button'; th.className = 'thumb'; th.title = s.title;
      th.innerHTML = `<img src="/screen/media/${deck.id}/${s.file}" loading="lazy" alt=""><span class="n">${i + 1}</span>`;
      th.onclick = () => showSlide(i);
      $('thumbs').append(th);
    });
    $('thumbs').dataset.deck = deck ? deck.id + ':' + deck.slides.length : '';
  }
  $('deck-del').disabled = !deck;
  markThumb();
}
function markThumb() {
  const deck = currentDeck();
  [...$('thumbs').children].forEach((th, i) => th.classList.toggle('on', i === slideIdx));
  if (!$('slide-n').dataset.busy) $('slide-n').textContent = deck?.slides.length ? `${slideIdx + 1}/${deck.slides.length}` : '–';
}
function showSlide(i) {
  const deck = currentDeck();
  if (!deck?.slides.length) return toast('Upload a presentation first');
  slideIdx = (i + deck.slides.length) % deck.slides.length;
  if (S.cfg.deck !== deck.id) setOpt('deck', deck.id);
  api('/api/screen', { kind: 'slide', deck: deck.id, index: slideIdx });
  markThumb();
}
$('deck').onchange = () => { slideIdx = 0; setOpt('deck', $('deck').value || null); };
$('prev').onclick = () => showSlide(slideIdx - 1);
$('next').onclick = () => showSlide(slideIdx + 1);
$('welcome').onclick = () => api('/api/screen', { kind: 'welcome' });
$('blank').onclick = () => api('/api/screen', { kind: 'blank' });
$('deck-del').onclick = () => {
  const deck = currentDeck(); if (!deck) return;
  $('deck-confirm-text').textContent = `Delete “${deck.name}” (${deck.slides.length} slides) from this laptop?`;
  $('deck-confirm').hidden = false; $('deck-confirm').dataset.id = deck.id;
};
$('deck-del-no').onclick = () => { $('deck-confirm').hidden = true; };
$('deck-del-yes').onclick = async () => {
  const id = $('deck-confirm').dataset.id, wasSelected = S.cfg.deck === id;
  $('deck-confirm').hidden = true;
  if (await api('/api/decks/' + id, undefined, 'DELETE') && wasSelected)
    toast('No presentation selected: the AI has no slides now');
};
$('tablet-reload').onclick = () => api('/api/screen/reload');

// Upload: images as they are; a PDF is drawn page by page here (pdf.js, bundled
// in /static/vendor) and each page uploaded as a PNG, so the server needs no PDF library.
async function loadPdfJs() {
  if (window.pdfjsLib) return;
  const load = src => new Promise((ok, bad) => {
    const s = document.createElement('script'); s.src = src; s.onload = ok; s.onerror = bad; document.head.append(s);
  });
  try {
    await load('/static/vendor/pdf.min.js');
    pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.js';
  } catch (e) {   // only if the bundled copy is missing from this checkout
    await load('https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js');
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  }
}
async function pdfPages(file, onPage) {
  await loadPdfJs();
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  const out = [], n = Math.min(pdf.numPages, 60);
  for (let p = 1; p <= n; p++) {
    onPage(p, n);
    const page = await pdf.getPage(p), vp0 = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.min(1280 / vp0.width, 800 / vp0.height) * 1.5 });
    const cv = document.createElement('canvas'); cv.width = vp.width; cv.height = vp.height;
    await page.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise;
    out.push({ name: `${file.name.replace(/\.pdf$/i, '')} ${String(p).padStart(2, '0')}.png`,
               data: await new Promise(r => cv.toBlob(r, 'image/png')) });
  }
  return out;
}
function uploadStatus(text) { $('upload-status').textContent = text || ''; $('upload-status').hidden = !text; }
async function upload(files) {
  files = [...files];
  if (!files.length) return;
  const slides = [];
  for (const f of files) {
    if (f.type === 'application/pdf' || /\.pdf$/i.test(f.name)) {
      try { slides.push(...await pdfPages(f, (p, n) => uploadStatus(`Turning ${f.name} into slides… ${p}/${n}`))); }
      catch (e) { toast(`Couldn't read ${f.name}: ${e.message || e}`, true); }
    } else if (f.type.startsWith('image/')) slides.push({ name: f.name, data: f });
    else toast(`${f.name}: only images and PDFs. Save PowerPoint as PDF first.`, true);
  }
  uploadStatus('');
  if (!slides.length) return;
  const name = files.length === 1 ? files[0].name.replace(/\.[^.]+$/, '') : `${slides.length} images`;
  const deck = await api('/api/decks', { name });
  if (!deck) return;
  $('slide-n').dataset.busy = '1';
  let ok = 0;
  for (const [i, s] of slides.entries()) {
    $('slide-n').textContent = `${i + 1}/${slides.length}`;
    uploadStatus(`Uploading ${i + 1}/${slides.length}…`);
    const r = await fetch(`/api/decks/${deck.id}/slides?name=${encodeURIComponent(s.name)}`, { method: 'PUT', body: s.data });
    if (!r.ok) toast(`${s.name}: ${sentence((await r.json().catch(() => ({}))).detail || r.status)}`, true);
    else ok++;
  }
  delete $('slide-n').dataset.busy;
  uploadStatus('');
  slideIdx = 0;
  if (await api(`/api/decks/${deck.id}/done`)) toast(`${name} (${ok} slides) is ready and selected`);
}
$('file').onchange = e => { upload(e.target.files); e.target.value = ''; };
$('upload-link').onclick = e => { e.preventDefault(); $('file').click(); };
const sc = $('screen-card');
['dragover', 'dragenter'].forEach(ev => sc.addEventListener(ev, e => { e.preventDefault(); sc.classList.add('dropping'); }));
['dragleave', 'drop'].forEach(ev => sc.addEventListener(ev, e => { e.preventDefault(); if (ev === 'drop' || !sc.contains(e.relatedTarget)) sc.classList.remove('dropping'); }));
sc.addEventListener('drop', e => upload(e.dataTransfer.files));

// ------------------------------------------------------------ camera
function onFrame(f) {
  if (f.n === lastFrame) return;
  lastFrame = f.n;
  const img = $('camimg'), next = new Image();
  next.onload = () => { img.src = next.src; img.hidden = false; $('camnone').hidden = true; $('camlive').hidden = false; };
  next.src = '/api/camera.png?n=' + f.n;
  $('caminfo').textContent = `LIVE · ${f.w}×${f.h} · ${f.cam ? 'bottom' : 'top'}`;
  const svg = $('faces');
  svg.setAttribute('viewBox', `0 0 ${+f.w || 320} ${+f.h || 240}`);
  svg.innerHTML = $('ovl').checked ? (f.faces || []).map(b => b.map(Number)).map(([x, y, w, h]) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="#4ADE80" stroke-width="2" rx="3"/>`).join('') : '';
}
$('snap').onclick = () => {
  if (!lastFrame) return toast('No camera picture yet');
  const a = document.createElement('a');
  a.href = '/api/camera.png?n=' + lastFrame; a.download = `pepper-camera-${new Date().toISOString().replace(/[:.]/g, '-')}.png`; a.click();
};
$('camsel').onchange = () => setOpt('camera', +$('camsel').value);
setInterval(() => { $('vision-tag').textContent = visionAt ? `frame sent to AI ${Math.round(Date.now() / 1000 - visionAt)} s ago` : ''; }, 1000);

// ------------------------------------------------------------ More menu
const menu = $('more-menu');
$('more-btn').onclick = e => {
  e.stopPropagation();
  menu.hidden = !menu.hidden; $('more-btn').setAttribute('aria-expanded', String(!menu.hidden));
};
document.addEventListener('click', e => { if (!menu.hidden && !menu.contains(e.target)) { menu.hidden = true; $('more-btn').setAttribute('aria-expanded', 'false'); } });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !menu.hidden) { menu.hidden = true; $('more-btn').focus(); } });
menu.querySelectorAll('[data-dialog]').forEach(b => {
  b.onclick = () => { menu.hidden = true; openDialog(b.dataset.dialog); };
});
document.querySelectorAll('dialog [data-close]').forEach(b => { b.onclick = () => b.closest('dialog').close(); });
function openDialog(id) {
  if (id === 'dlg-emoji') {
    const now = (S.cfg.emoji_broken || []).map(e => S.emoji_candidates.indexOf(e) + 1).filter(n => n > 0);
    $('emoji-nums').value = now.join(', ');
  }
  if (id === 'dlg-facts') {
    $('facts-text').textContent = 'Loading…';
    api('/api/lab_facts', undefined, 'GET').then(r => {
      if (!r) return;
      $('facts-file').textContent = r.file;
      $('facts-text').textContent = r.text || 'No lab facts yet: Pepper says it is not sure.';
    });
  }
  if (id === 'dlg-rehearse') { $('rehearse-sim').hidden = !S.sim; $('rehearse-real').hidden = !!S.sim; $('rehearse-start').hidden = !!S.sim; }
  $(id).showModal();
}
$('emoji-test').onclick = () => api('/api/screen', { kind: 'emoji_test' });
$('emoji-mark').onclick = async () => {
  const numbers = ($('emoji-nums').value.match(/\d+/g) || []).map(Number);
  const r = await api('/api/emoji/broken', { numbers });
  if (r) { toast(`${r.allowed} emoji allowed on Pepper's screen`); $('dlg-emoji').close(); }
};
let screenKind = 'message';
function seg(kind) {
  screenKind = kind;
  $('seg-msg').classList.toggle('on', kind === 'message'); $('seg-choice').classList.toggle('on', kind === 'choice');
  $('form-msg').hidden = kind !== 'message'; $('form-choice').hidden = kind !== 'choice';
}
$('seg-msg').onclick = () => seg('message');
$('seg-choice').onclick = () => seg('choice');
$('screen-show').onclick = async () => {
  let body;
  if (screenKind === 'message') body = { kind: 'message', text: $('msg-text').value };
  else body = { kind: 'choice', question: $('choice-q').value,
                options: [...document.querySelectorAll('.choice-opt')].map(i => ({ label: i.value.trim() })).filter(o => o.label) };
  if (await api('/api/screen', body)) $('dlg-screen').close();
};

// ------------------------------------------------------------ live link
function connect() {
  const ws = new WebSocket(`ws://${location.host}/api/ws`);
  ws.onopen = () => { wsUp = true; };
  ws.onmessage = ev => {
    const { type, data } = JSON.parse(ev.data);
    if (type === 'snapshot') {
      wsUp = true;
      S = { ...S, ...data };
      const off = new Set(data.experiences_off || []);   // shown, but not for the demo
      $('exp').innerHTML = '';
      Object.entries(data.experiences).forEach(([k, v]) => {
        const o = document.createElement('option'); o.value = k;
        o.textContent = off.has(k) ? `${v} (not for the demo)` : v; o.disabled = off.has(k);
        $('exp').append(o);
      });
      $('engine').innerHTML = '';
      Object.entries(data.engines).forEach(([k, v]) => { const o = document.createElement('option'); o.value = k; o.textContent = v; $('engine').append(o); });
      $('phrases').innerHTML = '';
      data.phrases.forEach(p => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'qp'; b.title = p;
        b.innerHTML = `<b>${/[֐-׿]/.test(p) ? 'HE' : 'EN'}</b><span dir="auto"></span>`;
        b.lastChild.textContent = p;
        b.onclick = () => wozSay(p);
        $('phrases').append(b);
      });
      $('log').innerHTML = ''; data.logs.forEach(addLog);
      $('chat').innerHTML = ''; pepperBubbles.clear(); data.chat.forEach(addChat);
      if (!data.chat.length) addChat({ role: 'hint', text: 'Press Start conversation and Pepper begins talking.' });
      renderKeys(); renderCfg(); renderHealth(); renderAI(); renderScreen();
    } else if (type === 'log') addLog(data);
    else if (type === 'chat') addChat(data);
    else if (type === 'health') { S.health = data; renderHealth(); }
    else if (type === 'ai') { S.ai = data; renderAI(); }
    else if (type === 'screen') {
      S.screen = data;
      if (data.picked) S.lastTap = `${data.picked} · ${hhmmss()}`;
      renderScreen();
    }
    else if (type === 'cfg') { S.cfg = data; renderCfg(); }
    else if (type === 'web') { S.web = data; renderCfg(); }
    else if (type === 'decks') { S.decks = data; renderDecks(); }
    else if (type === 'frame') onFrame(data);
    else if (type === 'vision') visionAt = data.t;
    else if (type === 'hearing') { S.hearing = data.text; renderMic(); }
    else if (type === 'el_voices') { S.el_voices = data; renderVoices(); }
  };
  ws.onclose = () => {
    wsUp = false;
    renderHealth();
    setTimeout(connect, 2000);
  };
}
connect();

$('rehearse-start').onclick = async () => {
  const b = $('rehearse-start'); b.disabled = true; b.textContent = 'Starting…';
  // Open the window now, inside the click, so the browser lets it through;
  // its address is set when the simulator answers.
  let win = null;
  try { win = window.open('about:blank', '_blank'); } catch (e) { win = null; }
  const r = await api('/api/rehearse');
  b.disabled = false; b.textContent = 'Start rehearsal';
  if (r && r.url) {
    if (win) { win.location = r.url; toast('Rehearsal started.'); }
    else {
      toast('Rehearsal started. ');
      const a = document.createElement('a');
      a.href = r.url; a.target = '_blank'; a.rel = 'noopener'; a.textContent = 'Open it';
      $('toast').append(a);
    }
  } else if (win) win.close();
};

// Keep the floating AI-stuck bar just below the top bar, however many rows it wraps to.
(function () {
  const top = document.querySelector('.top');
  if (!top) return;
  const set = () => document.documentElement.style.setProperty('--topH', top.offsetHeight + 'px');
  set();
  if (window.ResizeObserver) new ResizeObserver(set).observe(top);
  window.addEventListener('resize', set);
})();
