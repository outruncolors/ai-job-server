/* Hoodat character profile: tabbed sections, per-field generate + edit-prompt
   (via the shared FieldControls hover affordance + Prompt Pal), avatar
   replace (generate/upload), voice, dialogue/experiences/outfit lists, and
   targeted exports. */
(function () {
  const $ = (id) => document.getElementById(id);
  const APP = '/apps/hoodat';

  const SEX_OPTIONS = ['Male', 'Female'];
  const OUTFIT_SLOTS = ['top', 'bottoms', 'underwear', 'socks_shoes', 'accessories'];
  const SLOT_LABELS = {
    top: 'Top', bottoms: 'Bottoms', underwear: 'Underwear',
    socks_shoes: 'Socks & shoes', accessories: 'Accessories',
  };

  // Identity/personality/background/speaking_style field layout — mirrors
  // app/apps/hoodat/models.py FIELD_SPECS. Appearance is handled separately
  // (renderAppearance) because of its sub-sections + outfit list.
  const FIELDS = {
    identity: [
      ['name', 'Name', 'scalar'], ['summary', 'Summary', 'scalar'],
      ['tagline', 'Tagline', 'scalar'], ['age', 'Age', 'int'],
      ['sex', 'Sex', 'radio'], ['occupation', 'Occupation', 'scalar'],
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

  // Appearance sub-sections (all live on the `appearance` block). Mirrors the
  // appearance entries in models.FIELD_SPECS — keep both in sync.
  const APPEARANCE_BASICS = [
    ['height', 'Height', 'feet-inches'], ['build', 'Build', 'scalar'],
    ['skin', 'Skin tone', 'scalar'],
    ['hair_color', 'Hair color', 'scalar'], ['hair_details', 'Hair details', 'scalar'],
    ['eye_color', 'Eye color', 'scalar'], ['eye_details', 'Eye details', 'scalar'],
    ['distinguishing_features', 'Distinguishing features', 'list'],
  ];
  const NUDE_SHARED = [
    ['body_hair', 'Body hair', 'scalar'], ['pubic_hair', 'Pubic hair', 'scalar'],
    ['buttocks', 'Buttocks', 'scalar'], ['lips', 'Lips', 'scalar'],
    ['hands', 'Hands', 'scalar'], ['feet', 'Feet', 'scalar'],
  ];
  const NUDE_MALE = [['penis', 'Penis', 'scalar'], ['testicles', 'Testicles', 'scalar']];
  const NUDE_FEMALE = [['breasts', 'Breasts', 'scalar'], ['vulva', 'Vulva', 'scalar']];

  let charId = null;
  let character = null;
  let promptMap = {};       // prompt key -> prompt entry id
  let caps = { image: true, voice: true };

  // ---- value helpers ----
  function getValue(section, field) {
    if (section === 'identity') return character[field];
    return (character[section] || {})[field];
  }
  function patchFor(section, field, value) {
    return section === 'identity' ? { [field]: value } : { [section]: { [field]: value } };
  }
  function setLocal(section, field, value) {
    if (section === 'identity') character[field] = value;
    else { character[section] = character[section] || {}; character[section][field] = value; }
  }

  // ---- height (stored as a canonical `F'I"` string) ----
  function parseHeight(str) {
    str = String(str || '');
    let m = str.match(/(\d+)\s*(?:'|’|ft|feet)\s*(\d+)/i);   // 5'10", 5ft 10, 5 feet 10
    if (m) return { feet: m[1], inches: m[2] };
    m = str.match(/(\d+)\s*(?:'|’|ft|feet)/i);                // just feet
    if (m) return { feet: m[1], inches: '0' };
    m = str.match(/(\d+)/);                                   // bare number -> feet
    if (m) return { feet: m[1], inches: '0' };
    return { feet: '', inches: '' };
  }
  function formatHeight(ft, inch) {
    const f = parseInt(ft, 10); const i = parseInt(inch, 10);
    if (Number.isNaN(f) && Number.isNaN(i)) return '';
    return `${Number.isNaN(f) ? 0 : f}'${Number.isNaN(i) ? 0 : i}"`;
  }

  // ---- control registry: kind -> {render, set, get} ----
  // `set(slot, storedValue)` populates the control; `get(slot)` returns the
  // typed value to persist; `render(id)` returns the input HTML.
  const _TEXTAREA = (rows) => ({
    render: (id) => `<textarea id="${id}" rows="${rows}"></textarea>`,
    set: (slot, v) => { slot.querySelector('textarea').value = (v == null) ? '' : String(v); },
    get: (slot) => slot.querySelector('textarea').value,
  });
  const CONTROLS = {
    scalar: _TEXTAREA(3),
    long: _TEXTAREA(8),
    list: {
      render: (id) => `<textarea id="${id}" rows="5"></textarea>`,
      set: (slot, v) => { slot.querySelector('textarea').value = (v || []).join('\n'); },
      get: (slot) => slot.querySelector('textarea').value.split('\n').map((s) => s.trim()).filter(Boolean),
    },
    int: {
      render: (id) => `<input type="number" id="${id}" min="0">`,
      set: (slot, v) => { slot.querySelector('input').value = (v == null || v === '') ? '' : String(v); },
      get: (slot) => { const n = parseInt(slot.querySelector('input').value, 10); return Number.isNaN(n) ? 0 : n; },
    },
    radio: {
      render: (id) => `<div class="hd-radio-row">${SEX_OPTIONS.map((o) =>
        `<label class="hd-radio"><input type="radio" name="${id}" value="${o}">${o}</label>`).join('')}</div>`,
      set: (slot, v) => {
        const val = String(v || '').toLowerCase();
        slot.querySelectorAll('input[type=radio]').forEach((r) => { r.checked = r.value.toLowerCase() === val; });
      },
      get: (slot) => { const r = slot.querySelector('input[type=radio]:checked'); return r ? r.value : ''; },
    },
    'feet-inches': {
      render: (id) => `<div class="hd-height">
        <input type="number" min="0" class="hd-ft" id="${id}-ft"><span>ft</span>
        <input type="number" min="0" max="11" class="hd-in" id="${id}-in"><span>in</span></div>`,
      set: (slot, v) => {
        const { feet, inches } = parseHeight(v);
        slot.querySelector('.hd-ft').value = feet;
        slot.querySelector('.hd-in').value = inches;
      },
      get: (slot) => formatHeight(slot.querySelector('.hd-ft').value, slot.querySelector('.hd-in').value),
    },
  };

  // ---- section cards (shared visual wrapper for every tab) ----
  const SECTION_TITLES = {
    identity: 'Identity', personality: 'Personality',
    background: 'Background', speaking_style: 'Speaking Style',
  };
  function sectionCard(title, bodyHtml) {
    return `<section class="hd-section">
      <div class="hd-section-head"><h3 class="hd-section-title">${_escHtml(title)}</h3></div>
      <div class="hd-section-body">${bodyHtml}</div>
    </section>`;
  }

  // ---- generic field rendering ----
  function fieldRowHtml(section, field, label, kind) {
    const inId = `f-${section}-${field}`;
    const hint = kind === 'list' ? '<span class="hd-field-hint">one per line</span>' : '';
    return `<div class="hd-field" data-section="${section}" data-field="${field}" data-kind="${kind}">
      <label for="${inId}">${_escHtml(label)} ${hint}</label>
      ${CONTROLS[kind].render(inId)}
    </div>`;
  }

  function wireField(slot) {
    const { section: sec, field, kind } = slot.dataset;
    CONTROLS[kind].set(slot, getValue(sec, field));
    slot.addEventListener('change', () => saveField(sec, field, kind, slot));
    FieldControls.attach(slot, {
      kind: 'field',
      context: () => ({ section: sec, field, kind, slot }),
      controls: [
        { id: 'gen', label: '✨', title: 'Generate this field', onClick: generateField },
        { id: 'prompt', label: '✏️', title: 'Edit this field\'s prompt', onClick: editPrompt },
      ],
    });
  }

  function renderSection(section, container) {
    const fieldsHtml = FIELDS[section].map(([f, l, k]) => fieldRowHtml(section, f, l, k)).join('');
    container.innerHTML = sectionCard(SECTION_TITLES[section] || section, fieldsHtml);
    container.querySelectorAll('.hd-field').forEach(wireField);
  }

  async function saveField(section, field, kind, slot) {
    const value = CONTROLS[kind].get(slot);
    try {
      await api(`${APP}/characters/${charId}`, 'PUT', patchFor(section, field, value));
      setLocal(section, field, value);
      if (section === 'identity' && (field === 'name' || field === 'tagline')) renderHeader();
      if (section === 'identity' && field === 'sex') renderAppearance();  // re-gate Nude
    } catch (err) {
      console.error('save failed', err);
    }
  }

  async function generateField(ctx, meta) {
    const { section, field, kind, slot } = ctx;
    const btn = meta && meta.button;
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    try {
      const res = await api(`${APP}/characters/${charId}/fields/${section}/${field}/generate`, 'POST');
      CONTROLS[kind].set(slot, res.value);
      setLocal(section, field, res.value);
      if (res.prompt_id) promptMap[`field.${section}.${field}`] = res.prompt_id;
      if (section === 'identity' && (field === 'name' || field === 'tagline')) renderHeader();
    } catch (err) {
      console.error('generate failed', err);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨'; }
    }
  }

  function openPromptFor(key) {
    const id = promptMap[key];
    const url = id
      ? `/prompt-pal/?app=hoodat&highlight=${encodeURIComponent(id)}`
      : `/prompt-pal/?app=hoodat`;
    window.open(url, '_blank');
  }
  function editPrompt(ctx) { openPromptFor(`field.${ctx.section}.${ctx.field}`); }

  // ---- appearance: Basics / Nude (gendered) / Clothed (outfits) ----
  function renderAppearance() {
    const pane = $('tab-appearance');
    const basics = APPEARANCE_BASICS.map(([f, l, k]) => fieldRowHtml('appearance', f, l, k)).join('');
    const sex = (character.sex || '').toLowerCase();
    let nudeFields = NUDE_SHARED.slice();
    if (sex === 'male') nudeFields = nudeFields.concat(NUDE_MALE);
    else if (sex === 'female') nudeFields = nudeFields.concat(NUDE_FEMALE);
    const nude = nudeFields.map(([f, l, k]) => fieldRowHtml('appearance', f, l, k)).join('');
    pane.innerHTML = sectionCard('Basics', basics) + sectionCard('Nude', nude)
      + '<div id="hd-outfits"></div>';
    pane.querySelectorAll('.hd-field').forEach(wireField);
    renderOutfits();
  }

  // ---- outfits (frontend owns the list; persisted wholesale) ----
  function outfitsList() { return ((character.appearance || {}).outfits) || []; }

  function collectOutfits() {
    return Array.from(document.querySelectorAll('#hd-outfits .hd-outfit-card')).map((card) => {
      const o = { name: card.querySelector('.hd-outfit-name').value.trim() };
      OUTFIT_SLOTS.forEach((slot) => { o[slot] = card.querySelector(`textarea[data-slot="${slot}"]`).value.trim(); });
      o.primary = card.querySelector('.hd-outfit-primary').checked;
      return o;
    });
  }

  function normalizeOutfits(list) {
    list = list.filter((o) => o.name || OUTFIT_SLOTS.some((s) => o[s]));
    if (!list.length) return list;
    let pi = list.findIndex((o) => o.primary);
    if (pi === -1) pi = 0;
    list.forEach((o, i) => { o.primary = (i === pi); });
    return list;
  }

  function persistOutfits(list) {
    const norm = normalizeOutfits(list);
    character.appearance = character.appearance || {};
    character.appearance.outfits = norm;
    return api(`${APP}/characters/${charId}`, 'PUT', { appearance: { outfits: norm } });
  }
  function persistOutfitsFromDom() {
    return persistOutfits(collectOutfits()).catch((e) => console.error('outfit save failed', e));
  }

  function outfitCardHtml(o, i) {
    const slots = OUTFIT_SLOTS.map((slot) => `
      <div class="hd-outfit-slot" data-slot="${slot}">
        <label>${_escHtml(SLOT_LABELS[slot])}</label>
        <textarea data-slot="${slot}" rows="2">${_escHtml(o[slot] || '')}</textarea>
      </div>`).join('');
    return `<div class="hd-outfit-card" data-index="${i}">
      <div class="hd-outfit-head">
        <input class="hd-outfit-name" placeholder="Outfit name" value="${_escHtml(o.name || '')}">
        <label class="hd-radio"><input type="radio" class="hd-outfit-primary" name="hd-outfit-primary" ${o.primary ? 'checked' : ''}>primary</label>
        <button type="button" class="hd-outfit-gen secondary" title="Generate the whole outfit">✨ Outfit</button>
        <button type="button" class="hd-outfit-rm secondary" title="Remove outfit">✗</button>
      </div>
      <div class="hd-outfit-slots">${slots}</div>
    </div>`;
  }

  function renderOutfits() {
    const list = outfitsList();
    const container = $('hd-outfits');
    const cards = list.map((o, i) => outfitCardHtml(o, i)).join('');
    const empty = list.length ? '' : '<div class="hd-dlg-empty">No outfits yet.</div>';
    const body = `${empty}<div class="hd-outfit-cards">${cards}</div>
      <div class="hd-dlg-actions"><button type="button" id="hd-outfit-add">+ Add outfit</button></div>`;
    container.innerHTML = sectionCard('Clothed', body);
    $('hd-outfit-add').addEventListener('click', addOutfit);
    container.querySelectorAll('.hd-outfit-card').forEach(wireOutfitCard);
  }

  function wireOutfitCard(card) {
    card.addEventListener('change', persistOutfitsFromDom);
    card.querySelector('.hd-outfit-gen').addEventListener('click', (e) => generateWholeOutfit(card, e.currentTarget));
    card.querySelector('.hd-outfit-rm').addEventListener('click', () => removeOutfit(Number(card.dataset.index)));
    card.querySelectorAll('.hd-outfit-slot').forEach((slotEl) => {
      FieldControls.attach(slotEl, {
        kind: 'field',
        context: () => ({ card, slot: slotEl.dataset.slot, textarea: slotEl.querySelector('textarea') }),
        controls: [
          { id: 'gen', label: '✨', title: 'Generate this slot', onClick: generateOutfitSlot },
          { id: 'prompt', label: '✏️', title: 'Edit the outfit-slot prompt', onClick: () => openPromptFor('outfit.slot') },
        ],
      });
    });
  }

  function addOutfit() {
    const list = collectOutfits();
    const blank = { name: '', primary: list.length === 0 };
    OUTFIT_SLOTS.forEach((s) => { blank[s] = ''; });
    list.push(blank);
    persistOutfits(list).then(renderOutfits).catch((e) => console.error('outfit add failed', e));
  }

  function removeOutfit(index) {
    const list = collectOutfits();
    list.splice(index, 1);
    persistOutfits(list).then(renderOutfits).catch((e) => console.error('outfit remove failed', e));
  }

  async function generateWholeOutfit(card, btn) {
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    const all = collectOutfits();
    const idx = Number(card.dataset.index);
    const others = all.filter((_, i) => i !== idx);
    try {
      const res = await api(`${APP}/characters/${charId}/outfits/generate`, 'POST',
        { outfits: others, outfit: all[idx] || {} });
      if (res.prompt_id) promptMap['outfit.full'] = res.prompt_id;
      const v = res.value || {};
      const nameInput = card.querySelector('.hd-outfit-name');
      if (v.name && !nameInput.value.trim()) nameInput.value = v.name;
      OUTFIT_SLOTS.forEach((slot) => { if (v[slot] != null) card.querySelector(`textarea[data-slot="${slot}"]`).value = v[slot]; });
      await persistOutfitsFromDom();
    } catch (err) {
      console.error('outfit generate failed', err);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨ Outfit'; }
    }
  }

  async function generateOutfitSlot(ctx, meta) {
    const btn = meta && meta.button;
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    const { card, slot, textarea } = ctx;
    const all = collectOutfits();
    const idx = Number(card.dataset.index);
    const others = all.filter((_, i) => i !== idx);
    try {
      const res = await api(`${APP}/characters/${charId}/outfits/slot/${slot}/generate`, 'POST',
        { outfit: all[idx] || {}, outfits: others });
      if (res.prompt_id) promptMap['outfit.slot'] = res.prompt_id;
      textarea.value = res.value || '';
      await persistOutfitsFromDom();
    } catch (err) {
      console.error('outfit slot generate failed', err);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✨'; }
    }
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
          { id: 'prompt', label: '✏️', title: 'Edit the dialogue prompt', onClick: () => openPromptFor('dialogue.example') },
          { id: 'rm', label: '✗', title: 'Remove', onClick: (ctx) => removeDialogue(ctx.index) },
        ],
      });
    });
  }

  // ---- experiences (frontend owns the list; AI also picks the valence) ----
  function experiencesList() { return character.experiences || []; }
  function expRows() { return document.querySelectorAll('#tab-experiences .hd-exp-row'); }
  function collectExperiencesRaw() {
    return Array.from(expRows()).map((row) => ({
      description: row.querySelector('textarea').value,
      valence: (row.querySelector('input[type=radio]:checked') || {}).value || 'positive',
    }));
  }
  function collectExperiences() {
    return collectExperiencesRaw()
      .map((e) => ({ description: e.description.trim(), valence: e.valence }))
      .filter((e) => e.description);
  }

  function persistExperiences(list) {
    character.experiences = list;
    return api(`${APP}/characters/${charId}`, 'PUT', { experiences: list });
  }

  async function generateExperience(experiences) {
    const res = await api(`${APP}/characters/${charId}/experiences/generate`, 'POST', { experiences });
    if (res.prompt_id) promptMap['experience.example'] = res.prompt_id;
    return res.value;  // { description, valence }
  }

  async function addExperience() {
    const list = collectExperiences();
    if (list.length === 0) {
      // Nothing to learn from yet — give the user an empty row to type in (the
      // ✨ on a row generates and lets the LLM pick the valence).
      renderExperiences(collectExperiencesRaw().concat([{ description: '', valence: 'positive' }]));
      const tas = expRows();
      if (tas.length) tas[tas.length - 1].querySelector('textarea').focus();
      return;
    }
    const btn = $('hd-exp-add');
    if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
    try {
      const value = await generateExperience(list);
      const next = list.concat([value]);
      await persistExperiences(next);
      renderExperiences(next);
    } catch (err) {
      console.error('experience add failed', err);
      if (btn) { btn.disabled = false; btn.textContent = '+ Add experience'; }
    }
  }

  async function regenExperience(ctx, meta) {
    const btn = meta && meta.button;
    if (btn) { btn.disabled = true; btn.textContent = '…'; }
    const rows = collectExperiencesRaw();
    const others = rows.filter((_, i) => i !== ctx.index)
      .map((e) => ({ description: e.description.trim(), valence: e.valence })).filter((e) => e.description);
    try {
      const value = await generateExperience(others);
      rows[ctx.index] = value;
      const cleaned = rows.map((e) => ({ description: e.description.trim(), valence: e.valence })).filter((e) => e.description);
      await persistExperiences(cleaned);
      renderExperiences(cleaned);
    } catch (err) {
      console.error('experience regenerate failed', err);
      if (btn) { btn.disabled = false; btn.textContent = '✨'; }
    }
  }

  async function removeExperience(index) {
    const cleaned = collectExperiencesRaw().filter((_, i) => i !== index)
      .map((e) => ({ description: e.description.trim(), valence: e.valence })).filter((e) => e.description);
    try {
      await persistExperiences(cleaned);
      renderExperiences(cleaned);
    } catch (err) {
      console.error('experience remove failed', err);
    }
  }

  function expRowHtml(e, i) {
    const neg = e.valence === 'negative';
    return `<div class="hd-exp-row" data-index="${i}">
      <textarea rows="3" placeholder="Something that happened to them, and how it made them feel…">${_escHtml(e.description || '')}</textarea>
      <div class="hd-radio-row">
        <label class="hd-radio"><input type="radio" name="hd-exp-val-${i}" value="positive" ${neg ? '' : 'checked'}>Positive</label>
        <label class="hd-radio"><input type="radio" name="hd-exp-val-${i}" value="negative" ${neg ? 'checked' : ''}>Negative</label>
      </div>
    </div>`;
  }

  function renderExperiences(list) {
    if (list === undefined) list = experiencesList();
    const container = $('tab-experiences');
    const rowsHtml = list.map((e, i) => expRowHtml(e, i)).join('');
    const empty = list.length ? '' : '<div class="hd-dlg-empty">No experiences yet.</div>';
    const body = `${empty}<div class="hd-exp-rows">${rowsHtml}</div>
      <div class="hd-dlg-actions"><button type="button" id="hd-exp-add">+ Add experience</button></div>`;
    container.innerHTML = sectionCard('Experiences', body);
    $('hd-exp-add').addEventListener('click', addExperience);
    container.querySelectorAll('.hd-exp-row').forEach((row) => {
      row.addEventListener('change', () => persistExperiences(collectExperiences()));
      FieldControls.attach(row, {
        kind: 'field',
        context: () => ({ index: Number(row.dataset.index), row }),
        controls: [
          { id: 'gen', label: '✨', title: 'Regenerate this experience', onClick: regenExperience },
          { id: 'prompt', label: '✏️', title: 'Edit the experience prompt', onClick: () => openPromptFor('experience.example') },
          { id: 'rm', label: '✗', title: 'Remove', onClick: (ctx) => removeExperience(ctx.index) },
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
    renderAppearance();
    renderSection('personality', $('tab-personality'));
    renderSection('background', $('tab-background'));
    renderExperiences();
    renderSection('speaking_style', $('speaking-fields'));
    renderDialogue();
    await loadVoice();
    switchTab(qs.get('tab') || 'identity');
  }

  init();
})();
