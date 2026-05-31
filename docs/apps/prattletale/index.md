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

## Status

**Phase 1 (text-first conversation loop + voice) and Phase 2 (config & dev tools) are built.** A
human can create a conversation against a Hoodat character and exchange typed-bubble turns; model
dialogue/narration can be synthesized to audio with a per-item reveal cadence (degrades to text when
voice is off or the `voice` capability is absent). Phase 2 adds an in-chat **config view** (edit
metadata + behaviour after creation), **per-message edit / hide / delete** (and delete-turn), and a
**dev-tools trace viewer + pipeline node-graph**. Phases 3–4 (plugins, Model×Model, autonomous
ticks, group chat) are sketched in the design and get their own build plans just-in-time.

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
