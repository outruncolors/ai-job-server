# SP1 — Transcript editing API (edit / hide / delete)

Sub-phase **SP1** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** — · **Next:** [02 — SP2 conversation settings API](02-sp2-conversation-settings-api.md) · [Sequence](README.md)

Self-contained: pure store ops + HTTP endpoints. No LLM, no network, no frontend.

```
Implement Phase 2 sub-phase SP1 of Prattletale (iMessage-style roleplay chat): the transcript
editing API — edit a message's text, hide/show a message from context, delete a message, delete a
turn. All in place on disk. No LLM, no frontend.

Read first:
- docs/apps/prattletale/design.md — "Terminology & data model" (item shape, hidden_from_context,
  the <turn_id>-i<NN> item-id format). Skim "Scope by phase" for context.
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP1" section.
- app/apps/prattletale/store.py (committed) — mirror replace_turn / apply_audio: re-read the
  transcript before writing, atomic write, _touch_conversation. Note ids are stable / never
  renumbered.
- app/apps/prattletale/generator.py (committed) — _flatten_transcript, so you can see exactly how
  hidden_from_context and empty turns drop out of the model context.
- app/apps/prattletale/router.py (committed) — the 404 patterns and the per-item audio route's
  turn/item lookup.

Build (additive only):
1. app/apps/prattletale/store.py — new ops, each re-reading before the atomic write and returning
   None on a missing conversation/turn/item:
   - edit_item(conversation_id, turn_id, item_id, text) -> dict|None: overwrite one item's text in
     place (id/type/audio/hidden unchanged); returns the updated turn.
   - set_item_hidden(conversation_id, turn_id, item_id, hidden: bool) -> dict|None.
   - delete_item(conversation_id, turn_id, item_id) -> dict|None: drop one item; if the turn is left
     with zero items, delete the whole turn (pick + document a clear return shape for that case).
   - delete_turn(conversation_id, turn_id) -> bool.
   Do NOT renumber surviving turns/items; next_turn_seq stays monotonic and ids stay stable.
2. app/apps/prattletale/router.py — endpoints (404 on missing conversation/turn/item):
   - PATCH /conversations/{id}/turns/{turn_id}/items/{item_id} with body {text?, hidden_from_context?}
     applying whichever fields are set; returns the updated turn.
   - DELETE /conversations/{id}/turns/{turn_id}/items/{item_id} -> updated turn (or a turn-deleted
     signal when it removed the last item).
   - DELETE /conversations/{id}/turns/{turn_id} -> 204.

Done when tests/apps/test_prattletale_edit.py passes (monkeypatch store.CONVERSATIONS_DIR to
tmp_path):
- edit_item changes only text and round-trips via get_transcript;
- set_item_hidden(...True) makes generator.build_context exclude that item from the rendered
  {transcript} (assert on the flattened string);
- delete_item on a turn's only item removes the turn; delete_turn removes a turn and leaves the
  other turns' ids unchanged;
- every op / endpoint 404s on a missing id.
Run the full suite (.venv/bin/pytest) since router.py changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
No model change — Item already has text + hidden_from_context. Don't commit until I've reviewed.
```
</content>
