# ai-job-server

REST API and browser UI for queuing AI jobs: text generation, voice synthesis, and image generation. Jobs run as background tasks; outputs are stored as plain directories on disk. No database required.

Runs on port **8090**. Designed for LAN use — no authentication, no CORS.

---

## Requirements

- Python 3.11+
- [OmniVoice](https://github.com/k2-fsa/OmniVoice) (`omnivoice-infer` on PATH) for voice jobs
- ComfyUI on `127.0.0.1:8188` for image jobs (accepted and queued; backend integration is a stub)
- An OpenAI-compatible LLM API for chain jobs (e.g. Ollama on another machine)

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Running

**Development** (hot-reload):
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --reload
```

**Production** (single worker required):
```bash
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090 --workers 1
```

The browser UI is at `http://<host>:8090/`.

**Environment variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `JOBS_BASE` | `/srv/ai-jobs` | Root directory for job storage (created automatically) |
| `OMNIVOICE_CONFIG_PATH` | `<repo>/config/omnivoice.json` | Override path for the OmniVoice config file |

---

## Tests

```bash
source .venv/bin/activate
.venv/bin/pytest tests/test_chain.py -v   # chain tests — must always pass
.venv/bin/pytest tests/ -v               # full suite (voice tests have known pre-existing failures)
```

---

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/architecture.md`](docs/architecture.md) | Module map, job lifecycle, chain execution flow, design decisions |
| [`docs/api.md`](docs/api.md) | Complete REST API reference with request/response schemas and curl examples |
| [`docs/chain-jobs.md`](docs/chain-jobs.md) | Chain step types, template variables, sequences, MCP tools, voice auto-segmentation |
| [`docs/configuration.md`](docs/configuration.md) | Environment variables, `omnivoice.json` fields, `config/` directory layout, external services |

---

## Quick start — chain job

```bash
curl -s -X POST http://localhost:8090/v1/jobs/chain \
  -H 'Content-Type: application/json' \
  -d '{
    "input": "Write a short poem about the sea.",
    "llm": {
      "api_base": "http://your-llm-host:11434/v1",
      "model": "gemma4"
    },
    "steps": [
      { "name": "Write", "type": "llm", "prompt": "{{input}}" }
    ]
  }'

# Poll until done
curl -s http://localhost:8090/v1/jobs/<job_id>/files/status.json | python3 -m json.tool

# Fetch output
curl -s http://localhost:8090/v1/jobs/<job_id>/files/final_output.txt
```
