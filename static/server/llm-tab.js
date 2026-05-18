// LLM Endpoints sub-tab — CRUD for OpenAI-compatible HTTP destinations
// (/v1/llm-endpoints). The Models sub-tab is in llm-models-tab.js.
// Auto-migrates legacy localStorage presets from the old chain page.

let _llmPresets = [];
let _llmDefaultId = null;
let _llmEditingId = null;
let _activeLlmSubtab = 'models';   // default sub-tab on LLM tab open

function initLlmTab() {}

async function onLlmTabActive() {
  // Load both sub-panes' data (cheap; both are small JSON lists).
  await Promise.all([
    _loadPresets(),
    onLlmModelsActive(),
  ]);
  _migrateLocalStorage();
}

function switchLlmSubtab(name) {
  _activeLlmSubtab = name;
  document.querySelectorAll('.llm-subtab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.llm-subtab-btn').forEach(el => el.classList.remove('active'));
  const pane = document.getElementById('subtab-' + name);
  const btn  = document.querySelector('.llm-subtab-btn[data-subtab="' + name + '"]');
  if (pane) pane.classList.add('active');
  if (btn)  btn.classList.add('active');
}

async function _loadPresets() {
  try {
    const data = await api('/llm-endpoints');
    _llmPresets    = data.presets || [];
    _llmDefaultId  = data.default_preset_id || null;
    _renderPresetList();
  } catch (e) {
    _setLlmMsg('Failed to load presets: ' + e.message, '#e44');
  }
}

function _renderPresetList() {
  const list = document.getElementById('llm-preset-list');
  if (!list) return;
  if (!_llmPresets.length) {
    list.innerHTML = '<div style="color:#444;font-size:0.8rem;padding:10px 0;">No presets yet.</div>';
    return;
  }
  list.innerHTML = _llmPresets.map(p => {
    const isDefault = p.id === _llmDefaultId;
    return '<div class="llm-preset-item' + (p.id === _llmEditingId ? ' selected' : '') + '" onclick="editLlmPreset(\'' + p.id + '\')">' +
      '<div class="llm-preset-name">' + _escHtml(p.name) +
        (isDefault ? ' <span class="llm-default-badge">default</span>' : '') +
      '</div>' +
      '<div class="llm-preset-sub">' + _escHtml(p.api_base) + ' · ' + _escHtml(p.model) + '</div>' +
      '</div>';
  }).join('');
}

function newLlmPreset() {
  _llmEditingId = null;
  document.getElementById('llm-form-heading').textContent = 'New Preset';
  document.getElementById('llm-name').value        = '';
  document.getElementById('llm-api-base').value    = '';
  document.getElementById('llm-model').value       = '';
  document.getElementById('llm-temp').value        = '0.7';
  document.getElementById('llm-max-tokens').value  = '2048';
  document.getElementById('llm-timeout').value     = '120';
  document.getElementById('llm-delete-btn').style.display   = 'none';
  document.getElementById('llm-default-btn').style.display  = 'none';
  _setLlmMsg('', '');
  _renderPresetList();
}

function editLlmPreset(id) {
  const p = _llmPresets.find(x => x.id === id);
  if (!p) return;
  _llmEditingId = id;
  document.getElementById('llm-form-heading').textContent = 'Edit Preset';
  document.getElementById('llm-name').value        = p.name;
  document.getElementById('llm-api-base').value    = p.api_base;
  document.getElementById('llm-model').value       = p.model;
  document.getElementById('llm-temp').value        = p.temperature;
  document.getElementById('llm-max-tokens').value  = p.max_tokens;
  document.getElementById('llm-timeout').value     = p.timeout_seconds;
  document.getElementById('llm-delete-btn').style.display  = '';
  document.getElementById('llm-default-btn').style.display = '';
  document.getElementById('llm-default-btn').textContent   =
    p.id === _llmDefaultId ? 'Clear Default' : 'Set as Default';
  _setLlmMsg('', '');
  _renderPresetList();
}

async function saveLlmPreset() {
  const name = document.getElementById('llm-name').value.trim();
  if (!name) { _setLlmMsg('Name required', '#e44'); return; }
  const body = {
    name,
    api_base:        document.getElementById('llm-api-base').value.trim(),
    model:           document.getElementById('llm-model').value.trim(),
    temperature:     parseFloat(document.getElementById('llm-temp').value),
    max_tokens:      parseInt(document.getElementById('llm-max-tokens').value, 10),
    timeout_seconds: parseInt(document.getElementById('llm-timeout').value, 10),
  };
  if (_llmEditingId) body.id = _llmEditingId;
  _setLlmMsg('Saving…', '#777');
  try {
    const saved = await api('/llm-endpoints', 'POST', body);
    _llmEditingId = saved.id;
    await _loadPresets();
    _setLlmMsg('Saved.', '#2a6');
    document.getElementById('llm-delete-btn').style.display  = '';
    document.getElementById('llm-default-btn').style.display = '';
    document.getElementById('llm-default-btn').textContent   =
      saved.id === _llmDefaultId ? 'Clear Default' : 'Set as Default';
  } catch (e) {
    _setLlmMsg('Error: ' + e.message, '#e44');
  }
}

async function deleteLlmPreset() {
  if (!_llmEditingId) return;
  const p = _llmPresets.find(x => x.id === _llmEditingId);
  if (!p || !confirm('Delete preset "' + p.name + '"?')) return;
  try {
    await api('/llm-endpoints/' + _llmEditingId, 'DELETE');
    _llmEditingId = null;
    await _loadPresets();
    newLlmPreset();
  } catch (e) {
    _setLlmMsg('Delete failed: ' + e.message, '#e44');
  }
}

async function toggleLlmDefault() {
  if (!_llmEditingId) return;
  const newDefault = _llmEditingId === _llmDefaultId ? null : _llmEditingId;
  try {
    await api('/llm-endpoints/default', 'PUT', { id: newDefault });
    _llmDefaultId = newDefault;
    await _loadPresets();
    document.getElementById('llm-default-btn').textContent =
      _llmEditingId === _llmDefaultId ? 'Clear Default' : 'Set as Default';
    _setLlmMsg(newDefault ? 'Set as default.' : 'Default cleared.', '#2a6');
  } catch (e) {
    _setLlmMsg('Error: ' + e.message, '#e44');
  }
}

function _setLlmMsg(text, color) {
  const el = document.getElementById('llm-msg');
  if (!el) return;
  el.textContent  = text;
  el.style.color  = color;
}

async function _migrateLocalStorage() {
  const raw = localStorage.getItem('chain_llm_presets');
  if (!raw) return;
  let legacy;
  try { legacy = JSON.parse(raw); } catch (_) { return; }
  if (!Array.isArray(legacy) || !legacy.length) return;
  if (_llmPresets.length > 0) return; // server already has presets — don't overwrite
  let migrated = 0;
  for (const p of legacy) {
    try {
      await api('/llm-endpoints', 'POST', {
        name:            p.name || 'Migrated',
        api_base:        p.api_base || '',
        model:           p.model || '',
        temperature:     parseFloat(p.temperature ?? 0.7),
        max_tokens:      parseInt(p.max_tokens ?? 2048, 10),
        timeout_seconds: 120,
      });
      migrated++;
    } catch (_) {}
  }
  if (migrated > 0) {
    localStorage.removeItem('chain_llm_presets');
    localStorage.removeItem('chain_llm_preset_selected');
    await _loadPresets();
    toast('success', 'Migrated ' + migrated + ' legacy LLM preset' + (migrated > 1 ? 's' : '') + ' from chain page');
  }
}
