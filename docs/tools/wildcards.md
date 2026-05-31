# Wildcards

Wildcards are `%%token%%` placeholders that expand to weighted random entries at submission time. They work in any prompt field across the site — chain steps, image prompts, voice text — so the same vocabulary can drive every domain.

## What's on the page

- **Left** — list of wildcards, each showing `%%name%%`, the optional description (truncated to one line), and entry count
- **Right** — editor:
  - **Name** with a live `%%name%%` preview
  - **Description** — optional one-line note, surfaced in the list and in the `%%` autocomplete
  - **Entries** — a table of `{text, weight}` rows; weight runs 1–10 (Less often → More often, default 5)
  - **+ Add Entry** to append, remove button per row
- **Save** / **Delete**

## Autocomplete

Every prompt field on the site exposes a `%%` popover that lists known wildcards as you type, so authors don't have to remember names. The popover queries the same `/v1/wildcards` list.

## Data model

Stored in `config/wildcards/index.json` as [Cruddable envelopes](../management/cruddables.md):

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | int | envelope format version (`1`) |
| `type` | string | `"wildcard"` |
| `id` | slug | human-readable, unique within type. Wildcards are referenced by **name** (`%%name%%`), not id |
| `name` | string | the token identifier; case-sensitive |
| `description` | string | optional one-line note shown in the list and autocomplete |
| `tags` | string[] | envelope meta |
| `data.entries` | `{text, weight}[]` | at least one required, no empty text |
| `created_at`, `updated_at` | ISO 8601 | |

A wildcard is a [cruddable](../management/cruddables.md): Export / Copy / Extend the whole collection, or ship a vocabulary in a [Pack](packs.md).

## Expansion

`%%name%%` tokens are replaced just before a job runs, in the same pass that renders chain template variables. Replacement is weighted-random per occurrence: a weight-10 entry is twice as likely as a weight-5 entry. Unknown tokens (`%%not_a_wildcard%%`) pass through unchanged, so a prompt is forward-compatible with wildcards added later.

Expansion is applied to: chain step prompts, `ctx_pre`/`ctx_post`, image prompts, voice manual segments, and the input to voice auto-segmentation. What's saved into the job's `request.json` is the expanded text — re-running a job won't re-roll the wildcards.

### Composition

Entries may themselves contain `%%name%%` tokens, so wildcards compose. After an entry is picked, its text is re-scanned and any nested tokens are resolved (each occurrence picked independently). Cycles are blocked in two places:

- **At save time** — POST/PUT `/v1/wildcards` walks the reference graph (entry texts → token names, lowercased) and returns HTTP 422 with a `detail` describing the cycle path if saving would introduce a self-reference or transitive cycle. The wildcards editor surfaces the `detail` in its status line.
- **At resolve time** — a token whose name is already being expanded higher up the stack is left literal and a warning is logged to the browser console, so anything that slipped past the save check (e.g. wildcards added out of order to `config/wildcards/index.json` by hand) still can't hang the page. A hard depth cap of 16 acts as a final safety net.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/wildcards` | List |
| POST | `/v1/wildcards` | Create |
| PUT | `/v1/wildcards/{id}` | Update |
| DELETE | `/v1/wildcards/{id}` | Remove |
