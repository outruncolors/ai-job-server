# Prattletale Phase 2 — Config & dev tools Build Plan

> Execution sequencing for **per-conversation configuration** and **developer/inspection tools** on
> top of the Phase 1 text+voice loop. Designed for **one sub-phase per session** to keep context
> small. Each sub-phase lists what to read, what to build, and how to know it's done. Sub-phases are
> dependency-ordered; each is a clean candidate for one ticket.
>
> **Per-session rule of thumb:** read [`design.md`](./design.md) + this sub-phase + the files the
> sub-phase names + the *committed* code of prerequisite sub-phases. You should not need earlier
> sub-phases' reasoning. Copy-paste session-starters: [`phase2-prompts/`](./phase2-prompts/README.md).

Environment reminders (from CLAUDE.md): `.venv/bin/python` (3.13), `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>`. Stores write under `config/`
(gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` constants to `tmp_path`. **No new
pip dependencies.** Generation still runs the chain executor **directly** (Phase 2 adds no new
generation paths). **Don't commit until reviewed.**

**Scope:** SP1–SP3 are thin **backend** additions (transcript editing, conversation settings, trace
read) and are mutually independent. SP4–SP6 are their **frontend** consumers (config view,
per-message action wrapper, the dev-tools trace viewer + pipeline node-graph). SP7 hardens +
documents. Plugins, Model×Model, autonomous ticks, and group chat remain Phase 3/4.

**What Phase 1 already shipped that Phase 2 builds on** (do not re-build):
- `Item.hidden_from_context` is **honored** by `generator.build_context` (`_flatten_transcript`
  skips it) but no endpoint ever sets it — SP1/SP5 surface it.
- `store.replace_turn` / `store.apply_audio` already edit a turn **in place**; SP1 adds the
  finer-grained item edits beside them, reusing the same re-read-before-write discipline.
- `conversation.config` already carries `context_window_turns` (read by `build_context`) plus the
  `voice_enabled` / `typing_timing_enabled` / `variety_pass_enabled` toggles — SP2/SP4 make them all
  editable after creation (today only the three booleans are toggleable, via `PATCH
  /conversations/{id}`, and only `title`/`scenario`/… are set at create time).
- `store.write_trace` writes `traces/<turn>.json` = `{job_id, context_input, raw_final_output,
  parsed_items, reveal_schedule, voice_error, error}` for **every** model turn (success and error),
  but **no endpoint reads it back** — SP3 exposes it and SP6 renders it.
- `static/js/field-controls.js` (`FieldControls.attach`) is the hover-control affordance Hoodat uses
  for ✨/✏️ on every field — SP5 reuses it verbatim for per-message edit/hide/delete.

---

## SP1 — Transcript editing API (edit / hide / delete)

**Goal:** a single item's text can be edited, an item can be hidden-from-context (toggled), an item
can be deleted, and a whole turn can be deleted — all in place on disk, with no LLM and no frontend.
Surfaces the already-honored `hidden_from_context`.

**Read:** `design.md` §"Terminology & data model" (item shape, `hidden_from_context`, item-id
format); committed `app/apps/prattletale/store.py` (`replace_turn`, `apply_audio`, `_read_transcript`,
the re-read-before-write pattern, `_touch_conversation`); `app/apps/prattletale/generator.py`
`_flatten_transcript` (so you can see exactly what `hidden_from_context` / empty turns do to
context); `app/apps/prattletale/router.py` (404 patterns, the per-item audio route's
turn/item lookup).

**Build (additive):**
- `store.py` ops (mirror `replace_turn`'s re-read-then-write):
  - `edit_item(conversation_id, turn_id, item_id, text) -> dict | None` — overwrite one item's
    `text` in place (ids/type/audio unchanged); returns the updated turn or None.
  - `set_item_hidden(conversation_id, turn_id, item_id, hidden: bool) -> dict | None` — set
    `hidden_from_context`.
  - `delete_item(conversation_id, turn_id, item_id) -> dict | None` — drop one item from a turn;
    if the turn is left with **zero** items, drop the whole turn (return `{"turn_deleted": turn_id}`
    or similar sentinel — decide and document the shape).
  - `delete_turn(conversation_id, turn_id) -> bool` — remove a whole turn.
  - Do **not** renumber surviving turns/items (`next_turn_seq` stays monotonic; ids are stable —
    deep-links and traces keep pointing at the right thing).
- `router.py` endpoints (all 404 on missing conversation/turn/item):
  - `PATCH /conversations/{id}/turns/{turn_id}/items/{item_id}` — body `{text?: str,
    hidden_from_context?: bool}`; applies whichever fields are set; returns the updated turn.
  - `DELETE /conversations/{id}/turns/{turn_id}/items/{item_id}` — returns the updated turn (or a
    turn-deleted signal when it was the last item).
  - `DELETE /conversations/{id}/turns/{turn_id}` — 204.

**Done when** `tests/apps/test_prattletale_edit.py` passes (monkeypatch `CONVERSATIONS_DIR`):
edit changes only `text` and round-trips via `get_transcript`; toggling `hidden_from_context` on an
item makes `generator.build_context` exclude it from the rendered `transcript` (assert on the
flattened string); deleting the only item in a turn removes the turn; deleting a turn removes it and
leaves the others' ids unchanged; every op 404s on a missing id. Full suite still green (touched
`router.py`).

**Touches:** `store.py` (new ops), `router.py` (new endpoints). Additive. **No model change** —
`Item` already has `text`/`hidden_from_context`. **No dep on SP2/SP3 — parallel-able.**

---

## SP2 — Conversation settings API (editable metadata + behaviour)

**Goal:** after creation, a conversation's metadata (`title`, `scenario`, `role_instructions`,
`device_user`) and **behaviour config** (`context_window_turns` + the existing voice/timing/variety
toggles) can be edited through one endpoint. No frontend.

**Read:** `design.md` §"`conversation.json`" + §"Risks/open questions" (#3 context-window unit);
committed `store.py` `update_conversation` (shallow-merge → `Conversation(**current)` → atomic write
— it **already** persists any of these fields); `router.py` `ConversationCreate` / `ConfigPatch` /
`update_conversation_config` (today's config-toggle-only `PATCH`); `app/apps/prattletale/models.py`
(`Conversation`, `DeviceUser`, `ConversationConfig`).

**Build (additive):** broaden the conversation `PATCH` so it accepts editable metadata **and** a
nested `config` patch, while keeping today's header toggles working.
- Recommended shape: `PATCH /conversations/{id}` with a `ConversationUpdate` body — all-optional
  `title`, `scenario`, `role_instructions`, `device_user` (a `DeviceUser`), and `config` (a partial
  `ConversationConfig`, **including `context_window_turns`**). Apply via the existing
  `store.update_conversation` (shallow-merge top-level; deep-merge the `config` sub-dict so unset
  config keys are preserved). Validate `context_window_turns` ≥ 1 (422 otherwise).
- **Back-compat:** the Phase-1 frontend `toggleConfig()` sends flat `{voice_enabled: …}` to this
  `PATCH`. Either keep accepting flat config keys (hoist them into `config`) **or** migrate the three
  toggle calls to the nested form in this sub-phase — pick one and note it so the running app stays
  green between SP2 and SP4. (Recommended: hoist flat config keys for now; SP4 switches the UI to the
  nested form and to the new metadata fields.)

**Done when** `tests/apps/test_prattletale_conversation_settings.py` passes: patching `scenario` /
`role_instructions` / `device_user.persona` persists and round-trips via `get_conversation` and
bumps `updated_at`; patching `config.context_window_turns` changes the window `build_context` slices
(assert the rendered transcript honors the new window) **without** clearing the voice/variety flags;
a `context_window_turns` of 0/negative 422s; an unchanged toggle still flips via the same endpoint;
missing conversation 404s. Full suite still green.

**Touches:** `router.py` (broaden the update endpoint + request model). `store.update_conversation`
likely unchanged (confirm deep-merge of `config`; add it if the shallow merge would drop sibling
config keys). Additive. **No model change.** **No dep on SP1/SP3 — parallel-able.**

---

## SP3 — Trace + pipeline read API (dev-tools backend)

**Goal:** the per-turn debug trace is readable over HTTP, and (recommended) enriched with the
ordered pipeline steps + their per-step output, so SP6's trace viewer and node-graph render from the
trace alone (keeping the conversation folder self-describing/portable). No frontend.

**Read:** `design.md` §"Turn-generation pipeline" (the `turn → (variety) → guard` chain) + §"Risks"
#6 (trace size); committed `generator.py` (`build_turn_request` builds the ordered `steps`;
`run_model_turn` writes the trace via `store.write_trace`); `store.py` (`_trace_path`, `write_trace`);
`app/chain/executor.py` (per-step `steps/NNN_<id>/` dirs + their output files, and `final_output.txt`
— so you know where intermediate step outputs land on disk).

**Build (additive):**
- `store.py`: `get_trace(conversation_id, turn_id) -> dict | None` (read `traces/<turn>.json`);
  optional `list_traces(conversation_id) -> list[str]` (turn ids that have a trace).
- `router.py`: `GET /conversations/{id}/turns/{turn_id}/trace` → the trace dict (404 when absent).
- **Trace enrichment (recommended, additive to the trace dict — it's a free-form dict, not a Pydantic
  model, so no model migration):** in `generator.run_model_turn`, after `execute_chain_job`, capture
  an ordered `steps` list — `[{number, id, name, prompt, output}]` — by pairing the request steps
  built in `build_turn_request` with the outputs the executor wrote under `steps/NNN_<id>/` (read the
  step output files; `final_output.txt` is the last step). Add `steps` to the trace alongside the
  existing keys. This is what lets the node-graph show the **actual** draft → variety → guard
  transformation for a turn, not just the static shape. Keep it best-effort: a step whose output
  can't be read records `output: null` rather than failing the turn.
  - Scope guard: if reading step dirs proves fiddly, the **minimum** acceptable enrichment is the
    ordered step identities + their rendered prompts (no per-step output); the node-graph then shows
    structure + prompts and the trace viewer still shows `raw_final_output`. Note the limitation.

**Done when** `tests/apps/test_prattletale_trace.py` passes: after a (stubbed-executor) model turn,
`GET …/trace` returns the trace with `job_id`/`context_input`/`raw_final_output`/`parsed_items`; the
enriched `steps` list is ordered `turn`(→`variety`)→`guard` and matches the steps
`build_turn_request` produced for that conversation's config (variety on vs off changes the step
count); `GET …/trace` 404s for a turn with no trace and for a missing conversation. Full suite still
green.

**Touches:** `store.py` (read helpers), `router.py` (one GET), `generator.py` (trace enrichment).
Additive. **No dep on SP1/SP2 — parallel-able.**

---

## SP4 — Conversation config view (frontend)

**Goal:** from the chat, open a per-conversation **config view** that edits device-user (display
name + persona), scenario, role instructions, title, and the behaviour knobs (context-window slider
+ voice/timing/variety) — saved through SP2's endpoint. Depends on **SP2**.

**Read:** `design.md` §"Mission"/"`conversation.json`"; committed `static/apps/prattletale/`
(`index.html` view structure — `#pt-list-view` / `#pt-chat-view` toggled by `?id=`; `prattletale.js`
`showView`/`renderToggles`/`toggleConfig`/`openSettings`; `styles.css`); `docs/reference/ui-standards.md`
+ `ui-cheatsheet.md`; SP2's committed endpoint.

