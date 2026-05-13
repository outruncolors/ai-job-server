// Server tab — start/stop/restart ComfyUI, status polling, GPU display.

let _srvPollTimer = null;
let _srvBusy = false;

function initServerTab() {
  _updateEditorLinks();
}

function onServerTabActive() {
  loadServerStatus();
}

function _updateEditorLinks() {
  const url = 'http://' + window.location.hostname + ':8188';
  const link = document.getElementById('srv-ui-link');
  if (link) link.href = url;
}

function _logAction(msg, cls = '') {
  const log = document.getElementById('srv-action-log');
  if (!log) return;
  if (log.children.length === 1 && log.firstElementChild.style.color === 'rgb(42,42,42)') {
    log.innerHTML = '';
  }
  const ts  = new Date().toLocaleTimeString();
  const div = document.createElement('div');
  div.className = 'log-entry' + (cls ? ' ' + cls : '');
  div.innerHTML = '<span class="log-time">' + ts + '</span>' + _escHtml(msg);
  log.prepend(div);
  while (log.children.length > 20) log.lastChild.remove();
}

function _setSrvButtons(running, busy) {
  const start   = document.getElementById('srv-btn-start');
  const stop    = document.getElementById('srv-btn-stop');
  const restart = document.getElementById('srv-btn-restart');
  if (!start) return;
  start.disabled   = busy || running;
  stop.disabled    = busy || !running;
  restart.disabled = busy || !running;
}

function _fmtBytes(b) {
  if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(0) + ' MB';
  return b + ' B';
}

function _fmtUptime(s) {
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

function _renderServerStatus(status) {
  const indicator = document.getElementById('srv-indicator');
  const label     = document.getElementById('srv-label');
  const detail    = document.getElementById('srv-detail');
  const gpuDiv    = document.getElementById('srv-gpu-detail');
  const queueDiv  = document.getElementById('srv-queue');

  const running = status.running;

  indicator.className = 'indicator ' + (running ? 'running' : 'stopped');
  label.textContent   = running ? 'Running' : 'Stopped';

  const lines = [];
  if (status.pid)            lines.push('PID: ' + status.pid);
  if (status.uptime_seconds) lines.push('Uptime: ' + _fmtUptime(status.uptime_seconds));
  if (status.port)           lines.push('Port: ' + status.port);
  detail.textContent = lines.join(' · ');

  // GPU
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
        _fmtBytes(used) + ' / ' + _fmtBytes(total) + ' (' + pct + '%)' +
      '</div>';
  } else {
    gpuDiv.textContent = running ? 'Loading…' : '—';
  }

  queueDiv.textContent = running
    ? (status.queue_remaining != null ? status.queue_remaining + ' pending' : '—')
    : '—';
}

async function loadServerStatus() {
  try {
    const status = await api('/comfyui/status');
    _renderServerStatus(status);
    _setSrvButtons(status.running, _srvBusy);
  } catch (_) {}
}

async function doStart() {
  if (_srvBusy) return;
  _srvBusy = true;
  _setSrvButtons(false, true);
  _logAction('Starting ComfyUI…');
  toast('info', 'Starting ComfyUI — this may take up to 30s…', { id: 'srv-op', persistent: true });
  try {
    const status = await api('/comfyui/start', 'POST');
    toastDismiss('srv-op');
    toast('success', 'ComfyUI started');
    _logAction('ComfyUI started (PID ' + (status.pid || '?') + ')', 'log-ok');
    _renderServerStatus(status);
    _setSrvButtons(status.running, false);
  } catch (e) {
    toastDismiss('srv-op');
    toast('error', 'Start failed: ' + e.message);
    _logAction('Start failed: ' + e.message, 'log-err');
    _setSrvButtons(false, false);
  }
  _srvBusy = false;
}

async function doStop() {
  if (_srvBusy) return;
  _srvBusy = true;
  _setSrvButtons(true, true);
  _logAction('Stopping ComfyUI…');
  toast('warning', 'Stopping ComfyUI…', { id: 'srv-op', duration: 8000 });
  try {
    await api('/comfyui/stop', 'POST');
    toastDismiss('srv-op');
    toast('success', 'ComfyUI stopped');
    _logAction('ComfyUI stopped', 'log-ok');
    _renderServerStatus({ running: false });
    _setSrvButtons(false, false);
  } catch (e) {
    toastDismiss('srv-op');
    toast('error', 'Stop failed: ' + e.message);
    _logAction('Stop failed: ' + e.message, 'log-err');
  }
  _srvBusy = false;
  loadServerStatus();
}

async function doRestart() {
  if (_srvBusy) return;
  _srvBusy = true;
  _setSrvButtons(true, true);
  _logAction('Restarting ComfyUI…');
  toast('warning', 'Restarting ComfyUI…', { id: 'srv-op', persistent: true });
  try {
    const status = await api('/comfyui/restart', 'POST');
    toastDismiss('srv-op');
    toast('success', 'ComfyUI restarted');
    _logAction('ComfyUI restarted (PID ' + (status.pid || '?') + ')', 'log-ok');
    _renderServerStatus(status);
    _setSrvButtons(status.running, false);
  } catch (e) {
    toastDismiss('srv-op');
    toast('error', 'Restart failed: ' + e.message);
    _logAction('Restart failed: ' + e.message, 'log-err');
    _setSrvButtons(false, false);
  }
  _srvBusy = false;
}
