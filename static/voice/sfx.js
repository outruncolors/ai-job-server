// ── SFX browser ──────────────────────────────────────────────────────
// Read-only grid to scan + audition imported SFX clips. Loads /v1/sfx/packs
// once and does all pack/profile/category/tag filtering + sorting client-side.

let _sfxPacks    = [];      // cached [{id, display_name, binding, domain, profiles:[…]}]
let _sfxInited   = false;   // lazy-init guard (first switch to the SFX tab)
let _synthList   = [];      // synthesis builder: [{path, label, delay_ms}]
let _synthUrl    = null;    // object URL of the last preview (revoked on replace)

// Build the served file URL for a clip. Paths carry spaces and commas, so
// encode each segment but keep the slashes the route splits on.
function sfxFileUrl(path) {
  return '/v1/sfx/file/' + String(path).split('/').map(encodeURIComponent).join('/');
}

async function initSfxBrowser() {
  if (_sfxInited) return;
  _sfxInited = true;

  const grid = document.getElementById('sfx-grid');
  try {
    const r = await fetch('/v1/sfx/packs');
    _sfxPacks = r.ok ? ((await r.json()).packs || []) : [];
  } catch (e) {
    _sfxPacks = [];
  }

  if (_sfxPacks.length === 0) {
    grid.innerHTML = '<p class="sfx-empty">No SFX packs installed.</p>';
    return;
  }

  const packSel = document.getElementById('sfx-pack');
  packSel.innerHTML = _sfxPacks.map((p) =>
    `<option value="${_escHtml(p.id)}">${_escHtml(p.display_name || p.id)}</option>`
  ).join('');

  packSel.addEventListener('change', onSfxPackChange);
  document.getElementById('sfx-profile').addEventListener('change', onSfxProfileChange);
  ['sfx-search', 'sfx-category', 'sfx-tag', 'sfx-sort'].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener(id === 'sfx-search' ? 'input' : 'change', renderSfxGrid);
  });

  onSfxPackChange();
}

function currentSfxPack() {
  const id = document.getElementById('sfx-pack').value;
  return _sfxPacks.find((p) => p.id === id) || null;
}

function currentSfxProfile() {
  const pack = currentSfxPack();
  if (!pack) return null;
  const id = document.getElementById('sfx-profile').value;
  return (pack.profiles || []).find((pr) => pr.id === id) || null;
}

function onSfxPackChange() {
  const pack = currentSfxPack();
  const profSel = document.getElementById('sfx-profile');
  const profiles = (pack && pack.profiles) || [];
  profSel.innerHTML = profiles.map((pr) =>
    `<option value="${_escHtml(pr.id)}">${_escHtml(pr.display_name || pr.id)}</option>`
  ).join('');
  onSfxProfileChange();
}

function onSfxProfileChange() {
  const profile = currentSfxProfile();
  const items = (profile && profile.items) || [];

  // Rebuild the category + tag/domain facets from this profile's clips.
  const cats = [...new Set(items.map((it) => it.category).filter(Boolean))].sort();
  const tags = [...new Set(items.flatMap((it) => [...(it.tags || []), it.domain]).filter(Boolean))].sort();

  document.getElementById('sfx-category').innerHTML =
    '<option value="">All</option>' +
    cats.map((c) => `<option value="${_escHtml(c)}">${_escHtml(c)}</option>`).join('');
  document.getElementById('sfx-tag').innerHTML =
    '<option value="">All</option>' +
    tags.map((t) => `<option value="${_escHtml(t)}">${_escHtml(t)}</option>`).join('');

  renderSfxGrid();
}

