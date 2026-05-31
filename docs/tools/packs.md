# Packs & the unified Cruddable format

Every CRUD entity in the app ("cruddable") is stored as a single **envelope** shape:
shared meta columns plus a typed `data` payload. The on-disk shape **is** the export shape
**is** the envelope — one source of truth you can export, edit (or have an LLM generate),
re-import, and bundle into **Packs**.

## The envelope

```jsonc
{
  "schema_version": 1,           // envelope-format version
  "type": "wildcard",            // registry key / "table"
  "id": "hair_colors",           // human-readable, underscore-separated, unique within type
  "name": "Hair Colors",
  "description": "",
  "tags": ["Pack", "colors"],    // pack items carry "Pack" + a theme tag
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "data": { /* type-specific payload */ }
}
```

`id` is a slug (lowercase, underscores). Pack items end with `_pack_<pack_id>`. New items get
`slugify(name)`, uniquified with `_2`, `_3`, … (`app/cruddables/envelope.py`).

### `data` per type

| type | `data` |
|---|---|
| `wildcard` | `{ "entries": [{"text": str, "weight"?: int}] }` |
| `context_item` | `{ "content": str }` |
| `image_prompt` | `{ "prompt": str, "workflow": str\|null }` |
| `chain_sequence` | `{ "steps": [ChainStep], "variables": [SequenceVariable], "content_version": int }` |
| `prompt_pal` | `{ "app": str, "key": str, "prompt": str, "variables": {}, "guard": {}\|null }` |
| `hoodat_character` | the `Character` body (identity fields + `appearance`/`personality`/`background`/`speaking_style` blocks + `experiences`/`qa` + `avatar_path`) + `content_version` |

Wildcards are referenced by **name** (`%%name%%`); context items and sequences are
referenced by **id**. The one-time re-slug migration (`app/cruddables/migrate.py`, already
applied — run via `python -m app.cruddables.migrate`) converted every legacy uuid-keyed doc to a
human slug id, fixing those reference sites (`chain_sequence` step `sequence_id`/`context_ids`) and
re-keying hoodat avatar files + `data.avatar_path`. It is idempotent, so re-running is a safe no-op.

## Packs

A pack bundles fully-formed envelopes:

```jsonc
{ "id": "basic_colors", "name": "Basic Colors", "description": "…",
  "tags": ["Pack", "colors"], "items": [ /* envelopes, ids end _pack_basic_colors */ ] }
```

**Applying a pack == extending a cruddable type with the pack's `items`** — byte-for-byte.
Each item is upserted by `id`, so re-applying a pack overwrites any local edits to a pack
item (rename it to keep your version).

### Where pack files live

- `packs/<type>/<pack_id>.json` — shipped in the repo (tracked).
- `config/packs/<type>/<pack_id>.json` — user packs (gitignored). A user pack **shadows** a
  builtin pack with the same `(type, id)`.

Malformed pack files are skipped and logged, never aborting a listing.

### Browsing & applying

The **Packs** page (Tools → Packs) lists packs with search + filter by type/tag + sort, shows
name/description/tags/type/item-count/source, and offers **Apply** and **View JSON** (copy +
download). Apply reports `{created, updated, errored}`.

### API (`/v1/packs`)

| method | path | purpose |
|---|---|---|
| GET | `/v1/packs/packs` | pack summaries (`{id,name,description,tags,type,item_count,source}`) |
| GET | `/v1/packs/{type}/{id}` | full pack doc |
| POST | `/v1/packs/{type}/{id}/apply` | apply → `apply_items` report (+ `pack` field) |

For `chain_sequence`, structural validation runs on apply (unique step numbers, weights,
goto targets) but **capability validation is skipped** so a cross-machine pack applies even
when a named preset is absent locally.

## `/add-pack` skill

`/add-pack <type> <theme>` authors a pack file from a one-line description, e.g.
`/add-pack wildcard A collection of sixteen different colors`. It slugs the theme to a
`pack_id`, generates envelope items (`id = <slug>_pack_<pack_id>`, `tags` include `"Pack"`,
valid `data`), writes `packs/<type>/<pack_id>.json`, and validates each item against the
`Cruddable` model. See `.claude/skills/add-pack/SKILL.md` for the per-type `data` spec.

## Code map

| File | Purpose |
|---|---|
| `app/cruddables/envelope.py` | `Cruddable` model + `slugify`/`unique_id` |
| `app/cruddables/base.py` | `CruddableAdapter` ABC (list/get/upsert/delete/migrate_native) |
| `app/cruddables/adapters/*.py` | one adapter per type, wrapping its store |
| `app/cruddables/registry.py` | `REGISTRY`, `get_adapter`, `list_types` |
| `app/cruddables/service.py` | `apply_items(items, expected_type=None)` — shared upsert/report |
| `app/cruddables/router.py` | `/v1/cruddables/{types, {type}/export, {type}/extend}` |
| `app/cruddables/migrate.py` | one-time re-slug migration (uuid→slug, reshape, ref-fix, avatar re-key); idempotent, already applied |
| `app/packs/store.py` | two-tree pack file store (builtin + user) |
| `app/packs/service.py` | `apply_pack(type, id)` → `apply_items` |
| `app/packs/router.py` | `/v1/packs/*` |
| `static/packs/`, `static/cruddables/` | the two UI pages |
