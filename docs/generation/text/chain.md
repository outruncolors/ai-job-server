# Chain

The Chain tab lets you build an ordered list of steps and run them as a single job. Each step has a name, a type, and a small set of fields. Outputs flow forward: an `llm` step writes `text_output` that downstream steps consume via `{{previous}}`.

## Step types

### `llm` — text generation

Renders a prompt template, calls the configured LLM, and stores the response as `text_output`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Display name, also available as `{{step_name}}` |
| `prompt` | string | `""` | Prompt template; see [template variables](#template-variables) |
| `context_ids` | string[] | `[]` | [Context items](../../tools/context.md) to inject as `{{context}}` |
| `tools` | string[] | `[]` | [MCP tools](../../tools/mcp.md) to make available |

The step writes `prompt.txt`, `output.txt`, optionally `context.txt`, and `tool_calls.json` when tools are used.

### `voice` — text-to-speech

Synthesizes the current `text_output` through OmniVoice using a saved [voice preset](../audio/clone-voice.md). Does **not** update `text_output`; a voice step cannot be first in a chain (there is no text yet).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `voice_preset_id` | string | required | ID from `/v1/voice-presets` |
| `voice_pre` | string\|null | null | Prepended to the input before TTS |
| `voice_post` | string\|null | null | Appended to the input before TTS |
| `voice_preprocess` | bool | false | Clean the input through an LLM (strip markdown, expand symbols) |
| `voice_auto_segment` | bool | false | Split into natural segments with pauses via [auto-segmentation](../audio/use-voice.md#auto-segmentation) |

The step writes `output.wav`. With auto-segmentation, `auto_segment_prompt.txt` and `auto_segment_raw.txt` are also captured.

### `write_context` — save to context library

Persists the current `text_output` as a [context item](../../tools/context.md). Useful for chaining results into later runs.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ctx_name` | string | required | Title for the item (collision = update) |
| `ctx_description` | string\|null | null | |
| `ctx_tags` | string[] | `[]` | |
| `ctx_pre` / `ctx_post` | string\|null | null | Surround the saved text |
| `ctx_overwrite` | bool | false | Replace when true, append when false |

Writes `output.json` with the resulting item's `id` and `title`.

### `sequence` — expand a saved sequence

Inlines the steps of a saved [sequence](sequences.md). Names are prefixed `<sequence name> > <step name>`. Sequences can reference other sequences; runtime depth is capped at 20.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `sequence_id` | string | required | ID from `/v1/chain-sequences` |

## Template variables

Rendered in `prompt`, `ctx_pre`, and `ctx_post`:

| Variable | Resolves to |
|----------|-------------|
| `{{input}}` | The chain's `input` field |
| `{{previous}}` | The most recent `llm` step's output (empty until the first `llm`) |
| `{{context}}` | All resolved `context_ids`, joined with `\n\n---\n\n` |
| `{{step_index}}` | 1-based index in the fully-expanded chain |
| `{{step_name}}` | This step's `name` |

[Wildcards](../../tools/wildcards.md) expand alongside template variables: any `%%name%%` token in a prompt, context body, or voice text is replaced with a weighted random entry at submission time.

## Job layout

```
JOBS_BASE/YYYY-MM-DD/<uuid>/
├── request.json
├── status.json
├── logs.txt
├── artifacts.json
├── final_output.txt
└── steps/
    ├── 001_Write_Poem/
    │   ├── prompt.txt
    │   ├── output.txt
    │   └── tool_calls.json
    └── 002_Recite/
        └── output.wav
```

## Submitting a chain

```bash
curl -X POST http://localhost:8090/v1/jobs/chain \
  -H 'Content-Type: application/json' \
  -d '{
    "input": "Write a short poem about the sea.",
    "llm": {
      "api_base": "http://debian1.local:11434/v1",
      "model": "gemma4",
      "temperature": 0.8,
      "max_tokens": 512
    },
    "steps": [
      {"name": "Write", "type": "llm", "prompt": "{{input}}"},
      {"name": "Recite", "type": "voice", "voice_preset_id": "<preset>", "voice_auto_segment": true}
    ]
  }'
```

Poll `/v1/jobs/<id>` for status; retrieve `final_output.txt` and the per-step files when done.
