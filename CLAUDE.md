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
| `app/chain/models.py` | Pydantic schemas: `ChainStep`, `Alternative`, `SequenceVariable`, `ChainJobRequest`, `ChainLLMConfig`. `ChainStep` has `number`, `visit_cap`, `alternatives: list[Alternative]`. A `model_validator(mode='before')` hoists v1-shorthand flat keys (`prompt`, `tools`, `preset`, `ctx_*`, `voice_*`, `sequence_id`, `target_step`, `fall_through`, …) into a single alternative so simple callers and existing tests keep parsing. |
| `app/chain/executor.py` | `execute_chain_job()` — number-keyed graph walker. Picks one alternative per visit with `random.choices` over relative weights; handles `goto` (jump to `target_step` or `fall_through` to next number); enforces per-step `visit_cap` (default 100) and a 2000-run total budget. Step dirs are `NNN_id` on first visit, `NNN_id_xII` on re-runs. Per-invocation `step_inputs[N]` / `step_outputs[N]` feed `{{N_input}}` / `{{N_output}}`. Only `llm` steps mutate `text_output`. |
| `app/chain/steps/llm.py` | `run_llm_step(step_dir, step, alt, request, client, text_output, step_index, …)` — LLM tool loop, Gemma fallback parser. Reads `alt.prompt` / `alt.tools` / `alt.context_ids` / `alt.preset`. |
| `app/chain/llm_swap.py` | `ensure_loaded_for_step(step, alt, base_llm, prev_preset)` — resolves the chosen alternative's preset (`alt.preset` → `llamacpp.default_preset` → skip), POSTs to peer's `/v1/llamacpp/ensure-loaded` (control plane, FastAPI port), then GETs `/v1/llamacpp/config` to discover the llama-server port (data plane) and returns overridden `ChainLLMConfig` + swap log line. **Two ports**: `config/server.json` peers carry the FastAPI port (~8090); the llama-server port (~8080) is fetched from the peer's llamacpp config because it's not in the peer manifest. |
| `app/chain/steps/voice.py` | `run_voice_step(step_dir, step, alt, text, …)` — TTS synthesis, auto-segmentation. Reads voice fields from `alt`. |
| `app/chain/steps/write_context.py` | `run_write_context_step(step_dir, step, alt, text_output)` — saves to context library. |
| `app/chain/steps/image_prompt.py` | `run_image_prompt_step()` — calls `app.image_prompts.create_prompt(rendered_name, body, workflow)`. Does not mutate `text_output`. |
| `app/chain/steps/save_wildcard.py` | `run_save_wildcard_step()` — `mode=append` looks up existing wildcard by name and appends; `mode=create` always creates. Does not mutate `text_output`. |
| `app/chain/steps/create_ticket.py` | `run_create_ticket_step()` — calls `app.tickets.store.create_ticket(rendered_title, rendered_description, file_hints)`. Does not mutate `text_output`. |
| `app/chain/sequences.py` | Sequence CRUD (`schema_version: 2`), `check_for_cycles()` (DFS over `type=sequence` refs), `_validate_steps()` (unique numbers, weight >=1, goto target exists, exactly one of `target_step` / `fall_through`), `validate_llm_step_capabilities()` (per-alternative). Sequences persist a `variables` array of `{name, default, choices?}`. |
| `app/chain/context.py` | `resolve_context_ids()` |
| `app/chain/context_library.py` | Context item CRUD (JSON index) |
| `app/tickets/store.py` | Ticket queue CRUD + reorder + `next_ticket()` (JSON index) |
| `app/image_prompts.py` | Saved image prompt CRUD (JSON index) — name/prompt/workflow |
| `app/chain/template.py` | `render_template()` — single regex pass; tokens: `{{input}}` `{{previous}}` `{{context}}` `{{step_index}}` `{{step_name}}` `{{N_input}}` `{{N_output}}` `{{var.NAME}}`. Unknown tokens render as `""` (forward refs to not-yet-run steps are legal because of gotos). |
| `app/chain/llm_client.py` | `OpenAICompatibleLLMClient` — uses `httpx`, not `requests` |
| `app/mcp/registry.py` | Hardcoded tool definitions: `random_integer`, `generate_name`, `format_voice_segments`, plus `save_image_prompt`, `save_wildcard`, `create_ticket` (each mirroring a same-named chain step type so the work can happen either inside an LLM tool loop or as a direct chain step). |
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
| `app/peer_health.py` | Background asyncio poller — every 30s GETs each peer's `/v1/server/health` (5s timeout) and stores `{status: green/amber/red, git_sha, last_seen, error, host, port}` in an in-memory snapshot. `green` = peer reachable + SHA matches local; `amber` = reachable + SHA mismatch (or either side has no SHA); `red` = unreachable or 5xx. `last_seen` and `git_sha` are sticky across failed polls. `/v1/server/peers` reads from `get_peer_health_snapshot()`; lifespan calls `start_peer_poller()`/`stop_peer_poller()` |
| `static/js/nav.js` | Builds top nav from `NAV_ITEMS` array; auto-marks active page by pathname |
| `static/js/voice-segments.js` | Reusable segment list widget (`vsAddSegment`, `vsCollectSegments`) |
| `static/js/resolved-prompt.js` | `renderResolvedPrompt(container, items)` — shows the resolved prompt + per-token wildcard substitutions above voice/image output panels; pairs with `resolveWildcardsTracked()` in `wildcards.js` |
| `static/js/profiles-widget.js` | Profile widget pinned to right of `#topnav` on every page: `[select ▾] [💾] [⬇] [⬆]`; select-change activates, save overwrites or expands to `[name ✓ ✗]` for `(new profile)`; self-contained (works without api/toast/escape) |
| `static/js/peer-status-widget.js` | Peer-health dots pinned to the right of `#topnav` (before the profile widget): one colored dot per peer (green/amber/red) with tooltip (peer name, host, status, git_sha, last_seen, error). Polls `/v1/server/peers` every 30s. On amber, renders a fixed banner under the topnav with the version-skew hint. Self-contained |
| `static/css/responsive.css` | Shared responsive styles (dark theme, breakpoints, `#topnav`) |

