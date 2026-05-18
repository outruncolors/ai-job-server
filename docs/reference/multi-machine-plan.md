# Multi-Machine Architecture — Implementation Plan

Status: planning complete, not yet implemented. This document is the single source of truth for the multi-machine epic. Every ticket in this epic references this file. Read this top-to-bottom before starting a ticket.

## Goal

Split the current single-machine deployment into two cooperating machines that run from the same codebase:

- **Primary** — the machine currently hosting the FastAPI web server, OmniVoice, and ComfyUI (3090 Ti). This is the user's backup PC. Everything UI-facing and image/voice-related runs here.
- **Secondary** — the user's stronger PC, dedicated to LLM inference via llama.cpp. Currently runs a standalone Gemma 4 process unrelated to this repo; will be migrated into the fleet.

Both machines run the same `ai-job-server` codebase, but each only activates the subsystems it's configured for.

## Design decisions (all locked)

### Roles via capabilities array, not enum

`config/server.json` on each machine declares:

```json
{
  "role": "primary",
  "capabilities": ["web", "voice", "image"],
  "peers": [
    { "name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"] }
  ]
}
```

```json
{
  "role": "secondary",
  "capabilities": ["llm"],
  "peers": [
    { "name": "primary", "host": "primary.local", "port": 8090, "capabilities": ["web","voice","image"] }
  ]
}
```

The `role` field is informational; **capability presence is what drives behavior**. A future "stronger PC also does image gen" scenario adds `"image"` to its capabilities — no enum change. `app/main.py` lifespan inspects capabilities and only starts the managers it owns (no ComfyUI manager on secondary, no llama.cpp manager on primary). Routers mount the same way on both boxes; out-of-capability routes return 503.

### Same UI everywhere, capability-gated

The web UI is served from both machines. Features whose required capability lives on a peer are rendered **disabled** with a warning banner (e.g., "This feature requires the `image` capability, available on `primary.local`"). The UI fetches `/v1/server/capabilities` on load to decide what to disable.

**Server-side enforcement is mandatory** — routes that need a missing capability return:

```json
{ "error": "capability_unavailable", "needed": "llm", "where": "gpu.local" }
```

with HTTP 503. UI gating is convenience; the route check is the actual contract.

### Peer discovery and health: pull-based polling

Each machine polls every peer's `GET /v1/server/health` every 30 seconds. No push, no heartbeats. Health response includes `git_sha`, `capabilities`, and basic uptime. Status cached in-process. Exposed via `/v1/server/peers`.

A small status widget in the topnav shows a dot per peer (green/amber/red). Amber = up but `git_sha` mismatch (still functional, but flagged with a banner).

### Names via mDNS (avahi)

`apt install avahi-daemon` on both machines. Each is reachable as `<hostname>.local` automatically. No DNS server to maintain. If `.local` ever bites (corp VPN, weird routing), the `host` field in `config/server.json` is a one-line change to a static IP or a switch to dnsmasq.

### Repo hosting: bare repo on primary

- Canonical repo: `/srv/git/ai-job-server.git` on primary (bare)
- Primary's working tree: `/opt/ai-stack/claude-work/ai-job-server` (existing checkout), with the bare repo as a `local` remote
- Secondary's working tree: `~/ai-job-server`, cloned from `git@primary.local:/srv/git/ai-job-server.git`
- No GitHub, no Forgejo. Drop Forgejo in front of `/srv/git/` later if code review UI is wanted.

### Version sync: surfaced, never automatic

- Both machines report `git_sha` in `/v1/server/health`
- Peer poller compares; mismatch → amber status + banner
- No automatic pull. Manual deploy via `scripts/deploy-secondary.sh`:
  ```
  git push local master
  ssh gpu.local 'cd ~/ai-job-server && git pull && systemctl --user restart ai-job-server'
  ```

### systemd user units on both machines

`scripts/systemd/ai-job-server.service` (user unit). Restart-on-failure, journal logging. Makes "is it running?" a `systemctl --user status` question instead of "is there a screen session?". Required because the deploy script restarts via systemctl.

### Global sequential job queue (prerequisite)

**Currently broken:** all three `create_*_job` endpoints in `app/main.py` dispatch via FastAPI `BackgroundTasks`. Two jobs posted back-to-back run concurrently. The user's mental model — and the LLM swap logic that follows — assumes strict sequential execution.

Fix:

