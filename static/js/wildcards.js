// ── Wildcard resolution ──────────────────────────────────────────────────────

async function resolveWildcards(text) {
  if (!text || !text.includes('%%')) return text;
  const wildcards = await _wc_fetch();
  const map = Object.fromEntries(wildcards.map(w => [w.name.toLowerCase(), w]));
  return text.replace(/%%([^%]+)%%/g, (match, name) => {
    const wc = map[name.toLowerCase()];
    if (!wc || !wc.entries.length) return match;
    return _wc_pickWeighted(wc.entries);
  });
}

function _wc_pickWeighted(entries) {
  const total = entries.reduce((s, e) => s + (e.weight || 5), 0);
  let r = Math.random() * total;
  for (const e of entries) {
    r -= (e.weight || 5);
    if (r <= 0) return e.text;
  }
  return entries[entries.length - 1].text;
}

async function _wc_fetch() {
  try {
    const r = await fetch('/v1/wildcards');
    if (!r.ok) return [];
    const data = await r.json();
    return data.wildcards || [];
  } catch {
    return [];
  }
}

// ── Autocomplete ─────────────────────────────────────────────────────────────

const _wcAC = { el: null, input: null, items: [], sel: 0, names: [] };

function _wcEsc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _wcInitAC() {
  const el = document.createElement('div');
  Object.assign(el.style, {
    display: 'none', position: 'fixed', zIndex: '9999',
    background: '#161616', border: '1px solid #2a2a2a', borderRadius: '3px',
    maxHeight: '192px', overflowY: 'auto', minWidth: '160px',
    boxShadow: '0 4px 14px rgba(0,0,0,0.55)',
    fontFamily: 'monospace', fontSize: '0.78rem',
  });
  // Prevent textarea blur when clicking an item
  el.addEventListener('mousedown', e => e.preventDefault());
  el.addEventListener('click', e => {
    const item = e.target.closest('[data-idx]');
    if (item) _wcFill(_wcAC.items[+item.dataset.idx]);
  });
  el.addEventListener('mouseover', e => {
    const item = e.target.closest('[data-idx]');
    if (item) { _wcAC.sel = +item.dataset.idx; _wcRender(); }
  });
  document.body.appendChild(el);
  _wcAC.el = el;

  document.addEventListener('input',   _wcOnInput,   true);
  document.addEventListener('keydown', _wcOnKeydown, true);
  document.addEventListener('blur', e => {
    if (!_wcAC.el || _wcAC.el.style.display === 'none') return;
    if (e.target === _wcAC.input) setTimeout(_wcHide, 150);
  }, true);

  // Pre-fetch names for autocomplete
  _wc_fetch().then(wcs => { _wcAC.names = wcs.map(w => w.name); });
}

function _wcOnInput(e) {
  const el = e.target;
  if (el.tagName !== 'TEXTAREA' && !(el.tagName === 'INPUT' && el.type === 'text')) return;
  const before = el.value.slice(0, el.selectionStart);
  const m = before.match(/%%([^%\n]*)$/);
  if (!m) { _wcHide(); return; }
  if (!_wcAC.names.length) return;
  const q = m[1].toLowerCase();
  const matches = _wcAC.names.filter(n => !q || n.toLowerCase().startsWith(q));
  if (!matches.length) { _wcHide(); return; }
  _wcAC.input = el;
  _wcAC.items = matches;
  _wcAC.sel   = 0;
  _wcRender();
  _wcPosition(el);
}

function _wcOnKeydown(e) {
  if (!_wcAC.el || _wcAC.el.style.display === 'none') return;
  if      (e.key === 'ArrowDown')              { e.preventDefault(); _wcMove(1); }
  else if (e.key === 'ArrowUp')                { e.preventDefault(); _wcMove(-1); }
  else if (e.key === 'Tab' || e.key === 'Enter') {
    if (_wcAC.items.length) { e.preventDefault(); _wcFill(_wcAC.items[_wcAC.sel]); }
  }
  else if (e.key === 'Escape')                 { e.stopPropagation(); _wcHide(); }
}

function _wcMove(dir) {
  _wcAC.sel = Math.max(0, Math.min(_wcAC.items.length - 1, _wcAC.sel + dir));
  _wcRender();
}

function _wcRender() {
  _wcAC.el.innerHTML = _wcAC.items.map((name, i) => {
    const active = i === _wcAC.sel;
    return `<div data-idx="${i}" style="padding:6px 10px;cursor:pointer;white-space:nowrap;` +
      `color:${active ? '#6c6' : '#4a8'};background:${active ? '#1a2a1a' : 'transparent'};">` +
      `%%${_wcEsc(name)}%%</div>`;
  }).join('');
  const sel = _wcAC.el.children[_wcAC.sel];
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function _wcPosition(input) {
  const rect = input.getBoundingClientRect();
  const el   = _wcAC.el;
  el.style.left     = rect.left + 'px';
  el.style.minWidth = Math.min(Math.max(160, Math.floor(rect.width * 0.5)), 280) + 'px';
  el.style.display  = 'block';
  // Flip above input when space below is tight
  if (window.innerHeight - rect.bottom < 100 && rect.top > 200) {
    el.style.top    = '';
    el.style.bottom = (window.innerHeight - rect.top + 3) + 'px';
  } else {
    el.style.bottom = '';
    el.style.top    = (rect.bottom + 3) + 'px';
  }
}

function _wcHide() {
  if (_wcAC.el) _wcAC.el.style.display = 'none';
  _wcAC.input = null;
}

function _wcFill(name) {
  const input = _wcAC.input;
  if (!input) return;
  const val    = input.value;
  const pos    = input.selectionStart;
  const before = val.slice(0, pos);
  const m      = before.match(/%%([^%\n]*)$/);
  if (!m) return;
  const start  = pos - m[0].length;
  input.value  = val.slice(0, start) + '%%' + name + '%% ' + val.slice(pos);
  const newPos = start + name.length + 5;
  input.setSelectionRange(newPos, newPos);
  _wcHide();
  input.focus();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _wcInitAC);
} else {
  _wcInitAC();
}
