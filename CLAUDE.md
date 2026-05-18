# ai-job-server — Claude working notes

## Environment

- **Python**: `.venv/bin/python` (3.13) — never use bare `python` or `python3`
- **Tests**: `.venv/bin/pytest` — `asyncio_mode = auto`, tmp_path + monkeypatch for I/O
- **Syntax check**: `.venv/bin/python -m py_compile <file>`
- **Dev server**: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`

## Key files

| File | Purpose |
|------|---------|
| `app/main.py` | All FastAPI routes |
| `app/jobs.py` | Job lifecycle: `create_job()`, artifact tracking, file serving |
| `app/job_queue.py` | `JobQueue` — single-worker async queue all create-job endpoints flow through; `recover_interrupted_jobs()` for startup recovery |
| `app/chain/models.py` | Pydantic schemas: `ChainStep`, `ChainJobRequest`, `ChainLLMConfig` |
| `app/chain/executor.py` | `execute_chain_job()`, `_expand_steps()`, step loop; shared helpers (`_write_chain_status`, `_append_log`) |
| `app/chain/steps/llm.py` | `run_llm_step()` — LLM tool loop, Gemma fallback parser |
| `app/chain/llm_swap.py` | `ensure_loaded_for_step()` — resolves step preset (`step.preset` → `llamacpp.default_preset` → skip), POSTs to peer's `/v1/llamacpp/ensure-loaded`, returns overridden `ChainLLMConfig` + swap log line |
| `app/chain/steps/voice.py` | `run_voice_step()` — TTS synthesis, auto-segmentation |
| `app/chain/steps/write_context.py` | `run_write_context_step()` — saves text output to context library |
| `app/chain/sequences.py` | Sequence CRUD + `check_for_cycles()` |
| `app/chain/context.py` | `resolve_context_ids()` |
| `app/chain/context_library.py` | Context item CRUD (JSON index) |
| `app/tickets/store.py` | Ticket queue CRUD + reorder + `next_ticket()` (JSON index) |
| `app/image_prompts.py` | Saved image prompt CRUD (JSON index) — name/prompt/workflow |
| `app/chain/template.py` | `render_template()` — vars: `{{input}}` `{{previous}}` `{{context}}` `{{step_index}}` `{{step_name}}` |
| `app/chain/llm_client.py` | `OpenAICompatibleLLMClient` — uses `httpx`, not `requests` |
| `app/mcp/registry.py` | Hardcoded tool definitions (`random_integer`, `generate_name`, `format_voice_segments`) |
| `app/mcp/executor.py` | `execute()` — runs a named tool with validated arguments |
| `app/comfyui/config.py` | `ComfyUIConfig` model, get/save from `config/comfyui.json` |
| `app/comfyui/manager.py` | `ComfyUIManager` — long-lived process: start/stop/restart, readiness probe, GPU status |
| `app/comfyui/client.py` | `ComfyUIClient` — httpx wrapper for ComfyUI HTTP API (port 8188) |
| `app/comfyui/workflows.py` | `list_workflows()`, `introspect_params()`, `inject_params()` — workflow discovery + param injection |
| `app/comfyui/runner.py` | `execute_image_job()` — submits prompt, polls history, fetches output images |
| `app/comfyui/router.py` | Routes: `/v1/comfyui/{status,start,stop,restart,config,workflows,system_stats}` |
| `app/llamacpp/config.py` | `LlamaCppConfig` model (binary_path/port/default_preset/models_dir); get/save from `config/llamacpp.json` |
| `app/llamacpp/manager.py` | `LlamaCppManager` — long-lived `llama-server` process; `ensure_loaded(preset_dict)` swap-locks on full-args hash, 180s readiness deadline via `/health`, 500-line stdout/stderr ring buffer, `os.killpg` cleanup, `adopt()` |
| `app/llamacpp/router.py` | Routes: `/v1/llamacpp/{status,start,stop,restart,config,models,ensure-loaded,logs}`; `_resolve_preset` looks up named presets via `app.llm_presets` (404 if missing) or accepts an inline dict |
| `app/llm/models.py` | `LLMPreset` Pydantic schema for llama.cpp load presets: `name` (kebab-case), `model_path`, `args` dict, `capabilities` (`text`/`vision`), `description?` |
| `app/llm_presets.py` | LLM preset CRUD over `config/llm_presets/<name>.json` — `list_presets`/`get_preset`/`save_preset`/`delete_preset`, atomic writes |
| `app/llm_config.py` | LLM **endpoint** preset CRUD (OpenAI-compatible HTTP endpoints used by chain LLM steps + voice auto-segment); route prefix `/v1/llm-endpoints` |
| `app/omnivoice/runner.py` | `OmniVoiceEphemeralRunner` — subprocess-based TTS invocation |
| `app/voice_presets.py` | Preset CRUD backed by `config/voice_presets/` |
| `app/profiles/models.py` | `MasterProfile` Pydantic schema bundling every declarative-config domain (llm/omnivoice/comfyui/workflows/voice presets/wildcards/context items/image prompts/chain sequences) + binary asset manifest |
| `app/profiles/exporter.py` | `build_master_profile(name, description)` snapshots live config; `list_required_assets(profile)` returns binary asset paths (voice WAVs) |
| `app/profiles/importer.py` | `apply_master_profile(profile, mode='replace'\|'merge', asset_source)` writes every domain back to its on-disk store (atomic per-domain), copies referenced WAVs, returns an `ImportReport` |
| `app/profiles/bundle.py` | `pack_profile(profile, out_path)` and `unpack_profile(zip_path)` — `.zip` bundle with `master.json` + `assets/voice_presets/<wav>`; unpack validates `schema_version`, zip-slip-safe, returns flat asset dir for importer |
| `app/profiles/store.py` | Named-profile store: `save_profile`, `list_profiles`, `get_profile`, `delete_profile`, `set_active`, `get_active`, plus `export_to_zip`/`import_as_new`/`apply_from_zip` for bundle I/O; profiles live under `config/profiles/<id>/{master.json,assets/}` with `index.json` + `active.json` markers |
| `app/server.py` | `get_server_stats()`, `schedule_restart()`, 5s job-count cache (`_get_job_counts()`); multi-machine config (`ServerConfig`, `Peer`, `get_local_capabilities()`, `get_peers()`, `find_peer_for_capability()`, `get_git_sha()`) and the `requires_capability(cap)` FastAPI dependency that 503s out-of-capability routes |
| `static/js/nav.js` | Builds top nav from `NAV_ITEMS` array; auto-marks active page by pathname |
| `static/js/voice-segments.js` | Reusable segment list widget (`vsAddSegment`, `vsCollectSegments`) |
| `static/js/resolved-prompt.js` | `renderResolvedPrompt(container, items)` — shows the resolved prompt + per-token wildcard substitutions above voice/image output panels; pairs with `resolveWildcardsTracked()` in `wildcards.js` |
| `static/js/profiles-widget.js` | Profile widget pinned to right of `#topnav` on every page: `[select ▾] [💾] [⬇] [⬆]`; select-change activates, save overwrites or expands to `[name ✓ ✗]` for `(new profile)`; self-contained (works without api/toast/escape) |
| `static/css/responsive.css` | Shared responsive styles (dark theme, breakpoints, `#topnav`) |

