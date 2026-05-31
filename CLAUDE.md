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
| `app/embed_lab/db.py` | Standalone SQLite playground (`config/embed-lab/playground.db`) — separate from `blaboratory.db` so manual embed/KNN testing can't pollute the sim. Lazily loads sqlite-vec + creates `docs` + `vec_docs(embedding float[384], doc_id)`. |
| `app/embed_lab/router.py` | Routes: `/v1/embed-lab/{compare,docs,query,status}` — paste N texts → cosine matrix; add/list/delete/clear docs; KNN query (bge prefix on queries). Embeds via `app.apps.blaboratory.embeddings.embed_texts` (reused as a thin client). Frontend at `/embed-lab/`. |
| `app/comfyui/config.py` | `ComfyUIConfig` model, get/save from `config/comfyui.json` |
| `app/comfyui/manager.py` | `ComfyUIManager` — long-lived process: start/stop/restart, readiness probe, GPU status |
| `app/comfyui/client.py` | `ComfyUIClient` — httpx wrapper for ComfyUI HTTP API (port 8188) |
| `app/comfyui/workflows.py` | `list_workflows()`, `introspect_params()`, `inject_params()` — workflow discovery + param injection |
| `app/comfyui/runner.py` | `execute_image_job()` — submits prompt, polls history, fetches output images |
| `app/comfyui/router.py` | Routes: `/v1/comfyui/{status,start,stop,restart,config,workflows,system_stats}` |
| `app/llamacpp/config.py` | `LlamaCppConfig` model (binary_path/port/default_preset/models_dir + D1 embed fields `embed_port`/`embed_model_path`/`embed_pooling`); get/save from `config/llamacpp.json` |
| `app/llamacpp/manager.py` | `LlamaCppManager` — long-lived `llama-server` process; `ensure_loaded(preset_dict)` swap-locks on full-args hash, 180s readiness deadline via `/health`, 500-line stdout/stderr ring buffer, `os.killpg` cleanup, `adopt()` |
| `app/llamacpp/embed_manager.py` | `LlamaCppEmbedManager` (D1) — sibling of `LlamaCppManager` for a **second**, always-on embed `llama-server` (`/v1/embeddings`, port 8081). Fixed argv (`--embeddings --pooling cls --ctx-size 512 -ngl 99`, no swap hash); adopt/start/stop/restart, `/health` readiness, ring buffer, `killpg`. Started/adopted at lifespan on `llm` nodes |
| `app/llamacpp/router.py` | Routes: `/v1/llamacpp/{status,start,stop,restart,config,models,ensure-loaded,logs}`; `_resolve_preset` looks up named presets via `app.llm_presets` (404 if missing) or accepts an inline dict |
| `app/llamacpp/embed_router.py` | Routes: `/v1/llamacpp-embed/{status,start,stop,restart,logs}` (D1) — lifecycle for the embed server (no preset resolution; fixed model from config). `llm`-capability-gated |
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
| `static/js/nav.js` | Builds top nav from `NAV_ITEMS` (nested: top-level links + dropdown groups for Generate/Tools/Manage); auto-marks active link by pathname; exposes `window.NAV_ITEMS` for `nav-mobile.js` to rebuild the hamburger menu (groups become section headers) |
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

### Apps (consumer experiences)

`app/apps/<name>/` (backend) + `static/apps/<name>/` (frontend), bridged by a single `Apps` entry in `static/js/nav.js`. App pages load the shared systems nav (`<nav id="topnav">` + `nav.js` + `nav-mobile.js`) just like the rest of the site, with `padding-top: 44px` on `body` to clear the fixed 44px bar. They style off `responsive.css` tokens and reuse `api.js`/`escape.js`. Design lives under `docs/apps/<name>/`.

