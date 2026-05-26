# Blaboratory — Design

> Canonical design reference for the **Blaboratory** app. The "what & why."
> Build sequencing lives in [`mvp-build-plan.md`](./mvp-build-plan.md).
> This doc is self-contained — a build session needs only this + the build plan.

## Overview

Blaboratory is an LLM/automation **app** (a consumer experience, distinct from the backend
"systems" like chain/voice/image) built on the ai-job-server stack. AI **residents** live in
rooms of a virtual lab and interact socially through three channels. The world simulates
continuously in the background; the UI lets you scrub a numbered **tick** timeline of what
happened.

**Apps vs systems separation:** consumer apps live behind a separate `/apps` landing, walled off
from the systems nav. Blaboratory backend = `app/apps/blaboratory/`, frontend =
`static/apps/blaboratory/`. The single bridge from the systems UI is one `Apps` entry in
`static/js/nav.js`; apps pages do not carry the systems nav.

**Reuse principle:** lean on the existing chain/sequence engine, LLM client, MCP tools, and store
patterns. Game-specific logic lives in the game code; genuinely generic improvements get pushed
DOWN into the shared backend so other apps benefit.

## Terminology (standardized)

- **Tick** — the unit of simulation *and* playback. Fires every **5 real-world minutes**
  (configurable). During a tick, **all active residents take exactly one action**. Ticks are
  **numbered** (#35, #36, …), have **non-fixed wall-duration**, and **no in-fiction time** passes
  between them. (There is no separate "segment" concept.)
- **Resident** — an AI inhabitant; a single living JSON document with a `schema_version`.
- **Room** — one of 16 fixed cells (#1–#16). Occupancy is a separate store, never a field on the
  resident.
- **Action** — a self-contained plugin a resident performs on its tick (`use_computer`,
  `use_televisor`, `use_speakerphone`, `sleep`, `idle`, …).
- **Event** — a row in the simulation log (an action, a line of dialogue, a news broadcast, …).

---

# Part 1 — MVP: Resident Creation (buildable now)

The first slice is the **visible resident-creation loop**, nothing simulated yet:

`/apps` landing → Blaboratory page (themed 16-room 4×4 grid) → empty room **[Fill Room]** →
two-mode creation form → generation runs (busy spinner) → resident appears in that room → click
the room → **detail view** showing the document.

### Resident schema v1 (exact fields)

```
id, schema_version (=1), created_at, updated_at,
name, age, sex,
height, build, hair_color, hair_style, eye_color, skin_tone,
distinguishing_features: list[str],
occupation,
personality: { traits: list[str], quirks: list[str], speech_style: str },
backstory
```

No `room_id` (occupancy is separate), no `memories` (retrieved at action-time later), no media
refs, no `date_of_birth`. Physical fields are "driver-license" style, chosen to be useful for
image prompts later. `id`/`schema_version`/timestamps are **server-assigned**, never from the LLM.

### Creation: two input modes, one generator

- **Free-text mode:** the user gives an overall description; the model invents all details.
- **Guided mode:** every official field is exposed; the user fills what they want, the model fills
  the blanks (user-supplied fields win).

Both feed the **same multi-step generation chain**, differing only in the first step's prompt and
input.

### Generation flow

The generator runs the existing **chain executor** directly (NOT via the shared single-worker
`JobQueue`, to avoid starving real jobs), **synchronously** within the request:

1. `create_job("blaboratory_resident", …)` + `find_job_dir` → on-disk scaffold (visible in the
   Jobs page for debuggability; recovery correctly marks an interrupted one `error`).
2. Build a 2-step `ChainJobRequest`: **(1) ideate** — free-text or guided prompt produces rich
   character prose; **(2) assemble** — consumes `{{previous}}`, emits **strict JSON** for the
   schema. LLM config from `get_default_as_chain_llm_config()` (`app/llm_config.py`).
3. `await execute_chain_job(job_id, job_dir, request, event_bus=bus)` directly.
4. Read `final_output.txt` → strip ```json fences → `json.loads` → validate into `ResidentDraft`.
   **Retry on parse failure** (≤2): re-run an assemble-only request seeded with the captured
   step-1 prose.
5. Merge validated draft with user-supplied guided fields; build full `Resident` (server-assigned
   id/timestamps/schema_version).
6. Persist **resident first, then occupancy** (so a crash never points occupancy at a missing
   resident). Guard `is_empty(room_id)` at request entry to avoid wasting an LLM run.

MVP prompts live **in code** (a registry keyed by id), structured so they migrate cleanly to the
composable prompt JSON later (see Part 2 → Prompt system).

### Stores (MVP)

- **Residents** — file-per-document: `config/blaboratory/residents/<id>.json` (list by globbing).
- **Occupancy** — `config/blaboratory/occupancy.json`: `{ "1": "<resident_id>"|null, … }` for all
  16 rooms. Invariants: room in 1–16; `set_occupant` rejects an occupied room.

Both follow the existing JSON-store conventions (`app/image_prompts.py`, `app/tickets/store.py`):
module-level `*_DIR`/`*_PATH` constants (monkeypatchable in tests), `_read`/`_write`, atomic writes.

### API (router mounted at `/v1/apps/blaboratory`)

- `GET /rooms` → `{ rooms: [ { room_id, occupant: {id,name,occupation,age}|null }, …16 ] }`
- `GET /residents/{id}` → full `Resident` (404 if missing)
- `POST /rooms/{room_id}/residents` — body `{ mode: "free_text"|"guided", free_text?, fields? }` →
  `201 { resident, room_id, job_id }`; `409` if occupied; `422` bad body; `502` if generation
  fails after retries.
- `GET /residents` (optional) → list all (debug).

### Frontend (MVP)

- `/apps` landing (`static/apps/index.html` + `apps.js` + `styles.css`) — lists app cards; does
  NOT load the systems nav. Blaboratory card links to `/apps/blaboratory/`.
- One `Apps` entry added to `NAV_ITEMS` in `static/js/nav.js` (the only shared-frontend edit).
- Blaboratory page trio (`static/apps/blaboratory/{index.html, blaboratory.js, styles.css}`):
  - **4×4 grid** from `GET /rooms`. Occupied cell = occupant card; empty cell = **[Fill Room]**.
    (Pre-sim, occupied cells show the name; the action-word + event log arrive with the sim build.)
  - **[Fill Room]** opens a `<dialog>` with a Describe/Build toggle (free-text vs guided form).
    Submit → `POST`; show a simple **"Generating resident…"** busy state (synchronous request; no
    SSE yet). On success, close + refetch grid.
  - **Detail view** (master/detail): clicking a room loads the full document and renders it grouped
    by section. (Later gains the event log + active-context panels — Part 2.)

### Reuse map (existing code)

| Need | Reuse |
|---|---|
| Run a generation chain | `execute_chain_job` — `app/chain/executor.py` |
| Request/step shapes | `ChainJobRequest`/`ChainStep`/`Alternative` — `app/chain/models.py` |
| LLM config from default | `get_default_as_chain_llm_config()` — `app/llm_config.py` |
| Job scaffold + lookup | `create_job`/`find_job_dir` — `app/jobs.py` |
| Enqueue pattern (reference) | chain create route — `app/main.py` |
| JSON store shape | `app/image_prompts.py`, `app/tickets/store.py` |
| Template substitution | `render_template` — `app/chain/template.py` |
| Static serving (auto) | `app/main.py` static mount (`html=True`) serves `/apps/**` |

### Risks / notes

- **Don't enqueue generation on the shared `JobQueue`** — call `execute_chain_job` directly.
- Generation jobs ARE visible in the systems Jobs page (`job_type="blaboratory_resident"`) — kept
  for debuggability; the synchronous handler must mark the job `error` on failure so it isn't left
  `running`.
- **Profiles export:** residents + occupancy are game *state*, not server config — do NOT register
  them in `MasterProfile` for the MVP.

### Build notes (what landed / drifted)

Part 1 is built (`app/apps/blaboratory/`, `static/apps/blaboratory/`). Minor decisions made
during implementation, recorded so the design stays truthful:

- **`run_generation(room_id, mode, free_text?, fields?, llm?)`** owns both persistence *and*
  occupancy (resident first, then `set_occupant`), and re-guards `is_empty(room_id)` at entry. The
  optional `llm` arg is a test seam; production reads `get_default_as_chain_llm_config()`.
- **Missing/failed LLM config** raises `GenerationError` (mapped to `502`) rather than a 500. The
  `POST` route also re-checks occupancy on failure so a lost race reports `409`, not `502`.
- **Retry** re-runs an *assemble-only* single-step chain seeded with the captured ideate prose
  (read from `steps/NNN_ideate/output.txt`), reusing the same job dir; the assemble prompt's
  `{{previous}}` resolves to that prose.
- **`GET /residents`** (the "optional" debug route) is implemented. A dangling occupancy pointer
  (resident deleted under it) renders as an empty room rather than erroring.
- Prompts live in `prompts.py` as an id-keyed registry (`IDEATE_FREE_TEXT`, `IDEATE_GUIDED`,
  `ASSEMBLE`) — plain `{{var}}` text, drop-in for the Part 2 composable-prompt system.

---

# Part 2 — Future systems (shaped, build later)

These are designed but out of MVP scope. Build order is open; each is independently sliceable.

## Persistence (hybrid)

- **JSON docs** (existing pattern): residents, world/lore knowledge, prompt assets, room layout —
  config-like, low-volume, human-editable, exportable.
- **SQLite** (`config/blaboratory/blaboratory.db`, stdlib `sqlite3`, no new dep): the event/memory
  log — `events` (+ audience/exposure), chat, utterances, calls. Append-heavy, query-driven reads.
- One small `db.py` owns the connection + `PRAGMA user_version` migrations.

## Memory / context pipeline

Loop: **read → act → write.** Before acting, assemble a context **block** via a common template;
feed to LLM; save the response in a predictable format so it becomes future memory.

Template (fixed section order):
```
[Overview]       You are a resident in Blaboratory. <game/world framing + identity>
[Everyone Knows] world/general lore — identical for every resident
[Some Know]      scoped knowledge (DEFERRED — empty in MVP; rule TBD)
[You Know]       this resident's consumed memories (see consumption rule)
[Your Action]    what they're doing now + inputs + the action's breakpoint clause
```

- **Prepare pipeline = mechanical** for MVP (gather → recency/size caps → fill template). Later:
  an MCP tool can fetch more relevant context.
- **Visibility = consumption, not exposure.** A resident only knows chat/news they've actively
  consumed via `use_computer`/`use_televisor`. Tracked by per-resident **consumption cursors**
  (last-seen chat id, last-seen news id). Unconsumed events don't register.
- Retrieval uses the **vector index** (below) for relevance once memories grow.

## Simulation clock, driver & priority

- **Continuous background generation** while the server is up.
- **Unified priority queue** (extend `app/job_queue.py`): HIGH (image/voice/chain/manual +
  interactive game actions) always popped before LOW (background game generation). One worker; a
  running task is not interrupted mid-flight.
- **Tick** every 5 real minutes (configurable); all active residents act. Reuse the
  `app/ticks/scheduler.py` pattern.

## Channels & actions

- **Televisor** = world→resident broadcast (separate news generator, below). Residents only
  receive/consume; never "act" it.
- **Chat + Speakerphone** = resident actions, chosen by the LLM from context, exposed as **MCP
  tools** + the LLM tool-loop (`app/mcp/registry.py`, `app/chain/steps/llm.py`).
- **Actions are self-contained plugins** (mirror chain step-runners + MCP tools). Each declares how
  it presents itself to the LLM, what it executes (events, cursor advances, sub-sequences), and its
  **breakpoints**.
- **Breakpoints** unify the per-tick continue/switch decision, activity duration, and call
  length/segue: `continue_breakpoints: [{count, breakpoint}]`. As an activity's `count` climbs, the
  matching clause is composed into the tick-decision prompt to nudge wrapping up. Per-tick decision
  is **LLM free-choice** each tick (Continue is one option).
- **Current-activity state** lets multi-tick activities (e.g. `sleep`) start once and Continue.
- First sim-slice action set: `use_computer` (chat catch-up ± post), `use_televisor`,
  `use_speakerphone`, `sleep`, `idle`.

### Phone call (atomic, internally structured)

A → "attempt voice call"; the **callee's LLM** accepts/declines from its own context. On accept, a
**conversation sequence** runs: an LLM step picks the caller's opening topic → X exchange steps →
weighted `goto` to **terminate** (fall through) or **segue** (jump back to topic-select with a
"previous conversation" bridge). Duration is LLM-signalled within a breakpoint-bounded range. The
whole call generates within the caller's tick; the callee forfeits its own action that tick
(busy = single tick). This is literally a chain sequence (`executor.py` reuse).

## Prompt system (composable resolution primitive — not a UI)

A prompt is JSON: `{ "prompt": "<text with {{vars}}>", "variables": { name: value } }`. A
`compose(node)` resolver renders it; a variable value may be a literal, another prompt object
(resolved recursively first, output piped in), or a reference to a stored prompt by id —
composition until the full text is built, then piped to the LLM or into a parent. Reuses
`render_template` for leaf substitution; depth-bounded. No builder UI, no version history (git
covers it); optionally a Claude skill generates the JSON. Game sequences stay constructed in code.

## Televisor / news generator (lore-building engine)

- **Invented world flavor**, branching from a seed (cities/countries/events). Reads from AND writes
  to the shared **lore registry** (= `[Everyone Knows]`), so the world accretes consistent lore.
  Lab/resident activity does NOT appear on TV in the MVP (no feedback loop).
- Per segment, balance **referencing / extending / creating** lore via a structured pipeline:
  select-or-invent (weighted) → generate story → extract new lore → write back.
- **News organizations** are first-class (name, history, vibe, niche; frame the story). Seeded set
  (3–5), can grow.
- **Single global feed**; `use_televisor` catches a resident up on unseen segments (cursor).
- **MVP fidelity = story-only**; ComfyUI image slideshows deferred (reuse `image_prompt` +
  ComfyUI runner then).

## Lore + memory retrieval (vector)

- **`sqlite-vec`** — vectors in the same SQLite db as the event log (confirmed feasible:
  `enable_load_extension=True`). Thin `VectorIndex` helper (add/query top-k).
- **Embeddings via llama.cpp `/v1/embeddings`** — run an embedding GGUF through the
  OpenAI-compatible client (add an `embed()` method); reuse `LlamaCppManager`. Backend changes
  pushed down per the reuse principle.
- Serves both **lore** retrieval and resident **memory** retrieval (one index).

## Timeline & event-feed UI (master/detail)

- **Master:** the 4×4 grid. Occupied rooms show a single word for their most recent action; empty
  rooms show **[Fill Room]**.
- **Detail:** click a room → resident info + the **event log** + the resident's **active
  context/knowledge** (what they currently know — inspection/debugging).
- **Playback = manual scrub by tick.** Loads on the latest tick; navigate tick-by-tick. A
  resident's event log is newest-first (playhead tick at top, prior ticks below), **truncated at
  the playhead**. No auto-advance.
- **Live append:** a finishing tick appears as a new timeline entry (poll the event log or a
  lightweight SSE feed — NOT the per-job EventBus).
- A phone call's utterances render in **both** participants' rooms.

---

## Part 2 — Build notes (what landed / drifted)

Part 2 is built **except** the two deferred systems (vector retrieval, news generator). Phased
sequencing lived in [`part2-build-plan.md`](./part2-build-plan.md). Decisions made during the build,
recorded so the design stays truthful:

- **Persistence** — `app/apps/blaboratory/db.py` owns the connection + `PRAGMA user_version`
  migrations; per-table helpers are `event_store` / `chat_store` / `cursor_store` / `utterance_store`.
  The connection uses `check_same_thread=False` (the single connection is shared between the event
  loop and worker/threadpool threads; access is effectively serialized).
- **Context pipeline** — `context_pipeline.build_context` fills the five fixed sections; `[Some Know]`
  is **emitted empty** (rule still TBD). `[Everyone Knows]` reads `config/blaboratory/lore/world.json`
  (the news-generator *writer* is deferred). Retrieval is mechanical recency/size-cap
  (`gather_memories` + `apply_caps`); the vector index will later slot in behind `gather_memories`.
- **Priority queue** — `app/job_queue.py` gained two FIFO lanes (`Priority.HIGH`/`LOW`) sharing the
  one worker via a counting semaphore. **HIGH is the default**, so no existing call site changed; tick
  work enqueues on LOW.
- **All occupants act each tick**; `sleep` is just an action (no awake/enabled flag). Current
  multi-tick activity (action + count) lives in `activity_store`; the per-tick decision is an LLM
  free-choice (`tick_runner.decide`/`run_tick`) with Continue as one option and the activity's
  breakpoint clause composed into the prompt as `count` climbs.
- **Sim clock** — `sim_clock.SimClock` clones the `TickScheduler` loop and fires **one LOW job per
  tick**. It is wired into the FastAPI lifespan but **auto-start is gated by `BLAB_SIM_AUTOSTART`
  (default off)** so the server never silently runs continuous LLM generation; the clock is otherwise
  driven via `POST /clock/{start,stop}` and `POST /ticks/fire`.
- **Phone call** — `call_sequence.run_call` runs inside the caller's tick (the callee is marked busy
  and forfeits its action). The turn loop (accept/decline → topic → alternating lines →
  continue/segue/end) is **orchestrated in Python, reusing `execute_chain_job` per turn** rather than
  encoded as literal weighted-`goto` steps — a deliberate, testable simplification of the
  single-goto-chain framing; re-encoding it as goto steps is a clean later refactor. Each line is
  written to **both** rooms. Callee selection is a random other occupant.
- **Prompt composition** — `prompt_compose.compose` resolves `{prompt, variables}` nodes (literal /
  nested / stored-by-id), substituting only `{{var.NAME}}` and leaving chain tokens intact;
  `prompts_store` backs `{"prompt_id": ...}` references. Part 1 prompts now route through it
  (`prompts.get_prompt` unchanged externally).
- **Timeline UI** — the existing `static/apps/blaboratory/` trio gained a tick scrubber, per-cell
  action word, an event log (merged with call utterances) + active-context panel, and **polling-based**
  live append (`/ticks/latest` every 5s — no new SSE).

Still deferred / open: the **televisor/news generator**, the **`[Some Know]`** scoping rule, and
ComfyUI image slideshows. (The **vector retrieval index** landed in D1 — see below.)

---

## D1 — Vector memory & lore retrieval — Build notes (what landed / drifted)

Built per [`d1-vector-build-plan.md`](./d1-vector-build-plan.md), phases D1.1–D1.5. Replaces the
mechanical recency `[You Know]` gather with **hybrid** retrieval (recency floor ∪ relevance), one
index serving resident memory now and lore (D2) later.

- **Store** — `sqlite-vec==0.1.9` loaded on the shared `db.py` connection (`VEC_AVAILABLE` flag,
  logged-once fallback). Migration 2 adds a `vec_memories` **vec0** vtable (`embedding float[384]` +
  `resident_id`/`kind`/`ref_id`/`tick` metadata) and a `vec_rowmap` dedupe table. The migration is a
  **no-op when the extension is unavailable** (retrieval stays mechanical), though `user_version`
  still advances to 2. `vector_index.py` is the thin `is_available()`/`add()`/`query()` helper; scope
  filters live in the KNN `WHERE` (resident match incl. global rows, `kind IN (...)`, and a chat-only
  `ref_id <= max_chat_id` range honoring the consumption cursor).
  - **Drift:** vec0 0.1.9 **rejects NULL** in TEXT/INTEGER metadata columns, so "global" (lore) rows
    are stored as the **empty-string sentinel** rather than `NULL` as the plan's schema comment said;
    `query()` surfaces/maps it transparently. KNN distance is L2 (euclidean), nearest-first.
- **Embedder** — bge-small-en-v1.5, **384-dim**, served by a *second*, app-managed `llama-server`
  (`LlamaCppEmbedManager`, `app/llamacpp/embed_manager.py`) on `llm`-capable nodes — fixed argv
  (`--embeddings --pooling cls --port 8081 --ctx-size 512 -ngl 99`), adopt-if-running, `/health`
  readiness, ring-buffer logs, `killpg` teardown. Config fields `embed_port`/`embed_model_path`/
  `embed_pooling` on `LlamaCppConfig`; control routes `/v1/llamacpp-embed/{status,start,stop,restart,
  logs}`; started/adopted at lifespan and stopped on shutdown, gated on the `llm` capability. With
  `embed_model_path` unset the embed server simply stays down.
- **Client + config** — `OpenAICompatibleLLMClient.embed()` (batched POST `/embeddings`, vectors in
  index order, errors → `EmbedError`); `app/apps/blaboratory/embeddings.py` carries port/model/dim/
  query_prefix and resolves the embed URL from the `llm` peer (local `127.0.0.1` when llm-capable).
  The bge **query-instruction prefix is applied to queries only** (document/query asymmetry).
- **Indexing** — `memory_index.index_pending()` runs once at the top of `run_tick`: a batched,
  idempotent backfill of every `events`/`chat`/`utterances` row not yet in `vec_rowmap` (LEFT JOIN),
  embedded and added. Scoping: events → `resident_id`, chat → **global** (the reader's cursor scopes
  visibility at query time), utterances → speaker. Keeps embed calls **out** of the synchronous
  `write_phase`; degrades to a logged-once no-op when the extension/embed server is unavailable.
- **Retrieval** — `context_pipeline.build_context`/`read_phase` are now **async**;
  `retrieve_memories()` merges the recency floor (`RECENCY_FLOOR_ITEMS`, kept verbatim) with the
  top-k (`RELEVANT_TOP_K`) similar items (deduped, scoped), then `apply_caps` (recent wins ties). When
  the index is unavailable, nothing is indexed yet, or the embed server is unreachable, it falls back
  to the **byte-identical** mechanical capped gather — the sim never blocks on the index. All
  `build_context` call sites (`tick_runner`, `call_sequence` ×4, the context route) were awaited.
- **Re-index on model change (LOUD):** the 384-dim vec0 schema is **model-specific**. Switching the
  embedder to a different dimension is **incompatible** with the existing vtable — you must `DROP TABLE
  vec_memories`, clear `vec_rowmap`, and re-run `index_pending` to rebuild. There is no automatic
  migration for a dimension change.

**Still deferred:** `[Some Know]`/lore *content* (D2 — the schema already carries `kind='lore'`/global
rows so it slots in without another migration); query-definition tuning (recency-window-as-query is the
default knob). Ops/deploy steps live in [`ops-d1-embeddings.md`](./ops-d1-embeddings.md).
