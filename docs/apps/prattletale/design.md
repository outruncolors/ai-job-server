# Prattletale — Design

> The canonical "what & why" for Prattletale. **Every build session reads this first.** It is the
> shared substrate that keeps each session self-contained: a fresh chat needs only this doc + that
> session's starter prompt + the committed code of prior sub-phases.

## Mission

An iMessage-style roleplay chat between a human **user** and a **Hoodat character** (the
*counterpart*). The model replies in the cadence of a real texting burst: an ordered stack of
short, typed bubbles. Conversations are self-contained on disk so they're portable and debuggable.

Prattletale depends on Hoodat for all non-user characters; Hoodat has no dependency on
Prattletale. (Other apps may later reuse Prattletale's messaging pipeline.)

## Scope by phase

- **Phase 1 (Foundation, text-first):** one human user ↔ one Hoodat counterpart. Conversation
  model + store, conversation-list + chat UI, the turn-generation pipeline, error/retry. Then a
  dedicated **voice + timing** session (OmniVoice TTS, typing/pause reveal cadence).
- **Phase 2 (Config & dev tools):** per-conversation config page + behaviour sliders, message
  edit/hide/delete, per-message action wrapper, trace viewer, a node-graph view of the pipeline,
  device-user/role settings.
- **Phase 3 (Plugins):** manifest + loader + hook registry, per-conversation plugin config,
  frontend plugin loading, a sample Emotion plugin, a Rescan UI.
- **Phase 4 (Advanced):** tick-driven autonomous pacing, **Model×Model** mode, timing refinement,
  a Group-chat plugin, error/history polish, narrator-voice settings + per-item TTS regen, a11y.

**Deferred from Phase 1** (noted, not built): voice & timing live in their own session (SP6);
Model×Model, plugins, ticks/autonomy, and the node-graph/trace UI are later phases.

## Platform building blocks (reused, no new core code)

| Need | Reuse | Symbol / path |
|------|-------|---------------|
| App layout | apps convention | `app/apps/prattletale/` + `static/apps/prattletale/`; `app.include_router(...)` in `app/main.py`; card in `static/apps/apps.js` |
| LLM turn | chain executor, called **directly** | `app/chain/executor.py::execute_chain_job`; default config `app/llm_config.py::get_default_as_chain_llm_config`; scaffold via `app/jobs.py::create_job` + `find_job_dir`, read `final_output.txt` |
| Chain request shape | pydantic models | `app/chain/models.py` — `ChainJobRequest`, `ChainStep`, `Alternative`, `ChainLLMConfig` |
| Counterpart sheet/avatar/voice | Hoodat store + renderer | `app/apps/hoodat/characters_store.py::get_character`; `app/apps/hoodat/prompts.py::render_character_context`; `character["avatar_path"]`; `character["speaking_style"]["voice_preset_id"]` |
| Prompts + narrative editor | Prompt Pal | `register("prattletale", key, ...)` in `prompts.py`, module added to `app/prompt_pal/registry.py::_PROMPT_MODULES`; runtime `app/prompt_pal/service.py::get_text`/`get_guard`. The narrative editor is a **guard** (Hoodat's spoken-only guard is the precedent) |
| Voice (SP6) | OmniVoice | `app/omnivoice/runner.py`, `app/chain/steps/voice.py::run_voice_step`, `app/voice_presets.py`; gate with `app/server.py::requires_capability("voice")` |
| Autonomy (Phase 4) | ticks / queue | `app/ticks/scheduler.py`, `app/apps/blaboratory/sim_clock.py`; JobQueue LOW lane |

**Reference apps to mirror:** Hoodat (`generator.py` `_run_single_step`/`run_create`, the guard
step, the file-per-doc atomic-write store, `router.py` `GenerationError`→HTTP mapping) and
Blaboratory (`generator.py` runs the executor directly; `tick_runner.py` `_choose`).

## Terminology & data model

A conversation is a folder: `config/prattletale/conversations/<id>/`

```
conversation.json    # metadata, scenario, role instructions, device-user, config
transcript.json      # ordered turns -> items
traces/<turn>.json   # per-model-turn debug capture
media/<item>.wav     # generated audio (SP6 onward; absent in text-first phase)
```

### `conversation.json`

```json
{
  "schema_version": 1,
  "type": "prattletale_conversation",
  "id": "late-night-diner-a1b2",
  "title": "Late-night diner",
  "counterpart_character_id": "mara-okafor",
  "device_user": {
    "display_name": "You",
    "persona": "A regular who shows up most nights, tired but curious.",
    "avatar_path": null
  },
  "scenario": "It's 1am at an all-night diner. Rain outside.",
  "role_instructions": "Stay in character as Mara. React to what the user actually says.",
  "config": {
    "context_window_turns": 12,
    "voice_enabled": false,
    "typing_timing_enabled": false
  },
  "created_at": "2026-05-31T00:00:00Z",
  "updated_at": "2026-05-31T00:00:00Z"
}
```

- `counterpart_character_id` resolves through `characters_store.get_character(id)` **at generation
  time** — avatar and voice are read live, never copied here (so editing the character updates the
  chat). `id` is a slug derived from `title`, made unique against existing folder names (reuse
  `slugify`/`unique_id` from `app/cruddables/envelope.py`).
- `config` is the forward-compatibility block. Phase 1 reads only `context_window_turns`. The voice
  flags ship **inert** so the voice session (SP6) activates them with no schema migration.

### `transcript.json`

```json
{
  "schema_version": 1,
  "conversation_id": "late-night-diner-a1b2",
  "turns": [
    { "id": "t0001", "author": "user", "created_at": "...Z",
      "items": [
        { "id": "t0001-i01", "turn_id": "t0001", "author": "user",
          "type": "dialogue", "text": "you actually showed up",
          "status": "committed", "audio": null,
          "hidden_from_context": false, "created_at": "...Z" } ] },
    { "id": "t0002", "author": "model", "created_at": "...Z", "job_id": "job_...",
      "items": [
        { "id": "t0002-i01", "turn_id": "t0002", "author": "model",
          "type": "narration_emotion", "text": "She doesn't look up from the menu.",
          "status": "committed", "audio": null, "hidden_from_context": false, "created_at": "...Z" },
        { "id": "t0002-i02", "turn_id": "t0002", "author": "model",
          "type": "dialogue", "text": "Where else would I be.",
          "status": "committed", "audio": null, "hidden_from_context": false, "created_at": "...Z" } ] }
  ],
  "next_turn_seq": 3
}
```

**Turn vs item.** A **turn** is one side's atomic contribution — the unit of alternation,
context-window slicing, and retry: `{id, author: user|model, created_at, job_id?, items:[...]}`.
An **item** is one rendered bubble: `{id, turn_id, author, type, text, status, audio,
hidden_from_context, created_at}`. iMessage renders a turn as one avatar-grouped stack of item
bubbles; the model legitimately emits several bubbles per reply (a narration beat, then dialogue),
each individually typed/timed later, so items cannot collapse into one blob.

**Item `type`** ∈ `dialogue | action | narration | narration_emotion | system_error`:
- `dialogue` — spoken words (the only TTS-eligible type in SP6).
- `action` — a physical beat (e.g. the user slides over the sugar).
- `narration` — third-person scene/event text.
- `narration_emotion` — narration focused on the counterpart's internal/emotional state.
- `system_error` — a failed model turn rendered as a tappable error bubble (author `model`, never
  fed back into context).

**`status`** ∈ `committed | generating | error`. **`audio`** is `null` in the text-first phase;
SP6 sets `{"path": "media/<item>.wav", "duration_ms": N, "voice_preset_id": "..."}`.
**`hidden_from_context`** ships in Phase 1 (always `false`, but **honored** by the context
assembler) so the Phase-2 message-editing feature needs no pipeline change. **Item id** format is
`<turn_id>-i<NN>` — make the formatter explicit so traces and the frontend agree.

## Turn-generation pipeline (text-only)

`generator.py` mirrors Hoodat's `_run_single_step`/`run_create`, structured as discrete,
independently testable stages.

1. **`build_context(conversation, character, transcript) -> dict[str,str]`** — a **pure function**
   (store reads only, no LLM). Produces the variable bundle:
   - `character` = `render_character_context(character)`
   - `scenario`, `role_instructions`, `user_persona` (skip the persona section cleanly if empty)
   - `transcript` = the last `config.context_window_turns` turns flattened to a script, **skipping
     `hidden_from_context` and `system_error` items**, e.g.
     ```
     [User] you actually showed up
     [Mara] (she doesn't look up) "Where else would I be."
     ```
   Isolating this function means the later token-budget change (window unit is currently *turns*,
   not tokens) touches nothing else.

2. **Director pre-pass (default on, `config.director_enabled`)** — before drafting, a tiny one-step
   LLM job (`run_director`, `prattletale_director`) reads the conversation, the character's stable
   voice, and a deterministic **recent-pattern summary** (`build_recent_pattern_summary`: recent
   openings, message counts, overused phrases, trailing-question flag) and returns a **strict JSON
   plan** for the next reply — `reply_shape` (message count / action / narration), `conversation_move`,
   `emotional_temperature`, `stance`, `must_reference` / `must_include` / `must_avoid`, `length`
   (`director.py`: `parse_director_plan` validates/normalizes, `render_director_plan` renders it).
   The plan **subsumes** the old shade/move/cadence feel roll and is the primary lever against
   monotony — dynamism is decided *before* drafting, not patched in after. On any failure or empty
   parse it falls back to the weighted wildcard **feel roll** (`resolve_dialogue_feel_roll`), so the
   plan block is always populated.

3. **Turn call** — one `execute_chain_job` with a single `turn` step; its output becomes
   `final_output.txt`. Scaffold with `create_job("prattletale_turn", …)` + `find_job_dir`, then
   `await execute_chain_job(job_id, job_dir, request)`. By default (`config.structured_chat_history`)
   the turn step sends the model a **real sequenced role array** (`Alternative.messages`):
   system framing (identity + rules + output format via the `turn_system` prompt, then character /
   voice / standing orders / memory / the director plan) followed by the recent window as actual
   `user`/`assistant`/`summary` messages and a short final `user` instruction
   (`build_structured_messages` + `_transcript_to_messages`). Memory injects through the lone
   `{{memory}}` token in the dedicated memory message. The legacy **single flattened prompt** (the
   `turn` Prompt Pal entry, with the plan spliced through the `{{var.dialogue_feel_roll}}` slot)
   remains as the fallback when `structured_chat_history` is off. *(The old `variety` pass and LLM
   `guard` step are **retired** — see below.)*

4. **Deterministic-first repair → `parse_items(raw) -> list[dict]`** — the raw output runs through a
   cheap Python cleanup (`repair.py::repair_output_deterministic`: strip fences/emoji/preamble, drop
   empty lines, cap runaway) **before** the parser. Only when the deterministic pass + parser still
   can't produce items does a last-resort LLM **repair** job (`run_repair`, the `repair` prompt over
   `{{input}}`; gated by `config.repair_enabled`) reformat the reply. `parse_items` is the single
   arbiter — **canonical message format, not JSON.** The model emits one message per line:
   ```
   She doesn't look up from the menu.
   "Where else would I be."
   ```
   Canonical, per line: a full double-quoted line `"…"`→`dialogue` (outer quotes stripped; single
   quotes may nest), a line of one or more `*…*` spans→`action` (one item **per span**, so each is
   its own SFX candidate), and any other non-empty line→`narration`. **Legacy bracket tags** are
   still accepted as *input/back-compat only* (`say`→`dialogue`, `do`→`action`, `narration`/`feel`
   and any unknown tag→`narration`). A stray `_underscore-wrapped_` line is normalized to plain
   narration. Parser: fence-strip, split on newlines; **emoji are stripped deterministically**
   (`_clean_text`/`_EMOJI_RE`) and an item left empty by the scrub is dropped; an empty result raises
   `GenerationError`. (The prompt + deterministic repair also forbid emoji, but the parser scrub
   guarantees it regardless of the model.)

   *Why not JSON?* Hoodat uses JSON because it assembles a fixed-schema record and can afford an
   assemble-only retry. A chat turn is an **open-ended ordered sequence of short strings** where
   the failure mode that matters is "model wrapped dialogue in prose / added a preamble" — which
   JSON doesn't prevent and which the tagged format degrades on gracefully (untagged → dialogue)
   instead of throwing. It also avoids an expensive parse-retry that would *change* the reply.

5. **Persist + trace** — append the model turn, bump `next_turn_seq`/`updated_at`, atomic-write
   `transcript.json`, and write `traces/<turn>.json` = `{job_id, prompt_version, context_input,
   pattern_summary, director_plan, director_plan_raw, structured_messages, raw_final_output, repair,
   parsed_items, steps, error}` (so a trace is fully self-describing: what the director planned, the
   exact role array sent, and whether deterministic-vs-LLM repair ran).

### Format hygiene is deterministic-first repair (the LLM guard is retired)

The pipeline used to run an **unconditional LLM guard** step over every reply for format hygiene —
an extra round-trip that could also normalize voice away or quietly undo a standing order. It is
**retired**: `repair_output_deterministic` does the hygiene (fences, emoji, preamble, runaway cap) in
Python before `parse_items`, and the LLM **repair** prompt runs *only* when the deterministic pass
still won't parse. The seeded `turn` guard is disabled and the `variety` pass seeds empty (both kept
in Prompt Pal, resurrectable); `migrate_turn_variety_prompts` empties an unedited stored variety and
disables an unedited stored guard. `parse_items` stays the single arbiter, so parsing stays trivial.

