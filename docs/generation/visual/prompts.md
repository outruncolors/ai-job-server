# Saved Image Prompts

A small library of named prompts for image generation, with an optional workflow association. Save a prompt you like once and reload it later without retyping.

The same data backs two places: the **Save / Load** toolbar above the prompt textarea on the [Generate](generate.md) tab, and the dedicated **Prompts** tab for browse / rename / delete.

## Data model

Stored at `config/image_prompts/index.json` (gitignored) as [Cruddable envelopes](../../management/cruddables.md).

| Field | Notes |
|---|---|
| `schema_version` | Envelope format version (`1`) |
| `type` | `"image_prompt"` |
| `id` | Human-readable slug, unique within type |
| `name` | Required. Unique — duplicates are auto-suffixed `(2)`, `(3)`, … on create or rename |
| `description` / `tags` | Envelope meta |
| `data.prompt` | Required. The text injected into the workflow's `PROMPT` node |
| `data.workflow` | Optional. Filename (without `.json`) of a ComfyUI workflow, or `null` for generic |
| `created_at` / `updated_at` | ISO timestamps |

A saved image prompt is a [cruddable](../../management/cruddables.md): Export / Copy / Extend the library, or ship prompts in a [Pack](../../tools/packs.md).

## UI

### Generate tab — quick save / load

Above the prompt textarea on `/image`:

- **Load saved prompt** — dropdown listing every saved prompt; the workflow appears in parentheses (`name (workflow)`). Selecting one fills the textarea and, if the saved workflow still exists, also reselects it. The dropdown resets after selection so you can pick the same prompt again.
- **Save** — opens a name prompt. POSTs the current textarea and currently-selected workflow as a new entry. Empty prompts are refused. The new entry shows up immediately in the Load dropdown.

### Prompts tab — full CRUD

Two-panel layout (`/image#tab-prompts`), mirroring the Context page:

- **Left** — list of saved prompts sorted by name, each row showing name, a one-line prompt preview, and (if set) the workflow as a tag. Click a row to edit. **+ New** clears the form.
- **Right** — edit form with:
  - **Name** — required; renames are persisted.
  - **Workflow** — select populated from `/v1/comfyui/workflows`; blank means generic and not tied to a workflow.
  - **Prompt** — required textarea.
  - **Save** / **Cancel** / **Delete** — Delete asks for confirmation.

Saves and deletes also refresh the Generate tab's Load dropdown without a page reload.

## REST API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/image-prompts` | List → `{ prompts: [...] }` |
| `POST` | `/v1/image-prompts` | Create. Body: `{ name, prompt, workflow? }`. 422 on missing name/prompt |
| `GET` | `/v1/image-prompts/{id}` | Fetch one; 404 if unknown |
| `PUT` | `/v1/image-prompts/{id}` | Partial update of `name`, `prompt`, `workflow`. Unknown fields ignored. 422 on empty name. 404 if unknown |
| `DELETE` | `/v1/image-prompts/{id}` | Remove; 404 if unknown |

## Backing module

`app/image_prompts.py` — JSON-index CRUD; no separate process. The Generate tab loads the list once on page init via `loadSavedPromptList()` and refreshes it whenever the Prompts tab saves or deletes.
