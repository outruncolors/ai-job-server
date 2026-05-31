# Prattletale Phase 1 — Foundation (text-first) Build Plan

> Execution sequencing for the **text-first conversation loop** (then voice). Designed for **one
> sub-phase per session** to keep context small. Each sub-phase lists what to read, what to build,
> and how to know it's done. Sub-phases are dependency-ordered; each is a clean candidate for one
> ticket.
>
> **Per-session rule of thumb:** read [`design.md`](./design.md) + this sub-phase + the files the
> sub-phase names + the *committed* code of prerequisite sub-phases. You should not need earlier
> sub-phases' reasoning. Copy-paste session-starters: [`phase1-prompts/`](./phase1-prompts/README.md).

Environment reminders (from CLAUDE.md): `.venv/bin/python` (3.13), `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>`. Stores write under `config/`
(gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` constants to `tmp_path`. **No new
pip dependencies.** Generation runs the chain executor **directly** (not the JobQueue), mirroring
Hoodat/Blaboratory. **Don't commit until reviewed.**

**Scope:** SP1–SP5 deliver a working text-only user↔Hoodat chat; SP6 adds voice + timing; SP7
hardens + documents. Model×Model, plugins, ticks, and the trace/graph UI are later phases.

---

## SP1 — Scaffold + data model + store (no LLM)

**Goal:** the app package exists and a conversation can be created, read, and have turns
appended/replaced on disk. No LLM, no network, no frontend.

**Read:** `design.md` §"Terminology & data model"; `app/apps/hoodat/__init__.py` +
`characters_store.py` (file-per-doc atomic-write `tmp`+`os.replace` pattern, slug ids);
`app/cruddables/envelope.py` (`slugify`, `unique_id`, `now_iso`); `app/main.py` router-include
region (lines ~60–70 imports, ~237–245 includes); `static/apps/apps.js`.

**Build (additive):**
- `app/apps/prattletale/__init__.py`.
- `app/apps/prattletale/models.py` — Pydantic `Conversation`, `DeviceUser`, `ConversationConfig`,
  `Turn`, `Item`; `ItemType` / `Author` / `ItemStatus` enums. Mirror the design shapes exactly.
- `app/apps/prattletale/store.py` — `CONVERSATIONS_DIR` const (monkeypatchable); atomic writes;
  `list_conversations`, `get_conversation`, `create_conversation` (slug id, both files, empty
  transcript), `update_conversation`, `delete_conversation`; transcript ops `get_transcript`,
  `append_user_turn(id, items)`, `append_model_turn(id, items, *, job_id)`,
  `append_error_turn(id, message, *, job_id)`, `replace_turn(id, turn_id, items, *, author,
  job_id)`, `write_trace(id, turn_id, trace)`. Append ops re-read before write; assign monotonic
  turn ids (`t%04d` via `next_turn_seq`) and item ids (`<turn_id>-i%02d`).
- `app/main.py`: import + `app.include_router(prattletale_router)` (empty router stub for now).
- `static/apps/apps.js`: add the Prattletale card.

**Done when** `tests/apps/test_prattletale_store.py` passes (monkeypatch `CONVERSATIONS_DIR` to
tmp): create writes both files with a slug id; `append_user_turn`/`append_model_turn` assign
monotonic turn+item ids and round-trip; `replace_turn` overwrites in place (same turn_id, new
items); `append_error_turn` yields one `system_error` item; delete removes the folder. Full
existing suite still green (touched `main.py`).

**Touches:** additive; `main.py` (one import + include), `apps.js` (one card).

---

## SP2 — Prompts + parser (no network)

**Goal:** the `prattletale/turn` prompt (+ format-hygiene guard) is registered and seeds into the
Prompt Pal store; `parse_items` turns tagged-line output into ordered items.

**Read:** `design.md` §"Turn-generation pipeline" (esp. the parser + guard subsections);
`app/apps/hoodat/prompts.py` (the `register(...)` calls + `SPOKEN_ONLY_GUARD`);
`app/prompt_pal/registry.py` (`register`, `_PROMPT_MODULES`, `seed_registered`);
`app/prompt_pal/service.py` (`get_text`, `get_guard`); `app/apps/hoodat/prompts.py::
render_character_context` (the `{{var.character}}` shape).

**Build (additive):**
- `app/apps/prattletale/prompts.py` — `register("prattletale", "turn", title=, prompt=, variables=,
  guard={...})`. The prompt instructs the tagged-line format (`[say]/[do]/[narration]/[feel]`,
  one bubble per line, short texty bubbles) and consumes `{{var.character}}`, `{{var.scenario}}`,
  `{{var.role_instructions}}`, `{{var.user_persona}}`, `{{var.transcript}}`. The guard does format
  hygiene only (every line tagged, strip leaked meta/OOC; do **not** merge bubbles).
- `app/prompt_pal/registry.py`: append `"app.apps.prattletale.prompts"` to `_PROMPT_MODULES`.
- `parse_items(raw)` + `_strip_fences(raw)` (in `prompts.py` or a small `parsing.py`).

**Done when** `tests/apps/test_prattletale_prompts.py` passes: after `seed_registered()` the
`(prattletale, turn)` entry exists in a monkeypatched Prompt Pal store and `get_text` composes it;
`parse_items` maps each tag to the right `ItemType`, coalesces an untagged continuation line into
the previous item, defaults a lone untagged line to `dialogue`, strips ``` fences, and raises
`GenerationError` on empty/whitespace. Existing Prompt Pal tests still green.

**Touches:** `prompt_pal/registry.py` (one tuple entry). Additive otherwise. **No dep on SP1 —
can be built in parallel.**

---

## SP3 — Generator pipeline (LLM wired)

**Goal:** `run_model_turn(conversation_id)` runs the full pipeline against a real/default LLM and
persists a model turn + trace, or an error turn on failure. Depends on SP1 + SP2.

**Read:** `design.md` §"Turn-generation pipeline" + §"Commit semantics" + §"Error handling";
`app/apps/hoodat/generator.py` (`_resolve_llm`, `_run_single_step` with a guard step,
`run_create` scaffolding) and `app/apps/blaboratory/generator.py` (direct-executor pattern);
`app/chain/models.py` (`ChainJobRequest`/`ChainStep`/`Alternative`); `app/chain/executor.py`
(`execute_chain_job` signature, `final_output.txt`); `app/llm_config.py`
(`get_default_as_chain_llm_config`); `app/jobs.py` (`create_job`, `find_job_dir`); committed SP1
store + SP2 prompts/parser.

**Build (additive):**
- `app/apps/prattletale/generator.py` — `GenerationError`; `_resolve_llm(llm)`;
  `build_context(conversation, character, transcript) -> dict` (pure; the recent-turn window
  skipping hidden/error items); `build_turn_request(context_vars, llm) -> ChainJobRequest`
  (`steps=[turn, guard]`, prompt via `get_text`, guard via `get_guard`);
  `async run_model_turn(conversation_id, llm=None) -> tuple[dict, str]` — load conv+transcript,
  `get_character` (404→`GenerationError`), `build_context`, `create_job`/`find_job_dir`/
  `execute_chain_job`, `parse_items(final_output)`, `store.append_model_turn`, `store.write_trace`;
  on any failure `store.append_error_turn` and return that turn (do not raise to the router).

**Done when** `tests/apps/test_prattletale_generator.py` passes: with a stubbed chain executor
(monkeypatch `execute_chain_job` to write a known `final_output.txt`), `run_model_turn` on a
seeded conversation appends a committed model turn with ≥1 correctly-typed item and writes
`traces/<turn>.json`; a forced empty/garbage output produces a `system_error` turn (not a raised
exception); `build_context` excludes `hidden_from_context` + `system_error` items and renders an
empty persona cleanly.

**Touches:** additive.

---

## SP4 — Router / API

**Goal:** the HTTP surface from `design.md` §"API surface" works end-to-end against the generator.
Depends on SP1–SP3.

**Read:** `design.md` §"API surface"; `app/apps/hoodat/router.py` (APIRouter prefix, request
models, `GenerationError`→HTTP mapping, 404 patterns); committed SP3 generator.

**Build (additive):**
- `app/apps/prattletale/router.py` — `APIRouter(prefix="/v1/apps/prattletale")`; request models
  for create + post-turn; `GET/POST/DELETE /conversations`, `GET /conversations/{id}` (returns
  `{conversation, transcript}`), `POST /conversations/{id}/turns` (append user turn → await
  `run_model_turn` → return `{user_turn, model_turn}`), `POST /conversations/{id}/turns/{turn_id}
  /retry`. Map missing conversation/counterpart → 404.
- Replace the SP1 stub include in `main.py` with the real router.

**Done when** `tests/apps/test_prattletale_router.py` passes (TestClient, stubbed/monkeypatched
generator): create returns 201 + persisted both files; create against a missing counterpart 404s;
posting a user turn returns `{user_turn, model_turn}`; retry on an error turn replaces it in place;
delete removes the folder + returns 200/204; `GET /conversations/{id}` returns conversation +
transcript.

**Touches:** `main.py` (swap stub→real router).

---

## SP5 — Frontend (iMessage UI, text-only)

**Goal:** a human can create a conversation and exchange turns in the browser. Depends on SP4.

**Read:** `design.md` §"Mission"/"data model"/"API surface"; `static/apps/hoodat/` (fetch/render
conventions, `api()`/`_escHtml`, page skeleton); `docs/reference/ui-standards.md` +
`ui-cheatsheet.md`; `static/apps/apps.js` (card already added in SP1).

**Build (additive):** `static/apps/prattletale/` — `index.html` (skeleton + nav loader),
`prattletale.js`, `styles.css`:
- Conversation list for the active device user (counterpart name + avatar from Hoodat, last-item
  preview, timestamp) + **New conversation** form (pick counterpart character, scenario, role
  instructions, persona).
- Chat view: turns rendered as avatar-grouped bubble stacks, bubble shape per item type
  (dialogue/action/narration distinct); composer with **mode-cycling** (dialogue/action/narration)
  + multi-item drafting + commit; **client-side typing indicator** during the POST; **error
  bubble** with a **Retry** button wired to the retry endpoint.

**Done when** (manual, real LLM): create a conversation against an existing Hoodat character; send
a multi-item turn; see a typing indicator then the model's bubble stack; force a failure (bad LLM
endpoint) → error bubble → Retry replaces it in place; reload restores the full transcript from
disk. No automated assertion required beyond SP4's API tests.

