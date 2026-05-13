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
| `app/chain/executor.py` | `execute_chain_job()`, `_expand_steps()`, step loop |
| `app/chain/sequences.py` | Sequence CRUD + `check_for_cycles()` |
| `app/chain/context.py` | `resolve_context_ids()` |
| `app/chain/context_library.py` | Context item CRUD (JSON index) |
| `app/chain/template.py` | `render_template()` — vars: `{{input}}` `{{previous}}` `{{context}}` `{{step_index}}` `{{step_name}}` |
| `app/chain/llm_client.py` | `OpenAICompatibleLLMClient` — uses `httpx`, not `requests` |
| `app/server.py` | `get_server_stats()`, `schedule_restart()`, 5s job-count cache (`_get_job_counts()`) |
| `static/chain/index.html` | Full chain UI — HTML + inline `<style>` + inline `<script>` |
| `static/server/index.html` | Server domain UI: resource bars, job counts, restart + Fibonacci reconnection toast system |
| `static/css/responsive.css` | Shared responsive styles (dark theme, breakpoints) |
| `static/js/nav-mobile.js` | Hamburger nav for mobile |

## Architecture

- **Jobs** stored at `JOBS_BASE/YYYY-MM-DD/<uuid>/` with `request.json`, `status.json`, `logs.txt`, `artifacts.json`
- **Chain jobs** add `steps/NNN_<step_id>/` subdirs; `_expand_steps()` flattens sequence references before execution
- **Config** (sequences, context items, voice presets, omnivoice settings) lives in `config/` — **gitignored**, never commit
- **Step types**: `llm`, `voice`, `write_context`, `sequence` (sequence expands inline; only llm updates `text_output`)
- **Cycle detection**: DFS in `sequences.py`; enforced at save time (422) and run time (depth guard)
- UI is dark-theme monospace; two-panel layout (controls left, output right); tab switching via `switchTab()`
- **Job status on disk**: `"queued"`, `"running"`, `"done"`, `"error"` — note `"error"` maps to `"failed"` in the server stats API (see `_STATUS_MAP` in `app/server.py`)
- **Toast system**: inline in `static/server/index.html` — functional, `Map`-based, id-deduplicated; reference it if adding toasts to other pages
- **psutil**: `psutil.cpu_percent()` must be called once at import (no interval) to prime the sampler before using `interval=None` calls

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
// API helper already defined in every page
const data = await api('/chain-sequences');           // GET
const saved = await api('/chain-sequences', 'POST', body);

// Escape before inserting into innerHTML
_escHtml(str)
```

```python
# TestClient runs background tasks synchronously — monkeypatch at the importing module
# e.g., patch app.main.schedule_restart, NOT app.server.schedule_restart
monkeypatch.setattr(m, "schedule_restart", lambda: ...)
```
