/* Prompt Pal — list/filter/sort/search + editor, with ?highlight=<id> deep-link.
   Apps link here as /prompt-pal/?app=<app>&highlight=<id> to jump to one prompt. */
(function () {
  const $ = (id) => document.getElementById(id);

  let _entries = [];
  let _selectedId = null;

  // ---- loading ----
  async function load() {
    const data = await api('/prompt-pal/entries');
    _entries = data.entries || [];
    rebuildFilters();
    render();
  }

  function rebuildFilters() {
    const apps = [...new Set(_entries.map((e) => e.app))].sort();
    const tags = [...new Set(_entries.flatMap((e) => e.tags || []))].sort();
    fillSelect($('pp-filter-app'), 'All apps', apps);
    fillSelect($('pp-filter-tag'), 'All tags', tags);
  }

  function fillSelect(sel, allLabel, values) {
    const prev = sel.value;
    sel.innerHTML =
      `<option value="">${_escHtml(allLabel)}</option>` +
      values.map((v) => `<option value="${_escHtml(v)}">${_escHtml(v)}</option>`).join('');
    if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  }

  // ---- list rendering ----
  function visibleEntries() {
    const q = $('pp-search').value.trim().toLowerCase();
    const fApp = $('pp-filter-app').value;
    const fTag = $('pp-filter-tag').value;
    let out = _entries.filter((e) => {
      if (fApp && e.app !== fApp) return false;
      if (fTag && !(e.tags || []).includes(fTag)) return false;
      if (q) {
        const hay = [e.title, e.key, e.description, (e.tags || []).join(' ')]
          .join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const sort = $('pp-sort').value;
    out.sort((a, b) => {
      if (sort === 'title') return (a.title || '').localeCompare(b.title || '');
      if (sort === 'updated') return (b.updated_at || '').localeCompare(a.updated_at || '');
      // app: group by app then key
      return (a.app + a.key).localeCompare(b.app + b.key);
    });
    return out;
  }

  function render() {
    const list = $('pp-list');
    const items = visibleEntries();
    if (!items.length) {
      list.innerHTML = '<div class="pp-empty">No prompts match.</div>';
      return;
    }
    list.innerHTML = items.map((e) => {
      const sel = e.id === _selectedId ? ' selected' : '';
      const tags = (e.tags || []).map((t) => `<span class="pp-tag">${_escHtml(t)}</span>`).join('');
      return `<div class="pp-row${sel}" data-id="${_escHtml(e.id)}">
        <div class="pp-row-top">
          <span class="pp-badge">${_escHtml(e.app)}</span>
          <span class="pp-row-title">${_escHtml(e.title || e.key)}</span>
        </div>
        <code class="pp-key">${_escHtml(e.key)}</code>
        <div class="pp-tags">${tags}</div>
      </div>`;
    }).join('');
  }

  // ---- editor ----
  function select(id, { scroll = false } = {}) {
    const entry = _entries.find((e) => e.id === id);
    if (!entry) return;
    _selectedId = id;
    $('pp-editor-empty').hidden = true;
    $('pp-editor').hidden = false;
    $('pp-ed-app').textContent = entry.app;
    $('pp-ed-key').textContent = entry.key;
    $('pp-ed-title').value = entry.title || '';
    $('pp-ed-desc').value = entry.description || '';
    $('pp-ed-tags').value = (entry.tags || []).join(', ');
    $('pp-ed-prompt').value = entry.prompt || '';
    $('pp-ed-vars').value = JSON.stringify(entry.variables || {}, null, 2);
    const guard = entry.guard || {};
    $('pp-ed-guard-enabled').checked = guard.enabled !== false && !!(guard.prompt || '').trim();
    $('pp-ed-guard-prompt').value = guard.prompt || '';
    $('pp-ed-guard-vars').value = JSON.stringify(guard.variables || {}, null, 2);
    applyGuardState();
    $('pp-guard-preview').hidden = true;
    $('pp-preview').hidden = true;
    $('pp-ed-msg').textContent = '';
    render();
    if (scroll) {
      const row = document.querySelector(`.pp-row[data-id="${CSS.escape(id)}"]`);
      if (row) {
        row.scrollIntoView({ block: 'center' });
        row.classList.add('flash');
        setTimeout(() => row.classList.remove('flash'), 1600);
      }
    }
  }

  function parseVars(raw) {
    const t = raw.trim();
    if (!t) return {};
    const v = JSON.parse(t); // throws → caught by caller
    if (typeof v !== 'object' || Array.isArray(v)) throw new Error('variables must be a JSON object');
    return v;
  }

  // Dim the guard body when the toggle is off (still editable, just visually off).
  function applyGuardState() {
    $('pp-ed-guard').classList.toggle('off', !$('pp-ed-guard-enabled').checked);
  }

  // Build the guard object from the editor fields. Throws on bad guard JSON.
  function collectGuard() {
    return {
      enabled: $('pp-ed-guard-enabled').checked,
      prompt: $('pp-ed-guard-prompt').value,
      variables: parseVars($('pp-ed-guard-vars').value),
    };
  }

  async function save(e) {
    e.preventDefault();
    const msg = $('pp-ed-msg');
    let variables, guard;
    try {
      variables = parseVars($('pp-ed-vars').value);
    } catch (err) {
      msg.textContent = 'Invalid variables JSON: ' + err.message;
      msg.className = 'err';
      return;
    }
    try {
      guard = collectGuard();
    } catch (err) {
      msg.textContent = 'Invalid guard variables JSON: ' + err.message;
      msg.className = 'err';
      return;
    }
    const body = {
      title: $('pp-ed-title').value,
      description: $('pp-ed-desc').value,
      tags: $('pp-ed-tags').value.split(',').map((s) => s.trim()).filter(Boolean),
      prompt: $('pp-ed-prompt').value,
      variables,
      guard,
    };
    try {
      const updated = await api(`/prompt-pal/entries/${_selectedId}`, 'PUT', body);
      const i = _entries.findIndex((x) => x.id === updated.id);
      if (i >= 0) _entries[i] = updated;
      rebuildFilters();
      render();
      msg.textContent = 'Saved.';
      msg.className = 'ok';
    } catch (err) {
      msg.textContent = 'Save failed: ' + err.message;
      msg.className = 'err';
    }
  }

  async function preview() {
    const out = $('pp-preview');
    let variables;
    try {
      variables = parseVars($('pp-ed-vars').value);
    } catch (err) {
      out.hidden = false;
      out.textContent = 'Invalid variables JSON: ' + err.message;
      return;
    }
    try {
      const r = await api(`/prompt-pal/entries/${_selectedId}/preview`, 'POST', { variables });
      out.hidden = false;
      out.textContent = r.text;
    } catch (err) {
      out.hidden = false;
      out.textContent = 'Preview failed: ' + err.message;
    }
  }

  // Preview the guard prompt. The guard previewed on disk is the SAVED guard, so
  // remind the user to save edits first; {{previous}} is left intact (runtime).
  async function previewGuard() {
    const out = $('pp-guard-preview');
    let variables;
    try {
      variables = parseVars($('pp-ed-guard-vars').value);
    } catch (err) {
      out.hidden = false;
      out.textContent = 'Invalid guard variables JSON: ' + err.message;
      return;
    }
    try {
      const r = await api(`/prompt-pal/entries/${_selectedId}/preview`, 'POST',
        { variables, target: 'guard' });
      out.hidden = false;
      out.textContent = r.text;
    } catch (err) {
      out.hidden = false;
      out.textContent = 'Guard preview failed (save first?): ' + err.message;
    }
  }

  // ---- events ----
  function wire() {
    $('pp-list').addEventListener('click', (e) => {
      const row = e.target.closest('.pp-row');
      if (row) select(row.dataset.id);
    });
    ['pp-search', 'pp-filter-app', 'pp-filter-tag', 'pp-sort'].forEach((id) =>
      $(id).addEventListener('input', render));
    $('pp-editor').addEventListener('submit', save);
    $('pp-preview-btn').addEventListener('click', preview);
    $('pp-ed-guard-enabled').addEventListener('change', applyGuardState);
    $('pp-guard-preview-btn').addEventListener('click', previewGuard);
  }

  async function init() {
    wire();
    await load();
    const qs = new URLSearchParams(location.search);
    const app = qs.get('app');
    if (app) { $('pp-filter-app').value = app; render(); }
    const hi = qs.get('highlight');
    if (hi) select(hi, { scroll: true });
  }

  init();
})();
