# Cruddables (Manage)

The **Cruddables** page (Manage → Cruddables) is the operator surface for the unified
envelope format: per-type **Export**, **Copy JSON**, and **Extend**. It is the
import/export half of the [Packs](../tools/packs.md) feature — pasting a pack's `items`
array into Extend is exactly the same as applying that pack.

See [docs/tools/packs.md](../tools/packs.md) for the envelope schema and per-type `data`.

## What you can do

Each registered cruddable type gets a panel showing its label and current item count:

- **Export JSON** — downloads the type's whole collection as an envelope array
  (`GET /v1/cruddables/{type}/export`).
- **Copy JSON** — same array, to the clipboard (paste into ChatGPT to generate more).
- **Extend** — paste (or upload) an envelope array and upsert each item by `id`
  (`POST /v1/cruddables/{type}/extend`). Created vs updated vs errored is reported inline.

Each item is routed by its own `type` field; the panel you use is a **guard** — an item
whose `type` doesn't match the panel is reported as an error rather than written. One bad
item never aborts the rest of the batch.

## Round-trip / single source of truth

Because the on-disk shape is the envelope, Export → edit → Extend is lossless:

1. Export `wildcard` → a JSON array.
2. Edit the array (or generate new entries with an LLM).
3. Extend `wildcard` with it → each envelope is upserted by `id`; unchanged ones stay,
   edited ones overwrite, new ones are added.

## API (`/v1/cruddables`)

| method | path | purpose |
|---|---|---|
| GET | `/v1/cruddables/types` | `{types:[{type,label,count}]}` |
| GET | `/v1/cruddables/{type}/export` | envelope array for the type |
| POST | `/v1/cruddables/{type}/extend` | upsert array → `{created,updated,errored,results}` |

## In-scope types

`wildcard`, `context_item`, `image_prompt`, `chain_sequence`, `prompt_pal`, and
`hoodat_character` are all live. Tickets, voice presets, and LLM presets/endpoints are
out of scope.
