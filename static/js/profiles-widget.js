/* Profile widget: inline group at the right edge of #topnav on every page.
   Layout:  [ select ▾ ] [ 💾 save ] [ ⬇ export ] [ ⬆ import ]
   When the select shows "(new profile)" and Save is clicked, the save area
   swaps to:  [ name input ] [ ✓ confirm ] [ ✗ cancel ] until the user
   confirms or cancels.
   Self-contained — works on pages that don't load api.js/toast.js. */

(function () {
  const esc = (typeof _escHtml === 'function')
    ? _escHtml
    : (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));

  function notify(type, msg) {
    if (typeof toast === 'function') return toast(type, msg);
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

  const NEW = '__new__';
  const state = { profiles: [], active_id: null, mode: 'idle' /* | 'naming' */ };
  let groupEl, selectEl, saveArea, exportBtn, importFileEl;

  async function refresh() {
    try {
      const data = await apiJson('/profiles');
      state.profiles = data.profiles || [];
      state.active_id = data.active_id || null;
    } catch (_) {
      state.profiles = [];
      state.active_id = null;
    }
  }

  function build() {
    const nav = document.getElementById('topnav');
    if (!nav) return;
    if (document.getElementById('nav-profile-group')) return;

    groupEl = document.createElement('div');
    groupEl.id = 'nav-profile-group';
    groupEl.className = 'nav-profile-group';

    selectEl = document.createElement('select');
    selectEl.id = 'profile-select';
    selectEl.title = 'Active profile';
    selectEl.addEventListener('change', onSelectChange);
    groupEl.appendChild(selectEl);

    saveArea = document.createElement('span');
    saveArea.className = 'profile-save-area';
    groupEl.appendChild(saveArea);

    exportBtn = document.createElement('button');
    exportBtn.id = 'profile-export';
    exportBtn.className = 'profile-icon-btn';
    exportBtn.type = 'button';
    exportBtn.title = 'Export selected profile';
    exportBtn.textContent = '⬇';
    exportBtn.addEventListener('click', onExport);
    groupEl.appendChild(exportBtn);

    const importBtn = document.createElement('button');
    importBtn.id = 'profile-import';
    importBtn.className = 'profile-icon-btn';
    importBtn.type = 'button';
    importBtn.title = 'Import profile bundle (.zip)';
    importBtn.textContent = '⬆';
    importBtn.addEventListener('click', () => importFileEl.click());
    groupEl.appendChild(importBtn);

    importFileEl = document.createElement('input');
    importFileEl.type = 'file';
    importFileEl.accept = '.zip,application/zip';
    importFileEl.style.display = 'none';
    importFileEl.addEventListener('change', onImportFile);
    groupEl.appendChild(importFileEl);

    nav.appendChild(groupEl);

    refresh().then(render);
  }

  function render() {
    renderSelect();
    renderSaveArea();
    updateExportEnabled();
  }

  function renderSelect() {
    selectEl.innerHTML = '';
    for (const p of state.profiles) {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.id === state.active_id ? p.name + ' ●' : p.name;
      selectEl.appendChild(opt);
    }
    const newOpt = document.createElement('option');
    newOpt.value = NEW;
    newOpt.textContent = '(new profile)';
    selectEl.appendChild(newOpt);

    if (state.mode === 'naming') {
      selectEl.value = NEW;
      selectEl.disabled = true;
    } else {
      selectEl.disabled = false;
      if (state.active_id && state.profiles.some(p => p.id === state.active_id)) {
        selectEl.value = state.active_id;
      } else {
        selectEl.value = NEW;
      }
    }
  }

  function renderSaveArea() {
    saveArea.innerHTML = '';
    if (state.mode === 'naming') {
      const nameInput = document.createElement('input');
      nameInput.type = 'text';
      nameInput.className = 'profile-name-input';
      nameInput.placeholder = 'profile name';
      nameInput.autocomplete = 'off';
      nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); commitNew(nameInput.value); }
        else if (e.key === 'Escape') { e.preventDefault(); cancelNew(); }
      });
      saveArea.appendChild(nameInput);

      const ok = document.createElement('button');
      ok.className = 'profile-icon-btn profile-confirm';
      ok.type = 'button';
      ok.title = 'Save new profile';
      ok.textContent = '✓';
      ok.addEventListener('click', () => commitNew(nameInput.value));
      saveArea.appendChild(ok);

      const cancel = document.createElement('button');
      cancel.className = 'profile-icon-btn';
      cancel.type = 'button';
      cancel.title = 'Cancel';
      cancel.textContent = '✗';
      cancel.addEventListener('click', cancelNew);
      saveArea.appendChild(cancel);

      setTimeout(() => nameInput.focus(), 0);
    } else {
      const save = document.createElement('button');
      save.className = 'profile-icon-btn';
      save.type = 'button';
      save.title = selectEl.value === NEW
        ? 'Save current live config as a new profile'
        : 'Save current live config over the selected profile';
      save.textContent = '💾';
      save.addEventListener('click', onSave);
      saveArea.appendChild(save);
    }
  }

  function updateExportEnabled() {
    const canExport = selectEl.value && selectEl.value !== NEW;
    exportBtn.disabled = !canExport;
  }

  async function onSelectChange() {
    if (state.mode === 'naming') return;
    const v = selectEl.value;
    updateExportEnabled();
    renderSaveArea();  // refresh save button title to reflect new vs overwrite
    if (v === NEW || v === '' || v === state.active_id) return;
    const p = state.profiles.find(x => x.id === v);
    if (!p) return;
    try {
      await apiJson(`/profiles/${v}/activate`, 'POST');
      notify('success', `Activated "${p.name}"`);
      await refresh();
      render();
    } catch (e) {
      notify('error', 'Activation failed: ' + e.message);
      await refresh();
      render();
    }
  }

  function onSave() {
    const v = selectEl.value;
    if (v === NEW || v === '') {
      state.mode = 'naming';
      render();
      return;
    }
    overwrite(v);
  }

  async function overwrite(pid) {
    const p = state.profiles.find(x => x.id === pid);
    if (!p) return;
    try {
      await apiJson(`/profiles/${pid}/overwrite`, 'POST');
      notify('success', `Saved over "${p.name}"`);
      await refresh();
      render();
    } catch (e) {
      notify('error', 'Save failed: ' + e.message);
    }
  }

  function cancelNew() {
    state.mode = 'idle';
    render();
  }

  async function commitNew(rawName) {
    const name = (rawName || '').trim();
    if (!name) {
      notify('error', 'Name is required');
      return;
    }
    try {
      const entry = await apiJson('/profiles', 'POST', { name });
      // Mark the freshly saved snapshot as active so the dropdown reflects it.
      await apiJson(`/profiles/${entry.id}/activate`, 'POST');
      notify('success', `Saved profile "${entry.name}"`);
      state.mode = 'idle';
      await refresh();
      render();
    } catch (e) {
      notify('error', 'Save failed: ' + e.message);
    }
  }

  function onExport() {
    const v = selectEl.value;
    if (!v || v === NEW) return;
    window.location.href = `/v1/profiles/${v}/export`;
  }

  async function onImportFile() {
    const file = importFileEl.files && importFileEl.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    try {
      const r = await fetch('/v1/profiles/import', { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const data = await r.json();
      notify('success', `Imported "${data.name}"`);
      await refresh();
      render();
    } catch (e) {
      notify('error', 'Import failed: ' + e.message);
    }
    importFileEl.value = '';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
