// Pepper operator dashboard. State arrives on /api/ws (a snapshot, then
// events); every control is a POST to /api/*.
const $ = id => document.getElementById(id);
// Only movements tested on this Pepper (agent/pepper_agent.py has the exact values).
const MOVES = [['wave', 'Wave'], ['yes', 'Nod yes'], ['no', 'Shake no'],
               ['arms_up', 'Both arms up'], ['arms_wide', 'Arms wide'], ['right_arm_up', 'Right arm up'],
               ['left_arm_up', 'Left arm up'], ['hands', 'Open/close hands'], ['walk', 'Walking']];
const STATE = {
  off: ['IDLE', 'bg-slate-100 text-slate-600'], waiting: ['WAITING FOR ANSWER', 'bg-blue-100 text-blue-700'],
  thinking: ['THINKING', 'bg-amber-100 text-amber-700'],
  speaking: ['SPEAKING', 'bg-green-100 text-green-700'], paused: ['PAUSED · YOU', 'bg-violet-100 text-violet-700'],
  stuck: ['AI STUCK', 'bg-red-100 text-red-700'],
};
let S = { cfg: {}, health: {}, ai: { state: 'off' }, screen: null, decks: [], el_voices: [], voices: [], hearing: '' };
let slideIdx = 0, lastFrame = 0, clockTimer = null;
const pepperBubbles = new Map();
const t = ts => new Date((ts || Date.now() / 1000) * 1000).toLocaleTimeString('en-GB');

// ------------------------------------------------------------ helpers
async function api(path, body, method = 'POST') {
  try {
    const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' },
                                  body: body === undefined ? undefined : JSON.stringify(body) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { toast(j.detail || j.error || ('HTTP ' + r.status)); return null; }
    return j;
  } catch (e) { toast('The dashboard server is not answering'); return null; }
}
let toastTimer;
function toast(msg) {
  const el = $('toast'); el.textContent = msg; el.classList.remove('hidden'); el.style.opacity = 1;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.style.opacity = 0; setTimeout(() => el.classList.add('hidden'), 250); }, 4500);
}
function setOpt(key, value) { S.cfg[key] = value; renderCfg(); return api('/api/options', { [key]: value }); }

// ------------------------------------------------------------ log + chat
function addLog(l) {
  const d = document.createElement('div');
  d.className = 'log-' + l.level;
  d.textContent = `${t(l.t)} ${l.level.padEnd(7)} ${l.msg}`;
  const box = $('log'), stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.append(d);
  while (box.childElementCount > 600) box.firstChild.remove();
  if (stick) box.scrollTop = 1e9;
}
$('copy').onclick = () => navigator.clipboard?.writeText($('log').innerText).then(
  () => { $('copied').textContent = 'Copied'; setTimeout(() => $('copied').textContent = '', 1500); },
  () => { $('copied').textContent = 'Copy failed'; });

function addChat(e) {
  const c = $('chat'), stick = c.scrollTop + c.clientHeight >= c.scrollHeight - 40;
  if (e.role === 'heard') {
    const d = document.createElement('div');
    d.className = 'b-heard'; d.dir = 'auto';
    d.innerHTML = '<span class="t"></span><button class="btn btn-slate btn-xs">Accept</button>';
    d.querySelector('.t').textContent = `Heard, not used: “${e.text}” (${e.why || 'not an answer'})`;
    d.title = e.text;
    d.querySelector('button').onclick = async () => { if (await api('/api/turn/accept', { text: e.text })) d.remove(); };
    c.append(d);
  } else if (e.role === 'event' || e.role === 'tap') {
    const d = document.createElement('div');
    d.className = 'b-event' + (e.role === 'tap' ? ' tap' : '');
    d.textContent = e.role === 'tap' ? `Tapped the screen: ${e.text}` : e.text;
    c.append(d);
  } else {
    let b = e.role === 'pepper' && e.id ? pepperBubbles.get(e.id) : null;
    if (!b) {
      b = document.createElement('div'); b.dir = 'auto';
      b.className = 'bubble b-' + (e.role === 'user' ? 'user' : e.role === 'woz' ? 'woz' : 'pepper');
      b.innerHTML = '<div class="who"></div><div class="txt"></div>';
      b.firstChild.textContent = { pepper: 'Pepper', user: 'Person', woz: 'Pepper · you (Wizard of Oz)' }[e.role] || e.role;
      c.append(b);
      if (e.role === 'pepper' && e.id) pepperBubbles.set(e.id, b);
    }
    b.querySelector('.txt').textContent = e.text;
    b.classList.toggle('partial', !!e.partial);
  }
  while (c.childElementCount > 300) c.firstChild.remove();
  if (stick) c.scrollTop = 1e9;
}

