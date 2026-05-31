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

2. **Chain call** — one `execute_chain_job` with `steps=[turn, (variety), guard]`. The prompt step,
   the optional **variety** pass, and the narrative-editor guard collapse into a single chain; the
   **last step's** output becomes `final_output.txt`. Scaffold the job with
   `create_job("prattletale_turn", request.model_dump(), input)` + `find_job_dir`, then
   `await execute_chain_job(job_id, job_dir, request)`. The **variety** step (gated by
   `config.variety_pass_enabled`, default on) sits between the draft and the guard: it is given the
   recent transcript + the drafted reply (`{{previous}}`) and rewrites the draft only when it
   repeats the structure/opening/length/move of the character's recent messages — the primary lever
   against conversations getting monotonous. It keeps the tagged-line format, so the guard + parser
   downstream are unchanged.

3. **`parse_items(raw) -> list[dict]`** — **tagged-line format, not JSON.** The model emits one
   tagged line per bubble:
   ```
   [narration] She doesn't look up from the menu.
   [say] Where else would I be.
   ```
   Tag→type map: `say`→`dialogue`, `do`→`action`, `narration`→`narration`, `feel`→
   `narration_emotion`. Parser: fence-strip, split on newlines, regex `^\s*\[(\w+)\]\s*(.+)$`; an
   untagged line **coalesces into the previous item's text** (a lone untagged line defaults to
   `dialogue`); **emoji are stripped deterministically** (`_clean_text`/`_EMOJI_RE`) and an item
   left empty by the scrub is dropped; an empty result raises `GenerationError`. (The prompt + guard
   also forbid emoji, but the parser scrub guarantees it regardless of the model.)

   *Why not JSON?* Hoodat uses JSON because it assembles a fixed-schema record and can afford an
   assemble-only retry. A chat turn is an **open-ended ordered sequence of short strings** where
   the failure mode that matters is "model wrapped dialogue in prose / added a preamble" — which
   JSON doesn't prevent and which the tagged format degrades on gracefully (untagged → dialogue)
   instead of throwing. It also avoids an expensive parse-retry that would *change* the reply.

4. **Persist + trace** — append the model turn, bump `next_turn_seq`/`updated_at`, atomic-write
   `transcript.json`, and write `traces/<turn>.json` = `{job_id, context_input, raw_final_output,
   parsed_items, error}`.

### The narrative editor is a guard

Register the `prattletale/turn` prompt with a Prompt Pal **guard** (Hoodat's `SPOKEN_ONLY_GUARD`
is the precedent). The guard runs as the chain's **final** `llm` step over `{{previous}}` and does
**format hygiene only**: ensure every line is tagged, strip emoji/markdown and leaked internal
monologue / meta ("As an AI", "Here's my response:"), drop OOC commentary. Keep the *format
instruction* in the
`turn` prompt; the guard must **not merge** multiple bubbles into one. This is why parsing stays
trivial and the editor is tunable in the Prompt Pal UI with no extra job dir.

### Commit semantics

The model turn runs **synchronously via direct `execute_chain_job`** inside the POST — exactly
like every synchronous-generation app here (Hoodat, Blaboratory) — so foreground generation never
starves the shared JobQueue. The "typing" indicator is a **client-side** affordance shown while
the POST is in flight; no polling. JobQueue + polling is deferred to autonomous/tick pacing
(Phase 4), where background turns genuinely must not block.

### Error handling & retry

If the pipeline raises (LLM error, empty parse after guard), the generator calls
`store.append_error_turn` — a model turn with a single `type:"system_error"`, `status:"error"`
item — and the router returns **HTTP 200** with that turn so the UI renders the error bubble
inline. `system_error` items are always skipped by `build_context`, so a failed turn never poisons
the next attempt. **Retry** (`POST .../turns/{turn_id}/retry`) re-runs against the transcript with
the error turn excluded and `store.replace_turn` overwrites it **in place** (same `turn_id`, new
items, status `committed`), keeping turn order and layout stable; a fresh trace overwrites
`traces/<turn>.json`.

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
- `POST /conversations/{id}/turns/{turn_id}/items/{item_id}/audio` — synthesize (or return) one
  model item's clip: `{audio: {path, duration_ms, voice_preset_id} | null}`. Idempotent (reuses an
  existing wav); `null` when the item isn't spoken. Drives the client's per-message voice playback.

## Voice + timing

Activate `config.voice_enabled` / `typing_timing_enabled`. Synthesize model **`dialogue`** items
with the counterpart's Hoodat voice preset and model **`narration`/`narration_emotion`** with an
app-level **narrator** voice (never synthesize user-authored text). Store `media/<item>.wav` +
`duration_ms` on the item's `audio`. Gate synthesis on `requires_capability("voice")`; when voice
is off or the capability is unavailable, fall back cleanly to text.

**Synthesis is per-message, not per-turn.** The turn POST computes the whole turn (the
`turn → variety → guard` chain) and returns its text immediately (`run_model_turn(synthesize=False)`).
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

1. **Guard scope** — keep the tagged-line *format* rule in the `turn` prompt; guard does hygiene
   only and must not merge bubbles. The untagged-line→dialogue fallback covers a weak guard.
2. **No automatic retry in the chat path** — a re-generation changes the reply, so parse-failure →
   `system_error` + manual Retry is intentional.
3. **Context window unit is turns, not tokens** — fine for Phase 1; the token-budget pass is
   isolated to `build_context`.
4. **Concurrent POSTs to one conversation** — `append_*` re-reads before write; add a
   per-conversation lock only if it ever matters (single-user makes it unlikely).
5. **`device_user.persona` empty** — render the section out cleanly (no dangling label).
6. **Trace size** — traces embed the full context input per turn; acceptable as a debug artifact,
   but note it when calling the folder "portable."
