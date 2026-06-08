// ── Prompt-token autocomplete: {{wc.}} / {{var.}} / {{ctx.}} ──────────────────
//
// One popover for every prompt-bearing field. Resolution is server-side now, so
// this module only helps authors *insert* tokens and preview their metadata.
//
// Trigger: type `{{`. Stages: namespace chooser → wildcard / variable / context.
//   {{        → choose wc. / var. / ctx.
//   {{wc.x    → wildcards starting with "x"          (shows description)
//   {{var.x   → in-scope variables starting with "x" (shows current value)
//   {{ctx.x   → context items starting with "x"       (shows description + tags)
//
// Variable scope: a page registers the in-scope variables for its fields via
//   window.PromptTokens.registerVariables(scopeEl, varsArrayOrMapOrFn)
// where each var is {name, value?, description?}. A function form is read live
// (so an editor reflecting the DOM stays fresh). The popover uses the nearest
// registered ancestor of the focused field; pages with no scope offer no vars
// (a typed {{var.x}} then falls back to its literal at the server).

const _NS = [
  { ns: 'wc',  desc: 'wildcard' },
  { ns: 'var', desc: 'variable' },
  { ns: 'ctx', desc: 'context item' },
];

const _ptAC = {
  el: null, input: null, items: [], sel: 0,
  stage: 'ns',        // 'ns' | 'wc' | 'var' | 'ctx'
  wcs: [], ctxs: [],  // prefetched library metadata
};

const _ptScopes = [];  // [{ el, vars: Array | Function }]

function _ptEsc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

window.PromptTokens = {
  registerVariables(scopeEl, vars) {
    if (!scopeEl) return;
    const norm = (typeof vars === 'function' || Array.isArray(vars))
      ? vars
      : Object.entries(vars || {}).map(([name, value]) => ({ name, value }));
    const existing = _ptScopes.find(s => s.el === scopeEl);
    if (existing) existing.vars = norm;
    else _ptScopes.push({ el: scopeEl, vars: norm });
  },
  unregisterVariables(scopeEl) {
    const i = _ptScopes.findIndex(s => s.el === scopeEl);
    if (i >= 0) _ptScopes.splice(i, 1);
  },
};

function _ptVarsFor(input) {
  // deepest registered scope that contains the focused field
  let best = null;
  for (const s of _ptScopes) {
    if (s.el && s.el.contains(input) && (!best || best.el.contains(s.el))) best = s;
  }
  if (!best) return [];
  const v = typeof best.vars === 'function' ? (best.vars() || []) : best.vars;
  return v.map(x => (typeof x === 'string' ? { name: x } : x));
}

function _ptInit() {
  const el = document.createElement('div');
  Object.assign(el.style, {
    display: 'none', position: 'fixed', zIndex: '9999',
    background: '#161616', border: '1px solid #2a2a2a', borderRadius: '3px',
    maxHeight: '192px', overflowY: 'auto', minWidth: '160px',
    boxShadow: '0 4px 14px rgba(0,0,0,0.55)',
    fontFamily: 'monospace', fontSize: '0.78rem',
  });
  el.addEventListener('mousedown', e => e.preventDefault());
  el.addEventListener('click', e => {
    const item = e.target.closest('[data-idx]');
    if (item) _ptPick(_ptAC.items[+item.dataset.idx]);
  });
  el.addEventListener('mouseover', e => {
    const item = e.target.closest('[data-idx]');
    if (item) { _ptAC.sel = +item.dataset.idx; _ptRender(); }
  });
  document.body.appendChild(el);
  _ptAC.el = el;

  document.addEventListener('input',   _ptOnInput,   true);
  document.addEventListener('keydown', _ptOnKeydown, true);
  document.addEventListener('blur', e => {
    if (!_ptAC.el || _ptAC.el.style.display === 'none') return;
    if (e.target === _ptAC.input) setTimeout(_ptHide, 150);
  }, true);

  _ptFetch();
}

async function _ptFetch() {
  try {
    const r = await fetch('/v1/wildcards');
    if (r.ok) _ptAC.wcs = ((await r.json()).wildcards || [])
      .map(w => ({ name: w.name, description: w.description || '' }));
  } catch (_) {}
  try {
    const r = await fetch('/v1/context-items');
    if (r.ok) _ptAC.ctxs = ((await r.json()).items || [])
      .map(c => ({ name: c.name, description: c.description || '', tags: c.tags || [] }));
  } catch (_) {}
}