function renderSfxGrid() {
  const grid    = document.getElementById('sfx-grid');
  const profile = currentSfxProfile();
  const items   = (profile && profile.items) || [];

  const q   = document.getElementById('sfx-search').value.trim().toLowerCase();
  const cat = document.getElementById('sfx-category').value;
  const tag = document.getElementById('sfx-tag').value;
  const sort = document.getElementById('sfx-sort').value;

  let rows = items.filter((it) => {
    if (cat && it.category !== cat) return false;
    if (tag && !((it.tags || []).includes(tag) || it.domain === tag)) return false;
    if (q) {
      const hay = [it.description, it.id, it.category, it.domain, ...(it.tags || [])]
        .filter(Boolean).join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  const nameKey = (it) => (it.description || it.id || '').toLowerCase();
  rows.sort((a, b) => {
    if (sort === 'duration') return (a.duration_ms || 0) - (b.duration_ms || 0);
    if (sort === 'category') return (a.category || '').localeCompare(b.category || '') ||
                                    nameKey(a).localeCompare(nameKey(b));
    return nameKey(a).localeCompare(nameKey(b));
  });

  document.getElementById('sfx-count').textContent =
    `${rows.length} clip${rows.length === 1 ? '' : 's'}` +
    (rows.length !== items.length ? ` of ${items.length}` : '');

  if (rows.length === 0) {
    grid.innerHTML = '<p class="sfx-empty">No clips match.</p>';
    return;
  }

  grid.innerHTML = rows.map((it) => {
    const dur   = it.duration_ms ? (it.duration_ms / 1000).toFixed(1) + 's' : '';
    const tags  = (it.tags || []).map((t) => `<span class="sfx-tag-chip">${_escHtml(t)}</span>`).join('');
    const label = it.description || it.id || '';
    const isWav = /\.wav$/i.test(it.path || '');
    const addBtn = isWav
      ? `<button type="button" class="sfx-add" title="Add to synthesis">➕</button>`
      : `<button type="button" class="sfx-add" disabled title="WAV only — OGG can't be synthesized yet">➕</button>`;
    return `<div class="sfx-card" data-url="${_escHtml(sfxFileUrl(it.path))}"
                 data-path="${_escHtml(it.path)}" data-label="${_escHtml(label)}">
      <div class="sfx-card-head">
        <span class="sfx-card-cat">${_escHtml(it.category || '')}</span>
        <span class="sfx-card-dur">${_escHtml(dur)}</span>
      </div>
      <div class="sfx-card-desc">${_escHtml(label)}</div>
      <div class="sfx-card-tags">${tags}</div>
      <div class="sfx-card-actions">
        <button type="button" class="sfx-play">▶ Play</button>
        ${addBtn}
      </div>
    </div>`;
  }).join('');

  grid.querySelectorAll('.sfx-card').forEach((card) => {
    card.querySelector('.sfx-play').addEventListener('click', () => playSfxCard(card));
    const add = card.querySelector('.sfx-add');
    if (add && !add.disabled) {
      add.addEventListener('click', () => addToSynthesis(card.dataset.path, card.dataset.label));
    }
  });
}

function playSfxCard(card) {
  const player = document.getElementById('sfx-player');
  document.querySelectorAll('.sfx-card.playing').forEach((c) => c.classList.remove('playing'));
  card.classList.add('playing');
  player.src = card.dataset.url;
  player.play().catch(() => {});
}

// ── L2 tabs: Explorer / Synthesis ────────────────────────────────────
function switchSfxTab(tab) {
  document.querySelectorAll('#sfx-l2-nav .l2-btn').forEach((b) =>
    b.classList.toggle('active', b.dataset.l2 === tab));
  document.getElementById('sfx-explorer').style.display  = tab === 'explorer'  ? '' : 'none';
  document.getElementById('sfx-synthesis').style.display = tab === 'synthesis' ? '' : 'none';
  if (tab === 'synthesis') { renderSynthList(); loadSavedSamples(); }
}

// ── Synthesis builder ────────────────────────────────────────────────
function addToSynthesis(path, label) {
  _synthList.push({ path, label: label || path, delay_ms: 200 });
  updateSynthBadge();
  // If we're already on the synthesis tab, reflect it immediately.
  if (document.getElementById('sfx-synthesis').style.display !== 'none') renderSynthList();
}

function updateSynthBadge() {
  const btn = document.querySelector('#sfx-l2-nav .l2-btn[data-l2="synthesis"]');
  if (btn) btn.textContent = _synthList.length ? `Synthesis (${_synthList.length})` : 'Synthesis';
}

function moveSynth(i, d) {
  const j = i + d;
  if (j < 0 || j >= _synthList.length) return;
  [_synthList[i], _synthList[j]] = [_synthList[j], _synthList[i]];
  renderSynthList();
}

function renderSynthList() {
  const wrap = document.getElementById('sfx-synth-list');
  if (_synthList.length === 0) {
    wrap.innerHTML = '<p class="sfx-empty">No clips yet — add some from the Explorer (➕).</p>';
  } else {
    wrap.innerHTML = _synthList.map((c, i) => `
      <div class="sfx-synth-row" data-i="${i}">
        <span class="sfx-synth-idx">${i + 1}</span>
        <span class="sfx-synth-label">${_escHtml(c.label)}</span>
        <label class="sfx-synth-delay">delay
          <input type="number" class="sfx-synth-delay-in" min="0" step="50" value="${c.delay_ms}"> ms
        </label>
        <button type="button" class="sfx-synth-up"   title="Move up">↑</button>
        <button type="button" class="sfx-synth-down" title="Move down">↓</button>
        <button type="button" class="sfx-synth-del"  title="Remove">✕</button>
      </div>`).join('');
    wrap.querySelectorAll('.sfx-synth-row').forEach((row) => {
      const i = parseInt(row.dataset.i, 10);
      row.querySelector('.sfx-synth-delay-in').addEventListener('input', (e) => {
        _synthList[i].delay_ms = Math.max(0, parseInt(e.target.value, 10) || 0);
      });
      row.querySelector('.sfx-synth-up').addEventListener('click', () => moveSynth(i, -1));
      row.querySelector('.sfx-synth-down').addEventListener('click', () => moveSynth(i, 1));
      row.querySelector('.sfx-synth-del').addEventListener('click', () => {
        _synthList.splice(i, 1); renderSynthList(); updateSynthBadge();
      });
    });
  }
  // Editing the list invalidates the last preview, so re-require Synthesize before Save.
  document.getElementById('sfx-synth-save').disabled = true;
}

function clearSynthesis() {
  _synthList = [];
  renderSynthList();
  updateSynthBadge();
  document.getElementById('sfx-synth-msg').textContent = '';
}

function _synthClips() {
  return _synthList.map((c) => ({ path: c.path, delay_ms: c.delay_ms }));
}

async function runSynthesis() {
  const msg    = document.getElementById('sfx-synth-msg');
  const player = document.getElementById('sfx-synth-player');
  if (_synthList.length === 0) { msg.textContent = 'Add at least one clip first.'; return; }
  msg.textContent = 'Synthesizing…';
  try {
    const r = await fetch('/v1/sfx/synthesize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clips: _synthClips() }),
    });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    const blob = await r.blob();
    if (_synthUrl) URL.revokeObjectURL(_synthUrl);
    _synthUrl = URL.createObjectURL(blob);
    player.src = _synthUrl;
    player.play().catch(() => {});
    document.getElementById('sfx-synth-save').disabled = false;
    const n = _synthList.length;
    msg.textContent = `Synthesized ${n} clip${n === 1 ? '' : 's'}.`;
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
  }
}

async function saveSynthesis() {
  const msg  = document.getElementById('sfx-synth-msg');
  const name = document.getElementById('sfx-synth-name').value.trim();
  if (_synthList.length === 0) { msg.textContent = 'Nothing to save.'; return; }
  try {
    const r = await fetch('/v1/sfx/synthesis', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, clips: _synthClips() }),
    });
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    const rec = await r.json();
    msg.textContent = `Saved “${rec.name}”.`;
    document.getElementById('sfx-synth-name').value = '';
    loadSavedSamples();
  } catch (e) {
    msg.textContent = 'Error: ' + e.message;
  }
}

