let _wildcards = [];
let _editingId = null;


async function loadWildcards() {
  try {
    const data = await api('/wildcards');
    _wildcards = (data.wildcards || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    renderList();
  } catch(e) {
    document.getElementById('wc-list').innerHTML =
      `<div style="color:#e44;font-size:0.75rem;">Error: ${_escHtml(e.message)}</div>`;
  }
}

function renderList() {
  const el = document.getElementById('wc-list');
  if (_wildcards.length === 0) {
    el.innerHTML = '<div id="empty-state">No wildcards yet. Click + New to create one.</div>';
    return;
  }
  el.innerHTML = _wildcards.map(wc => {
    const sel = _editingId === wc.id ? ' selected' : '';
    const count = (wc.data && wc.data.entries) ? wc.data.entries.length : 0;
    const desc = (wc.description || '').trim();
    const descHtml = desc ? `<div class="wc-item-desc">${_escHtml(desc)}</div>` : '';
    return `<div class="wc-item${sel}" onclick="editWildcard('${_escHtml(wc.id)}')">
      <div class="wc-item-name"><em>%%</em>${_escHtml(wc.name)}<em>%%</em></div>
      ${descHtml}
      <div class="wc-item-count">${count} ${count === 1 ? 'entry' : 'entries'}</div>
    </div>`;
  }).join('');
}

function _updatePreview() {
  const name = document.getElementById('f-name').value.trim();
  document.getElementById('f-name-preview').textContent = name ? `%%${name}%%` : '';
}

function _renderEntries(entries) {
  const container = document.getElementById('f-entries');
  const emptyMsg  = document.getElementById('f-entries-empty');
  container.innerHTML = '';
  if (!entries || entries.length === 0) {
    emptyMsg.style.display = '';
    return;
  }
  emptyMsg.style.display = 'none';
  entries.forEach((e, i) => {
    const row = document.createElement('div');
    row.className = 'entry-row';
    row.dataset.index = i;
    row.innerHTML = `
      <input type="text" class="entry-text" placeholder="Entry text…" value="${_escHtml(e.text || '')}">
      <div class="entry-weight-wrap">
        <input type="range" class="entry-weight" min="1" max="10" value="${e.weight || 5}">
        <div class="entry-weight-labels"><span>Less often</span><span>More often</span></div>
      </div>
      <button class="entry-remove" onclick="_removeEntry(${i})" title="Remove">×</button>`;
    container.appendChild(row);
  });
}

function _collectEntries() {
  return [...document.querySelectorAll('.entry-row')].map(row => ({
    text:   row.querySelector('.entry-text').value,
    weight: parseInt(row.querySelector('.entry-weight').value, 10) || 5,
  }));
}

function _removeEntry(idx) {
  const entries = _collectEntries();
  entries.splice(idx, 1);
  _renderEntries(entries);
}

function addEntry() {
  const entries = _collectEntries();
  entries.push({ text: '', weight: 5 });
  _renderEntries(entries);
  document.getElementById('f-entries-empty').style.display = 'none';
  const rows = document.querySelectorAll('.entry-row');
  if (rows.length) rows[rows.length - 1].querySelector('.entry-text').focus();
}

function newWildcard() {
  _editingId = null;
  document.getElementById('form-heading').textContent = 'New Wildcard';
  document.getElementById('f-name').value = '';
  document.getElementById('f-name-preview').textContent = '';
  document.getElementById('f-description').value = '';
  document.getElementById('btn-delete').style.display = 'none';
  document.getElementById('form-msg').textContent = '';
  _renderEntries([]);
  renderList();
  document.getElementById('f-name').focus();
}

function editWildcard(id) {
  const wc = _wildcards.find(w => w.id === id);
  if (!wc) return;
  _editingId = id;
  document.getElementById('form-heading').textContent = 'Edit Wildcard';
  document.getElementById('f-name').value = wc.name || '';
  document.getElementById('f-name-preview').textContent = wc.name ? `%%${wc.name}%%` : '';
  document.getElementById('f-description').value = wc.description || '';
  document.getElementById('btn-delete').style.display = 'inline-block';
  document.getElementById('form-msg').textContent = '';
  _renderEntries((wc.data && wc.data.entries) || []);
  renderList();
}

function cancelForm() {
  _editingId = null;
  newWildcard();
}

async function saveWildcard() {
  const msg = document.getElementById('form-msg');
  msg.style.color = '#777'; msg.textContent = 'Saving…';
  const name        = document.getElementById('f-name').value.trim();
  const description = document.getElementById('f-description').value.trim();
  const entries     = _collectEntries();
  if (!name) { msg.style.color = '#e44'; msg.textContent = 'Name is required.'; return; }
  if (entries.length === 0) { msg.style.color = '#e44'; msg.textContent = 'Add at least one entry.'; return; }
  const emptyEntry = entries.find(e => !e.text.trim());
  if (emptyEntry) { msg.style.color = '#e44'; msg.textContent = 'All entries must have text.'; return; }
  try {
    if (_editingId) {
      await api('/wildcards/' + _editingId, 'PUT', { name, description, entries });
    } else {
      const created = await api('/wildcards', 'POST', { name, description, entries });
      _editingId = created.id;
    }
    msg.style.color = '#2a6'; msg.textContent = 'Saved.';
    await loadWildcards();
    document.getElementById('btn-delete').style.display = 'inline-block';
    document.getElementById('form-heading').textContent = 'Edit Wildcard';
  } catch(e) {
    msg.style.color = '#e44'; msg.textContent = 'Error: ' + _wcErrDetail(e);
  }
}

function _wcErrDetail(e) {
  try { return JSON.parse(e.message).detail || e.message; }
  catch { return e.message; }
}

async function deleteWildcard() {
  if (!_editingId) return;
  const wc = _wildcards.find(w => w.id === _editingId);
  const name = wc ? `"%%${wc.name}%%"` : 'this wildcard';
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await api('/wildcards/' + _editingId, 'DELETE');
    _editingId = null;
    await loadWildcards();
    newWildcard();
  } catch(e) {
    document.getElementById('form-msg').style.color = '#e44';
    document.getElementById('form-msg').textContent = 'Error: ' + e.message;
  }
}

loadWildcards();
