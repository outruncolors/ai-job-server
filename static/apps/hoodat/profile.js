/* Hoodat character profile: tabbed sections, per-field generate + edit-prompt
   (via the shared FieldControls hover affordance + Prompt Pal), avatar
   replace (generate/upload), voice, and targeted exports. */
(function () {
  const $ = (id) => document.getElementById(id);
  const APP = '/apps/hoodat';

  // Field layout — mirrors app/apps/hoodat/models.py FIELD_SPECS.
  const FIELDS = {
    identity: [
      ['name', 'Name', 'scalar'], ['summary', 'Summary', 'scalar'],
      ['tagline', 'Tagline', 'scalar'], ['age', 'Age', 'int'],
      ['sex', 'Sex', 'scalar'], ['occupation', 'Occupation', 'scalar'],
    ],
    appearance: [
      ['height', 'Height', 'scalar'], ['build', 'Build', 'scalar'],
      ['hair', 'Hair', 'scalar'], ['eyes', 'Eyes', 'scalar'],
      ['skin', 'Skin tone', 'scalar'],
      ['distinguishing_features', 'Distinguishing features', 'list'],
      ['primary_outfit', 'Primary outfit', 'scalar'],
    ],
    personality: [
      ['traits', 'Traits', 'list'], ['quirks', 'Quirks', 'list'],
      ['values', 'Values', 'list'], ['fears', 'Fears', 'list'],
    ],
    background: [
      ['backstory', 'Backstory', 'long'], ['origin', 'Origin', 'scalar'],
      ['relationships', 'Relationships', 'list'],
      ['affiliations', 'Affiliations', 'list'], ['skills', 'Skills', 'list'],
    ],
    speaking_style: [['description', 'How they speak', 'long']],
  };

  let charId = null;
  let character = null;
  let promptMap = {};       // "field.section.field" -> prompt entry id
  let caps = { image: true, voice: true };

  // ---- value helpers ----
  function getValue(section, field) {
    if (section === 'identity') return character[field];
    return (character[section] || {})[field];
  }
  function displayValue(kind, value) {
    if (kind === 'list') return (value || []).join('\n');
    if (value === null || value === undefined) return '';
    return String(value);
  }
  function parseValue(kind, raw) {
    if (kind === 'list') return raw.split('\n').map((s) => s.trim()).filter(Boolean);
    if (kind === 'int') { const n = parseInt(raw, 10); return Number.isNaN(n) ? 0 : n; }
    return raw;
  }
  function patchFor(section, field, value) {
    return section === 'identity' ? { [field]: value } : { [section]: { [field]: value } };
  }
  function setLocal(section, field, value) {
    if (section === 'identity') character[field] = value;
    else { character[section] = character[section] || {}; character[section][field] = value; }
  }

  // ---- section cards (shared visual wrapper for every tab) ----
  const SECTION_TITLES = {
    identity: 'Identity', appearance: 'Appearance', personality: 'Personality',
    background: 'Background', speaking_style: 'Speaking Style',
  };
  function sectionCard(title, bodyHtml) {
    return `<section class="hd-section">
      <div class="hd-section-head"><h3 class="hd-section-title">${_escHtml(title)}</h3></div>
      <div class="hd-section-body">${bodyHtml}</div>
    </section>`;
  }

  // ---- field rendering ----
  const _ROWS = { scalar: 3, list: 5, long: 8 };
  function fieldInputHtml(kind, id) {
    if (kind === 'int') return `<input type="number" id="${id}" min="0">`;
    // every text field is a common, roomy full-width textarea
    return `<textarea id="${id}" rows="${_ROWS[kind] || 3}"></textarea>`;
  }

  function renderSection(section, container) {
    const fieldsHtml = FIELDS[section].map(([field, label, kind]) => {
      const inId = `f-${section}-${field}`;
      const hint = kind === 'list' ? '<span class="hd-field-hint">one per line</span>' : '';
      return `<div class="hd-field" data-section="${section}" data-field="${field}" data-kind="${kind}">
        <label for="${inId}">${_escHtml(label)} ${hint}</label>
        ${fieldInputHtml(kind, inId)}
      </div>`;
    }).join('');
    container.innerHTML = sectionCard(SECTION_TITLES[section] || section, fieldsHtml);

    container.querySelectorAll('.hd-field').forEach((slot) => {
      const { section: sec, field, kind } = slot.dataset;
      const input = slot.querySelector('input, textarea');
      input.value = displayValue(kind, getValue(sec, field));
      input.addEventListener('change', () => saveField(sec, field, kind, input));
      FieldControls.attach(slot, {
        kind: 'field',
        context: () => ({ section: sec, field, kind, input }),
        controls: [
          { id: 'gen', label: '✨', title: 'Generate this field', onClick: (ctx) => generateField(ctx) },
          { id: 'prompt', label: '✏️', title: 'Edit this field\'s prompt', onClick: (ctx) => editPrompt(ctx) },
        ],
      });
    });
  }

  async function saveField(section, field, kind, input) {
    const value = parseValue(kind, input.value);
    try {
      await api(`${APP}/characters/${charId}`, 'PUT', patchFor(section, field, value));
      setLocal(section, field, value);
      if (section === 'identity' && (field === 'name' || field === 'tagline')) renderHeader();
    } catch (err) {
      console.error('save failed', err);
    }
  }

  async function generateField(ctx) {
    const { section, field, kind, input } = ctx;
    const btn = input.closest('.hd-field').querySelector('.fc-btn[data-id="gen"]');
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const res = await api(`${APP}/characters/${charId}/fields/${section}/${field}/generate`, 'POST');
      input.value = displayValue(kind, res.value);
      setLocal(section, field, res.value);
      if (res.prompt_id) promptMap[`field.${section}.${field}`] = res.prompt_id;
      if (section === 'identity' && (field === 'name' || field === 'tagline')) renderHeader();
    } catch (err) {
      console.error('generate failed', err);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨'; }
    }
  }

  function editPrompt(ctx) {
    const key = `field.${ctx.section}.${ctx.field}`;
    const id = promptMap[key];
    const url = id
      ? `/prompt-pal/?app=hoodat&highlight=${encodeURIComponent(id)}`
      : `/prompt-pal/?app=hoodat`;
    window.open(url, '_blank');
  }

  // ---- dialogue examples ----
  // A growing list of sample lines. The frontend owns the list: generation
  // returns a candidate string and we PUT the full edited list back (the
  // nested-section merge replaces `dialogue_examples` wholesale).
  function dialogueList() { return ((character.speaking_style || {}).dialogue_examples) || []; }
  function dlgTextareas() { return document.querySelectorAll('#hd-dialogue .hd-dlg-row textarea'); }
  function collectDialogueRaw() { return Array.from(dlgTextareas()).map((t) => t.value); }
  function collectDialogue() { return collectDialogueRaw().map((s) => s.trim()).filter(Boolean); }

  function persistDialogue(list) {
    setLocal('speaking_style', 'dialogue_examples', list);
    return api(`${APP}/characters/${charId}`, 'PUT', { speaking_style: { dialogue_examples: list } });
  }

  function focusLastDialogue() {
    const tas = dlgTextareas();
    if (tas.length) tas[tas.length - 1].focus();
  }

  function openDialoguePrompt() {
    const id = promptMap['dialogue.example'];
    const url = id
      ? `/prompt-pal/?app=hoodat&highlight=${encodeURIComponent(id)}`
      : `/prompt-pal/?app=hoodat`;
    window.open(url, '_blank');
  }

  async function generateDialogue(examples) {
    const res = await api(`${APP}/characters/${charId}/dialogue-examples/generate`, 'POST', { examples });
    if (res.prompt_id) promptMap['dialogue.example'] = res.prompt_id;
    return res.value;
  }

  async function addDialogue() {
    const list = collectDialogue();
    if (list.length === 0) {
      // Nothing to learn from yet — just give the user an empty row to type in.
      renderDialogue(collectDialogueRaw().concat(['']));
      focusLastDialogue();
      return;
    }
    const btn = $('hd-dlg-add');
    if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
    try {
      const value = await generateDialogue(list);
      const next = list.concat([value]);
      await persistDialogue(next);
      renderDialogue(next);
      focusLastDialogue();
    } catch (err) {
      console.error('dialogue add failed', err);
      if (btn) { btn.disabled = false; btn.textContent = '+ Add dialogue example'; }
    }
  }

  async function regenDialogue(ctx, meta) {
    const btn = meta && meta.button;
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    const rows = collectDialogueRaw();
    const others = rows.filter((_, i) => i !== ctx.index).map((s) => s.trim()).filter(Boolean);
    try {
      const value = await generateDialogue(others);
      rows[ctx.index] = value;
      const cleaned = rows.map((s) => s.trim()).filter(Boolean);
      await persistDialogue(cleaned);
      renderDialogue(cleaned);
    } catch (err) {
      console.error('dialogue regenerate failed', err);
      if (btn) { btn.disabled = false; btn.textContent = '✨'; }
    }
  }

  async function removeDialogue(index) {
    const rows = collectDialogueRaw();
    rows.splice(index, 1);
    const cleaned = rows.map((s) => s.trim()).filter(Boolean);
    try {
      await persistDialogue(cleaned);
      renderDialogue(cleaned);
    } catch (err) {
      console.error('dialogue remove failed', err);
    }
  }

  function renderDialogue(list) {
    if (list === undefined) list = dialogueList();
    const container = $('hd-dialogue');
    const rowsHtml = list.map((text, i) =>
      `<div class="hd-dlg-row" data-index="${i}">
        <textarea rows="3" placeholder="A line this character might say…">${_escHtml(text)}</textarea>
      </div>`).join('');
    const empty = list.length ? '' : '<div class="hd-dlg-empty">No dialogue examples yet.</div>';
    const body = `${empty}<div class="hd-dlg-rows">${rowsHtml}</div>
      <div class="hd-dlg-actions">
        <button type="button" id="hd-dlg-add">+ Add dialogue example</button>
      </div>`;
    container.innerHTML = sectionCard('Dialogue examples', body);

    $('hd-dlg-add').addEventListener('click', addDialogue);
    container.querySelectorAll('.hd-dlg-row').forEach((rowEl) => {
      const textarea = rowEl.querySelector('textarea');
      textarea.addEventListener('change', () => persistDialogue(collectDialogue()));
      FieldControls.attach(rowEl, {
        kind: 'field',
        context: () => ({ index: Number(rowEl.dataset.index), input: textarea }),
        controls: [
          { id: 'gen', label: '✨', title: 'Regenerate this example', onClick: regenDialogue },
          { id: 'prompt', label: '✏️', title: 'Edit the dialogue prompt', onClick: openDialoguePrompt },
          { id: 'rm', label: '✗', title: 'Remove', onClick: (ctx) => removeDialogue(ctx.index) },
        ],
      });
    });
  }

  // ---- header + avatar ----
  function renderHeader() {
    $('hd-name').textContent = character.name || 'Unnamed';
    $('hd-tagline').textContent = character.tagline || '';
    renderAvatar();
  }

  // Render the placeholder initial into a dedicated child span — never via
  // el.textContent, which would wipe the FieldControls `.fc-cluster` child.
  function setInitial(text) {
    const el = $('hd-avatar');
    let span = el.querySelector('.hd-avatar-initial');
    if (!text) { if (span) span.remove(); return; }
    if (!span) {
      span = document.createElement('span');
      span.className = 'hd-avatar-initial';
      el.insertBefore(span, el.firstChild);
    }
    span.textContent = text;
  }

  function renderAvatar() {
    const el = $('hd-avatar');
    if (character.avatar_path) {
      el.style.backgroundImage = `url("${character.avatar_path}?v=${encodeURIComponent(character.updated_at || Date.now())}")`;
      el.classList.remove('hd-avatar-ph');
      setInitial('');
    } else {
      el.style.backgroundImage = '';
      el.classList.add('hd-avatar-ph');
      setInitial((character.name || '?').trim().charAt(0).toUpperCase() || '?');
    }
  }

  function openAvatarDialog() {
    $('hd-avatar-msg').textContent = '';
    const gen = $('hd-avatar-generate');
    gen.disabled = !caps.image;
    gen.title = caps.image ? '' : 'Image generation not available on this node';
    $('hd-avatar-dialog').showModal();
  }

  async function generateAvatar() {
    const msg = $('hd-avatar-msg');
    msg.textContent = 'Generating avatar…';
    try {
      const res = await api(`${APP}/characters/${charId}/avatar/generate`, 'POST');
      character.avatar_path = res.avatar_url;
      character.updated_at = String(Date.now());
      renderAvatar();
      $('hd-avatar-dialog').close();
    } catch (err) {
      msg.textContent = 'Generate failed: ' + err.message;
    }
  }

  async function uploadAvatar(file) {
    const msg = $('hd-avatar-msg');
    msg.textContent = 'Uploading…';
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch(`/v1${APP}/characters/${charId}/avatar/upload`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const res = await r.json();
      character.avatar_path = res.avatar_url;
      character.updated_at = String(Date.now());
      renderAvatar();
      $('hd-avatar-dialog').close();
    } catch (err) {
      msg.textContent = 'Upload failed: ' + err.message;
    }
  }

  // ---- voice ----
  async function loadVoice() {
    let presets = [];
    try { const r = await fetch('/v1/voice-presets'); presets = r.ok ? await r.json() : []; }
    catch (e) { presets = []; }
    const sel = $('hd-voice-select');
    const current = (character.speaking_style || {}).voice_preset_id || '';
    sel.innerHTML = '<option value="">(none)</option>' +
      presets.map((p) => `<option value="${_escHtml(p.id)}">${_escHtml(p.name || p.id)}</option>`).join('');
    sel.value = current;
    sel.addEventListener('change', async () => {
      await api(`${APP}/characters/${charId}`, 'PUT', { speaking_style: { voice_preset_id: sel.value || null } });
      setLocal('speaking_style', 'voice_preset_id', sel.value || null);
    });
    const synth = $('hd-voice-synth');
    synth.disabled = !caps.voice;
    synth.title = caps.voice ? '' : 'Voice synthesis not available on this node';
  }

  async function synthSample() {
    const text = $('hd-voice-text').value.trim();
    const msg = $('hd-voice-msg');
    if (!text) { msg.textContent = 'Enter a line first.'; return; }
    const presetId = $('hd-voice-select').value;
    msg.textContent = 'Synthesizing…';
    try {
      const job = await api('/jobs/voice', 'POST', { text, voice_preset_id: presetId || null });
      const jobId = job.job_id;
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        const st = await api(`/jobs/${jobId}`);
        if (st.status === 'done') {
          const audio = $('hd-voice-audio');
          audio.src = `/v1/jobs/${jobId}/files/output.wav`;
          audio.hidden = false;
          audio.play().catch(() => {});
          msg.textContent = '';
          return;
        }
        if (st.status === 'error') { msg.textContent = 'Synthesis failed.'; return; }
      }
      msg.textContent = 'Timed out.';
    } catch (err) {
      msg.textContent = 'Synthesis failed: ' + err.message;
    }
  }

  // ---- exports ----
  let detailLevels = ['brief', 'standard', 'detailed'];

  async function loadExports() {
    let data;
    try { data = await api(`${APP}/characters/${charId}/exports`); }
    catch (err) { $('hd-exports-list').innerHTML = `<div class="hd-empty">${_escHtml(err.message)}</div>`; return; }
    detailLevels = data.detail_levels || detailLevels;
    const exps = data.exports || [];
    const list = $('hd-exports-list');
    if (!exps.length) {
      list.innerHTML = '<div class="hd-empty">No export prompts yet. Create one to render this character into another format.</div>';
      return;
    }
    list.innerHTML = exps.map((e) => {
      const opts = detailLevels.map((d) => `<option value="${d}">${d}</option>`).join('');
      return `<div class="hd-export" data-key="${_escHtml(e.key)}" data-id="${_escHtml(e.id)}">
        <div class="hd-export-head">
          <span class="hd-export-title">${_escHtml(e.title || e.key)}</span>
          <select class="hd-export-detail">${opts}</select>
          <button type="button" class="hd-export-run">Run</button>
          <button type="button" class="hd-export-edit secondary">✏️ Prompt</button>
        </div>
        <pre class="hd-export-out" hidden></pre>
      </div>`;
    }).join('');
    list.querySelectorAll('.hd-export').forEach((row) => {
      row.querySelector('.hd-export-run').addEventListener('click', () => runExport(row));
      row.querySelector('.hd-export-edit').addEventListener('click', () =>
        window.open(`/prompt-pal/?app=hoodat&highlight=${encodeURIComponent(row.dataset.id)}`, '_blank'));
    });
  }

  async function runExport(row) {
    const key = row.dataset.key;
    const detail = row.querySelector('.hd-export-detail').value;
    const out = row.querySelector('.hd-export-out');
    const btn = row.querySelector('.hd-export-run');
    out.hidden = false; out.textContent = 'Running…'; btn.disabled = true;
    try {
      const res = await api(`${APP}/characters/${charId}/exports/${encodeURIComponent(key)}/run`, 'POST', { detail });
      out.textContent = res.text || '(empty)';
    } catch (err) {
      out.textContent = 'Run failed: ' + err.message;
    } finally {
      btn.disabled = false;
    }
  }

  function slugify(s) {
    return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'export';
  }

  async function createExport() {
    const name = $('hd-export-name').value.trim();
    const prompt = $('hd-export-prompt').value;
    const msg = $('hd-export-msg');
    if (!name) { msg.textContent = 'Name is required.'; return; }
    try {
      await api('/prompt-pal/entries', 'POST', {
        app: 'hoodat', key: `export.${slugify(name)}`, title: name, prompt, tags: ['export'],
      });
      $('hd-export-dialog').close();
      await loadExports();
    } catch (err) {
      msg.textContent = 'Create failed: ' + err.message;
    }
  }

  // ---- tabs ----
  function switchTab(tab) {
    document.querySelectorAll('#hd-tabs .tab-btn').forEach((b) =>
      b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach((p) =>
      p.hidden = p.id !== `tab-${tab}`);
    if (tab === 'exports') loadExports();
    history.replaceState(null, '', `?id=${encodeURIComponent(charId)}&tab=${tab}`);
  }

  // ---- init ----
  async function loadCaps() {
    try {
      const data = await api('/server/capabilities');
      // Endpoint shape: { local: [...], peers: [...] }. Avatar-generate and the
      // voice-job route both gate on LOCAL capability, so only local counts here.
      const local = Array.isArray(data) ? data : (data.local || data.capabilities || []);
      caps.image = local.includes('image');
      caps.voice = local.includes('voice');
    } catch (e) { /* default to enabled */ }
  }

  async function loadPromptMap() {
    try {
      const data = await api('/prompt-pal/entries?app=hoodat');
      (data.entries || []).forEach((e) => { promptMap[e.key] = e.id; });
    } catch (e) { /* edit-prompt links fall back to the list view */ }
  }

  function wire() {
    document.querySelectorAll('#hd-tabs .tab-btn').forEach((b) =>
      b.addEventListener('click', () => switchTab(b.dataset.tab)));
    FieldControls.attach($('hd-avatar'), {
      kind: 'avatar',
      controls: [{ id: 'replace', label: 'Replace', onClick: openAvatarDialog }],
    });
    $('hd-avatar-close').addEventListener('click', () => $('hd-avatar-dialog').close());
    $('hd-avatar-generate').addEventListener('click', generateAvatar);
    $('hd-avatar-file').addEventListener('change', (e) => {
      if (e.target.files[0]) uploadAvatar(e.target.files[0]);
    });
    $('hd-voice-synth').addEventListener('click', synthSample);
    $('hd-export-new').addEventListener('click', () => {
      $('hd-export-name').value = ''; $('hd-export-prompt').value = '';
      $('hd-export-msg').textContent = ''; $('hd-export-dialog').showModal();
    });
    $('hd-export-close').addEventListener('click', () => $('hd-export-dialog').close());
    $('hd-export-cancel').addEventListener('click', () => $('hd-export-dialog').close());
    $('hd-export-save').addEventListener('click', createExport);
  }

  async function init() {
    const qs = new URLSearchParams(location.search);
    charId = qs.get('id');
    if (!charId) { document.body.innerHTML = '<p style="padding:2rem">No character id.</p>'; return; }
    wire();
    await Promise.all([loadCaps(), loadPromptMap()]);
    try {
      character = await api(`${APP}/characters/${charId}`);
    } catch (err) {
      $('hd-name').textContent = 'Character not found';
      return;
    }
    renderHeader();
    renderSection('identity', $('tab-identity'));
    renderSection('appearance', $('tab-appearance'));
    renderSection('personality', $('tab-personality'));
    renderSection('background', $('tab-background'));
    renderSection('speaking_style', $('speaking-fields'));
    renderDialogue();
    await loadVoice();
    switchTab(qs.get('tab') || 'identity');
  }

  init();
})();
