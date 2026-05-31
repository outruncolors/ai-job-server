# Prattletale Phase 3 — Plugins (Summarizer) Build Plan

> Execution sequencing for a **plugin system** for Prattletale, with **Summarizer** as the first
> plugin. Designed for **one sub-phase per session** to keep context small. Each sub-phase lists what
> to read, what to build, and how to know it's done. Sub-phases are dependency-ordered; each is a
> clean candidate for one ticket.
>
> **Per-session rule of thumb:** read [`design.md`](./design.md) + this doc's **Design** section +
> the sub-phase + the files the sub-phase names + the *committed* code of prerequisite sub-phases.

Environment reminders (from CLAUDE.md): `.venv/bin/python` (3.13), `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>`. Stores write under `config/`
(gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` constants to `tmp_path`. **No new
pip/npm dependencies.** Generation (including summarization) runs the chain executor **directly**
(no new generation path). Commit to `master` after the work is reviewed.

**Scope:** a pragmatic hook-based plugin system — *enough hooks for Summarizer, plus the obvious
ones, designed to grow.* SP1 is the backend foundation (registry/loader/manifest/action dispatch +
per-conversation enable). SP2 is the summary item type + the map-reduce summarization engine. SP3 is
the Summarizer plugin wiring its action. SP4 is the **frontend** plugin loader + hook API + a
per-conversation enable toggle. SP5 is the Summarizer frontend (the slide-up composer panel + the
summary bubble). SP6 hardens + documents. A full **Rescan / plugin-manager UI** and additional
plugins are deferred — SP1's `GET /plugins` listing + SP4's enable toggle are the seam they'll hang
off.

**What Phase 1/2 already shipped that Phase 3 builds on** (do not re-build):
- `Item.hidden_from_context` is honored by `generator._flatten_transcript` and toggled by
  `store.set_item_hidden` — **Purge** reuses it verbatim (hide the covered items; the summary carries
  the context forward).
- The broadened `PATCH /conversations/{id}` deep-merges a nested `config` patch — per-conversation
  plugin enablement rides in `config` with no new endpoint.
- Generation runs `execute_chain_job` **directly** with an on-disk job (`generator.run_model_turn`
  is the precedent); the summarization engine scaffolds jobs the same way and reads `final_output.txt`.
- Prompt Pal is the editable home for internal prompts (`register("prattletale", key, …)` +
  `service.get_text`); the Summarizer's map/reduce/detail prompts live there.
- The composer already cycles `MODES` (dialogue/action/narration) and renders a per-mode panel; SP5
  adds a plugin-contributed mode + a richer panel with the slide-up animation.

---

## Design

### The plugin model

A **plugin** is a backend Python package under `app/apps/prattletale/plugins/<id>/` that registers
itself at import (mirroring `app/apps/blaboratory/actions/registry`), plus optional **frontend
assets** under `static/apps/prattletale/plugins/<id>/`. A plugin declares a **manifest** and zero or
more **actions**:

```python
# app/apps/prattletale/plugins/base.py
@dataclass
class Plugin:
    id: str                       # kebab id, e.g. "summarizer"
    name: str                     # display name
    description: str
    version: str = "1"
    frontend: list[str] = ()      # JS/CSS served from the plugin's static dir, loaded when enabled
    actions: dict[str, Callable]  # action name -> async run(conversation_id, params) -> dict
    default_enabled: bool = False # whether new/legacy conversations get it on
    seed_prompts: Callable | None # optional: register Prompt Pal entries at load
```

The **registry** (`plugins/registry.py`) holds `PLUGIN_REGISTRY`, `register(plugin)`,
`get_plugin(id)`, `list_plugins()`. A **loader** imports each plugin package once at lifespan
(`seed_plugins()` in `app/main.py`, beside `seed_registered()` for Prompt Pal) and calls each
plugin's `seed_prompts`.

### Hook surface (enough for Summarizer + the obvious ones)

**Backend — actions.** A plugin's only backend extension point is a named **action**: an async
callable the frontend invokes through one generic endpoint
`POST /conversations/{id}/plugins/{plugin_id}/actions/{action}` with a free-form params body. The
action does its work (its own LLM runs, store writes) and returns a result dict the frontend renders.
This one hook covers "do a custom thing when the user submits in a plugin mode" without the core
knowing what the plugin does. (Obvious future hooks — a `before_turn`/`after_turn` context filter, a
`render_context` contributor — are **not** built now but the registry leaves room: a plugin could
declare more callables later and the executor/`build_context` would consult them.)

**Frontend — a small `window.PtPlugins` API.** The page loads each enabled plugin's JS, which calls
`PtPlugins.register({...})` to contribute:
- `composerModes: [{type, label}]` — extra composer modes merged after Say/Do/Narrate.
- `renderPanel(container, ctx)` — when a plugin mode is active, the core slides the composer panel
  open and hands the plugin a container to render its form into. `ctx` = `{conversation, api,
  invokeAction, onResult, close}`.
- `bubble: {types: [...], render(item, turn) -> html}` — how to render plugin item types (the
  `summary` bubble).
These are the **obvious** UI hooks; the core consults the bubble-renderer map in `bubbleHtml` and the
mode list in the composer. Nothing plugin-specific is hard-coded in the core.

**Per-conversation enablement.** `ConversationConfig` gains `enabled_plugins: list[str]`. A plugin's
mode/panel only appears when its id is in that list. New conversations start with each plugin whose
`default_enabled` is true (Summarizer ships `default_enabled=True` so it's discoverable as the lone
first plugin). Toggled in the config dialog's new **Plugins** section (SP4), persisted through the
existing nested-`config` PATCH.

### Summarizer plugin spec

**Composer mode.** A 4th composer mode **📋 Summarize**. Selecting it makes the normal text input
give way to an **inline summarizer form** that **slides up** out of the composer (smooth, with a
bounce overshoot); switching back to any text mode slides it down. The form has:
- a **Keep / Purge** radio — *Keep* = the summary is posted and added to context but the originals
  stay in context (informational recap); *Purge* = the covered originals are marked
  `hidden_from_context` (still visible in the thread, styled "summarized") and the summary carries
  that history forward (context compression).
- a **detail level** choice — three options **Brief / Standard / Detailed**.
- a **focus** textarea — optional free-text describing what to emphasize. The detail-level directive
  is applied first (top of the template); the focus instructions are appended **at the end**.
- a **Summarize** button (replaces Send while in this mode).

**Engine — hierarchical map-reduce** (`plugins/summarizer/summarize.py`):
1. Collect the **covered** items: every transcript item currently visible in context
   (not `hidden_from_context`, not `system_error`) — naturally includes a prior `summary` and excludes
   already-purged originals, so re-summarizing folds the prior summary + new messages.
2. **Chunk** the covered turns into slices of `chunk_turns` (configurable, default ~6).
3. **Map:** summarize each chunk via `execute_chain_job` using the `summarize.map` Prompt Pal entry
   (`{{var.detail}}` = the chosen level's directive, `{{var.transcript}}` = the chunk, `{{var.focus}}`
   appended) → one partial summary per chunk.
4. **Reduce:** if more than one partial remains, group them (fan-in `reduce_fanin`, default ~4) and
   summarize each group via `summarize.reduce` (`{{var.partials}}` + same detail/focus); repeat until
   a single summary remains.
5. Return the final summary text (+ the covered item ids, for Purge).

Each LLM call is one direct executor job (foreground, like a turn). Long histories = more calls;
acceptable for a manual, on-demand action. A 1-item / single-chunk history skips the reduce stage.

**Result & rendering.** The action appends a new turn with a single **`summary`** item
(`ItemType.summary`, a system-authored turn rendered as a centered, full-width "📋 Summary" card — no
avatar, no counterpart reply). On **Purge** it then `set_item_hidden(True)` on every covered id and
returns them so the frontend marks those bubbles muted in place. The summary item is **kept in
context** (it's the compressed history) and rendered distinctly in `_flatten_transcript`
(e.g. `[Summary so far] …`).

### Prompt Pal entries (editable)

`plugins/summarizer/prompts.py` registers: `summarize.map`, `summarize.reduce`, and the three detail
directives `summarize.level.brief` / `.standard` / `.detailed` (kept as entries so they're tunable in
the Prompt Pal UI). The engine composes the chosen level entry into `{{var.detail}}`.

### Decisions / non-goals

- **Author of a summary turn:** add `Author.system` (avatar-less, centered render). Touches
  `_speaker_label`/`turnHtml` minimally; the reveal/optimistic paths don't apply (a summary posts
  directly, it isn't streamed message-by-message).
- **No model reply** follows a Summarize — the action posts exactly one summary turn.
- **Deferred:** a Rescan/plugin-manager page, plugin upload/install, sandboxing, more hook types,
  and any second plugin. The registry + `GET /plugins` + the enable toggle are the seam.

---

## SP1 — Plugin backend foundation (registry + manifest + action dispatch + enable)

**Goal:** a backend plugin registry, a loader wired into lifespan, a `GET /plugins` manifest listing,
a generic plugin-action dispatch endpoint, and per-conversation `enabled_plugins` — all exercised by
a **test-only fake plugin** (no Summarizer yet).

**Read:** this doc's Design; `app/apps/blaboratory/actions/registry.py` (the register-at-import
pattern); `app/prompt_pal/registry.py` (`seed_registered` + `_PROMPT_MODULES` import-then-seed);
`app/main.py` lifespan (where `seed_registered()` is called); committed
`app/apps/prattletale/{models.py,router.py}` (`ConversationConfig`, the broadened `PATCH`, 404
patterns).

**Build (additive):**
- `app/apps/prattletale/plugins/base.py` — the `Plugin` dataclass + `manifest()` (the JSON-safe
  subset: id/name/description/version/frontend/actions-keys/default_enabled).
- `plugins/registry.py` — `PLUGIN_REGISTRY`, `register`, `get_plugin`, `list_plugins`,
  `seed_plugins()` (imports plugin packages, calls each `seed_prompts`). Import the package list
  explicitly (like `_PROMPT_MODULES`).
- `models.py` — `ConversationConfig.enabled_plugins: list[str] = []`. Add `enabled_plugins` to the
  router's `ConfigPatch` so it flows through the nested-`config` PATCH.
- `router.py` — `GET /plugins` → `{plugins: [manifest…]}`; `POST
  /conversations/{id}/plugins/{plugin_id}/actions/{action}` → 404 (conversation/plugin/action
  missing), 409 when the plugin isn't in the conversation's `enabled_plugins`, else `await
  action.run(conversation_id, params)` and return its dict.
- Lifespan: call `seed_plugins()` beside `seed_registered()`.
- A **test-only** plugin registered inside the test (or a tiny `tests` fixture plugin) to drive
  dispatch without depending on SP3.

**Done when** `tests/apps/test_prattletale_plugins.py` passes: `GET /plugins` lists the registered
manifests; an action dispatches and returns its dict; dispatch 404s on unknown plugin/action and on a
missing conversation; 409s when the plugin isn't enabled for the conversation; `enabled_plugins`
round-trips through the broadened PATCH. Full suite green.

**Touches:** new `plugins/` package, `models.py` (+1 field), `router.py` (+2 routes, +1 ConfigPatch
field), `app/main.py` (lifespan). **No frontend.**

---

## SP2 — Summary item type + map-reduce summarization engine (backend)

**Goal:** an `ItemType.summary` (+ `Author.system`) that the store can post and `build_context`
renders sensibly, and a pure-ish hierarchical summarization engine that reduces a transcript to one
summary via the chain executor — **no plugin wiring yet**.

**Read:** Design (engine); committed `models.py` (`ItemType`/`Author`/`Item`/`Turn`); `store.py`
(`_append_turn`/`_build_items`, the re-read-before-write pattern); `generator.py`
(`_render_item`/`_speaker_label`/`_flatten_transcript`, and `run_model_turn` as the
direct-executor + `create_job`/`find_job_dir`/`final_output.txt` precedent); `app/prompt_pal/service.py`.

**Build (additive):**
- `models.py` — `ItemType.summary`; `Author.system`. Keep enums append-only.
- `store.py` — `append_summary_turn(conversation_id, text) -> dict` (a system-authored turn with one
  `summary` item). Generalize `_append_turn`/`_build_items` if needed (they already take `author`).
- `generator.py` — `_speaker_label` returns "Summary" for `system`; `_render_item` renders a summary
  item as its plain text; `_flatten_transcript` emits a summary turn as `[Summary so far] …` (and a
  `system`/`summary` turn is **not** skipped). Confirm the recent-window slice still behaves.
- `plugins/summarizer/summarize.py` — `async summarize_history(conversation, character, transcript,
  *, level, focus, chunk_turns=6, reduce_fanin=4, llm=None) -> str`: gather covered items → chunk →
  map (per chunk, one `execute_chain_job` over `summarize.map`) → reduce (hierarchical until one) →
  return text. Compose `{{var.detail}}` from the `summarize.level.<level>` entry, append
  `{{var.focus}}`. Best-effort job scaffolding like `run_model_turn`.
- `plugins/summarizer/prompts.py` — register `summarize.map`, `summarize.reduce`,
  `summarize.level.{brief,standard,detailed}`.

**Done when** `tests/apps/test_prattletale_summarize.py` passes (stubbed executor that returns a
deterministic summary per chunk): a long transcript reduces to one string; chunking + a multi-round
reduce fire the expected number of executor calls; a single-chunk history skips reduce; the chosen
detail level + focus reach the rendered prompt; `build_context` renders a `summary`/`system` turn as
`[Summary so far] …` and never drops it. Full suite green.

**Touches:** `models.py` (+2 enum members), `store.py` (+1 op), `generator.py` (render helpers),
new `plugins/summarizer/{summarize,prompts}.py`. **No frontend. No dep on SP1 — parallel-able.**

---

## SP3 — Summarizer plugin + action (backend)

**Goal:** register the Summarizer plugin and its `summarize` action, wiring SP2's engine into SP1's
dispatch: validate params, run the engine, post the summary turn, and on **Purge** hide the covered
items — returning what the frontend needs to render.

**Read:** Design (Summarizer spec); SP1's committed registry/dispatch + `Plugin` model; SP2's
committed engine + `append_summary_turn` + `set_item_hidden`; `store.py`.

**Build (additive) — `plugins/summarizer/plugin.py`:**
- A `Plugin(id="summarizer", name="Summarizer", default_enabled=True, frontend=[…],
  seed_prompts=…, actions={"summarize": run_summarize})`.
- `async run_summarize(conversation_id, params)` — validate `{mode: "keep"|"purge", detail:
  "brief"|"standard"|"detailed", focus: str}` (422-able error on bad values); load conversation +
  character + transcript; compute covered ids (visible-in-context, non-summary-of-this-run); call
  `summarize_history`; `append_summary_turn`; if `mode == "purge"`, `set_item_hidden(True)` on each
  covered id; return `{summary_turn, hidden_item_ids, mode}`. Any failure → a clear error dict /
  exception the dispatch maps to a 4xx/5xx (do **not** post a `system_error` chat turn for a failed
  summarize — surface it inline in the panel instead).
- `register()` the plugin at import; add the package to the loader's import list.

**Done when** `tests/apps/test_prattletale_summarizer_action.py` passes (stubbed executor): dispatch
`summarize` on a seeded transcript posts exactly one `summary` turn and no model reply; **Keep**
leaves all originals visible-in-context; **Purge** hides every covered original (assert the next
`build_context` transcript shows only `[Summary so far] …`, not the originals) while they remain in
the stored transcript; bad params 4xx; the plugin appears in `GET /plugins` with
`default_enabled=true`. Full suite green.

**Touches:** new `plugins/summarizer/plugin.py`, loader import list. **No frontend. Depends on
SP1 + SP2.**

---

## SP4 — Frontend plugin loader + hook API + enable toggle

**Goal:** the page loads enabled plugins' frontend assets, exposes the `window.PtPlugins` registration
API, consults plugin contributions (composer modes + bubble renderers), and lets the operator enable/
disable plugins per conversation from the config dialog.

**Read:** Design (frontend hooks); committed `static/apps/prattletale/{index.html,prattletale.js}`
(`MODES`, `renderMode`/`cycleMode`, `bubbleHtml`, `openConfig`/`saveConfig`, script load order);
`docs/reference/ui-standards.md`; SP1's `GET /plugins` + `enabled_plugins`.

**Build (additive) — `static/apps/prattletale/`:**
- `plugins.js` (loaded before `prattletale.js`) — defines `window.PtPlugins` with `register(spec)` +
  accessors (`composerModes()`, `bubbleRenderer(type)`, `panel(modeType)`). Idempotent.
- In `prattletale.js`: on chat load, `GET /plugins`, and for each plugin in the conversation's
  `config.enabled_plugins`, inject its `frontend` assets (`<script>`/`<link>` once per id). Merge
  `PtPlugins.composerModes()` (filtered to enabled plugins) into the composer mode list. In
  `bubbleHtml`, if a plugin registered a renderer for the item's type, use it (fallback to the core
  renderer).
- Config dialog: a **Plugins** section listing `GET /plugins` manifests with a checkbox each, bound
  to `config.enabled_plugins`, saved through the existing nested-`config` PATCH.
- Escape all text; reuse `api()`.

**Done when** (manual, server running): `GET /plugins` shows Summarizer; the config dialog's Plugins
section toggles it for the conversation and persists on reload; with it enabled the composer offers a
4th mode (the panel/animation land in SP5); a `summary` bubble (hand-inserted or from SP3) renders via
the plugin renderer. Run the suite to confirm no regression. **Pure frontend. Depends on SP1.**

**Touches:** `static/apps/prattletale/{index.html,plugins.js,prattletale.js,styles.css}`.

---

## SP5 — Summarizer frontend: slide-up panel + summary bubble

**Goal:** the Summarizer plugin's frontend — the **📋 Summarize** mode with the slide-up/bounce
composer panel (Keep/Purge, detail level, focus, Summarize button), invoking SP3's action and
rendering the returned summary bubble (+ applying Purge in place). Depends on **SP3 + SP4**.

**Read:** Design (Summarizer spec + panel); SP4's committed `PtPlugins` API + the composer-mode merge
+ bubble-renderer hook; committed `prattletale.js` (`resetComposer`/`renderMode`, the `send` path,
`rerenderTurn`/in-place update helpers, `appendTurn`, `_escHtml`); `styles.css` (composer layout).

**Build (additive) — `static/apps/prattletale/plugins/summarizer/`:**
- `summarizer.js` — `PtPlugins.register({ id:'summarizer', composerModes:[{type:'summarize',
  label:'📋 Summarize'}], renderPanel(container, ctx), bubble:{types:['summary'], render} })`.
  - `renderPanel` builds the form (Keep/Purge radio, Brief/Standard/Detailed, focus textarea,
    Summarize button); on submit calls `ctx.invokeAction('summarize', {mode, detail, focus})`,
    disables while running, then `ctx.onResult(res)` (append the summary turn; on `purge` mark each
    `hidden_item_ids` bubble muted in place via the existing hide styling) and `ctx.close()` (return
    to a text mode). Errors render inline in the panel (no chat error bubble).
  - `bubble.render` → the centered "📋 Summary" card markup.
- `summarizer.css` — the summary card + form styling.
- Core animation (in `prattletale.js`/`styles.css` under SP4's hooks): entering a mode that has a
  panel **slides the composer panel up** to reveal it; leaving slides it down. Use a CSS transition
  with a bounce/overshoot easing (e.g. `cubic-bezier(0.34, 1.56, 0.64, 1)`) on height/transform; the
  panel content fades/translates in. Respect `prefers-reduced-motion` (instant when set).

**Done when** (manual, server running, Summarizer enabled): switching to 📋 Summarize slides the
panel up with a bounce and shows the form; submitting posts one **📋 Summary** bubble and no reply;
**Purge** greys the covered bubbles and the next model turn's trace `context_input.transcript` shows
`[Summary so far] …` instead of the originals; **Keep** leaves them; switching back to Say slides the
panel down. Run the suite to confirm no regression. **Pure frontend. Depends on SP3 + SP4.**

**Touches:** new `static/apps/prattletale/plugins/summarizer/*`; small core hooks in
`prattletale.js`/`styles.css`.

---

## SP6 — Hardening + docs

**Goal:** edge cases covered, one integration test across the new surface, docs updated. Depends on
all prior.

**Read:** all prior sub-phases' tests; `design.md`; `docs/apps/prattletale/index.md`;
`docs/apps/index.md`; CLAUDE.md "Apps" Prattletale rows.

**Build:**
- Edge cases + tests:
  - summarize an **empty / single-turn** history (no reduce; sensible output or a clean "nothing to
    summarize" path); a history that is **only** a prior summary + a couple of new turns (folds);
  - **Purge then unhide** one covered item (SP5 hide-toggle) restores it to context alongside the
    summary; re-summarizing after a purge covers the summary + new turns, not the purged originals;
  - a disabled plugin's mode/panel is absent and its action 409s;
  - bad action params 4xx; a mid-run executor failure surfaces inline (no chat `system_error` turn).
- One integration test (`tests/apps/test_prattletale_plugins_integration.py`): enable Summarizer →
  seed a multi-turn transcript → dispatch `summarize` (purge, standard, with focus) → assert one
  `summary` turn, the covered originals hidden, `build_context` shows `[Summary so far] …` → add a
  user+model turn → re-summarize → assert it folds the prior summary. Drive a faithful stubbed
  executor; assert on-disk transcript shapes.
- Docs: update `docs/apps/prattletale/index.md` (a "How it works (Phase 3 — plugins)" section + mark
  Phase 3 built), the Prattletale row in `docs/apps/index.md`, and the CLAUDE.md "Apps" Prattletale
  rows + a short plugins note (current-state only). Add the Phase 3 build-plan link to `index.md`.

**Done when** the integration test passes end-to-end, all prattletale tests pass, the full suite is
green, and the docs reference the plugin system + Summarizer.

**Touches:** docs + CLAUDE.md; additive tests.

---

## Store/model change vs. pure-frontend summary

| Sub-phase | Store/model change | Backend route | Pure frontend |
|-----------|--------------------|---------------|---------------|
| SP1 | `ConversationConfig.enabled_plugins` (+1 field) | `GET /plugins`, action dispatch | — |
| SP2 | `ItemType.summary` + `Author.system`; `append_summary_turn` | — | — |
| SP3 | — (uses SP2 ops) | wires the `summarize` action into dispatch | — |
| SP4 | — | — | plugin loader + hook API + enable toggle |
| SP5 | — | — | summarizer panel (slide-up/bounce) + summary bubble |
| SP6 | — | — | docs + tests |

## Dependency graph

```
SP1 (plugin backend) ─┬─────────────> SP3 (summarizer action) ─┐
SP2 (summary + engine)┘                                         ├─> SP5 (summarizer UI) ─> SP6
SP1 (plugin backend) ───────────────> SP4 (frontend loader) ───┘
```

SP1 and SP2 are independent backend additions (build in any order). SP3 needs both. SP4 needs SP1.
SP5 needs SP3 + SP4. SP6 needs everything.

## Verification (Phase 3 end-to-end, manual)

`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090`, then in the UI:
1. Open a conversation → config dialog → **Plugins** → confirm **Summarizer** is enabled (it ships
   default-on); reload and confirm persistence.
2. Build up some history, then switch the composer to **📋 Summarize** → the panel **slides up** with
   a bounce. Pick **Detailed**, **Purge**, type a focus note → **Summarize**.
3. Confirm a single **📋 Summary** card posts (no counterpart reply), the covered bubbles grey out,
   and a subsequent model turn's **trace** shows `[Summary so far] …` in `context_input.transcript`
   in place of the purged originals.
4. Repeat with **Keep** and confirm the originals stay in context; switch back to **Say** and confirm
   the panel slides down.