### Frontend page layout

Each page under `static/<page>/` has three files (minimum):
- `index.html` — slim skeleton (~60–120 lines): meta, link tags, layout HTML, no inline CSS or JS
- `styles.css` — page-specific styles only
- `<page>.js` — shared utilities + init (loaded last so tab modules can call its globals from handlers)

Pages can split into multiple JS modules. Script load order: `nav.js` → (page deps / tab modules) → `<page>.js` → `nav-mobile.js`. The voice page loads `voice-segments.js` before `voice.js`. The image page loads `generate-tab.js`, `prompts-tab.js` before `image.js`. The server page loads `comfyui-tab.js`, `llm-tab.js`, `llm-models-tab.js` before `server.js` (LLM tab has two sub-tabs: Models + Endpoints).

### Apps (consumer experiences, walled off from the systems nav)

`app/apps/<name>/` (backend) + `static/apps/<name>/` (frontend), bridged by a single `Apps` entry in `static/js/nav.js`. The `/apps` landing and app pages do **not** load the systems nav (`nav.js`); they style off `responsive.css` tokens and reuse `api.js`/`escape.js`. Design lives under `docs/apps/<name>/`.

| File | Purpose |
|------|---------|
| `app/apps/blaboratory/models.py` | `Personality`, `Resident` (v1), `ResidentDraft` (Optional-field LLM-output target) |
| `app/apps/blaboratory/residents_store.py` | File-per-doc store at `config/blaboratory/residents/<id>.json`; `create_resident` assigns id/timestamps/schema_version |
| `app/apps/blaboratory/rooms.py` | Occupancy over 16 fixed rooms (`config/blaboratory/occupancy.json`); `set_occupant` rejects out-of-range/occupied |
| `app/apps/blaboratory/prompts.py` | Id-keyed prompt registry (`IDEATE_FREE_TEXT`/`IDEATE_GUIDED`/`ASSEMBLE`) |
| `app/apps/blaboratory/generator.py` | `run_generation()` — runs `execute_chain_job` **directly** (not the `JobQueue`); ideate→assemble, parse w/ ≤2 retries, persist resident then occupancy; `job_type="blaboratory_resident"` |
| `app/apps/blaboratory/router.py` | Routes at `/v1/apps/blaboratory` (`GET /rooms`, `GET /residents/{id}`, `POST /rooms/{room_id}/residents`); included in `app/main.py` |