### Frontend page layout

Each page under `static/<page>/` has three files (minimum):
- `index.html` — slim skeleton (~60–120 lines): meta, link tags, layout HTML, no inline CSS or JS
- `styles.css` — page-specific styles only
- `<page>.js` — shared utilities + init (loaded last so tab modules can call its globals from handlers)

Pages can split into multiple JS modules. Script load order: `nav.js` → (page deps / tab modules) → `<page>.js` → `nav-mobile.js`. The voice page loads `voice-segments.js` before `voice.js`. The image page loads `generate-tab.js`, `prompts-tab.js` before `image.js`.

## Architecture

- **Jobs** stored at `JOBS_BASE/YYYY-MM-DD/<uuid>/` with `request.json`, `status.json`, `logs.txt`, `artifacts.json`
- **Chain jobs** add `steps/NNN_<step_id>/` subdirs; `_expand_steps()` flattens sequence references before execution
- **Config** (sequences, context items, voice presets, omnivoice settings, comfyui settings + workflows) lives in `config/` — **gitignored**, never commit
- **Step types**: `llm`, `voice`, `write_context`, `sequence` (sequence expands inline; only llm updates `text_output`)
- **Step runner isolation**: step runners in `app/chain/steps/` raise exceptions on failure; `executor.py` owns all status writes and log appends — steps never import from `executor.py`
- **Cycle detection**: DFS in `sequences.py`; enforced at save time (422) and run time (depth guard at 20)
- **Job status on disk**: `"queued"`, `"running"`, `"done"`, `"error"` — note `"error"` maps to `"failed"` in server stats API (see `_STATUS_MAP` in `app/server.py`)
- UI is dark-theme monospace; two-panel layout (controls left, output right); tab switching via `switchTab()`
- **Toast system**: `Map`-based, id-deduplicated; defined in `static/server/server.js` and `static/mcp/mcp.js`; requires `<div id="toast-stack"></div>` in HTML
- **psutil**: `psutil.cpu_percent()` must be called once at import (no interval) to prime the sampler before using `interval=None` calls
- **ComfyUI**: unlike OmniVoice (ephemeral subprocesses), ComfyUI is a long-lived HTTP server at `127.0.0.1:8188`. `ComfyUIManager` starts it at FastAPI boot (`lifespan` in `main.py`), adopts it if already running, and manages the process group with `os.killpg`. Workflows are API-format JSON in `config/comfyui-workflows/`; params are auto-detected by node class. Install: `bash scripts/comfyui-setup.sh`
- **llama.cpp**: mirrors the ComfyUI pattern — long-lived `llama-server` process (default `127.0.0.1:8080`). `LlamaCppManager` only instantiates on nodes with `"llm"` capability and adopts an already-running server at boot. Model swaps go through `POST /v1/llamacpp/ensure-loaded` with either an inline preset dict (`{"model_path": ..., "args": {...}}`) or a named preset (`{"preset": "name"}` — resolved via `app.llm_presets`, 404 if missing). The swap key is a stable hash of the full preset (changing `ctx_size` or `n_gpu_layers` triggers a reload). Same hash → no-op; different hash → SIGTERM the existing process group, spawn the new args, poll `/health` for up to 180s. On timeout the manager raises `LlamaCppLoadError`, the route returns 503, and `current_preset_hash` is cleared — **no silent fallback** to the previous model. stdout/stderr stream into a 500-line `collections.deque` ring buffer surfaced via `GET /v1/llamacpp/logs?tail=N`.
- **LLM presets vs LLM endpoints — two separate stores**: `/v1/llm-presets` (`app/llm_presets.py`, `config/llm_presets/<name>.json`) describes *which GGUF + CLI args* to load on the local `llama-server` (feeds `ensure-loaded`). `/v1/llm-endpoints` (`app/llm_config.py`, `config/llm_config.json`) describes *where to send OpenAI-compatible HTTP requests* for chain LLM steps + voice auto-segmentation. The endpoint route was previously `/v1/llm-presets`; it was renamed when model presets landed (UI consumers: `static/server/llm-tab.js`, `static/voice/voice.js`, `static/chain/chain.js`).
- **Multi-machine capabilities**: `config/server.json` declares this node's `capabilities` (`web`/`voice`/`image`/`llm`) and known `peers`. Absent file → all-capabilities (single-machine). Routes that need a missing capability return `503 {"error":"capability_unavailable","needed":<cap>,"where":<peer-host>}` via `Depends(requires_capability(cap))` (see `app/main.py` — `POST /v1/jobs/image`, `POST /v1/jobs/voice`, the comfyui and omnivoice routers). Chain jobs are **not** route-gated; per-step gating is deferred. Endpoints: `GET /v1/server/capabilities`, `GET /v1/server/peers`, `GET /v1/server/health` (incl. `git_sha`). Full design: `docs/reference/multi-machine-plan.md`.

