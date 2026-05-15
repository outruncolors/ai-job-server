let _docs = [];
let _activeDoc = null;

async function loadDocList() {
  const data = await api('/docs');
  _docs = data.docs || [];
  renderList();
  const hash = location.hash.slice(1);
  const initial = _docs.find(d => d.name === hash) || _docs[0];
  if (initial) loadDoc(initial.name);
}

function renderList() {
  const el = document.getElementById('doc-list');
  if (!_docs.length) {
    el.innerHTML = '<div class="empty">No docs found.</div>';
    return;
  }
  el.innerHTML = _docs.map(d => `
    <button class="doc-item${d.name === _activeDoc ? ' active' : ''}"
            data-name="${_escHtml(d.name)}">
      ${_escHtml(d.title)}
      <span class="doc-item-size">${_fmtSize(d.size)}</span>
    </button>
  `).join('');
  el.querySelectorAll('.doc-item').forEach(btn => {
    btn.addEventListener('click', () => loadDoc(btn.dataset.name));
  });
}

async function loadDoc(filename) {
  _activeDoc = filename;
  location.hash = filename;
  renderList();

  const contentEl = document.getElementById('doc-content');
  contentEl.innerHTML = '<div class="doc-placeholder">Loading…</div>';

  try {
    const res = await fetch(`/v1/docs/${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    contentEl.innerHTML = marked.parse(text);
    contentEl.scrollTop = 0;
    document.getElementById('panel-right').scrollTop = 0;
  } catch (e) {
    contentEl.innerHTML = `<div class="doc-placeholder">Failed to load document: ${_escHtml(e.message)}</div>`;
  }
}

function _fmtSize(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  return `${(bytes / 1024).toFixed(1)}K`;
}

window.addEventListener('hashchange', () => {
  const name = location.hash.slice(1);
  if (name && name !== _activeDoc && _docs.find(d => d.name === name)) {
    loadDoc(name);
  }
});

loadDocList();
