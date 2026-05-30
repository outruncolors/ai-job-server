/* Blaboratory — 4×4 room grid, Fill Room dialog, resident detail.
   Uses the shared api() (auto-prepends /v1) and _escHtml(). */
(function () {
  const APP = '/apps/blaboratory';

  // Guided-mode field spec. `list` fields collect comma-separated values;
  // personality.* fields are nested under the `personality` object on submit.
  const GUIDED_FIELDS = [
    { key: 'name',        label: 'Name' },
    { key: 'age',         label: 'Age', type: 'number' },
    { key: 'sex',         label: 'Sex' },
    { key: 'occupation',  label: 'Occupation' },
    { key: 'height',      label: 'Height' },
    { key: 'build',       label: 'Build' },
    { key: 'hair_color',  label: 'Hair color' },
    { key: 'hair_style',  label: 'Hair style' },
    { key: 'eye_color',   label: 'Eye color' },
    { key: 'skin_tone',   label: 'Skin tone' },
    { key: 'distinguishing_features', label: 'Distinguishing features', list: true },
    { key: 'p_traits',      label: 'Personality traits', list: true },
    { key: 'p_quirks',      label: 'Quirks', list: true },
    { key: 'p_speech_style', label: 'Speech style' },
    { key: 'backstory',   label: 'Backstory', textarea: true },
  ];

  const $ = (id) => document.getElementById(id);
  const grid = $('grid');
  let currentRoom = null;
  let currentMode = 'free_text';

  // ── Timeline state ────────────────────────────────────────────────────
  let latestTick = 0;   // newest tick the server has produced
  let playhead = 0;     // tick currently being viewed (manual scrub)
  let following = true; // playhead tracks latest until the user scrubs back

  // ── Grid ──────────────────────────────────────────────────────────────
  async function loadGrid() {
    grid.setAttribute('aria-busy', 'true');
    let data;
    try {
      data = await api(`${APP}/ticks/${playhead}/rooms`);
    } catch (e) {
      grid.innerHTML = `<p class="error">Could not load rooms: ${_escHtml(e.message)}</p>`;
      return;
    } finally {
      grid.setAttribute('aria-busy', 'false');
    }
    grid.innerHTML = data.rooms.map(renderCell).join('');
  }

  function renderCell(room) {
    const n = room.room_id;
    if (room.occupant) {
      const o = room.occupant;
      const word = room.action_word
        ? `<span class="cell-action">${_escHtml(room.action_word)}</span>` : '';
      return `<button class="cell occupied" data-room="${n}" data-rid="${_escHtml(o.id)}">
        <span class="cell-num">#${n}</span>
        <span class="cell-name">${_escHtml(o.name)}</span>
        <span class="cell-occ">${_escHtml(o.occupation)}</span>
        ${word}
      </button>`;
    }
    return `<button class="cell empty" data-room="${n}" data-fill="1">
      <span class="cell-num">#${n}</span>
      <span class="cell-fill">+ Fill Room</span>
    </button>`;
  }

  // ── Timeline scrubber + sim controls ──────────────────────────────────
  function renderTimeline() {
    $('tl-label').textContent =
      `Tick ${playhead}` + (playhead === latestTick ? ' (latest)' : ` / ${latestTick}`);
    $('tl-prev').disabled = playhead <= 0;
    $('tl-next').disabled = playhead >= latestTick;
    $('tl-latest').disabled = playhead === latestTick;
  }

  async function refreshLatest() {
    try {
      const data = await api(`${APP}/ticks/latest`);
      latestTick = data.tick;
      if (following) playhead = latestTick;
    } catch (e) { /* leave prior values on a transient error */ }
  }

  async function setPlayhead(t) {
    playhead = Math.max(0, Math.min(t, latestTick));
    following = playhead === latestTick;
    renderTimeline();
    await loadGrid();
  }

  async function fireTick() {
    const status = $('tl-status');
    status.textContent = 'Firing tick…';
    try {
      await api(`${APP}/ticks/fire`, 'POST');
      status.textContent = 'Tick queued (runs in the background).';
    } catch (e) {
      status.textContent = `Could not fire tick: ${e.message}`;
    }
  }

  async function toggleClock() {
    const btn = $('tl-clock');
    try {
      const cur = await api(`${APP}/clock`);
      const next = cur.running ? 'stop' : 'start';
      const res = await api(`${APP}/clock/${next}`, 'POST');
      reflectClock(res.running);
    } catch (e) {
      $('tl-status').textContent = `Clock error: ${e.message}`;
    }
  }

  function reflectClock(running) {
    const btn = $('tl-clock');
    btn.textContent = running ? '⏸ Stop clock' : '▶ Start clock';
    btn.classList.toggle('running', running);
  }

  // Poll for newly-finished ticks; live-append when following the latest.
  async function poll() {
    const prevLatest = latestTick;
    await refreshLatest();
    if (latestTick !== prevLatest) {
      renderTimeline();
      if (following) await loadGrid();
    }
  }

  grid.addEventListener('click', (e) => {
    const cell = e.target.closest('.cell');
    if (!cell) return;
    if (cell.dataset.fill) openFill(Number(cell.dataset.room));
    else if (cell.dataset.rid) openDetail(cell.dataset.rid);
  });

  // ── Fill Room dialog ─────────────────────────────────────────────────
  function buildGuidedForm() {
    $('guided-fields').innerHTML = GUIDED_FIELDS.map((f) => {
      const ph = f.list ? 'comma, separated' : '';
      const ctrl = f.textarea
        ? `<textarea id="gf-${f.key}" rows="3"></textarea>`
        : `<input id="gf-${f.key}" type="${f.type || 'text'}" placeholder="${ph}">`;
      return `<div class="field${f.textarea ? ' wide' : ''}">
        <label for="gf-${f.key}">${_escHtml(f.label)}</label>${ctrl}
      </div>`;
    }).join('');
  }

  function setMode(mode) {
    currentMode = mode;
    document.querySelectorAll('.mode-btn').forEach((b) =>
      b.classList.toggle('active', b.dataset.mode === mode));
    $('mode-free_text').hidden = mode !== 'free_text';
    $('mode-guided').hidden = mode !== 'guided';
  }

  function openFill(room) {
    currentRoom = room;
    $('fill-title').textContent = `Fill Room #${room}`;
    $('fill-msg').textContent = '';
    $('free-text').value = '';
    GUIDED_FIELDS.forEach((f) => { const el = $(`gf-${f.key}`); if (el) el.value = ''; });
    setMode('free_text');
    $('fill-dialog').showModal();
  }

  function collectList(key) {
    return ($(`gf-${key}`).value || '')
      .split(',').map((s) => s.trim()).filter(Boolean);
  }

  function collectGuidedFields() {
    const fields = {};
    const personality = {};
    GUIDED_FIELDS.forEach((f) => {
      const el = $(`gf-${f.key}`);
      if (!el) return;
      if (f.key === 'p_traits') { const v = collectList('p_traits'); if (v.length) personality.traits = v; return; }
      if (f.key === 'p_quirks') { const v = collectList('p_quirks'); if (v.length) personality.quirks = v; return; }
      if (f.key === 'p_speech_style') { if (el.value.trim()) personality.speech_style = el.value.trim(); return; }
      if (f.list) { const v = collectList(f.key); if (v.length) fields[f.key] = v; return; }
      const val = el.value.trim();
      if (!val) return;
      fields[f.key] = (f.type === 'number') ? Number(val) : val;
    });
    if (Object.keys(personality).length) fields.personality = personality;
    return fields;
  }

  async function submitFill() {
    const msg = $('fill-msg');
    let body;
    if (currentMode === 'free_text') {
      const text = $('free-text').value.trim();
      if (!text) { msg.textContent = 'Please describe the resident.'; return; }
      body = { mode: 'free_text', free_text: text };
    } else {
      body = { mode: 'guided', fields: collectGuidedFields() };
    }

    const submit = $('fill-submit');
    submit.disabled = true;
    msg.className = 'msg busy';
    msg.textContent = 'Generating resident…';
    try {
      await api(`${APP}/rooms/${currentRoom}/residents`, 'POST', body);
      $('fill-dialog').close();
      await loadGrid();
    } catch (e) {
      msg.className = 'msg error';
      msg.textContent = `Generation failed: ${e.message}`;
    } finally {
      submit.disabled = false;
    }
  }

  // ── Detail dialog ────────────────────────────────────────────────────
  function section(title, rows) {
    const body = rows.filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && !v.length))
      .map(([k, v]) => `<div class="d-row"><span class="d-key">${_escHtml(k)}</span>
        <span class="d-val">${_escHtml(Array.isArray(v) ? v.join(', ') : v)}</span></div>`).join('');
    if (!body) return '';
    return `<section class="d-sec"><h4>${_escHtml(title)}</h4>${body}</section>`;
  }

  async function openDetail(rid) {
    const dlg = $('detail-dialog');
    $('detail-name').textContent = 'Resident';
    $('detail-body').innerHTML = '<p class="hint">Loading…</p>';
    dlg.showModal();
    let r;
    try {
      r = await api(`${APP}/residents/${rid}`);
    } catch (e) {
      $('detail-body').innerHTML = `<p class="error">${_escHtml(e.message)}</p>`;
      return;
    }
    $('detail-name').textContent = r.name;
    const p = r.personality || {};
    $('detail-body').innerHTML = [
      section('Identity', [['Age', r.age], ['Sex', r.sex], ['Occupation', r.occupation]]),
      section('Appearance', [
        ['Height', r.height], ['Build', r.build],
        ['Hair', [r.hair_color, r.hair_style].filter(Boolean).join(', ')],
        ['Eyes', r.eye_color], ['Skin', r.skin_tone],
        ['Distinguishing', r.distinguishing_features],
      ]),
      section('Personality', [
        ['Traits', p.traits], ['Quirks', p.quirks], ['Speech', p.speech_style],
      ]),
      r.backstory ? `<section class="d-sec"><h4>Backstory</h4>
        <p class="d-prose">${_escHtml(r.backstory)}</p></section>` : '',
      `<section class="d-sec" id="d-events"><h4>Event log <span class="d-sub">(through tick ${playhead})</span></h4>
        <div class="d-log">Loading…</div></section>`,
      `<details class="d-sec"><summary>Active context / knowledge</summary>
        <pre class="d-context" id="d-context">Loading…</pre></details>`,
    ].join('');

    loadActivity(rid, r.room_id);
  }

  // Event log (newest-first, truncated at playhead) + the call lines for this
  // resident's room + the active-context inspection panel.
  async function loadActivity(rid, roomId) {
    try {
      const [ev, ctx] = await Promise.all([
        api(`${APP}/residents/${rid}/events?until_tick=${playhead}`),
        api(`${APP}/residents/${rid}/context?tick=${playhead}`),
      ]);
      let utter = { utterances: [] };
      if (roomId != null) {
        utter = await api(`${APP}/rooms/${roomId}/utterances?until_tick=${playhead}`);
      }
      renderLog($('d-events').querySelector('.d-log'), ev.events, utter.utterances);
      const ctxEl = $('d-context');
      if (ctxEl) ctxEl.textContent = ctx.context || '(empty)';
    } catch (e) {
      const log = $('d-events') && $('d-events').querySelector('.d-log');
      if (log) log.innerHTML = `<p class="error">${_escHtml(e.message)}</p>`;
    }
  }

  function renderLog(el, events, utterances) {
    // Merge events + utterances into one newest-first list keyed by tick.
    const rows = [];
    (events || []).forEach((e) => rows.push({
      tick: e.tick, id: `e${e.id}`,
      text: `${_actionVerb(e.action || e.kind)}${_summaryOf(e)}`,
    }));
    (utterances || []).forEach((u) => rows.push({
      tick: u.tick, id: `u${u.id}`, speaker: u.speaker_resident_id,
      text: `📞 “${u.body}”`,
    }));
    rows.sort((a, b) => (b.tick - a.tick) || b.id.localeCompare(a.id));
    if (!rows.length) { el.innerHTML = '<p class="hint">No activity yet.</p>'; return; }
    el.innerHTML = rows.map((r) =>
      `<div class="log-row"><span class="log-tick">#${r.tick}</span>
        <span class="log-text">${_escHtml(r.text)}</span></div>`).join('');
  }

  function _actionVerb(a) {
    const map = {
      use_computer: 'Used the computer', use_televisor: 'Watched the televisor',
      use_speakerphone: 'Used the speakerphone', sleep: 'Slept', idle: 'Idled',
    };
    return map[a] || (a || 'Acted');
  }

  function _summaryOf(e) {
    const s = e.payload && e.payload.summary;
    return s ? ` — ${s}` : '';
  }

  // ── Tabs (hash-routed) ─────────────────────────────────────────────────
  const TABS = ['rooms', 'config'];

  function switchTab(name) {
    const tab = TABS.includes(name) ? name : 'rooms';
    document.querySelectorAll('.tab-btn').forEach((b) =>
      b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach((p) => {
      p.hidden = p.id !== `tab-${tab}`;
    });
    if (tab === 'config') loadSettings();
  }

  function syncTab() {
    switchTab(location.hash.replace('#', '') || 'rooms');
  }

  // ── Config form (hot-applied sim settings) ─────────────────────────────
  async function loadSettings() {
    let s;
    try { s = await api(`${APP}/settings`); }
    catch (e) { return; }  // leave inputs blank on a transient error
    Object.entries(s).forEach(([k, v]) => {
      const el = $(`cfg-${k}`);
      if (el) el.value = v;
    });
  }

  function _settingsError(e) {
    // api() throws Error(message); for our 422 it's JSON {field, message}.
    try {
      const d = JSON.parse(e.message);
      if (d && d.message) return d.message;
    } catch (_) { /* not our structured error */ }
    return e.message || 'Save failed.';
  }

  async function saveSection(form) {
    const fields = (form.dataset.fields || '').split(',').filter(Boolean);
    const msg = form.querySelector('.cfg-msg');
    const btn = form.querySelector('.cfg-save');
    const body = {};
    fields.forEach((f) => {
      const el = $(`cfg-${f}`);
      if (el && el.value !== '') body[f] = Number(el.value);
    });
    msg.className = 'cfg-msg busy';
    msg.textContent = 'Saving…';
    btn.disabled = true;
    try {
      const updated = await api(`${APP}/settings`, 'PUT', body);
      Object.entries(updated).forEach(([k, v]) => {
        const el = $(`cfg-${k}`);
        if (el) el.value = v;
      });
      msg.className = 'cfg-msg ok';
      msg.textContent = 'Saved.';
    } catch (e) {
      msg.className = 'cfg-msg error';
      msg.textContent = _settingsError(e);
    } finally {
      btn.disabled = false;
    }
  }

  // ── Wiring ───────────────────────────────────────────────────────────
  buildGuidedForm();
  document.querySelectorAll('.mode-btn').forEach((b) =>
    b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('fill-submit').addEventListener('click', submitFill);
  $('fill-cancel').addEventListener('click', () => $('fill-dialog').close());
  $('fill-close').addEventListener('click', () => $('fill-dialog').close());
  $('detail-close').addEventListener('click', () => $('detail-dialog').close());

  // Timeline + sim controls.
  $('tl-prev').addEventListener('click', () => setPlayhead(playhead - 1));
  $('tl-next').addEventListener('click', () => setPlayhead(playhead + 1));
  $('tl-latest').addEventListener('click', () => setPlayhead(latestTick));
  $('tl-fire').addEventListener('click', fireTick);
  $('tl-clock').addEventListener('click', toggleClock);

  // Tabs: clicking sets the hash; hashchange drives the actual switch.
  document.querySelectorAll('.tab-btn').forEach((b) =>
    b.addEventListener('click', () => { location.hash = b.dataset.tab; }));
  window.addEventListener('hashchange', syncTab);
  // Per-section save (forms submit on button click or Enter).
  document.querySelectorAll('.cfg-sec[data-fields]').forEach((form) =>
    form.addEventListener('submit', (e) => { e.preventDefault(); saveSection(form); }));

  (async function init() {
    syncTab();
    await refreshLatest();
    renderTimeline();
    await loadGrid();
    try { reflectClock((await api(`${APP}/clock`)).running); } catch (e) { /* ignore */ }
    setInterval(poll, 5000);
  })();
})();
