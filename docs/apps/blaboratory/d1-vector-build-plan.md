# Blaboratory D1 — Vector Memory & Lore Retrieval — Build Plan

> Phased sequencing for the **deferred D1 system** from
> [`part2-build-plan.md`](./part2-build-plan.md#deferred-noted-not-detailed) and
> [`design.md`](./design.md) §"Lore + memory retrieval (vector)". Replaces Phase 3's **mechanical
> recency** `[You Know]` gather with **relevance retrieval** over an embedding index, while keeping
> recency as a floor (hybrid). One index serves both resident **memory** and shared **lore**.
>
> Same conventions as the Part 2 plan: `.venv/bin/python`, `.venv/bin/pytest` (`asyncio_mode=auto`),
> `py_compile` for syntax checks; stores write under `config/` (gitignored); tests monkeypatch
> module-level `*_PATH`/`DB_PATH` constants to tmp. **One new pip dependency** (`sqlite-vec`) — this
> is the explicitly-sanctioned exception to Part 2's stdlib-only rule.

## Decisions locked (this session)

| Decision | Choice | Consequence |
|----------|--------|-------------|
| Embedder host | **Second `llama-server` on the LLM node (gpu.local), managed by the app** — mirrors `LlamaCppManager` | No model-swap thrash; chat (8080) + embed (8081) both live. Controlled through the app's routes/UI, not a hand-rolled unit. Extra ~130MB VRAM. |
| Embedding model | **bge-small-en-v1.5**, **384-dim** | Vector dimension `384` is **baked into the schema**. Changing the model later = re-index (drop + rebuild the vec table). |
| Retrieval mix | **Hybrid** — recent N (verbatim) ∪ top-k by similarity, merged + capped | A just-happened event can never fall out of context for being "irrelevant". |
| Index scope | Resident **memory now**; schema **ready for lore** (D2) | `kind` + `resident_id` columns scope rows; lore rows are global (`resident_id IS NULL`). |
| Query construction | The resident's **recent consumed items** (recency window) embedded as the query | Self-contained; works for both decision ticks and call turns. Tunable. |
| Indexing trigger | **Batch backfill of un-indexed rows** once per tick, before the gather | Idempotent, resilient; no embed calls threaded through every write site. |

---

## Topology (where each piece runs)

```
WEB NODE (debian2)                          LLM NODE (gpu.local)
 ├─ FastAPI app  (the sim, ticks, db)        ├─ FastAPI app (same artifact, llm capability)
 ├─ blaboratory.db  +  sqlite-vec  ◀── KNN   │   ├─ llama-server :8080 chat  (app-managed)
 └─ embed client ─ POST /v1/embeddings ──────┤   └─ llama-server :8081 embed (app-managed — NEW)
                                             └─ control: /v1/llamacpp-embed/* (start/stop/status/config)
```

- **Same app on both nodes.** The embedder is a *second* `llama-server` **owned by the app** on
  `llm`-capable nodes — a sibling of `LlamaCppManager` (start/adopt/`/health`/ring-buffer/`killpg`),
  started at lifespan, configured + controlled through new routes (and surfaced in the Server → LLM
  UI). Build it on primary, **commit, deploy to secondary**, and the secondary runs the embedder.
  No hand-maintained systemd unit (the app already runs under `ai-job-server.service`).
- The **vector index lives in the same `blaboratory.db`** on the web node (sqlite-vec is a loadable
  extension on that one connection). KNN runs locally on the web node.
- **Embeddings are computed remotely** on the LLM node and fetched over HTTP — exactly the existing
  chat pattern (`llm_swap.resolve_llm_server_url`), just a different port + endpoint.

---

## Operator prerequisites (what *you* set up before/while we build)

These are environment changes the code can't do for itself. None block writing the code; they block
*running* it end-to-end.

### A. On the **LLM node** (gpu.local) — the embed model file

The embed *server* is started and managed by the app (see Phase D1.2x below), so the only manual step
is providing the model:

1. **Get the GGUF.** Download a bge-small-en-v1.5 GGUF (f16 is fine, ~130MB) into
   `/opt/ai-stack/models/`, e.g. `bge-small-en-v1.5-f16.gguf`
   (HF: `CompendiumLabs/bge-small-en-v1.5-gguf` or `ChristianAzinn/bge-small-en-v1.5-gguf`).
2. **Reachability:** the web node must reach `gpu.local:8081`. (gpu.local already resolves from the
   server session for :8090/:8080.)

That's it — no hand-rolled unit; the app spawns `llama-server --embeddings --pooling cls --port 8081`
itself at lifespan, the same way it owns the chat server today.

### B. On the **web node** (debian2) — the extension  ✅ DONE

1. ✅ `sqlite-vec==0.1.9` installed into `.venv` and added to `requirements.txt`.
2. ✅ Verified end-to-end on this host (sqlite 3.46.1): `enable_load_extension` present;
   `sqlite_vec.load()` + `vec0` vtable + KNN + in-`MATCH` metadata filtering all work.
   **No `pysqlite3-binary` fallback needed.**

(Deploying to the secondary will install the same pinned dep via `requirements.txt`, but note: the
**index + KNN only run on the web node**, where `blaboratory.db` lives — the secondary just serves
embeddings.)

### C. Config the app will provide

- A small `config/blaboratory/embeddings.json` (`{"port": 8081, "model": "bge-small", "dim": 384,
  "query_prefix": "Represent this sentence for searching relevant passages: "}`) so the
  dimension/prefix live in one place; the **host follows the existing `llm` peer** via
  `find_peer_for_capability("llm")` (no separate host config).

---

## How we use it (retrieval design)

**Corpus (what gets embedded).** One row per memory-bearing item, embedded once and stored in the vec
index with scoping metadata:
- `events` — action summaries (`payload.summary`), scoped to `resident_id`.
- `chat` — each message, embedded once; **retrieval** is scoped by the reader's chat cursor (only
  rows with `chat.id <= cursor` are eligible), preserving *visibility = consumption*.
