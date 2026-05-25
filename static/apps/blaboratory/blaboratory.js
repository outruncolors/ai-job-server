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

  // ── Grid ──────────────────────────────────────────────────────────────
  async function loadGrid() {
    grid.setAttribute('aria-busy', 'true');
    let data;
    try {
      data = await api(`${APP}/rooms`);
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
      return `<button class="cell occupied" data-room="${n}" data-rid="${_escHtml(o.id)}">
        <span class="cell-num">#${n}</span>
        <span class="cell-name">${_escHtml(o.name)}</span>
        <span class="cell-occ">${_escHtml(o.occupation)}</span>
      </button>`;
    }
    return `<button class="cell empty" data-room="${n}" data-fill="1">
      <span class="cell-num">#${n}</span>
      <span class="cell-fill">+ Fill Room</span>
    </button>`;
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
    ].join('');
  }

  // ── Wiring ───────────────────────────────────────────────────────────
  buildGuidedForm();
  document.querySelectorAll('.mode-btn').forEach((b) =>
    b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('fill-submit').addEventListener('click', submitFill);
  $('fill-cancel').addEventListener('click', () => $('fill-dialog').close());
  $('fill-close').addEventListener('click', () => $('fill-dialog').close());
  $('detail-close').addEventListener('click', () => $('detail-dialog').close());

  loadGrid();
})();
