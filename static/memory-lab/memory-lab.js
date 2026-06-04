// Memory Lab — drives the /v1/memory routes.
//
// Atomic test bench: each panel exercises one memory operation and dumps the raw
// JSON response so behavior is observable one step at a time. The demo-fixtures
// panel (test/memory_demo scope) is the fastest way to see memory working before
// wiring it into an app.

const SCOPE_TYPES = [
  'global', 'app', 'project', 'user', 'session', 'character', 'custom', 'test',
];

function _fillScopeSelects() {
  const opts = SCOPE_TYPES.map(t => `<option value="${t}">${t}</option>`).join('');
  ['w-scope-type', 's-scope-type', 'ri-scope-type'].forEach(id => {
    const el = document.getElementById(id);
    el.innerHTML = opts;
    el.value = 'project';
  });
}

function _detail(e) {
  try { return JSON.parse(e.message).detail || e.message; }
  catch { return e.message; }
}

function _raw(id, obj) {
  document.getElementById(id).textContent = JSON.stringify(obj, null, 2);
}

function _setMsg(id, cls, text) {
  const el = document.getElementById(id);
  el.className = 'msg ' + cls;
  el.textContent = text;
}

// ── 1. Health ─────────────────────────────────────────────────────────────

async function refreshHealth() {
  const status = document.getElementById('status-text');
  try {
    const h = await api('/memory/health');
    const ok = h.enabled && h.index_available;
    status.textContent = `${h.enabled ? 'enabled' : 'disabled'} · backend=${h.backend} · index=${h.index_available ? 'ready' : 'unavailable'}`;
    status.style.color = ok ? '#888' : '#fa0';
    document.getElementById('health-result').innerHTML =
      `<div class="kv">
        <div><b>enabled:</b> ${h.enabled}</div>
        <div><b>backend:</b> ${_escHtml(h.backend)}</div>
        <div><b>store path:</b> ${_escHtml(h.store_path)}</div>
        <div><b>index available:</b> ${h.index_available}</div>
        <div><b>message:</b> ${_escHtml(h.message)}</div>
      </div>`;
    _raw('health-raw', h);
    _setMsg('health-msg', 'ok', 'OK');
  } catch (e) {
    status.textContent = 'health error: ' + _detail(e);
    status.style.color = '#e44';
    _setMsg('health-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 2. Write ──────────────────────────────────────────────────────────────

async function writeMemory() {
  const title = document.getElementById('w-title').value.trim();
  const body  = document.getElementById('w-body').value;
  const tags  = document.getElementById('w-tags').value.split(',').map(s => s.trim()).filter(Boolean);
  const scope = {
    scope_type: document.getElementById('w-scope-type').value,
    scope_id: document.getElementById('w-scope-id').value.trim() || 'global',
  };
  if (!title) { _setMsg('write-msg', 'err', 'Enter a title.'); return; }
  _setMsg('write-msg', 'busy', 'Writing…');
  try {
    const r = await api('/memory/write', 'POST', { title, body, scope, tags });
    _setMsg('write-msg', 'ok', `Wrote ${r.memory_id}`);
    _raw('write-raw', r);
    document.getElementById('r-id').value = r.memory_id;
  } catch (e) {
    _setMsg('write-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 3. Search ─────────────────────────────────────────────────────────────

function _renderResults(containerId, results) {
  const out = document.getElementById(containerId);
  if (!results || results.length === 0) {
    out.innerHTML = '<div class="empty">No results.</div>';
    return;
  }
  out.innerHTML = '<div class="result-list">' + results.map(r => `
    <div class="result-card">
      <div class="rc-head">
        <span class="rc-title">${_escHtml(r.title)}</span>
        <span class="rc-score">score ${r.score}</span>
      </div>
      <div class="rc-snippet">${_escHtml(r.snippet)}</div>
      <div class="rc-meta">${_escHtml(r.memory_id)} · ${_escHtml((r.metadata.scope_type || '') + '/' + (r.metadata.scope_id || ''))} · tags: ${_escHtml((r.metadata.tags || []).join(', ') || '—')}</div>
      <div class="rc-path">${_escHtml(r.path)}</div>
    </div>`).join('') + '</div>';
}

async function searchMemory() {
  const query = document.getElementById('s-query').value.trim();
  const allScopes = document.getElementById('s-allscopes').checked;
  const scopeId = document.getElementById('s-scope-id').value.trim();
  const topK = parseInt(document.getElementById('s-topk').value, 10) || 5;
  if (!query) { _setMsg('search-msg', 'err', 'Enter a query.'); return; }
  const scopes = allScopes ? [] : [{
    scope_type: document.getElementById('s-scope-type').value,
    scope_id: scopeId || 'global',
  }];
  _setMsg('search-msg', 'busy', 'Searching…');
  try {
    const r = await api('/memory/search', 'POST', { query, scopes, top_k: topK });
    _setMsg('search-msg', 'ok', `${r.count} hit${r.count === 1 ? '' : 's'} · backend=${r.backend}`);
    _renderResults('search-result', r.results);
    _raw('search-raw', r);
  } catch (e) {
    _setMsg('search-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 4. Read ───────────────────────────────────────────────────────────────

async function readMemory() {
  const id = document.getElementById('r-id').value.trim();
  if (!id) { _setMsg('read-msg', 'err', 'Enter a memory id.'); return; }
  _setMsg('read-msg', 'busy', 'Reading…');
  try {
    const r = await api('/memory/read/' + encodeURIComponent(id));
    const m = r.memory;
    document.getElementById('read-result').innerHTML = `
      <div class="kv"><b>${_escHtml(m.title)}</b></div>
      <div class="result-card"><div class="rc-snippet">${_escHtml(m.body) || '<i>(empty body)</i>'}</div></div>`;
    _raw('read-raw', m.metadata);
    _setMsg('read-msg', 'ok', 'OK');
  } catch (e) {
    document.getElementById('read-result').innerHTML = '';
    _setMsg('read-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 5. Reindex ────────────────────────────────────────────────────────────

async function reindexMemory() {
  const scopeId = document.getElementById('ri-scope-id').value.trim();
  const force = document.getElementById('ri-force').checked;
  const scopes = scopeId ? [{
    scope_type: document.getElementById('ri-scope-type').value,
    scope_id: scopeId,
  }] : [];
  _setMsg('reindex-msg', 'busy', 'Reindexing…');
  try {
    const r = await api('/memory/reindex', 'POST', { scopes, force });
    _setMsg('reindex-msg', 'ok', `backend=${r.backend} · indexed=${r.indexed_files} · skipped=${r.skipped_files}`);
    _raw('reindex-raw', r);
  } catch (e) {
    _setMsg('reindex-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 6. Demo fixtures ───────────────────────────────────────────────────────

async function seedDemo() {
  _setMsg('demo-msg', 'busy', 'Seeding…');
  try {
    const r = await api('/memory/test/seed-demo', 'POST');
    _setMsg('demo-msg', 'ok', `Seeded ${r.memories.length} memories in ${r.scope.scope_type}/${r.scope.scope_id}`);
    _raw('demo-raw', r);
  } catch (e) {
    _setMsg('demo-msg', 'err', 'Error: ' + _detail(e));
  }
}

async function runDemo() {
  _setMsg('demo-msg', 'busy', 'Running fixed searches…');
  try {
    const r = await api('/memory/test/run-demo-searches', 'POST');
    const passed = r.searches.filter(s => s.ok).length;
    _setMsg('demo-msg', passed === r.searches.length ? 'ok' : 'err',
            `${passed}/${r.searches.length} queries matched expected`);
    document.getElementById('demo-result').innerHTML = r.searches.map(s => `
      <div class="demo-row">
        <span class="badge ${s.ok ? 'pass' : 'fail'}">${s.ok ? 'PASS' : 'FAIL'}</span>
        <span class="dq">${_escHtml(s.query)}</span>
        <span class="da">expected: ${_escHtml(s.expected_top)}<br>actual: ${_escHtml(s.actual_top || '—')}</span>
      </div>`).join('');
    _raw('demo-raw', r);
  } catch (e) {
    _setMsg('demo-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── 7. Reset demo ──────────────────────────────────────────────────────────

async function resetDemo() {
  if (!confirm('Clear all demo memories (test/memory_demo scope only)?')) return;
  _setMsg('reset-msg', 'busy', 'Clearing…');
  try {
    const r = await api('/memory/test/reset', 'POST');
    _setMsg('reset-msg', 'ok', `Removed ${r.removed} demo memories`);
    _raw('reset-raw', r);
    document.getElementById('demo-result').innerHTML = '';
  } catch (e) {
    _setMsg('reset-msg', 'err', 'Error: ' + _detail(e));
  }
}

// ── init ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  _fillScopeSelects();
  document.getElementById('s-query').addEventListener('keydown', e => { if (e.key === 'Enter') searchMemory(); });
  document.getElementById('r-id').addEventListener('keydown', e => { if (e.key === 'Enter') readMemory(); });
  refreshHealth();
});