- `utterances` — call lines, scoped to the rooms/participants.
- `lore` (D2, later) — global rows (`resident_id IS NULL`), eligible for everyone.

**The `text` we embed** is a short rendered line (the same shape `gather_memories` already builds,
e.g. `"[tick 4] you checked the computer: ..."`), so indexed text matches what the model would read.

**Query (per build_context call).** Embed the resident's **recency window** — the most recent K
consumed items joined — as the query vector ("what's on my mind right now"). This retrieves *older*
semantically-related memories beyond the recency floor. (Document/query asymmetry: bge prepends the
query instruction prefix to the query only; stored docs are embedded raw.)

**Hybrid merge (the `[You Know]` section).**
1. `recent = most-recent N consumed items` (verbatim, newest-first) — the floor.
2. `relevant = top-k by cosine similarity` to the query, **excluding** anything already in `recent`,
   filtered to this resident's eligible scope (own events + chat≤cursor + their utterances + lore).
3. `you_know = recent ++ relevant`, then `apply_caps` (existing item/char caps) — recent wins ties.

**Indexing trigger.** At the top of `run_tick` (and before any `build_context`), call
`index_pending()` — a batched embed of all rows that don't yet have a vector (LEFT-JOIN the source
tables against a `vec_rowmap`). Idempotent, catches chat authored by others, backfills after outages,
and keeps embed calls **out** of the synchronous `write_phase`.

**Fallback.** If the embed server is unreachable, retrieval degrades to **pure recency** (today's
behavior) and logs once — the sim never blocks on the index. This mirrors the "no silent failure,
but never hard-stop the sim" stance already in `tick_runner`.

---

## Schema (Phase 1 migration)

`MIGRATIONS[1]` (`user_version` 1 → 2), guarded so it's a no-op if the extension is unavailable
(retrieval then stays mechanical):

```sql
-- the vector store (vec0 virtual table; dim is fixed at 384 for bge-small)
CREATE VIRTUAL TABLE vec_memories USING vec0(
  embedding   float[384],
  resident_id text,        -- NULL = global (lore); else the owning resident
  kind        text,        -- 'event' | 'chat' | 'utterance' | 'lore'
  ref_id      integer,     -- source row id in its table
  tick        integer
);
-- maps an indexed source row → its vec_memories rowid (dedupe / "is it indexed?")
CREATE TABLE vec_rowmap (
  kind   text NOT NULL,
  ref_id integer NOT NULL,
  vec_id integer NOT NULL,
  PRIMARY KEY (kind, ref_id)
);
```

