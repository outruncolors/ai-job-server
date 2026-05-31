#!/usr/bin/env bash
# Deploy current master to a secondary peer.
#
#   bash scripts/deploy-secondary.sh [peer-host] [--force]
#
# Steps:
#   1. From the repo root, refuse if the working tree is dirty (unless --force).
#   2. git push local master  (the bare-repo remote set up in docs/multi-machine.md).
#   3. ssh <peer> 'cd ~/ai-job-server && git pull && systemctl --user restart ai-job-server'.
#   4. Wait ~5s, GET http://<peer>:8090/v1/server/health, compare git_sha.
#   5. Restart the local ai-job-server.service so its self-reported git_sha
#      refreshes (otherwise the peer poller sees the new HEAD on the peer but
#      stale HEAD locally and flags amber). Soft-fails if the unit isn't
#      installed locally.
#
# Idempotent: a second invocation with no new commits is a harmless no-op
# (git push has nothing new, restart succeeds, health probe still matches).
#
# Peer host defaults to the first peer in config/server.json that advertises
# the "llm" capability. Override by passing it as the first positional arg.

set -euo pipefail

# ── Resolve repo root + cd there ─────────────────────────────────────────────
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &>/dev/null && pwd)"
cd "$REPO_ROOT"

PEER_HOST=""
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
        -h|--help)
            sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        --*)
            echo "ERROR: unknown flag: $arg" >&2
            exit 2
            ;;
        *)
            if [ -z "$PEER_HOST" ]; then
                PEER_HOST="$arg"
            else
                echo "ERROR: extra positional argument: $arg" >&2
                exit 2
            fi
            ;;
    esac
done

# ── Default peer host from config/server.json ────────────────────────────────
if [ -z "$PEER_HOST" ]; then
    if [ ! -f "$REPO_ROOT/config/server.json" ]; then
        echo "ERROR: no peer host given and config/server.json does not exist." >&2
        echo "       Pass a peer hostname explicitly: $0 <peer-host>" >&2
        exit 2
    fi
    PY="$REPO_ROOT/.venv/bin/python"
    [ -x "$PY" ] || PY="python3"
    PEER_HOST="$(
        "$PY" - "$REPO_ROOT/config/server.json" <<'PYEOF'
import json, sys
path = sys.argv[1]
with open(path) as f:
    cfg = json.load(f)
for p in cfg.get("peers", []):
    if "llm" in p.get("capabilities", []):
        print(p["host"])
        break
PYEOF
    )"
    if [ -z "$PEER_HOST" ]; then
        echo "ERROR: no peer with 'llm' capability found in config/server.json." >&2
        echo "       Pass a peer hostname explicitly: $0 <peer-host>" >&2
        exit 2
    fi
    echo "--- Peer (auto): $PEER_HOST"
else
    echo "--- Peer: $PEER_HOST"
fi

# ── 1. Sanity: working tree clean ────────────────────────────────────────────
if [ -n "$(git status --porcelain)" ]; then
    if [ "$FORCE" -eq 0 ]; then
        echo "ERROR: working tree has uncommitted changes:" >&2
        git status --short >&2
        echo "" >&2
        echo "Commit/stash first, or re-run with --force to deploy anyway." >&2
        exit 1
    fi
    echo "WARN: working tree is dirty; --force given, continuing."
fi

# ── 2. Push to the bare repo ─────────────────────────────────────────────────
if ! git remote get-url local &>/dev/null; then
    echo "ERROR: git remote 'local' is not configured." >&2
    echo "       See docs/multi-machine.md > 'Bare repo bootstrap'." >&2
    exit 1
fi
echo "--- git push local master ---"
git push local master

LOCAL_SHA="$(git rev-parse HEAD)"
echo "--- Local SHA: $LOCAL_SHA"

# ── 3. SSH: pull + restart ───────────────────────────────────────────────────
echo "--- ssh $PEER_HOST: pull + restart ---"
# -o BatchMode=yes refuses to prompt for passwords — surfaces SSH-not-set-up
# loudly instead of hanging. ConnectTimeout caps the wait on an unreachable host.
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$PEER_HOST" \
    'set -e
     cd ~/ai-job-server
     git pull
     # Reinstall deps so new Python requirements (added on the primary) reach
     # the peer — git pull alone leaves the venv stale, which crashes boot when
     # a freshly-imported module (e.g. numpy via the SFX router) is missing.
     .venv/bin/pip install -q -r requirements.txt
     systemctl --user restart ai-job-server
     echo "Restarted on $(hostname) at $(date -Iseconds)"'
