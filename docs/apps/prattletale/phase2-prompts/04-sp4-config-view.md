# SP4 — Conversation config view (frontend)

Sub-phase **SP4** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [03 — SP3](03-sp3-trace-pipeline-api.md) · **Next:** [05 — SP5 message action wrapper](05-sp5-message-action-wrapper.md) · [Sequence](README.md)

Depends on **SP2**, committed. Verified manually in the browser.

```
Implement Phase 2 sub-phase SP4 of Prattletale (iMessage-style roleplay chat): the per-conversation
config view in the browser. SP2 is committed (the conversation settings PATCH works). Pure frontend.

Read first:
- docs/apps/prattletale/design.md — "Mission" and "conversation.json".
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP4" section.
- static/apps/prattletale/index.html + prattletale.js + styles.css (committed) — the single-page
  structure: #pt-list-view / #pt-chat-view toggled by ?id=; showView() routing; renderToggles() /
  toggleConfig() (header voice/timing/variety toggles); openSettings() (app-level narrator dialog).
- docs/reference/ui-standards.md and ui-cheatsheet.md — dark-theme tokens, components, touch targets.
- SP2's committed conversation PATCH endpoint (the exact body shape it accepts).

Build (additive only) — static/apps/prattletale/:
- A per-conversation CONFIG VIEW for the open conversation. Match the existing single-page pattern:
  either a third view toggled by a query param (e.g. ?id=<id>&view=config so reload/back behaves like
  the list<->chat toggle) OR a full-height dialog opened from a new gear control in the chat header —
  pick one and keep it consistent with the existing routing. (The list-view ⚙ stays app-level:
  narrator voice.)
- Editable fields: title, scenario, role instructions, your display name, your persona, a
  CONTEXT-WINDOW control (number/slider, min 1), and the voice/timing/variety toggles (move or mirror
  the header toggles here). Save -> SP2 PATCH; on success reflect the saved values into
  _current.conversation and re-render the chat header.
- Migrate the header toggle calls (toggleConfig) to whatever body shape SP2 settled on (nested config
  vs flat keys).
- Escape all text before innerHTML (_escHtml); reuse api() (auto-prepends /v1).

Done when (manual — start .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090):
- open a conversation -> open the config view;
- change scenario + your persona + the context-window value + a toggle -> save -> reload -> the
  changes persisted;
- send another turn and confirm the new context window / persona shows up in that turn's trace
  context_input (GET .../trace, or just trust SP2's tests).
No new automated assertions beyond SP2's API tests; run the existing suite to confirm nothing
regressed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto). No new pip deps. Don't commit until
I've reviewed.
```
</content>