Status: Part 1 (resident-creation MVP) built. Part 2 (simulation: ticks/channels/memory) is shaped in `docs/apps/blaboratory/design.md` but unbuilt.

## Architecture

- **Jobs** stored at `JOBS_BASE/YYYY-MM-DD/<uuid>/` with `request.json`, `status.json`, `logs.txt`, `artifacts.json`
- **Chain jobs** add `steps/NNN_<step_id>/` subdirs (and `NNN_<step_id>_xII/` for re-runs when a `goto` loops back); `_expand_steps()` flattens `type=sequence` references before execution
- **Config** (sequences, context items, voice presets, omnivoice settings, comfyui settings + workflows) lives in `config/` — **gitignored**, never commit
- **Step types**: `llm`, `voice`, `write_context`, `sequence`, `image_prompt`, `save_wildcard`, `create_ticket`, `goto`. Only `llm` updates `text_output`. `goto` doesn't run a step body; it picks an alternative whose `target_step` is the next step number (or whose `fall_through=true` lets execution continue normally).
- **Alternatives**: every step carries `alternatives: list[Alternative]` (min 1). The executor `random.choices` one per visit using relative weights. All alternatives in a step share the parent's type. v1-style flat step dicts are accepted as shorthand and hoisted into a single alternative by a Pydantic `model_validator(mode='before')` on `ChainStep`.
- **Variables**: `ChainJobRequest` carries `sequence_variables: list[SequenceVariable]` (declarations: name + default + optional choices) and `variables: dict[str,str]` (caller overrides). Resolved values are exposed as `{{var.NAME}}` to every template.
- **Loop safety**: each step has a `visit_cap` (default 100); the chain also bails after a 2000-run total budget. Either limit short-circuits the job to `status=error` with a clear reason.
- **Step runner isolation**: step runners in `app/chain/steps/` raise exceptions on failure; `executor.py` owns all status writes and log appends — steps never import from `executor.py`. Each runner now takes both `step` and the chosen `alt` (`Alternative`).
- **Cycle detection**: DFS in `sequences.py` for `type=sequence` references; enforced at save time (422) and run time (depth guard at 20). Goto target validity is enforced at save time too (`target_step` must reference an existing step `number`).
- **Job status on disk**: `"queued"`, `"running"`, `"done"`, `"error"` — note `"error"` maps to `"failed"` in server stats API (see `_STATUS_MAP` in `app/server.py`)
- UI is dark-theme monospace; two-panel layout (controls left, output right); tab switching via `switchTab()`
- **Toast system**: `Map`-based, id-deduplicated; defined in `static/server/server.js` and `static/mcp/mcp.js`; requires `<div id="toast-stack"></div>` in HTML
- **psutil**: `psutil.cpu_percent()` must be called once at import (no interval) to prime the sampler before using `interval=None` calls
- **ComfyUI**: unlike OmniVoice (ephemeral subprocesses), ComfyUI is a long-lived HTTP server at `127.0.0.1:8188`. `ComfyUIManager` starts it at FastAPI boot (`lifespan` in `main.py`), adopts it if already running, and manages the process group with `os.killpg`. Workflows are API-format JSON in `config/comfyui-workflows/`; params are auto-detected by node class. Install: `bash scripts/comfyui-setup.sh`
- **llama.cpp**: mirrors the ComfyUI pattern — long-lived `llama-server` process (default `127.0.0.1:8080`). Install on the secondary: `bash scripts/llamacpp-setup.sh` (clones `https://github.com/ggerganov/llama.cpp` to `/opt/ai-stack/llama.cpp` at the `LLAMA_CPP_TAG` pinned at the top of the script, builds with `-DGGML_CUDA=ON`, creates `/opt/ai-stack/models/`, installs the systemd user unit). Tag bumps are manual — see `docs/llamacpp-upgrade.md`. `LlamaCppManager` only instantiates on nodes with `"llm"` capability and adopts an already-running server at boot. Model swaps go through `POST /v1/llamacpp/ensure-loaded` with either an inline preset dict (`{"model_path": ..., "args": {...}}`) or a named preset (`{"preset": "name"}` — resolved via `app.llm_presets`, 404 if missing). The swap key is a stable hash of the full preset (changing `ctx_size` or `n_gpu_layers` triggers a reload). Same hash → no-op; different hash → SIGTERM the existing process group, spawn the new args, poll `/health` for up to 180s. On timeout the manager raises `LlamaCppLoadError`, the route returns 503, and `current_preset_hash` is cleared — **no silent fallback** to the previous model. stdout/stderr stream into a 500-line `collections.deque` ring buffer surfaced via `GET /v1/llamacpp/logs?tail=N`.
- **LLM presets vs LLM endpoints — two separate stores, one UI**: `/v1/llm-presets` (`app/llm_presets.py`, `config/llm_presets/<name>.json`) describes *which GGUF + CLI args* to load on the local `llama-server` (feeds `ensure-loaded`). `/v1/llm-endpoints` (`app/llm_config.py`, `config/llm_config.json`) describes *where to send OpenAI-compatible HTTP requests* for chain LLM steps + voice auto-segmentation. Both surfaces live as sub-tabs under the Server page's LLM tab (Models + Endpoints) — see `static/server/llm-models-tab.js` and `static/server/llm-tab.js`. The endpoint route was previously `/v1/llm-presets`; it was renamed when model presets landed (other UI consumers: `static/voice/voice.js`, `static/chain/chain.js`). Note: with `default_preset` set in the peer's `config/llamacpp.json`, `ensure_loaded_for_step` in `app/chain/llm_swap.py` overrides the endpoint's `api_base` + `model` at runtime to point at the LLM-capable peer — so for multi-machine the endpoint values are largely vestigial for chain LLM steps.
- **Multi-machine capabilities**: `config/server.json` declares this node's `capabilities` (`web`/`voice`/`image`/`llm`) and known `peers`. Absent file → all-capabilities (single-machine). Routes that need a missing capability return `503 {"error":"capability_unavailable","needed":<cap>,"where":<peer-host>}` via `Depends(requires_capability(cap))` (see `app/main.py` — `POST /v1/jobs/image`, `POST /v1/jobs/voice`, the comfyui and omnivoice routers). Chain jobs are **not** route-gated; per-step gating is deferred. Endpoints: `GET /v1/server/capabilities`, `GET /v1/server/peers` (now returns `local_git_sha` + per-peer `health` from the in-process poller), `GET /v1/server/health` (incl. `git_sha`). Peer health is refreshed in-process every 30s by `app/peer_health.py`; the topnav `peer-status-widget.js` reads `/v1/server/peers` every 30s on the client side. Full design: `docs/reference/multi-machine-plan.md`.

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