**Touches:** additive (new static dir).

---

## SP6 — Voice + timing (the text-first/voice split)

**Goal:** model items gain audio + a realistic reveal cadence; everything degrades to text when
voice is off/unavailable. Depends on SP3–SP5.

**Read:** `design.md` §"Voice + timing"; `app/chain/steps/voice.py` (`run_voice_step`,
auto-segmentation, wav output); `app/omnivoice/runner.py`; `app/voice_presets.py`
(`get_preset`/`resolve_preset_wav`); the `_wav_duration` helper in
`app/voice_presets_router.py`; `app/server.py::requires_capability`; the `/v1/jobs/voice` route in
`app/main.py`.

**Build:**
- Activate `config.voice_enabled` / `typing_timing_enabled` (default off; UI toggle).
- In the generator (or a `voice.py` sibling): after a successful text turn, synthesize model
  `dialogue` items with the counterpart's `voice_preset_id` and model `narration`/
  `narration_emotion` with an **app-level narrator** voice (new app setting); write
  `media/<item>.wav`, set the item's `audio = {path, duration_ms, voice_preset_id}`. Never
  synthesize user-authored text. Gate on `requires_capability("voice")`; on 503/missing, skip
  audio and leave text.
- Reveal schedule: per-item typing duration from text length (+ clip duration when audio exists) +
  jitter; store the schedule in the trace. Frontend plays the reveal cadence + audio after reveal.

