# Upgrading llama.cpp

llama.cpp on the secondary is pinned to a specific upstream tag by `scripts/llamacpp-setup.sh`. The tag is the single source of truth for which build the secondary runs. Bumps are manual and deliberate, not automatic, because different llama.cpp builds change CLI flag names, defaults, and tool-call template handling — preset files (`config/llm_presets/<name>.json`) are coupled to the pinned tag.

## Procedure

1. **Pick a new tag.** Browse the releases at <https://github.com/ggerganov/llama.cpp/releases>. Prefer a stable-looking tag (e.g., `b6042`) over the absolute latest, and skim the changelog for breaking changes — especially renames around CUDA flags, sampler defaults, the chat template, and tool-call parsing.

2. **Edit the script.** Open `scripts/llamacpp-setup.sh` and change the `LLAMA_CPP_TAG` variable at the top:

   ```bash
   LLAMA_CPP_TAG="b6042"   # was b6000
   ```

3. **Re-run setup on the secondary.** The script is idempotent — it fetches the new tag, checks it out, and rebuilds:

   ```bash
   ssh gpu.local 'cd ~/ai-job-server && bash scripts/llamacpp-setup.sh'
   ```

4. **Verify presets still parse.** llama.cpp occasionally renames or splits flags. Common ones to double-check against the new build's `--help`:

   - `--n-gpu-layers` vs `-ngl`
   - `--ctx-size` vs `-c`
   - `--flash-attn` (whether it's still a bare flag vs requiring `on`/`off`)
   - `--mmproj` for multimodal projector paths (vision models)
   - `--jinja` / `--chat-template` if you rely on a specific tool-call format

   For each preset under `config/llm_presets/`, mentally translate `args` into the CLI form and confirm the flags are still recognized. If you find a renamed flag, update the preset's `args` map.

5. **Sanity-check end-to-end.** Restart the unit and try a chain LLM step that uses the affected preset:

   ```bash
   ssh gpu.local 'systemctl --user restart ai-job-server'
   curl -s http://gpu.local:8090/v1/llamacpp/status | jq
   ```

   Watch for swap failures via `GET /v1/llamacpp/logs?tail=200` — if `llama-server` exits during the readiness window, the new build rejected one of the args.

6. **Commit the bump.** Single-purpose commit so the tag change is easy to find / revert:

   ```bash
   git add scripts/llamacpp-setup.sh
   git commit -m "llama.cpp: bump pinned tag b6000 → b6042"
   ```

   If any preset args changed, include those in the same commit so the tag bump and the preset edits stay together.

## When to bump

- A new llama.cpp release adds a model architecture or feature you want (e.g., a new GGUF format, vision-language updates, sampler improvements).
- The pinned build develops a bug that's been fixed upstream.
- The pinned build is more than a few months stale and you're touching the secondary anyway.

There's no automatic schedule. The pin is intentional.

## Rolling back

If a bump breaks something and you need to revert quickly, set `LLAMA_CPP_TAG` back to the old value, re-run `scripts/llamacpp-setup.sh`, and restart the unit. The build dir under `/opt/ai-stack/llama.cpp/build` is reused, so a downgrade is usually faster than the initial install.
