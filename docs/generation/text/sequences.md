# Sequences

A sequence is a named, reusable list of chain steps (plus the variables that drive them). Once saved, a sequence can be loaded back into the Chain tab to run directly or referenced from another chain as a `sequence` step that expands inline at run time.

## Lifecycle

- **Create** — Sequences tab → **+ New**, fill in the name, add steps and variables in the Chain tab, click Save.
- **Edit** — click a sequence row to load it back into the editor.
- **Duplicate** — `POST /v1/chain-sequences/{id}/duplicate` (a Duplicate button in the row menu).
- **Delete** — `DELETE /v1/chain-sequences/{id}`.

## Storage

Sequences live in `config/chain_sequences/index.json` as [Cruddable envelopes](../../tools/packs.md). Each entry:

| Field | Description |
|-------|-------------|
| `schema_version` | Envelope format version — `1` |
| `type` | `"chain_sequence"` |
| `id` | Human-readable slug, unique within type; referenced by `sequence` steps' `sequence_id` |
| `name` | Display name |
| `description` / `tags` | Envelope meta |
| `created_at` / `updated_at` | ISO timestamps |
| `data.steps` | Array of v2 step objects (see [Chain](chain.md#anatomy-of-a-step)) |
| `data.variables` | Array of `{name, default, choices?}` declarations |
| `data.content_version` | Step-graph content version — `2` |

On save the server normalizes every step (assigns missing `number`s sequentially, hoists v1-shorthand keys onto a single alternative) before validating, so the stored shape is always clean v2.

A sequence is a [cruddable](../../management/cruddables.md): you can Export / Copy / Extend the whole collection and ship sequences in a [Pack](../../tools/packs.md). Applying a pack runs structural validation but skips capability validation, so a cross-machine sequence pack imports even when a named LLM preset is absent locally.

## Validation

Save-time checks (HTTP 422 on failure):

- Step `number`s are positive and unique within the sequence.
- Every alternative has `weight >= 1`.
- Every `goto` alternative has exactly one of `target_step` or `fall_through`, and any `target_step` references an existing step `number`.
- `requires` declared on any `llm` alternative is satisfied by the chosen (or default) [LLM preset](../../tools/llm-presets.md).
- `check_for_cycles()` runs a DFS over `type=sequence` references between top-level sequences; A→B→A cycles are rejected.

A runtime depth guard of 20 catches anything that slipped past save-time (e.g., a sequence that became cyclical after another sequence was edited).

## Expansion

When the executor encounters a `sequence` step, `_expand_steps()` replaces it with the referenced sequence's steps before the run begins. Step names get a `<sequence name> > ` prefix and inner step numbers are renumbered with an offset of `outer_number * 1000` so they sort after the host step. Inner gotos that point at inner numbers are rewritten in the same scheme.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/chain-sequences` | List |
| POST | `/v1/chain-sequences` | Upsert by name; body: `{name, steps, variables?}` |
| POST | `/v1/chain-sequences/{id}/duplicate` | Copy with `(copy)` suffix |
| DELETE | `/v1/chain-sequences/{id}` | Remove |

See [Chain](chain.md) for the structure of the `steps` array, the alternatives model, and template variables.
