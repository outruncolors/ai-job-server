/* Summarizer plugin frontend.
 *
 * Contributes a 📋 Summarize composer mode. Its slide-up panel holds only the
 * options (Keep/Purge + detail level); the composer's main input is reused as the
 * optional **focus** field, and the composer's Send button (relabeled **Go**)
 * runs the summarize action — independent of any pending staged draft. Renders the
 * returned summary card and applies Purge in place. Loaded by the core only when
 * the plugin is enabled for the conversation. */
(function () {
  if (!window.PtPlugins) return;

  // Render just the options into the slide-up panel (no focus field, no buttons —
  // those live on the composer input + Go button).
  function renderPanel(container, _ctx) {
    container.innerHTML = `
      <div class="pt-summarizer">
        <div class="pt-sum-row">
          <span class="pt-sum-label">Mode</span>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-mode" value="keep" checked>
            <span>Keep <small>recap added; originals stay</small></span></label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-mode" value="purge">
            <span>Purge <small>recap replaces the originals in context</small></span></label>
        </div>
        <div class="pt-sum-row">
          <span class="pt-sum-label">Detail</span>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="brief"> Brief</label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="standard" checked> Standard</label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="detailed"> Detailed</label>
        </div>
        <div class="pt-sum-msg" hidden></div>
      </div>`;
  }

  // Run on Go: read the options from the panel + the focus from the composer
  // input, invoke the action, render the result, then return to a text mode.
  async function submitPanel(ctx) {
    const box = ctx.panelEl;
    const msg = box.querySelector('.pt-sum-msg');
    const modeEl = box.querySelector('input[name="pt-sum-mode"]:checked');
    const detailEl = box.querySelector('input[name="pt-sum-detail"]:checked');
    if (!modeEl || !detailEl) return;
    const mode = modeEl.value;
    const detail = detailEl.value;
    const focus = ctx.primaryValue();   // the composer input, reused as focus
    if (msg) { msg.hidden = false; msg.className = 'pt-sum-msg'; msg.textContent = 'Summarizing… this may take a moment.'; }
    try {
      const res = await ctx.invokeAction('summarize', { mode, detail, focus });
      ctx.onResult(res);   // append the summary card; apply Purge in place
      ctx.close();         // back to the previous text mode (panel slides down)
    } catch (err) {
      // Surface the failure inline in the panel — no chat error bubble.
      if (msg) { msg.className = 'pt-sum-msg pt-sum-err'; msg.textContent = 'Summarize failed: ' + ((err && err.message) || err); }
      throw err;           // let the core re-enable the composer
    }
  }

  // The `summary` bubble: a centered, full-width "📋 Summary" card. Keeps
  // data-turn/data-item so the core's per-message controls (edit/hide/delete) attach.
  function renderSummary(item, turn) {
    const hidden = item.hidden_from_context ? ' pt-bubble--hidden' : '';
    const tag = item.hidden_from_context
      ? '<span class="pt-hidden-tag" title="Hidden from context">🚫 hidden</span>' : '';
    return `<div class="pt-bubble pt-summary-card${hidden}" data-turn="${_escHtml(turn.id)}" data-item="${_escHtml(item.id)}">` +
      `<div class="pt-summary-head">📋 Summary</div>` +
      `<div class="pt-summary-text">${_escHtml(item.text || '')}</div>${tag}</div>`;
  }

  PtPlugins.register({
    id: 'summarizer',
    composerModes: [{
      type: 'summarize',
      label: '📋 Summarize',
      goLabel: 'Go',
      placeholder: 'What should the summary emphasize? (optional)',
    }],
    renderPanel: renderPanel,
    submitPanel: submitPanel,
    bubble: { types: ['summary'], render: renderSummary },
  });
})();
