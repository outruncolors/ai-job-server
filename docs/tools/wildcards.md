# Wildcards

Wildcards are `{{wc.name}}` placeholders that expand to weighted random entries at submission time. They work in any prompt field across the site — chain steps, image prompts, voice text, Prattletale — so the same vocabulary can drive every domain.

Wildcards are one of three namespaces in the **unified prompt-token syntax** resolved by one engine (`app/prompt_template.py`) on the server:

- `{{wc.name}}` — this page's wildcards (weighted-random).
- `{{var.name}}` — a variable in scope, else the literal string `name` (see [chain variables](../generation/text/chain.md)).
- `{{ctx.name}}` — a [context item](context.md)'s full content, else the literal string `name`.

> **Legacy `%%name%%`** is still read as an alias of `{{wc.name}}`, so older prompts keep working. The one-time migration (`python -m app.cruddables.migrate`) rewrites stored `%%name%%` to `{{wc.name}}`; new authoring should use the `{{wc.}}` spelling.

## What's on the page

- **Left** — list of wildcards, each showing `{{wc.name}}`, the optional description (truncated to one line), and entry count
- **Right** — editor:
  - **Name** with a live `{{wc.name}}` preview
  - **Description** — optional one-line note, surfaced in the list and in the `{{`-token autocomplete
  - **Entries** — a table of `{text, weight}` rows; weight runs 1–10 (Less often → More often, default 5)
  - **+ Add Entry** to append, remove button per row
- **Save** / **Delete**

## Autocomplete

Every prompt field on the site shares one popover (`static/js/prompt-tokens.js`), triggered by typing `{{`. It first offers the three namespaces (`wc.` / `var.` / `ctx.`); pick one and it lists the matching items as you type — wildcards (with description), context items (description + tags), or the in-scope variables (with their current value). Wildcards come from `/v1/wildcards`, context items from `/v1/context-items`; each page registers its own variable scope. The popover only *inserts* tokens — resolution happens server-side.

## Data model

Stored in `config/wildcards/index.json` as [Cruddable envelopes](../management/cruddables.md):

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | int | envelope format version (`1`) |
| `type` | string | `"wildcard"` |
| `id` | slug | human-readable, unique within type. Wildcards are referenced by **name** (`{{wc.name}}`, or legacy `%%name%%`), not id |
| `name` | string | the token identifier; case-sensitive |
| `description` | string | optional one-line note shown in the list and autocomplete |
| `tags` | string[] | envelope meta |
| `data.entries` | `{text, weight}[]` | at least one required, no empty text |
| `created_at`, `updated_at` | ISO 8601 | |

A wildcard is a [cruddable](../management/cruddables.md): Export / Copy / Extend the whole collection, or ship a vocabulary in a [Pack](packs.md).

## Expansion

`{{wc.name}}` (and legacy `%%name%%`) tokens are replaced **server-side** just before a job runs, in the same unified pass that renders `{{var.}}`/`{{ctx.}}` and the chain tokens. Replacement is weighted-random per occurrence: a weight-10 entry is twice as likely as a weight-5 entry. Unknown tokens pass through unchanged, so a prompt is forward-compatible with wildcards added later.

Expansion is applied to every prompt-bearing field: chain step prompts, `voice_pre`/`voice_post`, `ctx_pre`/`ctx_post`, image prompts, voice text/manual segments, the input to voice auto-segmentation, and Prattletale prompts + chat input. The browser sends the raw text; the server resolves and (for image/voice) returns the resolved text + substitutions on the 202 for the "resolved prompt" display. What's saved into the job's `request.json` is the expanded text — re-running a job won't re-roll the wildcards.

> **Inert vs. re-scanned.** Only author-controlled library expansions (wildcard picks, context bodies) are re-scanned for further tokens. Runtime data — chain `{{input}}`/`{{previous}}`/`{{N_output}}`, `{{memory}}`, and resolved `{{var.}}` values — is substituted inertly and never re-expanded, so model output or a user variable containing `%%…%%`/`{{wc.…}}` cannot inject tokens.

### Composition

Entries may themselves contain `{{wc.name}}` (or `%%name%%`) tokens, so wildcards compose; they may also reference `{{var.}}`/`{{ctx.}}`. After an entry is picked, its text is re-scanned and any nested tokens are resolved (each occurrence picked independently). Cycles are blocked in two places:

- **At save time** — POST/PUT `/v1/wildcards` walks the reference graph (entry texts → token names in both `{{wc.name}}` and `%%name%%` form, lowercased) and returns HTTP 422 with a `detail` describing the cycle path if saving would introduce a self-reference or transitive cycle. The wildcards editor surfaces the `detail` in its status line.
- **At resolve time** — a token whose name is already being expanded higher up the stack is left literal and a warning is logged to the browser console, so anything that slipped past the save check (e.g. wildcards added out of order to `config/wildcards/index.json` by hand) still can't hang the page. A hard depth cap of 16 acts as a final safety net.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/wildcards` | List |
| POST | `/v1/wildcards` | Create |
| PUT | `/v1/wildcards/{id}` | Update |
| DELETE | `/v1/wildcards/{id}` | Remove |
