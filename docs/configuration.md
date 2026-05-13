# Configuration

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JOBS_BASE` | `/srv/ai-jobs` | Root directory for all job storage. Created automatically if it does not exist. |
| `OMNIVOICE_CONFIG_PATH` | `<repo>/config/omnivoice.json` | Override path for the OmniVoice config file. |

Example:
```bash
JOBS_BASE=/data/ai-jobs uvicorn app.main:app --host 0.0.0.0 --port 8090
```

---

## `config/omnivoice.json`

Stores runtime TTS settings. Created automatically with defaults on first use. Edit directly or via `PUT /v1/omnivoice/config`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `model` | string | `"k2-fsa/OmniVoice"` | Model identifier passed to the infer command |
| `response_format` | string | `"wav"` | Output format (`"wav"`) |
| `voice` | string | `"default"` | Voice name (legacy; prefer voice presets) |
| `speed` | float | 1.0 | Global playback speed (0.25–4.0) |
| `language` | string\|null | null | Default language hint |
| `instruct` | string\|null | null | Default instruction tags (e.g. `"Female, Young Adult"`) |
| `ref_audio_filename` | string\|null | null | Reference audio filename for voice cloning (relative to preset dir) |
| `ref_text` | string\|null | null | Text transcript of the reference audio |
| `infer_base_command` | string[]\|null | null | Command to invoke OmniVoice inference. Null uses `["omnivoice-infer"]`. |
| `voice_preprocess_prompt` | string\|null | null | Custom LLM prompt for text pre-processing before TTS. Null uses the built-in default. |
| `voice_auto_segment_prompt` | string\|null | null | Custom LLM prompt for voice auto-segmentation. Null uses the built-in default. |

Example config:
```json
{
  "model": "k2-fsa/OmniVoice",
  "response_format": "wav",
  "voice": "default",
  "speed": 1.0,
  "language": null,
  "instruct": null,
  "ref_audio_filename": null,
  "ref_text": null,
  "infer_base_command": null,
  "voice_preprocess_prompt": null,
  "voice_auto_segment_prompt": null
}
```

---

## `config/` directory layout

The `config/` directory lives at the repo root and is gitignored. It is created automatically on first use.

```
config/
  omnivoice.json          OmniVoice runtime settings
  sequences.json          Saved chain sequences (array)
  context_library.json    Context item index + content (array)
  voice_presets/
    index.json            Voice preset metadata (array)
    <id>.wav              Voice sample WAV files (one per preset, 3–10s)
```

Never commit `config/`. It contains user data (voice samples, context text, LLM configs) that should stay on the machine running the server.

---

## External service dependencies

| Service | Default address | Purpose |
|---------|----------------|---------|
| LLM API | `http://debian1.local:11434/v1` | OpenAI-compatible LLM for chain llm steps. Configured per-job in the `llm.api_base` field, not globally. |
| OmniVoice / TTS | Subprocess via `infer_base_command` | Text-to-speech synthesis. The job server spawns an ephemeral subprocess per voice job. |
| ComfyUI | `http://127.0.0.1:8188` | Image generation backend. Image jobs are accepted and queued but backend integration is not implemented. |

The LLM address is set per chain job in the request body (`llm.api_base`). There is no server-wide LLM URL setting — the UI's LLM preset system (stored in `localStorage`) handles the default.

---

## Running in development

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start with hot-reload
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

The static files are served directly from `static/` by FastAPI's `StaticFiles` mount. Changes to HTML, CSS, and JS files are visible immediately on browser refresh — no build step required.

CORS is not configured. The server is intended for LAN use only.

---

## Running in production

```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --workers 1
```

Use a single worker. The job system uses in-process background tasks and a shared process-level cache (`_get_job_counts` in `server.py`) that would not survive across workers.

The server supports hot restarts via `POST /v1/server/restart`, which calls `os.execv` to re-execute itself in-place. In-flight background tasks (running jobs) are not gracefully drained — a restart during an active job will leave it in `running` state on disk. The UI reconnects automatically using Fibonacci backoff.

---

## Tests

```bash
source .venv/bin/activate
.venv/bin/pytest tests/ -v
```

Known pre-existing failures: `tests/test_omnivoice.py` and `tests/test_voice_presets.py`. These test OmniVoice integration that requires a live subprocess and are not related to chain or context work.

The full chain test suite (`tests/test_chain.py`) must pass at all times:
```bash
.venv/bin/pytest tests/test_chain.py -v
```
