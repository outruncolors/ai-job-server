# Memory

An app-agnostic, **file-first** memory subsystem. Markdown files under `config/memory/`
are the durable source of truth; the search backend (a plain keyword scorer by default,
optional [memsearch](#backends)/Milvus for semantics) is a swappable implementation detail
behind a narrow adapter.

The guiding principle: memory behavior must be **observable, testable, and debuggable one
small operation at a time** — through atomic unit tests *and* the [Memory Lab](#memory-lab)
browser bench — before any app depends on it.

- **[API reference](api.md)** — every `/v1/memory` endpoint with curl examples
- **[App integration](apps.md)** — the standard contract apps use
- **[Chain integration](chains.md)** — the `{{memory}}` token + per-step `memory` config

## File layout

Each memory is one Markdown file with YAML frontmatter. Files live under a scope-derived
directory tree:

```text
config/memory/
  global/                    # scope_type=global (flat, no scope_id subdir)
    *.md
  apps/<scope_id>/           # scope_type=app
  projects/<scope_id>/       # scope_type=project
  users/<scope_id>/          # scope_type=user
  sessions/<scope_id>/       # scope_type=session
  characters/<scope_id>/     # scope_type=character
  custom/<scope_id>/         # scope_type=custom
  test/<scope_id>/           # scope_type=test  (demo fixtures live in test/memory_demo)
  .memsearch/milvus.db       # optional memsearch index (rebuildable, not source of truth)
```

`config/` is gitignored, so memory records and the optional Milvus-Lite index stay local
to the node. `scope_id` is slugified into the path, which also neutralizes path traversal.

### Record format

```markdown
---
id: mem_20260604_153012_a1b2c3
title: User prefers atomic UI test panels
scope_type: project
scope_id: ai-job-server
created_at: 2026-06-04T15:30:12+00:00
updated_at: 2026-06-04T15:30:12+00:00
status: active
tags:
  - architecture
  - testing
source_type: manual
importance: 0.7
---

The body is Markdown and is preserved byte-exact on disk.
```

Required meta: `id`, `title`, `scope_type`, `scope_id`, `created_at`, `updated_at`,
`status`. Optional: `app_id`, `user_id`, `session_id`, `tags`, `source_type`,
`source_ref`, `importance`, `expires_at`, `supersedes`, `visibility`. Any other
frontmatter keys are round-tripped verbatim (`MemoryRecord.extra`).

## Scopes

A scope identifies the ownership/context of a memory:

```json
{ "scope_type": "project", "scope_id": "ai-job-server" }
```

`scope_type` is one of `global | app | project | user | session | character | custom |
test`. Search accepts **one or more** scopes; an empty list searches everything. Some
callers only need `scope_type + scope_id`; others combine the optional typed fields
(`app_id`, `user_id`, `session_id`).

## Backends

Selected by `MEMORY_BACKEND` (config below). Both expose the identical result model — apps
never see backend-specific shapes.

| Backend | Deps | Notes |
|---|---|---|
| `plain` (default) | none | Deterministic keyword scorer (substring + token overlap, title/tag boosts). Reads live files every query — nothing to index. Ideal for tests + dev. |
| `memsearch` | `pip install "memsearch[onnx]"` | Semantic search via Milvus-Lite + local ONNX bge-m3 embeddings (model downloads from HuggingFace on first index/search; no API key). |

The adapter **never owns the write path** — the store writes Markdown; the adapter only
indexes/searches it. This keeps Markdown the real database and the vector index throwaway.

## Configuration

Environment variables (read by `app/memory/config.py`):

| Var | Default | Meaning |
|---|---|---|
| `MEMORY_ENABLED` | `true` | Master switch; when false, search returns empty + a clear flag. |
| `MEMORY_BACKEND` | `plain` | `plain` or `memsearch`. |
| `MEMORY_BASE_DIR` | `config/memory` | Root of the Markdown tree. |
| `MEMORY_TOP_K_DEFAULT` | `5` | Default result count when a request omits `top_k`. |
| `MEMORY_REQUIRE_BACKEND` | `false` | When true, an unavailable memsearch is a hard error instead of falling back to plain. |
| `MEMORY_MEMSEARCH_COLLECTION` | `ai_job_server_memory` | Milvus collection name. |
| `MEMORY_MEMSEARCH_URI` | `<base>/.memsearch/milvus.db` | Milvus-Lite db path (project-local). |
| `MEMORY_MEMSEARCH_TOKEN` | — | Token for remote Milvus/Zilliz Cloud (unused for Lite). |
| `MEMORY_MEMSEARCH_EMBED_PROVIDER` | `onnx` | memsearch embedding provider. |

## Fail-soft behavior

The subsystem never takes the server down:

- **Disabled** → health says disabled; search returns empty; chain `{{memory}}` is `""`;
  apps keep working.
- **memsearch unavailable** → health reports it; search falls back to plain (unless
  `MEMORY_REQUIRE_BACKEND=true`). The server still boots on the plain backend even if
  memsearch is not installed at all.
- **Writes are file-first** → a record is written to disk regardless of whether the index
  update succeeds.

## Memory Lab

The browser test bench at **`/memory-lab/`** (Tools → Memory Lab) exercises every
operation atomically and dumps raw JSON for each: health, write one, search, read by id,
reindex, and a **demo-fixtures** panel that seeds four controlled memories
(`test/memory_demo` scope) and runs four fixed queries showing expected-vs-actual. The
reset button only ever clears the demo scope.

## Testing atomically

Every behavior has an isolated test (`tests/test_memory_*.py`): store round-trip + path
safety, plain-adapter scoring/scoping/ordering, service write→read→search→delete, route
contracts, chain `{{memory}}` injection. The memsearch suite
(`tests/test_memory_memsearch.py`) is skipped unless `memsearch` is importable **and**
`MEMORY_MEMSEARCH_TEST=1` is set, so the normal suite never goes flaky or downloads a model.

```bash
.venv/bin/pytest tests/test_memory_*.py -q          # plain only
MEMORY_MEMSEARCH_TEST=1 .venv/bin/pytest tests/test_memory_memsearch.py -q
```

## What not to index

Keep retrieval separate from memory creation. Do **not** auto-extract memory from every
turn, dump raw transcripts, or index every job artifact. Write curated, durable facts
(manually, via the API, or via an app-curated summary). See [apps.md](apps.md).
