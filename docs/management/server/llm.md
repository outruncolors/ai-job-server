# Server / LLM

Manages **LLM endpoint presets** — saved OpenAI-compatible HTTP endpoints. Chain LLM steps and voice auto-segmentation use these as their default backend.

(Not to be confused with **LLM model presets** at `/llm-presets/`, which configure which GGUF and CLI args `llama-server` spawns with. See the [LLM Models page](../../tools/llm-presets.md) — endpoint presets and model presets live at different layers.)

## What's on the page

- **Left** — list of presets with a "+ New" button. The default preset is marked with a badge.
- **Right** — edit form with:
  - **Name**
  - **API base URL** (e.g. `http://debian1.local:11434/v1`)
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