**Build (additive) — `static/apps/prattletale/`:**
- A **config view** for the open conversation. Match the existing single-page pattern: either a
  third view toggled by a query param (e.g. `?id=<id>&view=config`, so reload/back works like the
  list↔chat toggle) **or** a full-height dialog reached from a ⚙ control in the chat header — pick
  one and keep it consistent with the list↔chat routing. (The list-view ⚙ stays app-level: narrator
  voice.)
- Fields: title, scenario, role instructions, your display name, your persona, and a
  **context-window** control (number/slider, min 1) + the voice/timing/variety toggles (move or
  mirror the header toggles here). Save → SP2 `PATCH`; reflect the saved config back into the
  in-memory `_current.conversation` and re-render the header.
- Migrate the header toggle calls to whatever shape SP2 settled on (nested `config` vs flat).
- Escape all text before `innerHTML` (`_escHtml`); reuse `api()`.

**Done when** (manual, server running): open a conversation → config view; change scenario + persona
+ context window + a toggle → save → reload → the changes persisted (and the next model turn's trace
shows the new context window / persona in `context_input`). No new automated assertions beyond SP2's
API tests; run the suite to confirm nothing regressed.

**Touches:** `static/apps/prattletale/*` (additive view + wiring). **Pure frontend.** Depends on SP2.

