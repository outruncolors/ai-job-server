# Blaboratory

A virtual lab of AI **residents** living in 16 rooms. The MVP (built — Part 1)
is the **resident-creation loop**; simulation (ticks, channels, actions) is
future work (Part 2).

- **[Design](design.md)** — the canonical "what & why" (Part 1 MVP + Part 2 shape).
- **[MVP build plan](mvp-build-plan.md)** — phased build sequencing.

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
