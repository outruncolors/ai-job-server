# SP5 — Per-message action wrapper (frontend)

Sub-phase **SP5** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [04 — SP4](04-sp4-config-view.md) · **Next:** [06 — SP6 trace viewer + node-graph](06-sp6-trace-viewer-node-graph.md) · [Sequence](README.md)

Depends on **SP1**, committed. Verified manually in the browser.

```
Implement Phase 2 sub-phase SP5 of Prattletale (iMessage-style roleplay chat): the per-message
action wrapper. SP1 is committed (edit/hide/delete item + delete turn endpoints work). Pure
frontend.

Read first:
- docs/apps/prattletale/design.md — "data model" (item types, hidden_from_context).
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP5" section.
- static/js/field-controls.js + static/css/field-controls.css — the FieldControls.attach(slot,
  {kind, controls:[{id,label,onClick(ctx)}], context}) hover-cluster contract (zero app knowledge;
  the app supplies all callbacks).
- static/apps/hoodat/profile.js — a real FieldControls.attach call site to copy the pattern.
- static/apps/prattletale/prattletale.js (committed) — bubbleHtml / turnHtml / renderThread, the
  existing per-bubble wiring (wirePlay / wireRetry), mediaUrl, and the retry path's in-place DOM swap
  (the model for re-rendering one turn after an edit).
- SP1's committed endpoints (PATCH/DELETE .../items/{item_id}, DELETE .../turns/{turn_id}).

Build (additive only) — static/apps/prattletale/:
- Wrap each rendered bubble with FieldControls (or an equivalent hover cluster consistent with the
  app styling): ✏️ EDIT (inline textarea -> PATCH .../items/{item_id} {text}); 🚫 HIDE / 👁 SHOW
  (toggle hidden_from_context via the same PATCH); 🗑 DELETE (DELETE .../items/{item_id}; confirm).
  A turn-level 🗑 DELETE TURN (DELETE .../turns/{turn_id}; confirm) on the turn's avatar/stack hover.
- Render HIDDEN items with a clear muted/strikethrough style + a "won't be sent to the model"
  affordance so the context effect is visible. Hidden items still render in history, just styled as
  excluded.
- After each op, update _current.transcript in memory and re-render the affected turn in place
  (mirror the retry path's outerHTML swap); an item delete that empties a turn removes the turn.
- Don't break the 🔊 play button or Retry — the hover cluster sits alongside them. Edit/hide/delete
  do NOT re-run the model (no cascade; regen is turn-level Retry — intentional).
- Load field-controls.js + field-controls.css in index.html. Escape all text; reuse api().

Done when (manual — start .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090):
- hover a bubble -> edit its text -> persists on reload;
- hide a model item -> it renders muted -> send another turn -> open that turn's trace
  (GET .../trace) and confirm context_input.transcript omits the hidden item;
- delete an item -> it disappears (an emptied turn collapses); delete a turn -> gone on reload.
No new automated assertions beyond SP1's API tests; run the existing suite to confirm no regression.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto). No new pip deps. Don't commit until
I've reviewed.
```
</content>
