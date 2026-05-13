// Config tab — load and save ComfyUIConfig.

let _loadedConfig = null;

function onConfigTabActive() {
  if (!_loadedConfig) loadConfig();
}

async function loadConfig() {
  try {
    const cfg = await api('/comfyui/config');
    _loadedConfig = cfg;
    _populateForm(cfg);
  } catch (e) {
    const msg = document.getElementById('cfg-msg');
    if (msg) { msg.style.color = '#c44'; msg.textContent = 'Failed to load config: ' + e.message; }
  }
}

function _populateForm(cfg) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
  set('cfg-comfyui_root', cfg.comfyui_root);
  set('cfg-venv_python',  cfg.venv_python);
  set('cfg-host',         cfg.host);
  set('cfg-port',         cfg.port);
  set('cfg-vram_mode',    cfg.vram_mode);
  set('cfg-reserve_vram_gb', cfg.reserve_vram_gb);
  set('cfg-preview_method',  cfg.preview_method);
  set('cfg-output_dir',      cfg.output_dir);
  set('cfg-input_dir',       cfg.input_dir);
  set('cfg-models_root',     cfg.models_root);
  set('cfg-extra_model_paths_yaml', cfg.extra_model_paths_yaml);
  set('cfg-default_workflow', cfg.default_workflow || '');
  setChk('cfg-autostart',          cfg.autostart);
  setChk('cfg-use_sage_attention', cfg.use_sage_attention);
  set('cfg-extra_args', (cfg.extra_args || []).join('\n'));
}

function _collectForm() {
  const get    = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
  const getChk = id => { const el = document.getElementById(id); return el ? el.checked : false; };
  const extraArgsRaw = get('cfg-extra_args');
  const extra_args = extraArgsRaw
    ? extraArgsRaw.split('\n').map(s => s.trim()).filter(Boolean)
    : [];
  return {
    comfyui_root:  get('cfg-comfyui_root'),
    venv_python:   get('cfg-venv_python'),
    host:          get('cfg-host'),
    port:          parseInt(get('cfg-port'), 10) || 8188,
    autostart:     getChk('cfg-autostart'),
    use_sage_attention: getChk('cfg-use_sage_attention'),
    vram_mode:     get('cfg-vram_mode'),
    reserve_vram_gb: parseFloat(get('cfg-reserve_vram_gb')) || 1.0,
    preview_method: get('cfg-preview_method'),
    extra_args,
    models_root:   get('cfg-models_root'),
    output_dir:    get('cfg-output_dir'),
    input_dir:     get('cfg-input_dir'),
    extra_model_paths_yaml: get('cfg-extra_model_paths_yaml'),
    default_workflow: get('cfg-default_workflow') || null,
  };
}

async function saveConfig() {
  const msg = document.getElementById('cfg-msg');
  msg.textContent = 'Saving…'; msg.style.color = '#888';
  try {
    const cfg = await api('/comfyui/config', 'PUT', _collectForm());
    _loadedConfig = cfg;
    msg.style.color = '#2a6'; msg.textContent = 'Saved. Restart ComfyUI to apply changes.';
    toast('success', 'Config saved');
  } catch (e) {
    msg.style.color = '#c44'; msg.textContent = 'Save failed: ' + e.message;
    toast('error', 'Config save failed: ' + e.message);
  }
}
