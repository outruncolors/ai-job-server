# ComfyUI Setup

ComfyUI runs as a long-lived HTTP server at `127.0.0.1:8188`. This document covers installing it, pointing it at shared models, and the launch flags this server uses on an RTX 3090 Ti.

## One-shot install

```bash
bash scripts/comfyui-setup.sh
```

The script is idempotent and performs:

1. **System packages** — `nvidia-cuda-toolkit`, `nvidia-cuda-dev`, `gcc-13` (CUDA 12.4 nvcc rejects gcc 14).
2. **ComfyUI clone** — pinned tag `v0.3.43` from GitHub.
3. **Venv** — `/opt/ai-stack/runtimes/comfyui-venv` with Python 3.13.
4. **PyTorch** — `torch torchvision torchaudio` from the CUDA 12.4 wheel index.
5. **ComfyUI requirements** — plus `requests`, which the upstream `requirements.txt` omits.
6. **Triton** — `>= 3.0`, needed by SageAttention 2.x.
7. **SageAttention** — built from source against `sm_86` (Ampere) with gcc-13 and `MAX_JOBS=4`.
8. **Model directories** — created under `/opt/ai-stack/models/` (`checkpoints`, `loras`, `vae`, `clip`, `unet`, `controlnet`, `upscale_models`, `embeddings`, `diffusion_models`, `text_encoders`, `style_models`, `hypernetworks`).
9. **`extra_model_paths.yaml`** — points ComfyUI at the shared model directories so models live outside the repo.
10. **Output / input dirs** — `/var/lib/comfy/output`, `/var/lib/comfy/input`.
11. **Sanity check** — imports torch, prints CUDA availability, imports SageAttention.

## Launch configuration

Configured in `config/comfyui.json` (edited via the [Server → ComfyUI](../../management/server/comfyui.md) tab). Defaults tuned for the 3090 Ti:

| Field | Default | Notes |
|-------|---------|-------|
| `comfyui_root` | clone path | |
| `venv_python` | `/opt/ai-stack/runtimes/comfyui-venv/bin/python` | |
| `host` / `port` | `127.0.0.1` / `8188` | |
| `vram_mode` | `highvram` | `normalvram`, `lowvram`, `novram` also accepted |
| `reserve_vram_gb` | `1` | left to the OS |
| `use_sage_attention` | `true` | requires SageAttention build above |
| `preview_method` | `none` | `auto`, `latent2rgb`, `taesd` available |
| `models_root` | `/opt/ai-stack/models` | written to `extra_model_paths.yaml` |
| `output_dir` / `input_dir` | `/var/lib/comfy/{output,input}` | |
| `autostart` | true | start ComfyUI at FastAPI boot |
| `extra_args` | `[]` | extra argv injected after the resolved flags |

The full launch line is roughly:

```
<venv_python> <comfyui_root>/main.py --listen <host> --port <port> \
  --use-sage-attention --highvram --reserve-vram 1 --cuda-malloc \
  --preview-method none --output-directory /var/lib/comfy/output \
  --input-directory /var/lib/comfy/input \
  --extra-model-paths-config <extra_model_paths_yaml>
```

## Lifecycle

`ComfyUIManager` (`app/comfyui/manager.py`) handles the process:

- At FastAPI lifespan startup, it checks `/system_stats`. If a ComfyUI is already running on `host:port`, it adopts the PID (via `psutil.net_connections()`) so manual launches survive a restart of this server.
- If no instance is alive and `autostart=true`, it spawns one with `start_new_session=True` so the process gets its own group. stdout/stderr go to `config/comfyui-server.{stdout,stderr}.log`.
- Readiness is determined by polling `/system_stats` until GPU devices appear (timeout 120 s).
- On stop, the manager calls `/interrupt`, waits up to 10 s for the queue to drain, then `SIGTERM` to the process group; another 10 s and it escalates to `SIGKILL`.

## Troubleshooting

- **`nvcc` errors mentioning gcc 14** — the install script should have placed gcc-13; rerun the setup script.
- **CUDA not available** — confirm the host driver is recent (≥ 550) and `nvidia-smi` works. The python venv was built against CUDA 12.4 wheels.
- **OOM at launch with `highvram`** — drop to `normalvram` in the Config tab and restart ComfyUI.
- **SageAttention import fails** — re-run the setup script; the build is tied to the venv's torch ABI.
