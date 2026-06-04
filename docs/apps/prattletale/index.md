# Prattletale

Prattletale is an **iMessage-style roleplay chat** between a human user and a
[Hoodat](../hoodat/index.md) character. You pick a counterpart character, set a scenario and
role instructions, and exchange turns. The model's replies arrive as a stack of typed bubbles —
**dialogue**, **action**, and **narration** — the way a real texting burst does.

Each conversation is a **self-contained folder** on disk (`config/prattletale/conversations/<id>/`)
holding its metadata, transcript, debug traces, and (later) generated audio. Prattletale depends
on Hoodat for every non-user character (sheet, avatar, voice); Hoodat stays app-agnostic.

- **[Design](design.md)** — the canonical "what & why": terminology, data model, the turn-generation
  pipeline, and what's deferred. **Every build session reads this first.**
- **[Phase 1 — Foundation build plan](phase1-foundation-build-plan.md)** — phased sequencing for
  the text-first conversation loop (model + store + UI + pipeline), then voice.
- **[Phase 1 session prompts](phase1-prompts/README.md)** — copy-paste session-starters, one per
  sub-phase, so each chat stays small and self-contained.
- **[Phase 2 — Config & dev-tools build plan](phase2-config-devtools-build-plan.md)** — per-conversation
  settings, message edit/hide/delete, a per-message action wrapper, a trace viewer, and a node-graph
  view of the `turn → variety → guard` pipeline.
- **[Phase 2 session prompts](phase2-prompts/README.md)** — copy-paste session-starters for the
  config / dev-tools sub-phases.
- **[Phase 3 — Plugins (Summarizer) build plan](phase3-plugins-build-plan.md)** — a hook-based plugin
  system (registry + manifest + action dispatch + per-conversation enable + frontend loader) with
  **Summarizer** as the first plugin: a 📋 Summarize composer mode with a slide-up panel
  (Keep/Purge · detail level · focus) that map-reduces the history into one summary bubble.

## Status

**Phase 1 (text-first conversation loop + voice), Phase 2 (config & dev tools), and Phase 3
(plugins — Summarizer) are built.** A human can create a conversation against a Hoodat character and
exchange typed-bubble turns; model dialogue/narration can be synthesized to audio with a per-item
reveal cadence (degrades to text when voice is off or the `voice` capability is absent). Phase 2
adds an in-chat **config view** (edit metadata + behaviour after creation), **per-message edit /
hide / delete** (and delete-turn), and a **dev-tools trace viewer + pipeline node-graph**. Phase 3
adds a **hook-based plugin system** with **Summarizer** as the first plugin (a 📋 Summarize composer
mode that map-reduces the history into one summary bubble; Keep or Purge). Phase 4 (Model×Model,
autonomous ticks, group chat) is sketched in the design and gets its own build plan just-in-time.

## How it works (Phase 1)

1. Open **Apps** (`/apps`) → the **Prattletale** card → `/apps/prattletale/`.
2. The landing page lists conversations. **+ New conversation** picks a Hoodat counterpart, a
   scenario, role instructions, and your own persona.
3. The chat view shows alternating, avatar-grouped bubble stacks. The **composer** lets you cycle
   an item's mode (dialogue / action / narration) and stack multiple items into one turn, then
   commit.
4. Committing appends your turn and runs the model's reply **synchronously** (a direct chain run,
   like Hoodat/Blaboratory). A client-side typing indicator shows while it generates; the reply
   then renders as its bubble stack. A failed turn becomes a red error bubble with **Retry**.
5. Reloading restores the full transcript from disk.

**Prerequisite:** a default LLM endpoint (Server → LLM → Endpoints), used via
`get_default_as_chain_llm_config()`. Voice additionally needs the `voice` capability and a narrator
voice (Prattletale settings); without it Prattletale degrades to text.

## How it works (Phase 2 — config & dev tools)

- **Config view** (the ⚙ in the chat header) edits the conversation's `title`, `scenario`,
  `role_instructions`, your display name + persona, the **context window** (turns), and the
  voice / typing-timing / variety toggles — all through one broadened `PATCH /conversations/{id}`
  (nested `config` patch; flat config keys still accepted for back-compat). The list-view ⚙ stays
  app-level (narrator voice).
