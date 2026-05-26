# Blaboratory

A virtual lab of AI **residents** living in 16 rooms. Part 1 (built) is the
**resident-creation loop**; Part 2 (built, minus two deferred systems) adds the
**simulation** — ticks, actions/channels, memory, phone calls, and a scrubable
timeline. Deferred: the vector retrieval index and the televisor/news generator.

- **[Design](design.md)** — the canonical "what & why" (Part 1 MVP + Part 2 shape).
- **[Part 1 — MVP build plan](mvp-build-plan.md)** — phased sequencing for the resident-creation loop (built).
- **[Part 2 — Simulation build plan](part2-build-plan.md)** — phased sequencing for ticks, channels, memory, and the timeline UI.
- **[D1 — Vector memory & lore retrieval build plan](d1-vector-build-plan.md)** — phased sequencing for the deferred embedding-retrieval index (sqlite-vec + bge-small via llama.cpp).

## Using it (MVP)

1. Open **Apps** (`/apps`) → the **Blaboratory** card → `/apps/blaboratory/`.
2. The page shows a **4×4 grid** of rooms. Empty rooms show **[+ Fill Room]**;
   occupied rooms show the resident's name + occupation.
3. Click **[+ Fill Room]** to open the creation dialog:
   - **Describe** — a free-text description; the model invents every detail.
   - **Build** — fill any official fields you care about; the model fills the
     rest (your values win).
4. Submit → a synchronous **"Generating resident…"** run (a 2-step LLM chain).
   On success the dialog closes and the room fills.
5. Click an occupied room to see the full resident document (identity,
   appearance, personality, backstory).

**Prerequisite:** a default LLM **endpoint** preset must be configured
(Server → LLM → Endpoints) — generation uses `get_default_as_chain_llm_config()`.
With a missing/failed model the request returns `502`.

## How it works

- **Schema** (`app/apps/blaboratory/models.py`) — `Resident` (v1), `Personality`,
  and `ResidentDraft` (the LLM-output validation target). `id` / `schema_version`
  / timestamps are server-assigned.
- **Stores** — residents are file-per-document JSON
  (`config/blaboratory/residents/<id>.json`); occupancy is a separate
  `occupancy.json` over all 16 rooms (`app/apps/blaboratory/rooms.py`).
- **Generator** (`generator.py`) — runs the chain executor **directly** (not the
  shared `JobQueue`): ideate → assemble, parse strict JSON with ≤2 retries,
  merge guided fields, persist **resident first, then occupancy**. Generation
  jobs appear in the **Jobs** page as `blaboratory_resident` for debuggability.
- **API** (`router.py`, prefix `/v1/apps/blaboratory`) — `GET /rooms`,
  `GET /residents/{id}`, `POST /rooms/{room_id}/residents` (`409` occupied,
  `422` bad body, `502` generation failure), `GET /residents` (debug).

## Simulation (Part 2)

Once rooms are filled, the world can run. Every **tick**, each occupant takes one
action (the LLM chooses: `use_computer`, `use_televisor`, `use_speakerphone`,
`sleep`, `idle`, or Continue an ongoing activity). Actions read a fixed-section
context block (`[Overview]`/`[Everyone Knows]`/`[Some Know]`/`[You Know]`/`[Your
Action]`) and write back to an append-only SQLite log
(`config/blaboratory/blaboratory.db`). Visibility = consumption: a resident only
knows chat/news it has consumed (tracked by per-resident cursors).

- **Driving it** — the page's timeline bar has **Fire tick** (one tick now) and
  **Start/Stop clock** (auto-fire every `BLAB_TICK_INTERVAL_SECONDS`, default 300s).
  The clock does **not** auto-start at boot unless `BLAB_SIM_AUTOSTART=1`. Tick
  work runs on the job queue's **LOW** lane so it never starves real jobs.
- **Watching it** — scrub the **tick** timeline (no auto-advance); each occupied
  room shows its most-recent-action word; a room's detail shows the event log
  (truncated at the playhead) + the resident's active context. Phone-call lines
  render in both participants' rooms.
- **Sim API** — `GET /ticks/latest`, `GET /ticks/{tick}/rooms`,
  `GET /residents/{id}/events?until_tick=`, `GET /residents/{id}/context?tick=`,
  `GET /rooms/{id}/utterances`, `POST /ticks/fire`, `GET`+`POST /clock`.

See **[Part 2 — Simulation build plan](part2-build-plan.md)** for module map and
**[Design](design.md)** §"Part 2 — Build notes" for what landed.
