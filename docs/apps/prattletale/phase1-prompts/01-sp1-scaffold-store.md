# SP1 — Scaffold + data model + store (no LLM)

Sub-phase **SP1** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** — · **Next:** [02 — SP2 prompts + parser](02-sp2-prompts-parser.md) · [Sequence](README.md)

Self-contained: pure file-based store + Pydantic models. No LLM, no network, no frontend.

```
Implement Phase 1 sub-phase SP1 of Prattletale — a new iMessage-style roleplay chat app in this
repo (app/apps/<name> + static/apps/<name> convention). This sub-phase is the package scaffold +
data model + on-disk store only. No LLM, no network, no frontend.

Read first:
- docs/apps/prattletale/design.md — focus on "Terminology & data model". Skim "Mission" + "Scope
  by phase" for context. Do NOT build the generator/router/UI yet.
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP1" section.
- app/apps/hoodat/__init__.py and app/apps/hoodat/characters_store.py — mirror the file-per-doc
  atomic-write (tmp + os.replace) store pattern and slug-id assignment.
- app/cruddables/envelope.py — reuse slugify / unique_id / now_iso.
- app/main.py — the router import region (~lines 60–70) and include region (~237–245).
- static/apps/apps.js — the APPS array (add a Prattletale card).

Build (additive only):
1. app/apps/prattletale/__init__.py
2. app/apps/prattletale/models.py — Pydantic Conversation, DeviceUser, ConversationConfig, Turn,
   Item; enums ItemType (dialogue|action|narration|narration_emotion|system_error), Author
   (user|model), ItemStatus (committed|generating|error). Match the design JSON shapes exactly,
   including the inert config voice flags and item.hidden_from_context (default False).
3. app/apps/prattletale/store.py — CONVERSATIONS_DIR const (monkeypatchable; under
   config/prattletale/conversations/). Atomic writes. Functions:
   list_conversations(), get_conversation(id), create_conversation(fields) [slug id unique vs
   existing folders; writes conversation.json + an empty transcript.json], update_conversation(id,
   patch), delete_conversation(id); get_transcript(id), append_user_turn(id, items),
   append_model_turn(id, items, *, job_id), append_error_turn(id, message, *, job_id),
   replace_turn(id, turn_id, items, *, author, job_id), write_trace(id, turn_id, trace).
   Append/replace re-read transcript before writing; turn ids "t%04d" via next_turn_seq; item ids
   "<turn_id>-i%02d". append_error_turn writes one system_error item (status error).
4. app/main.py: add `from .apps.prattletale.router import router as prattletale_router` and
   `app.include_router(prattletale_router)`. For SP1, create router.py with just an empty
   APIRouter(prefix="/v1/apps/prattletale") so the import resolves.
5. static/apps/apps.js: add a Prattletale card (href '/apps/prattletale/', name, tagline, blurb,
   glyph).

Done when tests/apps/test_prattletale_store.py passes (monkeypatch CONVERSATIONS_DIR to tmp_path):
- create_conversation writes both files with a slug id;
- append_user_turn / append_model_turn assign monotonic turn + item ids and round-trip via
  get_transcript;
- replace_turn overwrites a turn in place (same turn_id, new items);
- append_error_turn yields exactly one system_error item;
- delete_conversation removes the folder.
Also run the full existing suite (.venv/bin/pytest) since main.py changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
