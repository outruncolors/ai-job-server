/* Remember plugin frontend.
 *
 * Contributes a 🧠 Remember composer mode. The composer's main input is reused as
 * the fact to remember; the slide-up panel holds the scope chooser (this character
 * / this conversation) and optional tags. The composer's Send button (relabeled
 * **Save**) runs the `remember` action. Memory is side data — there's no chat turn
 * to render — so success is surfaced inline in the panel (and via a toast).
 *
 * (The per-message 🧠 Memorize → Verbatim / Gist affordance lives in the core
 * thread controls; this mode is the free-text "jot a fact" entry point.) */
(function () {
  if (!window.PtPlugins) return;

  function renderPanel(container, _ctx) {
    container.innerHTML = `
      <div class="pt-memory">
        <div class="pt-mem-row">
          <span class="pt-mem-label">Scope</span>
          <label class="pt-mem-opt"><input type="radio" name="pt-mem-scope" value="character" checked>
            <span>This character <small>recalled in every chat with them</small></span></label>
          <label class="pt-mem-opt"><input type="radio" name="pt-mem-scope" value="session">
            <span>This conversation <small>recalled only here</small></span></label>
        </div>
        <div class="pt-mem-row">
          <span class="pt-mem-label">Tags</span>
          <input type="text" class="pt-mem-tags" placeholder="optional, comma-separated">
        </div>
        <div class="pt-mem-msg" hidden></div>
      </div>`;
  }

  async function submitPanel(ctx) {
    const box = ctx.panelEl;
    const msg = box.querySelector('.pt-mem-msg');
    const scopeEl = box.querySelector('input[name="pt-mem-scope"]:checked');
    const scope = scopeEl ? scopeEl.value : 'character';
    const tags = (box.querySelector('.pt-mem-tags').value || '')
      .split(',').map((s) => s.trim()).filter(Boolean);
    const text = ctx.primaryValue();   // the composer input, reused as the fact
    function show(cls, text) { if (msg) { msg.hidden = false; msg.className = 'pt-mem-msg ' + cls; msg.textContent = text; } }
    if (!text) { show('pt-mem-err', 'Type a fact to remember first.'); return; }
    show('', 'Saving…');
    try {
      const res = await ctx.invokeAction('remember', { text, scope, tags });
      if (window.toast) window.toast('success', 'Remembered: ' + ((res && res.title) || 'saved'));
      ctx.close();   // back to the previous text mode (panel slides down)
    } catch (err) {
      show('pt-mem-err', 'Save failed: ' + ((err && err.message) || err));
      throw err;     // let the core re-enable the composer
    }
  }

  PtPlugins.register({
    id: 'memory',
    composerModes: [{
      type: 'remember',
      label: '🧠 Remember',
      goLabel: 'Save',
      placeholder: 'A fact to remember…',
    }],
    renderPanel: renderPanel,
    submitPanel: submitPanel,
  });
})();
