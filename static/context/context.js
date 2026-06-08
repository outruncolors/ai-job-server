    let _items = [];
    let _editingId = null;


    function _parseTags(raw) {
      return raw.split(',').map(s => s.trim()).filter(Boolean);
    }

    async function loadItems() {
      try {
        const data = await api('/context-items');
        _items = (data.items || []).slice().sort((a, b) => a.title.localeCompare(b.title));
        renderList();
      } catch(e) {
        document.getElementById('item-list').innerHTML =
          `<div style="color:#e44;font-size:0.75rem;">Error: ${_escHtml(e.message)}</div>`;
      }
    }

    function renderList() {
      const el = document.getElementById('item-list');
      if (_items.length === 0) {
        el.innerHTML = '<div id="empty-state">No context items yet. Click + New to create one.</div>';
        return;
      }
      el.innerHTML = _items.map(item => {
        const tagsHtml = item.tags.length
          ? `<div class="ctx-tags">${item.tags.map(t => `<span class="ctx-tag">${_escHtml(t)}</span>`).join('')}</div>`
          : '';
        const sel = _editingId === item.id ? ' selected' : '';
        return `<div class="ctx-item${sel}" onclick="editItem('${item.id}')">
          <div class="ctx-item-title">${_escHtml(item.name || '(untitled)')}</div>
          ${item.description ? `<div class="ctx-item-desc">${_escHtml(item.description)}</div>` : ''}
          ${tagsHtml}
        </div>`;
      }).join('');
    }

    function _updateCtxPreview() {
      const name = document.getElementById('f-title').value.trim();
      document.getElementById('f-title-preview').textContent = name ? `{{ctx.${name}}}` : '';
    }

    function newItem() {
      _editingId = null;
      document.getElementById('form-heading').textContent = 'New Item';
      document.getElementById('f-title').value = '';
      document.getElementById('f-tags').value = '';
      document.getElementById('f-desc').value = '';
      document.getElementById('f-content').value = '';
      document.getElementById('btn-delete').style.display = 'none';
      document.getElementById('form-msg').textContent = '';
      _updateCtxPreview();
      renderList();
      document.getElementById('f-title').focus();
    }

    function editItem(id) {
      const item = _items.find(i => i.id === id);
      if (!item) return;
      _editingId = id;
      document.getElementById('form-heading').textContent = 'Edit Item';
      document.getElementById('f-title').value = item.title || '';
      document.getElementById('f-tags').value = (item.tags || []).join(', ');
      document.getElementById('f-desc').value = item.description || '';
      document.getElementById('f-content').value = item.content || '';
      document.getElementById('btn-delete').style.display = 'inline-block';
      document.getElementById('form-msg').textContent = '';
      _updateCtxPreview();
      renderList();
    }

    function cancelForm() {
      _editingId = null;
      newItem();
    }

    async function saveItem() {
      const msg = document.getElementById('form-msg');
      msg.style.color = '#777'; msg.textContent = 'Saving…';
      const body = {
        title:       document.getElementById('f-title').value.trim(),
        tags:        _parseTags(document.getElementById('f-tags').value),
        description: document.getElementById('f-desc').value.trim(),
        content:     document.getElementById('f-content').value,
      };
      if (!body.title) { msg.style.color = '#e44'; msg.textContent = 'Title is required.'; return; }
      try {
        if (_editingId) {
          await api('/context-items/' + _editingId, 'PUT', body);
        } else {
          const created = await api('/context-items', 'POST', body);
          _editingId = created.id;
        }
        msg.style.color = '#2a6'; msg.textContent = 'Saved.';
        await loadItems();
        renderList();
        document.getElementById('btn-delete').style.display = 'inline-block';
        document.getElementById('form-heading').textContent = 'Edit Item';
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    async function deleteItem() {
      if (!_editingId) return;
      const item = _items.find(i => i.id === _editingId);
      const name = item ? `"${item.title}"` : 'this item';
      if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
      try {
        await api('/context-items/' + _editingId, 'DELETE');
        _editingId = null;
        await loadItems();
        newItem();
      } catch(e) {
        document.getElementById('form-msg').style.color = '#e44';
        document.getElementById('form-msg').textContent = 'Error: ' + e.message;
      }
    }

    loadItems();
