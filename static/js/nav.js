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
    a.href = item.href;
    a.textContent = item.label;
    if (item.cls) a.className = item.cls;
    if (item.page) {
      a.dataset.page = item.page;
      if (item.page === currentPage) a.classList.add('active');
    }
    return a;
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
      // Close any sibling dropdowns
      nav.querySelectorAll('.nav-dropdown.open').forEach((d) => {
        if (d !== wrap) {
          d.classList.remove('open');
          const t = d.querySelector('.nav-dropdown-trigger');
          if (t) t.setAttribute('aria-expanded', 'false');
        }
      });
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
    nav.querySelectorAll('.nav-dropdown.open').forEach((d) => {
      d.classList.remove('open');
      const t = d.querySelector('.nav-dropdown-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    nav.querySelectorAll('.nav-dropdown.open').forEach((d) => {
      d.classList.remove('open');
      const t = d.querySelector('.nav-dropdown-trigger');
      if (t) t.setAttribute('aria-expanded', 'false');
    });
  });
})();
