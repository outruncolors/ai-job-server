/* Profile widget: dropdown on desktop, slide-in drawer on mobile.
   Self-contained — works on any page that loads nav.js, even ones without
   the shared toast/api/escape modules. */

(function () {
  const esc = (typeof _escHtml === 'function')
    ? _escHtml
    : (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));

  function notify(type, msg) {
    if (typeof toast === 'function') return toast(type, msg);
    // minimal fallback toast
    let stack = document.getElementById('toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'toast-stack';
      document.body.appendChild(stack);
    }
    const el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.textContent = msg;
    stack.appendChild(el);
    setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); },
               type === 'error' ? 6000 : 3500);
  }

  async function apiJson(path, method = 'GET', body = null) {
    if (typeof api === 'function' && method !== 'DELETE') return api(path, method, body);
    const url = path.startsWith('/v1') ? path : '/v1' + path;
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== null) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error(await r.text());
    if (r.status === 204) return null;
    return r.json();
  }

  const state = { profiles: [], active_id: null, open: false, view: 'menu' };
  let btn, panel, overlay;

  async function refresh() {
    try {
      const data = await apiJson('/profiles');
      state.profiles = data.profiles || [];
      state.active_id = data.active_id || null;
    } catch (e) {
      state.profiles = [];
      state.active_id = null;
    }
  }

  function activeProfile() {
    return state.profiles.find(p => p.id === state.active_id) || null;
  }

  function activeLabel() {
    const a = activeProfile();
    return a ? a.name : 'No profile';
  }

  function build() {
    const nav = document.getElementById('topnav');
    if (!nav) return;
    if (document.getElementById('nav-profile-btn')) return;  // already built

    btn = document.createElement('button');
    btn.id = 'nav-profile-btn';
    btn.className = 'nav-profile-btn';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Profiles');
    btn.innerHTML =
      '<span class="profile-icon">👤</span>' +
      '<span class="profile-name">' + esc(activeLabel()) + '</span>' +
      '<span class="profile-caret">▾</span>';
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      state.open ? close() : open();
    });
    nav.appendChild(btn);

    overlay = document.createElement('div');
    overlay.id = 'profile-overlay';
    overlay.className = 'profile-overlay';
    overlay.addEventListener('click', close);
    document.body.appendChild(overlay);

    panel = document.createElement('div');
    panel.id = 'profile-panel';
    panel.className = 'profile-panel';
    panel.setAttribute('role', 'dialog');
    panel.addEventListener('click', (e) => e.stopPropagation());
    document.body.appendChild(panel);

    // Close on outside click anywhere (desktop dropdown has no overlay).
    document.addEventListener('click', (e) => {
      if (!state.open) return;
      if (panel.contains(e.target) || btn.contains(e.target)) return;
      close();
    });

    // Keyboard: Esc closes
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.open) close();
    });

    refresh().then(updateLabel);
  }

  function updateLabel() {
    if (!btn) return;
    const nameSpan = btn.querySelector('.profile-name');
    if (nameSpan) nameSpan.textContent = activeLabel();
  }

  async function open() {
    state.open = true;
    state.view = 'menu';
    await refresh();
    render();
    updateLabel();
  }

  function close() {
    state.open = false;
    if (panel) panel.classList.remove('open');
    if (overlay) overlay.classList.remove('open');
  }

  function render() {
    if (!panel) return;
    panel.innerHTML = (state.view === 'save')
      ? saveFormHtml()
      : (state.view === 'import') ? importFormHtml() : menuHtml();
    wire();
    panel.classList.add('open');
    overlay.classList.add('open');
  }

  function menuHtml() {
    const active = activeProfile();
    const rows = state.profiles.length
      ? state.profiles.map(p => `
          <li class="profile-row${p.id === state.active_id ? ' active' : ''}">
            <button class="profile-pick" data-id="${esc(p.id)}" type="button">
              <span class="profile-row-name">${esc(p.name)}</span>
              ${p.id === state.active_id ? '<span class="profile-row-tag">active</span>' : ''}
            </button>
          </li>`).join('')
      : '<li class="profile-empty">No saved profiles yet.</li>';

    return `
      <div class="profile-header">
        <span class="profile-header-title">Profiles</span>
        <button class="profile-close" type="button" aria-label="Close">×</button>
      </div>
      <div class="profile-body">
        <ul class="profile-list">${rows}</ul>
        <div class="profile-actions">
          <button class="profile-action" data-act="save"   type="button">Save current as new profile…</button>
          <button class="profile-action" data-act="import" type="button">Import bundle…</button>
          <button class="profile-action" data-act="export" type="button" ${active ? '' : 'disabled'}>Export active</button>
          <button class="profile-action danger" data-act="delete" type="button" ${active ? '' : 'disabled'}>Delete active…</button>
        </div>
      </div>`;
  }

  function saveFormHtml() {
    return `
      <div class="profile-header">
        <button class="profile-back" type="button" aria-label="Back">←</button>
        <span class="profile-header-title">Save current</span>
        <button class="profile-close" type="button" aria-label="Close">×</button>
      </div>
      <div class="profile-body">
        <label for="pw-save-name">Name</label>
        <input id="pw-save-name" type="text" placeholder="e.g. friday-baseline" autocomplete="off">
        <label for="pw-save-desc">Description (optional)</label>
        <textarea id="pw-save-desc" rows="3" placeholder=""></textarea>
        <button class="profile-primary" data-act="save-submit" type="button">Save profile</button>
      </div>`;
  }

  function importFormHtml() {
    return `
      <div class="profile-header">
        <button class="profile-back" type="button" aria-label="Back">←</button>
        <span class="profile-header-title">Import bundle</span>
        <button class="profile-close" type="button" aria-label="Close">×</button>
      </div>
      <div class="profile-body">
        <label for="pw-import-file">Bundle (.zip)</label>
        <input id="pw-import-file" type="file" accept=".zip,application/zip">
        <label for="pw-import-name">Profile name (optional — defaults to the bundle's own name)</label>
        <input id="pw-import-name" type="text" placeholder="" autocomplete="off">
        <fieldset class="profile-mode">
          <legend>Mode</legend>
          <label><input type="radio" name="pw-mode" value="new" checked> Save as new profile</label>
          <label><input type="radio" name="pw-mode" value="replace"> Apply directly (overwrites live config)</label>
        </fieldset>
        <button class="profile-primary" data-act="import-submit" type="button">Upload</button>
      </div>`;
  }

  function wire() {
    panel.querySelectorAll('.profile-close').forEach(b => b.addEventListener('click', close));
    panel.querySelectorAll('.profile-back').forEach(b => b.addEventListener('click', () => {
      state.view = 'menu';
      render();
    }));

    panel.querySelectorAll('.profile-pick').forEach(b => b.addEventListener('click', () => {
      activate(b.dataset.id);
    }));

    panel.querySelectorAll('.profile-action').forEach(b => b.addEventListener('click', () => {
      const act = b.dataset.act;
      if (act === 'save')   { state.view = 'save';   render(); }
      if (act === 'import') { state.view = 'import'; render(); }
      if (act === 'export') exportActive();
      if (act === 'delete') deleteActive();
    }));

    const saveBtn = panel.querySelector('[data-act="save-submit"]');
    if (saveBtn) saveBtn.addEventListener('click', saveCurrent);

    const importBtn = panel.querySelector('[data-act="import-submit"]');
    if (importBtn) importBtn.addEventListener('click', importBundle);
  }

  async function activate(id) {
    const p = state.profiles.find(x => x.id === id);
    if (!p) return;
    if (id === state.active_id) { close(); return; }
    if (!confirm(`Switch active profile to "${p.name}"? This overwrites every live config domain.`)) return;
    try {
      await apiJson(`/profiles/${id}/activate`, 'POST');
      notify('success', `Activated "${p.name}"`);
      await refresh();
      updateLabel();
      close();
    } catch (e) {
      notify('error', 'Activation failed: ' + e.message);
    }
  }

  async function saveCurrent() {
    const name = (panel.querySelector('#pw-save-name').value || '').trim();
    if (!name) { notify('error', 'Name is required'); return; }
    const description = panel.querySelector('#pw-save-desc').value || '';
    try {
      const entry = await apiJson('/profiles', 'POST', { name, description });
      notify('success', `Saved profile "${entry.name}"`);
      await refresh();
      updateLabel();
      state.view = 'menu';
      render();
    } catch (e) {
      notify('error', 'Save failed: ' + e.message);
    }
  }

  function exportActive() {
    const id = state.active_id;
    if (!id) return;
    window.location.href = `/v1/profiles/${id}/export`;
    close();
  }

  async function deleteActive() {
    const a = activeProfile();
    if (!a) return;
    if (!confirm(`Delete profile "${a.name}"? This cannot be undone.`)) return;
    try {
      const r = await fetch(`/v1/profiles/${a.id}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(await r.text());
      notify('success', `Deleted "${a.name}"`);
      await refresh();
      updateLabel();
      close();
    } catch (e) {
      notify('error', 'Delete failed: ' + e.message);
    }
  }

  async function importBundle() {
    const fileEl = panel.querySelector('#pw-import-file');
    const file = fileEl && fileEl.files && fileEl.files[0];
    if (!file) { notify('error', 'Choose a .zip first'); return; }
    const name = (panel.querySelector('#pw-import-name').value || '').trim();
    const mode = panel.querySelector('input[name="pw-mode"]:checked').value;
    if (mode === 'replace') {
      if (!confirm('Apply this bundle in replace mode? All current live config will be overwritten.')) return;
    }
    const fd = new FormData();
    fd.append('file', file);
    if (name) fd.append('name', name);
    if (mode === 'replace') fd.append('mode', 'replace');
    try {
      const r = await fetch('/v1/profiles/import', { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      notify('success', mode === 'replace' ? 'Bundle applied' : `Imported "${data.name}"`);
      await refresh();
      updateLabel();
      close();
    } catch (e) {
      notify('error', 'Import failed: ' + e.message);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
