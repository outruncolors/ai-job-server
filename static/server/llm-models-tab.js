// LLM Models sub-tab — CRUD over llama.cpp load presets (/v1/llm-presets).
// Ported from the former standalone /llm-presets/ page; functions renamed
// with the "Model" prefix to avoid collision with the Endpoints sub-tab.

let _modelPresets = [];
let _modelEditingName = null;  // null = creating new

async function loadModelPresets() {
  try {
    const data = await api('/llm-presets');
    _modelPresets = (data.presets || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    renderModelList();
  } catch (e) {
    document.getElementById('model-list').innerHTML =
      '<div style="color:#e44;font-size:0.75rem;">Error: ' + _escHtml(e.message) + '</div>';
  }
}

function renderModelList() {
  const el = document.getElementById('model-list');
  if (!el) return;
  if (_modelPresets.length === 0) {
    el.innerHTML = '<div class="empty" style="color:#444;font-size:0.75rem;padding:10px 0;">No models yet. Click + New to create one.</div>';
    return;
  }
  el.innerHTML = _modelPresets.map(p => {
    const sel  = _modelEditingName === p.name ? ' selected' : '';
    const desc = (p.description || '').trim();
    const sub  = desc || p.model_path || '';
    const caps = (p.capabilities || []).join(' · ');
    return '<div class="preset-item' + sel + '" onclick="editModelPreset(\'' + _escHtml(p.name) + '\')">' +
      '<div class="preset-item-name">' + _escHtml(p.name) + '</div>' +
      '<div class="preset-item-sub">'  + _escHtml(sub)    + '</div>' +
      '<div class="preset-item-caps">' + _escHtml(caps)   + '</div>' +
      '</div>';
  }).join('');
}

function _renderModelArgs(args) {
  const container = document.getElementById('model-args');
  const empty     = document.getElementById('model-args-empty');
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
    if      (v === true)  valDisplay = 'true';
    else if (v === false) valDisplay = 'false';
    else if (v === null)  valDisplay = 'null';
    else                  valDisplay = String(v);
    row.innerHTML =
      '<input type="text" class="arg-key"   placeholder="key (e.g. ctx_size)" value="' + _escHtml(k) + '">' +
      '<input type="text" class="arg-value" placeholder="value"               value="' + _escHtml(valDisplay) + '">' +
      '<button class="arg-remove" onclick="_removeModelArg(' + i + ')" title="Remove">×</button>';
    container.appendChild(row);
  });
}

function _collectModelArgs() {
  const out = {};
  for (const row of document.querySelectorAll('#model-args .arg-row')) {
    const k = row.querySelector('.arg-key').value.trim();
    if (!k) continue;
    const rawV = row.querySelector('.arg-value').value.trim();
    out[k] = _coerceModelArgValue(rawV);
  }
  return out;
}

function _coerceModelArgValue(raw) {
  if (raw === '' || raw.toLowerCase() === 'null') return null;
  if (raw.toLowerCase() === 'true')  return true;
  if (raw.toLowerCase() === 'false') return false;
  if (/^-?\d+$/.test(raw))           return parseInt(raw, 10);
  if (/^-?\d*\.\d+$/.test(raw))      return parseFloat(raw);
  return raw;
}

function _removeModelArg(idx) {
  const args = _collectModelArgs();
  const keys = Object.keys(args);
  if (idx < 0 || idx >= keys.length) return;
  delete args[keys[idx]];
  _renderModelArgs(args);
}

function addModelArg() {
  const args = _collectModelArgs();
  let i = 1;
  while (Object.prototype.hasOwnProperty.call(args, '_new_' + i)) i++;
  args['_new_' + i] = '';
  _renderModelArgs(args);
  const rows = document.querySelectorAll('#model-args .arg-row');
  if (rows.length) rows[rows.length - 1].querySelector('.arg-key').focus();
}

function newModelPreset() {
  _modelEditingName = null;
  document.getElementById('model-form-heading').textContent = 'New Model';
  document.getElementById('f-model-name').value        = '';
  document.getElementById('f-model-name').disabled     = false;
  document.getElementById('f-model-description').value = '';
  document.getElementById('f-model-path').value        = '';
  document.getElementById('model-cap-vision').checked  = false;
  document.getElementById('model-btn-delete').style.display = 'none';
  document.getElementById('model-form-msg').textContent = '';
  _renderModelArgs({});
  renderModelList();
  document.getElementById('f-model-name').focus();
}

function editModelPreset(name) {
  const p = _modelPresets.find(x => x.name === name);
  if (!p) return;
  _modelEditingName = name;
  document.getElementById('model-form-heading').textContent = 'Edit Model';
  document.getElementById('f-model-name').value        = p.name;
  document.getElementById('f-model-name').disabled     = true;  // rename = delete + recreate
  document.getElementById('f-model-description').value = p.description || '';
  document.getElementById('f-model-path').value        = p.model_path || '';
  document.getElementById('model-cap-vision').checked  = (p.capabilities || []).includes('vision');
  document.getElementById('model-btn-delete').style.display = 'inline-block';
  document.getElementById('model-form-msg').textContent = '';
  _renderModelArgs(p.args || {});
  renderModelList();
}

function cancelModelForm() {
  _modelEditingName = null;
  newModelPreset();
}

async function saveModelPreset() {
  const msg = document.getElementById('model-form-msg');
  msg.style.color = '#777'; msg.textContent = 'Saving…';
  const name        = document.getElementById('f-model-name').value.trim();
  const description = document.getElementById('f-model-description').value.trim();
  const modelPath   = document.getElementById('f-model-path').value.trim();
  const args        = _collectModelArgs();
  const capabilities = ['text'];
  if (document.getElementById('model-cap-vision').checked) capabilities.push('vision');

  if (!name)      { msg.style.color = '#e44'; msg.textContent = 'Name is required.'; return; }
  if (!modelPath) { msg.style.color = '#e44'; msg.textContent = 'Model path is required.'; return; }

  const body = { name, description: description || null, model_path: modelPath, args, capabilities };
  try {
    if (_modelEditingName) {
      await api('/llm-presets/' + encodeURIComponent(_modelEditingName), 'PUT', body);
    } else {
      await api('/llm-presets', 'POST', body);
      _modelEditingName = name;
    }
    msg.style.color = '#2a6'; msg.textContent = 'Saved.';
    await loadModelPresets();
    document.getElementById('f-model-name').disabled = true;
    document.getElementById('model-btn-delete').style.display = 'inline-block';
    document.getElementById('model-form-heading').textContent = 'Edit Model';
  } catch (e) {
    msg.style.color = '#e44'; msg.textContent = 'Error: ' + _modelDetail(e);
  }
}

function _modelDetail(e) {
  try { return JSON.parse(e.message).detail || e.message; }
  catch { return e.message; }
}

async function deleteModelPreset() {
  if (!_modelEditingName) return;
  if (!confirm('Delete model "' + _modelEditingName + '"? This cannot be undone.')) return;
  try {
    await api('/llm-presets/' + encodeURIComponent(_modelEditingName), 'DELETE');
    _modelEditingName = null;
    await loadModelPresets();
    newModelPreset();
  } catch (e) {
    const msg = document.getElementById('model-form-msg');
    msg.style.color = '#e44';
    msg.textContent = 'Error: ' + _modelDetail(e);
  }
}

async function onLlmModelsActive() {
  await loadModelPresets();
}
