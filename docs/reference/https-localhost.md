# HTTPS for LAN access

## Why

The **Voice/STT** page records the microphone with `navigator.mediaDevices.getUserMedia()`
(`static/voice/stt.js`). Browsers only expose the mic (and clipboard, service workers, etc.)
in a **secure context**. A secure context is HTTPS *or* `http://localhost`/`127.0.0.1`.

So mic recording already works when you browse from the same machine via `localhost`. It does
**not** work when you open the app from a phone or another device over the LAN IP
(`http://192.168.x.x:8090`) — that origin is not secure, and `getUserMedia` falls back to the
manual file-upload path.

The fix is to serve the app over HTTPS for LAN devices.

## How it works

We terminate TLS in front of the app with [Caddy](https://caddyserver.com/), using a
locally-trusted certificate from [mkcert](https://github.com/FiloSottile/mkcert). uvicorn is
**unchanged** — it keeps serving plain HTTP on `:8090`. Peers also keep talking to it over
plain HTTP. Only the browser→app leg is encrypted.

```
phone / LAN browser ──HTTPS :8443──▶ Caddy ──HTTP 127.0.0.1:8090──▶ uvicorn (unchanged)
other peers         ──HTTP  :8090──────────────────────────────────▶ uvicorn (unchanged)
```

The frontend uses relative API paths (`/v1/...`) and a same-origin `EventSource`, so nothing in
the UI changes — requests just ride the proxy. Caddy streams the SSE job timeline
(`/v1/jobs/<id>/stream`) without buffering (`flush_interval -1` in the `Caddyfile`).

## One-time setup

1. **Install the tools** (on the machine that faces the LAN):

   ```bash
   sudo apt install -y mkcert libnss3-tools caddy
   ```
   (Caddy is also available from the official Caddy apt repo; mkcert can alternatively be a
   release binary from its GitHub page.)

2. **Generate the certificate:**

   ```bash
   bash scripts/tls-setup.sh
   ```
   This installs the mkcert local CA on this machine and writes
   `config/tls/cert.pem` + `config/tls/key.pem`, valid for `localhost`, `127.0.0.1`, the
   machine's hostname, its `.local` mDNS name, and every LAN IP. (`config/` is gitignored, so
   the cert/key are never committed.)

   It then **deploys a copy to `/var/lib/caddy/tls/`** (needs sudo). This matters: the repo
   tree (`/opt/ai-stack/...`) is private (`0700`/`2770`), so the `caddy` system user can't
   traverse into it to read certs under `config/tls`. The certs must live somewhere `caddy`
   owns — its home is the natural spot. The `Caddyfile`'s `tls` directive points there.

3. **Apply it:**

   The Debian `caddy` package ships a system service (`caddy.service`) that reads
   `/etc/caddy/Caddyfile`. `tls-setup.sh` already installed a **copy** of our `Caddyfile`
   there (a symlink into the repo won't work — the `caddy` user can't traverse the private
   `/opt` tree). Just restart the service:

   ```bash
   sudo systemctl restart caddy
   ```

   > Because `/etc/caddy/Caddyfile` is a copy, **re-run `bash scripts/tls-setup.sh` after
   > editing the repo `Caddyfile`** to refresh it (or `sudo cp Caddyfile /etc/caddy/Caddyfile`).

   > **No caddy package?** If Caddy isn't installed as a service, you can instead run it as
   > your own user — `caddy run --config Caddyfile` (ad-hoc) or via the user unit
   > `scripts/systemd/ai-job-server-tls.service`. In that case the certs in `config/tls` are
   > readable directly (no `/var/lib/caddy` copy needed) since they run as you.

## Trusting the cert on a phone / other device

mkcert's CA is trusted on the machine that ran `tls-setup.sh`, but other devices will show a
"Not Secure" warning until you install the CA root there. Find it with `mkcert -CAROOT`
(the file is `rootCA.pem`):

- **iOS:** AirDrop/email `rootCA.pem` to the device → install the profile, then
  Settings → General → About → Certificate Trust Settings → enable it.
- **Android:** copy `rootCA.pem` over → Settings → Security → Encryption & credentials →
  Install a certificate → CA certificate.

Then browse to `https://<hostname>.local:8443` or `https://<LAN-IP>:8443` and use the mic.

(You can also just click through the browser warning each time without installing the CA — the
connection is still encrypted; only the trust badge differs.)

## What this does NOT change

- `run.sh`, `ai-job-server.service`, and uvicorn stay plain HTTP on `:8090`.
- All peer-to-peer traffic stays HTTP (`app/peer_health.py`, `app/chain/llm_swap.py`,
  `app/llm_config.py`, embeddings, ComfyUI/llama proxying). See
  [Multi-machine](../multi-machine.md).
