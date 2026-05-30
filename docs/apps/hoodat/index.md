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
   **Experiences**, **Speaking Style**, **Q&A**, **Exports**.
4. **Edit any field** inline (changes save on blur). Fields render the control
   that fits them — text areas, a number input for age, **Male/Female radios** for
   sex, and a **feet + inches** pair for height (stored as a canonical `5'10"`
   string). **Hover a field** to reveal:
   - **✨ Generate** — regenerate just that field from the rest of the character.
   - **✏️ Edit prompt** — jump to that field's prompt in [Prompt Pal](../../tools/prompt-pal.md).
5. **Hover the avatar** → **Replace** → **Generate from description** (ComfyUI
   `image` workflow) or **Upload an image**.
6. The **Appearance** tab is split into three cards: **Basics** (always visible —
   height, build, skin, hair color/details, eye color/details, distinguishing
   features), **Nude** (private-area fields; the male-only vs female-only fields
   are shown based on the character's **sex**, shared fields always), and
   **Clothed** — a list of **outfits**, each a card with garment slots (top,
   bottoms, underwear, socks & shoes, accessories). Generate a whole outfit at once
   (**✨ Outfit**) or one slot at a time (per-slot ✨), and mark exactly one outfit
   **primary** (the one that feeds the avatar image prompt).
7. On the **Speaking Style** tab, build a **Dialogue examples** list: the first
   row is typed by hand, then **+ Add dialogue example** *generates* the next
   line from the list-so-far + the character (few-shot — more examples ⇒ closer
   matches). Each row has ✨ (regenerate just that line), ✏️ (edit the prompt),
   and ✗ (remove). The list is reachable in export prompts as
   `{{var.dialogue_examples}}`.
8. The **Experiences** tab is a list of formative events. **+ Add experience**
   *generates* one from the character + the list-so-far, and the LLM also decides
   whether it was **Positive** or **Negative** (you can flip the toggle). Each row
   has ✨/✏️/✗ like dialogue. Experiences are reachable in export prompts split by
   valence as `{{var.experiences_positive}}` / `{{var.experiences_negative}}`.
9. The **Q&A** tab is an [AliChat](https://rentry.co/alichat)-style interview: type
   a question and **✨ Generate answer**, or **💡 Suggest question** to have the LLM
   propose one first. Each answer is generated *in the character's voice* and is
   **spoken-only** — a [guarded prompt](../../tools/prompt-pal.md#guarded-prompts)
   strips stage directions, actions, and symbols so it reads well aloud. Edit either
   field freely; each pair has ✨ (regenerate the answer), ✏️ (edit the `qa.answer`
   prompt), ✗ (remove), and — when the character has a **voice preset** set on the
   Speaking Style tab — a **🔊** button to hear the answer over TTS. Q&A pairs feed
   the shared character context (and exports), weighted last per AliChat.

Each tab's content is grouped into uniform section cards (header + body) for a
consistent look.

**Prerequisite:** generation uses `get_default_as_chain_llm_config()`, so an LLM
must be reachable (a local `llama-server` or the `llm` peer). Avatar *generation*
additionally needs the **`image`** capability on this node (see below). With a
missing/failed model, create/generate calls return `502`.

## Sections (the v2 template)

`app/apps/hoodat/models.py` defines `Character` (full, persisted) and
`CharacterDraft` (all-Optional, the LLM-output validation target). `id` /
`schema_version` / timestamps / `avatar_path` are server-assigned.

| Section | Fields |
|---------|--------|
| **Identity & Basics** (top-level) | `name`, `summary`, `tagline`, `age`, `sex`, `occupation` |
| **Appearance → Basics** | `height`, `build`, `skin`, `hair_color`, `hair_details`, `eye_color`, `eye_details`, `distinguishing_features[]` |
| **Appearance → Nude** (flat fields, UI-gated on `sex`) | shared: `body_hair`, `pubic_hair`, `buttocks`, `lips`, `hands`, `feet`; male-only: `penis`, `testicles`; female-only: `breasts`, `vulva` |
| **Appearance → Clothed** | `outfits[]` — each `Outfit` = `name`, `top`, `bottoms`, `underwear`, `socks_shoes`, `accessories`, `primary` |
| **Personality** | `traits[]`, `quirks[]`, `values[]`, `fears[]` |
| **Background & Relationships** | `backstory`, `origin`, `relationships[]`, `affiliations[]`, `skills[]` |
| **Speaking Style** | `description`, `voice_preset_id` (references the [voice preset](../../generation/audio/use-voice.md) system), `dialogue_examples[]` |
| **Experiences** (top-level) | `experiences[]` — each `Experience` = `description`, `valence` (`positive`/`negative`) |
| **Q&A** (top-level) | `qa[]` — each `QAPair` = `question`, `answer` (AliChat interview exemplars; spoken-only answers) |

`FIELD_SPECS` in `models.py` is the single source of truth for which scalar/list
fields are generatable, their label, and their kind (`scalar` / `int` / `list`) —
it drives per-field prompt registration, patch-building, and value normalization.
The Nude fields are kept **flat** on the `Appearance` block (not nested) so they
reuse the standard `field.appearance.<x>` generate path unchanged; the UI gates
which ones it shows. `dialogue_examples`, `outfits`, `experiences`, and `qa` are
intentionally **not** in `FIELD_SPECS`: they are list-of-objects/few-shot fields
the frontend owns and generates one item at a time (see below).

**Migration (v1 → v2):** older characters carried flat `hair` / `eyes` /
`primary_outfit`. A `model_validator(mode="before")` on `Appearance` hoists them
into `hair_color` / `eye_color` / a single primary `outfits` entry, and the store
normalizes legacy docs on read (`schema_version` bumped to `2`), so no data is
lost and the UI never sees the old shape.

## How it works

- **Store** (`characters_store.py`) — file-per-document JSON at
  `config/hoodat/characters/<id>.json`; `update_character_fields(id, patch)`
  deep-merges nested-section patches.
- **Generator** (`generator.py`) — runs the chain executor **directly** (not the
  shared `JobQueue`), mirroring Blaboratory. `run_create()` does ideate → assemble,
  parses strict JSON with ≤2 retries, merges the user's name, and persists.
  `run_field()` is a single-step chain over the rendered document, normalized per
  the field's kind. `run_dialogue_example(id, examples)`,
  `run_experience_example(id, experiences)`, `run_outfit(id, outfits, outfit)`,
  `run_outfit_slot(id, slot, outfit, outfits)`, `run_qa_answer(id, question, pairs)`,
  and `run_qa_question(id, pairs)` are single-step chains that generate one list
  item from the character + prior items and **do not persist** (the frontend owns
  those lists and saves them via the CRUD `PUT`). The experience generator returns
  a `{description, valence}` object — the LLM picks the valence. The
  [guarded](../../tools/prompt-pal.md#guarded-prompts) generators (`run_dialogue_example`,
  `run_qa_answer`) append the prompt's guard as a second `llm` step via
  `_run_single_step(..., guard_prompt=…)`, so the spoken-only editor runs before
  the value comes back. Jobs appear in the **Jobs** page as `hoodat_character` /
  `hoodat_field` / `hoodat_dialogue` / `hoodat_experience` / `hoodat_outfit` /
  `hoodat_qa` / `hoodat_export` / `hoodat_avatar`.
- **Prompts** (`prompts.py`) — registers `IDEATE`/`ASSEMBLE`, one
  `field.<section>.<field>` per generatable field, `dialogue.example`
  (`{{var.character}}` + `{{var.examples}}`), `experience.example`
  (`{{var.character}}` + `{{var.experiences}}` → JSON `{description, valence}`),
  `qa.answer` (`{{var.character}}` + `{{var.question}}` + `{{var.qa}}`),
  `qa.question` (suggest helper), `outfit.full` / `outfit.slot`, and
  `avatar.image_prompt` with [Prompt Pal](../../tools/prompt-pal.md). `dialogue.example`
  and `qa.answer` ship a shared **spoken-only guard**. All editable in its UI.
- **Avatars** (`avatars.py`) — *generate* builds a templated image prompt (tuned
  to **FLUX.2 [klein]** best practices for a realistic photographic portrait) and
  runs the ComfyUI `image` workflow via `execute_image_job`, copying the result to
  `config/hoodat/avatars/<id>.png`; *upload* stores raw image bytes. Either sets
  `avatar_path` to the serve endpoint.
- **Targeted Exports** (`exports.py`) — export definitions **are** Prompt Pal
  entries (`app="hoodat"`, `key="export.<slug>"`) with `{{var.character}}` +
  `{{var.detail}}` + `{{var.dialogue_examples}}` + `{{var.experiences_positive}}` +
  `{{var.experiences_negative}}`; running one is a single LLM chain over the
  rendered document at the chosen detail level (`brief` / `standard` / `detailed`).
  The Exports tab also has plain **⬇ Export JSON** / **📋 Copy JSON** buttons that
  download or copy the full character document verbatim (the canonical server doc,
  re-fetched first) — no LLM, purely client-side. Copy falls back to a hidden
  textarea + `execCommand` when `navigator.clipboard` is unavailable (LAN HTTP).

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
`POST …/qa/generate` + `…/qa/question/generate`, avatar generate/upload/serve, and
exports list/run.
