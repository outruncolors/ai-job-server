// ComfyUI tab — start/stop/restart ComfyUI, status polling, GPU display.
// Lives on the Server page; same backend routes as before (/v1/comfyui/*).

let _comfyBusy = false;

function initComfyTab() {
  _updateComfyEditorLinks();
}

function onComfyTabActive() {
  loadComfyStatus();
  if (!_loadedComfyCfg) loadComfyConfig();
}

function _updateComfyEditorLinks() {
  const url = 'http://' + window.location.hostname + ':8188';
  document.querySelectorAll('.comfy-editor-link').forEach(el => { el.href = url; });
}

function _logComfyAction(msg, cls) {
  const log = document.getElementById('comfy-action-log');
  if (!log) return;
  if (log.children.length === 1 && log.firstElementChild.style.color === 'rgb(42, 42, 42)') {
    log.innerHTML = '';
  }
  const ts  = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = 'log-entry' + (cls ? ' ' + cls : '');
  div.innerHTML = '<span class="log-time">' + ts + '</span>' + _escHtml(msg);
  log.prepend(div);
  while (log.children.length > 20) log.lastChild.remove();
}

function _setComfyButtons(running, busy) {
  const start   = document.getElementById('comfy-btn-start');
  const stop    = document.getElementById('comfy-btn-stop');
  const restart = document.getElementById('comfy-btn-restart');
  if (!start) return;
  start.disabled   = busy || running;
  stop.disabled    = busy || !running;
  restart.disabled = busy || !running;
}

function _fmtComfyBytes(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(0) + ' MB';
  return b + ' B';
}

function _fmtComfyUptime(s) {
  if (s == null) return '—';
  s = Math.floor(s);
  const h = Math.floor(s / 3600); s %= 3600;
  const m = Math.floor(s / 60);   s %= 60;
  const parts = [];
  if (h) parts.push(h + 'h');
  if (m) parts.push(m + 'm');
  parts.push(s + 's');
  return parts.join(' ');
}

function _renderComfyStatus(status) {
  const indicator = document.getElementById('comfy-indicator');
  const label     = document.getElementById('comfy-label');
  const detail    = document.getElementById('comfy-detail');
  const gpuDiv    = document.getElementById('comfy-gpu-detail');
  const queueDiv  = document.getElementById('comfy-queue');
  if (!indicator) return;

  const running = status.running;
  indicator.className = 'indicator ' + (running ? 'running' : 'stopped');
  label.textContent   = running ? 'Running' : 'Stopped';

  const lines = [];
  if (status.pid)            lines.push('PID: ' + status.pid);
  if (status.uptime_seconds) lines.push('Uptime: ' + _fmtComfyUptime(status.uptime_seconds));
  if (status.port)           lines.push('Port: ' + status.port);
  detail.textContent = lines.join(' · ');

  const gpu = status.gpu;
  if (gpu && running) {
    const used  = gpu.vram_total - gpu.vram_free;
    const total = gpu.vram_total;
    const pct   = total > 0 ? Math.round(used / total * 100) : 0;
    const barCls = pct >= 90 ? 'danger' : pct >= 75 ? 'warn' : '';
    gpuDiv.innerHTML =
      '<div style="color:#888;font-size:0.78rem;">' + _escHtml(gpu.name || 'GPU') + '</div>' +
      '<div class="vram-bar-wrap"><div class="vram-bar ' + barCls + '" style="width:' + pct + '%"></div></div>' +
      '<div style="font-size:0.74rem;color:#555;">' +
        _fmtComfyBytes(used) + ' / ' + _fmtComfyBytes(total) + ' (' + pct + '%)' +
      '</div>';
  } else {
    gpuDiv.textContent = running ? 'Loading…' : '—';
  }

  if (queueDiv) {
    queueDiv.textContent = running
      ? (status.queue_remaining != null ? status.queue_remaining + ' pending' : '—')
      : '—';
  }
}

async function loadComfyStatus() {
  try {
    const status = await api('/comfyui/status');
    _renderComfyStatus(status);
    _setComfyButtons(status.running, _comfyBusy);
  } catch (_) {}
}

async function comfyStart() {
  if (_comfyBusy) return;
  _comfyBusy = true;
  _setComfyButtons(false, true);
  _logComfyAction('Starting ComfyUI…');
  toast('info', 'Starting ComfyUI — this may take up to 30s…', { id: 'comfy-op', persistent: true });
  try {
    const status = await api('/comfyui/start', 'POST');
    toastDismiss('comfy-op');
    toast('success', 'ComfyUI started');
    _logComfyAction('ComfyUI started (PID ' + (status.pid || '?') + ')', 'log-ok');
    _renderComfyStatus(status);
    _setComfyButtons(status.running, false);
  } catch (e) {
    toastDismiss('comfy-op');
    toast('error', 'Start failed: ' + e.message);
    _logComfyAction('Start failed: ' + e.message, 'log-err');
    _setComfyButtons(false, false);
  }
  _comfyBusy = false;
}

