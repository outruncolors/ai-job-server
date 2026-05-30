# Prompt Pal

Prompt Pal is the project-wide registry for the **internal LLM prompts apps use
for "creative input."** Instead of hard-coding prompt strings in each app, an app
*registers* its prompts; Prompt Pal gives every one an editable, filterable,
deep-linkable home so they can be tuned over time without a code change — while
keeping a code-side default so a fresh checkout (or a test) still works.

It's an app-agnostic tool (like [Context](context.md) or [Wildcards](wildcards.md)):
[Blaboratory](../apps/blaboratory/index.md) and [Hoodat](../apps/hoodat/index.md)
both register their prompts here.

## What's on the page

`/prompt-pal/` is a master/detail view:

- **Left** — every registered/stored prompt, with an `app` badge, its `key`,
  title, and tags. A toolbar offers **search** (title/key/description/tags),
  **filter by app**, **filter by tag**, and **sort** (app / title / updated).
- **Right** — an editor for the selected prompt: title, description, tags, the
  prompt body, and a `variables` JSON object. **Save** persists; **Preview**
  composes the prompt with the current variables so you can see the resolved
  text. `app` and `key` are shown read-only — they're code contracts.

**Deep-linking:** apps link here as `/prompt-pal/?app=<app>&highlight=<id>` to
scroll to, flash, and open a specific prompt. This is what Hoodat's per-field
"✏️ Edit prompt" button and the Exports tab use.

## How it works

- **Register in code, seed on startup.** An app declares its prompts at import
  with `register(app, key, *, title, prompt, description="", tags=(), variables=None)`
  (`app/prompt_pal/registry.py`). At boot, `lifespan` calls `seed_registered()`,
  which writes any **missing** `(app, key)` to the store — **seed-if-absent**, so
  it never clobbers an edit you made in the UI.
- **Resolve at runtime.** App code calls
  `prompt_pal.service.get_text(app, key, *, variables=None)`. The **store copy
  wins** (your edits take effect), otherwise the **in-code default** is used. Both
  are run through `compose`, which substitutes `{{var.NAME}}` tokens (and resolves
  any `{"prompt_id": …}` references via the store) while leaving chain tokens like
  `{{input}}` / `{{previous}}` intact for the [chain executor](../generation/text/chain.md).
  `id_for(app, key)` returns the entry id for `?highlight=` links.
- **A prompt is a compose node.** `prompt` + `variables` are exactly the
  `{prompt, variables}` shape `compose` (`app/prompt_pal/compose.py`) understands.

## Data model

File-per-document at `config/prompt_pal/<id>.json`:

| Field | Type | Notes |
|-------|------|-------|
| `id` | uuid | stable surrogate; what `?highlight=` and the filename use |
| `schema_version` | int | `1` |
| `app` | string | owning app, e.g. `"hoodat"` — **immutable** |
| `key` | string | code-facing id, e.g. `"IDEATE"` / `"field.appearance.primary_outfit"` — **immutable** |
| `title` | string | |
| `description` | string | |
| `tags` | string[] | |
| `prompt` | string | the body (may contain `{{var.NAME}}` and chain tokens) |
| `variables` | object | compose variables (literal, nested node, or `{prompt_id}`) |
| `created_at`, `updated_at` | ISO 8601 | |

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/prompt-pal/entries` | List (optional `?app=` / `?tag=` filters) |
| GET | `/v1/prompt-pal/entries/{id}` | Fetch one |
| POST | `/v1/prompt-pal/entries` | Create an ad-hoc entry (`409` if `(app,key)` exists) |
| PUT | `/v1/prompt-pal/entries/{id}` | Patch `title`/`description`/`tags`/`prompt`/`variables` (`app`/`key` ignored) |
| DELETE | `/v1/prompt-pal/entries/{id}` | Remove |
| POST | `/v1/prompt-pal/entries/{id}/preview` | Compose with supplied `{"variables": {…}}` |

Not capability-gated — it's pure config CRUD.

## FieldControls — the hover affordance

`static/js/field-controls.js` (+ `static/css/field-controls.css`) is the reusable,
app-agnostic companion to Prompt Pal. `FieldControls.attach(slotEl, {kind, controls,
context})` wraps any "slot" — an editable field or an avatar — and reveals a small
control cluster on hover / keyboard focus (tap-toggle on touch for avatars). The
component carries **zero app knowledge**; the app supplies every button's `onClick`.
Hoodat uses it to give each field a **✨ Generate** (fill the field from the rest of
the document) and **✏️ Edit prompt** (deep-link to that field's Prompt Pal entry)
button, and the avatar a **Replace** control.

## Migrating an app onto Prompt Pal

1. In the app's `prompts.py`, keep the literal prompt strings and add a
   `register("<app>", "<key>", title=…, prompt=<literal>, …)` for each.
2. Replace direct prompt lookups with `get_text("<app>", "<key>")` (Blaboratory's
   `get_prompt` is now a one-liner wrapper around this).
3. Ensure the app's prompts module is listed in `registry._PROMPT_MODULES` so
   `seed_registered()` imports it.

Because `get_text` falls back to the in-code default when the store is empty,
existing behavior and tests keep working before anything is seeded.
