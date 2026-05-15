# Wildcards

Wildcards are `%%token%%` placeholders that expand to weighted random entries at submission time. They work in any prompt field across the site — chain steps, image prompts, voice text — so the same vocabulary can drive every domain.

## What's on the page

- **Left** — list of wildcards, each showing `%%name%%` and entry count
- **Right** — editor:
  - **Name** with a live `%%name%%` preview
  - **Entries** — a table of `{text, weight}` rows; weight runs 1–10 (Less often → More often, default 5)
  - **+ Add Entry** to append, remove button per row
- **Save** / **Delete**

## Autocomplete

Every prompt field on the site exposes a `%%` popover that lists known wildcards as you type, so authors don't have to remember names. The popover queries the same `/v1/wildcards` list.

## Data model

Stored in `config/wildcards/index.json`:

| Field | Type | Notes |
|-------|------|-------|
| `id` | uuid | |
| `name` | string | the token identifier; case-sensitive |
| `entries` | `{text, weight}[]` | at least one required, no empty text |
| `created_at`, `updated_at` | ISO 8601 | |

## Expansion

`%%name%%` tokens are replaced just before a job runs, in the same pass that renders chain template variables. Replacement is weighted-random per occurrence: a weight-10 entry is twice as likely as a weight-5 entry. Unknown tokens (`%%not_a_wildcard%%`) pass through unchanged, so a prompt is forward-compatible with wildcards added later.

Expansion is applied to: chain step prompts, `ctx_pre`/`ctx_post`, image prompts, voice manual segments, and the input to voice auto-segmentation. What's saved into the job's `request.json` is the expanded text — re-running a job won't re-roll the wildcards.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/wildcards` | List |
| POST | `/v1/wildcards` | Create |
| PUT | `/v1/wildcards/{id}` | Update |
| DELETE | `/v1/wildcards/{id}` | Remove |