`db.get_connection()` gains: `conn.enable_load_extension(True); sqlite_vec.load(conn)` wrapped in a
try/except that sets a module flag `VEC_AVAILABLE` (False → migration 2 skips the vtable, retrieval
falls back). Vectors are written with `sqlite_vec.serialize_float32(list[float])`. KNN reads:
`SELECT ref_id, kind, distance FROM vec_memories WHERE embedding MATCH ? AND k = ? AND <scope filter>`.

---

## Phases (dependency-ordered; one phase per session)

> Paste-able session-starter prompts for each phase live in
> **[`d1-prompts/`](./d1-prompts/README.md)** (cross-linked, one file per phase).

### Phase D1.1 — Extension load + schema + `VectorIndex` helper
**Goal:** sqlite-vec loads on the shared connection; migration 2 adds the vtable + rowmap; a thin
`vector_index.py` (`add(rows)`, `query(vec, k, *, resident_id, kinds, max_chat_id)`,
`is_available()`). No embeddings yet (tests use hand-built float vectors).
**Read:** `db.py` (connection + migration pattern), `event_store.py` (query-helper shape to mirror).
**Build:** `db.py` extension-load + `VEC_AVAILABLE` flag + `_migration_2`; `vector_index.py`.
**Done when:** `tests/apps/test_vector_index.py` passes (monkeypatched tmp `DB_PATH`): migrate lands
at `user_version=2`; add 3 vectors, KNN returns nearest-first; scope filters (`resident_id`, `kind`,
`max_chat_id`) exclude correctly; with the extension forced unavailable, migration 2 skips and
`is_available()` is False. **Touches:** `db.py` (migration — additive), new module.

### Phase D1.2a — App-managed embed `llama-server` (LLM node) + control routes
**Goal:** a second, always-on `llama-server` owned by the app on `llm`-capable nodes, serving
`/v1/embeddings` on port 8081 — the sibling of the chat `LlamaCppManager`. Configured + controlled
through the app (committed, deployed to secondary, which then runs it).
**Read:** `llamacpp/manager.py` (entire — adopt/start/`/health`/ring-buffer/`_terminate`/`killpg` to
mirror), `llamacpp/config.py`, `llamacpp/router.py` (route shape), `app/main.py` lifespan (where the
chat manager starts/adopts; gate on `"llm" in get_local_capabilities()`).
**Build:** `app/llamacpp/embed_manager.py` (`LlamaCppEmbedManager` — fixed embed preset:
`--embeddings --pooling cls --port {embed_port} --ctx-size 512 -ngl 99`, adopt-if-running, 180s
readiness via `/health`); `embed` fields in `llamacpp/config.py` (or a dedicated
`llamacpp_embed.json`): `embed_port`, `embed_model_path`, `embed_pooling`; routes
`/v1/llamacpp-embed/{status,start,stop,restart,logs}`; lifespan start/adopt on llm nodes; a small
Server → LLM UI affordance (status + start/stop) optional in D1.5.
**Done when:** `tests/test_embed_manager.py` passes (subprocess + httpx mocked like the existing
llama.cpp manager tests): start spawns the embed argv on the embed port; adopt picks up a running
server; readiness times out → clear error + cleared state; routes return status. On the real LLM node
(manual): `curl localhost:8081/v1/embeddings -d '{"input":"hi","model":"bge-small"}'` → 384-vector.
**Touches:** new manager + routes; `llamacpp/config.py` (additive fields); `app/main.py` lifespan
(additive, capability-gated).

### Phase D1.2b — `embed()` client + embedding config + remote wiring (web node)
**Goal:** an async `embed(texts, *, is_query) -> list[list[float]]` on `OpenAICompatibleLLMClient`
hitting the embed server's `/v1/embeddings`; an `embeddings.py` config (port/model/dim/query_prefix)
+ URL resolution reusing `find_peer_for_capability("llm")` (host) + the embed port.
**Read:** `chain/llm_client.py` (httpx error mapping to mirror), `chain/llm_swap.py`
(`resolve_llm_server_url` peer-discovery pattern), Phase D1.2a config.
**Build:** `client.embed()`; `app/apps/blaboratory/embeddings.py` (config + `embed_url()` +
`embed_texts()` applying the query prefix). Batch input; map errors to a clear `EmbedError`.
**Done when:** `tests/apps/test_embeddings.py` passes (httpx transport mock): batches N texts → N
vectors of `dim`; query prefix applied only when `is_query=True`; connect/timeout → `EmbedError`.
**Touches:** `chain/llm_client.py` (additive method), new config module.

