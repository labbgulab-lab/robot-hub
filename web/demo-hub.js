/* Demo mode for the hub page: /?demo=<state> renders from fake data, so every
   design board (docs/design/renders) can be screenshotted without a hub or
   robots. Loaded only when ?demo= is in the URL; never used otherwise.

   States: hub (default), main, keylater, robotpanel, robotpanel2, wifiresults,
   network, logs, settings, files, setup, hotspot, cardstates, norobots,
   starting, stopped, update, updating, logsdot, chip-hotspot, chip-full,
   chip-5ghz, chip-vpn, chip-nowifi, key-checking, key-ok, key-bad,
   key-nocredit, key-offline, key-unknown, key-voice, key-dup, key-notakey,
   setup-downloading, setup-unpacking, setup-verifying, setup-broke,
   setup-wrongzip, setup-diskfull, setup-done. */
(function () {
  'use strict';
  const now = () => Date.now() / 1000;
  const T0 = now();

  function robot(key, type_id, name, state, extra) {
    return Object.assign({
      type: 'robot', key, type_id, name, state, address: null, battery: null, detail: '',
      mic: null, system_url: null, daemon_version: null, can_speak: true, disabled_reason: null,
      launching_since: null, launch_error: null, posture_pending: null, posture_note: null,
      posture_failed: false, connect_error: null, battery_low: false, charging: null, in_use_by: null,
      needs_setup: null, staff_only_actions: type_id === 'naoqi' ? ['nao_app'] : [], last_seen: now(),
      facts: { robot_software: null, mic: null, holds: [], seen_ago: 2 },
    }, extra || {});
  }
  const K = {
    gem: { id: 'k1', provider: 'gemini', label: 'Lab Gemini', tail: 'a91f', status: { state: 'works', detail: 'Works.', credit: null }, used_by: ['reachy1', 'Furhat'], voice_only: false, groups_only: false },
    gpt5: { id: 'k2', provider: 'gpt', label: 'Lab OpenAI', tail: '5b12', status: { state: 'works', detail: 'Works.', credit: null }, used_by: ['Pepper'], voice_only: false, groups_only: false },
    gpt3: { id: 'k5', provider: 'gpt', label: 'My OpenAI', tail: '3c07', status: { state: 'works', detail: 'Works.', credit: null }, used_by: [], voice_only: false, groups_only: false },
    or: { id: 'k3', provider: 'openrouter', label: 'Lab OpenRouter', tail: '7c20', status: { state: 'works', detail: '$4.20 left', credit: { left: 4.2, limit: 5, unit: 'usd' } }, used_by: [], voice_only: false, groups_only: true },
    el: { id: 'k4', provider: 'elevenlabs', label: 'Lab ElevenLabs', tail: 'e01b', status: { state: 'no_credit', detail: 'No characters left.', credit: null }, used_by: ['Pepper'], voice_only: true, groups_only: false },
  };
  const ALL = ['gemini', 'gpt', 'elevenlabs', 'openrouter', 'qwen'];
  const pub = k => k && Object.assign({}, k);
  function slot(key, assigned, how, providers) { return { key: pub(key), assigned: assigned || null, how: how || 'assigned', providers }; }

  function hubData() {
    const robots = [
      robot('reachy:r1', 'reachy_wireless', 'reachy1', 'RUNNING', { address: '10.0.4.21', detail: 'ready, control loop 50 Hz', system_url: 'http://10.0.4.21:8765/', daemon_version: '1.13.0', mic: 'Wireless Mic Rx (this laptop)', facts: { robot_software: 'Daemon 1.13.0 · reachy_chat on the robot', mic: 'Wireless Mic Rx (this laptop)', holds: ['Microphone'], seen_ago: 2 } }),
      robot('reachy:r3', 'reachy_wireless', 'reachy3', 'CONNECTED', { address: '10.0.4.23', detail: 'ready', daemon_version: '1.13.0' }),
      robot('reachy:r6', 'reachy_wireless', 'reachy6', 'DETECTED', { address: '10.0.4.26', detail: 'detected at 10.0.4.26' }),
      robot('furhat:f1', 'furhat', 'Furhat', 'CONNECTED', { address: '10.0.4.30', detail: 'Studio running. Voice: Matthew' }),
      robot('naoqi:n1', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 78, detail: 'broker answering', posture_note: 'NAO is sitting, motors off (hottest joint: left knee 54 °C)', daemon_version: '2.8.6.23', mic: 'Windows default input (NAO app)' }),
      robot('pepper:p1', 'pepper', 'Pepper', 'RUNNING', { address: '10.0.4.41', battery: 62, detail: 'system running', system_url: 'http://127.0.0.1:8780/', daemon_version: '2.5.10.7', mic: "Pepper's own four microphones", facts: { robot_software: 'NAOqi 2.5.10.7', mic: "Pepper's own four microphones", holds: ['Port 8780'], seen_ago: 1 } }),
      robot('reachy:r2', 'reachy_wireless', 'reachy2', 'ABSENT', { last_seen: T0 - 5000 }),
      robot('reachy:r5', 'reachy_wireless', 'reachy5', 'ABSENT', { last_seen: T0 - 9000 }),
      robot('placeholder:reachy_lite', 'reachy_lite', 'Reachy Mini Lite', 'ABSENT', { needs_setup: null }),
    ];
    const keys = [K.gem, K.gpt5, K.or, K.el, K.gpt3];
    const slots = {
      'reachy:r1': { main: slot(K.gem, 'k1', 'assigned', ALL) },
      'reachy:r3': { main: slot(K.gem, null, 'no key assigned, using the first Gemini key', ALL) },
      'reachy:r6': { main: slot(K.gem, null, 'no key assigned, using the first Gemini key', ALL) },
      'reachy:r2': { main: slot(K.gem, null, 'no key assigned, using the first Gemini key', ALL) },
      'reachy:r5': { main: slot(K.gem, null, 'no key assigned, using the first Gemini key', ALL) },
      'furhat:f1': { main: slot(K.gem, 'k1', 'assigned', ['gpt', 'gemini', 'openrouter']) },
      'pepper:p1': { main: slot(K.gpt5, 'k2', 'assigned', ['gpt']), voice: slot(K.el, 'k4', 'assigned', ['elevenlabs']) },
    };
    return {
      robots,
      network: { state: 'ok', ssid: 'HOT-WiFi', band: '2.4 GHz', kind: 'lab', ranges: ['10.0.4.0/24'], hotspot: { devices: 7, limit: 5 }, robots_network: { ssid: 'HOT-WiFi', last_seen: T0 }, vpn: [], detail: '', expected: 'HOT-WiFi', on_robot_subnet: true, interfaces: ['10.0.4.12'] },
      settings: { auto_connect: true, staff_tools: true, save_transcripts: true, setup_seen: true, lab_wifi: { name: 'HOT-WiFi', open: true }, passwords: { furhat: { set: true, works: true } }, robots_network: { ssid: 'HOT-WiFi', last_seen: T0 } },
      keys: { type: 'keys', keys, providers: [], assign: {}, slots },
      setup: [
        { id: 'naoqi_kit', label: 'Pepper and NAO kit', for: ['naoqi', 'pepper'], state: 'ok', progress: null, detail: 'Installed.', code: null, actions: ['check'] },
        { id: 'reachy_lite_app', label: 'Reachy Mini Control app', for: ['reachy_lite'], state: 'missing', progress: null, detail: 'Install Reachy Mini Control from Pollen.', code: null, actions: ['open', 'check'] },
        { id: 'furhat_password', label: 'Furhat password', for: ['furhat'], state: 'ok', progress: null, detail: 'Works.', code: null, actions: ['check'] },
      ],
      log: [],
    };
  }

  const LOG = [
    ['14:02:31', 'info', 'Looking for robots on HOT-WiFi'],
    ['14:02:33', 'info', 'Found reachy1, reachy3, reachy6 and Furhat'],
    ['14:02:40', 'info', 'reachy1: connecting'],
    ['14:02:42', 'ok', 'reachy1: connected. Said hello.'],
    ['14:02:47', 'info', 'reachy1: speaking through Lab Gemini (...a91f; assigned)'],
    ['14:02:55', 'ok', 'reachy1: launched -> talking, listening through Microphone (Wireless Mic Rx)'],
    ['14:03:12', 'info', 'reachy1 heard: "hi, what\'s your name?"'],
    ['14:03:13', 'info', 'reachy1 answered in 1.1 s'],
    ['14:04:02', 'warn', 'Furhat: not answering. Trying again in 5 s'],
    ['14:04:07', 'ok', 'Furhat recovered'],
    ['14:05:20', 'info', 'reachy3 said: "I am reachy3, I am connected and ready to run."'],
    ['14:06:41', 'info', 'reachy1 heard: "tell me about the lab"'],
    ['14:06:42', 'info', 'reachy1 answered in 1.3 s'],
    ['14:07:05', 'info', 'Pepper: speaking through Lab OpenAI (...5b12; assigned). Voice: Lab ElevenLabs (...e01b)'],
    ['14:07:09', 'info', 'Pepper: pepper_app dashboard on http://127.0.0.1:8780/'],
    ['14:07:31', 'error', 'NAO: launch failed - NAO_LLM refuses to start without OPENAI_API_KEY -- add it to .env'],
  ];
  function logEntries() {
    const d = new Date(); d.setHours(14, 0, 0, 0);
    return LOG.map(([t, level, text]) => {
      const [h, m, s] = t.split(':').map(Number);
      const x = new Date(d); x.setHours(h, m, s);
      return { type: 'log', level, text, ts: x.getTime() / 1000 };
    });
  }

  function byKey(data, key) { return data.robots.find(r => r.key === key); }
  function setRobot(data, key, fields) { Object.assign(byKey(data, key), fields); }

  function cardStates(data) {
    // One card per state (docs/design/CardStates), each with its caption.
    const R = [];
    const add = (cap, r, slots) => { r._caption = cap; R.push(r); if (slots) data.keys.slots[r.key] = slots; };
    const gemDef = { main: slot(K.gem, null, 'no key assigned, using the first Gemini key', ALL) };
    add('Not nearby', robot('c:2', 'reachy_wireless', 'reachy2', 'ABSENT', { last_seen: T0 - 3600 }));
    add('Connecting', robot('c:3', 'reachy_wireless', 'reachy6', 'CONNECTING', { address: '10.0.4.26', detail: 'connecting' }), gemDef);
    add('Connected, could not speak', robot('c:4', 'furhat', 'Furhat', 'CONNECTED', { address: '10.0.4.30', can_speak: false, detail: 'connected, but could not speak' }));
    add('Starting', robot('c:5', 'pepper', 'Pepper', 'CONNECTED', { address: '10.0.4.41', battery: 62, launching_since: now() - 23 }));
    add('First Talk on a new Reachy', robot('c:6', 'reachy_wireless', 'reachy7', 'CONNECTED', { address: '10.0.4.27', launching_since: now() - 100 }));
    add('Start failed', robot('c:7', 'pepper', 'Pepper', 'CONNECTED', { address: '10.0.4.41', battery: 61, launch_error: "the dashboard didn't answer on port 8780" }));
    add('Something else is using it', robot('c:8', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 70 }));
    add('About to stop', robot('c:9', 'reachy_wireless', 'reachy3', 'DEGRADED', { address: '10.0.4.23', detail: 'Control loop errors (3). It usually stops about 7 s later.' }), { main: slot(K.gem, 'k1', 'assigned', ALL) });
    add('Old robot software', robot('c:10', 'reachy_wireless', 'reachy5', 'DETECTED', { address: '10.0.4.25', detail: 'ready -- daemon 1.9.2 is older than 1.10.0, where `ready` is permanently false' }));
    add('Not answering yet', robot('c:11', 'reachy_wireless', 'reachy1', 'DEGRADED', { address: '10.0.4.21', detail: 'Not answering yet. Restarting?' }));
    add('Lost, retrying', robot('c:12', 'reachy_wireless', 'reachy6', 'ERROR', { address: '10.0.4.26', detail: 'connect timed out', retry_at: now() + 20 }));
    add("Key that can't talk", robot('c:13', 'reachy_wireless', 'reachy3', 'CONNECTED', { address: '10.0.4.23' }), { main: slot(K.el, 'k4', 'assigned', ALL) });
    add('Pepper without a GPT key', robot('c:14', 'pepper', 'Pepper', 'CONNECTED', { address: '10.0.4.41', battery: 58 }), { main: slot(null, null, 'no GPT key in the hub', ['gpt']) });
    add('In use by another laptop', robot('c:15', 'reachy_wireless', 'reachy4', 'DETECTED', { address: '10.0.4.24', in_use_by: 'LAB-LAPTOP-3' }));
    add('Moved to a hotspot', robot('c:16', 'reachy_wireless', 'reachy8', 'ABSENT', {}));
    add('NAO moving', robot('c:17', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 77, posture_pending: 'sit' }));
    add('NAO too hot', robot('c:18', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 71, posture_note: 'Not standing: left knee is 64 °C, the limit is 60 °C. Let it cool', posture_failed: true }));
    add('NAO stand, battery low', robot('c:19', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 12, battery_low: true }));
    add("NAO didn't finish", robot('c:20', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 69, posture_note: "NAO didn't reach Sit. Motors left on. Check on it", posture_failed: true }));
    add('Pepper key changed while running', robot('c:21', 'pepper', 'Pepper', 'RUNNING', { address: '10.0.4.41', battery: 64, detail: 'Dashboard was already running', system_url: 'http://127.0.0.1:8780/', _changedRunning: true }), { main: slot(K.gpt3, 'k5', 'assigned', ['gpt']), voice: slot(K.el, 'k4', 'assigned', ['elevenlabs']) });
    add('Reachy Mini Lite on USB', robot('c:22', 'reachy_lite', 'Reachy Mini Lite', 'CONNECTED', { address: '127.0.0.1', detail: 'Daemon ready' }));
    add('Needs setup', robot('placeholder:naoqi', 'naoqi', 'NAO', 'DISABLED', { address: '10.0.4.40', needs_setup: 'naoqi_kit' }));
    add('Reachy blocked by another robot', robot('c:24', 'reachy_wireless', 'reachy3', 'CONNECTED', { address: '10.0.4.23' }), { main: slot(K.gem, 'k1', 'assigned', ALL) });
    add('NAO app, first start', robot('c:25', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 80, launching_since: now() - 40 }));
    add('NAO app running', robot('c:26', 'naoqi', 'NAO', 'RUNNING', { address: '10.0.4.40', battery: 76, detail: 'NAO app on port 9600', system_url: 'http://127.0.0.1:9600/' }));
    add("NAO app can't start", robot('c:27', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 75, launch_error: 'NAO_LLM refuses to start without OPENAI_API_KEY -- add it to .env' }));
    add('NAO already there', robot('c:28', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 74, posture_note: 'NAO was already sitting, nothing moved' }));
    add('Furhat needs its password', robot('c:29', 'furhat', 'Furhat', 'CONNECTED', { address: '10.0.4.30', _pwBad: true }));
    add('Windows blocks Pepper', robot('c:30', 'pepper', 'Pepper', 'CONNECTED', { address: '10.0.4.41', battery: 62, launch_error: 'Windows firewall blocks port 8782' }), { main: slot(K.gpt5, 'k2', 'assigned', ['gpt']), voice: slot(K.el, 'k4', 'assigned', ['elevenlabs']) });
    add('Battery low', robot('c:31', 'naoqi', 'NAO', 'CONNECTED', { address: '10.0.4.40', battery: 14, battery_low: true }));
    add('Unknown robot', robot('c:32', 'mystery', 'Robot', 'DETECTED', { address: '10.0.4.51' }));
    data.robots = R;
    return R;
  }

  const Demo = {
    data: null,
    hub: null,
    state: 'hub',
    wait(ms) { return new Promise(r => setTimeout(r, ms)); },

    start(state, Hub) {
      this.state = state;
      this.hub = Hub;
      const data = this.data = hubData();
      const ui = Hub.ui;
      let after = null;
      data.log = logEntries();
      const nokeys = () => { data.keys.keys = []; Object.keys(data.keys.slots).forEach(k => { const s = data.keys.slots[k]; Object.keys(s).forEach(x => { s[x] = slot(null, null, 'no key in the hub', s[x].providers); }); }); };
      switch (state) {
        case 'main':
          nokeys();
          data.robots = data.robots.filter(r => ['reachy:r1', 'reachy:r3', 'furhat:f1'].includes(r.key));
          after = () => { Hub.openPopup(); };
          break;
        case 'keylater':
          nokeys();
          data.robots = [
            robot('reachy:r1', 'reachy_wireless', 'reachy1', 'CONNECTED', { address: '10.0.4.21', detail: 'ready' }),
            robot('reachy:r3', 'reachy_wireless', 'reachy3', 'DETECTED', { address: '10.0.4.23', detail: 'detected at 10.0.4.23' }),
            robot('furhat:f1', 'furhat', 'Furhat', 'CONNECTED', { address: '10.0.4.30', detail: 'Studio running' }),
          ];
          after = () => Hub.toast('Add a key any time in Settings.', 'info');
          break;
        case 'robotpanel':
          after = () => {
            ui.wifi['reachy:r1'] = { ssid: 'Lab Phone', pw: 'password1', open: false, save: false };
            Hub.openDetails('reachy:r1');
          };
          break;
        case 'robotpanel2':
          after = () => {
            ui.wifi['pepper:p1'] = { ssid: 'Lab Phone', pw: 'password1', open: false, save: false };
            ui.wifiBusy['pepper:p1'] = true;
            Hub.openDetails('pepper:p1');
          };
          break;
        case 'wifiresults': {
          const notes = [
            ['Before Join', 'warn', 'Type the hotspot name.'],
            ['Before Join', 'warn', 'A WiFi password has at least 8 characters.'],
            ['Done', 'ok', 'Pepper joined "Lab Phone" and will remember it. Move this laptop there too.'],
            ['Done', 'ok', 'reachy3 is already on "Lab Phone". Its password is updated.'],
            ['Done', 'warn', 'reachy3 saved "Lab Phone" but can\'t see it now, so it stays on "HOT-WiFi".'],
            ["Didn't work", 'err', 'Pepper couldn\'t join "Lab Phone". Wrong password? It is back on "HOT-WiFi".'],
            ["Didn't work", 'err', 'Pepper is starting its app. Wait for it, then try again.'],
            ["Didn't work", 'err', '"reachy-mini-ap" is the robot\'s own setup network.'],
            ["Didn't work", 'err', "Couldn't ask the hub. Is Robot Hub running?"],
          ];
          data.robots = notes.map((n, i) => Object.assign(robot('w:' + i, i % 2 ? 'reachy_wireless' : 'pepper', i % 2 ? 'reachy3' : 'Pepper', 'CONNECTED', { address: '10.0.4.4' + i }), { _caption: n[0] }));
          notes.forEach((n, i) => { ui.wifiNote['w:' + i] = { kind: n[1], text: n[2] }; });
          Hub.flags.captions = true;
          break;
        }
        case 'network':
          Object.assign(data.network, { state: 'wrong_network', ssid: 'eduroam', band: '5 GHz', kind: 'other', expected: 'HOT-WiFi' });
          data.robots.forEach(r => { if (r.state !== 'ABSENT') r.state = 'ABSENT'; });
          after = () => { ui.sheet = { kind: 'network' }; };
          break;
        case 'logs':
          after = () => { ui.logs = true; };
          break;
        case 'settings':
          after = () => { Hub.setView('settings'); ui.keyArm = 'k3'; ui.resources = { resources: [{ resource: 'audio_in:', owner: 'reachy1', mode: 'require' }], ports: { 8780: 'Pepper' } }; };
          break;
        case 'files':
          after = () => { Hub.ui.files.robot = 'reachy_wireless'; Hub.setView('files'); };
          break;
        case 'setup':
          data.setup[0] = { id: 'naoqi_kit', label: 'Pepper and NAO kit', for: ['naoqi', 'pepper'], state: 'missing', progress: null, detail: 'One free download, about 360 MB.', code: null, actions: ['download', 'choose_zip', 'open', 'check'] };
          after = () => { ui.sheet = { kind: 'setup', id: 'naoqi_kit' }; };
          break;
        case 'hotspot':
          after = () => { Hub.setView('hotspot'); ui.hotspot.picked = ['reachy:r1', 'reachy:r3', 'pepper:p1']; };
          break;
        case 'cardstates':
          cardStates(data);
          Hub.flags.captions = true;
          ui.conflicts['c:8'] = 'The microphone is in use by reachy1. Stop it first, or override.';
          ui.conflicts['c:24'] = 'The microphone is in use by NAO. Stop it first, or override.';
          ui.moved['c:16'] = 'Lab Phone';
          ui.armed['c:19'] = 1;
          break;
        case 'norobots':
          Object.assign(data.network, { state: 'wrong_network', ssid: 'eduroam', band: null, kind: 'other', expected: 'HOT-WiFi' });
          data.robots = data.robots.filter(r => r.state === 'ABSENT' && r.key.startsWith('placeholder:'));
          data.setup[1].state = 'ok';
          break;
        case 'starting': Hub.flags.boot = true; break;
        case 'stopped': after = () => { ui.stopped = true; }; break;
        case 'update': after = () => { Hub.S.app = { version: '1.0.0', update: { available: true, latest: 'v1.1.0' } }; }; break;
        case 'updating': after = () => { ui.updating = true; }; break;
        case 'logsdot': after = () => { ui.logUnseen = true; }; break;
        case 'chip-hotspot': Object.assign(data.network, { kind: 'hotspot', ssid: 'Lab Phone', hotspot: { devices: 3, limit: 5 } }); break;
        case 'chip-full': Object.assign(data.network, { kind: 'hotspot', ssid: 'Lab Phone', hotspot: { devices: 5, limit: 5 } }); break;
        case 'chip-5ghz': Object.assign(data.network, { state: 'hotspot_5ghz', kind: 'hotspot', ssid: 'Lab Phone', band: '5 GHz' }); break;
        case 'chip-vpn': Object.assign(data.network, { state: 'vpn_on', vpn: ['Tailscale'] }); break;
        case 'chip-nowifi': Object.assign(data.network, { state: 'no_network', kind: 'none', ssid: null, band: null }); break;
        default:
          if (state.startsWith('key-')) {
            nokeys();
            const k = { 'key-nocredit': 'sk-proj-xxxxxxxxxxxxa91f', 'key-offline': 'AIzaSyxxxxxxxxxxxxQx2c', 'key-unknown': 'x7Gk2xxxxxxxxxxxx9pLm', 'key-voice': 'sk_3fxxxxxxxxxxxxe01b', 'key-dup': 'AIzaSyxxxxxxxxxxxxQx2c', 'key-notakey': 'hello', 'key-bad': 'AIzaSyBADxxxxxxxxx', 'key-ok': 'sk-proj-xxxxxxxxxxxxxxxxxxxxa91f', 'key-checking': 'sk-proj-xxxxxxxxxxxxxxxxa91f' }[state] || '';
            after = () => {
              Hub.openPopup();
              ui.popup.key = k;
              if (state === 'key-checking') ui.popup.phase = 'checking';
              else Demo.popupResult = state;
            };
          } else if (state.startsWith('setup-')) {
            const kit = data.setup[0];
            const st = {
              'setup-downloading': { state: 'downloading', progress: { done: 147 * 1048576, total: 358 * 1048576 }, actions: ['cancel'] },
              'setup-unpacking': { state: 'unpacking', progress: { done: 2400, total: 6000 }, actions: ['cancel'] },
              'setup-verifying': { state: 'verifying', progress: null, actions: ['cancel'] },
              'setup-broke': { state: 'failed', code: 'DOWNLOAD_BROKE', detail: 'The download stopped.', actions: ['download', 'choose_zip', 'open', 'check'] },
              'setup-wrongzip': { state: 'failed', code: 'WRONG_ZIP', detail: "That zip isn't the kit.", actions: ['download', 'choose_zip', 'open', 'check'] },
              'setup-diskfull': { state: 'failed', code: 'DISK_FULL', detail: 'Not enough space.', actions: ['download', 'choose_zip', 'open', 'check'] },
              'setup-done': { state: 'ok', detail: 'Installed.', actions: ['check'] },
            }[state] || {};
            Object.assign(kit, { code: null, progress: null }, st);
            after = () => { ui.sheet = { kind: 'setup', id: 'naoqi_kit' }; };
          }
      }
      if (state === 'keylater') { try { sessionStorage.setItem('hub.keyLater', '1'); } catch (e) { /* demo */ } }
      Hub.handle(Object.assign({ type: 'snapshot' }, data));
      Hub.S.snapshotAt = Date.now() - 60000;   // past the first-seconds skeleton
      if (!['network'].includes(state)) Hub.ui.sheet = null;
      Hub.S.lastEvent = (function () { const d = new Date(); d.setHours(14, 6, 41, 0); return d.getTime() / 1000; })();
      Hub.S.live = 'live';
      Hub.S.app = Hub.S.app.version ? Hub.S.app : { version: '1.0', update: { available: false } };
      if (state === 'hub') Hub.toast('reachy3 will speak through Lab Gemini');
      if (after) after();
      if (Demo.popupResult) this.applyPopupResult();
      Hub.render();
    },

    applyPopupResult() {
      const ui = this.hub.ui;
      const s = Demo.popupResult;
      const res = {
        'key-nocredit': { ok: true, key: { provider: 'gpt', status: { state: 'no_credit' } } },
        'key-offline': { ok: true, key: { provider: 'gemini', status: { state: 'offline' } } },
        'key-voice': { ok: true, key: { provider: 'elevenlabs', status: { state: 'works' } } },
        'key-ok': { ok: true, key: { provider: 'gpt', status: { state: 'works' } } },
        'key-unknown': { ok: false, code: 'UNKNOWN_PROVIDER' },
        'key-dup': { ok: false, code: 'DUPLICATE', label: 'Lab Gemini' },
        'key-notakey': { ok: false, code: 'NOT_A_KEY' },
        'key-bad': { ok: false, code: 'KEY_REFUSED' },
      }[s];
      if (!res) return;
      ui.popup.result = this.hub.keyResult ? this.hub.keyResult(res) : null;
      ui.popup._demo = res;
    },

    async api(method, path, body) {
      const data = this.data;
      const Hub = this.hub;
      await this.wait(120);
      let m;
      if (path === '/api/app') return { ok: true, version: Hub.S.app.version || '1.0', data_dir: '', first_run: false, update: (Hub.S.app.update || { available: false }) };
      if (path.startsWith('/api/log?')) return { ok: true, log: logEntries() };
      if (path === '/api/log/report') return { ok: true, path: 'C:/Downloads/robot-hub-report.zip' };
      if (path === '/api/network') return Object.assign({ ok: true }, Hub.S.network);
      if (path === '/api/rescan') return { ok: true };
      if (path === '/api/doctor') return { ok: true, checks: [{ name: 'Python 3.11+', ok: true, detail: 'running 3.12.7' }, { name: 'Pepper and NAO kit', ok: true, detail: 'C:/LabaLab/naoqi-sdk' }, { name: 'Port 8780', ok: false, detail: 'in use', remedy: 'Close the other Pepper dashboard.' }] };
      if (path === '/api/resources') return { ok: true, resources: [{ resource: 'audio_in:', owner: 'reachy1', mode: 'require' }], ports: { 8780: 'Pepper' } };
      if (path === '/api/files' && method === 'POST') return { ok: false, exists: true, error: `${body.name} is already shared` };
      if (path === '/api/files') {
        return { ok: true, repo: 'labbgulab-lab/robot-hub', robots: [{ id: 'furhat', label: 'Furhat' }, { id: 'reachy_wireless', label: 'Reachy Mini' }, { id: 'reachy_lite', label: 'Reachy Mini Lite' }, { id: 'naoqi', label: 'NAO' }, { id: 'pepper', label: 'Pepper' }],
          files: [
            { id: 1, robot: 'reachy_wireless', name: 'group-demo.json', size: 4096, uploader: 'labbgulab-lab', updated: '2026-11-03T10:00:00Z', needs: ['gemini'] },
            { id: 2, robot: 'reachy_wireless', name: 'persona-pack.zip', size: 2.1 * 1048576, uploader: 'labbgulab-lab', updated: '2026-10-28T10:00:00Z', needs: ['gemini'] },
            { id: 3, robot: 'reachy_wireless', name: 'video-bank-clips.zip', size: 380 * 1048576, uploader: 'labbgulab-lab', updated: '2026-10-19T10:00:00Z', needs: [] },
            { id: 4, robot: 'reachy_wireless', name: 'old-voices.json', size: 2048, uploader: 'labbgulab-lab', updated: '2026-10-02T10:00:00Z', needs: [] },
            { id: 5, robot: 'furhat', name: 'lab-skill.skill', size: 85 * 1048576, uploader: 'labbgulab-lab', updated: '2026-10-12T10:00:00Z', needs: ['gpt'] },
          ] };
      }
      if ((m = /^\/api\/robots\/([^/]+)\/wifi$/.exec(path))) {
        if (method === 'GET') return { ok: true, supported: true, networks: [{ ssid: 'HOT-WiFi', current: true, note: null }, { ssid: 'Lab Phone', current: false, note: null }, { ssid: 'Old Phone', current: false, note: "won't join by itself" }, { ssid: 'reachy-mini-ap', current: false, note: 'its own setup network' }] };
        await this.wait(1500);
        return { ok: true, message: `${decodeURIComponent(m[1]).split(':')[0]} joined “${body.ssid}” and will remember it. Connect this laptop to “${body.ssid}” to see it again.` };
      }
      if ((m = /^\/api\/robots\/([^/]+)$/.exec(path))) {
        const r = Hub.S.robots.get(decodeURIComponent(m[1]));
        return r ? Object.assign({ ok: true, has_wifi: ['naoqi', 'pepper', 'reachy_wireless'].includes(r.type_id), staff_tools: true }, r) : { ok: false, code: 'UNKNOWN_ROBOT', error: 'There is no such robot.' };
      }
      if ((m = /^\/api\/robots\/([^/]+)\/(connect|disconnect|launch|override|posture|key)$/.exec(path))) {
        const key = decodeURIComponent(m[1]);
        const r = Hub.S.robots.get(key);
        if (m[2] === 'connect') { Hub.handle(Object.assign({}, r, { type: 'robot', state: 'CONNECTING' })); await this.wait(900); Hub.handle(Object.assign({}, r, { type: 'robot', state: 'CONNECTED', detail: 'ready' })); return { ok: true }; }
        if (m[2] === 'disconnect') { Hub.handle(Object.assign({}, r, { type: 'robot', state: 'DETECTED', detail: 'disconnected', system_url: null })); return { ok: true }; }
        if (m[2] === 'launch' || m[2] === 'override') { Hub.handle(Object.assign({}, r, { type: 'robot', launching_since: now() })); await this.wait(3000); Hub.handle(Object.assign({}, r, { type: 'robot', state: 'RUNNING', launching_since: null, system_url: 'http://127.0.0.1:8780/' })); return { ok: true, url: 'http://127.0.0.1:8780/' }; }
        if (m[2] === 'posture') { Hub.handle(Object.assign({}, r, { type: 'robot', posture_pending: body.name })); await this.wait(2000); Hub.handle(Object.assign({}, r, { type: 'robot', posture_pending: null, posture_note: `NAO is ${body.name === 'sit' ? 'sitting' : body.name === 'lie' ? 'lying down' : 'standing'}, motors ${body.name === 'stand' ? 'on' : 'off'} (hottest joint: left knee 54 °C)` })); return { ok: true }; }
        if (m[2] === 'key') {
          const s = data.keys.slots[key][body.slot];
          s.assigned = body.key_id; s.key = data.keys.keys.find(k => k.id === body.key_id) || s.key;
          return Object.assign({ ok: true }, data.keys);
        }
      }
      if (path === '/api/keys' && method === 'POST') {
        const p = Hub.ui.popup;
        if (p && p._demo) return p._demo;
        return { ok: false, code: 'KEY_REFUSED', error: 'That key was refused.' };
      }
      if ((m = /^\/api\/keys\/([^/]+)\/check$/.exec(path))) { await this.wait(700); return Object.assign({ ok: true }, data.keys); }
      if ((m = /^\/api\/keys\/([^/]+)$/.exec(path)) && method === 'DELETE') { data.keys.keys = data.keys.keys.filter(k => k.id !== m[1]); return Object.assign({ ok: true }, data.keys); }
      if (path === '/api/settings' && method === 'PUT') { Object.assign(data.settings, body); return Object.assign({ ok: true }, data.settings); }
      if (path.startsWith('/api/settings/password/')) return Object.assign({ ok: true }, data.settings);
      if ((m = /^\/api\/setup\/([^/]+)\/(\w+)$/.exec(path))) return { ok: true, item: data.setup.find(x => x.id === m[1]) };
      return { ok: true };
    },
  };
  window.HubDemo = Demo;
})();
