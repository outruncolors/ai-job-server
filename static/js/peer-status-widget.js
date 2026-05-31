/* Peer status widget: dots pinned at the right edge of #topnav, one per
   configured peer. Polls /v1/server/peers every 30s and colors each dot by
   the server-side health snapshot. The dot's tooltip outlines the commit
   difference on skew (amber); to sync a behind peer, use the topnav
   Quick Actions > Catch-Up action.

   Self-contained — no dependency on api.js / toast.js / escape.js. */

(function () {
  const POLL_MS = 30_000;

  let groupEl = null;
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
    const status = (h && h.status) || 'unknown';
    const lines = [
      `${peer.name} (${peer.host}:${peer.port})`,
      `status: ${status}`,
    ];
    if (status === 'amber') {
      // Spell out the commit difference — this is what the orange light means.
      lines.push('⚠ version skew — peer is on a different commit than this node:');
      lines.push(`    peer:  ${shortSha(h && h.git_sha)}`);
      lines.push(`    local: ${shortSha(localSha)}`);
      lines.push('Run Quick Actions ▸ Catch-Up to sync the peer.');
    } else {
      lines.push(`peer sha:  ${shortSha(h && h.git_sha)}`);
      lines.push(`local sha: ${shortSha(localSha)}`);
    }
    lines.push(`last seen: ${relTime(h && h.last_seen)}`);
    if (h && h.error) lines.push(`error: ${h.error}`);
    return lines.join('\n');
  }

  function render(data) {
    if (!groupEl) return;
    if (!data || !Array.isArray(data.peers) || data.peers.length === 0) {
      groupEl.innerHTML = '';
      return;
    }
    const localSha = data.local_git_sha || null;

    groupEl.innerHTML = '';
    for (const peer of data.peers) {
      const h = peer.health;
      const status = (h && h.status) || 'unknown';

      const dot = document.createElement('span');
      dot.className = `peer-dot peer-dot-${status}`;
      dot.setAttribute('role', 'img');
      dot.setAttribute('aria-label', `${peer.name}: ${status}`);
      dot.title = tooltip(peer, h, localSha);
      groupEl.appendChild(dot);
    }
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
