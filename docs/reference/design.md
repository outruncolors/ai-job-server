# Design

## Goals

A self-hosted REST + browser interface for AI jobs on a LAN. Three job types — chain (LLM + tools), voice (OmniVoice TTS), image (ComfyUI) — plus the tooling around them: a context library, wildcards, schedules, MCP tools, server controls.

The browser is the primary interface. curl is a peer, not an afterthought.

## What's in the box

- **Chain jobs** — multi-step LLM pipelines with `llm`, `voice`, `write_context`, and `sequence` step types. The chain executor expands sequence references recursively (depth-capped at 20) and runs steps in a flat loop.
- **MCP tools** — a small built-in registry (`random_integer`, `generate_name`, `format_voice_segments`) wired into the LLM step's tool loop. Both OpenAI `tool_calls` and Gemma's `<tool_call>` content tokens are handled.
- **Voice presets** — named 3–10 s WAV samples plus captions. Used as reference audio for OmniVoice's speaker-conditioned mode.
- **Context library** — flat list of text items injected into LLM prompts as `{{context}}`. `write_context` steps feed outputs back in.
- **Sequences** — saved, reusable step lists. Cycle detection at save (422) and a depth guard at run time.
- **Wildcards** — `%%token%%` placeholders that expand to weighted random entries across every prompt-bearing field on the site.
- **Ticks** — cron-/interval-driven scheduled runs of a sequence with overlap protection.
- **ComfyUI integration** — long-lived managed subprocess (adopted if already running), workflow validation, prompt injection into the `PROMPT` node, history polling, artifact collection.
- **Server domain** — live resource stats, hot restart via `os.execv`, LLM preset management.

## Non-goals

- **Authentication.** LAN-only by design. If you need auth, terminate at a reverse proxy.
- **Multi-worker.** Background tasks and the job-count cache are process-local. Single uvicorn worker.
- **SSE / WebSocket push.** Status polling is sufficient for human-scale traffic; the simpler model wins.
- **Atomic cross-job queries.** Jobs are directories. If you need joins, query the filesystem.

## Key tradeoffs

**File-based jobs, no database.** Every job is a directory. `status.json` is the source of truth. Easy to inspect, back up, and survive schema changes. No transactions, but the workload doesn't need them.

**Long-lived ComfyUI, ephemeral OmniVoice.** ComfyUI's startup cost is enormous (model loading), so it runs continuously and is adopted by `ComfyUIManager` if it's already alive on the configured port. OmniVoice starts cheaply, so each voice job spawns its own subprocess — no shared state to corrupt.

**Backend-agnostic LLM.** Chain jobs talk OpenAI-compatible chat completions through an httpx client. Ollama, llama.cpp, OpenAI itself, anything else that speaks the protocol. Endpoints are per-job, with a saved preset providing the default — no global URL setting.

**httpx everywhere.** All HTTP is async via `httpx.AsyncClient()` so the FastAPI event loop never blocks during slow LLM or ComfyUI calls.

**Static SPA UI.** No template engine. Each page is a self-contained `index.html` / `styles.css` / `<page>.js` triplet under `static/<page>/`. `nav.js` builds the nav from a shared config array — one change updates every page. Refresh-only iteration.

**Step runner isolation.** Step modules under `app/chain/steps/` are pure work units that raise on failure. The executor owns all status writes and log appends. Step modules don't import from `executor.py`; the dependency graph stays acyclic.

**Config in a gitignored directory.** All user data — voice samples, prompt text, LLM presets, sequences, ComfyUI workflows — lives in `config/` at the repo root. Safe to push the repo. The config directory is created on first use.

## Architecture summary

See [Architecture](architecture.md) for the module map and execution flow. See [API](api.md) for the REST surface.