### Phase D1.3 — Indexing pipeline (`index_pending` batch backfill)
**Goal:** embed-and-store all un-indexed `events`/`chat`/`utterances` rows in one batched pass;
idempotent via `vec_rowmap`.
**Read:** Phases D1.1–D1.2; `context_pipeline.gather_memories` (the text-rendering shape to reuse so
indexed text == read text).
**Build:** `memory_index.py`: `render_indexable(row, kind) -> text`; `index_pending(*, limit=…)` —
find un-indexed rows, embed in batches, `VectorIndex.add`. Degrades to no-op (logged once) if
`embeddings` unreachable or `not VEC_AVAILABLE`.
**Done when:** `tests/apps/test_memory_index.py` (patched embed): seed events+chat → `index_pending`
indexes each once; a second call is a no-op; an embed outage leaves rows un-indexed without raising.
**Touches:** new module.

### Phase D1.4 — Hybrid retrieval at the `[You Know]` swap point
**Goal:** rewrite `gather_memories` (or a new `retrieve_memories`) to the hybrid recent∪relevant
merge; wire `index_pending()` into `run_tick`'s top; keep mechanical recency as the fallback.
**Read:** `context_pipeline.py` (current gather/caps + `build_context`), `tick_runner.run_tick`.
**Build:** `context_pipeline`: `_build_query(resident)` (recency-window text), `retrieve_memories()`
(recent floor + KNN-scoped relevant, deduped), keep `apply_caps`. `tick_runner.run_tick`: call
`memory_index.index_pending()` once before the occupant loop.
**Done when:** `tests/apps/test_context_pipeline.py` extended: with a fake index, `[You Know]`
contains the recent floor **and** a relevant older item that recency alone would have dropped;
de-dupe holds; caps still enforced; **with the index unavailable, output is byte-identical to today's
mechanical gather** (regression guard).
**Touches:** `context_pipeline.py`, `tick_runner.py` (one call).

### Phase D1.5 — Ops, docs, polish
**Goal:** deploy notes (the embed model file on the secondary + `llm`-node embed-server start at
boot); a new `docs/apps/blaboratory/` ops note; design.md "what landed/drifted"; optional Server → LLM
UI tile for embed-server status/start-stop. (`requirements.txt` += sqlite-vec is already done.)
`GET /residents/{id}/context` already surfaces the assembled block, so retrieval is inspectable in the
timeline UI with no new endpoint.
**Done when:** full suite green (`.venv/bin/pytest -q`); manual: fire ticks and confirm a resident
recalls an older-but-relevant memory (e.g., seed a distinctive earlier chat, then a related moment
many ticks later, and see it resurface in `/residents/{id}/context`).

---

## Dependency graph

```
D1.1 schema+index ─────────┬─▶ D1.3 indexing ──▶ D1.4 hybrid retrieval ──▶ D1.5 ops/docs
D1.2a embed server ─▶ D1.2b embed client ─┘
```

D1.1 is independent. D1.2b needs D1.2a (or a mocked endpoint). D1.3 needs D1.1 + D1.2b. D1.4 is the
payoff. The embed server (D1.2a) is the piece that must be **committed and deployed to the secondary**
before real (non-mocked) end-to-end runs.

## Risks & open questions

- **Extension loading** — ✅ resolved: verified working on the web node (sqlite 3.46.1,
  `enable_load_extension` present, `vec0` + in-`MATCH` filtering all functional). No `pysqlite3`
  fallback. The `VEC_AVAILABLE` guard stays anyway, so a node without the extension degrades to
  mechanical recency instead of crashing.
- **Pooling/prefix correctness** — bge wants CLS pooling + a query-only instruction prefix; wrong
  settings silently degrade similarity. D1.2 done-when should eyeball that "cat" ~ "kitten" >
  "cat" ~ "tax return".
- **Re-index on model change** — the 384-dim schema is model-specific. Switching embedders = `DROP`
  the vtable + clear `vec_rowmap` + re-`index_pending`. Note this loudly in D1.5.
- **`[Some Know]` + lore** — still empty/deferred (D2). The schema carries `kind='lore'`/global rows
  so D2 slots in without another migration.
- **Query definition** is the main tuning knob — recency-window-as-query is a sane default but worth
  revisiting once we can watch recalls in the timeline.
