#!/usr/bin/env bash
#
# tls-setup.sh — one-time HTTPS cert setup for LAN access.
#
# Why: the Voice/STT page records the mic via getUserMedia(), which browsers only
# allow in a "secure context". http://localhost counts, but http://<LAN-IP>:8090
# (from a phone or another machine) does NOT. We serve HTTPS via Caddy (see
# Caddyfile) using a locally-trusted mkcert certificate generated here.
#
# This script is idempotent: re-running it just regenerates the cert.
#
#   bash scripts/tls-setup.sh
#
# Then start the proxy (see scripts/systemd/ai-job-server-tls.service or just):
#   caddy run --config Caddyfile
#
# Full guide: docs/reference/https-localhost.md
set -euo pipefail

# Resolve repo root (this script lives in <root>/scripts/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TLS_DIR="$ROOT/config/tls"

if ! command -v mkcert >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: mkcert is not installed.

Install it, then re-run this script:

  Debian/Ubuntu:  sudo apt install -y mkcert libnss3-tools
  (or download a release binary from https://github.com/FiloSottile/mkcert)

EOF
  exit 1
fi

# Create + trust the local CA on THIS machine (no-op if already installed).
echo "==> Installing mkcert local CA (this machine)…"
mkcert -install

# Collect the names/IPs the cert should be valid for.
HOST="$(hostname)"
# hostname -I yields a space-separated list of all bound IPs (v4 + v6).
IPS="$(hostname -I 2>/dev/null || true)"

mkdir -p "$TLS_DIR"

echo "==> Generating certificate in $TLS_DIR …"
# shellcheck disable=SC2086  # word-splitting $IPS is intentional (one SAN per IP).
mkcert \
  -cert-file "$TLS_DIR/cert.pem" \
  -key-file  "$TLS_DIR/key.pem" \
  localhost 127.0.0.1 ::1 "$HOST" "$HOST.local" $IPS

CAROOT="$(mkcert -CAROOT)"

# Deploy the cert into caddy's own home for the packaged caddy.service. The repo
# tree (/opt/ai-stack/...) is private (0700/2770), so the caddy system user cannot
# traverse into it to read certs stored under config/tls — they must live somewhere
# caddy owns. This step needs root; skip it if you run Caddy as your own user.
CADDY_TLS_DIR="/var/lib/caddy/tls"
if id caddy >/dev/null 2>&1; then
  echo "==> Deploying cert to $CADDY_TLS_DIR for the packaged caddy.service (needs sudo)…"
  sudo mkdir -p "$CADDY_TLS_DIR"
  sudo cp "$TLS_DIR/cert.pem" "$TLS_DIR/key.pem" "$CADDY_TLS_DIR/"
  sudo chown -R caddy:caddy "$CADDY_TLS_DIR"
  sudo chmod 600 "$CADDY_TLS_DIR/key.pem"
  echo "    deployed → $CADDY_TLS_DIR/{cert,key}.pem"

  # The service reads /etc/caddy/Caddyfile. A symlink into the repo won't work —
  # the caddy user can't traverse the private /opt tree — so install a real copy.
  # (Re-run this script after editing the repo Caddyfile to refresh the copy.)
  echo "==> Installing Caddyfile to /etc/caddy/Caddyfile (needs sudo)…"
  sudo rm -f /etc/caddy/Caddyfile
  sudo cp "$ROOT/Caddyfile" /etc/caddy/Caddyfile
fi

cat <<EOF

✓ Done.
  cert: $TLS_DIR/cert.pem  (deployed copy: $CADDY_TLS_DIR/cert.pem)
  key:  $TLS_DIR/key.pem   (deployed copy: $CADDY_TLS_DIR/key.pem)
  SANs: localhost 127.0.0.1 ::1 $HOST $HOST.local $IPS

Next (packaged caddy.service — see docs/reference/https-localhost.md):
  1. Apply it:              sudo systemctl restart caddy
  2. Browse from this box:  https://localhost:8443
  (cert + /etc/caddy/Caddyfile were installed above; re-run this script after
   editing the repo Caddyfile to refresh the copy.)

To trust the cert on a PHONE / other LAN device (kills the "Not Secure" warning),
install the mkcert root CA on that device:

  CA file: $CAROOT/rootCA.pem

  • iOS:     AirDrop/email rootCA.pem to the device → install the profile, then
             Settings → General → About → Certificate Trust Settings → enable it.
  • Android: copy rootCA.pem over → Settings → Security → Encryption & credentials
             → Install a certificate → CA certificate.

Then browse:  https://$HOST.local:8443   (or https://<this-machine-LAN-IP>:8443)
EOF
