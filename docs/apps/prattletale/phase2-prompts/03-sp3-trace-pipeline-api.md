# SP3 — Trace + pipeline read API (dev-tools backend)

Sub-phase **SP3** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [02 — SP2](02-sp2-conversation-settings-api.md) · **Next:** [04 — SP4 config view](04-sp4-config-view.md) · [Sequence](README.md)

Self-contained: a read endpoint + an additive trace enrichment. **Independent of SP1/SP2 —
parallel-able.** No frontend; uses a stubbed executor in tests.

```
Implement Phase 2 sub-phase SP3 of Prattletale (iMessage-style roleplay chat): the trace + pipeline
read API — expose the per-model-turn debug trace over HTTP, and (recommended) enrich it with the
ordered pipeline steps + their output so the SP6 trace viewer and node-graph render from the trace
alone (keeping the conversation folder self-describing). No frontend.

Read first:
- docs/apps/prattletale/design.md — "Turn-generation pipeline" (the turn -> (variety) -> guard
  chain) and "Risks / open questions" #6 (trace size).
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP3" section.
- app/apps/prattletale/generator.py (committed) — build_turn_request builds the ordered steps;
  run_model_turn writes the trace via store.write_trace ({job_id, context_input, raw_final_output,
  parsed_items, reveal_schedule, voice_error, error}).
- app/apps/prattletale/store.py (committed) — _trace_path, write_trace.
- app/chain/executor.py (committed) — the per-step steps/NNN_<id>/ dirs + their output files, and
  final_output.txt (so you know where intermediate step outputs land on disk).

Build (additive only):
1. app/apps/prattletale/store.py — get_trace(conversation_id, turn_id) -> dict|None (read
   traces/<turn>.json); optional list_traces(conversation_id) -> list[str].
2. app/apps/prattletale/router.py — GET /conversations/{id}/turns/{turn_id}/trace -> the trace dict
   (404 when the trace or the conversation is absent).
3. Trace enrichment (recommended; the trace is a free dict, so NO Pydantic/model migration): in
   generator.run_model_turn, after execute_chain_job, capture an ordered `steps` list
   [{number, id, name, prompt, output}] by pairing the request steps from build_turn_request with the
   outputs the executor wrote under steps/NNN_<id>/ (final_output.txt is the last step). Add `steps`
   to the trace dict. Best-effort: a step whose output can't be read records output: null rather than
   failing the turn. If reading step dirs is too fiddly, the MINIMUM acceptable enrichment is the
   ordered step identities + their rendered prompts (no per-step output) — note the limitation.

Done when tests/apps/test_prattletale_trace.py passes (monkeypatch store dirs; stub execute_chain_job
to write a known final_output.txt as the other prattletale tests do):
- after a model turn, GET .../trace returns the trace with job_id/context_input/raw_final_output/
  parsed_items;
- the enriched `steps` list is ordered turn (-> variety) -> guard and matches what build_turn_request
  produced for the conversation's config (variety on vs off changes the step count);
- GET .../trace 404s for a turn with no trace and for a missing conversation.
Run the full suite since router.py + generator.py changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
</content>
