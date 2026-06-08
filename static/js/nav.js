(function () {
  // Nav model: top-level entries are either links ({href,label,...}) or
  // dropdown groups ({label, dropdown:[…links…]}). The order here is the
  // order shown on desktop; dropdown groups also become section headers in
  // the mobile menu built below.
  const NAV_ITEMS = [
    { href: '/', label: 'AI Jobs', cls: 'nav-home' },
    { label: 'Generate', dropdown: [
      { href: '/chain', label: 'Text',   page: 'chain' },
      { href: '/voice', label: 'Audio',  page: 'voice' },
      { href: '/image', label: 'Visual', page: 'image' },
    ]},
    { label: 'Tools', dropdown: [
      { href: '/context/',   label: 'Context',   page: 'context'   },
      { href: '/wildcards/', label: 'Wildcards', page: 'wildcards' },
      { href: '/ticks',      label: 'Ticks',     page: 'ticks'     },
      { href: '/mcp',        label: 'MCP',       page: 'mcp'       },
      { href: '/embed-lab/', label: 'Embed Lab', page: 'embed-lab' },
      { href: '/memory-lab/', label: 'Memory Lab', page: 'memory-lab' },
      { href: '/prompt-pal/', label: 'Prompt Pal', page: 'prompt-pal' },
      { href: '/packs/',     label: 'Packs',      page: 'packs'      },
    ]},
    { label: 'Manage', dropdown: [
      { href: '/tickets/', label: 'Tickets', page: 'tickets' },
      { href: '/server',   label: 'Server',  page: 'server'  },
      { href: '/jobs',     label: 'Jobs',    page: 'jobs'    },
      { href: '/docs/',    label: 'Docs',    page: 'docs'    },
      { href: '/cruddables/', label: 'Cruddables', page: 'cruddables' },
    ]},
    { label: 'Apps', dropdown: [
      { href: '/apps/',             label: 'All Apps',    page: 'apps' },
      { href: '/apps/blaboratory/', label: 'Blaboratory', page: 'apps' },
      { href: '/apps/hoodat/',      label: 'Hoodat',      page: 'apps' },
      { href: '/apps/prattletale/', label: 'Prattletale', page: 'apps' },
      { href: '/apps/tomeberry/',   label: 'Tomeberry',   page: 'apps' },
    ]},
    // Quick Actions are not links — each `action` dispatches to a handler in
    // window.runQuickAction (defined below). Commonly-repeated chores live here.
    { label: 'Quick Actions', dropdown: [
      { action: 'reboot',      label: 'Reboot' },
      { action: 'catch-up',    label: 'Catch-Up' },
      { action: 'delete-jobs', label: 'Delete Jobs' },
    ]},
  ];

  // Expose for nav-mobile.js (it rebuilds the mobile menu from this same
  // model rather than cloning the desktop DOM, because dropdowns nest).
  window.NAV_ITEMS = NAV_ITEMS;

  const nav = document.getElementById('topnav');
  if (!nav) return;

  const currentPage = window.location.pathname.split('/').filter(Boolean)[0] || '';

  function makeLink(item) {
    const a = document.createElement('a');
    a.textContent = item.label;
    if (item.cls) a.className = item.cls;
    // Action items dispatch to a quick-action handler instead of navigating.
    if (item.action) {
      a.href = '#';
      a.classList.add('nav-action');
      a.dataset.action = item.action;
      a.addEventListener('click', (e) => {
        e.preventDefault();
        closeAllDropdowns();
        window.runQuickAction(item.action);
      });
      return a;
    }
    a.href = item.href;
    if (item.page) {
      a.dataset.page = item.page;
      if (item.page === currentPage) a.classList.add('active');
    }
    return a;
  }

  function closeAllDropdowns(except) {
    nav.querySelectorAll('.nav-dropdown.open').forEach((d) => {
      if (d === except) return;
      d.classList.remove('open');
      const t = d.querySelector('.nav-dropdown-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  }

  // Build a dropdown: a button trigger + an absolutely-positioned panel.
  // Clicking the trigger toggles `.open`; outside-click and ESC close it.
  function makeDropdown(group) {
    const wrap = document.createElement('div');
    wrap.className = 'nav-dropdown';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nav-dropdown-trigger';
    btn.setAttribute('aria-haspopup', 'true');
    btn.setAttribute('aria-expanded', 'false');
    btn.innerHTML = `${group.label}<span class="nav-chev" aria-hidden="true">▾</span>`;

    const panel = document.createElement('div');
    panel.className = 'nav-dropdown-panel';
    let hasActive = false;
    group.dropdown.forEach((child) => {
      const link = makeLink(child);
      if (link.classList.contains('active')) hasActive = true;
      panel.appendChild(link);
    });
    if (hasActive) btn.classList.add('active');

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = wrap.classList.toggle('open');
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      closeAllDropdowns(wrap); // close any sibling dropdowns
    });

    wrap.appendChild(btn);
    wrap.appendChild(panel);
    return wrap;
  }

  NAV_ITEMS.forEach((item) => {
    if (item.dropdown) {
      nav.appendChild(makeDropdown(item));
    } else {
      nav.appendChild(makeLink(item));
    }
  });

  // Outside click + ESC close any open dropdown.
  document.addEventListener('click', (e) => {
    if (nav.contains(e.target)) return;
    closeAllDropdowns();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllDropdowns();
  });

  /* ── Quick Actions ─────────────────────────────────────────────────────
     Self-contained (no api.js / toast.js dependency, so this works on every
     page that loads nav.js). A small fixed toast + a streaming run-log panel
     (reusing the .peer-deploy-* styles) provide feedback. */

  function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

  function qaToast(msg, kind) {
    let stack = document.getElementById('qa-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.id = 'qa-toast-stack';
      document.body.appendChild(stack);
    }
    const t = document.createElement('div');
    t.className = `qa-toast qa-toast-${kind || 'info'}`;
    t.textContent = msg;
    stack.appendChild(t);
    setTimeout(() => {
      t.classList.add('qa-toast-out');
      setTimeout(() => t.remove(), 300);
    }, 3600);
  }

  // A floating log panel for long-running quick actions (reboot, catch-up).
  function openRunPanel(title) {
    const existing = document.getElementById('qa-run-panel');
    if (existing) existing.remove();
    const panel = document.createElement('div');
    panel.id = 'qa-run-panel';
    panel.className = 'peer-deploy-panel';
    panel.innerHTML =
      `<div class="peer-deploy-header">` +
        `<span class="peer-deploy-title"></span>` +
        `<span class="peer-deploy-status" data-role="status">starting…</span>` +
        `<button type="button" class="peer-deploy-close" data-role="close" ` +
          `aria-label="Close">×</button>` +
      `</div>` +
      `<pre class="peer-deploy-log" data-role="log"></pre>`;
    document.body.appendChild(panel);
    panel.querySelector('.peer-deploy-title').textContent = title;
    const logEl = panel.querySelector('[data-role="log"]');
    const statusEl = panel.querySelector('[data-role="status"]');
    panel.querySelector('[data-role="close"]')
      .addEventListener('click', () => panel.remove());

    const atBottom = () =>
      logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 8;

    return {
      el: panel,
      log(line) {
        const stick = atBottom();
        logEl.textContent += (logEl.textContent ? '\n' : '') + line;
        if (stick) logEl.scrollTop = logEl.scrollHeight;
      },
      setLog(lines) {
        const stick = atBottom();
        logEl.textContent = (lines || []).join('\n');
        if (stick) logEl.scrollTop = logEl.scrollHeight;
      },
      status(kind, text) {
        statusEl.className = `peer-deploy-status peer-deploy-status-${kind}`;
        statusEl.textContent = text;
      },
      close() { panel.remove(); },
    };
  }

  async function healthOk() {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 2500);
    try {
      const r = await fetch('/v1/server/health', { signal: ctrl.signal, cache: 'no-store' });
      return r.ok;
    } catch (_) {
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function clearCachesAndReload() {
    try {
      if (window.caches && caches.keys) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch (_) { /* Cache Storage may be unavailable; reload still revalidates */ }
    location.reload();
  }

  /* ── Reboot ──────────────────────────────────────────────────────────── */
  async function doReboot() {
    if (!confirm('Reboot the server?\nThe page will clear its cache and refresh once the server is back.')) {
      return;
    }
    const ov = openRunPanel('Reboot');
    ov.status('running', 'restarting…');
    ov.log('$ POST /v1/server/restart');
    try {
      const r = await fetch('/v1/server/restart', { method: 'POST' });
      if (!r.ok) {
        ov.log('ERROR: HTTP ' + r.status);
        ov.status('error', 'failed to start');
        return;
      }
    } catch (e) {
      ov.log('ERROR: ' + (e && e.message ? e.message : String(e)));
      ov.status('error', 'failed to start');
      return;
    }
    ov.log('restart scheduled — waiting for the server to go down…');

    // Phase 1: wait until health stops responding (server re-execing), ~12s cap.
    let wentDown = false;
    for (let i = 0; i < 24; i++) {
      await sleep(500);
      if (!(await healthOk())) { wentDown = true; break; }
    }
    ov.log(wentDown ? 'server is down; waiting for it to come back…'
                    : 'server still responding; waiting for it to come back…');

    // Phase 2: wait until health responds again, ~60s cap.
    for (let i = 0; i < 120; i++) {
      await sleep(500);
      if (await healthOk()) {
        ov.log('server is back up — clearing cache and refreshing.');
        ov.status('done', 'back up — refreshing');
        await sleep(600);
        await clearCachesAndReload();
        return;
      }
    }
    ov.log('ERROR: server did not come back within ~60s. Refresh manually.');
    ov.status('error', 'timeout');
  }

  /* ── Catch-Up (deploy_all) ───────────────────────────────────────────── */
  async function doCatchUp() {
    const msg = prompt(
      'Catch-Up commit message:\n' +
      '(commit → merge active branch to master → push local + gh → deploy secondary)'
    );
    if (msg === null) return; // cancelled
    const message = msg.trim();
    if (!message) { qaToast('A commit message is required.', 'error'); return; }

    const ov = openRunPanel('deploy_all');
    ov.status('running', 'starting…');
    ov.setLog(['$ scripts/deploy_all "' + message + '"']);

    try {
      const r = await fetch('/v1/server/deploy-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      if (!r.ok) {
        let detail = 'HTTP ' + r.status;
        try { const j = await r.json(); if (j && j.detail) detail = String(j.detail); } catch (_) {}
        ov.log('ERROR: ' + detail);
        ov.status('error', 'failed to start');
        return;
      }
    } catch (e) {
      ov.log('ERROR: ' + (e && e.message ? e.message : String(e)));
      ov.status('error', 'failed to start');
      return;
    }

    pollDeploy(ov);
  }

  // Poll the shared deploy status until it leaves "running". deploy_all ends by
  // restarting this local server, so a burst of fetch failures while status was
  // last seen "running" means success, not failure.
  async function pollDeploy(ov) {
    let sawRunning = false;
    let failStreak = 0;
    while (true) {
      await sleep(1000);
      let snap = null;
      try {
        const r = await fetch('/v1/server/deploy-status', { cache: 'no-store' });
        if (r.ok) snap = await r.json();
      } catch (_) { /* network/restart hiccup */ }

      if (!snap) {
        failStreak += 1;
        if (sawRunning && failStreak >= 15) {
          ov.log('— local server appears restarted; refresh to confirm —');
          ov.status('done', 'local restarted');
          return;
        }
        if (!sawRunning && failStreak >= 5) {
          ov.log('ERROR: lost contact with server.');
          ov.status('error', 'lost contact');
          return;
        }
        continue;
      }

      failStreak = 0;
      ov.setLog(snap.lines || []);
      if (snap.status === 'running') {
        sawRunning = true;
        ov.status('running', 'running…');
        continue;
      }
      if (snap.status === 'done') {
        ov.status('done', 'done (exit 0)');
      } else if (snap.status === 'error') {
        const ec = (snap.exit_code != null) ? snap.exit_code : '?';
        ov.status('error', `error (exit ${ec})`);
      } else {
        ov.status(snap.status || 'idle', snap.status || 'idle');
      }
      return;
    }
  }

  /* ── Delete Jobs ─────────────────────────────────────────────────────── */
  async function doDeleteJobs() {
    if (!confirm('Delete ALL jobs? This permanently removes every job on disk and cannot be undone.')) {
      return;
    }
    try {
      const r = await fetch('/v1/jobs/all', { method: 'DELETE' });
      if (!r.ok) { qaToast('Delete failed: HTTP ' + r.status, 'error'); return; }
      const j = await r.json();
      qaToast(`Deleted ${j.removed ?? 0} job(s).`, 'done');
      // Refresh the listing if we're looking at it.
      if (currentPage === 'jobs') setTimeout(() => location.reload(), 700);
    } catch (e) {
      qaToast('Delete failed: ' + (e && e.message ? e.message : String(e)), 'error');
    }
  }

  const QUICK_ACTIONS = {
    'reboot': doReboot,
    'catch-up': doCatchUp,
    'delete-jobs': doDeleteJobs,
  };

  // Exposed so nav-mobile.js (which rebuilds the menu) can reuse the handlers.
  window.runQuickAction = function (action) {
    const fn = QUICK_ACTIONS[action];
    if (fn) fn();
  };
})();
