# Sequences

A sequence is a named, reusable list of chain steps. Sequences let you reach for "Summarize → Speak" or "Critique → Rewrite → Save" without re-typing the steps every time. Once saved, a sequence can be used in two ways: load it directly into the Chain tab, or reference it from another chain as a `sequence` step that expands inline at run time.

## Lifecycle

- **Create** — Sequences tab → **+ New**, fill in the name, add steps in the same form used on the Chain tab, click Save.
- **Edit** — click a sequence row to load it back into the editor.
- **Duplicate** — `POST /v1/chain-sequences/{id}/duplicate` (a Duplicate button in the row menu).
- **Delete** — `DELETE /v1/chain-sequences/{id}`.

## Storage

Sequences live in `config/chain_sequences/index.json`. Each entry: `id`, `name`, `steps` (the same step objects you'd inline in a chain), `created_at`, `updated_at`.

## Expansion

When the executor encounters a `sequence` step, `_expand_steps()` replaces it with the referenced sequence's steps before the run begins. Step names get a `<sequence name> > ` prefix so you can tell where they came from in `status.json`. Inline expansion happens recursively — a sequence may reference other sequences.

## Cycle detection

`check_for_cycles()` runs a DFS at save time. If sequence A references B and B references A (directly or through a longer chain), the save returns `422 Unprocessable Entity`. A runtime depth guard of 20 catches anything that slipped past save-time validation (e.g., a sequence that became cyclical after another sequence was edited).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/chain-sequences` | List |
| POST | `/v1/chain-sequences` | Create or update (id-bearing payload upserts) |
| POST | `/v1/chain-sequences/{id}/duplicate` | Copy with a new id |
| DELETE | `/v1/chain-sequences/{id}` | Remove |

See [Chain](chain.md#step-types) for the structure of the `steps` array.
