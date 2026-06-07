# Chain

The Chain tab lets you build a numbered list of steps and run them as a single job. Each step has a **number**, a **name**, a **type**, and one or more **alternatives** (the executor picks one per visit, weighted by `weight`). Steps can loop back via dedicated `goto` steps, and a sequence can declare named **variables** that the caller fills in at run time.

Persisted shape uses `schema_version: 2`. The wire format accepts v1-style flat step dicts (`prompt`, `tools`, `preset`, …) as shorthand and hoists them into a single alternative on parse, so simple `curl` payloads stay terse.

## Anatomy of a step

```jsonc
{
  "number": 1,                 // stable, user-visible; unique within the sequence
  "name": "Write",
  "type": "llm",               // see step types below
  "visit_cap": 100,             // hard limit on how many times this step may run
  "alternatives": [
    { "weight": 1, "prompt": "Write a story about {{var.topic}}" },
    { "weight": 3, "prompt": "Write a poem about {{var.topic}}" }
  ]
}
```

At runtime the executor `random.choices()` one alternative each visit. Weights are **relative** (no sum-to-100 rule): `1` and `3` means 25% / 75%.

If you don't care about branching, write a single alternative — that's the common case. The `weight` field defaults to 1.

## Step types

### `llm` — text generation

Renders a prompt template, calls the configured LLM, and stores the response as `text_output` (LLM steps are the only step type that mutate `text_output`).

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | `""` | Prompt template; see [template variables](#template-variables) |
| `context_ids` | string[] | `[]` | [Context items](../../tools/context.md) injected as `{{context}}` |
| `tools` | string[] | `[]` | [MCP tools](../../tools/mcp.md) available to this alternative |
| `preset` | string\|null | null | [LLM preset](../../tools/llm-presets.md) to load before the call. Falls back to `default_preset` from `config/llamacpp.json`. |
| `requires` | string[] | `[]` | Capabilities (`text`, `vision`) the chosen preset must advertise; validated at sequence-save time (422 on mismatch) |
| `thinking` | bool\|null | null | Reasoning control. `null` uses the project default (`DEFAULT_THINKING` — on); `true`/`false` force it. Realized as a per-request `thinking_budget_tokens` (`-1` on / `0` off) — no model reload. Set `false` for in-character roleplay replies; leave default for utility/JSON prompts. |

Before each `llm` alternative runs, the executor POSTs `{"preset": "<name>"}` to `/v1/llamacpp/ensure-loaded` on whichever node holds the `llm` capability. If the preset is already loaded the call is a near-instant no-op; otherwise `llama-server` is swapped and the swap is logged. With no preset set anywhere the swap is skipped and the request's `llm` config is used as-is.

**Reasoning ('thinking').** The per-step `thinking` flag is sent to llama.cpp as `thinking_budget_tokens` on the chat-completions body, so toggling it never reloads the model. This is honored **only when the server was launched without a `--reasoning-budget` flag** (CLI default `-1`); the default text preset should therefore set `jinja: true` + `reasoning_format: "auto"` and **omit** `reasoning_budget` from its `args`. With `reasoning_format` parsing on, the model's think block lands in the response's `reasoning_content` (not `content`), so step output stays clean; the executor also strips a stray leading `<think>…</think>` defensively.

Writes `prompt.txt`, `output.txt`, optionally `context.txt`, and `tool_calls.json` when tools fire.

### `voice` — text-to-speech

Synthesizes either the rendered `prompt` template (if non-empty) or the current `text_output` through OmniVoice using a saved [voice preset](../audio/clone-voice.md). Does **not** update `text_output`.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `voice_preset_id` | string | required | ID from `/v1/voice-presets` |
| `prompt` | string | `""` | Optional template; if non-empty, becomes the spoken text (else falls back to `text_output`) |
| `voice_pre` / `voice_post` | string\|null | null | Wrap the spoken text |
| `voice_preprocess` | bool | false | Clean the input through an LLM (strip markdown, expand symbols) |
| `voice_auto_segment` | bool | false | Split into natural segments with pauses via [auto-segmentation](../audio/use-voice.md#auto-segmentation) |

Writes `output.wav`. With auto-segmentation, `auto_segment_prompt.txt` and `auto_segment_raw.txt` are also captured.

### `write_context` — save to context library

Persists the current `text_output` as a [context item](../../tools/context.md).

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `ctx_name` | string | required | Title for the item (collision = update) |
| `ctx_description` | string\|null | null | |
| `ctx_tags` | string[] | `[]` | |
| `ctx_pre` / `ctx_post` | string\|null | null | Wrap the saved text |
| `ctx_overwrite` | bool | false | Replace when true, append when false |

Writes `output.json` with the resulting item's `id` and `title`.

### `image_prompt` — save an image prompt

Saves a named entry to the image-prompts library. Title and body are both rendered templates.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `image_prompt_name` | string | required | Name template; the result is auto-suffixed if it collides |
| `image_prompt_workflow` | string\|null | null | Optional ComfyUI workflow filename |
| `prompt` | string | `""` | Body template; falls back to `text_output` when empty |

Writes `output.json` describing the saved prompt. Does not mutate `text_output`.

### `save_wildcard` — create or append a wildcard

Adds an entry to a wildcard list. `mode=append` (default) merges into the existing list when it exists; `mode=create` always creates a new one.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `wildcard_name` | string | required | Name template (used in `%%name%%` references elsewhere) |
| `wildcard_mode` | `"append"` \| `"create"` | `"append"` | |
| `prompt` | string | `""` | Entry text template; falls back to `text_output` when empty |

Writes `output.json`. Does not mutate `text_output`.

### `create_ticket` — file a ticket

Creates a ticket on the [tick queue](../../tools/ticks.md). Title and description are templates.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `ticket_title_template` | string | required | Title template |
| `ticket_description_template` | string | `""` | Description template; falls back to `text_output` when empty |
| `ticket_file_hints` | string[] | `[]` | Optional file path hints |

Writes `output.json`. Does not mutate `text_output`.

### `sequence` — expand a saved sequence

Inlines the steps of a saved [sequence](sequences.md). Names get a `<sequence name> > ` prefix; inner step numbers are renumbered with an offset so they sort after the host step.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `sequence_id` | string | required | ID from `/v1/chain-sequences` |

Runtime expansion depth is capped at 20.

### `goto` — jump (and loop)

Picks one alternative per visit; if `target_step` is set the executor jumps to that step number, otherwise (`fall_through: true`) the executor advances to the next-higher step number normally.

| Alt field | Type | Default | Description |
|-----------|------|---------|-------------|
| `target_step` | int \| null | null | Step number to jump to. Must reference an existing step; validated at save time. |
| `fall_through` | bool | false | When true, do not jump — let execution continue. Exactly one of `target_step` / `fall_through` must be set per alternative. |

Looping is just a goto pointing at an earlier `number`. Run-away gotos are bounded two ways: the **per-step `visit_cap`** (default 100), and a **chain-wide 2000-run total budget**. Either limit short-circuits the job to `status=error` with a descriptive reason in `status.json`.

## Variables

A sequence can declare variables that the caller overrides at submit time:

```jsonc
{
  "name": "tone",
  "default": "friendly",
  "choices": ["friendly", "formal", "curt"]   // optional; renders as dropdown
}
```

The chain page surfaces a `Variables` pane above the step list, and when you click **Run Chain** the page opens a dialog with one field per variable (dropdown when `choices` is set, text input otherwise) — the values you enter become `request.variables`. The executor merges them on top of each variable's `default`, then exposes the result as `{{var.NAME}}` to every template.

Programmatic submission attaches variables to the request body:

```jsonc
{
  ...
  "variables": { "tone": "curt" },
  "sequence_variables": [
    { "name": "tone", "default": "friendly", "choices": ["friendly", "formal", "curt"] }
  ]
}
```

## Template variables

Rendered in any template-ish alternative field (`prompt`, `image_prompt_name`, `wildcard_name`, `ticket_title_template`, `ticket_description_template`, `ctx_pre`, `ctx_post`, …):

| Token | Resolves to |
|-------|-------------|
| `{{input}}` | The chain's `input` field |
| `{{previous}}` | The most recent `llm` step's output |
| `{{context}}` | All resolved `context_ids` for the running alternative, joined |
| `{{step_index}}` | The current step's `number` |
| `{{step_name}}` | The current step's `name` |
| `{{N_input}}` | The rendered prompt that was fed to step number `N` on its most recent visit |
| `{{N_output}}` | The output of step number `N` on its most recent visit |
| `{{var.NAME}}` | Caller-overridden value, falling back to the variable's `default` |

Unknown tokens render as the empty string (a forward reference to a not-yet-run step is legal because of gotos).

[Wildcards](../../tools/wildcards.md) (`%%name%%`) expand alongside template tokens. The frontend resolves them before the request is sent, so what lands in `request.json` is the expanded text.

## Job layout

```
JOBS_BASE/YYYY-MM-DD/<uuid>/
├── request.json
├── status.json
├── logs.txt
├── artifacts.json
├── final_output.txt
└── steps/
    ├── 001_Write/                # first invocation of step 1
    │   ├── prompt.txt
    │   ├── output.txt
    │   └── tool_calls.json
    ├── 001_Write_x01/             # re-invocation (loop back to step 1)
    │   ├── prompt.txt
    │   └── output.txt
    └── 002_Recite/
        └── output.wav
```

Re-runs of the same step (only possible when a `goto` points back at it) get an `_xNN` suffix where `NN` is a zero-padded invocation index. A step that only runs once keeps the simple `NNN_id` form.

## Submitting a chain

```bash
curl -X POST http://localhost:8090/v1/jobs/chain \
  -H 'Content-Type: application/json' \
  -d '{
    "schema_version": 2,
    "input": "Write a short poem about the sea.",
    "llm": {
      "api_base": "http://debian1.local:11434/v1",
      "model": "gemma4",
      "temperature": 0.8,
      "max_tokens": 512
    },
    "variables": { "tone": "curt" },
    "sequence_variables": [
      { "name": "tone", "default": "friendly", "choices": ["friendly","curt"] }
    ],
    "steps": [
      { "number": 1, "name": "Write",  "type": "llm",
        "alternatives": [{"prompt": "{{input}} in a {{var.tone}} voice"}] },
      { "number": 2, "name": "Recite", "type": "voice",
        "alternatives": [{"voice_preset_id": "<preset>", "voice_auto_segment": true}] }
    ]
  }'
```

Single-alternative v1-style steps still parse: `{"name":"Write","type":"llm","prompt":"{{input}}"}` is hoisted into one alternative on the server.

Poll `/v1/jobs/<id>` for status; retrieve `final_output.txt` and the per-step files when done.
