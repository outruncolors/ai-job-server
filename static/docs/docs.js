let _tree = [];
let _activeDoc = null;
const _expanded = new Set();
const _docPaths = new Set();

async function loadDocList() {
  const data = await api('/docs');
  _tree = data.tree || [];
  collectDocPaths(_tree);

  const hash = decodeURIComponent(location.hash.slice(1));
  const initial = (hash && _docPaths.has(hash)) ? hash : firstDoc(_tree);
  if (initial) {
    expandAncestors(initial);
    renderTree();
    loadDoc(initial);
  } else {
    renderTree();
  }
}

function collectDocPaths(nodes) {
  for (const n of nodes) {
    if (n.type === 'doc') _docPaths.add(n.path);
    else if (n.children) collectDocPaths(n.children);
  }
}

function firstDoc(nodes) {
  for (const n of nodes) {
    if (n.type === 'doc') return n.path;
    if (n.children) {
      const found = firstDoc(n.children);
      if (found) return found;
    }
  }
  return null;
}

function expandAncestors(docPath) {
  const parts = docPath.split('/');
  for (let i = 1; i < parts.length; i++) {
    _expanded.add(parts.slice(0, i).join('/'));
  }
}

function renderTree() {
  const el = document.getElementById('doc-list');
  if (!_tree.length) {
    el.innerHTML = '<div class="empty">No docs found.</div>';
    return;
  }
  el.innerHTML = renderNodes(_tree, 0);
  wireTree(el);
}

function renderNodes(nodes, depth) {
  return nodes.map(n => {
    const indent = `style="padding-left:${8 + depth * 14}px"`;
    if (n.type === 'dir') {
      const open = _expanded.has(n.path);
      const caret = open ? '▾' : '▸';
      const childrenHtml = open
        ? `<div class="doc-children">${renderNodes(n.children || [], depth + 1)}</div>`
        : '';
      return `
        <div class="doc-dir${open ? ' open' : ''}">
          <button class="doc-dir-row" data-dir="${_escHtml(n.path)}" ${indent}>
            <span class="doc-caret">${caret}</span>
            <span class="doc-dir-title">${_escHtml(n.title)}</span>
          </button>
          ${childrenHtml}
        </div>`;
    }
    const active = n.path === _activeDoc ? ' active' : '';
    return `
      <button class="doc-item${active}" data-path="${_escHtml(n.path)}" ${indent}>
        <span class="doc-item-title">${_escHtml(n.title)}</span>
        <span class="doc-item-size">${_fmtSize(n.size)}</span>
      </button>`;
  }).join('');
}

function wireTree(el) {
  el.querySelectorAll('.doc-dir-row').forEach(btn => {
    btn.addEventListener('click', () => {
      const p = btn.dataset.dir;
      if (_expanded.has(p)) _expanded.delete(p);
      else _expanded.add(p);
      renderTree();
    });
  });
  el.querySelectorAll('.doc-item').forEach(btn => {
    btn.addEventListener('click', () => loadDoc(btn.dataset.path));
  });
}

async function loadDoc(docPath) {
  _activeDoc = docPath;
  location.hash = encodeURI(docPath);
  expandAncestors(docPath);
  renderTree();

  const contentEl = document.getElementById('doc-content');
  contentEl.innerHTML = '<div class="doc-placeholder">Loading…</div>';

  try {
    const url = '/v1/docs/' + docPath.split('/').map(encodeURIComponent).join('/');
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const text = await res.text();
    contentEl.innerHTML = marked.parse(text);
    rewriteInternalLinks(contentEl, docPath);
    contentEl.scrollTop = 0;
    document.getElementById('panel-right').scrollTop = 0;
  } catch (e) {
    contentEl.innerHTML = `<div class="doc-placeholder">Failed to load document: ${_escHtml(e.message)}</div>`;
  }
}

function rewriteInternalLinks(root, currentPath) {
  const currentDir = currentPath.includes('/')
    ? currentPath.slice(0, currentPath.lastIndexOf('/'))
    : '';

  root.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href');
    if (!href) return;
    if (/^[a-z]+:\/\//i.test(href) || href.startsWith('mailto:') || href.startsWith('#')) return;

    const [pathPart, fragment] = href.split('#', 2);
    if (!pathPart.endsWith('.md')) return;

    const resolved = resolvePath(currentDir, pathPart);
    if (!_docPaths.has(resolved)) return;

    a.setAttribute('href', '#' + encodeURI(resolved) + (fragment ? '#' + fragment : ''));
    a.addEventListener('click', (ev) => {
      ev.preventDefault();
      loadDoc(resolved);
    });
  });
}

function resolvePath(baseDir, relPath) {
  if (relPath.startsWith('/')) return relPath.slice(1);
  const baseParts = baseDir ? baseDir.split('/') : [];
  const relParts = relPath.split('/');
  for (const part of relParts) {
    if (part === '' || part === '.') continue;
    if (part === '..') baseParts.pop();
    else baseParts.push(part);
  }
  return baseParts.join('/');
}

function _fmtSize(bytes) {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes}B`;
  return `${(bytes / 1024).toFixed(1)}K`;
}

window.addEventListener('hashchange', () => {
  const name = decodeURIComponent(location.hash.slice(1));
  if (name && name !== _activeDoc && _docPaths.has(name)) {
    loadDoc(name);
  }
});

loadDocList();
