  // ── Utilities ──────────────────────────────────────────────────────────────

  async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch('/v1' + path, opts);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }

  function _escHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

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

  // ── Toast system ───────────────────────────────────────────────────────────

  const _toasts = new Map(); // id → { el, timerId }
  let _toastSeq = 0;

  function toast(type, message, opts = {}) {
    const id = opts.id || ('t' + (++_toastSeq));

    const existing = _toasts.get(id);
    if (existing) {
      clearTimeout(existing.timerId);
      // Update content in-place to avoid fade collision
      existing.el.className = 'toast toast-' + type;
      existing.el.querySelector('.toast-msg').textContent = message;
      const cdEl = existing.el.querySelector('.toast-countdown');
      if (cdEl && !opts.countdown) cdEl.textContent = '';
      if (!cdEl && opts.countdown) {
        const d = document.createElement('span');
        d.className = 'toast-countdown';
        d.id = 'tc-' + id;
        existing.el.appendChild(d);
      }
      if (!opts.persistent) {
        const dur = opts.duration ?? _toastDuration(type);
        existing.timerId = setTimeout(() => toastDismiss(id), dur);
      } else {
        existing.timerId = null;
      }
      return id;
    }

    const el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.innerHTML =
      '<span class="toast-dismiss" onclick="toastDismiss(\'' + id + '\')">&#x2715;</span>' +
      '<span class="toast-msg">' + _escHtml(message) + '</span>' +
      (opts.countdown ? '<span class="toast-countdown" id="tc-' + id + '"></span>' : '');
    document.getElementById('toast-stack').appendChild(el);

    let timerId = null;
    if (!opts.persistent) {
      const dur = opts.duration ?? _toastDuration(type);
      timerId = setTimeout(() => toastDismiss(id), dur);
    }
    _toasts.set(id, { el, timerId });
    return id;
  }

  function _toastDuration(type) {
    return type === 'success' ? 3500 : type === 'error' ? 6000 : 4500;
  }

  function toastDismiss(id) {
    const entry = _toasts.get(id);
    if (!entry) return;
    clearTimeout(entry.timerId);
    entry.el.style.opacity = '0';
    setTimeout(() => { entry.el.remove(); _toasts.delete(id); }, 300);
  }

  function toastSetCountdown(id, text) {
    const el = document.getElementById('tc-' + id);
    if (el) el.textContent = text;
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

  // ── Auto-refresh & init ────────────────────────────────────────────────────

  const _statsInterval = setInterval(loadStats, 5000);

  window.addEventListener('beforeunload', () => {
    clearInterval(_statsInterval);
    clearInterval(_reconnCdTimer);
    clearTimeout(_reconnTimer);
  });

  loadStats();
