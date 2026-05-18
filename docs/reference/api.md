# API Reference

The server listens on port `8090`. All REST routes are under `/v1/`; `/health` is the exception.

## Health

### `GET /health`

```json
{ "status": "ok", "timestamp": "2026-05-15T12:00:00Z" }
```

## Jobs

### `POST /v1/jobs/image` → 202

Submit an image job. The workflow's `PROMPT` node receives the prompt text.

```json
{ "workflow": "my-workflow", "prompt": "a cat on the moon" }
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `workflow` | string | yes | Workflow filename without `.json`, from `config/comfyui-workflows/` |
| `prompt` | string | yes | Injected into the node titled `PROMPT` |

Response: `{ "job_id", "job_type": "image", "status": "queued", "created_at" }`.

### `POST /v1/jobs/voice` → 202

Submit a TTS job. Use `text` for a single segment, `segments` for multi, `auto_segment` to let an LLM split.

```json
{
  "voice_preset_id": "uuid",
  "segments": [
    { "text": "First sentence.", "delay_ms": 600 },
    { "text": "Second sentence.", "delay_ms": 0 }
  ],
  "speed": 1.0
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | string\|null | null | Provide `text`, `segments`, or `text` with `auto_segment` |
| `segments` | `{text, delay_ms}[]` \| null | null | Ordered segments with trailing silence |
| `auto_segment` | bool | false | Have the LLM split `text` into segments |
| `auto_segment_llm_base_url` | string | – | Required when `auto_segment` is true |
| `auto_segment_llm_model` | string | – | Required when `auto_segment` is true |
| `voice_preset_id` | string\|null | null | Recommended; falls back to `voice` legacy field |
| `voice` | string | `"default"` | Legacy; use `voice_preset_id` |
| `speed` | float | 1.0 | 0.25–4.0 |
| `language` | string\|null | null | |
| `instruct` | string\|null | null | e.g. `"Female, Young Adult"` |
| `num_step` | int\|null | null | Inference steps (4–64) |
| `guidance_scale` | float\|null | null | 0–4 |

### `POST /v1/jobs/chain` → 202

See [Chain](../generation/text/chain.md) for step shapes.

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
    { "name": "Write", "type": "llm", "prompt": "{{input}}" }
  ]
}
```

| Field | Type | Required | |
|-------|------|----------|---|
| `input` | string | no (default `""`) | Available as `{{input}}` |
| `llm` | object | yes | `api_base`, `model`, `temperature`, `max_tokens`, `timeout_seconds` |
| `steps` | array | yes | At least one step |

### `GET /v1/jobs`

Paginated list. Query params: `limit`, `offset`, optional `status`, `type`.

```json
{
  "jobs": [ { "job_id", "job_type", "status", "created_at", "updated_at", "error" } ],
  "total": 42
}
```

### `GET /v1/jobs/{id}`

Full status. 404 if missing.

### `DELETE /v1/jobs/{id}` / `DELETE /v1/jobs` / `DELETE /v1/jobs/all`

| Path | Behaviour |
|------|-----------|
| `DELETE /v1/jobs/{id}` (status=`queued`) | Pops the job off the queue and marks its on-disk status `cancelled`. Returns `{"cancelled": id}`. The job dir is preserved. |
| `DELETE /v1/jobs/{id}` (other statuses) | Removes the job directory. Returns `{"deleted": id}`. Cancel-while-running is out of scope. |
| `DELETE /v1/jobs` | Removes queued + running jobs from disk |
| `DELETE /v1/jobs/all` | Everything |

### `GET /v1/jobs/{id}/steps`

Chain jobs only; returns the per-step status list.

### `GET /v1/jobs/{id}/files/{path}`

Serve any file inside the job directory. `path` may include slashes (e.g., `steps/001_Write/output.txt`).

## Chain sequences

| Method | Path | |
|--------|------|---|
| GET | `/v1/chain-sequences` | List |
| POST | `/v1/chain-sequences` | Upsert by id (422 on cycle) |
| POST | `/v1/chain-sequences/{id}/duplicate` | Copy with `(copy)` suffix |
| DELETE | `/v1/chain-sequences/{id}` | Remove |

## Context items

| Method | Path | |
|--------|------|---|
| GET | `/v1/context-items` | List |
| POST | `/v1/context-items` | Create |
| GET | `/v1/context-items/{id}` | Fetch |
| PUT | `/v1/context-items/{id}` | Partial update |
| DELETE | `/v1/context-items/{id}` | Remove |

## Wildcards

| Method | Path | |
|--------|------|---|
| GET | `/v1/wildcards` | List |
| POST | `/v1/wildcards` | Create |
| PUT | `/v1/wildcards/{id}` | Update |
| DELETE | `/v1/wildcards/{id}` | Remove |

## Ticks

| Method | Path | |
|--------|------|---|
| GET | `/v1/ticks` | List |
| POST | `/v1/ticks` | Upsert |
| DELETE | `/v1/ticks/{id}` | Remove |
| POST | `/v1/ticks/{id}/enable` | `{enabled: bool}` |
| POST | `/v1/ticks/{id}/fire` | Fire now (overlap-guarded unless `force=true`) |
| GET | `/v1/ticks/{id}/recent-jobs` | Jobs fired by this tick |
| POST | `/v1/ticks/preview` | Preview next 3 fires for a cron expression |

## Profiles

A profile is a snapshot of every declarative-config domain (LLM presets, OmniVoice config, ComfyUI config, voice presets, wildcards, context items, image prompts, chain sequences) plus the voice-cloning WAVs those presets reference. ComfyUI workflows are tracked by filename only (their JSON contents live in `config/comfyui-workflows/` and are managed by ComfyUI itself, not by the profile system). Stored profiles live under `config/profiles/<id>/{master.json,assets/voice_presets/}`. Activating a profile re-applies its contents to live config in replace mode; workflow files on disk are never touched, but missing references surface as warnings in the import report.

| Method | Path | |
|--------|------|---|
| GET | `/v1/profiles` | `{ profiles: [...], active_id }` |
| GET | `/v1/profiles/active` | `{ active: {...} \| null }` |
| POST | `/v1/profiles` | `{ name, description? }` — snapshot current live config as a new named profile (name auto-deduped) |
| POST | `/v1/profiles/{id}/activate` | Apply the profile to live config in replace mode and mark active. Returns `{ active_id, domains, assets_copied, asset_warnings }` |
| POST | `/v1/profiles/{id}/overwrite` | Re-snapshot current live config into the existing slot (preserves id/name; bumps `updated_at`). Does NOT touch live config or the active marker. |
| DELETE | `/v1/profiles/{id}` | Remove the profile directory; clears `active_id` if it was the active one |
| GET | `/v1/profiles/{id}/export` | Download the profile as a `.zip` bundle (`master.json` + `assets/voice_presets/...`) with `Content-Disposition: attachment; filename="<name>.zip"` |
| POST | `/v1/profiles/import` | `multipart/form-data` with `file` (the `.zip`), optional `name`, optional `mode`. Without `mode`: unpacks and saves as a new named profile (returns the index entry). With `mode=replace\|merge`: applies the bundle directly to live config without storing (returns the import report). Malformed bundles or unsupported `schema_version` → 422. |

The profile widget pinned to the right edge of every page's nav (`static/js/profiles-widget.js`) wraps these routes as an inline group: `[ select ▾ ] [ 💾 save ] [ ⬇ export ] [ ⬆ import ]`. Changing the select calls `activate`; Save calls `overwrite` on an existing profile or expands into a name input + ✓/✗ for `(new profile)`; Export navigates to the bundle download; Import uploads a `.zip` and saves it as a new named profile.

## Image prompts

Saved text prompts for image generation. `workflow` is optional — `null` means generic, otherwise the workflow name as context. Names are auto-deduplicated (`Foo`, `Foo (2)`, …).

| Method | Path | |
|--------|------|---|
| GET | `/v1/image-prompts` | List → `{ prompts: [...] }` |
| POST | `/v1/image-prompts` | `{ name, prompt, workflow? }` |
| GET | `/v1/image-prompts/{id}` | Fetch one |
| PUT | `/v1/image-prompts/{id}` | Partial update (`name`, `prompt`, `workflow`) |
| DELETE | `/v1/image-prompts/{id}` | Remove |

## Voice presets

| Method | Path | |
|--------|------|---|
| GET | `/v1/voice-presets` | List |
| POST | `/v1/voice-presets` | `multipart/form-data` upload (`file`, `name`, `caption`) — 3–10 s WAV |
| POST | `/v1/voice-presets/from-job` | `{ job_id, name, caption }` — copy from a voice job's `output.wav` |
| DELETE | `/v1/voice-presets/{id}` | Remove |

## LLM presets

| Method | Path | |
|--------|------|---|
| GET | `/v1/llm-presets` | List |
| POST | `/v1/llm-presets` | Upsert |
| DELETE | `/v1/llm-presets/{id}` | Remove |
| PUT | `/v1/llm-presets/default` | `{ id }` |

## MCP tools

| Method | Path | |
|--------|------|---|
| GET | `/v1/mcp/tools` | List with input schemas |
| POST | `/v1/mcp/tools/{name}/call` | `{ "arguments": {...} }` |

Success: `{ "result": ..., "execution_ms": N, "timestamp": "..." }`.
Validation error: `{ "error": "...", "validation_status": "invalid_arguments" }`.

## OmniVoice

| Method | Path | |
|--------|------|---|
| GET | `/v1/omnivoice/status` | `{ ephemeral_available, active_voice_jobs, infer_base_command }` |
| GET | `/v1/omnivoice/config` | Read `omnivoice.json` |
| PUT | `/v1/omnivoice/config` | Replace and persist |

## ComfyUI

| Method | Path | |
|--------|------|---|
| GET | `/v1/comfyui/status` | Alive / PID / uptime / GPU / queue |
| POST | `/v1/comfyui/start` | |
| POST | `/v1/comfyui/stop` | Graceful (SIGTERM → SIGKILL) |
| POST | `/v1/comfyui/restart` | |
| GET | `/v1/comfyui/config` | |
| PUT | `/v1/comfyui/config` | |
| GET | `/v1/comfyui/workflows` | Includes validity info |
| GET | `/v1/comfyui/system_stats` | Passthrough |

## Server

| Method | Path | |
|--------|------|---|
| GET | `/v1/server/stats` | CPU / memory / disk / jobs / `queue_depth` / hostname / python |
| GET | `/v1/server/health` | `status`, `timestamp`, `git_sha`, local `capabilities`, `uptime_seconds`; polled by peers |
| GET | `/v1/server/capabilities` | `{ "local": [...], "peers": [...] }` — UI uses this on load to gate controls |
| GET | `/v1/server/peers` | Configured peers with cached `health` (null until poller lands) |
| POST | `/v1/server/restart` | `os.execv` hot restart |

### Capability gating

Each node declares its capabilities in `config/server.json` (see `config/server.json.example`).
Routes that need a capability the local node lacks return **HTTP 503** with body:

```json
{ "detail": { "error": "capability_unavailable", "needed": "image", "where": "render.local" } }
```

`where` is the host of the first configured peer that owns the missing capability, or `"unknown"`.
Gated routes include `POST /v1/jobs/image` (needs `image`), `POST /v1/jobs/voice` (needs `voice`),
the entire `/v1/comfyui/*` router (needs `image`), and the entire `/v1/omnivoice/*` router (needs `voice`).
Chain jobs are not gated at the route level — they orchestrate locally and call out to peers per step.

## Docs

| Method | Path | |
|--------|------|---|
| GET | `/v1/docs` | Recursive tree of `docs/` |
| GET | `/v1/docs/{path:path}` | File contents (text/plain), `..` rejected |

## curl examples

```bash
# Submit a chain job
curl -s -X POST http://debian2.local:8090/v1/jobs/chain \
  -H 'Content-Type: application/json' \
  -d '{"input":"Hello","llm":{"api_base":"http://debian1.local:11434/v1","model":"gemma4"},"steps":[{"name":"Step 1","type":"llm","prompt":"{{input}}"}]}'

# Poll status
curl -s http://debian2.local:8090/v1/jobs/<job_id> | python3 -m json.tool

# Submit an image job
curl -s -X POST http://debian2.local:8090/v1/jobs/image \
  -H 'Content-Type: application/json' \
  -d '{"workflow":"basic-sd","prompt":"a cat on the moon"}'

# Call an MCP tool
curl -s -X POST http://debian2.local:8090/v1/mcp/tools/random_integer/call \
  -H 'Content-Type: application/json' \
  -d '{"arguments":{"min":1,"max":100}}'
```
