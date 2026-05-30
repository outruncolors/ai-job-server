# Architecture

## Module map

```
app/
  main.py                FastAPI app, route definitions, lifespan, static mount
  models.py              Shared Pydantic request/response schemas
  jobs.py                Job lifecycle: create, list, get, delete, artifact tracking
  server.py              get_server_stats(), schedule_restart(), 5s job-count cache
  llm_config.py          LLM preset CRUD (config/llm_config.json)
  wildcards.py           Wildcard CRUD + %%token%% expansion
  voice_presets.py       Voice preset CRUD
  voice_presets_router.py  GET/POST/DELETE /v1/voice-presets, /from-job
  audio_utils.py         WAV concatenation with silence padding
  chain/
    executor.py          execute_chain_job() — number-keyed graph walker, weighted
                         alternative picker, goto + visit_cap + 2000-run total budget,
                         per-invocation step dirs, _expand_steps() for sequence refs
    models.py            ChainStep, Alternative, SequenceVariable, ChainJobRequest,
                         ChainLLMConfig. ChainStep has a model_validator that hoists
                         v1-shorthand keys onto a single alternative.
    sequences.py         Sequence CRUD (schema_version 2), DFS cycle detection,
                         step-number / goto-target / weight validation
    template.py          render_template() — {{input}} {{previous}} {{context}}
                         {{step_index}} {{step_name}} {{N_input}} {{N_output}} {{var.NAME}}
    context.py           resolve_context_ids()
    context_library.py   Context item CRUD
    llm_client.py        OpenAICompatibleLLMClient (httpx)
    llm_swap.py          ensure_loaded_for_step(step, alt, …) — per-alt preset routing
    steps/
      llm.py             run_llm_step() — tool loop, Gemma fallback parser
      voice.py           run_voice_step() — synthesis, auto-segmentation
      write_context.py   run_write_context_step()
      image_prompt.py    run_image_prompt_step() — saves to /v1/image-prompts
      save_wildcard.py   run_save_wildcard_step() — append or create wildcard list
      create_ticket.py   run_create_ticket_step() — file ticket on the queue
  mcp/
    registry.py          Hardcoded tool definitions
    executor.py          execute() — schema-validated tool invocation
    router.py            GET /v1/mcp/tools, POST /v1/mcp/tools/{name}/call
    validator.py         JSON Schema input validation
  prompt_pal/            App-agnostic prompt registry (config/prompt_pal/<id>.json)
    compose.py           compose() — {prompt, variables} / {prompt_id} resolver
    models.py            PromptEntry, PromptEntryPatch
    store.py             File-per-doc CRUD + get_by_app_key, node_for_id
    registry.py          register() table + seed_registered() (seed-if-absent)
    service.py           get_text(app, key) — store-wins-else-default; id_for()
    router.py            /v1/prompt-pal/entries CRUD + /preview
  apps/                  Consumer experiences (own package per app)
    blaboratory/         Virtual lab of AI residents (rooms, sim, memory)
    hoodat/              Character creation/management
      models.py          Character / CharacterDraft, FIELD_SPECS
      characters_store.py  File-per-doc (config/hoodat/characters/<id>.json)
      prompts.py         Registers IDEATE/ASSEMBLE/field.*/avatar prompts
      generator.py       run_create() / run_field() — direct execute_chain_job
      avatars.py         generate (ComfyUI image) / upload / serve
      exports.py         Targeted Exports (Prompt Pal entries, run over the doc)
      router.py          /v1/apps/hoodat — characters, fields, avatar, exports
  omnivoice/
    config.py            OmniVoiceConfig + persistence
    manager.py           Tracks active TTS jobs / runner availability
    runner.py            Per-job subprocess invocation
    router.py            GET/PUT /v1/omnivoice/config, GET /status
  comfyui/
    config.py            ComfyUIConfig + persistence
    manager.py           Process lifecycle: start/stop/restart, adopt, GPU/queue status
    client.py            httpx wrapper over ComfyUI HTTP API
    workflows.py         list_workflows(), validate, inject_params()
    runner.py            execute_image_job() — submit, poll, fetch outputs
    router.py            /v1/comfyui/{status,start,stop,restart,config,workflows,system_stats}
  ticks/
    persistence.py       Tick CRUD (config/ticks/index.json)
    scheduler.py         Async loop, 10s poll, overlap guard

static/
  css/responsive.css     Design tokens, breakpoints, mobile nav
  css/components.css     Shared component classes
  js/nav.js              Top-nav builder + active-page marker
  js/nav-mobile.js       Hamburger menu for mobile
  js/api.js              fetch wrapper (auto /v1 prefix)
  js/escape.js           _escHtml
  js/toast.js            Toast stack
  js/poll.js             pollJob()
  js/voice-segments.js   Multi-segment text widget
  js/field-controls.js   FieldControls.attach() — reusable hover-control affordance
  js/marked.min.js       Markdown renderer for docs page
  css/field-controls.css Hover-cluster styles for FieldControls
  <page>/                index.html, styles.css, <page>.js per nav page
  prompt-pal/            Prompt Pal management UI (list/filter/edit/deep-link)
  apps/<name>/           Per-app frontend (blaboratory, hoodat)

docs/                    Markdown rendered by the in-site viewer
config/                  Runtime data (gitignored)
```

