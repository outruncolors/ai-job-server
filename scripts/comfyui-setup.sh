#!/usr/bin/env bash
# ComfyUI setup — idempotent, run with: bash scripts/comfyui-setup.sh
# Target: RTX 3090 Ti (Ampere, sm_86, 24 GB), Debian 13, Python 3.12, CUDA 12.4
#
# Requires: python3.12, git, and a loaded NVIDIA driver (550+).
# After running: place model files in /opt/ai-stack/models/<type>/ and start
# ComfyUI from the Image > Server tab (or via the API at POST /v1/comfyui/start).

set -euo pipefail

RUNTIMES=/opt/ai-stack/runtimes
MODELS=/opt/ai-stack/models
COMFY_DIR="$RUNTIMES/ComfyUI"
VENV_DIR="$RUNTIMES/comfyui-venv"

# Pinned release tag — update when you want to upgrade
COMFY_TAG="v0.3.43"

echo "=== ComfyUI Setup ==="
echo "  Clone target : $COMFY_DIR"
echo "  Venv         : $VENV_DIR"
echo "  Models       : $MODELS"
echo "  Tag          : $COMFY_TAG"
echo ""

# 1. Clone or update
if [ -d "$COMFY_DIR/.git" ]; then
    echo "--- Updating existing clone ---"
    git -C "$COMFY_DIR" fetch --tags --quiet
    git -C "$COMFY_DIR" checkout "$COMFY_TAG" --quiet
else
    echo "--- Cloning ComfyUI ---"
    git -C "$RUNTIMES" clone --depth 1 --branch "$COMFY_TAG" \
        https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR"
fi

# 2. Create venv
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "--- Creating Python 3.12 venv ---"
    python3.12 -m venv "$VENV_DIR"
fi
PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"
"$PIP" install --upgrade pip --quiet

# 3. PyTorch + CUDA 12.4 (sm_86 Ampere, matches driver 550 + CUDA 12.4)
echo "--- Installing PyTorch cu124 ---"
"$PIP" install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124 \
    --quiet

# 4. ComfyUI core requirements
echo "--- Installing ComfyUI requirements ---"
"$PIP" install -r "$COMFY_DIR/requirements.txt" --quiet

# 5. Speed stack for 3090 Ti
echo "--- Installing Triton ---"
"$PIP" install triton --quiet

# SageAttention: builds CUDA kernels, so requires nvcc from the CUDA toolkit.
# The PyPI package (latest ~1.0.6) may or may not have a prebuilt wheel for
# this torch/CUDA combo. Make this non-fatal — ComfyUI works without it
# (falls back to pytorch cross-attention); set use_sage_attention=false in
# config if the import fails at runtime.
echo "--- Installing SageAttention (best-effort) ---"
if "$PIP" install sageattention --no-build-isolation --quiet 2>&1; then
    echo "  SageAttention installed OK"
else
    echo "  SageAttention install failed — likely missing nvcc (CUDA toolkit)."
    echo "  ComfyUI will still work; set use_sage_attention=false in comfyui.json"
    echo "  or install the CUDA toolkit and re-run this script."
fi

# 6. Shared model directories
echo "--- Creating model directories ---"
mkdir -p \
    "$MODELS/checkpoints" \
    "$MODELS/loras" \
    "$MODELS/vae" \
    "$MODELS/clip" \
    "$MODELS/unet" \
    "$MODELS/controlnet" \
    "$MODELS/upscale_models" \
    "$MODELS/embeddings" \
    "$MODELS/diffusion_models" \
    "$MODELS/text_encoders" \
    "$MODELS/style_models" \
    "$MODELS/hypernetworks"

# 7. extra_model_paths.yaml — tells ComfyUI to look in $MODELS
YAML_PATH="$MODELS/extra_model_paths.yaml"
if [ ! -f "$YAML_PATH" ]; then
    echo "--- Writing extra_model_paths.yaml ---"
    cat > "$YAML_PATH" << 'YAML'
# ComfyUI extra model paths — shared across installs
ai_stack:
  base_path: /opt/ai-stack/models
  checkpoints: checkpoints/
  loras: loras/
  vae: vae/
  clip: clip/
  unet: unet/
  controlnet: controlnet/
  upscale_models: upscale_models/
  embeddings: embeddings/
  diffusion_models: diffusion_models/
  text_encoders: text_encoders/
  style_models: style_models/
  hypernetworks: hypernetworks/
YAML
fi

# 8. Output + input directories used by the managed launch
mkdir -p /var/lib/comfy/output /var/lib/comfy/input

# 9. Quick sanity check
echo ""
echo "--- Verifying installation ---"
"$PYTHON" -c "import torch; print(f'  torch {torch.__version__}, CUDA available: {torch.cuda.is_available()}')"
"$PYTHON" -c "import sageattention; print(f'  sageattention {sageattention.__version__}')" 2>/dev/null || \
    echo "  sageattention: import check failed (may need a CUDA toolkit for the kernel — try a GPU-loaded context)"
echo ""
echo "=== Done ==="
echo ""
echo "Next steps:"
echo "  1. Place model files in /opt/ai-stack/models/<type>/"
echo "  2. Start the ai-job-server — ComfyUI auto-starts on boot"
echo "     or manually: POST /v1/comfyui/start"
echo "  3. Open ComfyUI editor at http://localhost:8188 to build workflows"
echo "  4. Export a workflow: Settings → Dev Mode ON, then Workflow → Export (API)"
echo "  5. Save the exported JSON to config/comfyui-workflows/<name>.json"
echo "  6. Use the Image page to generate with that workflow"
