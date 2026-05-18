// LLM-presets page: CRUD over llama.cpp model load presets.

let _presets = [];
let _editingName = null;  // null = creating new

async function loadPresets() {
  try {
    const data = await api('/llm-presets');
    _presets = (data.presets || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    renderList();
  } catch (e) {
    document.getElementById('preset-list').innerHTML =
      `<div style="color:#e44;font-size:0.75rem;">Error: ${_escHtml(e.message)}</div>`;
  }
}

function renderList() {
  const el = document.getElementById('preset-list');
  if (_presets.length === 0) {
    el.innerHTML = '<div id="empty-state" class="empty">No presets yet. Click + New to create one.</div>';
    return;
  }
  el.innerHTML = _presets.map(p => {
    const sel = _editingName === p.name ? ' selected' : '';
    const desc = (p.description || '').trim();
    const sub  = desc || p.model_path || '';
    const caps = (p.capabilities || []).join(' · ');
    return `<div class="preset-item${sel}" onclick="editPreset('${_escHtml(p.name)}')">
      <div class="preset-item-name">${_escHtml(p.name)}</div>
      <div class="preset-item-sub">${_escHtml(sub)}</div>
      <div class="preset-item-caps">${_escHtml(caps)}</div>
    </div>`;
  }).join('');
}

function _renderArgs(args) {
  const container = document.getElementById('f-args');
  const empty = document.getElementById('f-args-empty');
  container.innerHTML = '';
  const entries = Object.entries(args || {});
  if (entries.length === 0) {
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  entries.forEach(([k, v], i) => {
    const row = document.createElement('div');
    row.className = 'arg-row';
    let valDisplay;
    if (v === true)          valDisplay = 'true';
    else if (v === false)    valDisplay = 'false';
    else if (v === null)     valDisplay = 'null';
    else                     valDisplay = String(v);
    row.innerHTML = `
      <input type="text" class="arg-key"   placeholder="key (e.g. ctx_size)" value="${_escHtml(k)}">
      <input type="text" class="arg-value" placeholder="value" value="${_escHtml(valDisplay)}">
      <button class="arg-remove" onclick="_removeArg(${i})" title="Remove">×</button>`;
    container.appendChild(row);
  });
}

function _collectArgs() {
  const out = {};
  for (const row of document.querySelectorAll('.arg-row')) {
    const k = row.querySelector('.arg-key').value.trim();
    if (!k) continue;
    const rawV = row.querySelector('.arg-value').value.trim();
    out[k] = _coerceArgValue(rawV);
  }
  return out;
}

function _coerceArgValue(raw) {
  if (raw === '' || raw.toLowerCase() === 'null') return null;
  if (raw.toLowerCase() === 'true')  return true;
  if (raw.toLowerCase() === 'false') return false;
  if (/^-?\d+$/.test(raw))           return parseInt(raw, 10);
  if (/^-?\d*\.\d+$/.test(raw))      return parseFloat(raw);
  return raw;
}

function _removeArg(idx) {
  const args = _collectArgs();
  const keys = Object.keys(args);
  if (idx < 0 || idx >= keys.length) return;
  delete args[keys[idx]];
  _renderArgs(args);
}

function addArg() {
  const args = _collectArgs();
  // Use a unique placeholder key so the new row renders without clobbering existing entries.
  let i = 1;
  while (Object.prototype.hasOwnProperty.call(args, `_new_${i}`)) i++;
  args[`_new_${i}`] = '';
  _renderArgs(args);
  const rows = document.querySelectorAll('.arg-row');
  if (rows.length) rows[rows.length - 1].querySelector('.arg-key').focus();
}

function newPreset() {
  _editingName = null;
  document.getElementById('form-heading').textContent = 'New Preset';
  document.getElementById('f-name').value        = '';
  document.getElementById('f-name').disabled     = false;
  document.getElementById('f-description').value = '';
  document.getElementById('f-model-path').value  = '';
  document.getElementById('cap-vision').checked  = false;
  document.getElementById('btn-delete').style.display = 'none';
  document.getElementById('form-msg').textContent = '';
  _renderArgs({});
  renderList();
  document.getElementById('f-name').focus();
}

function editPreset(name) {
  const p = _presets.find(x => x.name === name);
  if (!p) return;
  _editingName = name;
  document.getElementById('form-heading').textContent = 'Edit Preset';
  document.getElementById('f-name').value        = p.name;
  document.getElementById('f-name').disabled     = true;  // rename = delete + recreate
  document.getElementById('f-description').value = p.description || '';
  document.getElementById('f-model-path').value  = p.model_path || '';
  document.getElementById('cap-vision').checked  = (p.capabilities || []).includes('vision');
  document.getElementById('btn-delete').style.display = 'inline-block';
  document.getElementById('form-msg').textContent = '';
  _renderArgs(p.args || {});
  renderList();
}

function cancelForm() {
  _editingName = null;
  newPreset();
}

async function savePreset() {
  const msg = document.getElementById('form-msg');
  msg.style.color = '#777'; msg.textContent = 'Saving…';
  const name        = document.getElementById('f-name').value.trim();
  const description = document.getElementById('f-description').value.trim();
  const modelPath   = document.getElementById('f-model-path').value.trim();
  const args        = _collectArgs();
  const capabilities = ['text'];
  if (document.getElementById('cap-vision').checked) capabilities.push('vision');

  if (!name)      { msg.style.color = '#e44'; msg.textContent = 'Name is required.'; return; }
  if (!modelPath) { msg.style.color = '#e44'; msg.textContent = 'Model path is required.'; return; }

  const body = { name, description: description || null, model_path: modelPath, args, capabilities };
  try {
    if (_editingName) {
      await api('/llm-presets/' + encodeURIComponent(_editingName), 'PUT', body);
    } else {
      await api('/llm-presets', 'POST', body);
      _editingName = name;
    }
    msg.style.color = '#2a6'; msg.textContent = 'Saved.';
    await loadPresets();
    document.getElementById('f-name').disabled = true;
    document.getElementById('btn-delete').style.display = 'inline-block';
    document.getElementById('form-heading').textContent = 'Edit Preset';
  } catch (e) {
    msg.style.color = '#e44'; msg.textContent = 'Error: ' + _detail(e);
  }
}

function _detail(e) {
  try { return JSON.parse(e.message).detail || e.message; }
  catch { return e.message; }
}

async function deletePreset() {
  if (!_editingName) return;
  if (!confirm(`Delete preset "${_editingName}"? This cannot be undone.`)) return;
  try {
    await api('/llm-presets/' + encodeURIComponent(_editingName), 'DELETE');
    _editingName = null;
    await loadPresets();
    newPreset();
  } catch (e) {
    document.getElementById('form-msg').style.color = '#e44';
    document.getElementById('form-msg').textContent = 'Error: ' + _detail(e);
  }
}

loadPresets();