### Message shape: the director plan (wildcard fallback)

Left alone, the model over-narrates and fires a burst of bubbles every turn. The desired *shape* of
a reply — how many messages, and whether to include an action or narration — is now decided by the
**director plan**'s `reply_shape`. The legacy `Prattletale Message Style` **wildcard** (seeded by
`app/apps/prattletale/seed.py`, tunable in the Wildcards UI) lives in the single-prompt `turn` entry
via a `%%Prattletale Message Style%%` token resolved server-side
(`wildcards.resolve_wildcards`, fresh weighted pick each turn: default 40% single / 30%
action+message / 20% mix with narration / 10% burst) — it applies only in the single-prompt fallback
when `structured_chat_history` is off and the director is unavailable.

### Commit semantics

The model turn runs **synchronously via direct `execute_chain_job`** inside the POST — exactly
like every synchronous-generation app here (Hoodat, Blaboratory) — so foreground generation never
starves the shared JobQueue. The "typing" indicator is a **client-side** affordance shown while
the POST is in flight; no polling. JobQueue + polling is deferred to autonomous/tick pacing
(Phase 4), where background turns genuinely must not block.

### Error handling & retry

If the pipeline raises (LLM error, empty parse after deterministic + LLM repair), the generator calls
`store.append_error_turn` — a model turn with a single `type:"system_error"`, `status:"error"`
item — and the router returns **HTTP 200** with that turn so the UI renders the error bubble
inline. `system_error` items are always skipped by `build_context`, so a failed turn never poisons
the next attempt. **Retry** (`POST .../turns/{turn_id}/retry`) re-runs against the transcript with
the error turn excluded and `store.replace_turn` overwrites it **in place** (same `turn_id`, new
items, status `committed`), keeping turn order and layout stable; a fresh trace overwrites
`traces/<turn>.json`.

