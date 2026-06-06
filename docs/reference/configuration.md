# Configuration

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JOBS_BASE` | `/srv/ai-jobs` | Root for all job storage. Created on first use. |
| `OMNIVOICE_CONFIG_PATH` | `<repo>/config/omnivoice.json` | Override the OmniVoice config path. |
| `AI_JOB_SERVER_CONFIG_PATH` | `<repo>/config/server.json` | Override the multi-machine server config path. |

```bash
JOBS_BASE=/data/ai-jobs .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
```

## `config/` directory

Lives at the repo root, gitignored, created automatically.

```
config/
  server.json
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

## `config/server.json`

Declares this node's role in a multi-machine fleet. If absent, the server defaults to **all capabilities enabled** (single-machine mode — backwards compatible). Ship a `config/server.json.example` alongside the real file in the repo.

```json
{
  "role": "primary",
  "capabilities": ["web", "voice", "image"],
  "peers": [
    { "name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"] }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `role` | string | Informational tag (`"primary"` or `"secondary"` by convention) — does **not** drive behavior |
| `capabilities` | string[] | Subsystems this node serves: any of `"web"`, `"voice"`, `"image"`, `"llm"` |
| `peers[].name` | string | Stable identifier for the peer |
| `peers[].host` | string | Hostname (mDNS `.local`) or IP |
| `peers[].port` | int | HTTP port (default `8090`) |
| `peers[].capabilities` | string[] | Subsystems hosted on that peer |

The `capabilities` array is the contract: routes that need a missing capability return HTTP 503 with `{ "error": "capability_unavailable", "needed": "<cap>", "where": "<peer-host>" }`. See [API → Server → Capability gating](api.md#capability-gating) and the [multi-machine plan](multi-machine-plan.md) for the full design.

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

## System dependencies

- **ffmpeg** — required on the **web** node for Speech-to-Text (`POST /v1/jobs/stt`,
  audio → 16 kHz mono WAV) and for Vision uploads whose format llama.cpp can't decode
  natively — notably **WebP**, which is transcoded to PNG first (`POST /v1/jobs/vision`;
  PNG/JPEG pass through untouched). Install with `apt-get install -y ffmpeg`. Without it,
  an STT job — or a WebP Vision job — ends in `error` with a clear message in its
  `logs.txt`; PNG/JPEG Vision jobs are unaffected.

## Vision / Speech-to-Text (multimodal)

Both features run the **same** multimodal preset on the `llm` node (one model + mmproj
serves vision *and* audio, so switching between them never reloads). Configure:

- `config/llamacpp.json` → `multimodal_preset` — name of the preset to load (default
  `"gemma-4-e4b-mm"`). Set to `null` to disable the features (they 503).
- `config/llm_presets/<name>.json` (on the `llm` node) — the model + mmproj. Example:

```json
{
  "name": "gemma-4-e4b-mm",
  "model_path": "/abs/path/Gemma-4-E4B-…-Q8_K_P.gguf",
  "args": { "ctx_size": 16384, "n_gpu_layers": 99, "flash_attn": "on", "jinja": true,
            "mmproj": "/abs/path/mmproj-Gemma-4-E4B-…-f16.gguf" },
  "capabilities": ["text", "vision"]
}
```

`model_path`/`mmproj` must be **absolute** (no `~` expansion). Vision/STT run as JobQueue
jobs (`POST /v1/jobs/{vision,stt}`, multipart upload) like image/voice — each gets a job
dir with `logs.txt` and an `output.txt` result artifact. The runner swaps the `llm` node's
`llama-server` to this preset via the existing hash-based `ensure-loaded` and leaves it
resident; the next normal chain LLM step swaps back to `default_preset`.

**Truncated descriptions / transcripts.** Image embeddings consume a large share of
context, so a small preset `ctx_size` (or an `n_predict` cap) would truncate long Vision
descriptions / STT transcripts mid-sentence. To prevent this, the multimodal swap loads
the preset with **boosted args**: `ctx_size` is raised to at least `multimodal_min_ctx`
(default **8192**, in `config/llamacpp.json` on the web node; never lowers a larger value)
and any `n_predict` output cap is dropped — applied inline at load time, so the stored
preset on the llm node is left untouched. Lower `multimodal_min_ctx` if that node is
VRAM-constrained. The runner also logs the stop reason to each job's `logs.txt` (visible in
the OutputConsole): `[generate] finish_reason=length completion_tokens=… prompt_tokens=…`;
`finish_reason=stop` means the model finished naturally, `length` means a limit was still
hit (raise `multimodal_min_ctx` further, or `max_tokens` in `service.py`).

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