Full developer docs live under `docs/` and are organized by section. Start at `docs/index.md` for the table of contents.

**Reference (the most useful pages when navigating the codebase):**
- `docs/reference/architecture.md` — module map, job lifecycle, chain execution flow
- `docs/reference/api.md` — REST API reference with curl examples
- `docs/reference/configuration.md` — env vars, `omnivoice.json` fields, external services, dev/prod setup
- `docs/reference/design.md` — design notes / non-obvious decisions
- `docs/reference/ui-standards.md`, `docs/reference/ui-cheatsheet.md` — frontend conventions
- `docs/reference/multi-machine-plan.md` — multi-machine design doc

**Generation (per-domain user guides):**
- `docs/generation/text/chain.md` — step types (v2), alternatives, gotos, template vars, variables
- `docs/generation/text/sequences.md` — sequence storage, validation, expansion
- `docs/generation/audio/{clone-voice,design-voice,use-voice,utility-prompts}.md` — OmniVoice flows
- `docs/generation/visual/{generate,prompts,comfyui-setup}.md` — ComfyUI image generation + install

**Tools (shared subsystems):**
- `docs/tools/mcp.md` — MCP tool registry and the same-named chain step types
- `docs/tools/context.md`, `docs/tools/wildcards.md`, `docs/tools/llm-presets.md`, `docs/tools/ticks.md`

**Management (operator pages, not feature pages):**
- `docs/management/jobs.md`, `docs/management/tickets.md`, `docs/management/docs.md`
- `docs/management/server/{web,llm,comfyui}.md` — Server tab sub-pages

**Top-level deployment docs:**
- `docs/multi-machine.md` — primary/secondary deployment (bare repo, systemd user unit, capability gating, cutover)
- `docs/llamacpp-upgrade.md` — procedure for bumping `LLAMA_CPP_TAG` in `scripts/llamacpp-setup.sh`
