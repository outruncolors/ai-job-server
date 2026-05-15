# MCP Tools

The MCP page hosts a tiny registry of structured tools that LLM chain steps can call. Tools are defined in code (`app/mcp/registry.py`), exposed through `/v1/mcp/*`, and surfaced to the LLM in OpenAI tool-use format.

## Built-in tools

| Name | Purpose |
|------|---------|
| `random_integer` | Returns an integer in `[min, max]`. |
| `generate_name` | Generates a random US name. Params: `gender` (`male`/`female`), `include_middle_name`, `include_last_name`. |
| `format_voice_segments` | Returns an array of `{text, delay_ms}` segments. Used by voice auto-segmentation; safe to expose to other steps if you want similar structure. |

There is no runtime registration mechanism — adding a tool means editing the registry and executor.

## What's on the page

- **Left** — list of tools with name and description
- **Right** — a "Try it" form auto-generated from the tool's JSON schema (text fields for strings, number fields for ints/floats, checkboxes for bools, dropdowns for enums). **Run** invokes the tool and prints the JSON result plus timing.

## Using tools in a chain

Set the `tools` field of an `llm` step to a list of tool names:

```json
{
  "name": "Pick",
  "type": "llm",
  "tools": ["random_integer", "generate_name"],
  "prompt": "Pick a number between 1 and 10, then a name for that number."
}
```

When `tools` is non-empty, the step enters a tool-use loop:

1. Send the prompt and tool schemas to the LLM.
2. If the response contains tool calls, validate the arguments, execute each tool, append the results as `tool` role messages, and call the LLM again.
3. Stop when the LLM produces a final text response or the loop hits 6 iterations.

Both standard `tool_calls` and llama.cpp's Gemma-style `<tool_call>...</tool_call>` token format are handled (the executor has a regex fallback for the latter). All tool invocations and results are written to `tool_calls.json` in the step's job directory.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/mcp/tools` | List with full input schemas |
| POST | `/v1/mcp/tools/{name}/call` | Execute the named tool with validated arguments |

## Gotchas

- The 6-iteration cap on the tool loop guards against infinite loops; a step that hits it is treated as completed with whatever output the LLM produced.
- Unknown tool names in `step.tools` are silently skipped (logged warning) — the step still runs without those tools.
- Tools don't see prior chain state. If you need access to `{{previous}}` or `{{context}}`, render it into the prompt instead.
