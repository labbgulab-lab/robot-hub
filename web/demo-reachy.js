/* Reachy app demo mode: /reachy.html?demo=<state> renders from this fake
 * data instead of the hub, so every board and state can be shown and
 * screenshotted (docs/design/renders/RA*.png). Loaded only in demo mode.
 *
 * States: talk, talk-refused, talk-gptlive, talk-stopped, talk-lost,
 * talk-ended, talk-character, talk-group, talk-inuse, talk-connect,
 * talk-starting, picker, table, table-idle, table-live, table-refused,
 * table-notsaved, table-checkfail, table-closing, table-overtime,
 * table-interrupt, table-empty, table-credits, table-simulate, table-five,
 * table-notes, groups, copy, woz, woz-off, editor.
 */
'use strict';

(function () {
  const now = () => Date.now() / 1000;
  const clone = (o) => JSON.parse(JSON.stringify(o));

  /* ----------------------------------------------------------------- hub */
  const ROBOTS = [
    { key: 'reachy:1', type_id: 'reachy_wireless', name: 'reachy1', state: 'CONNECTED', address: '10.0.4.21' },
    { key: 'reachy:3', type_id: 'reachy_wireless', name: 'reachy3', state: 'RUNNING', address: '10.0.4.23', system_url: 'http://10.0.4.23:8765/' },
    { key: 'reachy:6', type_id: 'reachy_wireless', name: 'reachy6', state: 'CONNECTED', address: '10.0.4.26' },
  ].map(r => ({ type: 'robot', battery: null, detail: '', mic: 'robot', can_speak: true, facts: { robot_software: 'Daemon 1.11.0', mic: 'robot', holds: [], seen_ago: 2 }, ...r }));

  const SETTINGS = { auto_connect: true, staff_tools: false, save_transcripts: true, setup_seen: true,
                     woz_quick: ['Sorry, can you say that again?', 'Let me think about that for a second.', 'That is a great question!'] };

  /* --------------------------------------------------------------- group */
  const ELV = [['v-dan', 'Daniel'], ['v-adam', 'Adam'], ['v-josh', 'Josh'], ['v-brian', 'Brian'], ['v-cal', 'Callum']]
    .map(([voice_id, name]) => ({ voice_id, name, gender: 'male' }));
  const OAV = [['ash', 'male'], ['ballad', 'male'], ['cedar', 'male'], ['echo', 'male'], ['onyx', 'male, deep'], ['fable', 'male, British'], ['verse', 'male']];
  const GEV = ['Achird', 'Algenib', 'Algieba', 'Alnilam', 'Charon', 'Enceladus', 'Fenrir', 'Iapetus', 'Orus', 'Puck', 'Rasalgethi', 'Sadachbia', 'Sadaltager', 'Schedar', 'Umbriel', 'Zubenelgenubi'];
  const VOICE_OPTIONS = {
    openai: OAV.map(([v, d]) => ({ id: v, label: `${v} (${d})` })),
    openrouter: OAV.filter(([v]) => ['ash', 'ballad', 'cedar', 'echo', 'verse'].includes(v)).map(([v, d]) => ({ id: v, label: `${v} (${d})` })),
    gemini: GEV.map(v => ({ id: v, label: `${v} (male)` })),
  };
  function seats() {
    return [
      { key: 'reachy:1', name: 'reachy1', included: true, listen: true, character: 'Max', persona: 'For AI music: optimistic, brings examples of tools musicians already use.',
        voice_provider: 'elevenlabs', voice_id: 'v-dan', writer: 'google/gemini-3.5-flash', interrupt_level: 3, gestures: 'lively', vision: true, loudness: 150,
        default_voices: { elevenlabs: 'v-dan', openai: 'ash', gemini: 'Charon' } },
      { key: 'reachy:3', name: 'reachy3', included: true, listen: true, character: 'Leo', persona: 'Against: skeptical, asks who gets paid and what makes music human.',
        voice_provider: 'openai', openai_voice: 'onyx', writer: 'openai/gpt-oss-120b', interrupt_level: 4, gestures: 'calm', vision: true, loudness: 130,
        default_voices: { elevenlabs: 'v-adam', openai: 'verse', gemini: 'Charon' } },
      { key: 'reachy:6', name: 'reachy6', included: true, listen: false, character: 'Reachy Mini 3', persona: 'Precise: brings facts and numbers.',
        voice_provider: 'gemini', writer: 'google/gemini-3.5-flash', interrupt_level: 2, gestures: 'lively', vision: true, loudness: 150,
        default_voices: { elevenlabs: 'v-josh', openai: 'echo', gemini: 'Charon' } },
    ];
  }
  const CHECKS_PENDING = {
    'OpenAI': { ok: true, ms: 600 }, 'Writer gemini-3.5-flash': { ok: true, ms: 1900 }, 'Writer gpt-oss-120b': { ok: true, ms: 1100 },
    'Writer gemini-3.5-flash-lite': { ok: null }, 'Hearing (speech to text)': { ok: true, ms: 800 }, 'Voice of Max': { ok: true, ms: 700 },
    'Voice of Leo': { ok: null }, 'Voice detection': { ok: true, ms: 200 },
  };
  const CHECKS_OK = Object.fromEntries(Object.keys(CHECKS_PENDING).map(k => [k, { ok: true, ms: { 'Writer gemini-3.5-flash-lite': 900, 'Voice of Leo': 750 }[k] || CHECKS_PENDING[k].ms }]));

  function groupState(o) {
    o = o || {};
    return {
      running: false, connected: true, mode: null, people_live: '', limit_s: null, closing: false,
      eleven_credits: 41220, eleven_in_use: true, connected_seats: ['reachy:1', 'reachy:3', 'reachy:6'],
      available: ROBOTS.map(r => ({ key: r.key, name: r.name, state: r.state === 'RUNNING' ? 'CONNECTED' : r.state })),
      seats: seats(), voices: ELV, voice_options: VOICE_OPTIONS,
      providers: { elevenlabs: true, openai: true, openrouter: true, gemini: true },
      settings: { topic: 'Should AI write music?', language: 'en', minutes: 6, listen_gap_s: 0.6, simulate: false, voice_min_level: 0.3,
                  heads_mirror: false, barge_in: 'normal', slow_network: true, lab_intro: true, people_mic: 'auto',
                  groups: [{ id: 'g1', name: 'Group 1', members: ['reachy:1', 'reachy:3'], talk: false, move: true }] },
      status: { phase: 'ready', speaker: null, elapsed_s: 0, detail: 'getting ready: checking every service', mode: null },
      transcript: [], error: null,
      voice_backend: {}, brain: {}, echo: { 'reachy:1': { peak_excess_db: 4.1 }, 'reachy:3': { peak_excess_db: 2.6 } },
      mics: ['Microphone (Wireless Mic Rx)', 'Microphone Array (Realtek(R) Audio)'], people_mic_active: 'Microphone (Wireless Mic Rx)',
      mic: { in_use: 'people', people_mic: 'Microphone (Wireless Mic Rx)', health: 'ok', robot_mics: [], dji: 'Microphone (Wireless Mic Rx)' },
      warm: { checks: CHECKS_PENDING, at: now() - 5, busy: true },
      ...o,
    };
  }
  const LIVE_TRANSCRIPT = [
    { id: 1, t: 0, kind: 'note', who: 'hub', text: 'Group talk started · lab intro: every robot says a line about the lab' },
    { id: 2, t: 1, kind: 'robot', who: 'reachy1', character: 'Max', move: 'intro', latency_ms: 820, text: 'Welcome to Laba Lab, where robots learn to listen. Today: should AI write music?' },
    { id: 3, t: 14, kind: 'robot', who: 'reachy3', character: 'Leo', move: 'challenge', latency_ms: 640, text: 'Write it, maybe. But who gets paid when a model copies a style it learned from a real band?' },
    { id: 4, t: 31, kind: 'robot', who: 'reachy1', character: 'Max', move: 'yes-but', latency_ms: 910, cut: true, text: 'Fair, but musicians already use these tools to sketch ideas faster, and the song is still theirs.' },
    { id: 5, t: 44, kind: 'human', who: 'people', heard_by: 'reachy:6', text: 'But can a machine feel sad when it writes a sad song?' },
    { id: 6, t: 47, kind: 'robot', who: 'reachy6', character: 'Reachy Mini 3', move: 'people', latency_ms: 1120, text: 'Feel it? No. Measure it? Sad songs are slower, 20% on average, and lean on minor keys.' },
    { id: 7, t: 178, kind: 'note', who: 'hub', text: 'operator: ask the people who their favourite band is' },
    { id: 8, t: 185, kind: 'robot', who: 'reachy3', character: 'Leo', move: 'people', latency_ms: 700, text: 'Before we vote: who here has a favourite band? Shout it out, and I will tell you whether a model could ever copy them.' },
  ];
  function liveState(o) {
    return groupState({
      running: true, mode: 'group', limit_s: 360,
      available: ROBOTS.map(r => ({ key: r.key, name: r.name, state: 'RUNNING' })),
      status: { phase: 'speaking', speaker: 'reachy3', character: 'Leo', elapsed_s: 192, detail: 'answering the room', mode: 'group' },
      transcript: clone(LIVE_TRANSCRIPT),
      people_live: "Radiohead! And honestly I don't think a computer could write Creep",
      eleven_credits: 40980,
      voice_backend: { 'reachy:1': 'elevenlabs', 'reachy:3': 'openai', 'reachy:6': 'gemini' },
      brain: { 'reachy:1': 'openrouter', 'reachy:3': 'openrouter', 'reachy:6': 'openrouter' },
      warm: { checks: CHECKS_OK, at: now() - 180, busy: false },
      ...o,
    });
  }

  /* ---------------------------------------------------------------- talk */
  const BRAINS = [
    { id: 'gemini-3.8', provider: 'gemini', label: 'Gemini 3.8 Live', key_ok: true, key_error: '', note: '' },
    { id: 'gemini-3.1', provider: 'gemini', label: 'Gemini 3.1 Flash Live (previous)', key_ok: true, key_error: '', note: '' },
    { id: 'gpt-live-1', provider: 'gpt_live', label: 'OpenAI GPT-Live-1', key_ok: false, key_error: 'No OpenAI key yet. Add one in Settings.', note: 'Hebrew is unverified on GPT-Live.' },
  ];
  const PRESETS = [{ id: 'scientist', label: 'Scientist' }, { id: 'cowboy', label: 'Cowboy' }, { id: 'jokes', label: 'Jokes only' }, { id: 'pirate', label: 'Pirate' }, { id: 'shy', label: 'Shy' }];
  const SCI = 'You are a curious scientist. You explain things with small experiments the person can try at home, and you get excited about numbers.';
  function backend(o) {
    return { brain: 'gemini-3.8', brains: BRAINS, voice: '', voices: ['Aoede', 'Kore', 'Charon', 'Puck', 'Leda'], default_voice: 'Aoede',
             el_not_recommended: false, language: 'en', languages: [{ id: 'he', label: 'עברית' }, { id: 'en', label: 'English' }, { id: 'auto', label: 'Auto (עברית / English)' }],
             elevenlabs: { enabled: false, key_ok: true, key_error: '', voice_id: '', voice_name: '', model: 'eleven_v4_turbo', models: ['eleven_v4_turbo', 'eleven_v4'] },
             vision: { enabled: true, available: true, source: 'robot camera', how: 'the model sees the frames' }, applies_next: true, ...o };
  }
  function persona(o) {
    return { enabled: true, overlay: SCI, preset_id: 'scientist', voice: '', presets: PRESETS, voices: ['Aoede', 'Kore', 'Charon', 'Puck', 'Leda'],
             default_voice: 'Aoede', active: true, max_chars: 1500, applies_next: true, ...o };
  }
  const LOG = [
    '14:12:02.114 INFO  client  conversation on Gemini 3.8 Live',
    '14:12:02.480 INFO  conversation  opener: hi + one question',
    '14:12:05.031 INFO  vision  frame 512x288, 1/s',
    '14:12:21.903 INFO  reachy.tools  [tool] play_emotion(name=nod) -> queued',
    '14:13:40.227 WARNING conversation  turn 4: Gemini silent, aborted',
    '14:14:02.660 INFO  reachy.tools  [tool] play_emotion(name=happy) -> queued',
    '14:14:03.012 DEBUG vad  speech end, 0.8 s hangover',
    '14:14:11.540 INFO  conversation  turn 7 listening',
    '14:14:13.901 INFO  conversation  turn 7 speaking',
  ];
  function talkSnapshot(o) {
    return {
      event: 'state.snapshot', state: 'CONVERSATION_RUNNING',
      robot: { connected: true, ip: '10.0.4.23', daemon_status: 'active' },
      conversation: { id: '1105-1412-a3', turn_count: 7, backend: 'Gemini 3.8 Live · en-US · Gemini Live voice Aoede', persona: 'preset:scientist' },
      identity: { robot: { display_name: 'reachy3' }, provider: { name: 'gemini', display_name: 'Gemini 3.8 Live', implemented: true },
                  key: { label: 'Lab Gemini', key_tail: 'a91f', source: 'hub' } },
      persona: persona(), backend: backend(), recent_log: LOG,
      transcript: [
        { role: 'robot', turn_id: 0, text: "Hi, I'm Reachy Mini. Want to see something cool with a glass of water?" },
        { role: 'user', turn_id: 1, text: 'Yes! What do I need?' },
        { role: 'robot', turn_id: 1, text: 'Just a glass, some water and a sheet of paper. Fill it to the top, cover it, then flip it over.' },
        { role: 'aborted', turn_id: 4, reason: 'gemini_silent' },
        { role: 'user', turn_id: 6, text: 'מה אתה רואה עכשיו?' },
        { role: 'robot', turn_id: 6, text: 'I see a blue mug on the table and someone waving at me. Hello there!' },
      ],
      ...o,
    };
  }
  const TALK_LIVE_EVENTS = [
    { event: 'turn.substate', state: 'SPEAKING', turn_id: 7 },
    { event: 'log', level: 'INFO', logger: 'reachy.tools', msg: '[tool] move_head(direction=up) -> queued', ts: '14:14:14.120' },
    { event: 'conversation.partial', turn: 7, turn_id: 7, who: 'robot', text: 'Now flip the glass fast, and pull the paper away slowly. The air pushes up', delta: ' up' },
  ];

  /* ---------------------------------------------------------------- show */
  function cue(id, hotkey, label, dur, text, motion, extra) {
    return { id, hotkey, label, duration_s: dur, text, motion, has_audio: !!text, audio_ready: !!dur || !text, section: '', ...extra };
  }
  const CATALOG = {
    sections: [
      { id: 'opening', title: 'Opening', cues: [cue('hello', '1', 'Hello', 2.1, "Hi, I'm Reachy. What's your name?", { type: 'emotion', name: 'happy' }),
        cue('meet', '2', 'Nice to meet you', 1.8, 'Nice to meet you! Want to see a trick?', { type: 'dance', name: 'groovy' }),
        cue('nod', 'n', 'Nod', null, '', { type: 'emotion', name: 'nod' })] },
      { id: 'topic', title: 'Topic', cues: [cue('glass1', 'g', 'Glass trick, part 1', 3.4, 'Fill the glass to the top and put the paper on it.', { type: 'head', direction: 'down' }),
        cue('glass2', 'h', 'Glass trick, part 2', 2.6, 'Pull the paper away slowly. The air holds the water in.', { type: 'head', direction: 'up' }),
        cue('why', 'j', 'Why it works', null, 'Air presses on everything, about one kilo on each fingernail.', null, { audio_ready: false, boss_cue: "Ask: why doesn't the water fall?" })] },
      { id: 'closing', title: 'Closing', cues: [cue('bye', 'b', 'Goodbye', 1.6, 'Thank you for playing with me. Bye!', { type: 'emotion', name: 'wave' }),
        cue('sleep', 'k', 'Sleep', null, '', { type: 'emotion', name: 'sleep' })] },
    ],
  };
  CATALOG.sections.forEach(s => s.cues.forEach(c => { c.section = s.id; }));
  CATALOG.order = CATALOG.sections.flatMap(s => s.cues.map(c => c.id));
  const SAID = [
    { id: 's1', text: "Hi, I'm Reachy. What's your name?", ms: 2100, prepared: true, at: now() - 180 },
    { id: 's3', text: 'Do you have a glass of water?', ms: 1900, prepared: true, at: now() - 60 },
  ];

  /* -------------------------------------------------------------- states */
  const D = {
    route: '#group', robots: ROBOTS, settings: SETTINGS, group: groupState(), talk: null, talkEvents: [],
    show: CATALOG, said: SAID, after: null, transcripts: { enabled: true, active: [] }, linkDown: false,
    api: {},
  };
  const STATES = {
    talk() { D.route = '#talk/reachy:3'; D.talk = talkSnapshot(); D.talkEvents = TALK_LIVE_EVENTS;
      D.transcripts = { enabled: true, active: [{ kind: 'talk', key: 'reachy:3', file: 'talk-2026-11-05_14-12-02-reachy3.txt' }] }; },
    'talk-refused'() { STATES.talk(); D.talk.state = 'IDLE_BREATHING'; D.talk.conversation = null; D.talk.transcript = []; D.talkEvents = [];
      D.talk.backend = backend({ brain: 'gpt-live-1', voices: ['gleam', 'meridian', 'quartz'], default_voice: 'gleam' });
      D.talk.identity.provider = { name: 'gpt_live', display_name: 'OpenAI GPT-Live-1', implemented: true };
      D.talk.identity.key = { error: 'No OpenAI key yet' };
      D.api['POST conversation/start'] = { status: 400, body: { error: 'refused', detail: 'GPT-Live-1 needs an OpenAI key. Add one in Settings, or pick Gemini.' } };
      D.after = () => setTimeout(() => document.getElementById('action-btn').click(), 50); },
    'talk-gptlive'() { STATES.talk(); D.talkEvents = [];
      D.talk.backend = backend({ brain: 'gpt-live-1', brains: BRAINS.map(b => ({ ...b, key_ok: true })), el_not_recommended: true,
        elevenlabs: { enabled: true, key_ok: true, voice_id: 'el-dan', voice_name: 'Daniel (English)' },
        vision: { enabled: true, available: true, source: 'robot camera', how: 'described for the model by gpt-4.1-mini' } }); },
    'talk-stopped'() { STATES.talk(); D.talkEvents = []; D.talk.state = 'STOPPED'; D.talk.conversation = null; D.talk.transcript = [];
      D.talk.error_message = 'microphone unavailable on the robot.'; D.transcripts = { enabled: true, active: [] }; },
    'talk-lost'() { STATES.talk(); D.talkEvents = [{ event: 'robot.heartbeat', ok: false }, { event: 'robot.heartbeat', ok: false },
      { event: 'robot.status', connected: false, ip: '10.0.4.23', daemon_status: 'unreachable' }]; },
    'talk-ended'() { STATES.talk(); D.talkEvents = [{ event: 'state.change', state: 'IDLE_BREATHING' },
      { event: 'conversation.ended', reason: 'end_phrase', summary: { turn_count: { total: 9, completed: 8, aborted: 1 }, latency: { gemini_first_chunk_ms: { median: 1100 } } } }];
      D.transcripts = { enabled: true, active: [] }; },
    'talk-character'() { STATES.talk(); D.talkEvents = [];
      D.talk.persona = persona({ overlay: 'x', preset_id: '', active: true });
      D.after = () => setTimeout(() => { const t = document.getElementById('persona-text'); t.value = SCI.repeat(13).slice(0, 1620); t.dispatchEvent(new Event('input')); document.getElementById('persona-save').click(); }, 80); },
    'talk-group'() { D.route = '#talk/reachy:1'; D.talk = null; D.linkDown = true; D.group = groupState({ warm: { checks: CHECKS_OK, at: now() - 60, busy: false } }); },
    'talk-inuse'() { D.route = '#talk/reachy:6'; D.talk = null; D.linkDown = true; D.group = groupState({ connected: false, connected_seats: [] });
      D.api['POST /api/robots/reachy%3A6/launch'] = { status: 409, body: { ok: false, conflict: true, error: 'reachy6 is in use by the Reachy Mini desktop app.' } };
      D.after = () => setTimeout(() => { const b = document.querySelector('#talk-gate .btn-primary'); if (b) b.click(); }, 80); },
    'talk-connect'() { D.route = '#talk/reachy:6'; D.talk = null; D.linkDown = true; D.group = groupState({ connected: false, connected_seats: [] });
      D.robots = ROBOTS.map(r => (r.key === 'reachy:6' ? { ...r, state: 'DETECTED' } : r)); },
    'talk-starting'() { D.route = '#talk/reachy:6'; D.talk = null; D.linkDown = true; D.group = groupState({ connected: false, connected_seats: [] });
      D.robots = ROBOTS.map(r => (r.key === 'reachy:6' ? { ...r, launching_since: now() - 12 } : r)); },
    picker() { D.route = '#talk'; },
    table() { D.route = '#group'; },
    'table-idle'() { D.group = groupState({ connected: false, connected_seats: [], status: { phase: 'idle', elapsed_s: 0, detail: '' }, warm: {},
      mic: { in_use: null, people_mic: '', health: '', robot_mics: [], dji: 'Microphone (Wireless Mic Rx)' },
      seats: seats().map((s, i) => (i === 1 ? { ...s, included: false } : s)) }); },
    'table-live'() { D.group = liveState(); D.transcripts = { enabled: true, active: [{ kind: 'group', key: 'group', file: 'group-2026-11-05_14-02-11-reachy1-reachy3-reachy6.txt' }] }; },
    'table-refused'() { D.group = groupState({ connected: false, connected_seats: [], status: { phase: 'idle' }, warm: {},
      error: "Couldn't start: include at least two connected Reachys." }); },
    'table-notsaved'() { D.group = groupState({ warm: { checks: CHECKS_OK, at: now() - 120, busy: false } });
      D.api['PUT /api/group/config'] = { status: 0, body: { error: "the hub didn't answer" } };
      D.after = () => setTimeout(() => { const t = document.querySelector('.seat-character'); t.value = 'Maxi'; t.dispatchEvent(new Event('input', { bubbles: true })); }, 80); },
    'table-checkfail'() { const checks = { ...CHECKS_OK, 'Voice of Leo': { ok: false, detail: 'ElevenLabsError: voice not found' } };
      D.group = groupState({ warm: { checks, at: now() - 30, busy: false }, status: { phase: 'ready', detail: 'connected, but Voice of Leo failed the check' } }); },
    'table-closing'() { D.group = liveState({ closing: true, status: { phase: 'speaking', speaker: 'reachy1', elapsed_s: 356, detail: '', mode: 'group' } }); },
    'table-overtime'() { D.group = liveState({ status: { phase: 'thinking', elapsed_s: 372, detail: 'answering the room', mode: 'group' }, closing: false }); },
    'table-interrupt'() { D.group = liveState({ mode: 'interrupt', status: { phase: 'human', elapsed_s: 64, detail: 'waiting for the person', mode: 'interrupt' } }); },
    'table-empty'() { D.robots = []; D.group = groupState({ connected: false, available: [], seats: [], connected_seats: [], status: { phase: 'idle' }, warm: {} }); },
    'table-credits'() { D.group = groupState({ eleven_credits: 1120, providers: { elevenlabs: false, openai: true, openrouter: true, gemini: true },
      seats: seats().map((s, i) => (i === 0 ? { ...s, voice_id: 'x8Kq3' } : (i === 1 ? { ...s, openai_voice: 'shimmer', voice_provider: 'openrouter' } : s))) }); },
    'table-simulate'() { D.group = groupState({ connected: false, connected_seats: [], status: { phase: 'idle' }, warm: {},
      settings: { ...groupState().settings, simulate: true },
      seats: [{ key: 'sim:1', name: 'laptop', included: true, listen: false, character: 'Reachy Mini 1' }], available: [] }); },
    'table-five'() { const extra = [{ key: 'reachy:7', name: 'reachy7', character: 'Ori' }, { key: 'sim:1', name: 'laptop', character: 'Noa', listen: false }];
      D.group = liveState({ seats: [...seats(), ...extra.map(x => ({ included: true, listen: true, voice_provider: 'auto', interrupt_level: 3, gestures: 'lively', vision: true, loudness: 150, ...x }))],
        available: [...ROBOTS.map(r => ({ key: r.key, name: r.name, state: 'RUNNING' })), { key: 'reachy:7', name: 'reachy7', state: 'RUNNING' }] }); },
    'table-notes'() { const extra = [
        { id: 9, t: 250, kind: 'note', text: "Leo's voice failed: timeout. It goes on." },
        { id: 10, t: 271, kind: 'note', text: "the people are heard through the robots' mics now" },
        { id: 11, t: 302, kind: 'note', text: '+1 min: it now ends at 7:00' }];
      D.group = liveState({ status: { phase: 'listening', elapsed_s: 305, detail: 'waiting for the rest', mode: 'group' }, limit_s: 420 });
      D.after = () => setTimeout(() => { const tr = document.getElementById('transcript'); tr.scrollTop = 0; tr.dispatchEvent(new Event('scroll'));
        setTimeout(() => { const st = RA.Group.state(); extra.forEach(t => RA.Group.handle({ type: 'group.turn', turn: t })); }, 400); }, 300); },
    groups() { STATES['table-live'](); D.group = groupState({ settings: { ...groupState().settings, groups: [
        { id: 'g1', name: 'Group 1', members: ['reachy:1', 'reachy:3'], talk: false, move: true },
        { id: 'g2', name: 'Team B', members: ['reachy:6'], talk: true, move: true }] }, warm: { checks: CHECKS_OK, at: now() - 60, busy: false } });
      D.transcripts = { enabled: true, active: [] };
      D.after = () => setTimeout(() => document.getElementById('groups-button').click(), 80); },
    copy() { D.group = groupState({ warm: { checks: CHECKS_OK, at: now() - 60, busy: false } });
      D.after = () => setTimeout(() => document.querySelector('.copy-button').click(), 80); },
    woz() { D.route = '#woz/reachy:3'; D.talk = talkSnapshot(); D.talkEvents = [
        { event: 'show.cue.started', cue_id: 'glass2', label: 'Glass trick, part 2', duration_s: 6.3, has_audio: true }];
      D.after = () => setTimeout(() => { document.activeElement.blur(); for (let i = 0; i < 5; i++) document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); }, 200); },
    'woz-off'() { STATES.woz(); D.talk.state = 'STOPPED'; D.talkEvents = []; },
    editor() { STATES.woz(); D.talkEvents = [];
      D.after = () => setTimeout(() => { document.querySelectorAll('.cue .ed')[5].click(); setTimeout(() => { const h = document.getElementById('ed-hotkey'); h.value = 'g'; h.dispatchEvent(new Event('input')); }, 200); }, 200); },
  };

  /* ----------------------------------------------------------- transport */
  const reply = (status, body) => Promise.resolve({ ok: status >= 200 && status < 300, status, body });

  function api(method, url, payload) {
    const path = url.split('?')[0];
    const reachy = /^\/api\/reachy\/([^/]+)\/(.*)$/.exec(path);
    const sub = reachy ? reachy[2] : '';
    const custom = D.api[`${method} ${sub}`] || D.api[`${method} ${path}`];
    if (custom) return reply(custom.status, custom.body);
    if (path === '/api/group/state') return reply(200, D.group);
    if (path === '/api/group/config' && method === 'PUT') {
      const st = clone(D.group);
      st.settings = { ...st.settings, ...(payload.settings || {}) };
      return reply(200, st);
    }
    if (path.startsWith('/api/group/')) return reply(200, { ok: true });
    if (path === '/api/transcripts/current') return reply(200, D.transcripts);
    if (path === '/api/log') return reply(200, { log: [] });
    if (path === '/api/settings' && method === 'PUT') { Object.assign(D.settings, payload); return reply(200, D.settings); }
    if (/^\/api\/robots\/[^/]+$/.test(path)) {
      const r = D.robots.find(x => `/api/robots/${encodeURIComponent(x.key)}` === path) || {};
      return reply(200, { ...r, keys: {}, has_wifi: true, postures: [], staff_tools: false });
    }
    if (/^\/api\/robots\/.+\/(launch|override|connect|disconnect)$/.test(path)) return reply(200, { ok: true });
    if (reachy) {
      if (sub === 'show/cues') return reply(200, { ...D.show, playing: null, state: D.talk ? D.talk.state : 'IDLE_BREATHING' });
      if (sub === 'show/said') return reply(200, { said: D.said });
      if (sub === 'show/motions') return reply(200, { emotions: ['happy', 'nod', 'sad', 'wave', 'sleep'], dances: ['groovy', 'chicken'], directions: ['left', 'right', 'up', 'down', 'front'] });
      if (sub === 'show/prepare') return reply(200, { id: 'p1', ready: true, ms: 1800, text: payload.text });
      if (sub === 'show/say') return reply(200, { played: true, prepared: true, ms: 1800, id: 'p1', text: payload.text, waited_ms: 0 });
      if (sub === 'volume') return reply(200, { level: 120, max: 150 });
      if (sub === 'backend' && D.talk) return reply(200, { ...D.talk.backend, ...payload });
      if (sub === 'persona' && D.talk) return reply(200, { ...D.talk.persona, ...payload });
      if (sub === 'backend/elevenlabs/voices') return reply(200, { voices: [{ voice_id: 'el-dan', name: 'Daniel', language: 'English' }, { voice_id: 'el-adam', name: 'Adam', language: 'English' }] });
      return reply(200, {});
    }
    return reply(200, {});
  }

  function socket(path, handlers) {
    const link = { live: true, close() {}, send() {}, reconnect() {} };
    const deliver = (list) => list.forEach((m, i) => setTimeout(() => handlers.message(m), 10 + i * 5));
    setTimeout(() => {
      if (handlers.open) handlers.open();
      if (path === '/ws') {
        deliver([{ type: 'snapshot', robots: D.robots, settings: D.settings, network: {}, keys: {}, setup: [], log: [
          { type: 'log', level: 'ok', text: 'reachy3: launched -> http://10.0.4.23:8765/', ts: now() - 300 },
          { type: 'log', level: 'info', text: 'group: Group talk started', ts: now() - 200 }] },
          { type: 'transcripts', ...D.transcripts }]);
      } else if (path === '/ws/group') {
        deliver([{ type: 'group.state', ...D.group }]);
      } else if (path.startsWith('/ws/reachy/')) {
        if (D.linkDown || !D.talk) deliver([{ event: 'proxy.error', code: 'NOT_RUNNING', error: 'not running' }]);
        else deliver([{ event: 'proxy.open' }, D.talk, ...D.talkEvents]);
      }
    }, 0);
    return link;
  }

  // A script error in demo mode shows on the page, so a screenshot catches it.
  function showError(text) {
    const bar = document.createElement('p');
    bar.className = 'demo-error';
    bar.style.cssText = 'position: fixed; left: 0; right: 0; bottom: 0; z-index: 999; margin: 0; padding: 8px 12px; background: #B91C1C; color: #FFFFFF; font: 13px monospace;';
    bar.textContent = `demo error: ${text}`;
    document.body.append(bar);
  }
  window.addEventListener('error', (e) => showError(`${e.message} (${e.filename}:${e.lineno})`));
  window.addEventListener('unhandledrejection', (e) => showError(String(e.reason && (e.reason.stack || e.reason))));
  const origError = console.error;
  console.error = (...args) => { showError(args.map(a => (a && a.stack) || String(a)).join(' ')); origError.apply(console, args); };

  RA.demo = {
    install(state) {
      (STATES[state] || STATES.table)();
      if (location.hash !== D.route) history.replaceState(null, '', `${location.pathname}${location.search}${D.route}`);
      this.after = D.after;
    },
    api, socket, data: D,
  };
})();
