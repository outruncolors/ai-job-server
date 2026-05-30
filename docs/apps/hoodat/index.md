# Hoodat

Hoodat is a tool for **creating and managing characters**. You give a name and a
short prompt; a generation chain best-guesses every field of a versioned,
standardized character template. From there each field can be regenerated on
demand, the character gets a Discord-profile-style page, an avatar can be
generated or uploaded, and **Targeted Exports** render the whole character into
other formats at a configurable level of detail.

Hoodat dogfoods two cross-app abstractions: [Prompt Pal](../../tools/prompt-pal.md)
(every prompt it uses — create, per-field, export, avatar — is a Prompt Pal entry)
and the **FieldControls** hover affordance (per-field generate/edit-prompt and the
avatar Replace control).

## Using it

1. Open **Apps** (`/apps`) → the **Hoodat** card → `/apps/hoodat/`.
2. The landing page is a searchable grid of **character cards**. Click **+ New
   character**, enter a **name** + **prompt**, and submit. A synchronous
   *"Generating character…"* run (a 2-step LLM chain) fills the template, then you
   land on the character's **profile page**.
3. The profile has a circular **avatar** (top-left), the name, and tabs for each
   section: **Identity**, **Appearance**, **Personality**, **Background**,
   **Speaking Style**, **Exports**.
4. **Edit any field** inline (changes save on blur). **Hover a field** to reveal:
   - **✨ Generate** — regenerate just that field from the rest of the character.
   - **✏️ Edit prompt** — jump to that field's prompt in [Prompt Pal](../../tools/prompt-pal.md).
5. **Hover the avatar** → **Replace** → **Generate from description** (ComfyUI
   `image` workflow) or **Upload an image**.
6. On the **Speaking Style** tab, build a **Dialogue examples** list: the first
   row is typed by hand, then **+ Add dialogue example** *generates* the next
   line from the list-so-far + the character (few-shot — more examples ⇒ closer
   matches). Each row has ✨ (regenerate just that line), ✏️ (edit the prompt),
   and ✗ (remove). The list is reachable in export prompts as
   `{{var.dialogue_examples}}`.

Each tab's content is grouped into uniform section cards (header + body) for a
consistent look.

**Prerequisite:** generation uses `get_default_as_chain_llm_config()`, so an LLM
must be reachable (a local `llama-server` or the `llm` peer). Avatar *generation*
additionally needs the **`image`** capability on this node (see below). With a
missing/failed model, create/generate calls return `502`.

## Sections (the v1 template)

`app/apps/hoodat/models.py` defines `Character` (full, persisted) and
`CharacterDraft` (all-Optional, the LLM-output validation target). `id` /
`schema_version` / timestamps / `avatar_path` are server-assigned.

| Section | Fields |
|---------|--------|
| **Identity & Basics** (top-level) | `name`, `summary`, `tagline`, `age`, `sex`, `occupation` |
| **Appearance** | `height`, `build`, `hair`, `eyes`, `skin`, `distinguishing_features[]`, `primary_outfit` |
| **Personality** | `traits[]`, `quirks[]`, `values[]`, `fears[]` |
| **Background & Relationships** | `backstory`, `origin`, `relationships[]`, `affiliations[]`, `skills[]` |
| **Speaking Style** | `description`, `voice_preset_id` (references the [voice preset](../../generation/audio/use-voice.md) system), `dialogue_examples[]` |

`FIELD_SPECS` in `models.py` is the single source of truth for which fields are
generatable, their label, and their kind (`scalar` / `int` / `list`) — it drives
per-field prompt registration, patch-building, and value normalization.
`dialogue_examples` is intentionally **not** in `FIELD_SPECS`: it is a list-aware
few-shot field generated one item at a time (see below).

## How it works

- **Store** (`characters_store.py`) — file-per-document JSON at
  `config/hoodat/characters/<id>.json`; `update_character_fields(id, patch)`
  deep-merges nested-section patches.
- **Generator** (`generator.py`) — runs the chain executor **directly** (not the
  shared `JobQueue`), mirroring Blaboratory. `run_create()` does ideate → assemble,
  parses strict JSON with ≤2 retries, merges the user's name, and persists.
  `run_field()` is a single-step chain over the rendered document, normalized per
  the field's kind. `run_dialogue_example(id, examples)` is a single-step chain
  that generates one new dialogue line from the character + the prior examples
  and **does not persist** (the frontend owns the list and saves it via the CRUD
  `PUT`). Jobs appear in the **Jobs** page as `hoodat_character` / `hoodat_field`
  / `hoodat_dialogue` / `hoodat_export` / `hoodat_avatar`.
- **Prompts** (`prompts.py`) — registers `IDEATE`/`ASSEMBLE`, one
  `field.<section>.<field>` per generatable field, `dialogue.example`
  (`{{var.character}}` + `{{var.examples}}`), and `avatar.image_prompt` with
  [Prompt Pal](../../tools/prompt-pal.md). All editable in its UI.
- **Avatars** (`avatars.py`) — *generate* builds a templated image prompt (tuned
  to **FLUX.2 [klein]** best practices for a realistic photographic portrait) and
  runs the ComfyUI `image` workflow via `execute_image_job`, copying the result to
  `config/hoodat/avatars/<id>.png`; *upload* stores raw image bytes. Either sets
  `avatar_path` to the serve endpoint.
- **Targeted Exports** (`exports.py`) — export definitions **are** Prompt Pal
  entries (`app="hoodat"`, `key="export.<slug>"`) with `{{var.character}}` +
  `{{var.detail}}` + `{{var.dialogue_examples}}`; running one is a single LLM chain
  over the rendered document at the chosen detail level (`brief` / `standard` /
  `detailed`).

## Capability gating

Text generation is **not** route-gated — chain steps route to the `llm` peer
automatically. Avatar *generation* **degrades gracefully**: the
`POST …/avatar/generate` handler returns `503 {"error":"capability_unavailable",
"needed":"image"}` on a node without the `image` capability rather than gating the
whole app — **upload and everything else stay available**. The profile page hides
the Generate-avatar and voice-synthesis controls when the corresponding local
capability is absent.

## API

Prefix `/v1/apps/hoodat` — see the [API reference](../../reference/api.md#apps--hoodat)
for the full table. Briefly: characters CRUD, `POST …/fields/{section}/{field}/generate`,
avatar generate/upload/serve, and exports list/run.
