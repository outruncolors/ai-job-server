# SP6 — Trace viewer + pipeline node-graph (frontend)

Sub-phase **SP6** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [05 — SP5](05-sp5-message-action-wrapper.md) · **Next:** [07 — SP7 hardening + docs](07-sp7-hardening-docs.md) · [Sequence](README.md)

Depends on **SP3**, committed. Verified manually in the browser.

```
Implement Phase 2 sub-phase SP6 of Prattletale (iMessage-style roleplay chat): the dev-tools trace
viewer + the pipeline node-graph. SP3 is committed (GET .../trace returns the trace with the enriched
`steps`). Pure frontend.

Read first:
- docs/apps/prattletale/design.md — "Turn-generation pipeline", "The narrative editor is a guard",
  and "Risks / open questions" #6.
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP6" section.
- SP3's committed GET /conversations/{id}/turns/{turn_id}/trace and the trace shape (context_input,
  raw_final_output, parsed_items, reveal_schedule, voice_error/error, and the enriched `steps`
  [{number,id,name,prompt,output}]).
- static/apps/prattletale/prattletale.js (committed) — where model turns render and how per-turn
  affordances are wired (wireRetry/wirePlay).
- The Prompt Pal deep-link convention: /prompt-pal/?app=prattletale&highlight=<entry_id>. See
  app/prompt_pal/service.py::id_for and how Hoodat links into Prompt Pal. The relevant entries are
  (prattletale, turn) [+ its guard], (prattletale, variety).
- docs/reference/ui-standards.md.

Build (additive only) — static/apps/prattletale/:
- A 🔍 TRACE affordance on each MODEL turn (only when a trace exists) -> a modal/panel that fetches
  GET .../trace and shows: the context_input bundle (character/scenario/role/persona/transcript),
  raw_final_output, the parsed_items, the reveal_schedule, and any voice_error/error.
- A NODE-GRAPH of the pipeline for that turn, rendered from the trace's `steps`: ordered nodes
  Turn -> (Variety) -> Guard (omit Variety when the turn had it off), each node clickable to reveal
  its prompt + output (fall back to "(output not captured)" if SP3 took the minimum path). Each node
  deep-links to its Prompt Pal entry. Plain CSS/flex/SVG boxes-and-arrows — NO new graph library, no
  new deps.
- Error turns: the trace viewer still opens (shows error + raw_final_output) so a failed turn is
  debuggable.
- Escape all text; reuse api().

Done when (manual — start .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090):
- generate a model turn -> open its trace -> see the context bundle + raw/parsed output + reveal
  schedule;
- the node-graph shows Turn -> Variety -> Guard (and only Turn -> Guard when variety is off for the
  conversation); each node opens its prompt/output and its Prompt Pal link lands on the right entry;
- open the trace on a forced error turn -> the error shows.
No new automated assertions beyond SP3's API test; run the existing suite to confirm no regression.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto). No new pip deps. Don't commit until
I've reviewed.
```
</content>