**Done when** (mix of automated + manual): with voice enabled and a stubbed synth, a model turn
sets `audio` on `dialogue`/`narration` items and writes `media/*.wav`; with voice disabled or the
`voice` capability removed, the same turn returns text-only with `audio: null` and no media files;
manual: a real model turn plays a believable typing→reveal→audio cadence.

**Touches:** generator (additive voice stage), `conversation.json` config flags (already present),
new app-level narrator-voice setting.

---

## SP7 — Hardening + docs

**Goal:** edge cases covered, one full integration test, docs finalized. Depends on all prior.

**Read:** all prior sub-phases' tests; `design.md` §"Risks / open questions".

**Build:** edge cases — empty-transcript first turn, oversized windows, guard stripping leaked
meta, concurrent-write re-read; one integration test driving create→commit→model-turn→
induced-error→retry against the default LLM and asserting on-disk transcript shape; finalize
`docs/apps/prattletale/index.md`, fold the Prattletale entry into `docs/apps/index.md` +
`docs/index.md`, and add the CLAUDE.md "Apps" table row.

**Done when** `tests/apps/test_prattletale_integration.py` passes end-to-end and the docs build.

**Touches:** docs + `CLAUDE.md`; additive tests.

---

## Dependency graph

```
SP1 (store) ─┐
             ├─> SP3 (generator) ─> SP4 (router) ─> SP5 (frontend) ─> SP6 (voice) ─> SP7 (harden)
SP2 (prompts)┘
```

SP1 and SP2 are independent and may be built in either order / in parallel.

## Verification (Phase 1 end-to-end, manual)

`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`, then in the UI: create a conversation
against an existing Hoodat character → send a multi-item user turn → confirm typing indicator then
a model bubble stack → force an error → confirm the error bubble + working Retry → reload and
confirm the transcript restores from `config/prattletale/conversations/<id>/transcript.json`. After
SP6: confirm `media/*.wav` + a realistic reveal cadence, and that voice-off / removed `voice`
capability degrade to text.
