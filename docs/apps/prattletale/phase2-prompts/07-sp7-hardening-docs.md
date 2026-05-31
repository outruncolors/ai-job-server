# SP7 — Hardening + docs

Sub-phase **SP7** of [`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md).
**Prev:** [06 — SP6](06-sp6-trace-viewer-node-graph.md) · **Next:** — · [Sequence](README.md)

Depends on **all** prior sub-phases, committed. Closes out Phase 2.

```
Implement Phase 2 sub-phase SP7 of Prattletale (iMessage-style roleplay chat): hardening + docs.
SP1–SP6 are committed (transcript editing, conversation settings, trace API, config view, message
action wrapper, trace viewer + node-graph). This closes Phase 2.

Read first:
- docs/apps/prattletale/design.md — "Risks / open questions".
- docs/apps/prattletale/phase2-config-devtools-build-plan.md — the "SP7" section.
- The committed prior sub-phases' tests (tests/apps/test_prattletale_*.py).
- docs/apps/prattletale/index.md, docs/apps/index.md — where the app is registered in the docs tree.
- CLAUDE.md — the "Apps (consumer experiences)" table Prattletale rows.

Build:
- Edge cases + tests:
  - edit/hide/delete on the only item of a turn, on a system_error turn, and on a mid-list turn
    (other turns' ids unchanged);
  - hidden-then-shown round-trip restores the item to context; a fully-hidden turn drops out of the
    flattened transcript with no dangling speaker label;
  - settings: context_window_turns larger than the turn count; a 0/negative rejection;
  - concurrent edit + a posted turn (re-read-before-write keeps both);
  - trace read for a turn with no trace / a missing conversation.
- One integration test (tests/apps/test_prattletale_config_devtools_integration.py): create ->
  commit a user + model turn -> edit the user item -> hide a model item and assert the next turn's
  trace context_input omits it -> patch context_window_turns and assert the window changed -> read
  the trace and assert the enriched `steps` shape -> delete a turn. Drive the default LLM path or a
  faithful stub; assert on-disk transcript + trace shapes.
- Docs (current-state only — NO "previously/now/renamed" framing):
  - docs/apps/prattletale/index.md — mark Phase 2 built; add the config / dev-tools "how it works"
    bullets and link this plan + prompts;
  - docs/apps/index.md — update the Prattletale row to mention config + dev tools;
  - CLAUDE.md "Apps" table — extend the Prattletale rows for the new endpoints (item PATCH/DELETE,
    turn DELETE, broadened conversation PATCH, GET trace) and the config view / per-message action
    wrapper / trace viewer + node-graph UI.

Done when tests/apps/test_prattletale_config_devtools_integration.py passes end-to-end, all
prattletale tests pass, the full suite is green, and the docs reference the new surface.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps. Don't
commit until I've reviewed.
```
</content>
