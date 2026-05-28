// Embed Lab — drives the /v1/embed-lab routes.
//
// Two surfaces: a stateless compare panel (paste N texts → similarity matrix)
// and a tiny KNN playground (add/list/delete docs, query). Everything lives in
// its own SQLite db so this can't pollute the blaboratory sim.

// ── Status ──────────────────────────────────────────────────────────────

async function refreshStatus() {
  const el = document.getElementById('status-text');
  try {
    const s = await api('/embed-lab/status');
    const vec = s.vec_available ? 'vec0 loaded' : 'vec0 unavailable';
    el.textContent = `${vec} · ${s.doc_count} docs · dim=${s.embedding_dim}`;
    el.style.color = s.vec_available ? '#888' : '#e44';
  } catch (e) {
    el.textContent = 'status error: ' + e.message;
    el.style.color = '#e44';
  }
}

// ── Compare ─────────────────────────────────────────────────────────────

function _gradeCell(v) {
  // v in [-1, 1] → background hue (red→amber→green)
  const t = Math.max(0, Math.min(1, (v + 1) / 2));   // map to [0,1]
  const r = Math.round(180 * (1 - t) + 30 * t);
  const g = Math.round(30  * (1 - t) + 160 * t);
  const b = 30;
  return `rgb(${r},${g},${b})`;
}

function _renderSimTable(texts, sim) {
  const head = '<tr><th></th>' + texts.map((_, i) => `<th>${i + 1}</th>`).join('') + '</tr>';
  const rows = texts.map((t, i) => {
    const cells = sim[i].map(v =>
      `<td class="cell"><span class="sim-cell-bg" style="background:${_gradeCell(v)}">${v.toFixed(3)}</span></td>`
    ).join('');
    return `<tr><td class="label" title="${_escHtml(t)}">${i + 1}. ${_escHtml(t)}</td>${cells}</tr>`;
  }).join('');
  return `<table class="sim-table">${head}${rows}</table>`;
}

async function runCompare() {
  const ta  = document.getElementById('compare-texts');
  const msg = document.getElementById('compare-msg');
  const out = document.getElementById('compare-result');
  const btn = document.getElementById('compare-btn');
  const texts = ta.value.split('\n').map(s => s.trim()).filter(Boolean);
  if (texts.length < 2) {
    msg.className = 'msg err';
    msg.textContent = 'Need at least 2 non-empty lines.';
    out.innerHTML = '';
    return;
  }
  btn.disabled = true;
  msg.className = 'msg busy';
  msg.textContent = `Embedding ${texts.length}…`;
  out.innerHTML = '';
  try {
    const r = await api('/embed-lab/compare', 'POST', { texts });
    msg.className = 'msg ok';
    msg.textContent = `Done · dim=${r.dim}`;
    out.innerHTML = _renderSimTable(r.texts, r.similarity);
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = 'Error: ' + _detail(e);
  } finally {
    btn.disabled = false;
  }
}

// ── Playground index ────────────────────────────────────────────────────

async function loadDocs() {
  const list = document.getElementById('doc-list');
  const cnt  = document.getElementById('doc-count');
  try {
    const docs = await api('/embed-lab/docs');
    cnt.textContent = `(${docs.length})`;
    if (docs.length === 0) {
      list.innerHTML = '<div class="empty">No docs yet — add one above.</div>';
      return;
    }
    list.innerHTML = docs.map(d =>
      `<div class="doc-row">
        <span class="doc-id">#${d.id}</span>
        <span class="doc-text" title="${_escHtml(d.text)}">${_escHtml(d.text)}</span>
        <button onclick="deleteDoc(${d.id})">×</button>
      </div>`
    ).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty" style="color:#e44">Error: ${_escHtml(e.message)}</div>`;
  }
}

async function addDoc() {
  const inp = document.getElementById('add-text');
  const msg = document.getElementById('add-msg');
  const btn = document.getElementById('add-btn');
  const text = inp.value.trim();
  if (!text) { msg.className = 'msg err'; msg.textContent = 'Enter some text.'; return; }
  btn.disabled = true;
  msg.className = 'msg busy';
  msg.textContent = 'Embedding…';
  try {
    const d = await api('/embed-lab/docs', 'POST', { text });
    msg.className = 'msg ok';
    msg.textContent = `Added #${d.id}.`;
    inp.value = '';
    await loadDocs();
    await refreshStatus();
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = 'Error: ' + _detail(e);
  } finally {
    btn.disabled = false;
  }
}

async function deleteDoc(id) {
  try {
    await api('/embed-lab/docs/' + id, 'DELETE');
    await loadDocs();
    await refreshStatus();
  } catch (e) {
    alert('Delete failed: ' + _detail(e));
  }
}

async function clearDocs() {
  if (!confirm('Clear every doc in the playground? This cannot be undone.')) return;
  try {
    await api('/embed-lab/docs', 'DELETE');
    document.getElementById('query-result').innerHTML = '';
    await loadDocs();
    await refreshStatus();
  } catch (e) {
    alert('Clear failed: ' + _detail(e));
  }
}

async function runQuery() {
  const qInp = document.getElementById('query-text');
  const kInp = document.getElementById('query-k');
  const msg  = document.getElementById('query-msg');
  const out  = document.getElementById('query-result');
  const btn  = document.getElementById('query-btn');
  const q = qInp.value.trim();
  const k = parseInt(kInp.value, 10) || 10;
  if (!q) { msg.className = 'msg err'; msg.textContent = 'Enter a query.'; return; }
  btn.disabled = true;
  msg.className = 'msg busy';
  msg.textContent = `Searching k=${k}…`;
  out.innerHTML = '';
  try {
    const r = await api('/embed-lab/query', 'POST', { query: q, k });
    msg.className = 'msg ok';
    msg.textContent = `${r.hits.length} hit${r.hits.length === 1 ? '' : 's'}`;
    if (r.hits.length === 0) {
      out.innerHTML = '<div class="empty">No hits.</div>';
    } else {
      out.innerHTML = '<div class="hit-list">' + r.hits.map(h =>
        `<div class="hit-row">
          <span class="hit-id">#${h.doc_id}</span>
          <span class="hit-text" title="${_escHtml(h.text)}">${_escHtml(h.text)}</span>
          <span class="hit-dist">d=${h.distance.toFixed(4)}</span>
        </div>`
      ).join('') + '</div>';
    }
  } catch (e) {
    msg.className = 'msg err';
    msg.textContent = 'Error: ' + _detail(e);
  } finally {
    btn.disabled = false;
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────

function _detail(e) {
  try { return JSON.parse(e.message).detail || e.message; }
  catch { return e.message; }
}

// Enter shortcuts on the single-line inputs
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-text').addEventListener('keydown',   e => { if (e.key === 'Enter') addDoc(); });
  document.getElementById('query-text').addEventListener('keydown', e => { if (e.key === 'Enter') runQuery(); });
  refreshStatus();
  loadDocs();
});
