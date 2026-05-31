---
name: add-pack
description: Author a Pack file (a curated bundle of Cruddable envelopes) from a one-line description of the cruddable type plus a theme. Use when the user types /add-pack <type> <theme>, e.g. "/add-pack wildcard A collection of sixteen different colors".
---

# /add-pack — author a Pack of cruddables

A **Pack** is a JSON file bundling fully-formed Cruddable "envelopes" so they can be
browsed on the Packs page and applied (each item written to its store, overwriting any
item with the same id). This skill turns `/add-pack <type> <theme>` into a valid pack file
on disk.

## Input

`$ARGUMENTS` is `<type> <theme>`. The **first whitespace-delimited token** is the cruddable
type; **the rest** is the free-text theme.

Example: `/add-pack wildcard A collection of sixteen different colors`
→ type = `wildcard`, theme = `A collection of sixteen different colors`.

### Type aliases (normalize to the canonical type)

| canonical | accepts |
|---|---|
| `wildcard` | wildcard, wildcards, wc |
| `context_item` | context_item, context, context-item, ctx |
| `image_prompt` | image_prompt, image-prompt, imageprompt, prompt-image |
| `chain_sequence` | chain_sequence, sequence, chain-sequence, seq |
| `prompt_pal` | prompt_pal, prompt-pal, promptpal, pp |
| `hoodat_character` | hoodat_character, character, hoodat, char |

If the type is unrecognized, stop and tell the user the valid types.

## Steps

1. **Parse** type (normalize via the alias table) and theme.
2. **`pack_id`** = slugify(theme): lowercase, replace any run of non-alphanumerics with a
   single `_`, trim leading/trailing `_`. (e.g. "A collection of sixteen different colors"
   → `a_collection_of_sixteen_different_colors`). If that is unwieldy, you may pick a
   shorter sensible slug — but it must be lowercase underscore-separated.
3. **Generate the items.** Decide a reasonable count from the theme (honor an explicit
   number like "sixteen"). For each item build an envelope:
   - `schema_version`: `1`
   - `type`: the canonical type
   - `id`: `<slugify(item-name)>_pack_<pack_id>` — **must** end with `_pack_<pack_id>`
   - `name`: human-readable item name
   - `description`: short, optional
   - `tags`: `["Pack", "<short-theme-tag>"]` — always include the literal `"Pack"`
   - `created_at` / `updated_at`: omit (the store stamps them) **or** an ISO-8601 string
   - `data`: the **type-specific payload** (see schemas below) — this is the only part that
     differs per type.
4. **Write** the pack file to `packs/<type>/<pack_id>.json` with this shape:
   ```json
   { "id": "<pack_id>", "name": "<Title Case Theme>", "description": "<one line>",
     "tags": ["Pack", "<theme-tag>"], "items": [ /* envelopes */ ] }
   ```
   Create the `packs/<type>/` directory if missing. (Repo `packs/` is tracked; the user can
   also drop packs under `config/packs/<type>/` which shadow repo packs by id.)
5. **Validate** the items before declaring success. Either:
   - Preferred: POST the `items` array to the running server:
     `curl -s -X POST localhost:8090/v1/cruddables/<type>/extend -H 'content-type: application/json' -d @<(jq .items packs/<type>/<pack_id>.json)`
     and confirm `errored == 0`. **Note this writes to the live stores** — only do it if the
     user is OK applying it, otherwise skip and rely on the model check below.
   - Offline: validate each item parses as the `Cruddable` model:
     `.venv/bin/python -c "import json,sys; from app.cruddables.envelope import Cruddable; [Cruddable(**i) for i in json.load(open('packs/<type>/<pack_id>.json'))['items']]; print('OK')"`
6. **Report**: the `pack_id`, item count, file path, and the URL `/packs/` (filter by the
   type to find it). Mention that applying it from the Packs page upserts the items by id.

## Per-type `data` payloads

- **wildcard** → `{ "entries": [ {"text": "red"}, {"text": "blue", "weight": 2} ] }`
  (`weight` optional, integer ≥ 1). The wildcard is referenced elsewhere by its **name** via
  `%%name%%`, so pick a clear `name`.
- **context_item** → `{ "content": "<the context text>" }`. Use `tags`/`description` for
  metadata; the body text goes in `data.content`.
- **image_prompt** → `{ "prompt": "<positive prompt text>", "workflow": "<workflow.json or null>" }`.
- **chain_sequence** → `{ "steps": [ <ChainStep> … ], "variables": [ <SequenceVariable> … ] }`.
  A minimal step: `{ "number": 1, "type": "llm", "visit_cap": 100, "alternatives": [ { "weight": 1, "prompt": "…", "fall_through": true } ] }`.
  v1 shorthand (flat `prompt`/`tools`/`preset` on the step, no `alternatives`) is also accepted
  and hoisted into one alternative. Step types: `llm`, `voice`, `write_context`, `sequence`,
  `image_prompt`, `save_wildcard`, `create_ticket`, `goto`. Keep self-contained — don't
  reference sequences/contexts/presets that won't exist on the target machine (apply skips
  capability validation but structural validation still runs: unique `number`, `weight` ≥ 1,
  goto targets must exist).
- **prompt_pal** → `{ "app": "system", "key": "<key>", "prompt": "<text, may use {{var.NAME}}>",
  "variables": {}, "guard": null }`. Logical identity is `(app, key)`; with no specific app use
  `"system"`. For a pack, suffix the **key** too so it can't collide with a seeded app prompt
  (e.g. `key: "tone_friendly_pack_<pack_id>"`).
- **hoodat_character** → `{ <character body blocks> , "avatar_path": null }`. The body holds
  `appearance` / `personality` / `background` / `speaking_style` / `experiences` / `qa` plus the
  top-level identity fields the Hoodat `Character` model defines; envelope `name` is the
  character's name. Leave `avatar_path` null (avatars are generated/uploaded per-install).

## Worked example

`/add-pack wildcard A collection of three moods` →

`packs/wildcard/a_collection_of_three_moods.json`:
```json
{
  "id": "a_collection_of_three_moods",
  "name": "A Collection of Three Moods",
  "description": "Three mood wildcards.",
  "tags": ["Pack", "moods"],
  "items": [
    {
      "schema_version": 1, "type": "wildcard",
      "id": "mood_pack_a_collection_of_three_moods",
      "name": "Mood", "description": "Emotional tone.",
      "tags": ["Pack", "moods"],
      "data": { "entries": [ {"text": "joyful"}, {"text": "melancholy"}, {"text": "serene"} ] }
    }
  ]
}
```

Always finish by confirming the file path, item count, and that it is valid.