// ------------------------------------------------------------ status
function renderHealth() {
  const h = S.health || {}, r = h.robot || {}, st = r.status || {}, sc = h.screen || {};
  const ok = r.state === 'connected';
  $('robot-pill').className = 'pill' + (ok ? '' : r.state === 'deploying' || r.state === 'starting' ? ' warn' : ' bad');
  $('robot-dot').className = 'dot ' + (ok ? 'ok' : r.state === 'deploying' || r.state === 'starting' ? 'warn' : 'bad');
  const bat = st.battery == null ? '' : ` · battery ${st.battery}%${st.charging ? ', charging' : ''}`;
  $('robot-sub').textContent = ok ? `${r.ip}${bat}` : (r.state === 'deploying' ? 'starting its agent…' : (r.detail || r.state || ''));
  $('robot-pill').title = ok ? `${r.info?.name || 'Pepper'} · NAOqi ${r.info?.naoqi || '?'} · ${st.posture || ''} · speaker: ${r.speaker_mode}` : (r.detail || '');
  $('screen-pill').className = 'pill' + (sc.connected ? '' : ' bad');
  $('screen-dot').className = 'dot ' + (sc.connected ? 'ok' : 'bad');
  $('screen-sub').textContent = sc.connected ? `${sc.ip} · live ${Math.round(sc.seen_s || 0)}s`
    : (sc.seen_s == null ? 'not connected yet · people see nothing' : `lost ${Math.round(sc.seen_s)}s ago · people see nothing`);
  $('screen-fix').classList.toggle('hidden', !!sc.connected);
  $('screen-off').classList.toggle('hidden', !!sc.connected);
  document.querySelectorAll('.needs-robot').forEach(b => b.disabled = !ok);
  document.querySelectorAll('.move').forEach(b => b.disabled = !ok);
  if (st.volume != null && document.activeElement !== $('vol')) { $('vol').value = st.volume; $('volv').textContent = st.volume + '%'; }
  if (h.phrases_ready != null) $('phrases-ready').textContent = h.phrases_ready ? `${h.phrases_ready} offline` : '';
  renderMic();
}

function renderMic() {
  const h = S.health || {}, ai = S.ai || {};
  if (!ai.running) { $('mic').textContent = ''; return; }
  if (h.speaking) { $('mic').innerHTML = '<span class="text-green-600">Pepper speaking · mic shut</span>'; return; }
  if (ai.paused) { $('mic').innerHTML = '<span class="text-violet-600">AI paused · you have the floor</span>'; return; }
  if (ai.turn !== 'waiting') { $('mic').innerHTML = '<span class="text-amber-600">Pepper\'s turn · mic shut</span>'; return; }
  if (S.hearing) { $('mic').innerHTML = ''; const sp = document.createElement('span');
    sp.className = 'text-sky-700 truncate max-w-[16rem]'; sp.dir = 'auto'; sp.textContent = 'hearing: ' + S.hearing;
    $('mic').append(sp); return; }
  const lvl = Math.min(1, (h.mic_level || 0) / 8000);
  $('mic').innerHTML = `<span class="wave text-blue-600"><span></span><span style="animation-delay:.15s"></span><span style="animation-delay:.3s"></span></span>
    listening <span class="inline-block w-12 h-1.5 bg-slate-200 rounded overflow-hidden align-middle"><span class="block h-full bg-blue-500" style="width:${Math.round(lvl * 100)}%"></span></span>`;
}

