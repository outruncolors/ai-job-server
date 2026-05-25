# AI Job Server

A self-hosted job runner for text, audio, and image generation, plus the tooling around it (context, wildcards, schedules, MCP tools, server controls).

Use the tree on the left to navigate. Every page in the site has a matching doc; the structure here mirrors the navbar.

## Sections

- **[Generation](generation/index.md)** — the three creative tabs: Text (chain jobs), Audio (voice), Visual (image)
- **[Tools](tools/index.md)** — content building blocks: context items, wildcards, ticks (schedules), MCP tools
- **[Management](management/index.md)** — server controls, the job list, this docs viewer
- **[Apps](apps/index.md)** — consumer experiences behind the `/apps` landing (Blaboratory)
- **[Reference](reference/index.md)** — architecture, REST API, configuration, design notes, UI standards
- **[Multi-machine](multi-machine.md)** — primary/secondary deployment: bare repo, systemd, capability gating, cutover
- **[Upgrading llama.cpp](llamacpp-upgrade.md)** — bumping the pinned `LLAMA_CPP_TAG` on the secondary

## Quick start

1. Open **Text** (`/chain`) and run a one-step chain: `{{input}}` as the prompt, type "say hi" in the input box.
2. Watch the **Jobs** page for status. Click the job to see its artifacts.
3. From **Server → LLM**, configure the LLM endpoint that backs chain jobs.

If something feels missing, it probably belongs in [Reference](reference/index.md).
