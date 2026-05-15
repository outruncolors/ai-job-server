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
    executor.py          execute_chain_job(), _expand_steps(), step loop, status writes
    models.py            ChainStep, ChainJobRequest, ChainLLMConfig
    sequences.py         Sequence CRUD, DFS cycle detection
    template.py          render_template() — {{input}} {{previous}} {{context}} …
    context.py           resolve_context_ids()
    context_library.py   Context item CRUD
    llm_client.py        OpenAICompatibleLLMClient (httpx)
    steps/
      llm.py             run_llm_step() — tool loop, Gemma fallback parser
      voice.py           run_voice_step() — synthesis, auto-segmentation
      write_context.py   run_write_context_step()
  mcp/
    registry.py          Hardcoded tool definitions
    executor.py          execute() — schema-validated tool invocation
    router.py            GET /v1/mcp/tools, POST /v1/mcp/tools/{name}/call
    validator.py         JSON Schema input validation
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
  js/marked.min.js       Markdown renderer for docs page
  <page>/                index.html, styles.css, <page>.js per nav page

docs/                    Markdown rendered by the in-site viewer
config/                  Runtime data (gitignored)
```

## Job lifecycle

Statuses in `status.json`: `queued` → `running` → `done` | `error`.

- **queued** — job dir created, request/status written, no work started
- **running** — background task active; chain jobs update `step_count`, `progress`, `current_step_index`, `current_step_name`
- **done** — all work complete; `artifacts.json` written; chain jobs also write `final_output.txt` and an `outputs` field on `status.json`
- **error** — failure; `error` set on `status.json` (and on the failing step's `status.json` for chains)

`_STATUS_MAP` in `app/server.py` translates the on-disk `error` to `failed` for the stats API.

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
      output.json             # write_context
```

## Chain execution flow

```
POST /v1/jobs/chain
  → create_job()                  request.json + status.json (queued)
  → patch_initial_chain_status()  add step_count, progress, …
  → background: execute_chain_job()
      → list_sequences()          seq_map for expansion
      → _expand_steps()           flatten sequence refs (depth ≤ 20)
      → for each flat step:
          _write_chain_status()   progress update
          run_llm_step | run_voice_step | run_write_context_step
          _write_step_status()    done | error
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
