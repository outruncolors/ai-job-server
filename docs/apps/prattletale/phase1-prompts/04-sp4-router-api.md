# SP4 — Router / API

Sub-phase **SP4** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [03 — SP3](03-sp3-generator-pipeline.md) · **Next:** [05 — SP5 frontend](05-sp5-frontend.md) · [Sequence](README.md)

Depends on **SP1–SP3**, committed. Tests use the FastAPI TestClient with a stubbed generator.

```
Implement Phase 1 sub-phase SP4 of Prattletale (iMessage-style roleplay chat): the HTTP API.
SP1–SP3 are committed. The empty router stub from SP1 is replaced here.

Read first:
- docs/apps/prattletale/design.md — "API surface (Phase 1)" + "Error handling & retry".
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP4" section.
- app/apps/hoodat/router.py — APIRouter prefix, Pydantic request models, GenerationError->HTTP
  mapping, 404 patterns, status codes.
- Committed SP3 generator (run_model_turn) + SP1 store.

Build (additive only) — app/apps/prattletale/router.py:
- APIRouter(prefix="/v1/apps/prattletale", tags=["prattletale"]).
- Request models: ConversationCreate {title, counterpart_character_id, device_user, scenario,
  role_instructions}; TurnCreate {items: list[{type, text}]}.
- Routes:
  - GET /conversations -> summaries (id, title, counterpart, last-item preview, updated_at).
  - POST /conversations (201) -> create; 404 if counterpart character missing.
  - GET /conversations/{id} -> {conversation, transcript}; 404 if missing.
  - DELETE /conversations/{id} -> 200/204; 404 if missing.
  - POST /conversations/{id}/turns -> store.append_user_turn(items); await run_model_turn(id);
    return {user_turn, model_turn} (model_turn may be a system_error turn — still 200).
  - POST /conversations/{id}/turns/{turn_id}/retry -> re-run run_model_turn against the transcript
    with that turn excluded; store.replace_turn in place; return the new turn. 404 if conv/turn
    missing; 409 if the turn isn't the latest model/error turn (your call — keep it simple).
- app/main.py: ensure the real router is included (replace the SP1 stub import target — the
  include line stays the same).

Done when tests/apps/test_prattletale_router.py passes (TestClient; monkeypatch CONVERSATIONS_DIR
to tmp; stub run_model_turn to append a known model turn):
- POST /conversations returns 201 and both files are persisted;
- POST /conversations with a missing counterpart 404s;
- POST /conversations/{id}/turns returns {user_turn, model_turn};
- retry on an error turn replaces it in place;
- DELETE removes the folder;
- GET /conversations/{id} returns conversation + transcript.
Run the full suite (.venv/bin/pytest) — main.py changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
