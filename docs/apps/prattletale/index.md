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

## Status

**Phase 1 (text-first conversation loop + voice) is built.** A human can create a conversation
against a Hoodat character and exchange typed-bubble turns; model dialogue/narration can be
synthesized to audio with a per-item reveal cadence (degrades to text when voice is off or the
`voice` capability is absent). Phases 2–4 (config/dev-tools, plugins, advanced) are sketched in the
design and get their own build plans just-in-time.

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
