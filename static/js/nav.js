(function () {
  const NAV_ITEMS = [
    { href: '/',         label: 'AI Jobs',  cls: 'nav-home' },
    { href: '/chain',    label: 'Text',     page: 'chain'   },
    { href: '/voice',    label: 'Audio',    page: 'voice'   },
    { href: '/image',    label: 'Visual',   page: 'image',  groupEnd: true },
    { href: '/context/', label: 'Context',  page: 'context'   },
    { href: '/wildcards/', label: 'Wildcards', page: 'wildcards' },
    { href: '/ticks',    label: 'Ticks',    page: 'ticks'   },
    { href: '/mcp',      label: 'MCP',      page: 'mcp'     },
    { href: '/embed-lab/', label: 'Embed Lab', page: 'embed-lab', groupEnd: true },
    { href: '/tickets/', label: 'Tickets',  page: 'tickets' },
    { href: '/server',   label: 'Server',   page: 'server'  },
    { href: '/jobs',     label: 'Jobs',     page: 'jobs'    },
    { href: '/docs/',    label: 'Docs',     page: 'docs',   groupEnd: true },
    { href: '/apps/',    label: 'Apps',     page: 'apps'    },
  ];

  const nav = document.getElementById('topnav');
  if (!nav) return;

  const currentPage = window.location.pathname.split('/').filter(Boolean)[0] || '';

  NAV_ITEMS.forEach(({ href, label, cls, page, groupEnd }) => {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = label;
    if (cls) a.className = cls;
    if (page) {
      a.dataset.page = page;
      if (page === currentPage) a.classList.add('active');
    }
    nav.appendChild(a);
    if (groupEnd) {
      const sep = document.createElement('span');
      sep.className = 'nav-sep';
      nav.appendChild(sep);
    }
  });
})();