| File | Purpose |
|------|---------|
| `app/apps/blaboratory/models.py` | `Personality`, `Resident` (v1), `ResidentDraft` (Optional-field LLM-output target) |
| `app/apps/blaboratory/residents_store.py` | File-per-doc store at `config/blaboratory/residents/<id>.json`; `create_resident` assigns id/timestamps/schema_version |
| `app/apps/blaboratory/rooms.py` | Occupancy over 16 fixed rooms (`config/blaboratory/occupancy.json`); `set_occupant` rejects out-of-range/occupied |
| `app/apps/blaboratory/prompts.py` | Id-keyed prompt registry (`IDEATE_FREE_TEXT`/`IDEATE_GUIDED`/`ASSEMBLE`); `get_prompt` now routes through `compose` (back-compat) |
| `app/apps/blaboratory/generator.py` | `run_generation()` — runs `execute_chain_job` **directly** (not the `JobQueue`); ideate→assemble, parse w/ ≤2 retries, persist resident then occupancy; `job_type="blaboratory_resident"` |
| `app/apps/blaboratory/router.py` | Routes at `/v1/apps/blaboratory` — Part 1 (`GET /rooms`, `GET /residents/{id}`, `POST /rooms/{room_id}/residents`) + Part 2 sim (`GET /ticks/latest`, `GET /ticks/{tick}/rooms`, `GET /residents/{id}/events`, `GET /residents/{id}/context`, `GET /rooms/{id}/utterances`, `POST /ticks/fire`, `GET`+`POST /clock`) + Messages (`GET /chat` — playhead-scoped feed paging: `until_tick`/`before`/`after`/`around`/`limit`, author-name enriched, returns `has_more_before`/`has_more_after`/`target_id`) + Config (`GET`+`PUT /settings`); included in `app/main.py` |
| `app/apps/blaboratory/db.py` | Owns the SQLite connection (`config/blaboratory/blaboratory.db`, `check_same_thread=False`) + `PRAGMA user_version` migrations. Tables: `events`, `chat`, `utterances`, `calls`, `consumption_cursors` |
| `app/apps/blaboratory/{event,chat,cursor,utterance}_store.py` | Per-table query/append helpers over `db.py` (newest-first reads, JSON payloads, consumption cursors, call/utterance ranges). `chat_store` also has playhead-scoped, oldest-first UI feed paging (`chat_latest`/`chat_before`/`chat_newer`/`get_chat`) for the Messages tab — separate from the cursor-driven `chat_after`/`chat_upto` |
| `app/apps/blaboratory/context_pipeline.py` | **async** `build_context()` fills the 5 fixed sections (`[Some Know]` empty; `[Everyone Knows]` reads `lore/world.json`); `[You Know]` via `retrieve_memories()` — D1 **hybrid** recency-floor ∪ KNN-relevant (deduped, scoped), `apply_caps`; falls back **byte-identical** to mechanical `gather_memories`+`apply_caps` when the index/embed server is unavailable; `write_phase()` persists an action + advances consumption cursors (visibility = consumption), and injects the new `chat_id` into the event payload so the event log can deep-link to the posted message |
| `app/apps/blaboratory/vector_index.py` | D1 `is_available()`/`add(rows)`/`query(vec, k, *, resident_id, kinds, max_chat_id)` over the `vec_memories` vec0 vtable; scope filters in the KNN `WHERE` (resident incl. global, kind, chat `ref_id<=max_chat_id`). Global rows use an empty-string sentinel (vec0 0.1.9 rejects NULL metadata) |
| `app/apps/blaboratory/embeddings.py` | D1 embed config (`config/blaboratory/embeddings.json`: port/model/dim=384/query_prefix); `embed_url()` (host from `llm` peer, embed port) + `embed_texts(texts, *, is_query)` (bge query prefix on queries only). Uses `OpenAICompatibleLLMClient.embed()` → `EmbedError` |
| `app/apps/blaboratory/memory_index.py` | D1 `render_indexable(row, kind)` (mirrors gather line shape), `fetch_and_render(kind, ref_id)`, and `index_pending(*, limit)` — batched idempotent backfill of un-indexed events/chat/utterances (LEFT JOIN `vec_rowmap`); logged-once no-op when extension/embed unavailable |
| `app/apps/blaboratory/prompt_compose.py` + `prompts_store.py` | `compose(node)` resolver over `{prompt, variables}` (literal/nested/`prompt_id`), substitutes only `{{var.NAME}}` (chain tokens pass through); file-per-doc prompt assets |
| `app/apps/blaboratory/actions/` | Action plugins (mirror MCP tools): `use_computer`/`use_televisor`/`use_speakerphone`/`sleep`/`idle` + `registry`; `Action` carries `breakpoints`+`multi_tick`; each `run()` returns the `write_phase` result dict |
| `app/apps/blaboratory/activity_store.py` | Current multi-tick activity per resident (`{action, count}`) for sleep/Continue |
| `app/apps/blaboratory/tick_runner.py` | `run_tick()` — calls `memory_index.index_pending()` once up front (D1 backfill, best-effort), then every occupant takes one action; per-tick LLM free-choice (`_choose` runs one decision chain job each via `execute_chain_job` direct), Continue option + breakpoint clause |
| `app/apps/blaboratory/sim_clock.py` | `SimClock` (clones `TickScheduler`) fires one LOW-lane job per tick; `fire_tick()`; lifespan-wired via `start_sim_clock_if_desired()` which resumes the **persisted desired state** at `config/blaboratory/clock_state.json` (operator-set `start`/`stop` writes the file; shutdown calls `stop_sim_clock(persist=False)` so an unexpected restart doesn't get logged as "stopped"). `BLAB_SIM_AUTOSTART` is now only the first-boot fallback (used when the state file is absent) |
| `app/apps/blaboratory/call_sequence.py` | `run_call()` — phone call inside the caller's tick (callee accepts/declines, topic→lines→continue/segue/end), reuses `execute_chain_job` per turn; lines written to both rooms; callee marked busy |
| `app/apps/blaboratory/config.py` | Sim tunables: `TICK_INTERVAL_SECONDS`, `MAX_MEMORY_ITEMS/CHARS`, `RECENCY_FLOOR_ITEMS`, `RELEVANT_TOP_K`, `SIM_AUTOSTART` (env-overridable). These are now the **defaults** `settings_store` falls back to — the file overrides them |
| `app/apps/blaboratory/settings_store.py` | Operator-editable sim knobs (Config tab). Flat JSON doc `config/blaboratory/settings.json` **overrides** the env-defaulted `config.py` constants; `get_settings()`/`update_settings(patch)` (validated: positive ints, per-key bounds, `SettingsError`) + per-key getters (`tick_interval_seconds()`, `max_memory_items()`, `max_memory_chars()`, `recency_floor_items()`, `relevant_top_k()`) called by `sim_clock._loop` and `context_pipeline` on each access so edits apply **hot** (next tick / next context build) — no restart |
| `app/job_queue.py` | `JobQueue` now has two FIFO lanes (`Priority.HIGH`/`LOW`, HIGH default) sharing the one worker via a counting semaphore — HIGH drained first, running job never interrupted |

Status: Part 1 (resident-creation MVP), Part 2 (simulation: ticks/channels/memory/phone calls/timeline), **and D1** (hybrid vector retrieval: sqlite-vec index + app-managed bge-small embed server), **plus the Config tab** (in-app sim controls + hot-applied numeric knobs via `settings_store`) **and the Messages tab** (Discord-style speech-bubble view of the `chat` feed via `GET /chat`; playhead-scoped, infinite-scroll-up + live-append, deep-linkable via `?tab=messages&message_id=<id>` — the resident detail modal is now tabbed Profile/Event log/Context and its reformatted event log links chat-post rows into Messages) built — see `docs/apps/blaboratory/part2-build-plan.md`, `d1-vector-build-plan.md` (+ `ops-d1-embeddings.md`), and `config-tab-build-plan.md`. Deferred: the televisor/news generator and `[Some Know]`/lore *content* (D2 — schema already carries `kind='lore'`/global rows). Embed-server status/start-stop UI tile deferred (control via `/v1/llamacpp-embed/*`). Blaboratory's prompts now live in **Prompt Pal** (see below) — `prompts.get_prompt(id)` routes through `prompt_pal.service.get_text("blaboratory", id)`, and `prompt_compose.py` is a thin re-export of the shared `app/prompt_pal/compose.py`.

### Prompt Pal — app-agnostic prompt registry (`app/prompt_pal/`)

The project-wide home for the internal LLM prompts apps use for "creative input." Apps declare prompts **in code** (`registry.register(app, key, *, title, prompt, …)` at import); `seed_registered()` (called once in `lifespan`) writes any missing `(app,key)` to the store — **seed-if-absent**, never clobbers edits. App code calls `service.get_text(app, key, *, variables=None)`: the **store copy wins** (user edits in the UI persist), else the **in-code default**; both composed via `compose` (substitutes `{{var.NAME}}`, leaves chain tokens `{{input}}`/`{{previous}}` for the executor). `id_for(app, key)` gives the entry id for `?highlight=` deep-links.

| File | Purpose |
|------|---------|
| `app/prompt_pal/compose.py` | The composable-prompt primitive (`compose(node, *, store=…)` over `{prompt, variables}` / `{prompt_id}` refs). Promoted from blaboratory; reuses `chain/template.py` `_TOKEN_RE`. |
| `app/prompt_pal/models.py` | `PromptEntry` (id/schema_version/app/key/title/description/tags/prompt/variables/timestamps + optional `guard`) + `PromptEntryPatch` (editable subset — `app`/`key` immutable) + `GuardSpec` (`{enabled, prompt, variables}`). A **guard** is a second "editor" LLM pass attached to a prompt: it runs after the main output, references it via the chain token `{{previous}}`, and either passes it through or rewrites it to meet requirements. |
| `app/prompt_pal/store.py` | File-per-doc store at `config/prompt_pal/<id>.json` (atomic writes, monkeypatchable `PROMPT_PAL_DIR`); `get_by_app_key`, `node_for_id` (the compose `store=` callable). |
| `app/prompt_pal/registry.py` | In-code `register()` table + `seed_registered()` (imports each app's `prompts` module first). |
| `app/prompt_pal/service.py` | `get_text(app, key)` / `get_guard(app, key)` (composed guard text or None if absent/disabled/empty) / `id_for(app, key)` — what app code calls. To apply a guard, a caller appends the guard text as a second `llm` chain step (see Hoodat's `_run_single_step`). |
| `app/prompt_pal/router.py` | `/v1/prompt-pal/entries` CRUD (`GET` list w/ `?app=`/`?tag=`, `GET`/`PUT`/`POST` (409 dup `(app,key)`; `guard` accepted)/`DELETE`, `POST .../preview` (`target=prompt`\|`guard`)). Not capability-gated. `register(..., guard=…)` seeds an in-code guard default. UI: the editor has a collapsible **Guard** sub-section (enable toggle + guard prompt + guard vars + guard preview). |
| `static/prompt-pal/` | Management UI (list + search/filter-by-app/filter-by-tag/sort + editor + live preview); deep-link `?app=&highlight=<id>` scrolls/flashes/opens a row. Nav: Tools dropdown. |
| `static/js/field-controls.js` + `static/css/field-controls.css` | Reusable **hover-control affordance**: `FieldControls.attach(slot, {kind:'avatar'\|'field', controls:[{id,label,onClick(ctx)}], context})`. Shows a `.fc-cluster` on hover/`:focus-within` (tap-toggle for avatars). App supplies all callbacks — zero app knowledge. |

### Cruddables, Packs & the unified envelope (`app/cruddables/`, `app/packs/`)

Every in-scope CRUD entity ("cruddable") is persisted as one **envelope** shape — shared meta
columns (`schema_version`/`type`/`id`/`name`/`description`/`tags`/`created_at`/`updated_at`)
plus a typed `data` payload. On-disk shape == export shape == envelope (single source of truth,
exportable, LLM-generatable, bundleable into Packs). IDs are human-readable underscore slugs;
pack items end `_pack_<pack_id>`. Full contract: `docs/tools/packs.md`.

**Migrated types (all 6):** `wildcard`, `context_item`, `image_prompt`, `chain_sequence`,
`prompt_pal`, `hoodat_character` — each store persists the envelope (`data.*` payload), tolerates
legacy docs on read (`migrate_native`), and exposes `upsert_envelope(dict)→(action,id)`.
`chain_sequence` keeps `steps`/`variables` under `data` with `data.content_version` (envelope
`schema_version`=1). `prompt_pal` identity is logical `(data.app, data.key)`; `id = slug(app_key)`;
no-app→`app="system"`. `hoodat_character` nests the whole `Character` body under `data` with
`data.content_version`; the **store is the envelope boundary** — its flat-body API
(`get_character`/`list_characters`/`create_character`/`save_character`/`update_character_fields`)
still returns the flat `Character` doc so router/generator/avatars/exports/`profile.js` are
unchanged, while `list_envelopes`/`get_envelope`/`upsert_envelope` back the adapter. `create_character`
now assigns a slug id (was uuid); existing uuid-keyed docs + avatars are tolerated until the
re-slug migration. **Pending:** the one-time live re-slug `migrate.py` (do LAST; includes hoodat
avatar re-keying).

| File | Purpose |
|------|---------|
| `app/cruddables/envelope.py` | `Cruddable` model + `slugify`/`unique_id`/`now_iso`, `ENVELOPE_SCHEMA_VERSION` |
| `app/cruddables/base.py` | `CruddableAdapter` ABC: `list_envelopes`/`get_envelope`/`upsert_envelope`/`delete`/`count`/`migrate_native` |
| `app/cruddables/adapters/*.py` | one thin adapter per type, wrapping its store |
| `app/cruddables/registry.py` | `REGISTRY`, `get_adapter(type)`, `list_types()→[{type,label,count}]` |
| `app/cruddables/service.py` | `apply_items(items, *, expected_type=None)→{created,updated,errored,results}` — routes each item by its own `type`; one bad item never aborts |
| `app/cruddables/router.py` | `/v1/cruddables/{types, {type}/export, {type}/extend}` |
| `app/packs/store.py` | two-tree pack store: `BUILTIN_PACKS_DIR=packs/`, `USER_PACKS_DIR=config/packs/` (`<dir>/<type>/<id>.json`, user shadows builtin); `list_packs()`/`get_pack(type,id)` |
| `app/packs/service.py` | `apply_pack(type,id)`→`cruddables.service.apply_items` (+`PackNotFound`) |
| `app/packs/router.py` | `/v1/packs/{packs, {type}/{id}, {type}/{id}/apply}` |
| `static/packs/` | Packs page (Tools nav): browse/filter/sort + Apply + View JSON |
| `static/cruddables/` | Cruddables page (Manage nav): per-type Export/Copy/Extend |
| `.claude/skills/add-pack/SKILL.md` | `/add-pack <type> <theme>` authors a pack file |

Both routers are wired in `app/main.py` after `prompt_pal_router` (inline imports). Pages are
auto-served by the root `StaticFiles(html=True)` mount — no page routes. **apply == extend**:
applying a pack routes its `items` through the same `apply_items` as a pasted Extend, upserting
by `id` (re-applying overwrites local edits to a pack item). For `chain_sequence`, apply runs
structural validation but skips capability validation (cross-machine packs). Example builtin
packs: `packs/wildcard/basic_colors.json`, `packs/hoodat_character/starter_hero.json`. Tests:
`tests/packs/`, `tests/cruddables/`.

### Hoodat — character creation/management (`app/apps/hoodat/`, `static/apps/hoodat/`)

| File | Purpose |
|------|---------|
| `app/apps/hoodat/models.py` | `Character` (**v2**, nested `Appearance`/`Personality`/`Background`/`SpeakingStyle` blocks + top-level Identity fields + top-level `experiences: list[Experience]` + top-level `qa: list[QAPair]` (`{question, answer}`, AliChat interview exemplars, frontend-owned) + server `avatar_path`) + `CharacterDraft` (all-Optional LLM target). `Appearance` is split into Basics (incl. `hair_color`/`hair_details`/`eye_color`/`eye_details`), flat Nude fields (shared + male-only `penis`/`testicles` + female-only `breasts`/`vulva`; UI-gated on `sex`, kept flat so the standard `field.appearance.<x>` path works), and `outfits: list[Outfit]` (garment slots + one `primary`). `SpeakingStyle.dialogue_examples`, `Appearance.outfits`, and `experiences` are **not** in `FIELD_SPECS` — list-of-objects/few-shot, frontend-owned. A `model_validator(mode='before')` on `Appearance` migrates v1 flat `hair`/`eyes`/`primary_outfit` → v2 (the store also normalizes legacy docs on read; `schema_version`→2). `FIELD_SPECS` (section→field→{label,kind}) is the single source of truth for generatable scalar/list fields (drives prompt registration, patch-building, normalization). |
| `app/apps/hoodat/characters_store.py` | File-per-doc at `config/hoodat/characters/<id>.json` — **Cruddable envelope on disk** (`type="hoodat_character"`, the `Character` body under `data` + `data.content_version`). Store is the envelope boundary: flat-body API (`get_character`/`list_characters`/`create_character` [slug id]/`save_character`/`update_character_fields` deep-merges nested-section patches) returns the flat `Character` doc; `list_envelopes`/`get_envelope`/`upsert_envelope` back the cruddable adapter. Legacy flat/v1 docs tolerated on read; tags ride the envelope, not the body. |
| `app/apps/hoodat/prompts.py` | Registers Prompt Pal entries: `IDEATE`/`ASSEMBLE` (create chain) + one `field.<section>.<field>` per generatable field + `dialogue.example` + `experience.example` (`{{var.character}}`+`{{var.experiences}}` → JSON `{description,valence}`) + `qa.answer` (`{{var.character}}`+`{{var.question}}`+`{{var.qa}}`) + `qa.question` (suggest helper) + `outfit.full`/`outfit.slot` + `avatar.image_prompt` (templated). `dialogue.example` and `qa.answer` carry a **shared spoken-only guard** (`SPOKEN_ONLY_GUARD` / `_spoken_only_guard()`) so their output is TTS-safe (no actions/symbols). `render_character_context(doc)` (explicit appearance render — combined hair/eyes, non-empty Nude block, numbered Outfits, split Positive/Negative experiences, **Q&A pairs last** per AliChat "bottom weighted stronger") / `experiences_split(doc)` / `avatar_prompt_variables(doc)` helpers. |
| `app/apps/hoodat/generator.py` | `run_create(name, prompt)` (ideate→assemble→parse w/ ≤2 retries→persist) + `run_field(id, section, field)` (single-step, normalize per kind, persist) + `run_dialogue_example(id, examples)` / `run_experience_example(id, experiences)` (returns `{description,valence}`, LLM picks valence) / `run_outfit(id, outfits, outfit)` / `run_outfit_slot(id, slot, outfit, outfits)` / `run_qa_answer(id, question, pairs)` / `run_qa_question(id, pairs)` (single-step, **do not persist** — frontend owns those lists). `_run_single_step(..., guard_prompt=None)` appends a SECOND `llm` "guard" step when given (the guard's output becomes `final_output.txt`); dialogue + qa.answer pass `get_guard("hoodat", key)`. Runs `execute_chain_job` **directly** (not the queue), mirroring blaboratory. |
| `app/apps/hoodat/avatars.py` | `generate_avatar(id)` (build prompt → `execute_image_job` `workflow="image"` → copy first image artifact to `config/hoodat/avatars/<id>.png`) + `save_uploaded_avatar(id, bytes, ctype)`; sets `avatar_path` to the serve URL. `execute_image_job` imported by name (monkeypatchable). |
| `app/apps/hoodat/exports.py` | Targeted Exports — export defs ARE Prompt Pal entries (`app="hoodat"`, `key="export.<slug>"`); `run_export(id, key, detail)` composes `{{var.character}}`+`{{var.detail}}`+`{{var.dialogue_examples}}` into a single LLM chain. |
| `app/apps/hoodat/router.py` | `/v1/apps/hoodat` — characters CRUD, `POST .../fields/{section}/{field}/generate` (→`{value, prompt_id, job_id}`), `POST .../dialogue-examples/generate` / `.../experiences/generate` / `.../outfits/generate` / `.../outfits/slot/{slot}/generate` / `.../qa/generate` (`{question, pairs}`) / `.../qa/question/generate` (`{pairs}`) (each →`{value, prompt_id, job_id}`; caller persists the full list via CRUD `PUT`), avatar generate/upload/serve, exports list/run. Text gen ungated; **avatar generate degrades gracefully** (503 when `image` not in `get_local_capabilities()` — does NOT gate the whole app). |
| `static/apps/hoodat/` | `index.html`+`hoodat.js` (card list + search + create→redirect); `profile.html`+`profile.js` (Discord-style profile, 8 tabs incl. **Experiences** and **Q&A**, every field + the avatar wrapped with `FieldControls` for ✨generate / ✏️edit-prompt; tabs use uniform `.hd-section` cards via `sectionCard()`. A `CONTROLS` registry keyed by `kind` renders the right input — textarea/number/list, **radio** (sex), **feet-inches** (height, stored as `5'10"`). **Appearance** renders 3 sub-cards: Basics, Nude (gated on `sex`, re-rendered when sex changes), Clothed (an **outfits** list — cards w/ slots, per-slot ✨, outfit-level ✨, one `primary` radio). Speaking Style integrates voice presets + `POST /v1/jobs/voice` sample + a **dialogue examples** list; **Experiences** tab is a list (description + Positive/Negative radio; +Add generates, LLM picks valence). **Q&A** tab is AliChat-style interview exemplars: a compose row (question input + ✨ Generate answer + 💡 Suggest question) over a list of {question, answer} cards (per-card ✨ regenerate / ✏️ edit `qa.answer` prompt / 🔊 speak [shown only when a voice preset is set] / ✗ remove); the reusable `playLine(text, audio, msg, presetId)` TTS helper backs both the Speaking Style sample and the 🔊 button. All lists are frontend-owned (collect→PUT wholesale). Exports tab). Registered in `static/apps/apps.js`. |

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
- **LLM presets vs LLM endpoints — two separate stores, one UI**: `/v1/llm-presets` (`app/llm_presets.py`, `config/llm_presets/<name>.json`) describes *which GGUF + CLI args* to load on the local `llama-server` (feeds `ensure-loaded`). `/v1/llm-endpoints` (`app/llm_config.py`, `config/llm_config.json`) describes *where to send OpenAI-compatible HTTP requests* for chain LLM steps + voice auto-segmentation. Both surfaces live as sub-tabs under the Server page's LLM tab (Models + Endpoints) — see `static/server/llm-models-tab.js` and `static/server/llm-tab.js`. The endpoint route was previously `/v1/llm-presets`; it was renamed when model presets landed (other UI consumers: `static/voice/voice.js`, `static/chain/chain.js`). Note: with `default_preset` set in the peer's `config/llamacpp.json`, `ensure_loaded_for_step` in `app/chain/llm_swap.py` overrides the endpoint's `api_base` + `model` at runtime to point at the LLM-capable peer — so for multi-machine the endpoint values are largely vestigial for chain LLM steps. **No endpoint preset is required**: `get_default_as_chain_llm_config()` falls back to the LLM node automatically — the local `llama-server` if this node has the `llm` capability, otherwise the `llm` peer (`config/server.json`) — and `ensure_loaded_for_step` routes/​swaps to the peer's llama-server even with no preset (it only raises if there is no `llm` node anywhere). So a lost/empty `config/llm_config.json` no longer breaks chain jobs.
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
