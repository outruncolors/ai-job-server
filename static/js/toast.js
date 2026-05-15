/* Toast notification system. Auto-injects #toast-stack on first call.
   API: toast(type, message, opts)  →  id string
        toastDismiss(id)
        toastSetCountdown(id, text) */

const _toasts = new Map();
let _toastSeq = 0;

function _ensureStack() {
  if (!document.getElementById('toast-stack')) {
    const s = document.createElement('div');
    s.id = 'toast-stack';
    document.body.appendChild(s);
  }
}

function _toastDuration(type) {
  return type === 'success' ? 3500 : type === 'error' ? 6000 : 4500;
}

function toast(type, message, opts = {}) {
  _ensureStack();
  const id = opts.id || ('t' + (++_toastSeq));

  const existing = _toasts.get(id);
  if (existing) {
    clearTimeout(existing.timerId);
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
    '<span class="toast-dismiss" onclick="toastDismiss(\'' + _escHtml(id) + '\')">&#x2715;</span>' +
    '<span class="toast-msg">' + _escHtml(message) + '</span>' +
    (opts.countdown ? '<span class="toast-countdown" id="tc-' + _escHtml(id) + '"></span>' : '');
  document.getElementById('toast-stack').appendChild(el);

  let timerId = null;
  if (!opts.persistent) {
    const dur = opts.duration ?? _toastDuration(type);
    timerId = setTimeout(() => toastDismiss(id), dur);
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
