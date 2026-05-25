# Blaboratory MVP — Phased Build Plan

> Execution sequencing for the **resident-creation MVP** (Part 1 of [`design.md`](./design.md)).
> Designed for **one phase per session** to keep context small. Each phase lists what to read,
> what to build, and how to know it's done. Phases are ordered by dependency; each is also a clean
> candidate for one ticket (`/create-tickets`, `/work-next-ticket`).
>
> **Per-session rule of thumb:** read `design.md` Part 1 + this phase + the files the phase names.
> You should not need earlier phases' reasoning, only their committed code.

Environment reminders (from CLAUDE.md): use `.venv/bin/python`, `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>` for syntax checks. Stores write
under `config/` (gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` constants to tmp.

---

## Phase 1 — Package + resident schema
**Goal:** the `app/apps/blaboratory/` package exists and the `Resident` schema validates.
**Read:** design.md §"Resident schema v1".
**Build:**
- `app/apps/__init__.py`, `app/apps/blaboratory/__init__.py`.
- `app/apps/blaboratory/models.py`: `Personality`, `Resident` (exact v1 fields), and
  `ResidentDraft` (all fields Optional, no id/timestamps — the LLM-output validation target).
- `tests/apps/test_models.py`: valid doc parses; missing required field raises; `ResidentDraft`
  accepts partials.
**Done when:** `.venv/bin/pytest tests/apps/test_models.py` passes; `py_compile` clean.
**Touches:** none of the existing app — fully additive.

## Phase 2 — Stores (residents + occupancy)
**Goal:** persist residents and room occupancy.
**Read:** design.md §"Stores (MVP)"; skim `app/image_prompts.py` + `app/tickets/store.py` for the
pattern.
**Build:**
- `residents_store.py`: `RESIDENTS_DIR` const; `list_residents`, `get_resident`, `create_resident`
  (assigns uuid/timestamps/schema_version=1), `save_resident`, `delete_resident`. File-per-doc.
- `rooms.py`: `ROOM_IDS = range(1,17)`, `OCCUPANCY_PATH`; `list_occupancy` (always all 16),
  `get_room`, `is_empty`, `set_occupant` (reject out-of-range / occupied), `clear_room`.
- `tests/apps/test_stores.py`: monkeypatch the dir/path consts to tmp; cover create→get roundtrip,
  occupancy invariants, set-on-occupied raises, out-of-range raises.
**Done when:** store tests pass.
**Touches:** additive.

## Phase 3 — Generator (chain integration + validation)
**Goal:** turn a creation request into a persisted resident via a 2-step chain, synchronously.
**Read:** design.md §"Generation flow" + §"Reuse map"; `app/chain/executor.py` (`execute_chain_job`
signature), `app/chain/models.py` (request/step/alternative), `app/jobs.py`
(`create_job`/`find_job_dir`), `app/llm_config.py` (`get_default_as_chain_llm_config`).
**Build:**
- `prompts.py`: in-code registry keyed by id — `IDEATE_FREE_TEXT`, `IDEATE_GUIDED`, `ASSEMBLE`
  (spells out the v1 field schema, "JSON only, no fences"). Structure so migration to composable
  JSON later is a drop-in.
- `generator.py`: `build_generation_request(mode, free_text, draft, llm)` (2 llm steps),
  `parse_resident_json(text)` (fence-strip + `json.loads` + `ResidentDraft`), `run_generation(...)`
  (create_job → `execute_chain_job` direct → parse w/ ≤2 retries → merge guided fields → build
  `Resident` → persist resident then occupancy; mark job `error` on failure).
- `tests/apps/test_generator.py`: patch `OpenAICompatibleLLMClient.chat_stream` to yield canned
  step-1 prose then valid step-2 JSON; assert resident persisted + occupancy set. Add a
  invalid-then-valid retry case, and a parse-fence case.
**Done when:** generator tests pass (mocked LLM, no real model needed).
**Touches:** additive; no shared-module edits.

## Phase 4 — API router + wiring
**Goal:** HTTP surface for the frontend.
**Read:** design.md §"API"; one existing router include in `app/main.py`.
**Build:**
- `router.py`: `APIRouter` with `GET /rooms`, `GET /residents/{id}`,
  `POST /rooms/{room_id}/residents` (guard `is_empty` → 409; bad body → 422; gen failure → 502),
  optional `GET /residents`.
- `app/main.py`: one `app.include_router(blaboratory_router)` line (with the other includes). No
  page-route changes — the static mount already serves `/apps/**`.
- `tests/apps/test_router.py`: `TestClient(app)` with `chat_stream` patched — rooms list shape,
  create → 201 + persisted + occupancy, 409 on occupied room.
**Done when:** router tests pass.
**Touches:** `app/main.py` (one line).

## Phase 5 — Frontend: /apps landing + Blaboratory grid + Fill Room + detail
**Goal:** the visible loop in a browser.
**Read:** design.md §"Frontend (MVP)"; `static/js/nav.js`; one existing page trio (e.g.
`static/chain/`) + `static/js/api.js`.
**Build:**
- `static/apps/index.html` + `apps.js` + `styles.css` — landing, lists the Blaboratory card; does
  NOT load the systems nav.
- One `Apps` entry in `NAV_ITEMS` (`static/js/nav.js`) — the only shared-frontend edit.
- `static/apps/blaboratory/{index.html, blaboratory.js, styles.css}`: 4×4 grid from `GET /rooms`;
  empty cell **[Fill Room]** → `<dialog>` with Describe/Build toggle → `POST` with "Generating
  resident…" busy state → refetch on success; clicking a room → **detail view** rendering the full
  document by section.
**Done when:** manual click-through works end-to-end (see Verification).
**Touches:** `static/js/nav.js` (one entry).

## Phase 6 — Docs + polish (optional, small)
- Add the page to `docs/index.md` TOC and any nav docs.
- Confirm the `blaboratory_resident` job renders acceptably in the Jobs page.
- Note in design.md anything that drifted during the build.

---

## Verification (end-to-end, after Phase 5)

**Automated:** `.venv/bin/pytest tests/apps/ -q`, then the full suite `.venv/bin/pytest -q` to
confirm no regressions.

**Manual (real LLM, default endpoint preset configured):**
1. Start the dev server: `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`.
2. `curl -s localhost:8090/v1/apps/blaboratory/rooms | jq` → 16 rooms, all empty.
3. `curl -s -X POST localhost:8090/v1/apps/blaboratory/rooms/1/residents -H 'content-type:
   application/json' -d '{"mode":"free_text","free_text":"a grumpy retired astronomer who hoards
   teacups"}' | jq` → returns resident + room_id=1.
4. `curl -s localhost:8090/v1/apps/blaboratory/residents/<id> | jq` → full v1 document, all required
   fields present.
5. Browser: open `/apps` → Blaboratory card → 4×4 grid → **[Fill Room]** on an empty room → try
   both Describe and Build modes → busy state → resident appears → click the room → detail view
   shows the document. Confirm a filled room no longer shows [Fill Room], and `POST` to an occupied
   room returns 409.

## Phase dependency graph

```
P1 schema ─▶ P2 stores ─▶ P3 generator ─▶ P4 router ─▶ P5 frontend ─▶ P6 docs
```
Each arrow = "needs the prior phase's committed code." No phase needs another phase's *reasoning* —
only this plan + design.md Part 1.
