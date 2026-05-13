# ai-job-server — Design

This document covers the motivation behind the system, how the design evolved, and the key tradeoffs made along the way.

---

## Original goals (May 2026)

The system started as a thin REST wrapper around two AI backends:

- **ComfyUI** (image generation) on `127.0.0.1:8188`
- **OmniVoice** (TTS) invoked as a subprocess

The core idea was file-based jobs: every request becomes a directory on disk with `request.json`, `status.json`, `logs.txt`, and output files. No database. Human-readable. Easy to back up.

The browser UI was the primary interface — curl was secondary.

---

## What was actually built

The system grew significantly beyond the original two job types:

### Chain jobs

A chain job is a sequence of steps that run in order, passing `text_output` between them. Step types:

- **`llm`** — sends a rendered prompt to an OpenAI-compatible LLM API; supports MCP tools
- **`voice`** — synthesizes text to audio via OmniVoice; supports auto-segmentation with LLM-assigned pause timings
- **`write_context`** — saves the current text output into the context library for use in later chains
- **`sequence`** — expands a saved sequence inline (reusable step groups)

Chains are the primary way to do multi-step LLM + TTS workflows. The chain executor expands `sequence` references recursively (depth-capped at 20), then runs steps in a flat loop.

### MCP tools

A small built-in tool registry wired into the LLM step's tool loop:

- `random_integer` — random number in a range
- `generate_name` — random US name (gender, middle name options)
- `format_voice_segments` — used internally by voice auto-segmentation to return structured segment data

The executor handles both the standard OpenAI `tool_calls` protocol and a regex fallback for llama.cpp servers (Gemma 4) that emit tool calls as `<tool_call>…</tool_call>` content tokens.

### Voice presets

Named voice samples (3–10s WAV files) stored in `config/voice_presets/`. Voice steps and direct voice jobs reference a preset by ID rather than uploading audio every time.

### Context library

A flat library of text items with titles, tags, and content. Chain LLM steps can reference items by ID; the content is injected as `{{context}}` in the prompt template. A `write_context` step can save step output back to the library for later chains.

### Sequences

Saved, reusable step lists. A `sequence` step in a chain expands inline. Cycle detection (DFS) runs at save time and returns 422; a depth guard at run time catches cycles that slip through (e.g., sequences added after the cycle check).

### Server domain

Live resource stats (CPU, memory, disk, job counts), hot-restart via `os.execv`, and a Fibonacci-backoff reconnection UI when the server is restarting.

---

## What was not built

- **ComfyUI integration**: Image jobs are accepted and queued but the ComfyUI submission logic is a stub. The job transitions to `running` and stays there (no processing). This was deprioritized in favor of chain/LLM work.
- **Authentication**: The server is LAN-only with no auth. This was an explicit non-goal.
- **SSE / WebSocket push**: The UI polls `status.json` every few seconds. The original design mentioned `GET /v1/jobs/{job_id}/events` (SSE) but it was never implemented; polling is good enough for the workload.
- **Multi-worker support**: The job system uses in-process background tasks and a process-level job-count cache. Single worker only — explicit in the production docs.

---

## Key design decisions

### File-based jobs, no database

Every job is a directory. `status.json` is the source of truth. This makes jobs easy to inspect with shell tools, trivial to back up, and immune to database version/migration issues. The tradeoff is no atomic cross-job queries — acceptable for human-scale LAN traffic.

### OpenAI-compatible LLM API

The chain executor uses a generic OpenAI-compatible client (`llm_client.py`) that works with any server that speaks the OpenAI chat completions protocol — Ollama, llama.cpp, OpenAI itself. The model and API base are specified per-job, not globally. This keeps the server backend-agnostic.

### httpx, not requests

All HTTP calls use `httpx` with `async with httpx.AsyncClient()`. This is required for compatibility with FastAPI's async event loop — `requests` is synchronous and would block the event loop during LLM calls.

### Static SPA UI, no template engine

All pages are served as static files by FastAPI's `StaticFiles` mount. Each page is a self-contained SPA. A shared `nav.js` script generates the top nav dynamically from a config array and auto-marks the active page. This gives the benefit of a shared nav without requiring Jinja2 or any build step — changes to HTML/CSS/JS are visible on browser refresh.

### Step runner isolation

Each step type (`llm`, `voice`, `write_context`) lives in its own module under `app/chain/steps/`. Runners raise exceptions on failure; the executor in `executor.py` owns all status writes and log appends. Step modules never import from `executor.py`, preventing circular imports.

### Config directory, gitignored

All runtime user data (voice samples, context text, sequences, OmniVoice settings) lives in `config/` at the repo root. It is gitignored and created automatically on first use. This keeps user data off git and makes the repo safe to push without scrubbing.

---

## Architecture summary

See [`architecture.md`](architecture.md) for the full module map and job lifecycle. See [`api.md`](api.md) for the complete API reference.
