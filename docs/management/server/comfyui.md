# Server / ComfyUI

Lifecycle controls and configuration for the ComfyUI subprocess. See [ComfyUI Setup](../../generation/visual/comfyui-setup.md) for the install side.

## What's on the page

**Status panel**

- Running / Stopped indicator
- PID and uptime
- GPU VRAM usage with a colored bar (red ≥ 90 %, orange ≥ 75 %)
- Queue depth (running + pending prompts)
- **Start** / **Stop** / **Restart** buttons (disabled during operations and when state forbids the action)
- Link to the ComfyUI editor at `http://hostname:8188`
- Scrolling action log of the last 20 operations

**Download model panel** — server-side fetch into `models_root`. Useful when you're SSH'd into the host and don't want clicking "Download" in your browser to land the file on your laptop instead of the GPU box.

- **URL** — direct download link. HuggingFace `/resolve/main/...` paths work directly
- **Authorization** (optional) — for gated downloads (HF tokens, etc.). A bare token is auto-wrapped as `Bearer <token>`; an explicit scheme (`Bearer …`, `Basic …`, `Token …`) is passed through verbatim. The value is held in memory for the download only — never persisted and never echoed back through `GET /v1/comfyui/downloads`
- **Path** — relative to `models_root`, e.g. `checkpoints/foo.safetensors`. A `models/` prefix is shown next to the field; the server strips it defensively if you paste it in
- **Overwrite** — opt-in checkbox; without it, an existing destination returns 409
- Active and recent downloads show a progress bar (when `Content-Length` is sent), bytes done / total, and a Cancel button while running. The list survives a page reload — `GET /v1/comfyui/downloads` is fetched on tab activation
- Downloads stream to `<dest>.partial` and are atomically renamed on success; cancels and errors remove the partial

**Config panel** — every field in `config/comfyui.json`:

- Paths: `comfyui_root`, `venv_python`, `models_root`, `output_dir`, `input_dir`, `extra_model_paths_yaml`
- Network: `host`, `port`
- VRAM: `vram_mode` (highvram / normalvram / lowvram / novram), `reserve_vram_gb`
- Optimization: `use_sage_attention`, `preview_method` (none / auto / latent2rgb / taesd)
- `autostart`
- `extra_args` (one argv per line)

**Save** writes the file via `PUT /v1/comfyui/config`. A reminder banner notes that most fields require a ComfyUI restart to take effect.

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/comfyui/status` | Alive / PID / uptime / GPU / queue |
| POST | `/v1/comfyui/start` | Start (no-op if running) |
| POST | `/v1/comfyui/stop` | Graceful (SIGTERM → SIGKILL) |
| POST | `/v1/comfyui/restart` | Stop + start |
| GET / PUT | `/v1/comfyui/config` | Read / write `comfyui.json` |
| GET | `/v1/comfyui/workflows` | List + validate workflow JSON files |
| GET | `/v1/comfyui/system_stats` | Passthrough of ComfyUI's stats endpoint |
| POST | `/v1/comfyui/downloads` | Start a server-side model download (`{url, path, overwrite}`) |
| GET | `/v1/comfyui/downloads` | List active + recent downloads |
| GET | `/v1/comfyui/downloads/{id}` | Single download state |
| POST | `/v1/comfyui/downloads/{id}/cancel` | Cancel a running download |

## Adopt-don't-fight

`ComfyUIManager` always probes `host:port` at startup. If a ComfyUI is already alive there (e.g., you started one manually), it adopts the PID via `psutil` and uses that for status and shutdown — it will not double-spawn. Restarting from this tab gracefully shuts the adopted process down and starts a fresh one with the configured argv.
