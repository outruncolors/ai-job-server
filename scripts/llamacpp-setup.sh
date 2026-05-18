#!/usr/bin/env bash
# llama.cpp setup — idempotent, run with: bash scripts/llamacpp-setup.sh
# Target: secondary machine with NVIDIA GPU + CUDA toolkit installed.
#
# Produces:
#   - llama.cpp source + Release build at /opt/ai-stack/llama.cpp/
#   - llama-server binary at  /opt/ai-stack/llama.cpp/build/bin/llama-server
#   - /opt/ai-stack/models/   (model files go here)
#   - ~/.config/systemd/user/ai-job-server.service  (installed, not enabled)
#
# Re-running is safe: existing clone is fetched + checked out to the pinned
# tag; cmake re-uses the existing build dir.

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Bump this manually when upgrading. Different builds have subtly different
# CLI args — preset files may need updates. See docs/llamacpp-upgrade.md.
# ─────────────────────────────────────────────────────────────────────────────
LLAMA_CPP_TAG="b9204"

LLAMA_DIR="/opt/ai-stack/llama.cpp"
MODELS_DIR="/opt/ai-stack/models"
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
UNIT_SRC="$REPO_ROOT/scripts/systemd/ai-job-server.service"
UNIT_DST_DIR="$HOME/.config/systemd/user"
UNIT_DST="$UNIT_DST_DIR/ai-job-server.service"

_sudo() { [ "$(id -u)" = "0" ] && "$@" || sudo "$@"; }

echo "=== llama.cpp Setup ==="
echo "  Clone target : $LLAMA_DIR"
echo "  Models dir   : $MODELS_DIR"
echo "  Tag          : $LLAMA_CPP_TAG"
echo "  Unit         : $UNIT_DST"
echo ""

# ── 1. CUDA toolkit check ────────────────────────────────────────────────────
# Need nvcc to build with GGML_CUDA=ON. nvidia-smi alone (driver only) is not
# sufficient. Fail with a clear message rather than letting cmake error 100
# lines deep.
if ! command -v nvcc &>/dev/null; then
    if command -v nvidia-smi &>/dev/null; then
        echo "ERROR: nvidia-smi is present but nvcc is missing." >&2
        echo "       Install the CUDA toolkit, e.g.:" >&2
        echo "         sudo apt install nvidia-cuda-toolkit nvidia-cuda-dev" >&2
        echo "       or follow https://developer.nvidia.com/cuda-downloads" >&2
    else
        echo "ERROR: neither nvcc nor nvidia-smi found on PATH." >&2
        echo "       This script targets machines with an NVIDIA GPU and the" >&2
        echo "       CUDA toolkit installed. Install the driver + toolkit first." >&2
    fi
    exit 1
fi
echo "--- nvcc: $(nvcc --version | grep -i release | head -n1)"

# ── 2. cmake / git presence ──────────────────────────────────────────────────
for bin in git cmake; do
    if ! command -v "$bin" &>/dev/null; then
        echo "ERROR: '$bin' is required but not on PATH." >&2
        echo "       Install with: sudo apt install $bin" >&2
        exit 1
    fi
done

# ── 3. Clone or fetch llama.cpp ──────────────────────────────────────────────
mkdir -p "$(dirname "$LLAMA_DIR")"
git config --global --add safe.directory "$LLAMA_DIR" 2>/dev/null || true

if [ -d "$LLAMA_DIR/.git" ]; then
    echo "--- Updating existing clone to $LLAMA_CPP_TAG ---"
    git -C "$LLAMA_DIR" fetch --tags --quiet
    git -C "$LLAMA_DIR" checkout "$LLAMA_CPP_TAG" --quiet
else
    echo "--- Cloning llama.cpp ---"
    git clone https://github.com/ggerganov/llama.cpp "$LLAMA_DIR"
    git -C "$LLAMA_DIR" fetch --tags --quiet
    git -C "$LLAMA_DIR" checkout "$LLAMA_CPP_TAG" --quiet
fi

# ── 4. Build with CUDA ───────────────────────────────────────────────────────
echo "--- Configuring (cmake -B build -DGGML_CUDA=ON) ---"
cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -DGGML_CUDA=ON

echo "--- Building (this takes several minutes) ---"
cmake --build "$LLAMA_DIR/build" --config Release -j"$(nproc)"

LLAMA_SERVER="$LLAMA_DIR/build/bin/llama-server"
if [ ! -x "$LLAMA_SERVER" ]; then
    echo "ERROR: build finished but llama-server binary not found at:" >&2
    echo "       $LLAMA_SERVER" >&2
    exit 1
fi
echo "--- Built: $LLAMA_SERVER"

# ── 5. Models directory ──────────────────────────────────────────────────────
if [ ! -d "$MODELS_DIR" ]; then
    echo "--- Creating $MODELS_DIR ---"
    mkdir -p "$MODELS_DIR"
else
    echo "--- $MODELS_DIR already exists ---"
fi

# ── 6. systemd user unit ─────────────────────────────────────────────────────
if [ ! -f "$UNIT_SRC" ]; then
    echo "ERROR: systemd unit template not found at $UNIT_SRC" >&2
    echo "       Are you running this from inside the repo checkout?" >&2
    exit 1
fi

mkdir -p "$UNIT_DST_DIR"
cp "$UNIT_SRC" "$UNIT_DST"
echo "--- Installed unit: $UNIT_DST"

if command -v systemctl &>/dev/null; then
    systemctl --user daemon-reload
    echo "--- systemctl --user daemon-reload"
else
    echo "WARN: systemctl not on PATH; skipped daemon-reload." >&2
fi

# ── 7. Next steps ────────────────────────────────────────────────────────────
cat <<EOF

=== Done ===

Next steps:

  1. Place your existing Gemma GGUF (or any other model) in:
       $MODELS_DIR/

  2. Create an LLM preset file mirroring your old launch args, e.g.:
       $REPO_ROOT/config/llm_presets/gemma-3.json

     Schema (see docs/tools/llm-presets.md):
       {
         "name": "gemma-3",
         "model_path": "/opt/ai-stack/models/gemma-3-27b-it-Q6_K.gguf",
         "args": { "ctx_size": 32768, "n_gpu_layers": 99, "flash_attn": true },
         "capabilities": ["text"],
         "description": "primary LLM"
       }

  3. Set the default preset in:
       $REPO_ROOT/config/llamacpp.json

     Example:
       { "binary_path": "$LLAMA_SERVER",
         "port": 8080,
         "default_preset": "gemma-3",
         "models_dir": "$MODELS_DIR" }

  4. If WorkingDirectory in the systemd unit doesn't match this checkout,
     edit $UNIT_DST before enabling. Then:

       systemctl --user enable --now ai-job-server
       systemctl --user status  ai-job-server
       journalctl --user -u ai-job-server -f

     (Run 'sudo loginctl enable-linger \$USER' once if the server should
     survive your logging out.)

Upgrading llama.cpp later: see docs/llamacpp-upgrade.md.
EOF
