(function () {
  const NAV_ITEMS = [
    { href: '/',         label: 'AI Jobs',  cls: 'nav-home' },
    { href: '/chain',    label: 'Chain',    page: 'chain'   },
    { href: '/context/', label: 'Context',  page: 'context' },
    { href: '/voice',    label: 'Voice',    page: 'voice'   },
    { href: '/image',    label: 'Image',    page: 'image'   },
    { href: '/jobs',     label: 'Jobs',     page: 'jobs'    },
    { href: '/server',   label: 'Server',   page: 'server'  },
    { href: '/mcp',      label: 'MCP',      page: 'mcp'     },
  ];

  const nav = document.getElementById('topnav');
  if (!nav) return;

  // Derive the current page from the first path segment (/chain → "chain")
  const currentPage = window.location.pathname.split('/').filter(Boolean)[0] || '';

  NAV_ITEMS.forEach(({ href, label, cls, page }) => {
    const a = document.createElement('a');
    a.href = href;
    a.textContent = label;
    if (cls) a.className = cls;
    if (page) {
      a.dataset.page = page;
      if (page === currentPage) a.classList.add('active');
    }
    nav.appendChild(a);
  });
})();