then
    echo "ERROR: remote deploy step failed on $PEER_HOST." >&2
    echo "       Check: ssh keys configured? peer reachable? ~/ai-job-server exists?" >&2
    echo "       systemd unit installed (see docs/multi-machine.md)?" >&2
    exit 1
fi

# ── 4. Health probe ──────────────────────────────────────────────────────────
HEALTH_URL="http://${PEER_HOST}:8090/v1/server/health"
echo "--- Waiting 5s for service to come back ---"
sleep 5

# Retry the probe a few times — restart-then-bind sometimes takes a beat.
PEER_SHA=""
PEER_BODY=""
for attempt in 1 2 3 4 5; do
    if PEER_BODY="$(curl -sf --max-time 5 "$HEALTH_URL" 2>/dev/null)"; then
        break
    fi
    echo "    probe $attempt/5 failed, retrying in 2s..."
    sleep 2
    PEER_BODY=""
done

if [ -z "$PEER_BODY" ]; then
    echo "ERROR: peer did not respond to $HEALTH_URL within ~15s." >&2
    echo "       Check 'journalctl --user -u ai-job-server' on $PEER_HOST." >&2
    exit 1
fi

PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
PEER_SHA="$("$PY" -c 'import json,sys; print(json.loads(sys.stdin.read()).get("git_sha") or "")' <<<"$PEER_BODY")"

echo "--- Peer SHA:  ${PEER_SHA:-<none>}"

if [ -z "$PEER_SHA" ]; then
    echo "WARN: peer health response had no git_sha field." >&2
    echo "      Service is up but version match cannot be confirmed." >&2
    exit 1
fi

if [ "$PEER_SHA" != "$LOCAL_SHA" ]; then
    echo "ERROR: peer SHA does not match local after deploy." >&2
    echo "       local=$LOCAL_SHA  peer=$PEER_SHA" >&2
    echo "       Did the remote 'git pull' diverge or fail silently?" >&2
    exit 1
fi

# ── 5. Restart local service so its self-reported git_sha refreshes ──────────
# get_git_sha() is computed at startup. Without this, commits made on the
# primary leave the peer poller showing amber (peer on new SHA, local stuck on
# old SHA) until someone manually restarts.
echo ""
echo "--- Restarting local ai-job-server (so local git_sha refreshes) ---"
if systemctl --user cat ai-job-server.service &>/dev/null; then
    if systemctl --user restart ai-job-server; then
        LOCAL_HEALTH_URL="http://localhost:8090/v1/server/health"
        LOCAL_BODY=""
        for attempt in 1 2 3 4 5; do
            if LOCAL_BODY="$(curl -sf --max-time 5 "$LOCAL_HEALTH_URL" 2>/dev/null)"; then
                break
            fi
            sleep 2
            LOCAL_BODY=""
        done
        if [ -z "$LOCAL_BODY" ]; then
            echo "WARN: local service did not respond to $LOCAL_HEALTH_URL within ~15s." >&2
            echo "      Check 'journalctl --user -u ai-job-server'." >&2
        else
            LOCAL_RESTARTED_SHA="$("$PY" -c 'import json,sys; print(json.loads(sys.stdin.read()).get("git_sha") or "")' <<<"$LOCAL_BODY")"
            echo "--- Local self-reported SHA: ${LOCAL_RESTARTED_SHA:-<none>}"
            if [ -n "$LOCAL_RESTARTED_SHA" ] && [ "$LOCAL_RESTARTED_SHA" != "$LOCAL_SHA" ]; then
                echo "WARN: local self-reported SHA ($LOCAL_RESTARTED_SHA) does not match HEAD ($LOCAL_SHA)." >&2
                echo "      The unit may be running from a different checkout than this script." >&2
            fi
        fi
    else
        echo "WARN: 'systemctl --user restart ai-job-server' failed; local git_sha may stay stale." >&2
        echo "      Restart manually once the underlying issue is fixed." >&2
    fi
else
    echo "--- ai-job-server.service not installed as a user unit on this host; skipping local restart."
    echo "    If the local node also runs ai-job-server, install the systemd unit (see docs/multi-machine.md)."
fi

echo ""
echo "=== Deploy OK ==="
echo "    $PEER_HOST is on $PEER_SHA, matches local."
