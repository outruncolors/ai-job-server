# Multi-Machine Deployment

Operational guide for the two-machine ai-job-server setup: **primary** (web + voice + image, 3090 Ti) and **secondary** (LLM inference via llama.cpp).

> **Design reference:** [`reference/multi-machine-plan.md`](reference/multi-machine-plan.md) holds every locked design decision, rationale, and tradeoff for this epic. Read that first if you're trying to understand *why* something is set up the way it is. This page is the *how* — bootstrap, cutover, and day-2 ops.

## Overview

Two machines, one codebase, capability-driven activation.

| Role | Hostname (mDNS) | Capabilities | Runs |
|------|-----------------|--------------|------|
| Primary | `primary.local` | `web`, `voice`, `image` | FastAPI UI on `:8090`, OmniVoice (ephemeral), ComfyUI on `:8188` |
| Secondary | `gpu.local` | `llm` | FastAPI on `:8090` (same UI, gated), `llama-server` on `:8080` |

Both machines run from the **same git checkout** (deployed via a bare repo on the primary — see [Bare repo bootstrap](#bare-repo-bootstrap)). Each only activates the subsystems its `capabilities` array covers — primary doesn't spawn `LlamaCppManager`, secondary doesn't spawn `ComfyUIManager`. Routes whose required capability lives on a peer return `503 {"error":"capability_unavailable","needed":...,"where":...}` via the `requires_capability(cap)` FastAPI dependency in `app/server.py`. The UI fetches `/v1/server/capabilities` on load and disables out-of-capability controls; the route check is the actual contract.

Cross-machine wiring:

- **Chain LLM steps** call `POST http://gpu.local:8090/v1/llamacpp/ensure-loaded` before each chat completion, then hit `http://gpu.local:8080/v1/chat/completions` directly. The ensure-loaded call is a no-op when the same preset is already loaded; on a swap it SIGTERMs the running `llama-server` and starts the new args (180s readiness deadline).
- **Peer health** is pulled, never pushed — every node polls each peer's `GET /v1/server/health` every 30s (5s timeout) and serves the snapshot at `/v1/server/peers`. Topnav dots and the version-skew banner read from that endpoint.
- **Deploys** are manual and idempotent — `scripts/deploy-secondary.sh` pushes to the bare repo, SSHes to the peer to pull + restart, then verifies `git_sha` parity.

See [`reference/multi-machine-plan.md`](reference/multi-machine-plan.md) for the full design discussion — capability vs role enum, swap-key hashing, why pull-based health, what's deliberately deferred (auth, idle eviction, cancel-while-running).

## Bare repo bootstrap

The canonical repo lives as a bare repository on the primary at `/srv/git/ai-job-server.git`. The primary's working checkout (`/opt/ai-stack/claude-work/ai-job-server`) and the secondary's checkout (`~/ai-job-server`) both push/pull against it. No GitHub, no Forgejo — single source of truth on the LAN.

One-time setup on the primary:

```bash
# 1. Create the bare repo
sudo mkdir -p /srv/git
sudo chown $USER /srv/git
cd /srv/git
git init --bare ai-job-server.git

# 2. Wire the existing working checkout to push there
cd /opt/ai-stack/claude-work/ai-job-server
git remote add local /srv/git/ai-job-server.git
git push local master
```

After this the primary can `git push local master` to publish; the secondary clones via SSH:

```bash
# On secondary, one-time:
git clone ssh://$USER@primary.local/srv/git/ai-job-server.git ~/ai-job-server
```

Deploys then go: push to `local` on primary → `ssh secondary 'git pull && systemctl --user restart ai-job-server'`. That sequence is automated by `scripts/deploy-secondary.sh` (see the Deploying changes section below).

## Avahi setup

mDNS gives both machines stable `<hostname>.local` names without running a DNS server. Required because `config/server.json`, the deploy script, the SSH clone URL, and the chain LLM step's peer-host lookup all use `.local` names.

Install on **both** machines:

```bash
sudo apt install avahi-daemon libnss-mdns
sudo systemctl enable --now avahi-daemon
```

`libnss-mdns` wires mDNS resolution into glibc's name service switch — without it `ping gpu.local` works under tools that query mDNS directly (`avahi-resolve`) but fails for everything else (curl, ssh, httpx). Confirm `/etc/nsswitch.conf` has `mdns4_minimal` in its `hosts:` line; the package adds it on install.

Set hostnames so the `.local` names resolve to something memorable:

```bash
# On primary
sudo hostnamectl set-hostname primary

# On secondary
sudo hostnamectl set-hostname gpu
```

Verify from each side:

```bash
avahi-resolve -n gpu.local         # → gpu.local <ipv4>
ping -c1 gpu.local                 # → 1 packet, low ms
curl -s http://gpu.local:8090/v1/server/health   # after the secondary is up
```

**Caveats:**

- **Corporate VPNs** sometimes hijack `.local` for split-horizon DNS (Microsoft AD), or block multicast on the VPN interface. Symptoms: `avahi-resolve -n gpu.local` works (it bypasses NSS) but `ping gpu.local` returns "Name or service not known". Fix: drop the VPN, or replace the `host` value in `config/server.json` with the peer's static LAN IP. The SSH clone URL and `scripts/deploy-secondary.sh`'s default peer host are read from the same place, so a single edit covers all of it.
- **Different subnets** — mDNS is link-local; both machines must be on the same L2 segment. If they're behind different switches/VLANs you need a static IP (or run `avahi-daemon --no-rlimits` with an mDNS reflector, out of scope here).
- **Firewall** — UFW or `firewalld` may block UDP/5353. `sudo ufw allow mdns` on each machine if you've enabled UFW.

## Role / capability config

Each machine reads `config/server.json` at startup. The file is gitignored — copy `config/server.json.example` as a template. **If the file is absent, the node defaults to all capabilities** (single-machine fallback, useful for dev).

Field reference:

| Field | Type | Meaning |
|-------|------|---------|
| `role` | string | Informational only — `"primary"` or `"secondary"`. Capability presence drives behavior, not this field. |
| `capabilities` | list[string] | Subsystems this node activates. Allowed: `"web"`, `"voice"`, `"image"`, `"llm"`. `LlamaCppManager` only instantiates if `"llm"` is present; `ComfyUIManager` and OmniVoice routes only mount under `"image"` / `"voice"`. |
| `peers` | list[object] | Known peer nodes. Each entry: `name` (short label, used in widget tooltips), `host` (mDNS name or IP), `port` (FastAPI port, almost always `8090`), `capabilities` (what the peer is expected to provide — used by `find_peer_for_capability`). |

### Primary `config/server.json`

```json
{
  "role": "primary",
  "capabilities": ["web", "voice", "image"],
  "peers": [
    { "name": "gpu", "host": "gpu.local", "port": 8090, "capabilities": ["llm"] }
  ]
}
```

### Secondary `config/server.json`

```json
{
  "role": "secondary",
  "capabilities": ["llm"],
  "peers": [
    { "name": "primary", "host": "primary.local", "port": 8090, "capabilities": ["web", "voice", "image"] }
  ]
}
```

### How gating works at runtime

- **Startup** — `app/main.py`'s `lifespan` inspects `get_local_capabilities()`. The ComfyUI manager only starts if `"image"` is present; the llama.cpp manager only starts if `"llm"` is present. The peer poller (`start_peer_poller`) starts unconditionally.
- **Per-route** — routes that require a capability declare `Depends(requires_capability("image"))` (or `"voice"`, `"llm"`). When the local node lacks that capability, the dependency 503s with the JSON body documented above. Currently gated: `POST /v1/jobs/image`, `POST /v1/jobs/voice`, the entire `app/comfyui/router.py`, the entire `app/omnivoice` router. Chain job creation (`POST /v1/jobs/chain`) is **not** route-gated — chain jobs may use a mix of step types, and per-step capability validation is deferred (see "Open items deliberately deferred" in the design doc).
- **In the UI** — pages fetch `/v1/server/capabilities` and disable controls whose capability is missing. Server-side enforcement is the contract; UI gating is convenience.

To inspect from the LAN:

```bash
curl -s http://primary.local:8090/v1/server/capabilities | jq
curl -s http://gpu.local:8090/v1/server/capabilities | jq
```

## Secondary cutover

The strong PC currently runs a standalone Gemma 4 process (`llama-server` invoked directly, no repo, no systemd). The cutover moves it into the fleet: same `llama-server` binary, same GGUF, but now started by `LlamaCppManager` from a preset file, restartable via systemctl, observable from the primary's UI.

Run these steps **on the secondary** unless noted.

**1. Capture the existing launch args.**

```bash
ps -ef | grep -E '[l]lama-server|[l]lama.cpp'
```

Note the `--model`, `-c`/`--ctx-size`, `-ngl`/`--n-gpu-layers`, `--flash-attn`, `--port`, and any other flags. These become the `args` block in the preset file. Also note the model path — the file itself doesn't have to move, but you'll want it under `/opt/ai-stack/models/` for convention.

**2. Stop the standalone process.**

Depends on how it's currently launched:

```bash
# If under a screen/tmux session, find the pid and stop it:
pkill -f 'llama-server.*gemma'

# If under a systemd unit you set up earlier:
sudo systemctl disable --now <your-old-unit>.service
```

Confirm it's gone — `lsof -i :8080` should be silent. The new manager binds the same port.

**3. Clone the repo.**

```bash
git clone ssh://$USER@primary.local/srv/git/ai-job-server.git ~/ai-job-server
cd ~/ai-job-server
```

If SSH isn't set up yet: `ssh-copy-id $USER@primary.local` from the secondary first. The bare repo on primary lives at `/srv/git/ai-job-server.git`; clone URL above assumes the convention from [Bare repo bootstrap](#bare-repo-bootstrap).

**4. Run the llama.cpp installer.**

```bash
bash scripts/llamacpp-setup.sh
```

This clones llama.cpp into `/opt/ai-stack/llama.cpp` at the pinned `LLAMA_CPP_TAG`, builds with `-DGGML_CUDA=ON` (takes several minutes), creates `/opt/ai-stack/models/`, and installs the systemd user unit at `~/.config/systemd/user/ai-job-server.service` (without enabling it — that comes after config is in place). Re-running the script is safe.

You'll also need the Python venv for `app/main.py` itself:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**5. Move the GGUF into the conventional models dir.**

```bash
sudo mv ~/path/to/gemma-3-27b-it-Q6_K.gguf /opt/ai-stack/models/
# or symlink if you'd rather keep the original location:
sudo ln -s ~/path/to/gemma-3-27b-it-Q6_K.gguf /opt/ai-stack/models/
```

`/opt/ai-stack/models/` is owned by your user (created by the setup script).

**6. Write the preset file.**

Translate the launch args captured in step 1. Example for a 27B Gemma 3 with high context, mirroring the user's typical `llama-server -m … -c 32768 -ngl 99 --flash-attn` invocation:

```bash
mkdir -p config/llm_presets
cat > config/llm_presets/gemma-3.json <<'EOF'
{
  "name": "gemma-3",
  "model_path": "/opt/ai-stack/models/gemma-3-27b-it-Q6_K.gguf",
  "args": {
    "ctx_size": 32768,
    "n_gpu_layers": 99,
    "flash_attn": true
  },
  "capabilities": ["text"],
  "description": "primary chat LLM, high-context"
}
EOF
```

Notes:

- `name` must be kebab-case (see `LLMPreset._validate_name`).
- `args` keys map 1:1 to llama-server CLI flags with `-` replaced by `_` — `ctx_size` → `--ctx-size`, `n_gpu_layers` → `--n-gpu-layers`, `flash_attn: true` → `--flash-attn`. Don't pass `--model`, `--port`, or `--host` here; the manager injects those.
- The full args dict is the swap key. Adding a flag later (or changing `ctx_size`) triggers a reload on the next `ensure-loaded` call.
- For vision-capable presets (e.g. a Gemma 3 4B with mmproj), set `"capabilities": ["text", "vision"]` and add `"mmproj": "/opt/ai-stack/models/gemma-3-4b-mmproj.gguf"` to `args`. Chain steps that declare `requires: ["vision"]` then filter to compatible presets.

**7. Write `config/server.json`.**

```bash
cat > config/server.json <<'EOF'
{
  "role": "secondary",
  "capabilities": ["llm"],
  "peers": [
    { "name": "primary", "host": "primary.local", "port": 8090, "capabilities": ["web", "voice", "image"] }
  ]
}
EOF
```

**8. Write `config/llamacpp.json`** — primarily to pin `default_preset` so chain LLM steps without an explicit `preset:` field still resolve a model:

```bash
cat > config/llamacpp.json <<'EOF'
{
  "binary_path": "/opt/ai-stack/llama.cpp/build/bin/llama-server",
  "port": 8080,
  "default_preset": "gemma-3",
  "models_dir": "/opt/ai-stack/models"
}
EOF
```

**9. Edit the systemd unit** to point at `~/ai-job-server` instead of the primary's path. The default `scripts/systemd/ai-job-server.service` has `WorkingDirectory=/opt/ai-stack/claude-work/ai-job-server`; on the secondary edit both `WorkingDirectory` and `ExecStart`'s uvicorn path:

```ini
WorkingDirectory=/home/<user>/ai-job-server
ExecStart=/home/<user>/ai-job-server/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8090
```

(Replace `<user>` with `$USER`.) Then:

```bash
cp scripts/systemd/ai-job-server.service ~/.config/systemd/user/
systemctl --user daemon-reload
sudo loginctl enable-linger "$USER"      # so the service survives logout
systemctl --user enable --now ai-job-server
```

**10. Verify from the primary.**

```bash
# Health endpoint reachable, returns git_sha
curl -s http://gpu.local:8090/v1/server/health | jq

# Peer poller sees it green
curl -s http://primary.local:8090/v1/server/peers | jq '.peers[0].health.status'   # → "green"
```

Open any page on the primary's UI (`http://primary.local:8090/`) — the topnav peer-status widget should show one green dot for `gpu`. Trigger a model swap end-to-end with:

```bash
curl -s -X POST http://gpu.local:8090/v1/llamacpp/ensure-loaded \
  -H 'content-type: application/json' \
  -d '{"preset":"gemma-3"}'
# → {"status":"loaded","preset":"gemma-3", ...}
```

A chain job whose LLM step has no explicit `preset:` field will now route through this default. Set a different preset on a step to exercise the swap; watch `/v1/llamacpp/logs?tail=200` from the primary for stderr if anything misfires.

## Deploying changes

Once the bare repo and the secondary checkout are wired up, deploys are a one-command operation from the primary:

```bash
bash scripts/deploy-secondary.sh                # auto-picks the first peer with "llm" capability
bash scripts/deploy-secondary.sh gpu.local      # or name the peer explicitly
bash scripts/deploy-secondary.sh --force        # deploy even with a dirty working tree
```

The script:

1. Refuses to run if the working tree is dirty (override with `--force`).
2. Runs `git push local master` to publish to the bare repo at `/srv/git/ai-job-server.git`.
3. SSHes to the peer and runs `cd ~/ai-job-server && git pull && systemctl --user restart ai-job-server`, streaming output back.
4. Waits 5s and probes `http://<peer>:8090/v1/server/health`, retrying for up to ~15s. Fails loudly if the peer doesn't come back, doesn't return a `git_sha`, or returns a `git_sha` that doesn't match the local HEAD.

It's idempotent: running it twice in a row with no new commits is harmless — `git push` has nothing to send, the restart still succeeds, and the health probe still confirms the SHA match.

Common failure modes the script will surface:

- **SSH not set up** — `ssh -o BatchMode=yes` refuses to prompt for a password, so missing keys fail fast instead of hanging.
- **Peer unreachable** — `ConnectTimeout=10` on SSH and 5-second curl timeouts on the health probe bound the wait.
- **Service didn't come back** — five 2-second-spaced retries on `/v1/server/health`, then exit non-zero with a pointer to `journalctl --user -u ai-job-server`.
- **SHA mismatch after deploy** — a successful push + pull + restart that lands on a different commit than local (e.g., the bare repo and peer diverged) exits non-zero rather than declaring success.

After a green run the amber version-skew banner (see the next section) should clear within 30 seconds, once the in-process peer poller re-fetches `/v1/server/health` on each node.

## Peer health and version-skew

Every node runs an in-process poller (`app/peer_health.py`) that hits each peer's `GET /v1/server/health` every 30 seconds with a 5-second timeout. The result feeds `GET /v1/server/peers`:

```json
{
  "local_git_sha": "deadbeef…",
  "peers": [
    {
      "name": "gpu",
      "host": "gpu.local",
      "port": 8090,
      "capabilities": ["llm"],
      "health": {
        "status": "green",         // green | amber | red
        "git_sha": "deadbeef…",
        "last_seen": "2026-05-17T…",
        "error": null,
        "host": "gpu.local",
        "port": 8090
      }
    }
  ]
}
```

Status rules:

- **green** — peer reachable and `git_sha` matches local.
- **amber** — peer reachable but `git_sha` differs (or either side has no SHA known). Functional, but flagged.
- **red** — peer unreachable or returned 5xx within the 5s timeout. `last_seen` and `git_sha` stay sticky from the prior successful poll so the UI can show the most recent known state.

The topnav widget (`static/js/peer-status-widget.js`) draws one colored dot per peer with a tooltip carrying the full status detail. When any peer is amber it also renders a fixed banner under the topnav:

> Peer `gpu.local` is on commit `abc1234`, this machine is on `def5678` — consider running `scripts/deploy-secondary.sh`.

Both the server-side poll and the client-side fetch are pull-based; nothing pushes status. To eyeball it without a browser:

```bash
curl -s http://primary.local:8090/v1/server/peers | jq
```

## Troubleshooting

Symptom → check ordering for the common failure modes. Stop at the first step that explains your symptom.

### `.local` hostname doesn't resolve

Symptom: `ping gpu.local` returns "Name or service not known", `curl http://gpu.local:8090/...` fails with "Could not resolve host".

1. **Is `avahi-daemon` running on the peer?**
   ```bash
   ssh gpu 'systemctl is-active avahi-daemon'   # → active
   ```
   If inactive: `sudo systemctl enable --now avahi-daemon` on the peer.
2. **Is `libnss-mdns` installed locally?** Without it, mDNS responses don't flow through glibc resolution.
   ```bash
   dpkg -l libnss-mdns                          # should be ii (installed)
   grep mdns /etc/nsswitch.conf                 # 'hosts:' line should include mdns4_minimal
   ```
   If missing: `sudo apt install libnss-mdns`.
3. **Does `avahi-resolve` see it?** This bypasses NSS — if it works but `ping` doesn't, the NSS path is broken (step 2).
   ```bash
   avahi-resolve -n gpu.local
   ```
4. **VPN or weird routing?** See the Avahi caveats above. Drop the VPN or replace the `host` field in `config/server.json` with a static LAN IP.

### Peer dot stays red

Symptom: topnav widget shows a red dot for the peer; `/v1/server/peers` reports `status: "red"` with an `error` string.

1. **Is the peer's service running?**
   ```bash
   ssh gpu 'systemctl --user is-active ai-job-server'    # → active
   ssh gpu 'systemctl --user status  ai-job-server --no-pager'
   ```
   If not active: `systemctl --user start ai-job-server`. Check why it died with `journalctl --user -u ai-job-server -n 200 --no-pager`.
2. **Wrong host in `config/server.json`?** The `host` field is what the poller resolves. Typos or stale IPs land here.
   ```bash
   curl -s http://primary.local:8090/v1/server/peers | jq '.peers[].host'
   ```
3. **Port not open?** Maybe `ai-job-server` is bound to `127.0.0.1` instead of `0.0.0.0`. The systemd unit specifies `--host 0.0.0.0`; check `ExecStart` if you've edited it.
   ```bash
   ssh gpu 'ss -lntp | grep :8090'
   ```
4. **Firewall?** `sudo ufw status` on the peer; allow `8090/tcp` if UFW is on.

### Amber banner / version-skew warning

Symptom: green dot but a banner "Peer gpu.local is on commit X, this machine is on Y".

```bash
bash scripts/deploy-secondary.sh
```

The banner clears within 30s after a green deploy run, once both pollers re-fetch each other's `/health`. If it persists after a successful deploy, hard-refresh the browser tab (the widget caches its DOM, not the data).

### Model swap returns 503 with timeout

Symptom: a chain LLM step fails with `503` from `/v1/llamacpp/ensure-loaded` after ~180s, chain job logs say `LlamaCppLoadError`.

```bash
# Pull the last 200 lines of llama-server stderr from the secondary:
curl -s 'http://gpu.local:8090/v1/llamacpp/logs?tail=200'
```

Look for:

- **OOM** — "CUDA error: out of memory" or "ggml_backend_cuda_buffer_type_alloc_buffer failed". Reduce `ctx_size` or `n_gpu_layers` in the preset.
- **Bad args** — "unknown argument: --foo" usually means a flag is supported on a different `llama.cpp` tag than the one pinned in `scripts/llamacpp-setup.sh`. Either bump the tag (see [Upgrading llama.cpp](llamacpp-upgrade.md)) or drop the flag from the preset.
- **Missing model file** — "failed to load model from '/opt/ai-stack/models/...'". The path in the preset doesn't exist on the secondary's disk.

After fixing the preset, retry the chain step; `ensure-loaded` will hash the new args and reload.

### `capability_unavailable` 503 on a route you expected to work

Symptom: a POST to `/v1/jobs/image` (or similar) returns `503 {"error":"capability_unavailable","needed":"image","where":"primary.local"}`.

You're hitting the wrong machine. The route requires a capability this node doesn't declare. Check:

```bash
curl -s http://<this-node>:8090/v1/server/capabilities | jq
curl -s http://<this-node>:8090/v1/server/peers | jq '.peers[].capabilities'
```

Send the request to whichever node advertises the needed capability instead. (If you intended to add the capability here, edit `config/server.json` and `systemctl --user restart ai-job-server` — but note that requires the managers to actually be installed on this box, e.g. ComfyUI for `"image"`.)

### systemd unit refuses to start

Symptom: `systemctl --user start ai-job-server` exits with "Failed to start", journal shows the error.

```bash
journalctl --user -u ai-job-server -n 100 --no-pager
```

Most common causes:

- **`WorkingDirectory` wrong** — copied the primary's unit verbatim onto the secondary. Edit `~/.config/systemd/user/ai-job-server.service`, fix `WorkingDirectory` and `ExecStart` paths, `systemctl --user daemon-reload`, restart.
- **Venv missing** — secondary cutover step "you'll also need the Python venv" was skipped. `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- **Port already bound** — leftover standalone `llama-server` on `:8080` or a stale uvicorn on `:8090`. `lsof -i :8090` / `lsof -i :8080` to find the pid; stop the old process before retrying.
- **Lingering not enabled, and you logged out** — the service stops on logout without lingering. `sudo loginctl enable-linger "$USER"` once per machine.

## systemd unit

Both machines run the server as a **user** unit. The unit file lives in this repo at `scripts/systemd/ai-job-server.service`; the comment header in that file documents the install commands. Quick reference:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/systemd/ai-job-server.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ai-job-server
```

Enable lingering once per machine if the server should survive your logging out:

```bash
sudo loginctl enable-linger "$USER"
```
