# Chain Jobs

A chain job is a sequence of steps that run in order. The output of one step becomes the input for the next. Chains are submitted to `POST /v1/jobs/chain`.

---

## Step types

### `llm` — text generation

Calls the LLM with a rendered prompt. The LLM's response becomes `text_output` and is passed to subsequent steps as `{{previous}}`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | Display name (used in `{{step_name}}`) |
| `type` | `"llm"` | **required** | |
| `prompt` | string | `""` | Prompt template; supports `{{input}}`, `{{previous}}`, `{{context}}`, `{{step_index}}`, `{{step_name}}` |
| `context_ids` | string[] | `[]` | IDs from the context library to inject as `{{context}}` |
| `tools` | string[] | `[]` | MCP tool names to make available (see [MCP tools](#mcp-tools)) |

The step writes these files in its subdirectory:
- `context.txt` — resolved context text (if any context was referenced)
- `prompt.txt` — the final rendered prompt sent to the LLM
- `output.txt` — the LLM's response
- `tool_calls.json` — tool call/result history (if tools were used)

---

### `voice` — text-to-speech

Synthesizes the current `text_output` to audio. Does **not** update `text_output`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | |
| `type` | `"voice"` | **required** | |
| `voice_preset_id` | string | **required** | ID from `/v1/voice-presets` |
| `voice_pre` | string\|null | null | Text prepended to the input before TTS |
| `voice_post` | string\|null | null | Text appended to the input before TTS |
| `voice_preprocess` | bool | false | Run the input through an LLM to clean markdown/symbols before TTS |
| `voice_auto_segment` | bool | false | Ask the LLM to split the text into natural segments with pause timings |

A voice step cannot be the first step in a chain (there is no text yet for the first step).

The step writes `output.wav` in its subdirectory. When `voice_auto_segment` is true, it also writes `auto_segment_prompt.txt` and `auto_segment_raw.txt` for auditability.

---

### `write_context` — save to context library

Saves the current `text_output` as a context item. Does **not** update `text_output`. Creates the item if it does not exist; updates it if an item with the same name already exists.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | |
| `type` | `"write_context"` | **required** | |
| `ctx_name` | string | **required** | Name/title for the context item |
| `ctx_description` | string\|null | null | Short description |
| `ctx_tags` | string[] | `[]` | Tags for organization and retrieval |
| `ctx_pre` | string\|null | null | Text prepended to the output before saving |
| `ctx_post` | string\|null | null | Text appended to the output before saving |
| `ctx_overwrite` | bool | false | If true, replace existing content; if false, append |

The step writes `output.json` with the saved context item's `id` and `title`.

---

### `sequence` — reference a saved sequence

Expands a saved sequence inline. The sub-steps run as if they were written directly in the chain. Step names get a prefix: `<sequence name> > <step name>`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | **required** | |
| `type` | `"sequence"` | **required** | |
| `sequence_id` | string | **required** | ID from `/v1/chain-sequences` |

Sequences can reference other sequences. Depth is capped at 20 to catch infinite loops not caught at save time.

---

## Template variables

Template variables are rendered at execution time in `prompt` (llm steps) and optionally in `ctx_pre`/`ctx_post` (write_context steps).

| Variable | Resolves to |
|----------|-------------|
| `{{input}}` | The chain's original `input` field |
| `{{previous}}` | The output of the most recent `llm` step (empty string if none yet) |
| `{{context}}` | Text from all resolved `context_ids`, joined with `\n\n---\n\n` separators |
| `{{step_index}}` | The 1-based index of this step in the fully-expanded chain |
| `{{step_name}}` | The name of this step |

If no context IDs are specified, `{{context}}` is replaced by an empty string.

---

## Sequences

Sequences are saved, reusable step lists. Manage them at `/v1/chain-sequences` or via the Chain UI → Chain tab → Sequences.

**Create / update:**
```bash
curl -X POST http://localhost:8090/v1/chain-sequences \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Summarize + Speak",
    "steps": [
      {"name":"Summarize","type":"llm","prompt":"Summarize in 3 sentences:\n\n{{previous}}"},
      {"name":"Speak","type":"voice","voice_preset_id":"<preset-id>"}
    ]
  }'
```

Cycle detection runs at save time. An attempt to create a sequence that (directly or transitively) references itself returns 422.

---

## Context items

Context items are stored in the context library (`/v1/context-items`). Each item has a `title`, optional `description`, `tags`, and a `content` field.

Reference them in an `llm` step's `context_ids` field — the content of all referenced items is concatenated and injected as `{{context}}`. You can also select items by tag: any item that has a matching tag is included.

Useful patterns:
- Store reference documentation or API specs as context items, then reference them in chain steps
- Use `write_context` steps to save outputs for later chains

---

## MCP tools

Tools available for `llm` steps:

| Tool | Description |
|------|-------------|
| `random_integer` | Generate a random integer in `[min, max]` |
| `generate_name` | Generate a random US name; params: `gender` (male/female), `include_middle_name`, `include_last_name` |
| `format_voice_segments` | Format text as voice segments with pause timings; used internally by voice auto-segmentation |

Specify tools by name in the step's `tools` array:
```json
{ "name": "Generate", "type": "llm", "tools": ["random_integer", "generate_name"], "prompt": "Pick a number between 1 and 10 and give it a name." }
```

The LLM tool loop runs up to 6 iterations. The executor handles the OpenAI-style `tool_calls` / `tool` messages protocol. For llama.cpp servers (Gemma 4) that emit tool calls as `<tool_call>…</tool_call>` content tokens, a regex fallback parser handles extraction automatically.

---

## Voice auto-segmentation

When `voice_auto_segment: true` is set on a voice step, the step:

1. Sends the text to the LLM with a segmentation prompt asking it to split the text into natural speech segments and assign pause durations.
2. The LLM calls the `format_voice_segments` MCP tool to return structured segments.
3. The segments are synthesized individually and merged into a single WAV with silence padding between them.

The segmentation prompt can be customized via `PUT /v1/omnivoice/config` (field `voice_auto_segment_prompt`). Leave it null to use the built-in default.

Use this feature when the input is long prose that benefits from natural pauses — for example, bullet lists, dialogue, or multi-sentence paragraphs.

---

## Example: two-step chain

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
      {
        "name": "Write Poem",
        "type": "llm",
        "prompt": "{{input}}"
      },
      {
        "name": "Recite",
        "type": "voice",
        "voice_preset_id": "<your-preset-id>",
        "voice_auto_segment": true
      }
    ]
  }'
```

Poll `GET /v1/jobs/<job_id>/files/status.json` every few seconds. When `status == "done"`, retrieve:
- `GET /v1/jobs/<job_id>/files/final_output.txt` — the poem text
- `GET /v1/jobs/<job_id>/files/steps/002_Recite/output.wav` — the audio