async function comfyStop() {
  if (_comfyBusy) return;
  _comfyBusy = true;
  _setComfyButtons(true, true);
  _logComfyAction('Stopping ComfyUI…');
  toast('warning', 'Stopping ComfyUI…', { id: 'comfy-op', duration: 8000 });
  try {
    await api('/comfyui/stop', 'POST');
    toastDismiss('comfy-op');
    toast('success', 'ComfyUI stopped');
    _logComfyAction('ComfyUI stopped', 'log-ok');
    _renderComfyStatus({ running: false });
    _setComfyButtons(false, false);
  } catch (e) {
    toastDismiss('comfy-op');
    toast('error', 'Stop failed: ' + e.message);
    _logComfyAction('Stop failed: ' + e.message, 'log-err');
  }
  _comfyBusy = false;
  loadComfyStatus();
}

async function comfyRestart() {
  if (_comfyBusy) return;
  _comfyBusy = true;
  _setComfyButtons(true, true);
  _logComfyAction('Restarting ComfyUI…');
  toast('warning', 'Restarting ComfyUI…', { id: 'comfy-op', persistent: true });
  try {
    const status = await api('/comfyui/restart', 'POST');
    toastDismiss('comfy-op');
    toast('success', 'ComfyUI restarted');
    _logComfyAction('ComfyUI restarted (PID ' + (status.pid || '?') + ')', 'log-ok');
    _renderComfyStatus(status);
    _setComfyButtons(status.running, false);
  } catch (e) {
    toastDismiss('comfy-op');
    toast('error', 'Restart failed: ' + e.message);
    _logComfyAction('Restart failed: ' + e.message, 'log-err');
    _setComfyButtons(false, false);
  }
  _comfyBusy = false;
}

// ── Config ────────────────────────────────────────────────────────────────────

let _loadedComfyCfg = null;

async function loadComfyConfig() {
  try {
    const cfg = await api('/comfyui/config');
    _loadedComfyCfg = cfg;
    _populateComfyCfgForm(cfg);
  } catch (e) {
    const msg = document.getElementById('comfy-cfg-msg');
    if (msg) { msg.style.color = '#c44'; msg.textContent = 'Failed to load config: ' + e.message; }
  }
}

function _populateComfyCfgForm(cfg) {
  const set    = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  const setChk = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
  set('cfg-comfyui_root',          cfg.comfyui_root);
  set('cfg-venv_python',           cfg.venv_python);
  set('cfg-host',                  cfg.host);
  set('cfg-port',                  cfg.port);
  set('cfg-vram_mode',             cfg.vram_mode);
  set('cfg-reserve_vram_gb',       cfg.reserve_vram_gb);
  set('cfg-preview_method',        cfg.preview_method);
  set('cfg-output_dir',            cfg.output_dir);
  set('cfg-input_dir',             cfg.input_dir);
  set('cfg-models_root',           cfg.models_root);
  set('cfg-extra_model_paths_yaml', cfg.extra_model_paths_yaml);
  set('cfg-default_workflow',      cfg.default_workflow || '');
  setChk('cfg-autostart',          cfg.autostart);
  setChk('cfg-use_sage_attention', cfg.use_sage_attention);
  set('cfg-extra_args',            (cfg.extra_args || []).join('\n'));
}

function _collectComfyCfgForm() {
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
    preview_method:  get('cfg-preview_method'),
    extra_args,
    models_root:   get('cfg-models_root'),
    output_dir:    get('cfg-output_dir'),
    input_dir:     get('cfg-input_dir'),
    extra_model_paths_yaml: get('cfg-extra_model_paths_yaml'),
    default_workflow: get('cfg-default_workflow') || null,
  };
}

async function saveComfyConfig() {
  const msg = document.getElementById('comfy-cfg-msg');
  msg.textContent = 'Saving…'; msg.style.color = '#888';
  try {
    const cfg = await api('/comfyui/config', 'PUT', _collectComfyCfgForm());
    _loadedComfyCfg = cfg;
    msg.style.color = '#2a6'; msg.textContent = 'Saved. Restart ComfyUI to apply changes.';
    toast('success', 'Config saved');
  } catch (e) {
    msg.style.color = '#c44'; msg.textContent = 'Save failed: ' + e.message;
    toast('error', 'Config save failed: ' + e.message);
  }
}
