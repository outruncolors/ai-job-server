  // ── Utilities ──────────────────────────────────────────────────────────────


  function _fmtBytes(b) {
    if (b >= 1e9) return (b / 1e9).toFixed(1) + ' GB';
    if (b >= 1e6) return (b / 1e6).toFixed(0) + ' MB';
    return (b / 1e3).toFixed(0) + ' KB';
  }

  function _fmtUptime(s) {
    s = Math.floor(s);
    const d = Math.floor(s / 86400); s %= 86400;
    const h = Math.floor(s / 3600);  s %= 3600;
    const m = Math.floor(s / 60);    s %= 60;
    const parts = [];
    if (d) parts.push(d + 'd');
    if (h) parts.push(h + 'h');
    if (m) parts.push(m + 'm');
    parts.push(s + 's');
    return parts.join(' ');
  }


  // ── Stats rendering ────────────────────────────────────────────────────────

  function _setBar(barId, pct) {
    const el = document.getElementById(barId);
    el.style.width = Math.min(pct, 100) + '%';
    el.classList.toggle('warn',   pct >= 75 && pct < 90);
    el.classList.toggle('danger', pct >= 90);
  }

  function renderStats(s) {
    _setBar('bar-cpu',  s.cpu_percent);
    document.getElementById('val-cpu').textContent = s.cpu_percent.toFixed(1) + '%';

    _setBar('bar-mem', s.memory.percent);
    document.getElementById('val-mem').textContent =
      _fmtBytes(s.memory.used) + ' / ' + _fmtBytes(s.memory.total);

    _setBar('bar-disk', s.disk.percent);
    document.getElementById('val-disk').textContent =
      _fmtBytes(s.disk.used) + ' / ' + _fmtBytes(s.disk.total);

    document.getElementById('cnt-queued').textContent  = s.jobs.queued;
    document.getElementById('cnt-running').textContent = s.jobs.running;
    document.getElementById('cnt-done').textContent    = s.jobs.done;
    document.getElementById('cnt-failed').textContent  = s.jobs.failed;

    document.getElementById('info-hostname').textContent = s.hostname;
    document.getElementById('info-python').textContent   = s.python_version;
    document.getElementById('info-uptime').textContent   = _fmtUptime(s.uptime_seconds);
  }

  async function loadStats() {
    if (_reconnState !== 'IDLE') return;
    try {
      renderStats(await api('/server/stats'));
    } catch (_) { /* silently tolerate during reconnect */ }
  }

  // ── Reconnection state machine ─────────────────────────────────────────────

  const FIB = [1, 1, 2, 3, 5, 8, 13, 21, 34, 55];
  const MAX_ATTEMPTS = FIB.length;
  const RECONNECT_TOAST = 'reconnect-toast';

  let _reconnState = 'IDLE'; // IDLE | RECONNECTING
  let _reconnAttempt = 0;
  let _reconnTimer = null;
  let _reconnCdTimer = null;

  function _logAction(msg, cls = '') {
    const log = document.getElementById('action-log');
    if (log.children.length === 1 && log.firstElementChild.style.color === 'rgb(42, 42, 42)') {
      log.innerHTML = ''; // clear placeholder
    }
    const ts = new Date().toLocaleTimeString();
    const div = document.createElement('div');
    div.className = 'log-entry' + (cls ? ' ' + cls : '');
    div.innerHTML = '<span class="log-time">' + ts + '</span>' + _escHtml(msg);
    log.prepend(div);
    while (log.children.length > 20) log.lastChild.remove();
  }

  async function doRestart() {
    if (_reconnState !== 'IDLE') return;
    const btn = document.getElementById('restart-btn');
    btn.disabled = true;
    _logAction('Restart requested');
    toast('warning', 'Sending restart command…', { duration: 2000 });
    try {
      await api('/server/restart', 'POST');
      _reconnState = 'RECONNECTING';
      _reconnAttempt = 0;
      _logAction('Restart accepted — waiting for server to come back');
      // Give execv time to fire before we start polling for UP
      _reconnTimer = setTimeout(_startReconnect, 1200);
    } catch (e) {
      btn.disabled = false;
      _reconnState = 'IDLE';
      toast('error', 'Restart failed: ' + e.message);
      _logAction('Restart failed: ' + e.message, 'log-err');
    }
  }

  function _startReconnect() {
    if (_reconnAttempt >= MAX_ATTEMPTS) {
      clearInterval(_reconnCdTimer);
      _reconnCdTimer = null;
      toastDismiss(RECONNECT_TOAST);
      const giveUpId = toast('error', 'Server appears to be down after ' + MAX_ATTEMPTS + ' attempts.', { persistent: true });
      const entry = _toasts.get(giveUpId);
      if (entry) {
        const btn = document.createElement('button');
        btn.textContent = 'Retry';
        btn.className = 'secondary';
        btn.style.cssText = 'margin-top:8px;padding:3px 10px;font-size:0.72rem;display:block;';
        btn.onclick = () => {
          toastDismiss(giveUpId);
          _reconnAttempt = 0;
          _reconnState = 'RECONNECTING';
          _startReconnect();
        };
        entry.el.appendChild(btn);
      }
      document.getElementById('restart-btn').disabled = false;
      _reconnState = 'IDLE';
      _logAction('Gave up reconnecting after ' + MAX_ATTEMPTS + ' attempts', 'log-err');
      return;
    }

    const waitSecs = FIB[_reconnAttempt];
    toast('warning',
      'Reconnecting… attempt ' + (_reconnAttempt + 1) + ' of ' + MAX_ATTEMPTS,
      { id: RECONNECT_TOAST, persistent: true, countdown: true }
    );
    _logAction('Reconnect attempt ' + (_reconnAttempt + 1) + ' (wait ' + waitSecs + 's)');

    clearInterval(_reconnCdTimer);
    let remaining = waitSecs;
    toastSetCountdown(RECONNECT_TOAST, 'Next attempt in ' + remaining + 's…');
    _reconnCdTimer = setInterval(() => {
      remaining--;
      if (remaining > 0) {
        toastSetCountdown(RECONNECT_TOAST, 'Next attempt in ' + remaining + 's…');
      } else {
        clearInterval(_reconnCdTimer);
        _reconnCdTimer = null;
        toastSetCountdown(RECONNECT_TOAST, 'Connecting…');
      }
    }, 1000);

    _reconnTimer = setTimeout(_tryReconnect, waitSecs * 1000);
  }

  async function _tryReconnect() {
    clearInterval(_reconnCdTimer);
    _reconnCdTimer = null;
    try {
      const r = await fetch('/health');
      if (!r.ok) throw new Error('non-ok');
      toastDismiss(RECONNECT_TOAST);
      toast('success', 'Reconnected!', { duration: 4000 });
      _logAction('Reconnected successfully', 'log-ok');
      document.getElementById('restart-btn').disabled = false;
      _reconnState = 'IDLE';
      loadStats();
    } catch (_) {
      _reconnAttempt++;
      _startReconnect();
    }
  }

  // ── Tab switching ──────────────────────────────────────────────────────────

  let _activeTab = 'web';

  function switchTab(name) {
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
    const pane = document.getElementById('tab-' + name);
    const btn  = document.querySelector('.tab-btn[data-tab="' + name + '"]');
    if (pane) pane.classList.add('active');
    if (btn)  btn.classList.add('active');
    _activeTab = name;
    if (name === 'comfyui') onComfyTabActive();
    if (name === 'llm')     onLlmTabActive();
  }

  // ── Auto-refresh & init ────────────────────────────────────────────────────

  const _statsInterval = setInterval(loadStats, 5000);

  window.addEventListener('beforeunload', () => {
    clearInterval(_statsInterval);
    clearInterval(_reconnCdTimer);
    clearTimeout(_reconnTimer);
  });

  initComfyTab();
  initLlmTab();
  loadStats();
