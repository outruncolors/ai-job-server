# LLM Models

LLM model presets are named load configurations for the local llama.cpp server (`llama-server`). Each preset bundles the GGUF model path, CLI args (context size, GPU layer count, flash attention, multimodal projector, etc.), and capability tags. The llama.cpp manager swaps between them on demand.

**UI location:** [Server → LLM → Models](../management/server/llm.md) sub-tab, alongside the Endpoints sub-tab so models and endpoints sit side-by-side.

**Companion concept:** [LLM endpoints](../management/server/llm.md) — the other sub-tab — describe *where chain LLM steps send HTTP requests*. Models describe *what llama.cpp loads*. When a chain step has a preset selected, the endpoint values are overridden at runtime to point at the LLM-capable peer.

## What's on the page

- **Left** — list of models, each showing name, description (or model path) and capability tags
- **Right** — editor:
  - **Name** — kebab-case, used as the filename (`config/llm_presets/<name>.json`)
  - **Description** — optional
  - **Model path** — absolute path on the LLM machine (e.g. `/opt/ai-stack/models/gemma-3-27b-q4.gguf`)
  - **Capabilities** — `text` (always on) and `vision` (toggle)
  - **Args** — `--key value` pairs forwarded to `llama-server`. Each row has a key and value; the value parses as bool / int / float / `null` / string. `true` becomes a bare `--flag`; `null` / empty is omitted.

## Data model

Each preset is a separate JSON file:

```json
// config/llm_presets/gemma-3-27b-highctx.json
{
  "name": "gemma-3-27b-highctx",
  "model_path": "/opt/ai-stack/models/gemma-3-27b-q4.gguf",
  "args": {
    "ctx_size": 32768,
    "n_gpu_layers": 99,
    "flash_attn": true,
    "mmproj": null
  },
  "capabilities": ["text"],
  "description": null
}
```

`config/llm_presets/` is gitignored. Preset names must be kebab-case.

## How presets are used

`POST /v1/llamacpp/ensure-loaded {"preset": "<name>"}` resolves the preset, computes a stable hash over `{model_path, args}`, and either:

- returns immediately if the hash matches the currently-loaded model, or
- terminates the running `llama-server`, spawns a fresh one with the new args, polls `/health` for up to 180 s, and returns 200 once ready.

If the named preset doesn't exist, `ensure-loaded` returns 404. If the new process fails to become healthy in time, it returns 503 — there is **no silent fallback** to the previous model.

## Endpoints

| Method | Path | |
|--------|------|---|
| GET | `/v1/llm-presets` | List |
| GET | `/v1/llm-presets/{name}` | Fetch one |
| POST | `/v1/llm-presets` | Create (409 if name exists) |
| PUT | `/v1/llm-presets/{name}` | Update |
| DELETE | `/v1/llm-presets/{name}` | Remove |