---

## SP5 — Per-message action wrapper (frontend)

**Goal:** each model/user bubble gains a hover affordance to **edit** its text, **hide/show** it
from context, and **delete** it; a turn can be deleted. Reuses `FieldControls`. Depends on **SP1**.

**Read:** `design.md` §"data model" (item types, `hidden_from_context`); `static/js/field-controls.js`
+ `static/css/field-controls.css` (the `FieldControls.attach(slot, {controls, context})` contract);
`static/apps/hoodat/profile.js` (a real `FieldControls.attach` call site); committed
`static/apps/prattletale/prattletale.js` (`bubbleHtml`/`turnHtml`/`renderThread`, the existing
`wirePlay`/`wireRetry` per-bubble wiring, `mediaUrl`); SP1's committed endpoints.

**Build (additive) — `static/apps/prattletale/`:**
- Wrap each rendered bubble with `FieldControls` (or an equivalent hover cluster consistent with the
  app's styling) exposing: ✏️ **edit** (inline textarea → `PATCH …/items/{item_id}` with `{text}`),
  🚫 **hide / 👁 show** (toggle `hidden_from_context` via the same `PATCH`), and 🗑 **delete**
  (`DELETE …/items/{item_id}`; confirm). A turn-level 🗑 **delete turn** (`DELETE …/turns/{turn_id}`,
  confirm) — e.g. on the turn's avatar/stack hover.
- Render **hidden** items with a clear muted/strikethrough style and a "won't be sent to the model"
  affordance, so the context effect is visible. They still render in the thread (history), just
  styled as excluded.
- After each op, update the in-memory `_current.transcript` and re-render the affected turn in place
  (mirror the retry path's in-place DOM swap); an item-delete that empties a turn removes the turn.
- Don't break the existing 🔊 play button or Retry; the hover cluster sits alongside them. Edit/hide/
  delete do **not** re-run the model (no cascade) — that's intentional (regen is turn-level Retry).
- Escape all text; reuse `api()`.

**Done when** (manual, server running): hover a bubble → edit its text (persists on reload); hide a
model item → it renders muted and the **next** model turn's trace `context_input.transcript` omits
it; delete an item → it disappears (and an emptied turn collapses); delete a turn → it's gone on
reload. No new automated assertions beyond SP1's API tests; run the suite to confirm no regression.

**Touches:** `static/apps/prattletale/*` (bubble rendering + wiring), loads `field-controls.js`/
`field-controls.css` in `index.html`. **Pure frontend.** Depends on SP1.

---

## SP6 — Dev tools: trace viewer + pipeline node-graph (frontend)

**Goal:** a per-model-turn **trace viewer** (context input, raw output, parsed items, reveal
schedule, voice error) and a **node-graph** of that turn's `turn → (variety) → guard` pipeline, with
each node showing its prompt/output and deep-linking to its Prompt Pal entry. Depends on **SP3**.

**Read:** `design.md` §"Turn-generation pipeline" + §"The narrative editor is a guard" + §"Risks"
#6; SP3's committed `GET …/trace` + the enriched `steps`; committed `prattletale.js` (where model
turns render; how to add a per-turn affordance); the Prompt Pal deep-link convention
(`/prompt-pal/?app=prattletale&highlight=<id>` — see `app/prompt_pal/service.py::id_for` and how
Hoodat links to it); `docs/reference/ui-standards.md`.

**Build (additive) — `static/apps/prattletale/`:**
- A 🔍 **trace** affordance on each **model** turn (only when a trace exists) → a modal/panel that
  fetches `GET …/trace` and shows: the `context_input` variable bundle (character/scenario/
  role/persona/transcript), `raw_final_output`, the `parsed_items`, the `reveal_schedule`, and any
  `voice_error`/`error`.
- A **node-graph** of the pipeline for that turn, rendered from the trace's `steps`: ordered nodes
  `Turn → (Variety) → Guard` (Variety node omitted when the conversation had it off), each node
  labeled and clickable to reveal that step's **prompt** and **output** (from the enriched `steps`;
  fall back to "(output not captured)" if SP3 took the minimum path). Each node deep-links to its
  Prompt Pal entry (turn / variety / turn-guard) so the operator can edit the prompt and re-run.
  Plain CSS/flex/SVG boxes-and-arrows — **no new graph library** (no new pip/npm deps).
