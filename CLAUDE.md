# ai-job-server — Claude working notes

A FastAPI job server (image / voice / chain-LLM jobs) with a LAN browser UI, plus
several consumer "apps" built on the chain executor. Multi-machine: capabilities are
split across peer nodes.

## Environment

- **Python**: `.venv/bin/python` (3.13) — never use bare `python` or `python3`
- **Tests**: `.venv/bin/pytest` — `asyncio_mode = auto`, tmp_path + monkeypatch for I/O
- **Syntax check**: `.venv/bin/python -m py_compile <file>`
- **Dev server**: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`
- **Git**: commit directly to `master` — do **not** create feature branches. The `post-commit`
  hook fails for you with `'/srv/git/ai-job-server.git/' does not appear to be a git repository`;
  this is expected and harmless — the commit still lands on `master`. Ignore it; don't mention it
  in summaries.

## Finding your way around

The full module map lives in **`docs/reference/architecture.md`** (job lifecycle + chain
execution flow too). Other entry points:

- `docs/index.md` — docs table of contents
- `docs/reference/api.md` — REST API reference with curl examples
- `docs/reference/configuration.md` — env vars, `omnivoice.json`, dev/prod setup
- `docs/reference/design.md` — non-obvious design decisions
- `docs/reference/ui-standards.md`, `ui-cheatsheet.md` — frontend conventions
- `docs/reference/multi-machine-plan.md` — multi-machine design
- `docs/generation/{text,audio,visual}/` — per-domain user guides (chain, OmniVoice, ComfyUI)
- `docs/tools/` — mcp, context, wildcards, llm-presets, ticks, packs
- `docs/apps/<name>/` — design + build plans for each app

Quick orientation, not a substitute for the module map:

- `app/main.py` — all FastAPI routes + lifespan wiring
- `app/jobs.py` + `app/job_queue.py` — job lifecycle; `JobQueue` is a single worker with two
  FIFO lanes (`Priority.HIGH`/`LOW`, HIGH drained first, never interrupts a running job)
- `app/chain/` — the chain executor and step types (see Chain jobs below)
- `app/prompt_pal/` — app-agnostic prompt registry (see Prompt Pal below)
- `app/cruddables/` + `app/packs/` — the unified envelope + curated bundles (see Cruddables below)
- `app/memory/` — app-agnostic, file-first memory subsystem (Markdown source of truth under
  `config/memory/`, plain keyword backend + optional memsearch behind an adapter, `/v1/memory`
  routes, `{{memory}}` chain token, `/memory-lab/` test bench). See `docs/memory/index.md`.
- `app/comfyui/`, `app/llamacpp/`, `app/omnivoice/` — long-lived/ephemeral generation backends
- `app/server.py`, `app/peer_health.py` — multi-machine config, capability gating, peer polling


## LLM presets vs LLM endpoints — two stores, one UI

- `/v1/llm-presets` (`app/llm_presets.py`, `config/llm_presets/<name>.json`) — *which GGUF + CLI args*
  to load on the local `llama-server` (feeds `ensure-loaded`).
- `/v1/llm-endpoints` (`app/llm_config.py`, `config/llm_config.json`) — *where to send
  OpenAI-compatible HTTP requests* for chain LLM steps + voice auto-segmentation.
- **No endpoint preset is required**: `get_default_as_chain_llm_config()` falls back to the local
  `llama-server` (if this node has `llm`) or the `llm` peer. `ensure_loaded_for_step`
  (`app/chain/llm_swap.py`) then overrides the endpoint's `api_base`/`model` to point at the chosen
  LLM peer and swaps the model there. **Two ports**: `config/server.json` peers carry the FastAPI
  port (~8090); the llama-server port (~8080) is fetched from the peer's llamacpp config.

## Multi-machine

`config/server.json` declares this node's `capabilities` (`web`/`voice`/`image`/`llm`) and known
`peers`. Absent file → all capabilities (single-machine). Routes needing a missing capability return
`503 {"error":"capability_unavailable","needed":…,"where":…}` via `Depends(requires_capability(cap))`
(image/voice job routes + the comfyui/omnivoice routers). Chain jobs are **not** route-gated.
`app/peer_health.py` polls each peer's `/v1/server/health` every 30s → green (reachable + SHA match) /
amber (SHA mismatch) / red (unreachable); the topnav widget reads `/v1/server/peers`.

## Frontend conventions

- Each page under `static/<page>/` is `index.html` (slim skeleton, no inline CSS/JS) + `styles.css`
  + `<page>.js`. Script load order: `nav.js` → page deps / tab modules → `<page>.js` → `nav-mobile.js`.
- UI is dark-theme monospace; two-panel layout (controls left, output right); `switchTab()`.
- `FieldControls.attach(slot, …)` (`static/js/field-controls.js`) is a reusable hover-control
  affordance (✨/✏️ etc.) — the app supplies all callbacks, zero app knowledge.
- **Toast system**: `Map`-based, id-deduplicated; needs `<div id="toast-stack"></div>` in the HTML.

## Common patterns

```python
# HTTP calls — always httpx, not requests
import httpx
async with httpx.AsyncClient() as client:
    r = await client.post(url, json=body, timeout=30)

# TestClient runs background tasks synchronously — monkeypatch at the IMPORTING module
# e.g. patch app.main.schedule_restart, NOT app.server.schedule_restart
monkeypatch.setattr(m, "schedule_restart", lambda: ...)
```

```javascript
// api() prepends /v1 automatically on every page except mcp.js
const data = await api('/chain-sequences');            // GET → /v1/chain-sequences
const saved = await api('/chain-sequences', 'POST', body);
// mcp.js uses full paths directly (no /v1 prepend)

_escHtml(str)   // always escape before inserting into innerHTML
```

## Conventions

- **Config** (`config/`) is **gitignored** — sequences, context items, presets, settings, app data.
  Never commit it.
- `psutil.cpu_percent()` must be called once at import (no interval) to prime the sampler before
  `interval=None` calls.
