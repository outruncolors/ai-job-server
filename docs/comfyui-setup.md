# ComfyUI Setup Guide

ComfyUI runs as a managed long-lived subprocess at `http://127.0.0.1:8188`. The host FastAPI app starts, stops, and monitors it; image generation is submitted over ComfyUI's HTTP API.

## Prerequisites

- NVIDIA driver 550+ loaded (`/opt/ai-stack/runtimes/omnivoice-venv/bin/nvidia-smi` to verify)
- Python 3.12 on PATH (`python3.12`)
- Git

## One-time Install

```bash
bash scripts/comfyui-setup.sh
```

This script is idempotent — re-running updates the pinned tag in place.

**What it installs** (in `/opt/ai-stack/runtimes/comfyui-venv`):
- PyTorch 2.x + CUDA 12.4 (matches driver 550 / CUDA 12.4)
- ComfyUI core requirements
- Triton ≥ 3.0 (required by SageAttention)
- SageAttention 2.x (built from source, cloned to `/opt/ai-stack/runtimes/SageAttention`) — primary attention backend for the 3090 Ti. 2.x is not on PyPI (version-per-CUDA-ABI problem); the script builds it with nvcc targeting sm_86 only, using gcc-13 as host compiler (nvcc 12.4 rejects the Debian 13 default of GCC 14)

## Launch Flags (3090 Ti defaults)

```
--use-sage-attention    # SageAttention kernels for attention layers
--highvram              # keep VAE + text encoders resident (24 GB is enough)
--reserve-vram 1        # reserve 1 GB for display / other use
--cuda-malloc           # PyTorch custom CUDA allocator, helps fragmentation
--disable-auto-launch   # don't open a browser tab
--preview-method none   # max throughput; change to latent2rgb for step previews
```

These are baked into the managed launch. Adjust via `PUT /v1/comfyui/config`.

## Placing Models

All models live in `/opt/ai-stack/models/` — outside the clone so they survive reinstalls:

```
/opt/ai-stack/models/
  checkpoints/    ← SDXL .safetensors, Flux .gguf, etc.
  loras/
  vae/
  clip/
  unet/
  controlnet/
  diffusion_models/
  text_encoders/
  upscale_models/
  embeddings/
```

ComfyUI sees these via `extra_model_paths.yaml` (written by the setup script at `/opt/ai-stack/models/extra_model_paths.yaml`).

## Building and Registering Workflows

1. Start ComfyUI from the Image > Server tab (or `POST /v1/comfyui/start`).
2. Open `http://localhost:8188` to use the editor.
3. Build your workflow. Give important nodes descriptive titles (right-click → Title):
   - `"Positive Prompt"` → maps to `prompt` param
   - `"Negative Prompt"` → maps to `negative_prompt` param
   - Other KSampler fields (seed, steps, cfg) are auto-detected by node class.
4. Enable Dev Mode: **Settings → Dev Mode**.
5. Export: **Workflow → Export (API)** — saves a JSON file.
6. Move the JSON to `config/comfyui-workflows/<name>.json`.
7. The Image > Workflows tab will show it immediately (no restart needed).

### Parameter Auto-Detection

The app introspects workflow JSON and surfaces tunable fields by node class:

| Node class | Surfaced params |
|---|---|
| `CLIPTextEncode` | `prompt` (first), `negative_prompt` (second or titled "neg/negative") |
| `KSampler` | `seed`, `steps`, `cfg`, `sampler_name`, `scheduler`, `denoise` |
| `EmptyLatentImage` | `width`, `height`, `batch_size` |
| `CheckpointLoaderSimple` | `ckpt_name` |
| `UNETLoader` | `unet_name` |
| `LoraLoader` | `lora_name`, `strength_model`, `strength_clip` |
| `FluxGuidance` | `guidance` |

**Override with a sidecar file**: create `config/comfyui-workflows/<name>.meta.json` with:
```json
{
  "params": [
    {"name": "prompt",  "node_id": "6",  "field": "text",  "type": "string", "default": "", "label": "Prompt"},
    {"name": "seed",    "node_id": "25", "field": "noise_seed", "type": "integer", "default": 0, "label": "Seed"}
  ]
}
```
This overrides auto-detection completely for that workflow.

## Updating ComfyUI

Edit `COMFY_TAG` in `runtimes/comfyui-setup.sh`, then re-run it.

**Warning**: updating ComfyUI can change node schemas and break existing workflow JSON. After updating:
- Reload each workflow in the editor and re-export as API format
- SageAttention and Triton are tightly coupled to the torch ABI — if torch changes version, reinstall both

## Troubleshooting

**ComfyUI won't start** — check `config/comfyui-server.stderr.log`. Common causes:
- Wrong `venv_python` path in `comfyui.json`
- Missing `comfyui_root` (run the setup script)
- GPU not visible (check driver: `ls /dev/nvidia*`)

**SageAttention import error at startup** — the setup script handles this, but if something went wrong: re-run `bash scripts/comfyui-setup.sh` (it's idempotent). The build requires `nvcc` + `gcc-13`; the script installs both via apt if they're missing.

If you want to disable it entirely: set `use_sage_attention: false` in `config/comfyui.json` to fall back to PyTorch's built-in cross-attention (slower but always works).

**Why not PyPI?** — SageAttention 2.x is not published to PyPI because PyPI can't distinguish binary wheels for the same version built against different CUDA/torch combinations. The script clones and builds from source.

**Workflow not appearing** — JSON must be in **API format** (not UI format). Open the workflow in the editor and re-export after enabling Dev Mode.

**Model not found in ComfyUI** — verify `extra_model_paths.yaml` has the correct `base_path` and the file is in the right subfolder.
