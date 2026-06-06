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

## Apps

`app/apps/<name>/` (backend) + `static/apps/<name>/` (frontend), bridged by a single `Apps` entry
in `static/js/nav.js`. App pages load the shared topnav and style off `responsive.css` tokens.
**All apps run `execute_chain_job` directly, not through the `JobQueue`** (in-request generation).

- **blaboratory** — virtual lab of AI residents: 16 rooms, tick-driven sim, hybrid vector memory
  (sqlite-vec index + app-managed bge-small embed server), phone calls, Messages timeline,
  in-app Config tab (hot-applied numeric knobs via `settings_store`).
- **hoodat** — character creation/management. `Character` has nested
  Appearance/Personality/Background/SpeakingStyle blocks plus frontend-owned lists
  (`experiences`, `qa`, outfits, dialogue examples). `FIELD_SPECS` is the single source of truth
  for generatable scalar/list fields. Avatar generation degrades gracefully (503) when this node
  lacks the `image` capability — it does not gate the whole app.
- **prattletale** — iMessage-style roleplay chat against a Hoodat character. Each conversation is
  a self-contained folder (`conversation.json` + `transcript.json` + `traces/` + `media/`).
  A *turn* is one side's contribution; an *item* is one rendered bubble. Has a plugin system
  (registry + manifest + generic action dispatch + `window.PtPlugins` loader); **Summarizer**
  ships as the first plugin.

## Chain jobs

- **Step types**: `llm`, `voice`, `write_context`, `sequence`, `image_prompt`, `save_wildcard`,
  `create_ticket`, `goto`. **Only `llm` mutates `text_output`.** `goto` runs no body — it picks an
  alternative whose `target_step` is the next step number, or `fall_through=true` to continue.
- **Alternatives**: every step has `alternatives: list[Alternative]` (min 1, all share the parent's
  type); the executor `random.choices` one per visit by relative weight. v1-style flat step dicts
  are accepted as shorthand and hoisted into a single alternative by a `model_validator` on `ChainStep`.
- **Variables**: `ChainJobRequest` carries `sequence_variables` (declarations) and `variables`
  (caller overrides); resolved values are exposed as `{{var.NAME}}` to every template.
- **Templates**: `render_template()` tokens — `{{input}}` `{{previous}}` `{{context}}`
  `{{step_index}}` `{{step_name}}` `{{N_input}}` `{{N_output}}` `{{var.NAME}}`. Unknown tokens
  render as `""` (forward refs are legal because of gotos).
- **Loop safety**: per-step `visit_cap` (default 100) + a 2000-run total budget; either short-circuits
  to `status=error`. Cycle detection is DFS over `type=sequence` refs (enforced at save and run time).
- **Step runner isolation**: runners in `app/chain/steps/` raise on failure; `executor.py` owns all
  status writes and log appends. Runners never import from `executor.py`. Each runner takes both
  `step` and the chosen `alt`.
- Jobs live at `JOBS_BASE/YYYY-MM-DD/<uuid>/` (`request.json`, `status.json`, `logs.txt`,
  `artifacts.json`). Chain jobs add `steps/NNN_<step_id>/` dirs (`_xII` suffix on goto re-runs).
- Job status on disk is `queued`/`running`/`done`/`error`; `error` maps to `failed` in the server
  stats API (`_STATUS_MAP` in `app/server.py`).

## Prompt Pal

The project-wide home for the internal LLM prompts apps use for creative input.

- Apps declare prompts **in code** (`registry.register(app, key, …)`); `seed_registered()` at
  lifespan writes any missing `(app,key)` to the store — **seed-if-absent, never clobbers edits**.
- App code calls `service.get_text(app, key, *, variables=None)`: the **store copy wins** (UI edits
  persist), else the in-code default; both composed via `compose` (substitutes `{{var.NAME}}`,
  leaves chain tokens for the executor).