function renderAI() {
  const ai = S.ai || { state: 'off' };
  const [label, cls] = STATE[ai.state] || STATE.off;
  $('state').textContent = label;
  $('state').className = 'text-[10px] font-semibold px-1.5 py-0.5 rounded ' + cls;
  $('convbtn').innerHTML = ai.running ? 'End conversation' : 'Start conversation';
  $('convbtn').className = 'btn flex-1 !py-1.5 !text-sm ' + (ai.running ? 'btn-danger' : 'btn-primary');
  $('resume').classList.toggle('hidden', !(ai.running && ai.paused));
  $('turns').textContent = ai.turns || 0;
  $('latency').textContent = ai.latency_ms ? `~${ai.latency_ms} ms` : '–';
  $('step').textContent = ai.steps ? `${ai.step || '–'}/${ai.steps}${ai.step_title ? ' ' + ai.step_title : ''}` : '–';
  $('turnrow').classList.toggle('hidden', !(ai.running && !ai.paused));
  renderTurn();
  const banner = ai.running && ai.stuck;
  if (banner && $('ai-banner').classList.contains('hidden'))
    ['woz-speech', 'woz-move'].forEach(id => { $(id).classList.remove('flash'); void $(id).offsetWidth; $(id).classList.add('flash'); });
  $('ai-banner').classList.toggle('hidden', !banner);
  clearInterval(clockTimer);
  const tick = () => {
    if (!ai.started_at) { $('clock').textContent = '00:00'; return; }
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ai.started_at));
    $('clock').textContent = String(s / 60 | 0).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0');
  };
  tick(); if (ai.running) clockTimer = setInterval(tick, 1000);
  renderMic();
}

let turnTimer = null;
function renderTurn() {
  const ai = S.ai || {};
  clearInterval(turnTimer);
  const draw = () => {
    let txt = '';
    if (ai.turn === 'waiting') {
      const s = ai.waiting_t ? Math.max(0, Math.floor(Date.now() / 1000 - ai.waiting_t)) : 0;
      txt = `Waiting for an answer · ${String(s / 60 | 0)}:${String(s % 60).padStart(2, '0')}`;
      txt += !ai.expects ? ' · no question open' : ai.reasked ? ' · asked again, waiting' : ` · re-asks at ${ai.reask_s | 0}s`;
    } else if (ai.state === 'thinking') txt = 'Pepper is thinking';
    else if (ai.state === 'speaking') txt = 'Pepper is speaking';
    $('turninfo').textContent = txt;
  };
  draw();
  if (ai.turn === 'waiting') turnTimer = setInterval(draw, 1000);
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
}

function renderCfg() {
  const c = S.cfg;
  $('exp').value = c.experience; $('lang').value = c.language;
  $('engine').value = c.engine; renderVoices();
  const nOk = (S.emoji_candidates || []).length - (c.emoji_broken || []).length;
  $('emoji-test').title = `Show every candidate emoji on Pepper's screen, numbered. ${nOk} allowed now.`;
  $('pause-ai').checked = !!c.pause_ai; $('tell-ai').checked = !!c.tell_ai;
  $('camsel').value = String(c.camera || 0);
  document.querySelectorAll('.tog').forEach(b => b.classList.toggle('on', !!c[b.dataset.opt]));
  renderDecks();
}

// ------------------------------------------------------------ the screen
function renderScreen() {
  const s = S.screen; if (!s) return;
  PepperScreen.render($('screen'), s, i => api('/screen/tap', { v: s.v, i }));
  $('shown-by').textContent = s.by === 'ai' ? 'by the AI' : s.by === 'you' ? 'by you' : '';
  $('emoji-mark').classList.toggle('hidden', s.item?.kind !== 'emoji_test');
  if (s.item?.kind === 'slide' && s.item.deck === S.cfg.deck) { slideIdx = s.item.index; markThumb(); }
}
new ResizeObserver(() => S.screen && renderScreen()).observe($('screen'));

