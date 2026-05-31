/* Prattletale SFX plugin (frontend).
 *
 * Registers an onModelTurn hook: when a freshly committed turn renders, it asks
 * the backend to resolve SFX for the turn's eligible action/narration items and
 * applies each resolved descriptor to the live item (ctx.applySfx). The core then
 * plays the SFX after the item's normal audio during reveal, and the speaker
 * button replays audio→SFX. The chance roll + chooser/guard run server-side; the
 * frontend just triggers resolution ASAP and surfaces the result. */
(function () {
  if (!window.PtPlugins) return;

  PtPlugins.register({
    id: 'sfx',
    async onModelTurn(turn, ctx) {
      if (!turn || !turn.id) return;
      // Only bother when this conversation has SFX switched on.
      const cfg = (ctx.conversation && ctx.conversation.config) || {};
      if (!cfg.sfx_enabled) return;
      let res;
      try {
        res = await ctx.invokeAction('resolve-turn', { turn_id: turn.id });
      } catch (_) {
        return; // best-effort; a resolver failure must never block the chat
      }
      ((res && res.items) || []).forEach((r) => {
        if (r && r.item_id) ctx.applySfx(turn.id, r.item_id, r.sfx);
      });
    },
  });
})();