function _ptOnInput(e) {
  const el = e.target;
  if (el.tagName !== 'TEXTAREA' && !(el.tagName === 'INPUT' && el.type === 'text')) return;
  const before = el.value.slice(0, el.selectionStart);
  const m = before.match(/\{\{\s*([^{}\n]*)$/);
  if (!m) { _ptHide(); return; }
  const frag = m[1];
  const dot = frag.indexOf('.');
  let items;
  if (dot === -1) {
    _ptAC.stage = 'ns';
    const q = frag.toLowerCase();
    items = _NS.filter(n => !q || n.ns.startsWith(q))
      .map(n => ({ kind: 'ns', ns: n.ns, name: n.ns, description: n.desc }));
  } else {
    const ns = frag.slice(0, dot).toLowerCase();
    const q = frag.slice(dot + 1).toLowerCase();
    if (ns === 'wc') {
      _ptAC.stage = 'wc';
      items = _ptAC.wcs.filter(w => !q || w.name.toLowerCase().startsWith(q))
        .map(w => ({ kind: 'wc', name: w.name, description: w.description }));
    } else if (ns === 'ctx') {
      _ptAC.stage = 'ctx';
      items = _ptAC.ctxs.filter(c => !q || c.name.toLowerCase().startsWith(q))
        .map(c => ({ kind: 'ctx', name: c.name, description: c.description, tags: c.tags }));
    } else if (ns === 'var') {
      _ptAC.stage = 'var';
      items = _ptVarsFor(el).filter(v => v.name && (!q || v.name.toLowerCase().startsWith(q)))
        .map(v => ({ kind: 'var', name: v.name, value: v.value, description: v.description }));
    } else { _ptHide(); return; }
  }
  if (!items.length) { _ptHide(); return; }
  _ptAC.input = el; _ptAC.items = items; _ptAC.sel = 0;
  _ptRender();
  _ptPosition(el);
}

function _ptOnKeydown(e) {
  if (!_ptAC.el || _ptAC.el.style.display === 'none') return;
  // Capture-phase: stop the keys we own from reaching the page's own handlers
  // (e.g. Prattletale's Enter-to-send on #pt-input) while the popover is open.
  if      (e.key === 'ArrowDown')                { e.preventDefault(); e.stopPropagation(); _ptMove(1); }
  else if (e.key === 'ArrowUp')                  { e.preventDefault(); e.stopPropagation(); _ptMove(-1); }
  else if (e.key === 'Tab' || e.key === 'Enter') {
    if (_ptAC.items.length) { e.preventDefault(); e.stopPropagation(); _ptPick(_ptAC.items[_ptAC.sel]); }
  }
  else if (e.key === 'Escape')                   { e.preventDefault(); e.stopPropagation(); _ptHide(); }
}

function _ptMove(dir) {
  _ptAC.sel = Math.max(0, Math.min(_ptAC.items.length - 1, _ptAC.sel + dir));
  _ptRender();
}

function _ptMeta(text) {
  return `<div style="color:#666;font-size:0.68rem;margin-top:1px;overflow:hidden;`
    + `text-overflow:ellipsis;max-width:260px;">${_ptEsc(text)}</div>`;
}

function _ptRender() {
  _ptAC.el.innerHTML = _ptAC.items.map((it, i) => {
    const active = i === _ptAC.sel;
    let label = '', meta = '';
    if (it.kind === 'ns') {
      label = '{{' + _ptEsc(it.name) + '.…}}';
      meta = _ptMeta(it.description);
    } else if (it.kind === 'wc') {
      label = '{{wc.' + _ptEsc(it.name) + '}}';
      if (it.description) meta = _ptMeta(it.description);
    } else if (it.kind === 'var') {
      label = '{{var.' + _ptEsc(it.name) + '}}';
      const v = (it.value !== undefined && it.value !== null && it.value !== '')
        ? '= ' + it.value : (it.description || '');
      if (v) meta = _ptMeta(v);
    } else if (it.kind === 'ctx') {
      label = '{{ctx.' + _ptEsc(it.name) + '}}';
      const tagStr = (it.tags && it.tags.length) ? '  #' + it.tags.join(' #') : '';
      const d = ((it.description || '') + tagStr).trim();
      if (d) meta = _ptMeta(d);
    }
    return `<div data-idx="${i}" style="padding:6px 10px;cursor:pointer;white-space:nowrap;`
      + `color:${active ? '#6c6' : '#4a8'};background:${active ? '#1a2a1a' : 'transparent'};">`
      + `${label}${meta}</div>`;
  }).join('');
  const sel = _ptAC.el.children[_ptAC.sel];
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function _ptPosition(input) {
  const rect = input.getBoundingClientRect();
  const el = _ptAC.el;
  el.style.left = rect.left + 'px';
  el.style.minWidth = Math.min(Math.max(160, Math.floor(rect.width * 0.5)), 280) + 'px';
  el.style.display = 'block';
  if (window.innerHeight - rect.bottom < 100 && rect.top > 200) {
    el.style.top = '';
    el.style.bottom = (window.innerHeight - rect.top + 3) + 'px';
  } else {
    el.style.bottom = '';
    el.style.top = (rect.bottom + 3) + 'px';
  }
}

function _ptHide() {
  if (_ptAC.el) _ptAC.el.style.display = 'none';
  _ptAC.input = null;
}

function _ptPick(it) {
  const input = _ptAC.input;
  if (!input || !it) return;
  const val = input.value;
  const pos = input.selectionStart;
  const m = val.slice(0, pos).match(/\{\{\s*[^{}\n]*$/);
  if (!m) return;
  const start = pos - m[0].length;

  if (it.kind === 'ns') {
    // First stage: drop in `{{ns.` and re-open the popover on its item list.
    const insert = '{{' + it.ns + '.';
    input.value = val.slice(0, start) + insert + val.slice(pos);
    const caret = start + insert.length;
    input.setSelectionRange(caret, caret);
    input.focus();
    _ptOnInput({ target: input });
    return;
  }

  const insert = '{{' + it.kind + '.' + it.name + '}} ';
  input.value = val.slice(0, start) + insert + val.slice(pos);
  const caret = start + insert.length;
  input.setSelectionRange(caret, caret);
  _ptHide();
  input.focus();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _ptInit);
} else {
  _ptInit();
}
