// Shared utilities + tab initialization for the Image page.
// Loaded last so tab modules can reference these as globals from event handlers.

// ── API helper ──────────────────────────────────────────────────────────────

function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  return fetch('/v1' + path, opts).then(r => {
    if (!r.ok) return r.text().then(t => { throw new Error(t); });
    return r.json();
  });
}

function _escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Toast system ─────────────────────────────────────────────────────────────

const _toasts = new Map();
let _toastSeq = 0;

function _toastDur(type) {
  return type === 'success' ? 3500 : type === 'error' ? 6000 : 4500;
}

function toast(type, message, opts = {}) {
  const id = opts.id || ('t' + (++_toastSeq));
  const existing = _toasts.get(id);
  if (existing) {
    clearTimeout(existing.timerId);
    existing.el.className = 'toast toast-' + type;
    existing.el.querySelector('.toast-msg').textContent = message;
    if (!opts.persistent) {
      existing.timerId = setTimeout(() => toastDismiss(id), opts.duration ?? _toastDur(type));
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
    timerId = setTimeout(() => toastDismiss(id), opts.duration ?? _toastDur(type));
  }
  _toasts.set(id, { el, timerId });
  return id;
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

// ── Init ─────────────────────────────────────────────────────────────────────

initGenerateTab();
