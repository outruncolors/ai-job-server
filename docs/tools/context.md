# Context

The Context Library is a small CMS for reusable text blocks. An item can be dropped into any prompt inline as `{{ctx.name}}` (by slug or name), and chain LLM steps can additionally splice a bundle of items as `{{context}}`.

## What's on the page

- **Left** — list of all items with title, description, tags
- **Right** — edit form: Title, Tags (comma-separated), Description, Content
- **+ New** / **Save** / **Cancel** / **Delete**

## Data model

Stored in `config/context_items/index.json` as [Cruddable envelopes](../management/cruddables.md):

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | int | envelope format version (`1`) |
| `type` | string | `"context_item"` |
| `id` | slug | human-readable, unique within type; chain steps reference items by this id (`context_ids`) |
| `name` | string | display title (the UI/API "Title" field maps here) |
| `description` | string | optional |
| `tags` | string[] | free-form |
| `data.content` | string | the text injected into prompts |
| `created_at`, `updated_at` | ISO 8601 | |

A context item is a [cruddable](../management/cruddables.md): Export / Copy / Extend the library, or ship reusable blocks in a [Pack](packs.md).

## How it's used

**Inline, anywhere** — write `{{ctx.name}}` in any prompt field (by the item's slug `id` or its name, case-insensitive). The unified resolver (`app/prompt_template.py`) substitutes the item's full `content`, re-scanning it for any further tokens. An unknown name falls back to the literal string (e.g. `{{ctx.missing}}` → `missing`).

**As a bundle (`{{context}}`)** — in a chain `llm` step, populate `context_ids` with one or more item ids. At run time `resolve_context_ids()` fetches each item's `content` and joins them with `\n\n---\n\n`; the result is what `{{context}}` resolves to.

If a step references contexts but the prompt doesn't use `{{context}}`, the resolved text is still prepended to the final prompt wrapped in `<START CONTEXT>...<END CONTEXT>` markers — the LLM sees it either way.

A `write_context` step is the inverse: it persists the chain's current `text_output` back into the library, optionally appending or overwriting an item with the same name. This lets a chain feed its own future runs.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/context-items` | List |
| POST | `/v1/context-items` | Create |
| GET | `/v1/context-items/{id}` | Fetch one |
| PUT | `/v1/context-items/{id}` | Update |
| DELETE | `/v1/context-items/{id}` | Remove |
