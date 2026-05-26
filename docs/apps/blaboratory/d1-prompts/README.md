# Blaboratory D1 — implementation prompt sequence

Copy-paste session-starters for building the vector memory/lore retrieval system
(**D1**), one phase per session. Each is self-contained; read it top-to-bottom and
paste the fenced block into a fresh session.

Plan of record: **[`../d1-vector-build-plan.md`](../d1-vector-build-plan.md)**.

| Order | Phase | Prompt | Depends on | Needs embed server / GPU node? |
|-------|-------|--------|-----------|-------------------------------|
| 1 | D1.1 — schema + `VectorIndex` | [01](01-d1.1-schema-index.md) | — | No (hand-built vectors) |
| 2 | D1.2a — app-managed embed server | [02](02-d1.2a-embed-server.md) | — | Built locally; **deployed** to run |
| 3 | D1.2b — `embed()` client + config | [03](03-d1.2b-embed-client.md) | D1.2a | No (mocked transport) |
| 4 | D1.3 — indexing pipeline | [04](04-d1.3-indexing.md) | D1.1 + D1.2b | No (mocked embed) |
| 5 | D1.4 — hybrid retrieval (payoff) | [05](05-d1.4-hybrid-retrieval.md) | D1.1 + D1.3 | No (fake index) |
| 6 | D1.5 — ops + docs + polish | [06](06-d1.5-ops-docs.md) | all | Yes (real end-to-end) |

**Shared conventions** (true for every prompt): branch `blaboratory-part2`;
`.venv/bin/python`, `.venv/bin/pytest` (`asyncio_mode=auto`),
`.venv/bin/python -m py_compile <file>`; stores write under `config/` (gitignored);
tests monkeypatch module-level `*_PATH`/`DB_PATH` to tmp; **don't commit until reviewed**.
`sqlite-vec==0.1.9` is already installed + committed.
