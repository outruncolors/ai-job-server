/* Tomeberry orchestrator — tale list + studio router (?tale=<id>). */
(function () {
  let inited = false;

  function show(view) {
    document.getElementById('tb-list-view').hidden = view !== 'list';
    document.getElementById('tb-studio').hidden = view !== 'studio';
  }

  // ---- tale list -----------------------------------------------------------

  async function renderList() {
    show('list');
    const main = document.getElementById('tb-list');
    main.innerHTML = '<div class="tb-empty">Loading…</div>';
    try {
      const data = await TB.api.listTales();
      const tales = data.tales || [];
      main.innerHTML = tales.length
        ? tales.map((t) => `
            <a class="tb-tale-card" href="?tale=${encodeURIComponent(t.id)}">
              <div class="tb-tale-title">${_escHtml(t.title)}</div>
              <div class="tb-tale-meta">${_escHtml((t.default_mode || '').toString())} · updated ${_escHtml((t.updated_at || '').slice(0, 10))}</div>
            </a>`).join('')
        : '<div class="tb-empty">No tales yet. Create one to begin.</div>';
    } catch (err) {
      main.innerHTML = `<div class="tb-empty">${_escHtml(err.message)}</div>`;
    }
  }

  async function newTale() {
    const title = prompt('Tale title:', 'Untitled Tale');
    if (title === null) return;
    const premise = prompt('Premise (optional — as vague as "a princess is saved"):', '') || '';
    try {
      const tale = await TB.api.createTale({ title, premise });
      window.location.search = `?tale=${encodeURIComponent(tale.id)}`;
    } catch (err) {
      toast('error', 'Create failed: ' + err.message);
    }
  }

  // ---- studio --------------------------------------------------------------

  TB.switchLeftTab = function (pane) {
    TB.leftTab = pane;
    TB.activePane = pane;
    document.getElementById('tb-content-pane').hidden = pane !== 'content';
    document.getElementById('tb-org-pane').hidden = pane !== 'organization';
    document.querySelectorAll('#tb-left-tabs .tb-tab').forEach((t) =>
      t.classList.toggle('active', t.getAttribute('data-pane') === pane)
    );
    if (TB.Topbar) TB.Topbar.render();
  };

  async function openStudio(tid) {
    try {
      const data = await TB.api.getTale(tid);
      TB.tale = data.tale;
      TB.hierarchy = data.hierarchy;
      TB.concepts = data.concepts || [];
      TB.mode = TB.tale.default_mode || 'draft';
      TB.savedPromptKey = TB.tale.default_saved_prompt || '';
      TB.currentUnitId = null;
    } catch (err) {
      toast('error', 'Could not open tale: ' + err.message);
      renderList();
      return;
    }
    show('studio');
    if (!inited) {
      TB.Topbar.init();
      TB.ContentPane.init();
      TB.Assistant.init();
      document.getElementById('tb-back').addEventListener('click', () => {
        window.location.search = '';
      });
      inited = true;
    }
    await TB.Topbar.populateSavedPrompts();
    TB.Topbar.render();
    TB.ContentPane.render();
    TB.OrgPane.render();
    await TB.Assistant.reload();
    TB.switchLeftTab('organization'); // start in organization to pick a unit
  }

  function boot() {
    document.getElementById('tb-new').addEventListener('click', newTale);
    const params = new URLSearchParams(window.location.search);
    const tid = params.get('tale');
    if (tid) {
      openStudio(tid);
    } else {
      renderList();
    }
  }

  boot();
})();
