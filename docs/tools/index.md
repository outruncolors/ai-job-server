# Tools

The middle nav group. These aren't job runners — they're building blocks the generation pages consume.

- **[Context](context.md)** — reusable text blocks injected into LLM prompts as `{{context}}`.
- **[Wildcards](wildcards.md)** — `%%token%%` placeholders that expand to weighted random entries at job submission.
- **[Ticks](ticks.md)** — schedules that fire saved [sequences](../generation/text/sequences.md) on intervals or cron.
- **[MCP](mcp.md)** — the tool registry that LLM steps can call (random integers, name generation, voice segment formatting).
- **[Prompt Pal](prompt-pal.md)** — the registry for apps' internal LLM prompts: register in code, edit/filter/deep-link in the UI, resolve with a store-wins-else-default fallback. Includes the reusable FieldControls hover affordance.

All are surfaced as standalone pages in the navbar, but every other domain on the site consumes them: chain steps reference contexts and tools, voice and chain prompts expand wildcards, ticks schedule sequence runs, and apps register their prompts in Prompt Pal.
