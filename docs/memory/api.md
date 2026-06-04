# Memory API

All routes are under `/v1/memory`. Responses are JSON. The subsystem fails soft — a
disabled subsystem returns clear empty/flagged responses rather than errors.

## `GET /v1/memory/health`

```bash
curl -s localhost:8090/v1/memory/health
```
```json
{
  "enabled": true,
  "backend": "plain",
  "store_path": "/opt/ai-stack/.../config/memory",
  "index_available": true,
  "message": "Plain keyword backend is ready (no external services required)."
}
```

## `GET /v1/memory/scopes`

Lists the known scope types and the scopes currently present on disk (with counts).

```bash
curl -s localhost:8090/v1/memory/scopes
```
```json
{
  "scope_types": ["global","app","project","user","session","character","custom","test"],
  "scopes": [{"scope_type": "project", "scope_id": "ai-job-server", "count": 3}]
}
```

## `POST /v1/memory/write`

Atomically writes one memory to Markdown.

```bash
curl -s localhost:8090/v1/memory/write -H 'Content-Type: application/json' -d '{
  "title": "User prefers atomic UI tests",
  "body": "The user wants new utilities to include small UI test panels.",
  "scope": {"scope_type": "project", "scope_id": "ai-job-server"},
  "tags": ["testing", "architecture"],
  "source_type": "manual"
}'
```
```json
{ "ok": true, "memory_id": "mem_20260604_153012_a1b2c3",
  "path": ".../config/memory/projects/ai-job-server/mem_20260604_153012_a1b2c3.md" }
```

## `POST /v1/memory/search`

```bash
curl -s localhost:8090/v1/memory/search -H 'Content-Type: application/json' -d '{
  "query": "How should we test new utilities?",
  "scopes": [{"scope_type": "project", "scope_id": "ai-job-server"}],
  "top_k": 5
}'
```
```json
{
  "ok": true, "enabled": true, "backend": "plain",
  "query": "How should we test new utilities?",
  "scopes": [{"scope_type": "project", "scope_id": "ai-job-server"}],
  "top_k": 5, "count": 1,
  "results": [{
    "memory_id": "mem_...", "title": "User prefers atomic UI tests",
    "score": 0.6, "path": ".../mem_....md",
    "snippet": "The user wants new utilities to include small UI test panels.",
    "metadata": {"scope_type": "project", "scope_id": "ai-job-server", "tags": ["testing","architecture"]}
  }]
}
```

The response echoes `backend`, `query`, `scopes`, `top_k`, and `count` so any query is
self-documenting for debugging. An empty `scopes` searches all scopes. `top_k` defaults to
`MEMORY_TOP_K_DEFAULT`.

## `GET /v1/memory/read/{memory_id}`

```bash
curl -s localhost:8090/v1/memory/read/mem_20260604_153012_a1b2c3
```
```json
{ "ok": true, "memory": { "id": "mem_...", "title": "...", "body": "...", "metadata": { } } }
```
`404` if the id is unknown; `400` if the id is unsafe (path traversal).

## `POST /v1/memory/update/{memory_id}`

Partial update — only provided fields change (`title`, `body`, `tags`, `status`,
`importance`, `source_type`, `source_ref`, `visibility`). Bumps `updated_at`.

```bash
curl -s localhost:8090/v1/memory/update/mem_... -H 'Content-Type: application/json' \
  -d '{"body": "Revised fact."}'
```

## `POST /v1/memory/delete/{memory_id}`

**Soft delete**: sets `status: deleted` (the file stays on disk) and drops the record from
the search index. Soft-deleted records are excluded from search.

```bash
curl -s localhost:8090/v1/memory/delete/mem_...
```
```json
{ "ok": true, "memory_id": "mem_...", "status": "deleted" }
```

## `POST /v1/memory/reindex`

Rebuilds the search index from the Markdown source files. A no-op for the plain backend.

```bash
curl -s localhost:8090/v1/memory/reindex -H 'Content-Type: application/json' \
  -d '{"scopes": [{"scope_type":"project","scope_id":"ai-job-server"}], "force": true}'
```
```json
{ "ok": true, "backend": "memsearch", "indexed_files": 12, "skipped_files": 0 }
```

## Dev/test helpers (confined to `test/memory_demo`)

These only ever touch the dedicated `test/memory_demo` scope — they can never wipe real
app memory.

- `POST /v1/memory/test/seed-demo` — writes the four demo memories.
- `POST /v1/memory/test/run-demo-searches` — runs four fixed queries, returns
  expected-vs-actual per query.
- `POST /v1/memory/test/reset` — hard-deletes every file in the demo scope.

```bash
curl -s localhost:8090/v1/memory/test/seed-demo -X POST
curl -s localhost:8090/v1/memory/test/run-demo-searches -X POST
curl -s localhost:8090/v1/memory/test/reset -X POST
```
