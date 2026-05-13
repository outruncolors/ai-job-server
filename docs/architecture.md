# Architecture

## Module map

```
app/
  main.py                   FastAPI app, all route definitions, static mount
  models.py                 Shared Pydantic schemas (requests, responses, stats)
  jobs.py                   Job lifecycle: create, read, list, delete, artifact tracking
  server.py                 get_server_stats(), schedule_restart(), 5s job-count cache
  chain/
    models.py               ChainStep, ChainJobRequest, ChainLLMConfig, ChainStepStatus
    executor.py             execute_chain_job(), _expand_steps(), I/O helpers
    steps/
      llm.py                LLM tool-loop step runner (run_llm_step)
      voice.py              Voice synthesis step runner (run_voice_step)
      write_context.py      Context library write step runner (run_write_context_step)
    llm_client.py           OpenAICompatibleLLMClient — httpx, not requests
    sequences.py            Sequence CRUD, cycle detection (DFS)
    context.py              resolve_context_ids() — loads file or library items
    context_library.py      Context item CRUD backed by config/context_library.json
    template.py             render_template() — {{input}}, {{previous}}, {{context}}, etc.
  mcp/
    registry.py             Hardcoded tool definitions (random_integer, generate_name, format_voice_segments)
    executor.py             execute() — runs a named tool with validated arguments
    router.py               GET /v1/mcp/tools, POST /v1/mcp/tools/{name}/call
    models.py               ToolDefinition, ToolCallRequest, ToolCallResult, ToolCallError
    validator.py            JSON Schema input validation
  omnivoice/
    config.py               OmniVoiceConfig Pydantic model, get/save config from config/omnivoice.json
    manager.py              OmniVoiceManager — tracks active jobs, ephemeral runner availability
    runner.py               OmniVoiceEphemeralRunner — subprocess-based TTS invocation
    router.py               GET/PUT /v1/omnivoice/config, GET /v1/omnivoice/status
  voice_presets.py          Preset CRUD backed by config/voice_presets/
  voice_presets_router.py   GET/POST/DELETE /v1/voice-presets, POST /v1/voice-presets/from-job
  voice_preprocess.py       LLM-based text preprocessing for TTS
  audio_utils.py            WAV segment merging (concatenate with silence padding)

static/
  css/responsive.css        Shared dark-theme styles, breakpoints, mobile nav, #topnav base
  js/nav.js                 Builds top nav from hardcoded config; marks active page
  js/nav-mobile.js          Hamburger nav for narrow viewports
  js/voice-segments.js      Reusable segment list widget for voice pages
  chain/                    Chain Jobs UI (index.html, styles.css, chain.js)
  voice/                    Voice UI (index.html, styles.css, voice.js)
  server/                   Server UI (index.html, styles.css, server.js)
  jobs/                     Jobs browser (index.html, styles.css, jobs.js)
  mcp/                      MCP tool explorer (index.html, styles.css, mcp.js)
  context/                  Context Library UI (index.html, styles.css, context.js)
  image/                    Image UI (index.html, styles.css, image.js)

config/                     Runtime config — gitignored, never commit
  omnivoice.json
  sequences.json
  context_library.json
  voice_presets/
    index.json
    *.wav
```

## Job lifecycle

Every job transitions through these statuses stored in `status.json`:

```
queued → running → done
                 ↘ error
```

- **queued**: Job directory created, `request.json` and `status.json` written. No processing yet.
- **running**: Background task started. For chain jobs, `status.json` is updated with `step_count`, `progress`, `current_step_index`, and `current_step_name` as each step runs.
- **done**: All processing complete. `artifacts.json` written. For chain jobs, `final_output.txt` and `outputs` field added to `status.json`.
- **error**: Processing failed. `error` field set in `status.json`. For chain jobs, the failed step's `status.json` also records the error.

Note: the server stats API maps `"error"` → `"failed"` in job counts (see `_STATUS_MAP` in `server.py`).

### Job directory layout

```
JOBS_BASE/YYYY-MM-DD/<job_id>/
  request.json          original request body
  status.json           current job status + metadata
  logs.txt              append-only execution log
  artifacts.json        list of output files with sizes
  final_output.txt      (chain only) last LLM step's text output
  steps/                (chain only)
    001_<step_id>/
      status.json       step status
      context.txt       resolved context text (llm steps)
      prompt.txt        rendered prompt sent to LLM (llm steps)
      output.txt        LLM response (llm steps)
      tool_calls.json   tool call history (llm steps with tools)
      output.wav        synthesized audio (voice steps)
      auto_segment_prompt.txt  (voice steps with auto_segment)
      auto_segment_raw.txt     (voice steps with auto_segment)
      output.json       saved context item data (write_context steps)
    002_<step_id>/
      ...
```

## Chain execution flow

```
POST /v1/jobs/chain
  → create_job()                   write request.json, status.json (queued)
  → patch_initial_chain_status()   add step_count, progress fields
  → background: execute_chain_job()
      → list_sequences()           load seq_map for expansion
      → _expand_steps()            flatten sequence refs, prefix names, depth guard
      → loop over flat_steps:
          → _write_chain_status()  progress update
          → run_llm_step()         or run_voice_step() or run_write_context_step()
          → _write_step_status()   done or error
          → _append_log()
      → write final_output.txt
      → write artifacts.json
      → _write_chain_status(done)
```

The step runners (`steps/llm.py`, `steps/voice.py`, `steps/write_context.py`) raise exceptions on failure; `executor.py` catches them and writes the error state. Steps never call `_write_chain_status` or `_append_log` directly.

## Config directory

`config/` lives at the repo root and is gitignored. It is created automatically on first use.

| File | Purpose |
|------|---------|
| `omnivoice.json` | OmniVoice runtime settings (TTS config, custom prompts) |
| `sequences.json` | Saved chain sequences |
| `context_library.json` | Context item index (content stored inline) |
| `voice_presets/index.json` | Voice preset metadata |
| `voice_presets/*.wav` | Voice sample WAV files (3–10s each) |

## Key design decisions

**File-based jobs**: Each job is a plain directory on disk. No database required. Easy to inspect, back up, and debug. The tradeoff is no atomic cross-job queries, but the workload (one job at a time, human-scale traffic) doesn't need them.

**httpx, not requests**: All HTTP calls use `httpx` with `async with httpx.AsyncClient()` for compatibility with FastAPI's async event loop.

**Static SPA UI**: The frontend is served as static files from `StaticFiles`. Each page is a self-contained SPA — no server-side templating. `nav.js` generates the nav bar dynamically to avoid duplication.

**Step runner isolation**: Each step type is in its own module under `steps/`. Runners raise on failure; the executor in `executor.py` owns all status writes. This prevents circular imports (`steps/` imports from `chain/` utilities but not from `executor.py`).
