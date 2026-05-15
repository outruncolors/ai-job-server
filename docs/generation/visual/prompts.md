# Prompts

The Prompts tab manages the library of saved image prompts that the Generate tab's "Load saved prompt" dropdown reads from.

## What's on the page

Two-panel layout, mirroring the Context page:

- **Left** — list of saved prompts, sorted by name. Each row shows the name, a one-line prompt preview, and (if set) the workflow as a tag. **+ New** clears the form.
- **Right** — edit form with:
  - **Name** — required; renames are persisted via `PUT /v1/image-prompts/{id}`.
  - **Workflow** — optional select populated from `/v1/comfyui/workflows`. Blank means the prompt is generic and not tied to a specific workflow.
  - **Prompt** — required textarea.
  - **Save** / **Cancel** / **Delete** — Delete asks for confirmation.

Saves and deletes also refresh the Generate tab's "Load saved prompt" dropdown so changes are visible immediately without a page reload.

## Backing API

| Verb | Path | Body |
|------|------|------|
| GET | `/v1/image-prompts` | — |
| POST | `/v1/image-prompts` | `{ name, prompt, workflow? }` |
| PUT | `/v1/image-prompts/{id}` | partial: `name`, `prompt`, `workflow` |
| DELETE | `/v1/image-prompts/{id}` | — |

Storage lives in `config/image_prompts/index.json` (gitignored). Name conflicts on create or rename are auto-disambiguated with ` (2)`, ` (3)`, etc.