async function loadSavedSamples() {
  const wrap = document.getElementById('sfx-saved');
  let samples = [];
  try {
    const r = await fetch('/v1/sfx/synthesis');
    samples = r.ok ? ((await r.json()).samples || []) : [];
  } catch (e) { samples = []; }

  if (samples.length === 0) {
    wrap.innerHTML = '<p class="sfx-empty">No saved samples yet.</p>';
    return;
  }
  wrap.innerHTML = samples.map((s) => {
    const dur = s.duration_ms ? (s.duration_ms / 1000).toFixed(1) + 's' : '';
    const n   = (s.clips || []).length;
    return `<div class="sfx-saved-row" data-id="${_escHtml(s.id)}">
      <span class="sfx-saved-name">${_escHtml(s.name || 'Untitled')}</span>
      <span class="sfx-saved-meta">${n} clip${n === 1 ? '' : 's'} · ${_escHtml(dur)}</span>
      <button type="button" class="sfx-saved-play" title="Play">▶</button>
      <button type="button" class="sfx-saved-del"  title="Delete">✕</button>
    </div>`;
  }).join('');

  const player = document.getElementById('sfx-synth-player');
  wrap.querySelectorAll('.sfx-saved-row').forEach((row) => {
    const id = row.dataset.id;
    row.querySelector('.sfx-saved-play').addEventListener('click', () => {
      player.src = `/v1/sfx/synthesis/${encodeURIComponent(id)}/file`;
      player.play().catch(() => {});
    });
    row.querySelector('.sfx-saved-del').addEventListener('click', () => deleteSavedSample(id));
  });
}

async function deleteSavedSample(id) {
  if (!window.confirm('Delete this saved sample?')) return;
  try {
    const r = await fetch(`/v1/sfx/synthesis/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    loadSavedSamples();
  } catch (e) {
    document.getElementById('sfx-synth-msg').textContent = 'Error: ' + e.message;
  }
}
