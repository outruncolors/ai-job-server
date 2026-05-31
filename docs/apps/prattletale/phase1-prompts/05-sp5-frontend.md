# SP5 — Frontend (iMessage UI, text-only)

Sub-phase **SP5** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [04 — SP4](04-sp4-router-api.md) · **Next:** [06 — SP6 voice + timing](06-sp6-voice-timing.md) · [Sequence](README.md)

Depends on **SP4**, committed. Verified manually in the browser against a real LLM.

```
Implement Phase 1 sub-phase SP5 of Prattletale (iMessage-style roleplay chat): the browser UI.
SP1–SP4 are committed; the API at /v1/apps/prattletale works. Text-only (no voice yet).

Read first:
- docs/apps/prattletale/design.md — "Mission", "data model", "API surface".
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP5" section.
- static/apps/hoodat/ — fetch/render conventions, the api()/_escHtml helpers, page skeleton +
  nav loading (<nav id="topnav"> + nav.js + nav-mobile.js, body padding-top:44px).
- docs/reference/ui-standards.md and docs/reference/ui-cheatsheet.md — dark-theme tokens,
  responsive.css, components.css, touch targets.
- static/apps/apps.js — the Prattletale card was added in SP1.

Build (additive only) — static/apps/prattletale/ (index.html + prattletale.js + styles.css):
- Conversation list for the active device user: each row shows the counterpart's name + avatar
  (character.avatar_path from Hoodat), a last-item preview, and a timestamp. A "+ New conversation"
  form picks a counterpart Hoodat character (fetch the character list), scenario, role
  instructions, and the user's persona; POST /conversations then open the chat view.
- Chat view: render turns as avatar-grouped bubble stacks; give each item type a distinct bubble
  shape/style (dialogue vs action vs narration/narration_emotion). A composer with MODE CYCLING (an
  inline control to toggle the next item between dialogue/action/narration), multi-item drafting
  (stack items before committing), and a commit action that POSTs {items:[...]} to
  /conversations/{id}/turns.
- While the POST is in flight, show a CLIENT-SIDE typing indicator; on response, append the model
  bubble stack. If the model_turn is a system_error item, render a red error bubble with a Retry
  button wired to POST /conversations/{id}/turns/{turn_id}/retry (replace the bubble in place on
  success).
- Reloading the chat view restores the full transcript from GET /conversations/{id}.
- Escape all text before innerHTML (_escHtml). Reuse api() (auto-prepends /v1).

Done when (manual, real LLM — start .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090):
- create a conversation against an existing Hoodat character;
- send a multi-item user turn; see a typing indicator, then the model's bubble stack;
- force a failure (e.g. a bad LLM endpoint) -> error bubble -> Retry replaces it in place;
- reload -> the transcript restores from disk.
No new automated assertions required beyond SP4's API tests; run the existing suite to confirm
nothing regressed.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto). No new pip deps.
Don't commit until I've reviewed.
```
