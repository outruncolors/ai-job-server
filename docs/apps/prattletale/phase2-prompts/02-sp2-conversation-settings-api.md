# SP2 — Conversation settings API (editable metadata + behaviour)

Sub-phase **SP2** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [01 — SP1](01-sp1-transcript-editing-api.md) · **Next:** [03 — SP3 trace + pipeline API](03-sp3-trace-pipeline-api.md) · [Sequence](README.md)

Self-contained: one broadened endpoint over the existing store. No LLM, no frontend.
**Independent of SP1 — can be built first / in parallel.**

```
Implement Phase 2 sub-phase SP2 of Prattletale (iMessage-style roleplay chat): the conversation
settings API — make a conversation's metadata (title, scenario, role_instructions, device_user) and
behaviour config (context_window_turns + the voice/timing/variety toggles) editable after creation,
through one endpoint. No frontend.

Read first:
- docs/apps/prattletale/design.md — "conversation.json" and "Risks / open questions" #3 (the context
  window unit is turns, not tokens).
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP2" section.
- app/apps/prattletale/store.py (committed) — update_conversation: it shallow-merges a patch into
  the conversation, re-validates Conversation(**current), and atomic-writes. It already persists any
  of these fields; the only question is preserving sibling config keys (deep-merge config).
- app/apps/prattletale/router.py (committed) — ConversationCreate, ConfigPatch, and the current
  config-toggle-only `update_conversation_config` PATCH. The Phase-1 frontend toggleConfig() posts
  flat {voice_enabled: ...} to this PATCH — keep that working.
- app/apps/prattletale/models.py — Conversation, DeviceUser, ConversationConfig.

Build (additive only):
- Broaden the conversation PATCH so it accepts editable metadata AND a nested config patch, while
  keeping today's header toggles working. Recommended: PATCH /conversations/{id} with a
  ConversationUpdate body — all-optional title, scenario, role_instructions, device_user (DeviceUser),
  and config (partial ConversationConfig, INCLUDING context_window_turns). Apply via
  store.update_conversation (shallow-merge top-level; DEEP-merge the config sub-dict so unset config
  keys are preserved — add the deep-merge if the current shallow merge would drop sibling keys).
  Validate context_window_turns >= 1 (422 otherwise).
- Back-compat: keep accepting the flat config toggle keys the Phase-1 UI sends (hoist them into
  config) so the running app stays green until SP4 switches the UI. Note which you chose.

Done when tests/apps/test_prattletale_conversation_settings.py passes (TestClient + monkeypatched
store dirs):
- patching scenario / role_instructions / device_user.persona persists, round-trips via
  get_conversation, and bumps updated_at;
- patching config.context_window_turns changes the window build_context slices (assert the rendered
  transcript honors the new window) WITHOUT clearing the voice/variety flags;
- context_window_turns of 0 / negative 422s;
- an existing toggle still flips via the same endpoint;
- a missing conversation 404s.
Run the full suite since router.py changed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps. No model
change. Don't commit until I've reviewed.
```
</content>