### Continue & regenerate (versions)

**Continue** (`POST .../continue`) runs the model-turn pipeline against the current transcript
**without** appending a user turn first — the partner takes another turn on its own. The composer's
Send button reads **"Continue"** when empty; this is also how the character can open an empty
conversation. `build_context` already tolerates consecutive model turns / an empty transcript.

**Regenerate** (`POST .../turns/{turn_id}/regenerate`) is like Retry — latest model turn only (409
otherwise), context excludes the turn — but instead of overwriting it **appends a new version** via
`store.add_turn_version`, keeping the prior take(s). A turn carries `versions: list[{items, job_id,
created_at}] | None` and `active_version: int`; `versions` is **None until the first regenerate**
(the common case — user turns and first-pass model turns are unversioned), then `Turn.items` becomes
a mirror of `versions[active_version].items` so every downstream reader (context, voice, sfx,
edit/hide/delete, the frontend) is unchanged. In-place item mutators sync their edit back into the
active version only (`store._sync_versions_from_items`). A regenerate that **fails re-raises** (the
router returns 502) rather than appending a `system_error` turn, so the existing turn and its
versions stay intact. **Switching** the active version (`POST .../turns/{turn_id}/version` with
`{index}`) is a non-generating op allowed on any versioned turn regardless of position; the UI shows
`◀ N/M ▶` plus a `↻` regenerate button (latest model turn only) in a per-turn footer.

