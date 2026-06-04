# Memory: app integration

Apps never know which backend is active — they call the local memory **service** and get a
stable result model. This page is the standard contract. (As of the first release no
production app writes memory automatically; this is the documented pattern to follow.)

## The contract

1. **Define scopes** for the app/entity/session.
2. **Search** the service with the user's message (or a derived query).
3. **Inject** a formatted block into the prompt via `format_memory_block`.
4. *(optionally)* **Write** curated memory — never dump raw transcripts.

```python
from app.memory import get_service, MemoryScope, MemorySearchRequest

svc = get_service()
resp = await svc.search(MemorySearchRequest(
    query=user_message,
    scopes=[
        MemoryScope(scope_type="app", scope_id="hoodat"),
        MemoryScope(scope_type="character", scope_id=character_id),
        MemoryScope(scope_type="session", scope_id=session_id),
    ],
    top_k=5,
))
memory_block = svc.format_memory_block(resp.results, max_chars=1200)
# → inject memory_block into your prompt (e.g. before the user turn)
```

`format_memory_block` produces a compact, deterministic, char-capped block:

```text
Relevant memories:

1. The lighthouse is north of the harbor
Scope: app/hoodat
Memory: The lighthouse is north of the harbor.
```

Writing curated memory:

```python
from app.memory import MemoryWriteRequest
record, path = await svc.write(MemoryWriteRequest(
    title="Player promised to return the amulet",
    body="During session 12 the player vowed to bring the amulet back to the temple.",
    scope=MemoryScope(scope_type="session", scope_id=session_id),
    tags=["promise", "plot"],
))
```

## Suggested scopes per app

### Hoodat
`app:hoodat`, `character:<character_id>`, `session:<session_id>`, `user:default`.
Use for character facts, important prior interactions, stable preferences, world facts.
Do **not** automatically remember every chat turn.

### Blaboratory
`app:blaboratory`, `resident:<resident_id>` (via `scope_type=custom`),
`experiment:<experiment_id>`. Use for resident history, notable outcomes, persistent
preferences, experiment discoveries. (Blaboratory's existing sqlite-vec sim memory is
separate; this subsystem is for curated, durable, file-first facts.)

### Prattletale
`app:prattletale`, `session:<session_id>`, `thread:<thread_id>` (via `scope_type=custom`).
Use for conversation summaries, recurring topics, prior decisions.

## Writing policy

Separate **retrieval** from **creation**. Initial write modes, in order of preference:

1. Manual write through Memory Lab.
2. Explicit API/service write.
3. Explicit chain `memory` step (see [chains.md](chains.md)) — retrieval today; a
   `write_memory` step is a documented future addition.
4. App-curated summary.

Avoid automatic background memory extraction until the primitives are stable. Never dump
raw transcripts or index every job artifact by default.
