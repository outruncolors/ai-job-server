# ai-job-server — Claude working notes

## Environment

- **Python**: `.venv/bin/python` (3.13) — never use bare `python` or `python3`
- **Tests**: `.venv/bin/pytest` — `asyncio_mode = auto`, tmp_path + monkeypatch for I/O
- **Syntax check**: `.venv/bin/python -m py_compile <file>`
- **Dev server**: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`
- **Known pre-existing failures**: `tests/test_omnivoice.py`, `tests/test_voice_presets.py` — unrelated to chain/context work, ignore unless touching voice

## Key files

| File | Purpose |
|------|---------|
| `app/main.py` | All FastAPI routes |
| `app/jobs.py` | Job lifecycle: `create_job()`, artifact tracking, file serving |
| `app/chain/models.py` | Pydantic schemas: `ChainStep`, `ChainJobRequest`, `ChainLLMConfig` |
| `app/chain/executor.py` | `execute_chain_job()`, `_expand_steps()`, step loop; shared helpers (`_write_chain_status`, `_append_log`) |
| `app/chain/steps/llm.py` | `run_llm_step()` — LLM tool loop, Gemma fallback parser |
| `app/chain/steps/voice.py` | `run_voice_step()` — TTS synthesis, auto-segmentation |
| `app/chain/steps/write_context.py` | `run_write_context_step()` — saves text output to context library |
| `app/chain/sequences.py` | Sequence CRUD + `check_for_cycles()` |
| `app/chain/context.py` | `resolve_context_ids()` |
| `app/chain/context_library.py` | Context item CRUD (JSON index) |
| `app/tickets/store.py` | Ticket queue CRUD + reorder + `next_ticket()` (JSON index) |
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
| `app/omnivoice/config.py` | `OmniVoiceConfig` model, get/save from `config/omnivoice.json` |
| `app/omnivoice/runner.py` | `OmniVoiceEphemeralRunner` — subprocess-based TTS invocation |
| `app/voice_presets.py` | Preset CRUD backed by `config/voice_presets/` |
| `app/server.py` | `get_server_stats()`, `schedule_restart()`, 5s job-count cache (`_get_job_counts()`) |
| `static/js/nav.js` | Builds top nav from `NAV_ITEMS` array; auto-marks active page by pathname |
| `static/js/voice-segments.js` | Reusable segment list widget (`vsAddSegment`, `vsCollectSegments`) |
| `static/css/responsive.css` | Shared responsive styles (dark theme, breakpoints, `#topnav`) |

### Frontend page layout

Each page under `static/<page>/` has three files (minimum):
- `index.html` — slim skeleton (~60–120 lines): meta, link tags, layout HTML, no inline CSS or JS
- `styles.css` — page-specific styles only
- `<page>.js` — shared utilities + init (loaded last so tab modules can call its globals from handlers)

Pages can split into multiple JS modules. Script load order: `nav.js` → (page deps / tab modules) → `<page>.js` → `nav-mobile.js`. The voice page loads `voice-segments.js` before `voice.js`. The image page loads `server-tab.js`, `generate-tab.js`, `workflows-tab.js`, `config-tab.js` before `image.js`.

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
