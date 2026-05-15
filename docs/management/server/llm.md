# Server / LLM

Manages **LLM presets** — saved OpenAI-compatible endpoints. Chain LLM steps and voice auto-segmentation use these as their default backend.

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
| GET | `/v1/llm-presets` | List |
| POST | `/v1/llm-presets` | Upsert (payload with `id` updates; without, creates) |
| DELETE | `/v1/llm-presets/{id}` | Remove |
| PUT | `/v1/llm-presets/default` | Set default by id |