- **Per-message controls**: hover any bubble for **✏️ edit** (inline, `PATCH …/items/{item_id}`),
  **🚫 hide / 👁 show** from context (toggles `hidden_from_context` — hidden bubbles stay in the
  thread but render muted/struck-through and are dropped from the next turn's context), and **🗑
  delete** (`DELETE …/items/{item_id}`; deleting a turn's last item removes the turn). A turn's
  avatar exposes **🗑 delete-turn** (`DELETE …/turns/{turn_id}`). Edits never re-run the model —
  regeneration stays turn-level **Retry**.
- **Dev tools**: a model turn's avatar exposes **🔍 trace** → a modal showing the `context_input`
  bundle, `raw_final_output`, parsed items, reveal schedule, and any error, plus a **node-graph**
  of that turn's `Turn → (Variety) → Guard` pipeline (read from the trace's enriched `steps`). Each
  node opens its rendered prompt + output and deep-links to its Prompt Pal entry. The trace is read
  via `GET …/turns/{turn_id}/trace`; the generator enriches each trace with the ordered `steps`
  (`{number, id, name, prompt, output}`) by pairing the request steps with the executor's per-step
  output dirs.

## How it works (Phase 3 — plugins)

A **plugin** is a backend package under `app/apps/prattletale/plugins/<id>/` that registers itself
at import (a `Plugin` manifest + named **actions**), with optional **frontend assets** under
`static/apps/prattletale/plugins/<id>/`. The backend hook surface is one generic endpoint —
`POST /conversations/{id}/plugins/{plugin_id}/actions/{action}` — that 404s on an unknown
plugin/action, 409s when the plugin isn't in the conversation's `config.enabled_plugins`, and
otherwise runs the action and returns its result dict. `GET /plugins` lists the manifests. The
frontend loads each enabled plugin's JS, which calls `window.PtPlugins.register({...})` to contribute
**composer modes**, a **renderPanel**, and **bubble renderers**; the core merges these in without
knowing what the plugin does. Plugins are toggled per conversation in the config dialog's **Plugins**
section (persisted through the same nested-`config` PATCH); new conversations start with each plugin
whose `default_enabled` is true.

**Summarizer** (the first plugin, default-on) adds a **📋 Summarize** composer mode. Selecting it
slides up a panel with **Keep / Purge**, a **detail level** (Brief / Standard / Detailed), and an
optional **focus** note. Submitting runs a hierarchical **map-reduce** over the chain executor
(chunk the covered turns → summarize each chunk → merge partials until one remains; editable
`summarize.map` / `summarize.reduce` / `summarize.level.*` Prompt Pal entries) and posts one
avatar-less, centered **📋 Summary** card (a `summary` item on a `system`-authored turn, kept in
context and rendered as `[Summary so far] …`). **Keep** leaves the originals in context;
**Purge** also marks the covered originals `hidden_from_context` (still visible, styled
"summarized") so the summary compresses the window — and re-summarizing folds the prior summary +
new turns rather than the purged originals. A failed summarize surfaces inline in the panel (no chat
error bubble).

**Sound Effects** (default-on) attaches an optional emote **after-cue** to `action` / `narration`
items (never `dialogue`). It's a thin frontend hook (`onModelTurn`) over the platform
[SFX subsystem](../../tools/sfx.md): when a turn renders it calls the `resolve-turn` action, which
for each eligible item rolls `config.sfx_chance` **before** any LLM call, then (on a pass) asks the
platform resolver to pick one clip from the counterpart character's emote **identity**
(set on Hoodat's **Audio** tab) plus any conversation-enabled global **domains** (`config.sfx_domains`,
e.g. `lewd` for the NSFW gate), validates it with a guard, and persists a compact `sfx` descriptor on
the item (`status` ∈ `skipped` / `none` / `rejected` / `resolved` / `error`; resolution traces append
to the turn's `traces/<turn>.json` under `sfx`). Playback is additive and ordered: during reveal and
on speaker-button replay the item's normal voice audio plays first, then the SFX cue
(`playItemAudioSequence`). A cue that resolves after its bubble is revealed is replay-only and never
interrupts later messages. The config dialog exposes **♪ Sound effects**, **🔞 NSFW SFX (lewd)**, and
an **SFX chance** field. Plugin actions: `resolve-item`, `resolve-turn`, `reroll-item` (skips the
chance roll and any prior final state), `clear-item`.

**Remember** (default-on) is Prattletale's [memory](../../memory/index.md) integration — the
first shipped end-to-end use of the app-agnostic memory subsystem. **Retrieval** is automatic
and invisible: every turn's chain step carries a `{{memory}}` config scoped to
`character:<counterpart>` + `session:<conversation>` + `app:prattletale` + `global` (so a
universal fact like the user's name reaches every character), queried by what the user just
said, so relevant long-term facts are recalled into the `TURN` prompt's `<memory>` section (written to
`steps/001_turn/memory.txt` for the trace). It's fail-soft — empty/disabled memory changes
nothing. **Writing** is always an explicit user action (never auto-extracted from turns):
the **🧠 Remember** composer mode (type a fact → pick scope → Save), and a per-bubble **🧠
Memorize** control that expands into **Verbatim** (save the message text) / **Gist** (distil a
durable fact via the guarded `memory.gist` prompt) / **Cancel** — using the reusable
`subactions` affordance in `FieldControls`. The **Summarizer** panel also gains an *"Also save
this recap to memory"* toggle. Plugin actions: `remember`, `gist`. Inspect or seed memories in
the [Memory Lab](../../memory/index.md) (`/memory-lab/`); they live as Markdown under
`config/memory/characters/<id>/` and `config/memory/sessions/<id>/`.
