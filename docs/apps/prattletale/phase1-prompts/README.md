# Prattletale Phase 1 — implementation prompt sequence

Copy-paste session-starters for building the **text-first conversation loop** (then voice), one
sub-phase per session. Each is self-contained: read it top-to-bottom and paste the fenced block
into a fresh session. `/clear` between sessions.

Plan of record: **[`../phase1-foundation-build-plan.md`](../phase1-foundation-build-plan.md)**.
Shared substrate every session reads: **[`../design.md`](../design.md)**.

| Order | Sub-phase | Prompt | Depends on | Needs LLM / GPU node? |
|-------|-----------|--------|-----------|------------------------|
| 1 | SP1 — scaffold + data model + store | [01](01-sp1-scaffold-store.md) | — | No |
| 2 | SP2 — prompts + parser | [02](02-sp2-prompts-parser.md) | — | No |
| 3 | SP3 — generator pipeline | [03](03-sp3-generator-pipeline.md) | SP1 + SP2 | No (mock executor) |
| 4 | SP4 — router / API | [04](04-sp4-router-api.md) | SP3 | No (stub generator) |
| 5 | SP5 — frontend (iMessage UI) | [05](05-sp5-frontend.md) | SP4 | Yes (manual, real LLM) |
| 6 | SP6 — voice + timing | [06](06-sp6-voice-timing.md) | SP3–SP5 | Yes (voice capability) |
| 7 | SP7 — hardening + docs | [07](07-sp7-hardening-docs.md) | all | Yes (real end-to-end) |

SP1 and SP2 are independent — build them in either order.

**Shared conventions** (true for every prompt): `.venv/bin/python`, `.venv/bin/pytest`
(`asyncio_mode=auto`), `.venv/bin/python -m py_compile <file>`; stores write under `config/`
(gitignored) — tests monkeypatch module-level `*_DIR`/`*_PATH` to `tmp_path`; generation runs the
chain executor **directly** (not the JobQueue), mirroring Hoodat/Blaboratory; **no new pip
dependencies**; **don't commit until reviewed**.