- Error turns: the trace viewer still opens (shows `error` + `raw_final_output`), so a failed turn is
  debuggable.
- Escape all text; reuse `api()`.

**Done when** (manual, server running): generate a model turn → open its trace → see the context
bundle + raw/parsed output + reveal schedule; the node-graph shows `Turn → Variety → Guard` (and only
`Turn → Guard` when variety is off), each node opens its prompt/output and the Prompt Pal link lands
on the right entry; opening the trace on a forced error turn shows the error. No new automated
assertions beyond SP3's API test; run the suite to confirm no regression.

**Touches:** `static/apps/prattletale/*` (trace modal + node-graph). **Pure frontend.** Depends on SP3.

---

## SP7 — Hardening + docs

**Goal:** edge cases covered, one integration test across the new surface, docs updated. Depends on
all prior.

**Read:** all prior sub-phases' tests; `design.md` §"Risks / open questions"; `docs/apps/prattletale/
index.md`; `docs/apps/index.md`; CLAUDE.md "Apps" Prattletale rows.

**Build:**
- Edge cases + tests:
  - edit/hide/delete on the **only** item of a turn, on a `system_error` turn, and on a turn that's
    mid-list (ids of other turns unchanged);
  - hidden-then-shown round-trip restores the item to context; a fully-hidden turn drops out of the
    flattened transcript with no dangling speaker label;
  - settings: `context_window_turns` larger than the turn count, and a 0/negative rejection;
  - concurrent edit + a posted turn (re-read-before-write keeps both);
  - trace read for a turn with no trace / a missing conversation.
- One integration test (`tests/apps/test_prattletale_config_devtools_integration.py`): create →
  commit a user + model turn → edit the user item → hide a model item and assert the next turn's
  trace `context_input` omits it → patch `context_window_turns` and assert the window changed →
  read the trace and assert the enriched `steps` shape → delete a turn. Drive the default LLM path or
  a faithful stub; assert on-disk transcript + trace shapes.
- Docs: update `docs/apps/prattletale/index.md` (mark Phase 2 built; add the config/dev-tools "how
  it works" bullets) and the Prattletale row in `docs/apps/index.md`; extend the CLAUDE.md "Apps"
  Prattletale rows for the new endpoints + the config/trace/node-graph UI (current-state only — no
  "previously/now" framing).

**Done when** `tests/apps/test_prattletale_config_devtools_integration.py` passes end-to-end, all
prattletale tests pass, the full suite is green, and the docs reference the new surface.

**Touches:** docs + CLAUDE.md; additive tests.

---

## Store/model change vs. pure-frontend summary

| Sub-phase | Store/model change | Backend route | Pure frontend |
|-----------|--------------------|---------------|---------------|
| SP1 | `store.py` ops only (no Pydantic model change — `Item` already has the fields) | edit/hide/delete endpoints | — |
| SP2 | possibly `update_conversation` deep-merge of `config` (no model change) | broaden the conversation `PATCH` | — |
| SP3 | trace dict gains a `steps` key (free dict, no model migration); `generator` reads step dirs | one `GET …/trace` | — |
| SP4 | — | — | config view |
| SP5 | — | — | per-message action wrapper (reuses `FieldControls`) |
| SP6 | — | — | trace viewer + node-graph |
| SP7 | — | — | docs + tests |

**Deferred to Phase 3+ (call-outs, not built here):** device-user **avatar upload** (Phase 1
`device_user.avatar_path` stays null — text/initials only); per-**item** regenerate (turn-level
Retry already covers regeneration); editing a message does **not** re-run downstream turns
(no cascade — intentional); changing the counterpart character of an existing conversation; the
token-budget context window (stays *turns* per design Risk #3). Plugins, Model×Model, autonomous
ticks, and group chat remain Phase 3/4 per `design.md` §"Scope by phase".

## Dependency graph

```
SP1 (edit API) ────────> SP5 (action wrapper) ─┐
SP2 (settings API) ─────> SP4 (config view) ───┼─> SP7 (harden + docs)
SP3 (trace API) ────────> SP6 (trace + graph) ─┘
```

SP1, SP2, SP3 are mutually independent backend additions — build in any order / in parallel. Each
frontend sub-phase depends only on its own backend (SP5→SP1, SP4→SP2, SP6→SP3); SP4/SP5/SP6 are
otherwise independent of each other. SP7 depends on everything.

## Verification (Phase 2 end-to-end, manual)

`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`, then in the UI on an existing
conversation:
1. Open the **config view** → change scenario, your persona, the context-window value, and a toggle
   → save → reload and confirm they persisted.
2. **Per-message**: hover a model bubble → edit its text (persists on reload); **hide** a model item
   (it renders muted) → send another turn → open that turn's **trace** and confirm the hidden item is
   absent from `context_input.transcript`; **delete** an item (an emptied turn collapses); delete a
   whole turn.
3. **Dev tools**: open a model turn's **trace** → confirm the context bundle, raw/parsed output, and
   reveal schedule; confirm the **node-graph** shows `Turn → Variety → Guard` (and `Turn → Guard`
   when variety is off for that conversation), each node opens its prompt/output, and the Prompt Pal
   link lands on the right entry; open the trace on a forced error turn and confirm the error shows.
</content>
</invoke>
