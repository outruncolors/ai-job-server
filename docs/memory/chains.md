# Memory: chain integration

LLM chain steps can retrieve memory before they run and inject it via the `{{memory}}`
template token.

## Per-step `memory` config

Add a `memory` block to an `llm` step's alternative (or as a v1 flat field — it is hoisted
like other alternative fields):

```json
{
  "type": "llm",
  "name": "Answer with memory",
  "prompt": "You may use these memories:\n\n{{memory}}\n\nQuestion: {{input}}\n\nAnswer concisely.",
  "memory": {
    "enabled": true,
    "query": "{{input}}",
    "scopes": [{ "scope_type": "project", "scope_id": "ai-job-server" }],
    "top_k": 5,
    "inject_as": "memory",
    "max_chars": 1200
  }
}
```

Fields:

| Field | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Turn retrieval on for this step. |
| `query` | `{{input}}` | Search query template (rendered with the step's tokens). |
| `scopes` | `[]` | List of `{scope_type, scope_id}`; each `scope_id` is templated. Empty = all scopes. |
| `top_k` | `5` | Max memories retrieved. |
| `inject_as` | `memory` | Template token the block is exposed as (`{{memory}}` by default). |
| `max_chars` | `1200` | Cap on the injected block. |

## Behavior

Before the LLM step renders its prompt, the runner:

1. Renders `query` and each scope's `scope_id` with the current step tokens
   (`{{input}}`, `{{previous}}`, `{{var.NAME}}`, …).
2. Searches the memory service.
3. Formats results into a compact block (`format_memory_block`).
4. Exposes the block as `{{<inject_as>}}` and writes it to the step's
   `steps/NNN_<id>/memory.txt` for inspection.

It does **not** mutate `{{context}}`. Retrieval is **fail-soft**: a disabled subsystem, no
matches, or any error yields an empty block — memory absence is never a step failure.

## `{{memory}}` token

`{{memory}}` (or your custom `inject_as` name) is resolved via `render_template`'s `extra`
map. Like all chain tokens, an unreferenced/empty token renders as `""`.

## Example sequence

The builtin **Memory Demo** pack (`packs/chain_sequence/memory_demo.json`) is a one-step
chain that retrieves `project/ai-job-server` memories for `{{input}}` and answers using
them. Apply it from **Tools → Packs**, seed some memories (Memory Lab, scope
`project/ai-job-server`), then run the sequence from the Text tab.

## Future: `write_memory` step

A non-LLM `write_memory` step (persist `{{previous}}` to a scope after a step) is a planned
addition. It was intentionally left out of the first release so the core service could
stabilize first.
