# ai-job-server design

This service runs on debian2 and exposes a LAN REST API for AI jobs.

## Goals

- Accept image generation jobs.
- Accept voice generation jobs.
- Store every job as a directory under /srv/ai-jobs.
- Preserve request.json, input.txt, status.json, final output, and logs.
- Hide ComfyUI and OmniVoice behind one API.
- Support a browser UI first.
- Support MCP tools later.

## Runtime services

- ComfyUI on 127.0.0.1:8188
- OmniVoice or TTS server on 127.0.0.1:8091
- ai-job-server on 0.0.0.0:8090

## API

- POST /v1/jobs/image
- POST /v1/jobs/voice
- GET /v1/jobs
- GET /v1/jobs/{job_id}
- GET /v1/jobs/{job_id}/events
- GET /v1/jobs/{job_id}/files/{filename}
- GET /health

## Job directory

/srv/ai-jobs/YYYY-MM-DD/<job_id>/

Required files:

- request.json
- input.txt
- status.json
- logs.txt
- artifacts.json
- output.png or output.wav