## API surface (Phase 1)

Prefix `/v1/apps/prattletale`:

- `GET /conversations` — summaries (id, title, counterpart, last-item preview, updated_at).
- `POST /conversations` — create from `{title, counterpart_character_id, device_user, scenario,
  role_instructions}` (404 if the counterpart character is missing).
- `GET /conversations/{id}` — `{conversation, transcript}`.
- `DELETE /conversations/{id}` — remove the folder.
- `POST /conversations/{id}/turns` — body `{items: [{type, text}, ...]}`; appends the user turn,
  runs the model turn, returns `{user_turn, model_turn}` (model_turn may be a `system_error` turn).
- `POST /conversations/{id}/turns/{turn_id}/retry` — re-run a failed/model turn; replaces it.
- `POST /conversations/{id}/continue` — partner takes another turn (no user turn appended); returns
  `{model_turn}`.
- `POST /conversations/{id}/turns/{turn_id}/regenerate` — append a new **version** of the latest
  model turn (keeps prior versions); 409 if not the latest model turn, 502 on generation failure.
- `POST /conversations/{id}/turns/{turn_id}/version` — body `{index}`; switch the active version of
  a turn. 422 when the turn is unversioned or the index is out of range.
- `POST /conversations/{id}/turns/{turn_id}/items/{item_id}/audio` — synthesize (or return) one
  model item's clip: `{audio: {path, duration_ms, voice_preset_id} | null}`. Idempotent (reuses an
  existing wav); `null` when the item isn't spoken. Drives the client's per-message voice playback.

