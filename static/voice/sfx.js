// ── SFX browser ──────────────────────────────────────────────────────
// Read-only grid to scan + audition imported SFX clips. Loads /v1/sfx/packs
// once and does all pack/profile/category/tag filtering + sorting client-side.

let _sfxPacks    = [];      // cached [{id, display_name, binding, domain, profiles:[…]}]
let _sfxInited   = false;   // lazy-init guard (first switch to the SFX tab)

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
    const dur  = it.duration_ms ? (it.duration_ms / 1000).toFixed(1) + 's' : '';
    const tags = (it.tags || []).map((t) => `<span class="sfx-tag-chip">${_escHtml(t)}</span>`).join('');
    return `<div class="sfx-card" data-url="${_escHtml(sfxFileUrl(it.path))}">
      <div class="sfx-card-head">
        <span class="sfx-card-cat">${_escHtml(it.category || '')}</span>
        <span class="sfx-card-dur">${_escHtml(dur)}</span>
      </div>
      <div class="sfx-card-desc">${_escHtml(it.description || it.id || '')}</div>
      <div class="sfx-card-tags">${tags}</div>
      <button type="button" class="sfx-play">▶ Play</button>
    </div>`;
  }).join('');

  grid.querySelectorAll('.sfx-card').forEach((card) => {
    card.querySelector('.sfx-play').addEventListener('click', () => playSfxCard(card));
  });
}

function playSfxCard(card) {
  const player = document.getElementById('sfx-player');
  document.querySelectorAll('.sfx-card.playing').forEach((c) => c.classList.remove('playing'));
  card.classList.add('playing');
  player.src = card.dataset.url;
  player.play().catch(() => {});
}
