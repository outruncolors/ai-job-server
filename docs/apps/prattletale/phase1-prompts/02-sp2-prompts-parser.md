# SP2 — Prompts + parser (no network)

Sub-phase **SP2** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [01 — SP1](01-sp1-scaffold-store.md) · **Next:** [03 — SP3 generator](03-sp3-generator-pipeline.md) · [Sequence](README.md)

Self-contained: Prompt Pal registration + a pure tagged-line parser. No network, no LLM call.
Independent of SP1 — can be built before or after it.

```
Implement Phase 1 sub-phase SP2 of Prattletale (an iMessage-style roleplay chat app). This
sub-phase registers the turn-generation prompt (+ a format-hygiene guard) with Prompt Pal and
implements the tagged-line parser. No network call.

Read first:
- docs/apps/prattletale/design.md — focus on "Turn-generation pipeline" (the parse_items + "The
  narrative editor is a guard" subsections). Skim "data model" for ItemType.
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP2" section.
- app/apps/hoodat/prompts.py — the register(...) call pattern and SPOKEN_ONLY_GUARD (the guard
  precedent); render_character_context (the {{var.character}} shape consumers pass in).
- app/prompt_pal/registry.py — register(), _PROMPT_MODULES, seed_registered().
- app/prompt_pal/service.py — get_text(app, key, variables=), get_guard(app, key).

Build (additive only):
1. app/apps/prattletale/prompts.py:
   - register("prattletale", "turn", title=..., description=..., variables={...}, guard={...}) with
     a prompt that instructs the model to reply as an ordered stack of short, texty bubbles, one
     per line, each tagged: [say] (dialogue), [do] (action), [narration], [feel]
     (narration_emotion). The prompt consumes {{var.character}}, {{var.scenario}},
     {{var.role_instructions}}, {{var.user_persona}}, {{var.transcript}} (and may reference
     {{input}} for the latest user line if you choose). The guard (enabled) runs over {{previous}}
     and does FORMAT HYGIENE ONLY: ensure every line is tagged, strip leaked internal monologue /
     meta ("As an AI", "Here's my response:") and OOC commentary; it must NOT merge multiple
     bubbles into one and must NOT rewrite content.
   - parse_items(raw) -> list[dict {type, text}] and _strip_fences(raw): strip ``` fences, split on
     newlines, regex ^\s*\[(\w+)\]\s*(.+)$, map say/do/narration/feel to the ItemType values; an
     untagged non-empty line coalesces into the previous item's text; a lone leading untagged line
     defaults to dialogue; empty/whitespace-only result raises GenerationError (define it here or
     import from generator later — keep a local exception for now).
2. app/prompt_pal/registry.py: append "app.apps.prattletale.prompts" to _PROMPT_MODULES.

Done when tests/apps/test_prattletale_prompts.py passes (monkeypatch the Prompt Pal store dir to
tmp):
- after seed_registered(), the (prattletale, turn) entry exists in the store and get_text composes
  it with provided variables; get_guard returns the guard text;
- parse_items maps [say]/[do]/[narration]/[feel] to dialogue/action/narration/narration_emotion;
- an untagged continuation line is appended to the previous item;
- a single untagged line becomes one dialogue item;
- fenced ```...``` wrappers are stripped;
- empty / whitespace-only input raises.
Also run the existing Prompt Pal tests (.venv/bin/pytest tests -k prompt_pal) — they must stay
green (you touched _PROMPT_MODULES).

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
