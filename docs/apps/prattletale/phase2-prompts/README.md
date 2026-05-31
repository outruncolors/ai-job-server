# Prattletale Phase 2 — implementation prompt sequence

Copy-paste session-starters for building **config & dev tools** on the Phase 1 text+voice loop, one
sub-phase per session. Each is self-contained: read it top-to-bottom and paste the fenced block into
a fresh session. `/clear` between sessions.

Plan of record: **[`../phase2-config-devtools-build-plan.md`](../phase2-config-devtools-build-plan.md)**.
Shared substrate every session reads: **[`../design.md`](../design.md)**.

| Order | Sub-phase | Prompt | Depends on | Needs LLM / GPU node? |
|-------|-----------|--------|-----------|------------------------|
| 1 | SP1 — transcript editing API (edit/hide/delete) | [01](01-sp1-transcript-editing-api.md) | — | No |
| 2 | SP2 — conversation settings API | [02](02-sp2-conversation-settings-api.md) | — | No |
| 3 | SP3 — trace + pipeline read API | [03](03-sp3-trace-pipeline-api.md) | — | No (stub executor) |
| 4 | SP4 — conversation config view | [04](04-sp4-config-view.md) | SP2 | Yes (manual, real LLM) |
| 5 | SP5 — per-message action wrapper | [05](05-sp5-message-action-wrapper.md) | SP1 | Yes (manual) |
| 6 | SP6 — trace viewer + node-graph | [06](06-sp6-trace-viewer-node-graph.md) | SP3 | Yes (manual) |
| 7 | SP7 — hardening + docs | [07](07-sp7-hardening-docs.md) | all | Yes (real end-to-end) |

SP1, SP2, SP3 are mutually independent backend additions — build them in any order / in parallel.
Each frontend sub-phase depends only on its own backend (SP4→SP2, SP5→SP1, SP6→SP3).

**Shared conventions** (true for every prompt): `.venv/bin/python`, `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>`; stores write under `config/`
(gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` to `tmp_path`; generation runs the
chain executor **directly** (not the JobQueue), mirroring Hoodat/Blaboratory; **no new pip
dependencies**; **don't commit until reviewed**.
</content>
