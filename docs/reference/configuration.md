# Configuration

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JOBS_BASE` | `/srv/ai-jobs` | Root for all job storage. Created on first use. |
| `OMNIVOICE_CONFIG_PATH` | `<repo>/config/omnivoice.json` | Override the OmniVoice config path. |

```bash
JOBS_BASE=/data/ai-jobs .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
```

## `config/` directory

Lives at the repo root, gitignored, created automatically.

```
config/
  omnivoice.json
  comfyui.json
  llm_config.json
  chain_sequences/index.json
  context_items/index.json
  wildcards/index.json
  ticks/index.json
  voice_presets/
    index.json
    <id>.wav
  comfyui-workflows/
    <name>.json
  comfyui-server.stdout.log
  comfyui-server.stderr.log
```

Never commit `config/`. It holds user data — voice samples, prompt text, LLM endpoints — that belongs on the machine running the server.

## `config/omnivoice.json`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"k2-fsa/OmniVoice"` | Model identifier passed to infer |
| `response_format` | string | `"wav"` | |
| `voice` | string | `"default"` | Legacy; prefer voice presets |
| `speed` | float | 1.0 | 0.25–4.0 |
| `language` | string\|null | null | Default language hint |
| `instruct` | string\|null | null | Default voice trait tags |
| `ref_audio_filename` | string\|null | null | Reference audio for voice cloning |
| `ref_text` | string\|null | null | Reference transcript |
| `infer_base_command` | string[]\|null | null | Defaults to `["omnivoice-infer"]` |
| `voice_preprocess_prompt` | string\|null | null | Custom; null uses built-in |
| `voice_auto_segment_prompt` | string\|null | null | Custom; null uses built-in |

Edit directly or via `PUT /v1/omnivoice/config`.

## `config/comfyui.json`

See [Server / ComfyUI](../management/server/comfyui.md#config-panel) for the field list and [ComfyUI Setup](../generation/visual/comfyui-setup.md) for the 3090 Ti defaults.

## `config/llm_config.json`

```json
{
  "presets": [
    { "id": "...", "name": "...", "api_base": "...", "model": "...",
      "temperature": 0.7, "max_tokens": 1024, "timeout": 60 }
  ],
  "default_preset_id": "..."
}
```

Managed through [Server / LLM](../management/server/llm.md).

## External services

| Service | Address | Notes |
|---------|---------|-------|
| LLM API | per chain job (`llm.api_base`) | OpenAI-compatible; LLM presets supply the default |
| OmniVoice | subprocess via `infer_base_command` | Spawned per voice job |
| ComfyUI | `http://127.0.0.1:8188` | Managed by `ComfyUIManager`; adopted if already running |

## Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

Static files are served directly from `static/` by FastAPI's `StaticFiles` mount. Edits to HTML/CSS/JS are visible on browser refresh — no build step. CORS is not configured; this is a LAN-only service.

## Production

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --workers 1
```

Single worker only — background tasks and the job-count cache are process-local. The hot restart endpoint uses `os.execv`; in-flight background tasks are *not* drained, so a restart during an active job will leave it in `running` state until the new process restarts and a subsequent job triggers cleanup (or until manual intervention via `DELETE /v1/jobs`).

## Tests

```bash
.venv/bin/pytest tests/ -v
```

`tests/test_omnivoice.py` and `tests/test_voice_presets.py` require a live OmniVoice subprocess and are skipped in normal runs. Everything else is expected to pass.
