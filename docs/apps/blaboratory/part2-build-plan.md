# Blaboratory Part 2 — Phased Build Plan

> Execution sequencing for the **simulation systems** (Part 2 of [`design.md`](./design.md),
> lines 168–279). Designed for **one phase per session** to keep context small. Each phase lists
> what to read, what to build, and how to know it's done. Phases are dependency-ordered; each is a
> clean candidate for one ticket (`/create-tickets`, `/work-next-ticket`).
>
> **Per-session rule of thumb:** read `design.md` Part 2 + this phase + the files the phase names +
> the *committed* code of prerequisite phases. You should not need earlier phases' reasoning.

Environment reminders (from CLAUDE.md): use `.venv/bin/python`, `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>` for syntax checks. Stores write under
`config/` (gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH`/`DB_PATH` constants to tmp.
**No new pip dependencies** in these phases (stdlib `sqlite3` only).

**Scope:** this plan fully designs every Part 2 system **except** two heavy-dependency systems,
which are deferred and only noted (see [Deferred](#deferred-noted-not-detailed)): the vector
retrieval index (`sqlite-vec` + llama.cpp `/v1/embeddings`) and the televisor/news generator. Memory
retrieval stays **mechanical** (recency + size-cap) for now — the design's stated MVP path.

**Confirmed design decisions** (carried into the phases below):
- **All occupants act each tick**; `sleep` is just an action a resident can choose/Continue. No
  separate awake/enabled flag.
- The **priority-queue change is bundled into the driver phase** (Phase 4), not a standalone phase.
  HIGH stays the *default* priority so no existing `enqueue` call site changes behavior.
- **Live-append via polling** `/ticks/latest` — no new SSE; the per-job EventBus is explicitly out
  of scope for the game feed.
- Tick cadence + memory caps live in a new `app/apps/blaboratory/config.py` (env-overridable
  constants). Sim work enqueues **one LOW job per tick**. A phone call runs via `execute_chain_job`
  **directly** inside the caller's tick.

---

## Phase 1 — SQLite persistence (`db.py` + migrations + event/log stores)

**Goal:** an append-only event/memory log at `config/blaboratory/blaboratory.db`, with one owner of
the connection + `PRAGMA user_version` migrations. Storage + query helpers only; no sim behavior.

**Read:** design.md §"Persistence (hybrid)"; `app/apps/blaboratory/rooms.py` + `residents_store.py`
(monkeypatchable `*_PATH` + atomic-write conventions to mirror); `app/ticks/persistence.py`
(JSON-index pattern, for contrast).

**Build:**
- `app/apps/blaboratory/db.py`: `DB_PATH` const (monkeypatchable); `get_connection()` (creates
  parent dir, `PRAGMA journal_mode=WAL`, `foreign_keys=ON`, `row_factory=sqlite3.Row`; caches one
  connection per `DB_PATH`, reset when the const changes so tests get a fresh db), `close_connection()`
  test hook; `MIGRATIONS: list[Callable[[Connection], None]]` (index = target `user_version`),
  `migrate()` (reads `PRAGMA user_version`, applies each pending migration in a transaction, bumps
  the version — idempotent, called lazily by `get_connection()` and explicitly at startup).
  Migration 1 creates the tables:
  - `events(id PK, tick, resident_id, room_id, kind, action, payload /*json*/, created_at)` — the
    master log (one row per action/utterance/system event).
  - `chat(id PK, tick, author_resident_id, body, created_at)` — the shared computer-channel feed.
  - `utterances(id PK, call_id, tick, speaker_resident_id, room_id, body, seq, created_at)` —
    phone-call lines.
  - `calls(id PK, tick, caller_resident_id, callee_resident_id, accepted, ended_reason, created_at)`.
  - `consumption_cursors(resident_id, channel /*chat|news*/, last_seen_id, updated_at,
    PRIMARY KEY(resident_id, channel))` — visibility = consumption.
- Sibling store modules (keep `db.py` connection-only): `event_store.py` (`append_event`,
  `events_for_resident`, `events_for_room`, `events_at_tick`, `latest_event_for_room`, `max_tick`),
  `chat_store.py` (`append_chat`, `chat_after`, `latest_chat_id`), `cursor_store.py`
  (`get_cursor`, `set_cursor`).

**Done when:** `tests/apps/test_db.py` passes (monkeypatch `DB_PATH` to tmp): fresh db at
`user_version=0` → `migrate()` lands at latest; re-running `migrate()` is a no-op; append→query
roundtrips for events/chat/utterances/calls; cursor get/set roundtrip; a stored `payload` dict
survives the JSON round-trip.

**Touches:** additive only.

---

## Phase 2 — Prompt composition (`compose(node)`) + migrate Part 1 prompts

**Goal:** a depth-bounded `compose(node)` resolver over JSON `{prompt, variables}` where a variable
may be a literal, a nested prompt object, or a stored-prompt-id reference. Migrate the Part 1
in-code prompts to it. A resolution primitive, not a UI.

**Read:** design.md §"Prompt system"; `app/chain/template.py` (`render_template` — the leaf
substitution to reuse; keyed for `{{var.NAME}}`); `app/apps/blaboratory/prompts.py` (the registry to
migrate).

**Build:**
- `prompt_compose.py`: `compose(node, *, store=None, depth=0, max_depth=16) -> str` — leaf `str`
  returned as-is; `{"prompt": "...{{var.X}}...", "variables": {X: <value>}}` first resolves each
  variable (recurse with `compose` if it's a dict / stored-ref, literal otherwise), then
  `render_template(prompt, variables={k: resolved})`; a variable value `{"prompt_id": "..."}` is
  looked up via `store` and composed; over-depth raises `PromptCompositionError` (mirrors executor's
  depth guard).
- `prompts_store.py`: file-per-doc JSON prompt assets under `config/blaboratory/prompts/<id>.json`
  (`get_prompt_asset`, `list_prompt_assets`, `save_prompt_asset` — same store conventions).
- Refactor `prompts.py`: keep `get_prompt(id)` signature (back-compat for the existing generator);
  express `IDEATE_FREE_TEXT`/`IDEATE_GUIDED`/`ASSEMBLE` as composable nodes so later action/call
  prompts reuse fragments (e.g. an `[Overview]` fragment). Game sequences stay constructed in code.
  **Do not re-point the Phase-1 generator's call site this phase** (lower risk).

**Done when:** `tests/apps/test_prompt_compose.py` passes: literal leaf; one-level `{{var.X}}`;
nested prompt object piped into a parent var; stored-prompt-id ref via a monkeypatched store;
cycle/over-depth raises. Existing `tests/apps/test_generator.py` still green.

**Touches:** `prompts.py` (refactor, signature preserved). Additive otherwise. **No upstream dep —
can be built in parallel with Phase 1.**

---

## Phase 3 — Memory / context pipeline (mechanical gather → cap → fill)

**Goal:** assemble the fixed-section context block for one resident on one tick, mechanically
(recency + size cap), plus the read/write halves of the loop (the *act* half is Phase 4). Depends on
Phases 1 + 2.

**Read:** design.md §"Memory / context pipeline"; Phase 1 + 2 committed code; `models.py` (Resident
shape for the identity line).

**Build:**
- `context_pipeline.py`: `build_context(resident, *, action_node, tick, caps) -> str` fills the
  template **in fixed order**:
  - `[Overview]` — static game/world framing + an identity line from the resident doc
    (name/occupation/personality summary).
  - `[Everyone Knows]` — general lore: read a single JSON lore doc
    (`config/blaboratory/lore/world.json`, file-store) or a constant if empty. (The *writer* is the
    deferred news generator; this only reads.)
  - `[Some Know]` — **emitted empty** (rule TBD — see [open questions](#open-design-questions)).
  - `[You Know]` — this resident's consumed memories: `events_for_resident(id)` newest-first + chat
    up to the cursor, then `apply_caps` (max items + max chars, dropping oldest first).
  - `[Your Action]` — the current action's presentation + inputs + breakpoint clause. Phase 4
    supplies this as an opaque pre-rendered string, decoupling the two phases.
- Helpers `gather_memories(id, caps)`, `apply_caps(items, caps)`; `read_phase(resident, tick)` and
  `write_phase(resident, tick, action_result)` (persists the produced action/utterances as events
  and advances cursors — cursor advance *is* the consumption: `use_computer` advances the chat
  cursor to `latest_chat_id()`, `use_televisor` advances the news cursor, a no-op until the news
  generator exists).
- `config.py`: env-overridable constants (`TICK_INTERVAL_SECONDS=300`, `MAX_MEMORY_ITEMS`,
  `MAX_MEMORY_CHARS`), matching the `os.environ.get(...)` pattern in `app/job_queue.py`.

**Done when:** `tests/apps/test_context_pipeline.py` passes (stores monkeypatched to tmp): the five
sections render in fixed order; `[Some Know]` is empty; `[You Know]` reflects only consumed items
and respects caps (over-cap drops oldest); a `use_computer` write advances the chat cursor so
previously-unconsumed chat becomes consumed on the next build.

**Touches:** additive.

---

## Phase 4 — Priority queue + action framework + first action set + sim driver

**Goal:** (a) extend `app/job_queue.py` to a single-worker, two-lane HIGH/LOW queue; (b) actions as
self-contained plugins with breakpoints + current-activity state; (c) a tick driver (cloning the
`TickScheduler` async-loop) that every N real minutes has **all occupants** take one action on the
**LOW** lane. Depends on Phases 1, 3 (+ 2 for prompts).

**Read:** design.md §"Simulation clock, driver & priority" + §"Channels & actions"; `app/job_queue.py`
(entire — `enqueue`, `_run`, `_pending_ids`, the `_SENTINEL` stop path); every `enqueue(...)` call
site (`app/main.py`, `app/ticks/scheduler.py`); `app/ticks/scheduler.py` (the async-loop lifecycle
to clone); `app/mcp/registry.py` (the `ToolDefinition` declaration pattern to mirror);
`app/chain/steps/llm.py` (the tool-loop) and `app/apps/blaboratory/generator.py` (build a
`ChainJobRequest` + call `execute_chain_job` directly).

**Build:**
- **Priority queue** in `app/job_queue.py`: two explicit FIFO `asyncio.Queue`s (HIGH/LOW) — *not* a
  `PriorityQueue` (avoids tuple-comparison pitfalls on equal priorities). A `Priority` enum
  (`HIGH`, `LOW`). `enqueue(job_id, runner, priority=Priority.HIGH)` — **HIGH is the default** so no
  existing call site needs editing. `_run()` pops HIGH if non-empty else LOW; preserve the on-disk
  `_job_still_queued` recheck and a `_SENTINEL` stop that wakes a worker idle on empty lanes
  (sentinel on both lanes, or an internal "item available" event). `depth`, `is_pending`,
  `cancel_queued`, and the bus methods keep their signatures. The full existing suite must stay
  green — this is the regression-risk surface.
- **Actions** `app/apps/blaboratory/actions/`: each module declares an MCP-style definition (name,
  description, presents-to-LLM schema — mirror `ToolDefinition`), `breakpoints: [{count, breakpoint}]`
  (continue clauses composed into the tick-decision prompt as `count` climbs), and
  `async execute(resident, tick, context, args) -> ActionResult` (emits events + advances cursors via
  Phase 3's `write_phase`; may run sub-sequences). First set: `use_computer.py` (chat catch-up ±
  post), `use_televisor.py` (advance news cursor — mostly a stub until the news generator),
  `use_speakerphone.py` (entry point; body in Phase 6), `sleep.py` (multi-tick via Continue),
  `idle.py`. `registry.py` (`ACTIONS`, `list_actions`, `get_action` — mirrors `mcp/registry.py`).
- `activity_store.py`: current-activity state per resident (action + `count`) so `sleep` starts once
  and Continues.
- `tick_runner.py`: `decide_action(resident, tick) -> (action, args)` — per-tick LLM free-choice:
  build context (Phase 3) with `[Your Action]` = a decision prompt listing available actions + the
  active activity's matching breakpoint clause; run a one-step `ChainJobRequest` (`execute_chain_job`
  direct, like the generator) or the tool-loop; parse the chosen action. **Continue** is one option
  (keeps the current activity). `run_tick(tick_number)` — **all occupants** decide → execute →
  `write_phase`, enqueued on the **LOW** lane. One LOW job **per tick** (keeps a tick atomic).
- `sim_clock.py`: clones `TickScheduler`'s shape (`start/stop/_loop` + `asyncio.sleep`), fires
  `run_tick` every `TICK_INTERVAL_SECONDS`; tick counter = `events.max_tick()+1`.
  `get_sim_clock`/`start_sim_clock`/`stop_sim_clock` wired into `app/main.py` lifespan beside
  `start_scheduler()`.

**Done when:** `tests/test_job_queue_priority.py` (HIGH drains before LOW even if LOW enqueued
first; FIFO within a lane; default enqueue is HIGH; a running job completes before the next pop;
stop wakes a worker idle on empty lanes) **and** the full existing suite are green;
`tests/apps/test_actions.py` + `tests/apps/test_tick_runner.py` pass (patched LLM): each action's
`execute` emits the right events/cursor advances; the decision step parses a chosen action;
`run_tick` over 2 seeded residents produces one event each + advances the tick counter; `sleep`
started on tick T Continues on T+1 with `count` incremented and the breakpoint clause appearing once
`count` crosses its threshold.

**Touches:** `app/job_queue.py` (central, highest-risk — no call-site edits since HIGH is default);
`app/main.py` (lifespan start/stop of the sim clock). Additive otherwise.

---

## Phase 5 — Action/tick API + manual tick controls

**Goal:** the HTTP surface the timeline UI needs. Depends on Phases 1, 4.

**Read:** design.md §"Timeline & event-feed UI"; Phase 1 store query helpers; existing `router.py`.

**Build:** extend `app/apps/blaboratory/router.py`:
- `GET /ticks/latest` → `{tick}` (= `events.max_tick()`).
- `GET /ticks/{tick}/rooms` → per-room most-recent-action **word** at/under that tick (master grid).
- `GET /residents/{id}/events?until_tick=` → newest-first, **truncated at the playhead** (`<= until_tick`).
- `GET /residents/{id}/context?tick=` → the active context/knowledge panel (calls Phase 3
  `build_context`; debug/inspection).
- `GET /rooms/{room_id}/utterances?until_tick=` → call lines in both rooms (Phase 6 fills calls).
- `POST /ticks/fire` (manual single tick now → LOW lane); `POST /clock/{start|stop}` (admin control
  of `SimClock`).

**Done when:** `tests/apps/test_router_sim.py` passes (`TestClient`, patched LLM): seed events
across ticks → `/ticks/latest` correct; `/residents/{id}/events?until_tick=N` is newest-first and
truncated at N; `/ticks/{t}/rooms` returns one action-word per occupied room; `POST /ticks/fire`
advances the counter.

**Touches:** `router.py` (additive routes).

---

## Phase 6 — Phone call as an atomic chain SEQUENCE

**Goal:** `use_speakerphone` runs a real `executor.py` sequence: the callee's LLM accepts/declines
from its own context → topic-select → X exchange steps → weighted `goto` to terminate (fall-through)
or segue (jump back to topic-select with a "previous conversation" bridge). The whole call generates
within the **caller's** tick; the **callee forfeits its own action** that tick. Utterances render in
both rooms. Depends on Phases 1, 3, 4.

**Read:** design.md §"Phone call (atomic, internally structured)"; `app/chain/executor.py` (the
`goto`/`fall_through`/`target_step`/`visit_cap`/weighted alternative pick — these *are* the
segue/terminate primitive); `app/chain/models.py` (`ChainStep`/`Alternative` goto fields); Phase 4
action framework.

**Build:** `call_sequence.py`:
- `build_call_request(caller, callee, caller_ctx, callee_ctx, llm) -> ChainJobRequest` — constructs
  the sequence in code (design says game sequences stay code-built): `accept` (llm, callee context) →
  if declined, terminate → `topic_select` (opening topic) → `exchange` step(s) (alternating speakers,
  bounded by `visit_cap`/breakpoint range) → a `goto` step with two weighted alternatives
  (`fall_through=True` terminate vs `target_step`=topic_select segue).
- `run_call(caller, callee, tick, llm)` — `create_job(JOB_TYPE="blaboratory_call", …)`,
  `execute_chain_job` **directly** (caller's tick owns it, matching the generator's rationale), parse
  each exchange output into `utterances` rows + a `calls` row, mark the callee busy for this tick so
  `run_tick` skips its separate action (forfeit).
- Wire `actions/use_speakerphone.execute` (Phase 4 stub) to pick a callee (random other-occupant for
  the first slice) and call `run_call`.

**Done when:** `tests/apps/test_call.py` passes (patched LLM scripting accept → 2 exchanges →
terminate, and a separate decline case): accept path writes a `calls` row + ordered `utterances`;
decline path writes a short call with no exchange; the callee is marked busy so `run_tick` doesn't
also give it a separate action that tick; a scripted segue re-enters topic-select once.

**Touches:** `actions/use_speakerphone.py` (fills the Phase 4 stub). Additive otherwise.

---

## Phase 7 — Timeline & event-feed frontend

**Goal:** the playable timeline UI. Master grid shows each room's most-recent-action word; detail =
resident info + event log + active context/knowledge panel; manual tick scrubbing (newest-first,
truncated at playhead, no auto-advance); **live append via polling** `/ticks/latest`; phone-call
utterances render in both rooms. Depends on Phase 5 (+ 6 for utterances).

**Read:** design.md §"Timeline & event-feed UI"; `static/apps/blaboratory/blaboratory.js` (extend,
don't rewrite); `static/js/api.js` (`api()` auto-prepends `/v1`). Note: the per-job `EventBus` is
explicitly out of scope for the game feed.

**Build:** extend the existing trio `static/apps/blaboratory/{index.html, blaboratory.js, styles.css}`:
- Grid cells gain a **most-recent-action word** (from `GET /ticks/{tick}/rooms`); empty cells keep
  `+ Fill Room`.
- A **tick scrubber** (prev/next + playhead label) driving `until_tick`; loads on the latest tick;
  no auto-advance.
- **Detail view** gains: resident info (existing) + **event log** (newest-first, truncated at
  playhead, from `/residents/{id}/events?until_tick=`) + **active context/knowledge panel**
  (`/residents/{id}/context?tick=`).
- **Phone-call utterances** rendered in both participants' rooms
  (`/rooms/{room_id}/utterances?until_tick=`).
- **Live append:** poll `/ticks/latest` on an interval; when a new tick lands and the playhead is at
  the newest tick, append it.

**Done when:** manual click-through (see [Verification](#verification-end-to-end-after-phase-7))
works. **Touches:** the blaboratory frontend trio only (the `Apps` nav entry already exists from
Part 1).

---

## Phase 8 — Docs + polish (optional, small)

- Update design.md Part 2 with a "what landed / drifted" section (mirror Part 1's build-notes).
- Note the timeline page behaviors in any nav/TOC docs.
- Confirm `blaboratory_call` + LOW-lane tick jobs render acceptably in the systems Jobs page.

---

## Deferred (noted, NOT detailed)

Both are independently sliceable after the core loop (Phases 1–7) is proven; neither blocks it.

- **D1 — Vector retrieval index.** `sqlite-vec` in the same db + a thin `VectorIndex` helper
  (add/query top-k) + an `embed()` method on the OpenAI-compatible client against llama.cpp
  `/v1/embeddings` (reuse `LlamaCppManager`). Replaces Phase 3's mechanical `[You Know]` gather with
  relevance retrieval; serves lore too. New dependency + extension loading
  (`enable_load_extension=True`) — out of scope until the mechanical path is proven.
- **D2 — Televisor / news generator (lore-building engine).** select-or-invent (weighted) →
  generate story → extract new lore → write back to the `[Everyone Knows]` lore registry;
  first-class news organizations (seeded 3–5); single global feed consumed via `use_televisor`'s
  news cursor (the cursor mechanics already exist from Phases 1/3, so this slots in cleanly).
  Story-only MVP; ComfyUI image slideshows further deferred.

---

## Open design questions

Defaults are chosen so building can proceed; revisit when the relevant phase lands.

1. **`[Some Know]` scoping rule** — design says TBD; Phase 3 emits it empty. Needs a cohort
   definition (per-room? per-relationship? per-topic tag) before it can be non-empty.
2. **Callee selection (Phase 6)** — random other-occupant for the first slice; could later prefer
   residents the caller "knows."

---

## Verification (end-to-end, after Phase 7)

**Automated:** `.venv/bin/pytest tests/apps/ -q`, then the **full** suite `.venv/bin/pytest -q`
(mandatory — the Phase 4 priority-queue change touches shared infrastructure).

**Manual (real LLM, default endpoint preset configured):**
1. Start the server (`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`).
2. Fill 2–3 rooms (Part 1 flow) so there are active residents.
3. `POST /v1/apps/blaboratory/ticks/fire` a few times (or `POST /clock/start` and wait one
   interval). Confirm new jobs appear on the Jobs page on the **LOW** lane and never block a
   manually-created chain/image job (start a chain job mid-tick → it runs first).
4. `GET /ticks/latest` → tick advances; `GET /residents/{id}/events?until_tick=N` → newest-first,
   nothing past N.
5. Trigger a `use_speakerphone` action → confirm a `calls` row + `utterances` rendered in **both**
   rooms.
6. Browser `/apps/blaboratory/`: grid shows action-words; scrub ticks (no auto-advance); open a room
   → event log truncated at playhead + active-context panel; let a tick finish → live-append at the
   newest playhead.

---

## Phase dependency graph

```
P1 db ──┬─▶ P3 context ──▶ P4 queue+actions+driver ──┬─▶ P5 sim API ──▶ P7 timeline UI ──▶ P8 docs
        │                                            │                      ▲
P2 compose ─────────────────────────────────────────┴─▶ P6 phone call ─────┘

Deferred after the P3/P4 loop is proven:
  D1 vector index   ──▶ replaces P3 mechanical gather
  D2 news generator ──▶ feeds [Everyone Knows] + use_televisor cursor
```
Arrow = "needs the prior phase's committed code." P2 has no upstream dep (build early / in parallel
with P1).