## Common patterns

```python
# HTTP calls — always httpx, not requests
import httpx
async with httpx.AsyncClient() as client:
    r = await client.post(url, json=body, timeout=30)

# Job status write
_write_chain_status(job_dir, "running", progress=0.5, ...)

# Artifact collection iterates executed_step_dirs: list[tuple[str, str]]  # (dir_name, step_type)
```

```javascript
// api() in all pages except mcp.js prepends /v1 automatically
const data = await api('/chain-sequences');           // GET → /v1/chain-sequences
const saved = await api('/chain-sequences', 'POST', body);

// mcp.js uses full paths directly (no /v1 prepend)
const data = await api('/v1/mcp/tools');

// Escape before inserting into innerHTML
_escHtml(str)
```

```python
# TestClient runs background tasks synchronously — monkeypatch at the importing module
# e.g., patch app.main.schedule_restart, NOT app.server.schedule_restart
monkeypatch.setattr(m, "schedule_restart", lambda: ...)
```

## Documentation

Full developer docs are in `docs/`:
- `docs/architecture.md` — module map, job lifecycle, chain execution flow
- `docs/api.md` — complete REST API reference with curl examples
- `docs/chain-jobs.md` — step type reference, template vars, sequences, MCP tools, voice auto-segmentation
- `docs/configuration.md` — env vars, `omnivoice.json` fields, external services, dev/prod setup
- `docs/comfyui-setup.md` — ComfyUI install, optimization flags, workflow authoring, troubleshooting
- `docs/multi-machine.md` — primary/secondary deployment (bare repo, systemd user unit, capability gating, cutover); design doc at `docs/reference/multi-machine-plan.md`