## Voice + timing

Activate `config.voice_enabled` / `typing_timing_enabled`. Synthesize model **`dialogue`** items
with the counterpart's Hoodat voice preset and model **`narration`/`narration_emotion`** with an
app-level **narrator** voice (never synthesize user-authored text). Store `media/<item>.wav` +
`duration_ms` on the item's `audio`. Gate synthesis on `requires_capability("voice")`; when voice
is off or the capability is unavailable, fall back cleanly to text.

**Synthesis is per-message, not per-turn.** The turn POST computes the whole turn (director plan →
turn step → deterministic repair) and returns its text immediately (`run_model_turn(synthesize=False)`).
The client then reveals the messages one at a time. A **background producer** synthesizes the
turn's clips in order, one at a time (via the per-item `.../audio` endpoint), so upcoming messages
are usually ready ahead of the playhead; the reveal loop shows each message's "..." indicator and
**awaits that message's clip** — usually already produced (brief dots), else the dots stay up until
it's ready — then swaps the dots for the bubble and plays the clip with a left→right progress bar
across the read-aloud duration (the clip length, else a text-length reading estimate when there's
no audio). Synthesis stays a single job at a time (the producer serializes, and the loop shares its
in-flight promise rather than firing its own), and the first message plays as soon as clip 0 is
ready — never waiting on the whole reply to be voiced. The eager `synthesize_turn` helper (whole
turn in one await) remains for non-streaming callers.

## Risks / open questions (non-blocking)

1. **Repair scope** — format hygiene is deterministic-first (`repair_output_deterministic`); the LLM
   `repair` prompt runs only on a parse failure and must not merge bubbles or change wording. The
   unrecognized-line→narration fallback covers a weak repair.
2. **No automatic retry in the chat path** — a re-generation changes the reply, so parse-failure →
   `system_error` + manual Retry is intentional.
3. **Context window unit is turns, not tokens** — fine for Phase 1; the token-budget pass is
   isolated to `build_context`.
4. **Concurrent POSTs to one conversation** — `append_*` re-reads before write; add a
   per-conversation lock only if it ever matters (single-user makes it unlikely).
5. **`device_user.persona` empty** — render the section out cleanly (no dangling label).
6. **Trace size** — traces embed the full context input per turn; acceptable as a debug artifact,
   but note it when calling the folder "portable."
