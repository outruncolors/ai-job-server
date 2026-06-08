/* Topbar — title, mode selector, saved-prompt selector, unit chip, indicators. */
(function () {
  const T = {};

  T.populateModes = function () {
    const sel = document.getElementById('tb-mode');
    sel.innerHTML = TB.MODE_GROUPS.map(([group, modes]) =>
      `<optgroup label="${_escHtml(group)}">${modes
        .map((m) => `<option value="${m}">${m.charAt(0).toUpperCase() + m.slice(1)}</option>`)
        .join('')}</optgroup>`
    ).join('');
    sel.value = TB.mode;
  };

  T.populateSavedPrompts = async function () {
    const sel = document.getElementById('tb-saved-prompt');
    let prompts = [];
    try {
      const data = await TB.api.savedPrompts();
      prompts = (data.entries || []).filter((p) => {
        const key = (p.data && p.data.key) || '';
        return key && !key.startsWith('mode.') && key !== 'base';
      });
    } catch (e) {
      prompts = [];
    }
    sel.innerHTML = '<option value="">— no saved prompt —</option>' +
      prompts.map((p) => {
        const key = (p.data && p.data.key) || '';
        return `<option value="${_escHtml(key)}">${_escHtml(p.name || key)}</option>`;
      }).join('');
    sel.value = TB.savedPromptKey || '';
  };

  T.render = function () {
    if (!TB.tale) return;
    document.getElementById('tb-title').value = TB.tale.title || '';
    document.getElementById('tb-mode').value = TB.mode;
    const unit = TB.currentUnit();
    const chip = document.getElementById('tb-unit-chip');
    chip.textContent = unit ? `✍ ${unit.title || unit.type}` : 'no unit';
    document.getElementById('tb-pane-ind').textContent = TB.activePane === 'content' ? '▭ content' : '▦ organization';
  };

  T.init = function () {
    T.populateModes();
    document.getElementById('tb-mode').addEventListener('change', (e) => {
      TB.mode = e.target.value;
    });
    document.getElementById('tb-saved-prompt').addEventListener('change', (e) => {
      TB.savedPromptKey = e.target.value;
    });
    document.getElementById('tb-title').addEventListener('change', async (e) => {
      await TB.api.patchTale(TB.tale.id, { title: e.target.value });
      TB.tale.title = e.target.value;
      toast('success', 'Title saved');
    });
    document.getElementById('tb-debug-toggle').addEventListener('click', () => TB.Debug.toggle());
    document.getElementById('tb-debug-close').addEventListener('click', () => TB.Debug.close());

    // left-tab switching
    document.querySelectorAll('#tb-left-tabs .tb-tab').forEach((tab) =>
      tab.addEventListener('click', () => TB.switchLeftTab(tab.getAttribute('data-pane')))
    );
  };

  window.TB = window.TB || {};
  window.TB.Topbar = T;
})();