- A **guard** is an optional second "editor" LLM pass attached to a prompt: it references the main
  output via `{{previous}}` and rewrites it to meet requirements. To apply one, a caller appends the
  guard text as a second `llm` chain step (see Hoodat's `_run_single_step`).
- **Whenever you tweak a prompt that has a guard, check the guard too.** The guard restates the
  prompt's format/requirements to repair the output, so a prompt change usually means the guard needs
  the matching change — otherwise it will "repair" valid output back to the old format (or, like the
  Prattletale `turn` guard once did, leak its own format-spec headers into the output).

## Cruddables, Packs & the unified envelope

Every in-scope CRUD entity is persisted as one **envelope** shape — shared meta
(`schema_version`/`type`/`id`/`name`/`description`/`tags`/`created_at`/`updated_at`) plus a typed
`data` payload. On-disk shape == export shape == envelope. IDs are human-readable underscore slugs.

- Types on the envelope: `wildcard`, `context_item`, `image_prompt`, `chain_sequence`, `prompt_pal`,
  `hoodat_character`. Each store is the envelope boundary — it keeps its flat-body API for
  router/generator code, while `list_envelopes`/`get_envelope`/`upsert_envelope` back the adapter.
- **apply == extend**: applying a Pack routes its `items` through the same `apply_items` as a pasted
  Extend, upserting by `id` (re-applying overwrites local edits to a pack item). For
  `chain_sequence`, apply runs structural validation but skips capability validation (cross-machine).
- Packs live in two trees: `packs/` (builtin) shadowed by `config/packs/` (user). Full contract:
  `docs/tools/packs.md`. Author a pack with `/add-pack <type> <theme>`.

## Generation backends

- **ComfyUI** is a long-lived HTTP server (`127.0.0.1:8188`). `ComfyUIManager` starts it at FastAPI
  boot, adopts it if already running, manages the process group with `os.killpg`. Workflows are
  API-format JSON in `config/comfyui-workflows/`; params auto-detected by node class.
  Install: `bash scripts/comfyui-setup.sh`.
- **llama.cpp** mirrors that pattern — long-lived `llama-server` (`127.0.0.1:8080`), instantiated
  only on `llm`-capability nodes. Model swaps go through `POST /v1/llamacpp/ensure-loaded` (inline
  preset dict or named `{"preset": "name"}`). The swap key is a stable hash of the full preset;
  same hash → no-op, different → SIGTERM + respawn + poll `/health` (180s). On timeout it raises,
  the route 503s, and the hash clears — **no silent fallback** to the previous model. A second,
  always-on embed `llama-server` (port 8081, fixed argv) backs vector retrieval.
  Install on the secondary: `bash scripts/llamacpp-setup.sh`; tag bumps: `docs/llamacpp-upgrade.md`.
- **OmniVoice** TTS runs as ephemeral per-job subprocesses (contrast with the long-lived servers above).
- **Multimodal (Vision + STT)** reuses the llama.cpp backend: `app/multimodal/` loads a dedicated
  multimodal preset (`gemma-4-e4b-mm`, with an `mmproj` projector) onto the `llm` node via the same
  hash-based `ensure-loaded` swap, then sends `image_url` / `input_audio` content parts through the
  OpenAI-compatible `/chat/completions` API. STT transcodes uploads to 16 kHz mono WAV (ffmpeg) and
  decodes greedily (`temperature=0.0`). The preset's `ctx_size` is boosted to `multimodal_min_ctx`
  at load so long descriptions/transcripts aren't truncated.
  - **The model is Gemma 4 E4B — a real Google model, NOT a typo for "Gemma 3n".** Gemma 4 (released
    2026, *after* the training cutoff of older Claude models — verify via web search, don't "correct"
    it from memory) is a unified multimodal family in E2B/E4B/12B/26B A4B/31B sizes; **E2B and E4B
    have native audio input** for speech recognition. We run E4B at the highest quantization.
  - **STT/ASR prompt must follow Gemma 4's template, which names the language** — e.g.
    `Transcribe the following speech segment in English into English text. ...` (or the auto-detect
    variant `...in its original language. ...`). A generic prompt that omits the language is the
    known cause of Gemma 4 emitting the wrong language (e.g. Chinese for English audio). See
    `DEFAULT_STT_PROMPT` in `app/multimodal/service.py` and Google's audio docs
    (`ai.google.dev/gemma/docs/capabilities/audio`).

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