- `app/job_queue.py` — `JobQueue` class wrapping `asyncio.Queue`
- One worker coroutine started in `app/main.py` lifespan, stopped on shutdown
- All three endpoints (`create_image_job`, `create_voice_job`, `create_chain_job`) become: write `request.json` with status `"queued"`, enqueue, return `job_id`. No more `BackgroundTasks` for execution.
- On clean shutdown: worker finishes current job, others stay `"queued"` on disk
- On startup recovery: scan job dirs. `"running"` → mark `"error"` with reason `"interrupted by server restart"` (can't safely resume mid-step). `"queued"` → re-enqueue sorted by `created_at`.
- `DELETE /v1/jobs/{id}` while status is `queued` pops from queue (cancel-while-queued only; cancel-while-running is out of scope).
- `queue_depth` field added to `/v1/server/stats`.

This must land before the llama.cpp ticket — the swap-lock semantics depend on it.

## llama.cpp integration

Mirrors the **ComfyUI pattern** (long-lived process, managed lifecycle), not OmniVoice's (ephemeral subprocess per request).

### Module layout

```
app/llamacpp/
├── config.py    # LlamaCppConfig pydantic model, load/save config/llamacpp.json
├── manager.py   # LlamaCppManager: start/stop/restart, ensure_loaded(), ring buffer of stdout/stderr, os.killpg cleanup
├── client.py    # OpenAI-compatible HTTP client (or thin shim over existing app/chain/llm_client.py)
├── router.py    # /v1/llamacpp/{status, start, stop, restart, config, models, ensure-loaded, logs}
└── workflows.py # not needed (no workflow concept here)
```

### LLM presets

```json
// config/llm_presets/gemma-3-27b-highctx.json
{
  "name": "gemma-3-27b-highctx",
  "model_path": "/opt/ai-stack/models/gemma-3-27b-q4.gguf",
  "args": {
    "ctx_size": 32768,
    "n_gpu_layers": 99,
    "flash_attn": true,
    "mmproj": null
  },
  "capabilities": ["text"]
}
```

- Stored at `config/llm_presets/<name>.json` (gitignored, like other configs)
- CRUD via `app/llm_presets.py` (mirror `app/voice_presets.py`)
- `LLMPreset` Pydantic schema in `app/chain/models.py` or a new `app/llm/models.py`
- `capabilities: ["text"]` or `["text", "vision"]` — declarative, used for safety check below
- Standalone `/llm-presets` UI page (CRUD, follows voice-presets/image-prompts pattern)

### Model swap mechanics

**Swap key is the full args hash, not just `model_path`.** Changing `ctx_size` or `n_gpu_layers` triggers a reload. Hash the resolved preset dict.

`POST /v1/llamacpp/ensure-loaded` body: `{"preset": "name"}`. Behavior:

1. Resolve preset → compute hash
2. If hash == `current_preset_hash`: return 200 immediately (no-op)
3. Acquire async lock (single load slot on this machine)
4. SIGTERM the running llama.cpp via `os.killpg`, wait for exit
5. Start new llama.cpp with new args, capture stdout/stderr into ring buffer (last 500 lines, in-memory)
6. Poll llama.cpp `/health` until ready, **180s deadline**
7. Update `current_preset_hash`, release lock, return 200
8. On timeout or startup failure: leave `current_preset_hash` unset (no model loaded), return 503 with details. **No silent fallback to previous model** — silent fallback masks config bugs.

Concurrent `ensure-loaded` calls for the **same** preset coalesce (second sees hash match after first releases). Concurrent calls for **different** presets serialize on the lock — but with the global job queue (above), this shouldn't happen in practice; the lock is a safety net.

### Step runner integration

In `app/chain/steps/llm.py`, before the chat-completion call:

1. If step has `preset` field, call `POST http://<llm-peer>.local:8090/v1/llamacpp/ensure-loaded` with the preset name
2. Wait for 200 (may take up to 180s on swap)
3. Log the swap visibly: `"swapping LLM: gemma-3-27b-highctx → gemma-3-4b-vision (loaded in 23.4s)"` (or `"LLM already loaded: gemma-3-27b-highctx"`)
4. Make the chat-completion call against the llama.cpp HTTP port (typically 8080) on the secondary

Two HTTP calls per LLM step. The cheap one (ensure-loaded with no-op) costs ~1ms; the expensive one (actual swap) is the bulk of latency on a swap step. Keeping them separate makes the swap observable in logs and decouples slow-control-plane from fast-data-plane.

### Step schema additions

`ChainStep` (or specifically the LLM step variant) gets two optional fields:

- `preset: str | None` — name of an LLM preset. If omitted, uses the configured `default_preset` from `config/llamacpp.json`.
- `requires: list[str] | None` — capabilities the step requires the chosen preset to have (e.g., `["vision"]`). Validated at save time against `LLMPreset.capabilities`. Saving a sequence that requests `vision` but selects a text-only preset returns 422.

Sequence editor UI: dropdown of available presets on the LLM step, populated from `/v1/llm-presets`. If `requires` is set, dropdown filters to compatible presets.

### Migrating the existing standalone Gemma

The strong PC currently runs Gemma 4 directly (no repo). Cutover steps (documented in `docs/multi-machine.md`):

1. SSH to secondary, note the existing launch command (model path, ctx-size, ngl, etc.)
2. Stop the standalone Gemma process
3. Run `scripts/llamacpp-setup.sh` on secondary
4. Move/symlink the existing GGUF into `/opt/ai-stack/models/`
5. Create `config/llm_presets/gemma-3.json` mirroring the old args
6. Set `default_preset` in `config/llamacpp.json` to that preset name
7. `systemctl --user start ai-job-server`

The model file itself doesn't move data, just paths. The repo doesn't ship llama.cpp as a submodule — `scripts/llamacpp-setup.sh` clones it to `/opt/ai-stack/llama.cpp` at a **pinned tag** (bump manually in the script when upgrading). Different llama.cpp builds have subtly different CLI args; preset files are coupled to the pinned tag. Note this in `docs/llamacpp-upgrade.md`.

## Cross-machine observability

Chain job logs live on primary (they always have). When llama.cpp errors on secondary:

1. The HTTP error from secondary is appended to the chain job's `logs.txt` with the full response body
2. Chain job detail page gets a **"Fetch peer logs"** button that calls `GET /v1/llamacpp/logs?tail=200` on the secondary (via the configured peer host)
3. Ring buffer on secondary holds last 500 lines of llama.cpp stdout/stderr in memory — pull on demand, no streaming

No syslog aggregation, no log shipping. Pull pattern matches the rest of the system.

## Backwards compatibility

- LLM steps without `preset` use `default_preset` from `config/llamacpp.json`. No saved sequence needs migration.
- The existing `LLMClient` in `app/chain/llm_client.py` doesn't change. Its `base_url` just points at the secondary now (`http://gpu.local:8080/v1`).
- Existing voice/image/chain jobs continue to work; they get queued instead of dispatched-immediate. The only behavioral change is back-to-back posts now serialize.

## Open items deliberately deferred

- **Auth between machines.** Trusted LAN only. If you ever expose the secondary outside LAN, add a shared token in `config/server.json`.
- **Cancel running jobs.** Cancel-while-queued is in scope. Cancel-while-running is harder (need to signal step runners) and not part of this epic.
- **Idle model eviction.** If you stop using an LLM, it stays loaded. VRAM is dedicated. Not worth solving until it's a problem.
- **Forgejo / code review UI.** Bare repo is enough for one user. Add Forgejo later if wanted.
- **dnsmasq / `.home` names visible from phones and laptops.** Avahi covers the two-box case. Layer dnsmasq on top later if desired — they coexist.

## Ticket execution order

Hard dependencies between tickets — execute in this order:

1. **Global sequential job queue** (prerequisite for everything else; LLM swap depends on "only one LLM step in flight")
2. **Multi-machine config + capability gating** (foundation: `config/server.json`, capability helpers, 503 enforcement, `/v1/server/capabilities`, `/v1/server/peers`)
3. **Bare repo + systemd units on primary** (operational foundation; deploy script depends on systemd)
4. **`app/llamacpp/` module** (depends on capability gating to know whether to start the manager)
5. **LLM preset system** (depends on llama.cpp module existing)
6. **LLM step preset selector** (depends on preset system)
7. **Peer health polling + topnav widget** (depends on capability endpoint existing)
8. **`scripts/llamacpp-setup.sh`** (operational tooling for secondary bootstrap)
9. **`scripts/deploy-secondary.sh`** (depends on bare repo + systemd units)
10. **Avahi setup + `docs/multi-machine.md`** (capstone: ties everything together with cutover instructions)

## Reference paths in the codebase

The implementer should study these existing modules before writing new ones — they establish the patterns to mirror:

- `app/comfyui/` — long-lived process manager pattern. `llama.cpp` mirrors this almost exactly. See especially `manager.py` (process lifecycle, adoption, killpg, readiness probe) and `config.py` (Pydantic config + JSON persistence).
- `app/voice_presets.py` — preset CRUD pattern. `app/llm_presets.py` mirrors this.
- `app/server.py` — `get_server_stats()`, `_get_job_counts()` (5s cache), `_STATUS_MAP`. The peer health endpoint and `/v1/server/capabilities` route belong adjacent to these.
- `app/main.py` lifespan — where ComfyUI manager is started/stopped. Llama.cpp manager start/stop lives here, gated on `"llm" in capabilities`.
- `app/chain/executor.py` — `execute_chain_job()`, status writes. The queue worker calls this; status semantics for `"queued"` get real teeth.
- `app/chain/steps/llm.py` — where the `ensure-loaded` call gets wired in before the chat completion.
- `static/js/profiles-widget.js` — the topnav-pinned widget pattern. The peer status widget follows this layout.
- `static/js/nav.js` — `NAV_ITEMS` and capability-based item disabling lives here (or in a sibling module).
- `CLAUDE.md` — keep up to date as new modules land.
