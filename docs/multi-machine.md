# Multi-Machine Deployment

Operational guide for the two-machine ai-job-server setup: **primary** (web + voice + image, 3090 Ti) and **secondary** (LLM inference via llama.cpp).

> **Design reference:** [`reference/multi-machine-plan.md`](reference/multi-machine-plan.md) holds every locked design decision, rationale, and tradeoff for this epic. Read that first if you're trying to understand *why* something is set up the way it is. This page is the *how* — bootstrap, cutover, and day-2 ops.

## Overview

<!-- TODO: ticket 10 -->

Two machines, one codebase, capabilities-driven activation. The primary serves the web UI and runs OmniVoice + ComfyUI; the secondary runs llama.cpp. Each machine declares its `capabilities` in `config/server.json`; routes whose capability lives on a peer return `503 capability_unavailable` and the UI gates the corresponding controls.

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

Deploys then go: push to `local` on primary → `ssh secondary 'git pull && systemctl --user restart ai-job-server'`. That sequence is automated by `scripts/deploy-secondary.sh` (see the Secondary cutover section below).

## Avahi setup

<!-- TODO: ticket 10 -->

`apt install avahi-daemon` on both machines so each is reachable as `<hostname>.local`. The `host` field in `config/server.json` and the SSH/clone URLs above all assume mDNS names; falling back to static IPs is a one-line config edit if `.local` resolution ever breaks.

## Role / capability config

<!-- TODO: ticket 10 -->

`config/server.json` on each machine declares its `role`, `capabilities`, and the list of known `peers`. See `app/server.py` for the helpers (`get_local_capabilities`, `get_peers`, `find_peer_for_capability`) and the `requires_capability(cap)` FastAPI dependency that enforces 503s on out-of-capability routes. Schema and worked examples are in [`reference/multi-machine-plan.md`](reference/multi-machine-plan.md#roles-via-capabilities-array-not-enum).

## Secondary cutover

<!-- TODO: ticket 10 -->

Migrating the existing standalone Gemma 4 process on the strong PC into the fleet: stop the old process, run `scripts/llamacpp-setup.sh`, drop the GGUF into `/opt/ai-stack/models/`, create a matching `config/llm_presets/<name>.json`, set `default_preset` in `config/llamacpp.json`, then `systemctl --user start ai-job-server`. Full step-by-step lands in ticket 10.

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

<!-- TODO: ticket 10 -->

Symptom → check ordering for the common failure modes: peer shows red, peer shows amber (git_sha mismatch), `503 capability_unavailable` on a route you expected to work, llama.cpp swap timeout, systemd unit refuses to start. Fills in once the operational surface is real.

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
