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
    bannerEl.innerHTML =
      `Peer <code>${esc(info.peer.host)}</code> is on commit ` +
      `<code>${esc(peerSha)}</code>, this machine is on ` +
      `<code>${esc(localSha)}</code> — consider running ` +
      `<code>scripts/deploy-secondary.sh</code>.`;
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
