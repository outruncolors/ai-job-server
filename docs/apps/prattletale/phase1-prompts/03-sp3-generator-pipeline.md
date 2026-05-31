# SP3 — Generator pipeline (LLM wired)

Sub-phase **SP3** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [02 — SP2](02-sp2-prompts-parser.md) · **Next:** [04 — SP4 router](04-sp4-router-api.md) · [Sequence](README.md)

Depends on **SP1** (store) + **SP2** (prompts + parser), both committed. Tests mock the executor —
no real GPU node needed.

```
Implement Phase 1 sub-phase SP3 of Prattletale (iMessage-style roleplay chat). This is the
turn-generation pipeline: build context, run the chain executor directly, parse, persist, trace.
SP1 (store) and SP2 (prompts + parser) are committed.

Read first:
- docs/apps/prattletale/design.md — "Turn-generation pipeline", "Commit semantics", "Error
  handling & retry".
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP3" section.
- app/apps/hoodat/generator.py — _resolve_llm, _run_single_step (note the optional guard step
  becoming final_output.txt), run_create scaffolding (create_job/find_job_dir/execute_chain_job).
- app/apps/blaboratory/generator.py — the run-the-executor-directly pattern.
- app/chain/models.py — ChainJobRequest, ChainStep, Alternative, ChainLLMConfig.
- app/chain/executor.py — execute_chain_job(job_id, job_dir, request) signature; final_output.txt.
- app/llm_config.py — get_default_as_chain_llm_config().
- app/jobs.py — create_job(job_type, request_data, input_text), find_job_dir(job_id).
- Committed SP1 store (app/apps/prattletale/store.py) and SP2 prompts/parser
  (app/apps/prattletale/prompts.py).

Build (additive only) — app/apps/prattletale/generator.py:
- GenerationError (and re-point SP2's parser to import it, if you stubbed a local one).
- _resolve_llm(llm: ChainLLMConfig | None) -> ChainLLMConfig — default via
  get_default_as_chain_llm_config(); force enable_thinking=False like Hoodat.
- build_context(conversation, character, transcript) -> dict[str,str] — PURE. Returns
  {character: render_character_context(character), scenario, role_instructions, user_persona,
  transcript}. The transcript value = last config.context_window_turns turns flattened to a
  [User]…/[Counterpart]… script, SKIPPING items with hidden_from_context=True and type
  system_error. An empty user_persona renders the section out cleanly.
- build_turn_request(context_vars, llm) -> ChainJobRequest — steps=[turn, guard]: an llm step
  whose prompt = get_text("prattletale","turn", variables=context_vars), then an llm guard step
  whose prompt = get_guard("prattletale","turn") over {{previous}} (skip the guard step if
  get_guard returns None).
- async run_model_turn(conversation_id, llm=None) -> tuple[dict, str]: load conversation +
  transcript (store); get_character(counterpart_character_id) — missing -> GenerationError;
  build_context; create_job("prattletale_turn", request.model_dump(), input); find_job_dir; await
  execute_chain_job(...); read final_output.txt; parse_items; store.append_model_turn(...,
  job_id=); store.write_trace(... {job_id, context_input, raw_final_output, parsed_items, error});
  return (model_turn, job_id). On ANY failure: store.append_error_turn(message, job_id=) and return
  that turn (do NOT raise to the caller).

Done when tests/apps/test_prattletale_generator.py passes (monkeypatch CONVERSATIONS_DIR to tmp +
monkeypatch execute_chain_job to write a known final_output.txt; stub get_character):
- a seeded conversation + a stubbed tagged-line output -> a committed model turn with ≥1
  correctly-typed item, and traces/<turn>.json exists with the captured fields;
- a stubbed empty/garbage output -> a system_error turn appended (no exception raised to caller);
- build_context excludes hidden_from_context + system_error items and renders an empty persona
  cleanly.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
