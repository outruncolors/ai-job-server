# ai-job-server

REST API for queuing AI jobs (image generation, voice generation). Stores every job as a directory on disk. ComfyUI and OmniVoice integration is not wired yet — jobs are accepted and queued but no backend processing runs.

## Requirements

- Python 3.11+
- Disk space under `/srv/ai-jobs` (created automatically)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

The browser UI is available at `http://localhost:8090/`.

To change the job storage directory:

```bash
JOBS_BASE=/data/ai-jobs uvicorn app.main:app --host 0.0.0.0 --port 8090
```

## API

### POST /v1/jobs/image

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

### POST /v1/jobs/voice

```json
{
  "text": "Hello, world!",
  "voice": null,
  "speed": 1.0,
  "language": null
}
```

Both return `202 Accepted`:

```json
{
  "job_id": "uuid",
  "job_type": "image",
  "status": "queued",
  "created_at": "2026-05-09T00:00:00Z"
}
```

### GET /v1/jobs

Returns `{ "jobs": [...], "total": N }`.

### GET /v1/jobs/{job_id}

Returns full job status.

### GET /v1/jobs/{job_id}/files/{filename}

Download a file from the job directory. Available files: `request.json`, `input.txt`, `status.json`, `logs.txt`, `artifacts.json`, `output.png`, `output.wav`.

### GET /health

```json
{ "status": "ok", "timestamp": "..." }
```

## Job directory layout

```
/srv/ai-jobs/YYYY-MM-DD/<job_id>/
├── request.json    # original request body
├── input.txt       # human-readable input (prompt or text)
├── status.json     # current job status
├── logs.txt        # worker logs (empty until processing starts)
└── artifacts.json  # list of output files (empty until done)
```

## Tests

```bash
source .venv/bin/activate
pytest tests/ -v
```