function renderDecks() {
  const sel = $('deck'); sel.innerHTML = '';
  if (!S.decks.length) sel.innerHTML = '<option value="">No presentations yet — upload one</option>';
  S.decks.forEach(d => {
    const o = document.createElement('option');
    o.value = d.id; o.textContent = `${d.name} · ${d.slides.length} slides`;
    sel.append(o);
  });
  sel.value = S.cfg.deck || (S.decks[0]?.id ?? '');
  const deck = S.decks.find(d => d.id === sel.value);
  $('thumbs').innerHTML = '';
  (deck?.slides || []).forEach((s, i) => {
    const th = document.createElement('div');
    th.className = 'thumb'; th.title = s.title;
    th.innerHTML = `<img src="/screen/media/${deck.id}/${s.file}" loading="lazy" alt=""><span class="n">${i + 1}</span>`;
    th.onclick = () => showSlide(i);
    $('thumbs').append(th);
  });
  markThumb();
}
function markThumb() {
  const deck = S.decks.find(d => d.id === $('deck').value);
  [...$('thumbs').children].forEach((th, i) => th.classList.toggle('on', i === slideIdx));
  $('slide-n').textContent = deck?.slides.length ? `${slideIdx + 1}/${deck.slides.length}` : '–';
}
function showSlide(i) {
  const deck = S.decks.find(d => d.id === $('deck').value);
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
$('deck-del').onclick = async () => {
  const deck = S.decks.find(d => d.id === $('deck').value);
  if (deck && confirm(`Delete “${deck.name}” (${deck.slides.length} slides) from this laptop?`))
    await api('/api/decks/' + deck.id, undefined, 'DELETE');
};
$('screen-fix').onclick = () => api('/api/screen/reload');
$('emoji-test').onclick = () => api('/api/screen', { kind: 'emoji_test' });
$('emoji-mark').onclick = async () => {
  const now = (S.cfg.emoji_broken || []).map(e => (S.emoji_candidates || []).indexOf(e) + 1).filter(n => n > 0);
  const ans = prompt('Which numbers show as empty boxes or wrong on Pepper\'s tablet? (e.g. 4, 17, 30). Empty = all fine.', now.join(', '));
  if (ans === null) return;
  const numbers = (ans.match(/\d+/g) || []).map(Number);
  const r = await api('/api/emoji/broken', { numbers });
  if (r) toast(`${r.allowed} emoji allowed on Pepper's screen`);
};

// Upload: images as they are; a PDF is drawn page by page here (pdf.js) and
// each page uploaded as a PNG, so the server needs no PDF library.
async function pdfPages(file) {
  if (!window.pdfjsLib) {
    await new Promise((ok, bad) => { const s = document.createElement('script');
      s.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'; s.onload = ok; s.onerror = bad; document.head.append(s); });
    pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
  }
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  const out = [];
  for (let p = 1; p <= Math.min(pdf.numPages, 60); p++) {
    const page = await pdf.getPage(p), vp0 = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.min(1280 / vp0.width, 800 / vp0.height) * 1.5 });
    const cv = document.createElement('canvas'); cv.width = vp.width; cv.height = vp.height;
    await page.render({ canvasContext: cv.getContext('2d'), viewport: vp }).promise;
    out.push({ name: `${file.name.replace(/\.pdf$/i, '')} ${String(p).padStart(2, '0')}.png`,
               data: await new Promise(r => cv.toBlob(r, 'image/png')) });
  }
  return out;
}
async function upload(files) {
  files = [...files];
  if (!files.length) return;
  const slides = [];
  for (const f of files) {
    if (f.type === 'application/pdf' || /\.pdf$/i.test(f.name)) {
      toast(`Turning ${f.name} into slides…`);
      try { slides.push(...await pdfPages(f)); } catch (e) { toast(`Could not read ${f.name}: ${e.message || e}`); }
    } else if (f.type.startsWith('image/')) slides.push({ name: f.name, data: f });
    else toast(`${f.name}: only images and PDFs (save PowerPoint as PDF first)`);
  }
  if (!slides.length) return;
  const name = files.length === 1 ? files[0].name.replace(/\.[^.]+$/, '') : `${slides.length} images`;
  const deck = await api('/api/decks', { name });
  if (!deck) return;
  for (const [i, s] of slides.entries()) {
    $('slide-n').textContent = `${i + 1}/${slides.length}`;
    const r = await fetch(`/api/decks/${deck.id}/slides?name=${encodeURIComponent(s.name)}`, { method: 'PUT', body: s.data });
    if (!r.ok) { toast(`${s.name}: ${(await r.json().catch(() => ({}))).detail || r.status}`); }
  }
  slideIdx = 0;
  await api(`/api/decks/${deck.id}/done`);
}
$('file').onchange = e => { upload(e.target.files); e.target.value = ''; };
const sc = $('screen-card');
['dragover', 'dragenter'].forEach(ev => sc.addEventListener(ev, e => { e.preventDefault(); sc.classList.add('dropping'); }));
['dragleave', 'drop'].forEach(ev => sc.addEventListener(ev, e => { e.preventDefault(); if (ev === 'drop' || !sc.contains(e.relatedTarget)) sc.classList.remove('dropping'); }));
sc.addEventListener('drop', e => upload(e.dataTransfer.files));

// ------------------------------------------------------------ camera
function onFrame(f) {
  if (f.n === lastFrame) return;
  lastFrame = f.n;
  const img = $('camimg');
  const next = new Image();
  next.onload = () => { img.src = next.src; img.classList.remove('hidden'); $('camnone').classList.add('hidden'); $('camlive').classList.remove('hidden'); };
  next.src = '/api/camera.png?n=' + f.n;
  $('caminfo').textContent = `LIVE · ${f.w}×${f.h} · ${f.cam ? 'bottom' : 'top'}`;
  const svg = $('faces');
  svg.setAttribute('viewBox', `0 0 ${f.w || 320} ${f.h || 240}`);
  svg.innerHTML = $('ovl').checked ? (f.faces || []).map(([x, y, w, h]) =>
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="#22c55e" stroke-width="2" rx="3"/>`).join('') : '';
}
$('snap').onclick = () => {
  if (!lastFrame) return toast('No camera picture yet');
  const a = document.createElement('a');
  a.href = '/api/camera.png?n=' + lastFrame; a.download = `pepper-camera-${new Date().toISOString().replace(/[:.]/g, '-')}.png`; a.click();
};
$('camsel').onchange = () => setOpt('camera', +$('camsel').value);
let visionAt = 0;
setInterval(() => { $('vision-tag').textContent = visionAt ? `frame sent to AI ${Math.round(Date.now() / 1000 - visionAt)} s ago` : ''; }, 1000);

// ------------------------------------------------------------ controls
$('convbtn').onclick = async () => {
  $('convbtn').disabled = true;
  await api(S.ai.running ? '/api/conversation/stop' : '/api/conversation/start');
  $('convbtn').disabled = false;
};
$('resume').onclick = () => api('/api/ai/resume');
$('ai-restart').onclick = () => api('/api/ai/restart');
$('estop').onclick = () => api('/api/stop_all');
$('exp').onchange = () => setOpt('experience', $('exp').value);
$('lang').onchange = () => setOpt('language', $('lang').value);
$('voice').onchange = () => setOpt(S.cfg.engine === 'eleven' ? 'el_voice' : 'voice', $('voice').value);
$('engine').onchange = () => setOpt('engine', $('engine').value);
$('pause-ai').onchange = () => setOpt('pause_ai', $('pause-ai').checked);
$('tell-ai').onchange = () => setOpt('tell_ai', $('tell-ai').checked);
document.querySelectorAll('.tog').forEach(b => b.onclick = () => setOpt(b.dataset.opt, !S.cfg[b.dataset.opt]));

function wozSay(text) {
  text = (text || '').trim(); if (!text) return;
  return api('/api/say', { text, pause_ai: $('pause-ai').checked, tell_ai: $('tell-ai').checked });
}
$('woz-say').onclick = () => { wozSay($('woz-text').value); $('woz-text').value = ''; $('woz-text').focus(); };
$('woz-text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('woz-say').click(); } });
$('woz-stop').onclick = () => api('/api/stop_speech');

MOVES.forEach(([name, label]) => {
  const b = document.createElement('button');
  b.className = name === 'walk' ? 'move move-walk' : 'move'; b.textContent = label;
  if (name === 'walk') b.title = '1 m forward, turn around, 1 m forward, turn around. Unplug the charger first; keep 1.5 m clear.';
  b.onclick = () => api('/api/move', { name });
  $('moves').append(b);
});
document.querySelectorAll('[data-head]').forEach(b => b.onclick = () => api('/api/head', { dir: b.dataset.head }));
document.querySelectorAll('[data-posture]').forEach(b => b.onclick = () => api('/api/posture', { name: b.dataset.posture }));
let trackingOn = true;
$('tracking').onclick = async () => {
  if (await api('/api/face_tracking', { on: !trackingOn })) {
    trackingOn = !trackingOn; $('tracking').textContent = `Face tracking: ${trackingOn ? 'on' : 'off'}`;
  }
};
$('stop-motion').onclick = () => api('/api/stop_motion');
let volTimer;
$('vol').oninput = () => { $('volv').textContent = $('vol').value + '%';
  clearTimeout(volTimer); volTimer = setTimeout(() => api('/api/volume', { value: +$('vol').value }), 250); };

// ------------------------------------------------------------ live link
function connect() {
  const ws = new WebSocket(`ws://${location.host}/api/ws`);
  ws.onmessage = ev => {
    const { type, data } = JSON.parse(ev.data);
    if (type === 'snapshot') {
      S = { ...S, ...data };
      const off = new Set(data.experiences_off || []);   // greyed out, not selectable (until after the demo)
      $('exp').innerHTML = Object.entries(data.experiences).map(([k, v]) => off.has(k)
        ? `<option value="${k}" disabled style="color:#9ca3af">${v} (not for the demo)</option>`
        : `<option value="${k}">${v}</option>`).join('');
      $('engine').innerHTML = '';
      Object.entries(data.engines).forEach(([k, v]) => { const o = document.createElement('option'); o.value = k; o.textContent = v; $('engine').append(o); });
      $('phrases').innerHTML = '';
      data.phrases.forEach(p => {
        const b = document.createElement('button');
        b.className = 'chip'; b.dir = 'auto'; b.title = p;
        b.innerHTML = `<span class="lang">${/[֐-׿]/.test(p) ? 'HE' : 'EN'}</span>`; b.append(p);
        b.onclick = () => wozSay(p); $('phrases').append(b);
      });
      $('nokey').classList.toggle('hidden', data.has_key);
      $('log').innerHTML = ''; data.logs.forEach(addLog);
      $('chat').innerHTML = ''; pepperBubbles.clear(); data.chat.forEach(addChat);
      if (!data.chat.length) addChat({ role: 'event', text: 'Press “Start conversation” and Pepper begins talking' });
      renderCfg(); renderHealth(); renderAI(); renderScreen();
    } else if (type === 'log') addLog(data);
    else if (type === 'chat') addChat(data);
    else if (type === 'health') { S.health = data; renderHealth(); }
    else if (type === 'ai') { S.ai = data; renderAI(); }
    else if (type === 'screen') { S.screen = data; renderScreen();
      if (data.picked) $('lasttap').textContent = `last tap: ${data.picked} · ${t()}`; }
    else if (type === 'cfg') { S.cfg = data; renderCfg(); }
    else if (type === 'decks') { S.decks = data; renderDecks(); }
    else if (type === 'frame') onFrame(data);
    else if (type === 'vision') visionAt = data.t;
    else if (type === 'hearing') { S.hearing = data.text; renderMic(); }
    else if (type === 'el_voices') { S.el_voices = data; renderVoices(); }
  };
  ws.onclose = () => {
    $('robot-sub').textContent = 'dashboard server stopped';
    $('robot-pill').className = 'pill bad'; $('robot-dot').className = 'dot bad';
    setTimeout(connect, 2000);
  };
}
connect();
