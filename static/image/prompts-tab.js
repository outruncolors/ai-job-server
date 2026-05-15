// Prompts tab — CRUD for saved image prompts (name, prompt, workflow).

let _prompts = [];
let _editingPromptId = null;
let _promptsTabInitialized = false;

function initPromptsTab() {
  if (_promptsTabInitialized) return;
  _promptsTabInitialized = true;
  _populateWorkflowSelect();
  loadPrompts();
}

function _populateWorkflowSelect() {
  const sel = document.getElementById('pf-workflow');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">— any workflow —</option>';
  // _workflows is defined in generate-tab.js
  if (typeof _workflows !== 'undefined') {
    _workflows.forEach(w => {
      const opt = document.createElement('option');
      opt.value = w.name;
      opt.textContent = w.name;
      sel.appendChild(opt);
    });
  }
  if (prev) sel.value = prev;
}

async function loadPrompts() {
  try {
    const data = await api('/image-prompts');
    _prompts = (data.prompts || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    renderPromptList();
  } catch (e) {
    document.getElementById('prompt-list').innerHTML =
      `<div style="color:#e44;font-size:0.75rem;">Error: ${_escHtml(e.message)}</div>`;
  }
}

function renderPromptList() {
  const el = document.getElementById('prompt-list');
  if (_prompts.length === 0) {
    el.innerHTML = '<div id="prompt-empty-state" class="empty">No saved prompts yet. Click + New to create one.</div>';
    return;
  }
  el.innerHTML = _prompts.map(p => {
    const sel = _editingPromptId === p.id ? ' selected' : '';
    const wfHtml = p.workflow
      ? `<div class="ctx-tags"><span class="ctx-tag">${_escHtml(p.workflow)}</span></div>`
      : '';
    const previewText = (p.prompt || '').replace(/\s+/g, ' ').trim();
    return `<div class="ctx-item${sel}" onclick="editPrompt('${p.id}')">
      <div class="ctx-item-title">${_escHtml(p.name || '(unnamed)')}</div>
      ${previewText ? `<div class="ctx-item-desc">${_escHtml(previewText)}</div>` : ''}
      ${wfHtml}
    </div>`;
  }).join('');
}

function newPrompt() {
  _editingPromptId = null;
  document.getElementById('prompt-form-heading').textContent = 'New Prompt';
  document.getElementById('pf-name').value = '';
  _populateWorkflowSelect();
  document.getElementById('pf-workflow').value = '';
  document.getElementById('pf-prompt').value = '';
  document.getElementById('pf-btn-delete').style.display = 'none';
  document.getElementById('prompt-form-msg').textContent = '';
  renderPromptList();
  document.getElementById('pf-name').focus();
}

function editPrompt(id) {
  const p = _prompts.find(x => x.id === id);
  if (!p) return;
  _editingPromptId = id;
  document.getElementById('prompt-form-heading').textContent = 'Edit Prompt';
  document.getElementById('pf-name').value = p.name || '';
  _populateWorkflowSelect();
  document.getElementById('pf-workflow').value = p.workflow || '';
  document.getElementById('pf-prompt').value = p.prompt || '';
  document.getElementById('pf-btn-delete').style.display = 'inline-block';
  document.getElementById('prompt-form-msg').textContent = '';
  renderPromptList();
}

function cancelPromptForm() {
  _editingPromptId = null;
  newPrompt();
}

async function savePrompt() {
  const msg = document.getElementById('prompt-form-msg');
  msg.style.color = '#777'; msg.textContent = 'Saving…';
  const name = document.getElementById('pf-name').value.trim();
  const prompt = document.getElementById('pf-prompt').value;
  const workflow = document.getElementById('pf-workflow').value || null;
  if (!name) { msg.style.color = '#e44'; msg.textContent = 'Name is required.'; return; }
  if (!prompt.trim()) { msg.style.color = '#e44'; msg.textContent = 'Prompt is required.'; return; }
  try {
    if (_editingPromptId) {
      await api('/image-prompts/' + _editingPromptId, 'PUT', { name, prompt, workflow });
    } else {
      const created = await api('/image-prompts', 'POST', { name, prompt, workflow });
      _editingPromptId = created.id;
    }
    msg.style.color = '#2a6'; msg.textContent = 'Saved.';
    await loadPrompts();
    renderPromptList();
    document.getElementById('pf-btn-delete').style.display = 'inline-block';
    document.getElementById('prompt-form-heading').textContent = 'Edit Prompt';
    // Refresh the saved-prompt dropdown on the Generate tab.
    if (typeof loadSavedPromptList === 'function') loadSavedPromptList();
  } catch (e) {
    msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
  }
}

async function deletePrompt() {
  if (!_editingPromptId) return;
  const p = _prompts.find(x => x.id === _editingPromptId);
  const name = p ? `"${p.name}"` : 'this prompt';
  if (!confirm(`Delete ${name}? This cannot be undone.`)) return;
  try {
    await api('/image-prompts/' + _editingPromptId, 'DELETE');
    _editingPromptId = null;
    await loadPrompts();
    newPrompt();
    if (typeof loadSavedPromptList === 'function') loadSavedPromptList();
  } catch (e) {
    document.getElementById('prompt-form-msg').style.color = '#e44';
    document.getElementById('prompt-form-msg').textContent = 'Error: ' + e.message;
  }
}
