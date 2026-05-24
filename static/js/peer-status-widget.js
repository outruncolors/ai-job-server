/* Peer status widget: dots pinned at the right edge of #topnav, one per
   configured peer. Polls /v1/server/peers every 30s and colors each dot by
   the server-side health snapshot. On SHA mismatch, also renders a banner
   under the topnav with the version-skew hint.

   Self-contained — no dependency on api.js / toast.js / escape.js. */

(function () {
  const esc = (typeof _escHtml === 'function')
    ? _escHtml
    : (s) => String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[c]));

  const POLL_MS = 30_000;

  let groupEl = null;
  let bannerEl = null;
  let pollTimer = null;

  // Deploy log overlay state (only created when the user clicks Deploy now).
  let deployPanelEl = null;
  let deployLogEl = null;
  let deployStatusEl = null;
  let deployCloseBtn = null;
  let deployPollTimer = null;
  let deployFailStreak = 0;
  let deployLastSawRunning = false;

  async function fetchPeers() {
    try {
      const r = await fetch('/v1/server/peers');
      if (!r.ok) return null;
      return await r.json();
    } catch (_) {
      return null;
    }
  }

  function build() {
    const nav = document.getElementById('topnav');
    if (!nav) return;
    if (document.getElementById('nav-peer-group')) return;

    groupEl = document.createElement('div');
    groupEl.id = 'nav-peer-group';
    groupEl.className = 'nav-peer-group';
    // Insert before the profile group so peer dots sit just to its left.
    // If profile group isn't there yet (script order or page without it),
    // fall back to plain append — the group has its own margin-left:auto.
    const profileGroup = document.getElementById('nav-profile-group');
    if (profileGroup) {
      nav.insertBefore(groupEl, profileGroup);
    } else {
      nav.appendChild(groupEl);
    }

    refresh();
    pollTimer = setInterval(refresh, POLL_MS);
  }

  function shortSha(sha) {
    if (!sha) return '—';
    return String(sha).slice(0, 7);
  }

  function relTime(iso) {
    if (!iso) return 'never';
    const t = Date.parse(iso);
    if (Number.isNaN(t)) return 'unknown';
    const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  }

  function tooltip(peer, h, localSha) {
    const lines = [
      `${peer.name} (${peer.host}:${peer.port})`,
      `status: ${h ? h.status : 'unknown'}`,
      `peer sha: ${shortSha(h && h.git_sha)}`,
      `local sha: ${shortSha(localSha)}`,
      `last seen: ${relTime(h && h.last_seen)}`,
    ];
    if (h && h.error) lines.push(`error: ${h.error}`);
    return lines.join('\n');
  }

  function render(data) {
    if (!groupEl) return;
    if (!data || !Array.isArray(data.peers) || data.peers.length === 0) {
      groupEl.innerHTML = '';
      renderBanner(null);
      return;
    }
    const localSha = data.local_git_sha || null;

    groupEl.innerHTML = '';
    let amberPeer = null;
    for (const peer of data.peers) {
      const h = peer.health;
      const status = (h && h.status) || 'unknown';

      const dot = document.createElement('span');
      dot.className = `peer-dot peer-dot-${status}`;
      dot.setAttribute('role', 'img');
      dot.setAttribute('aria-label', `${peer.name}: ${status}`);
      dot.title = tooltip(peer, h, localSha);
      groupEl.appendChild(dot);

      if (status === 'amber' && !amberPeer) amberPeer = { peer, h };
    }

    renderBanner(amberPeer ? { ...amberPeer, localSha } : null);
  }

  function renderBanner(info) {
    if (!info) {
      if (bannerEl) {
        bannerEl.remove();
        bannerEl = null;
      }
      document.body.classList.remove('has-peer-skew-banner');
      return;
    }
    if (!bannerEl) {
      bannerEl = document.createElement('div');
      bannerEl.id = 'peer-skew-banner';
      bannerEl.className = 'peer-skew-banner';
      document.body.appendChild(bannerEl);
      document.body.classList.add('has-peer-skew-banner');
    }
    const peerSha = shortSha(info.h && info.h.git_sha);
    const localSha = shortSha(info.localSha);
    const peerHost = info.peer.host;
    bannerEl.innerHTML =
      `<span class="peer-skew-msg">` +
        `Peer <code>${esc(peerHost)}</code> is on commit ` +
        `<code>${esc(peerSha)}</code>, this machine is on ` +
        `<code>${esc(localSha)}</code>.` +
      `</span>` +
      `<button type="button" class="peer-skew-deploy-btn" ` +
        `data-peer="${esc(peerHost)}">Deploy now</button>`;
    const btn = bannerEl.querySelector('.peer-skew-deploy-btn');
    if (btn) {
      btn.addEventListener('click', () => startDeploy(btn.dataset.peer || ''));
    }
  }

  /* ── Deploy panel ────────────────────────────────────────────────────── */

  function ensureDeployPanel() {
    if (deployPanelEl) return;
    deployPanelEl = document.createElement('div');
    deployPanelEl.id = 'peer-deploy-panel';
    deployPanelEl.className = 'peer-deploy-panel';
    deployPanelEl.innerHTML =
      `<div class="peer-deploy-header">` +
        `<span class="peer-deploy-title">deploy-secondary.sh</span>` +
        `<span class="peer-deploy-status" data-role="status">starting…</span>` +
        `<button type="button" class="peer-deploy-close" data-role="close" ` +
          `aria-label="Close">×</button>` +
      `</div>` +
      `<pre class="peer-deploy-log" data-role="log"></pre>`;
    document.body.appendChild(deployPanelEl);
    deployLogEl = deployPanelEl.querySelector('[data-role="log"]');
    deployStatusEl = deployPanelEl.querySelector('[data-role="status"]');
    deployCloseBtn = deployPanelEl.querySelector('[data-role="close"]');
    deployCloseBtn.addEventListener('click', closeDeployPanel);
  }

  function closeDeployPanel() {
    if (deployPollTimer) {
      clearInterval(deployPollTimer);
      deployPollTimer = null;
    }
    if (deployPanelEl) {
      deployPanelEl.remove();
      deployPanelEl = null;
      deployLogEl = null;
      deployStatusEl = null;
      deployCloseBtn = null;
    }
    deployFailStreak = 0;
    deployLastSawRunning = false;
  }

  async function startDeploy(peerHost) {
    ensureDeployPanel();
    setDeployStatus('running', 'starting…');
    setDeployLog(['$ scripts/deploy-secondary.sh ' + (peerHost || '')]);

    // Disable the banner button so double-clicks don't pile up requests.
    const btn = bannerEl && bannerEl.querySelector('.peer-skew-deploy-btn');
    if (btn) {
      btn.disabled = true;
      btn.textContent = 'Deploying…';
    }

    try {
      const r = await fetch('/v1/server/deploy-secondary', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(peerHost ? { peer_host: peerHost } : {}),
      });
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try {
          const j = await r.json();
          if (j && j.detail) msg = String(j.detail);
        } catch (_) { /* keep status-line msg */ }
        appendDeployLine('ERROR: ' + msg);
        setDeployStatus('error', 'failed to start');
        if (btn) { btn.disabled = false; btn.textContent = 'Deploy now'; }
        return;
      }
    } catch (e) {
      appendDeployLine('ERROR: ' + (e && e.message ? e.message : String(e)));
      setDeployStatus('error', 'failed to start');
      if (btn) { btn.disabled = false; btn.textContent = 'Deploy now'; }
      return;
    }

    deployFailStreak = 0;
    deployLastSawRunning = false;
    if (deployPollTimer) clearInterval(deployPollTimer);
    deployPollTimer = setInterval(pollDeploy, 1000);
    pollDeploy(); // immediate first poll
  }

  async function pollDeploy() {
    let snap = null;
    try {
      const r = await fetch('/v1/server/deploy-secondary');
      if (r.ok) snap = await r.json();
    } catch (_) { /* network/restart hiccup */ }

    if (!snap) {
      deployFailStreak += 1;
      // The script restarts the local FastAPI process near the end, so a
      // burst of fetch failures while status=running is expected. Only call
      // it actually-failed after enough consecutive misses.
      if (deployLastSawRunning && deployFailStreak >= 15) {
        appendDeployLine(
          '— local server appears restarted; refresh the page to confirm —'
        );
        setDeployStatus('done', 'local restarted');
        if (deployPollTimer) { clearInterval(deployPollTimer); deployPollTimer = null; }
      } else if (!deployLastSawRunning && deployFailStreak >= 5) {
        appendDeployLine('ERROR: lost contact with server');
        setDeployStatus('error', 'lost contact');
        if (deployPollTimer) { clearInterval(deployPollTimer); deployPollTimer = null; }
      }
      return;
    }

    deployFailStreak = 0;
    setDeployLog(snap.lines || []);

    if (snap.status === 'running') {
      deployLastSawRunning = true;
      setDeployStatus('running', 'running…');
      return;
    }

    if (snap.status === 'done') {
      setDeployStatus('done', 'done (exit 0)');
    } else if (snap.status === 'error') {
      const ec = (snap.exit_code != null) ? snap.exit_code : '?';
      setDeployStatus('error', `error (exit ${ec})`);
    } else {
      setDeployStatus(snap.status || 'idle', snap.status || 'idle');
    }
    if (deployPollTimer) { clearInterval(deployPollTimer); deployPollTimer = null; }

    // Re-enable button so the user can retry if it failed.
    const btn = bannerEl && bannerEl.querySelector('.peer-skew-deploy-btn');
    if (btn) {
      btn.disabled = false;
      btn.textContent = (snap.status === 'done') ? 'Deploy again' : 'Deploy now';
    }
  }

  function setDeployStatus(kind, text) {
    if (!deployStatusEl) return;
    deployStatusEl.className = `peer-deploy-status peer-deploy-status-${kind}`;
    deployStatusEl.textContent = text;
  }

  function setDeployLog(lines) {
    if (!deployLogEl) return;
    const nearBottom =
      deployLogEl.scrollTop + deployLogEl.clientHeight >= deployLogEl.scrollHeight - 8;
    deployLogEl.textContent = (lines || []).join('\n');
    if (nearBottom) deployLogEl.scrollTop = deployLogEl.scrollHeight;
  }

  function appendDeployLine(line) {
    if (!deployLogEl) return;
    const nearBottom =
      deployLogEl.scrollTop + deployLogEl.clientHeight >= deployLogEl.scrollHeight - 8;
    deployLogEl.textContent += (deployLogEl.textContent ? '\n' : '') + line;
    if (nearBottom) deployLogEl.scrollTop = deployLogEl.scrollHeight;
  }

  async function refresh() {
    const data = await fetchPeers();
    render(data);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