## Job lifecycle

Statuses in `status.json`: `queued` → `running` → `done` | `error` | `cancelled`.

- **queued** — job dir created, request/status written, sitting in the global queue waiting for the worker
- **running** — queue worker is executing the job; chain jobs update `step_count`, `progress`, `current_step_index`, `current_step_name`
- **done** — all work complete; `artifacts.json` written; chain jobs also write `final_output.txt` and an `outputs` field on `status.json`
- **error** — failure; `error` set on `status.json` (and on the failing step's `status.json` for chains). Jobs left in `running` across a server restart are rewritten to `error` with reason `"interrupted by server restart"` (the queue worker cannot safely resume mid-step).
- **cancelled** — `DELETE /v1/jobs/{id}` was called while the job was still `queued`; the job dir is preserved on disk for audit, the queue worker skips it when it pops it

`_STATUS_MAP` in `app/server.py` translates the on-disk `error` to `failed` for the stats API. Cancelled jobs are not counted in the stats buckets.

## Global job queue

All three create-job endpoints (`/v1/jobs/image`, `/v1/jobs/voice`, `/v1/jobs/chain`) and tick-fired chain jobs flow through a single `JobQueue` in `app/job_queue.py` rather than FastAPI `BackgroundTasks`. The queue has one worker coroutine that pulls runners off `asyncio.Queue` and awaits them one at a time — so back-to-back POSTs serialize.

- Worker lifecycle: started in `app/main.py` lifespan; stopped in shutdown. Lazy-started on first `enqueue` if lifespan didn't run (e.g. some test paths).
- On startup, `recover_interrupted_jobs(JOBS_BASE)` scans the job tree: any `running` job is rewritten to `error`; any `queued` job is re-enqueued in `created_at` order.
- `JobQueue.cancel_queued(job_id)` drops a queued job from in-memory pending tracking. The caller is responsible for writing the new on-disk status; the worker re-reads `status.json` when it pops an item and skips anything not still `queued`.
- `queue_depth` is exposed in `/v1/server/stats`.

### Job directory layout

```
JOBS_BASE/YYYY-MM-DD/<job_id>/
  request.json
  status.json
  logs.txt
  artifacts.json
  final_output.txt            # chain only
  workflow.json               # image only — resolved workflow after prompt injection
  output.wav                  # voice only
  auto_segment_segments.json  # voice w/ auto-segment
  steps/                      # chain only
    NNN_<name>/
      status.json
      prompt.txt              # llm
      output.txt              # llm
      context.txt             # llm if context_ids
      tool_calls.json         # llm if tools
      output.wav              # voice
      auto_segment_prompt.txt # voice w/ auto-segment
      auto_segment_raw.txt    # voice w/ auto-segment
      output.json             # write_context | image_prompt | save_wildcard | create_ticket
```

Step directories are named `NNN_id` on first visit and `NNN_id_xII` on re-runs (only possible when a `goto` points back at the step). `II` is a zero-padded invocation index starting at `01`.

## Chain execution flow

```
POST /v1/jobs/chain
  → create_job()                  request.json + status.json (queued)
  → patch_initial_chain_status()  add step_count, progress, …
  → enqueue on JobQueue (single worker, sequential)
  → eventually: execute_chain_job()
      → list_sequences()          seq_map for expansion
      → _renumber_top_level()     fill in missing step numbers
      → _expand_steps()           flatten sequence refs (depth ≤ 20)
      → walk by number until ptr is None or a budget trips:
          visit_cap (per-step, default 100) and 2000-run total budget
          _pick_alternative()     random.choices on alt weights
          if goto: jump to alt.target_step (or fall_through → next number)
          else:
            _write_chain_status() progress update
            run_<type>_step(step_dir, step, alt, …)
            step_inputs[ptr].append(rendered_prompt)
            step_outputs[ptr].append(result)        # empty for non-llm types
            text_output = result                    # llm only
            _write_step_status()  done | error
            _append_log()
      → write final_output.txt
      → write artifacts.json
      → _write_chain_status(done)
```

Step runners under `app/chain/steps/` raise on failure. The executor owns all status writes and log appends — step modules never import from `executor.py`, which keeps the dependency graph acyclic.

## Wildcard expansion

`%%token%%` tokens in any prompt-like field (chain step prompts, voice text, image prompts, context pre/post) are replaced just before submission. Replacement is weighted-random per occurrence using the wildcard's entry weights. What's persisted in `request.json` is the expanded text — reruns won't re-roll.

## Key design decisions

**File-based jobs.** No database. Each job is a directory inspectable with shell tools, trivially backed up.

**httpx everywhere.** Async clients keep the FastAPI event loop unblocked during long-running LLM calls.

**ComfyUI is long-lived; OmniVoice is ephemeral.** ComfyUI runs as a single HTTP server adopted or started at lifespan; OmniVoice spawns one subprocess per voice job. Mismatch is intentional — ComfyUI's startup cost is too high to repeat per job, OmniVoice's is small.

**Step runner isolation.** Steps know how to do their work and raise on failure. The executor owns all status and log state. This prevents circular imports and concentrates I/O concerns.

**Static SPA UI.** No template engine. Each page is a self-contained set of HTML/CSS/JS in `static/<page>/`. `nav.js` builds the nav from a single config array shared by every page.
