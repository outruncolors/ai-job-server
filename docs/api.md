# API Reference

Base path for all API routes: the server runs on port `8090`. All routes under `/v1/` are the REST API. `/health` is a special case.

---

## Health

### `GET /health`

Returns server liveness.

**Response 200:**
```json
{ "status": "ok", "timestamp": "2026-05-13T12:00:00Z" }
```

---

## Jobs

### `POST /v1/jobs/image` → 202

Submit an image generation job.

**Request body:**
```json
{
  "prompt": "a cat on the moon",
  "width": 512,
  "height": 512,
  "steps": 20,
  "model": null,
  "negative_prompt": null
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | string | **required** | Image prompt |
| `width` | int | 512 | Width in pixels |
| `height` | int | 512 | Height in pixels |
| `steps` | int | 20 | Diffusion steps |
| `model` | string\|null | null | Model override |
| `negative_prompt` | string\|null | null | Negative prompt |

**Response:**
```json
{ "job_id": "uuid", "job_type": "image", "status": "queued", "created_at": "..." }
```

---

### `POST /v1/jobs/voice` → 202

Submit a voice synthesis job.

**Request body (single segment):**
```json
{
  "text": "Hello, world!",
  "voice_preset_id": "uuid",
  "speed": 1.0,
  "language": "English"
}
```

**Request body (multi-segment):**
```json
{
  "segments": [
    { "text": "First sentence.", "delay_ms": 600 },
    { "text": "Second sentence.", "delay_ms": 0 }
  ],
  "voice_preset_id": "uuid",
  "speed": 1.0
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string\|null | null | Text to speak (provide `text` or `segments`) |
| `segments` | array\|null | null | Ordered segments with inter-segment silence |
| `voice` | string | `"default"` | Voice name (legacy; prefer `voice_preset_id`) |
| `voice_preset_id` | string\|null | null | ID from `/v1/voice-presets` |
| `speed` | float | 1.0 | Playback speed (0.25–4.0) |
| `language` | string\|null | null | Language hint (e.g. `"English"`, `"Chinese"`) |
| `instruct` | string\|null | null | Instruction tags (e.g. `"Female, Young Adult"`) |
| `num_step` | int\|null | null | Diffusion steps (4–64) |
| `guidance_scale` | float\|null | null | Guidance scale (0–4) |

One of `text` or `segments` is required. For `segments`, `delay_ms` is the silence after that segment (0 for the last).

**Response:** same 202 shape as image jobs.

---

### `POST /v1/jobs/chain` → 202

Submit a chain job. See [chain-jobs.md](chain-jobs.md) for full details.

**Request body:**
```json
{
  "input": "Write a poem about autumn.",
  "llm": {
    "api_base": "http://debian1.local:11434/v1",
    "model": "gemma4",
    "temperature": 0.7,
    "max_tokens": 2048
  },
  "steps": [
    {
      "name": "Step 1",
      "type": "llm",
      "prompt": "{{input}}"
    }
  ]
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `input` | string | `""` | Initial text passed to the first step as `{{input}}` |
| `llm` | object | **required** | LLM config used for all llm and voice steps |
| `llm.api_base` | string | **required** | OpenAI-compatible API base URL |
| `llm.model` | string | **required** | Model name |
| `llm.temperature` | float | 0.7 | Temperature (0–2) |
| `llm.max_tokens` | int | 2048 | Max tokens per LLM call |
| `llm.timeout_seconds` | int | 120 | HTTP timeout for LLM calls |
| `steps` | array | **required** | One or more step objects (see chain-jobs.md) |

**Response:** same 202 shape as other job types.

---

### `GET /v1/jobs`

List all jobs across all dates, sorted newest-first in the UI (unsorted at API level).

**Response:**
```json
{
  "jobs": [
    {
      "job_id": "uuid",
      "job_type": "chain",
      "status": "done",
      "created_at": "...",
      "updated_at": "...",
      "error": null
    }
  ],
  "total": 1
}
```

---

### `DELETE /v1/jobs`

Remove all jobs with `status == "queued"` from disk.

**Response:** `{ "removed": 3 }`

---

### `GET /v1/jobs/{job_id}`

Get full status for one job.

**Response:** `JobStatus` object (same shape as items in the list response).

**Error:** 404 if not found.

---

### `DELETE /v1/jobs/{job_id}`

Delete a job and all its files from disk.

**Response:** `{ "deleted": "uuid" }`

**Error:** 404 if not found.

---

### `GET /v1/jobs/{job_id}/steps`

Get the step-by-step execution status for a chain job.

**Response:**
```json
{
  "steps": [
    {
      "id": "Step_1",
      "name": "Step 1",
      "type": "llm",
      "status": "done",
      "started_at": "...",
      "completed_at": "...",
      "error": null,
      "output_file": "output.txt",
      "tools": []
    }
  ]
}
```

Returns an empty list for non-chain jobs or if the job hasn't started yet.

---

### `GET /v1/jobs/{job_id}/files/{filename}`

Download a file from the job directory. `filename` is a path relative to the job directory and may include `/` (e.g. `steps/001_step_1/output.txt`).

**Response:** file content with appropriate MIME type.

**Error:** 404 if the file does not exist.

Common filenames:
- `request.json` — original request
- `status.json` — current status (poll this to track progress)
- `logs.txt` — execution log
- `artifacts.json` — list of output files
- `final_output.txt` — final LLM text output (chain jobs)
- `output.wav` — synthesized audio (voice jobs, or in step subdirs)

---

## Chain Sequences

### `GET /v1/chain-sequences`

List saved sequences.

**Response:** `{ "sequences": [ { "id": "uuid", "name": "My Seq", "steps": [...], "updated_at": "..." } ] }`

---

### `POST /v1/chain-sequences`

Create or update a sequence (upsert by name).

**Request body:**
```json
{ "name": "My Sequence", "steps": [ { "name": "Step 1", "type": "llm", "prompt": "..." } ] }
```

**Response:** the saved sequence object.

**Error:** 422 if cycle detected.

---

### `DELETE /v1/chain-sequences/{seq_id}`

Delete a sequence by ID.

**Response:** `{ "ok": true }`

**Error:** 404 if not found.

---

### `POST /v1/chain-sequences/{seq_id}/duplicate`

Create a copy of an existing sequence (name gets ` (copy)` suffix).

**Response:** the new sequence object.

**Error:** 404 if not found.

---

## Context Items

### `GET /v1/context-items`

List all context library items.

**Response:** `{ "items": [ { "id": "uuid", "title": "...", "tags": [...], "description": "...", "content": "...", "created_at": "..." } ] }`

---

### `POST /v1/context-items` → 201

Create a context item.

**Request body:**
```json
{ "title": "My Notes", "tags": ["reference"], "description": "Short desc", "content": "Full text..." }
```

---

### `GET /v1/context-items/{item_id}`

Get a single item.

**Error:** 404 if not found.

---

### `PUT /v1/context-items/{item_id}`

Update a context item. All fields are optional; only supplied fields are replaced.

**Error:** 404 if not found.

---

### `DELETE /v1/context-items/{item_id}`

Delete a context item.

**Response:** `{ "ok": true }`

**Error:** 404 if not found.

---

## Voice Presets

### `GET /v1/voice-presets`

List all presets.

**Response:** array of `{ "id": "uuid", "name": "Alice", "caption": "...", "wav_filename": "...", "created_at": "..." }`

---

### `POST /v1/voice-presets` → 201

Upload a WAV file as a new preset. Uses `multipart/form-data`.

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | WAV file, must be 3–10 seconds |
| `name` | string | Display name for the preset |
| `caption` | string | Exact words spoken in the sample |

**Error:** 422 if file is not WAV, unreadable, or outside the 3–10s range.

---

### `POST /v1/voice-presets/from-job` → 201

Save `output.wav` from an existing voice job as a preset.

**Request body:**
```json
{ "job_id": "uuid", "name": "Alice", "caption": "Hello world" }
```

**Error:** 404 if job or output.wav not found; 422 if duration out of range.

---

### `DELETE /v1/voice-presets/{preset_id}`

Delete a preset (removes metadata and WAV file).

**Response:** `{ "deleted": "uuid" }`

**Error:** 404 if not found.

---

## MCP Tools

### `GET /v1/mcp/tools`

List all registered tools.

**Response:**
```json
{
  "tools": [
    {
      "name": "random_integer",
      "description": "...",
      "input_schema": { "properties": { ... }, "required": [...] }
    }
  ]
}
```

---

### `POST /v1/mcp/tools/{name}/call`

Execute a tool directly.

**Request body:**
```json
{ "arguments": { "min": 1, "max": 100 } }
```

**Response (success):**
```json
{ "result": 42, "execution_ms": 0.3, "timestamp": "..." }
```

**Response (validation error):**
```json
{ "error": "min is required", "validation_status": "invalid_arguments" }
```

**Error:** 404 if tool name not found.

---

## OmniVoice

### `GET /v1/omnivoice/status`

Check whether the ephemeral TTS runner is available and how many voice jobs are active.

**Response:** `{ "ephemeral_available": true, "active_voice_jobs": 0, "infer_base_command": [...] }`

---

### `GET /v1/omnivoice/config`

Read the current OmniVoice configuration.

**Response:** `OmniVoiceConfig` object (see [configuration.md](configuration.md) for field descriptions).

---

### `PUT /v1/omnivoice/config`

Replace the entire OmniVoice configuration and persist it to `config/omnivoice.json`.

**Request/Response:** `OmniVoiceConfig` object.

---

## Server

### `GET /v1/server/stats`

Current resource usage and job counts.

**Response:**
```json
{
  "cpu_percent": 12.4,
  "memory": { "used": 4294967296, "total": 8589934592, "percent": 50.0 },
  "disk": { "used": 10737418240, "total": 107374182400, "percent": 10.0 },
  "uptime_seconds": 3600.5,
  "jobs": { "queued": 0, "running": 1, "done": 42, "failed": 2 },
  "hostname": "debian2",
  "python_version": "3.13.0"
}
```

Job counts are cached for 5 seconds to avoid scanning the job directory on every poll.

---

### `POST /v1/server/restart`

Schedule a hot restart via `os.execv`. The server re-executes itself — existing jobs in the background task queue are lost, but completed jobs on disk are preserved. The UI polls `/health` during reconnection.

**Response:** `{ "ok": true, "message": "Restart scheduled" }`

---

## curl examples

```bash
# Submit a chain job
curl -s -X POST http://debian2.local:8090/v1/jobs/chain \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello","llm":{"api_base":"http://debian1.local:11434/v1","model":"gemma4"},"steps":[{"name":"Step 1","type":"llm","prompt":"{{input}}"}]}'

# Poll status
curl -s http://debian2.local:8090/v1/jobs/<job_id>/files/status.json | python3 -m json.tool

# List all jobs
curl -s http://debian2.local:8090/v1/jobs

# Call an MCP tool
curl -s -X POST http://debian2.local:8090/v1/mcp/tools/random_integer/call \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"min":1,"max":100}}'
```
