/* Prattletale frontend plugin API — window.PtPlugins.
 *
 * Loaded before prattletale.js. Each enabled plugin's JS (injected at chat load)
 * calls PtPlugins.register({...}) to contribute:
 *   - composerModes: [{type, label, goLabel?, placeholder?}] — extra composer modes
 *     (after Say/Do/Narrate). `goLabel` relabels the Send button while the mode is
 *     active; `placeholder` is shown in the main composer input (reused as the
 *     mode's free-text field — e.g. the Summarizer focus).
 *   - renderPanel(container, ctx) — render the mode's *options* into `container`
 *     (the slide-up panel). Buttons live on the composer's Go button, not here.
 *   - submitPanel(ctx) — run the action when Go is pressed (reads ctx.panelEl +
 *     ctx.primaryValue()). Independent of the composer's pending draft.
 *   - bubble: {types:[...], render(item, turn) -> html}  — how to render plugin item types
 *   - onModelTurn(turn, ctx) — fired once when a freshly committed turn (user or
 *     model) is rendered, so a plugin can resolve side content ASAP (e.g. SFX).
 * The core (prattletale.js) consults composerModes()/panel()/bubbleRenderer()/turnHooks()
 * — nothing plugin-specific is hard-coded there. register() is idempotent (last spec per id wins). */
(function () {
  const _specs = {};            // id -> spec
  const _bubbleRenderers = {};  // item type -> {pluginId, render}
  const _panels = {};           // composer mode type -> {pluginId, renderPanel}

  window.PtPlugins = {
    register(spec) {
      if (!spec || !spec.id) return;
      _specs[spec.id] = spec;
      (spec.composerModes || []).forEach((m) => {
        if (m && m.type) _panels[m.type] = {
          pluginId: spec.id,
          render: spec.renderPanel,
          submit: spec.submitPanel,
          placeholder: m.placeholder || '',
          goLabel: m.goLabel || 'Go',
        };
      });
      if (spec.bubble && typeof spec.bubble.render === 'function') {
        (spec.bubble.types || []).forEach((t) => {
          _bubbleRenderers[t] = { pluginId: spec.id, render: spec.bubble.render };
        });
      }
    },

    spec(id) { return _specs[id] || null; },

    // Composer modes contributed by the given enabled plugin ids, in id order.
    // Each returned mode carries `__pluginId` so the core can route its panel.
    composerModes(enabledIds) {
      const ids = enabledIds || Object.keys(_specs);
      const out = [];
      ids.forEach((id) => {
        const s = _specs[id];
        if (s && s.composerModes) {
          s.composerModes.forEach((m) => out.push(Object.assign({}, m, { __pluginId: id })));
        }
      });
      return out;
    },

    // The plugin renderer for an item type (e.g. the `summary` card), or null.
    bubbleRenderer(type) { return _bubbleRenderers[type] || null; },

    // The {pluginId, renderPanel} for a composer mode type, or null.
    panel(modeType) { return _panels[modeType] || null; },

    // [{pluginId, fn}] for enabled plugins exposing onModelTurn(turn, ctx). The
    // core fires these when a freshly committed turn renders.
    turnHooks(enabledIds) {
      const ids = enabledIds || Object.keys(_specs);
      const out = [];
      ids.forEach((id) => {
        const s = _specs[id];
        if (s && typeof s.onModelTurn === 'function') out.push({ pluginId: id, fn: s.onModelTurn });
      });
      return out;
    },
  };
})();
