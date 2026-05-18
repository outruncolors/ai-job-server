# Server / LLM

Two sub-tabs sitting under one page:

- **Models** — llama.cpp load presets (what GGUF + CLI args to load on the LLM-capable peer). Reads/writes `/v1/llm-presets`. Full schema reference in [LLM Models](../../tools/llm-presets.md).
- **Endpoints** — OpenAI-compatible HTTP destinations (where to POST chat completions). Reads/writes `/v1/llm-endpoints`.

Both surfaces lived as separate pages before multi-machine; the consolidation makes the relationship between them visible. When a chain LLM step has a preset selected (or `default_preset` is set in the peer's `config/llamacpp.json`), the **endpoint's api_base + model fields are overridden at runtime** to point at the LLM-capable peer — so for a typical multi-machine setup the endpoint values are placeholders. Endpoints still matter for voice auto-segmentation and legacy chains without a preset.

## Models sub-tab

See [LLM Models](../../tools/llm-presets.md) — same UI, same data, same endpoints, now mounted as a sub-tab.

## Endpoints sub-tab

- **Left** — list of endpoints with a "+ New" button. The default endpoint is marked with a badge.
- **Right** — edit form with:
  - **Name**
  - **API base URL** (e.g. `http://gpu.local:8080/v1`)
  - **Model**
  - **Temperature** (0–2)
  - **Max tokens**
  - **Timeout (s)**
- **Save** / **Set as Default** / **Delete**

## Data model

`config/llm_config.json` (`LLMConfigDoc` in `app/llm_config.py`):

```json
{
  "presets": [
    {"id": "...", "name": "...", "api_base": "...", "model": "...",
     "temperature": 0.7, "max_tokens": 1024, "timeout": 60}
  ],
  "default_preset_id": "..."
}
```

The default preset is the one [ticks](../../tools/ticks.md) and any chain submitted without an inline `llm` block will use.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/llm-endpoints` | List |
| POST | `/v1/llm-endpoints` | Upsert (payload with `id` updates; without, creates) |
| DELETE | `/v1/llm-endpoints/{id}` | Remove |
| PUT | `/v1/llm-endpoints/default` | Set default by id |

> Prior to the multi-machine work this route lived at `/v1/llm-presets`; `/v1/llm-presets` now addresses llama.cpp **model load** presets (a different concept).
