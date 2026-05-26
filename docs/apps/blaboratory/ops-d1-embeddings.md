# Blaboratory D1 — Embeddings ops & deploy checklist

Operator notes for the D1 vector-retrieval system (hybrid memory/lore retrieval).
Plan of record: [`d1-vector-build-plan.md`](./d1-vector-build-plan.md); what landed:
[`design.md` → "D1 — Build notes"](./design.md#d1--vector-memory--lore-retrieval--build-notes).

## Topology recap (where each piece runs)

```
WEB NODE (debian2)                          LLM NODE (gpu.local)
 ├─ FastAPI app (sim, ticks, db)             ├─ FastAPI app (same artifact, llm capability)
 ├─ blaboratory.db + sqlite-vec  ◀── KNN     │   ├─ llama-server :8080 chat  (app-managed)
 └─ embed client ─ POST /v1/embeddings ──────┤   └─ llama-server :8081 embed (app-managed)
                                             └─ control: /v1/llamacpp-embed/*
```

- The **index + KNN run only on the web node** (where `blaboratory.db` lives). sqlite-vec is a
  loadable extension on that one connection.
- **Embeddings are computed on the `llm` node** by a second, app-managed `llama-server`. The embed
  host follows the `llm` peer (`find_peer_for_capability("llm")`); only the port differs (8081).
- Same app artifact on both nodes — build on primary, **commit, deploy to the secondary**, and the
  secondary runs the embedder.

## Deploy checklist

1. **Dependency** — `sqlite-vec==0.1.9` is in `requirements.txt`; the deploy `pip install -r` puts it
   on both nodes. (Index/KNN only exercise it on the web node, but installing it everywhere is
   harmless.)
2. **Embed model file on the secondary (`llm` node).** Put the GGUF at
   `/opt/ai-stack/models/bge-small-en-v1.5-f16.gguf` (67 MB, HF
   `CompendiumLabs/bge-small-en-v1.5-gguf`). The embed server is app-managed, so this file is the only
   manual artifact.
3. **Config carries the embed fields.** On the `llm` node, `config/llamacpp.json` must set:
   ```json
   {
     "embed_port": 8081,
     "embed_model_path": "/opt/ai-stack/models/bge-small-en-v1.5-f16.gguf",
     "embed_pooling": "cls"
   }
   ```
   With `embed_model_path` unset the embed server **stays down** (lifespan logs and skips) — the sim
   degrades to mechanical recency. `--pooling cls` is correct for bge (verified on `LLAMA_CPP_TAG`
   b9204); wrong pooling silently degrades similarity.
4. **Reachability.** The web node must reach `gpu.local:8081` (it already resolves `:8090`/`:8080`).
5. **Lifespan does the rest.** On the `llm` node the embed manager adopts an already-running server or
   starts one at boot; it's stopped on shutdown. No hand-maintained systemd unit (the app already runs
   under `ai-job-server.service`).
6. **Web-node config (optional).** `config/blaboratory/embeddings.json` (auto-created with defaults)
   holds `port`/`model`/`dim`/`query_prefix`. Only edit it to change the port or query prefix.

Standard deploy flow (bare repo → pull → restart → verify `git_sha` parity) is unchanged — see
[`../../multi-machine.md`](../../multi-machine.md).

## Verify (real end-to-end)

- **Embed server up:** on the `llm` node,
  `curl localhost:8081/v1/embeddings -d '{"input":"hi","model":"bge-small"}'` → a **384-length**
  embedding. Or `GET /v1/llamacpp-embed/status` → `{"running": true, ...}`.
- **Recall surfaces relevance:** fire ticks; seed a distinctive earlier chat, then a related moment
  many ticks later. `GET /residents/{id}/context` should show the older-but-relevant memory back in
  `[You Know]` (it would have fallen out under pure recency).
- **Graceful degrade:** stop the embed server (`POST /v1/llamacpp-embed/stop`) and keep firing ticks —
  the sim keeps running, retrieval falls back to mechanical recency, and `index_pending`/retrieval log
  the degrade **once** (no per-tick spam).

## ⚠️ Re-index on embedder change (LOUD)

The `vec_memories` vtable hard-codes **`float[384]`** for bge-small. Switching to an embedder with a
**different dimension is incompatible** with the existing table — there is no automatic migration.
To change embedders:

1. `DROP TABLE vec_memories;`
2. `DELETE FROM vec_rowmap;`
3. Recreate the vtable at the new dimension (edit `_migration_2` in `db.py` or run the DDL manually).
4. Re-run `memory_index.index_pending()` (it backfills every row from scratch).

A same-dimension model swap (e.g. another 384-dim model) doesn't *require* a rebuild, but similarity
won't be comparable across mixed vectors — prefer a clean re-index there too.
