let _tickets = [];
let _editingId = null;
let _dragId = null;

function _parseHints(raw) {
  return raw.split('\n').map(s => s.trim()).filter(Boolean);
}

async function loadTickets() {
  try {
    const data = await api('/tickets');
    _tickets = data.tickets || [];
    renderList();
  } catch (e) {
    document.getElementById('ticket-list').innerHTML =
      `<li style="color:#e44;font-size:0.75rem;list-style:none;">Error: ${_escHtml(e.message)}</li>`;
  }
}

function renderList() {
  const el = document.getElementById('ticket-list');
  if (_tickets.length === 0) {
    el.innerHTML = '<li id="empty-state" class="empty">No tickets yet. Click + New to create one.</li>';
    return;
  }
  el.innerHTML = _tickets.map((t, i) => {
    const sel = _editingId === t.id ? ' selected' : '';
    const status = t.status || 'todo';
    const hintCount = (t.file_hints || []).length;
    return `<li class="ticket-item${sel}" draggable="true" data-id="${_escHtml(t.id)}" data-idx="${i}"
              onclick="editTicket('${t.id}')">
      <span class="ticket-prio">${i + 1}.</span>
      <div class="ticket-body">
        <div class="ticket-title">${_escHtml(t.title || '(untitled)')}</div>
        ${t.description ? `<div class="ticket-desc">${_escHtml(t.description)}</div>` : ''}
        <div class="ticket-meta">
          <span class="ticket-status ${status}">${_escHtml(status)}</span>
          ${hintCount ? `<span class="ticket-hint-count">${hintCount} hint${hintCount === 1 ? '' : 's'}</span>` : ''}
        </div>
      </div>
    </li>`;
  }).join('');

  el.querySelectorAll('.ticket-item').forEach(li => {
    li.addEventListener('dragstart', onDragStart);
    li.addEventListener('dragover', onDragOver);
    li.addEventListener('dragleave', onDragLeave);
    li.addEventListener('drop', onDrop);
    li.addEventListener('dragend', onDragEnd);
  });
}

function onDragStart(e) {
  _dragId = this.dataset.id;
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  if (this.dataset.id !== _dragId) this.classList.add('drop-target');
}

function onDragLeave() {
  this.classList.remove('drop-target');
}

async function onDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  this.classList.remove('drop-target');
  const targetId = this.dataset.id;
  if (!_dragId || _dragId === targetId) return;

  const fromIdx = _tickets.findIndex(t => t.id === _dragId);
  const toIdx = _tickets.findIndex(t => t.id === targetId);
  if (fromIdx < 0 || toIdx < 0) return;

  const [moved] = _tickets.splice(fromIdx, 1);
  _tickets.splice(toIdx, 0, moved);
  renderList();

  try {
    await api('/tickets/reorder', 'POST', { ids: _tickets.map(t => t.id) });
    toast('success', 'Reordered.');
  } catch (err) {
    toast('error', 'Reorder failed: ' + err.message);
    await loadTickets();
  }
}

function onDragEnd() {
  this.classList.remove('dragging');
  document.querySelectorAll('.ticket-item.drop-target').forEach(el => el.classList.remove('drop-target'));
  _dragId = null;
}

function newTicket() {
  _editingId = null;
  document.getElementById('form-heading').textContent = 'New Ticket';
  document.getElementById('f-title').value = '';
  document.getElementById('f-desc').value = '';
  document.getElementById('f-status').value = 'todo';
  document.getElementById('f-hints').value = '';
  document.getElementById('f-branch').value = '';
  document.getElementById('btn-delete').style.display = 'none';
  document.getElementById('form-msg').textContent = '';
  renderList();
  document.getElementById('f-title').focus();
}

function editTicket(id) {
  const t = _tickets.find(x => x.id === id);
  if (!t) return;
  _editingId = id;
  document.getElementById('form-heading').textContent = 'Edit Ticket';
  document.getElementById('f-title').value = t.title || '';
  document.getElementById('f-desc').value = t.description || '';
  document.getElementById('f-status').value = t.status || 'todo';
  document.getElementById('f-hints').value = (t.file_hints || []).join('\n');
  document.getElementById('f-branch').value = t.branch || '';
  document.getElementById('btn-delete').style.display = 'inline-block';
  document.getElementById('form-msg').textContent = '';
  renderList();
}

function cancelForm() {
  newTicket();
}

async function saveTicket() {
  const msg = document.getElementById('form-msg');
  msg.style.color = '#777';
  msg.textContent = 'Saving…';
  const body = {
    title: document.getElementById('f-title').value.trim(),
    description: document.getElementById('f-desc').value.trim(),
    status: document.getElementById('f-status').value,
    file_hints: _parseHints(document.getElementById('f-hints').value),
  };
  if (!body.title) {
    msg.style.color = '#e44';
    msg.textContent = 'Title is required.';
    return;
  }
  try {
    if (_editingId) {
      await api('/tickets/' + _editingId, 'PATCH', body);
    } else {
      const created = await api('/tickets', 'POST', { title: body.title, description: body.description, file_hints: body.file_hints });
      _editingId = created.id;
      if (body.status !== 'todo') {
        await api('/tickets/' + created.id, 'PATCH', { status: body.status });
      }
    }
    msg.style.color = '#2a6';
    msg.textContent = 'Saved.';
    await loadTickets();
    document.getElementById('btn-delete').style.display = 'inline-block';
    document.getElementById('form-heading').textContent = 'Edit Ticket';
  } catch (e) {
    msg.style.color = '#e44';
    msg.textContent = 'Error: ' + e.message;
  }
}

async function deleteTicket() {
  if (!_editingId) return;
  const t = _tickets.find(x => x.id === _editingId);
  const name = t ? `"${t.title}"` : 'this ticket';
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await api('/tickets/' + _editingId, 'DELETE');
    _editingId = null;
    await loadTickets();
    newTicket();
  } catch (e) {
    document.getElementById('form-msg').style.color = '#e44';
    document.getElementById('form-msg').textContent = 'Error: ' + e.message;
  }
}

loadTickets();
