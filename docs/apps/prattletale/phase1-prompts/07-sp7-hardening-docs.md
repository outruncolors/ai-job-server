# SP7 — Hardening + docs

Sub-phase **SP7** of [`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md).
**Prev:** [06 — SP6](06-sp6-voice-timing.md) · **Next:** — · [Sequence](README.md)

Depends on **all** prior sub-phases, committed. Closes out Phase 1.

```
Implement Phase 1 sub-phase SP7 of Prattletale (iMessage-style roleplay chat): hardening + docs.
SP1–SP6 are committed (text loop + voice). This closes Phase 1.

Read first:
- docs/apps/prattletale/design.md — "Risks / open questions".
- docs/apps/prattletale/phase1-foundation-build-plan.md — the "SP7" section.
- The committed prior sub-phases' tests (tests/apps/test_prattletale_*.py).
- docs/apps/index.md and docs/index.md — where to register the app in the docs tree.
- CLAUDE.md — the "Apps (consumer experiences)" table.

Build:
- Edge cases + tests:
  - empty-transcript first turn (build_context with no prior turns);
  - oversized context window (more turns than exist; very long turns);
  - guard stripping leaked meta / OOC while preserving bubble count;
  - concurrent-write safety: append_* re-reads transcript before writing (add a regression test);
  - empty device_user.persona renders cleanly.
- One integration test (tests/apps/test_prattletale_integration.py) driving the full loop end-to-end
  against the default LLM path (or a faithful stub): create -> commit user turn -> model turn ->
  induce an error -> retry -> assert the on-disk transcript shape (turn/item ids, statuses,
  system_error replaced in place).
- Docs: finalize docs/apps/prattletale/index.md (mark Phase 1 built); add a Prattletale row to
  docs/apps/index.md and a TOC line under "Apps" in docs/index.md; add a CLAUDE.md "Apps" table
  block for app/apps/prattletale/* + static/apps/prattletale/* (mirror the Hoodat/Blaboratory rows).

Done when tests/apps/test_prattletale_integration.py passes end-to-end, all prattletale tests pass,
the full suite is green, and the docs reference the new app.

Env: .venv/bin/python, .venv/bin/pytest (asyncio_mode=auto), py_compile. No new pip deps.
Don't commit until I've reviewed.
```
