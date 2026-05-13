#!/usr/bin/env bash
# ComfyUI setup — idempotent, run with: bash scripts/comfyui-setup.sh
# Target: RTX 3090 Ti (Ampere, sm_86, 24 GB), Debian 13, Python 3.12, CUDA 12.4
#
# Requires: python3.12, git, sudo access (for apt installs on first run).
# After running: place model files in /opt/ai-stack/models/<type>/ and start
# ComfyUI from the Image > Server tab (or via the API at POST /v1/comfyui/start).

set -euo pipefail

RUNTIMES=/opt/ai-stack/runtimes
MODELS=/opt/ai-stack/models
COMFY_DIR="$RUNTIMES/ComfyUI"
VENV_DIR="$RUNTIMES/comfyui-venv"
SAGE_SRC="$RUNTIMES/SageAttention"

# Pinned release tag — update when you want to upgrade
COMFY_TAG="v0.3.43"

_sudo() { [ "$(id -u)" = "0" ] && "$@" || sudo "$@"; }

echo "=== ComfyUI Setup ==="
echo "  Clone target : $COMFY_DIR"
echo "  Venv         : $VENV_DIR"
echo "  Models       : $MODELS"
echo "  Tag          : $COMFY_TAG"
echo ""

# ── 1. CUDA toolkit + compatible GCC ─────────────────────────────────────────
# nvcc is required to build SageAttention kernels from source.
# CUDA 12.4's nvcc rejects GCC 14 (Debian 13 default); gcc-13 is needed.
# These are idempotent — apt skips already-installed packages.
if ! command -v nvcc &>/dev/null; then
    echo "--- Installing CUDA toolkit (nvcc) ---"
    _sudo apt-get install -y nvidia-cuda-toolkit nvidia-cuda-dev
else
    echo "--- nvcc already installed: $(nvcc --version | grep release | awk '{print $6}')"
fi

if ! command -v gcc-13 &>/dev/null; then
    echo "--- Installing gcc-13 (required: nvcc 12.4 rejects gcc-14) ---"
    _sudo apt-get install -y gcc-13 g++-13
else
    echo "--- gcc-13 already installed ---"
fi

# ── 2. Clone ComfyUI ──────────────────────────────────────────────────────────
if [ -d "$COMFY_DIR/.git" ]; then
    echo "--- Updating existing clone to $COMFY_TAG ---"
    git -C "$COMFY_DIR" fetch --tags --quiet
    git -C "$COMFY_DIR" checkout "$COMFY_TAG" --quiet
else
    echo "--- Cloning ComfyUI $COMFY_TAG ---"
    git -C "$RUNTIMES" clone --depth 1 --branch "$COMFY_TAG" \
        https://github.com/comfyanonymous/ComfyUI "$COMFY_DIR"
fi

# ── 3. Python venv ───────────────────────────────────────────────────────────
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "--- Creating Python 3.12 venv ---"
    python3.12 -m venv "$VENV_DIR"
fi
PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"
"$PIP" install --upgrade pip --quiet

# ── 4. PyTorch + CUDA 12.4 ───────────────────────────────────────────────────
echo "--- Installing PyTorch cu124 ---"
"$PIP" install torch torchvision torchaudio \
    --index-url https://download.pytorch.org/whl/cu124 \
    --quiet

# ── 5. ComfyUI core requirements ──────────────────────────────────────────────
echo "--- Installing ComfyUI requirements ---"
"$PIP" install -r "$COMFY_DIR/requirements.txt" --quiet

# ── 6. Triton ─────────────────────────────────────────────────────────────────
echo "--- Installing Triton ---"
"$PIP" install triton --quiet

# ── 7. SageAttention (built from source) ─────────────────────────────────────
# SageAttention 2.x is not on PyPI (version-per-CUDA-ABI problem).
# We build from the GitHub source. Already done if the package is importable.
if "$PYTHON" -c "import sageattention" &>/dev/null; then
    SAGE_VER=$("$PYTHON" -c "import sageattention; print(sageattention.__version__)" 2>/dev/null || echo "unknown")
    echo "--- SageAttention already installed ($SAGE_VER) ---"
else
    echo "--- Building SageAttention from source ---"
    echo "    (compiling CUDA kernels — takes a few minutes)"

    if [ -d "$SAGE_SRC/.git" ]; then
        git -C "$SAGE_SRC" pull --quiet
    else
        git -C "$RUNTIMES" clone --depth 1 \
            https://github.com/thu-ml/SageAttention.git "$SAGE_SRC"
    fi

    # CUDA_HOME: Debian's nvidia-cuda-toolkit installs nvcc to /usr/bin
    # but torch's cpp_extension looks for headers under CUDA_HOME/include.
    # On Debian 13 the toolkit headers live under /usr.
    export CUDA_HOME="${CUDA_HOME:-/usr}"

    # Limit to sm_86 only (3090 Ti = Ampere) to keep compile time reasonable
    export TORCH_CUDA_ARCH_LIST="8.6"

    # Tell nvcc to use gcc-13 as the host compiler (gcc-14 is unsupported by nvcc 12.4)
    export NVCC_APPEND_FLAGS="--compiler-bindir /usr/bin/gcc-13"

    # Limit parallel compile jobs so the system stays responsive
    export MAX_JOBS="${MAX_JOBS:-4}"

    "$PIP" install "$SAGE_SRC" --no-build-isolation --quiet

    "$PYTHON" -c "import sageattention; print('  SageAttention', sageattention.__version__, 'installed OK')"
fi

# ── 8. Shared model directories ───────────────────────────────────────────────
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

# ── 9. extra_model_paths.yaml ─────────────────────────────────────────────────
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

# ── 10. Output / input dirs for the managed launch ───────────────────────────
_sudo mkdir -p /var/lib/comfy/output /var/lib/comfy/input
_sudo chown -R "$(id -u):$(id -g)" /var/lib/comfy

# ── 11. Sanity check ──────────────────────────────────────────────────────────
echo ""
echo "--- Verifying installation ---"
"$PYTHON" -c "
import torch, sageattention
print(f'  torch {torch.__version__}  CUDA available: {torch.cuda.is_available()}')
print(f'  sageattention {sageattention.__version__}')
"

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
