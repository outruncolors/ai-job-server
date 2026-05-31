/* Summarizer plugin frontend.
 *
 * Contributes a 📋 Summarize composer mode whose slide-up panel offers Keep/Purge,
 * a detail level, and an optional focus note, then invokes the backend `summarize`
 * action and renders the returned summary card (applying Purge in place). Loaded by
 * the core only when the plugin is enabled for the conversation. */
(function () {
  if (!window.PtPlugins) return;

  function renderPanel(container, ctx) {
    container.innerHTML = `
      <div class="pt-summarizer">
        <div class="pt-sum-head">📋 Summarize the conversation so far</div>
        <div class="pt-sum-row">
          <span class="pt-sum-label">Mode</span>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-mode" value="keep" checked>
            <span>Keep <small>recap added; originals stay in context</small></span></label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-mode" value="purge">
            <span>Purge <small>recap replaces the originals in context</small></span></label>
        </div>
        <div class="pt-sum-row">
          <span class="pt-sum-label">Detail</span>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="brief"> Brief</label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="standard" checked> Standard</label>
          <label class="pt-sum-opt"><input type="radio" name="pt-sum-detail" value="detailed"> Detailed</label>
        </div>
        <label class="pt-sum-focus">Focus <small>(optional)</small>
          <textarea class="pt-sum-focus-input" rows="2"
            placeholder="What should the summary emphasize?"></textarea>
        </label>
        <div class="pt-sum-msg" hidden></div>
        <div class="pt-sum-actions">
          <button type="button" class="pt-sum-cancel secondary">Cancel</button>
          <button type="button" class="pt-sum-go">Summarize</button>
        </div>
      </div>`;

    const go = container.querySelector('.pt-sum-go');
    const cancel = container.querySelector('.pt-sum-cancel');
    const msg = container.querySelector('.pt-sum-msg');

    cancel.addEventListener('click', () => ctx.close());

    go.addEventListener('click', async () => {
      const mode = container.querySelector('input[name="pt-sum-mode"]:checked').value;
      const detail = container.querySelector('input[name="pt-sum-detail"]:checked').value;
      const focus = container.querySelector('.pt-sum-focus-input').value.trim();
      go.disabled = true; cancel.disabled = true;
      msg.hidden = false; msg.className = 'pt-sum-msg'; msg.textContent = 'Summarizing… this may take a moment.';
      try {
        const res = await ctx.invokeAction('summarize', { mode, detail, focus });
        ctx.onResult(res);   // append the summary card; apply Purge in place
        ctx.close();         // back to a text mode (slides the panel down)
      } catch (err) {
        // Surface the failure inline in the panel — no chat error bubble.
        msg.className = 'pt-sum-msg pt-sum-err';
        msg.textContent = 'Summarize failed: ' + ((err && err.message) || err);
        go.disabled = false; cancel.disabled = false;
      }
    });
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
    composerModes: [{ type: 'summarize', label: '📋 Summarize' }],
    renderPanel: renderPanel,
    bubble: { types: ['summary'], render: renderSummary },
  });
})();
