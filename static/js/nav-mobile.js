document.addEventListener('DOMContentLoaded', () => {
  const nav = document.getElementById('topnav');
  if (!nav) return;

  const items = window.NAV_ITEMS;
  if (!Array.isArray(items) || items.length === 0) return;

  const currentPage = window.location.pathname.split('/').filter(Boolean)[0] || '';

  // Build mobile menu from the same NAV_ITEMS model. Dropdown groups render
  // as a section header followed by their child links (flat — the hamburger
  // panel is already vertical, no need for collapse-within-collapse).
  const menu = document.createElement('div');
  menu.className = 'nav-links-mobile';

  function appendLink(parent, item) {
    const a = document.createElement('a');
    a.href = item.href;
    a.textContent = item.label;
    if (item.cls) a.className = item.cls;
    if (item.page) {
      a.dataset.page = item.page;
      if (item.page === currentPage) a.classList.add('active');
    }
    parent.appendChild(a);
  }

  items.forEach((item) => {
    if (item.dropdown) {
      const hdr = document.createElement('div');
      hdr.className = 'nav-mobile-section';
      hdr.textContent = item.label;
      menu.appendChild(hdr);
      item.dropdown.forEach((child) => appendLink(menu, child));
    } else {
      appendLink(menu, item);
    }
  });

  nav.parentNode.insertBefore(menu, nav.nextSibling);

  // Close menu when any link inside it is clicked.
  menu.addEventListener('click', (e) => {
    if (e.target.tagName === 'A') menu.classList.remove('open');
  });

  // Hamburger toggle button (appended last so it sits at far right via
  // its own flex positioning).
  const btn = document.createElement('button');
  btn.className = 'nav-hamburger';
  btn.setAttribute('aria-label', 'Menu');
  btn.textContent = '☰';
  nav.appendChild(btn);

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    menu.classList.toggle('open');
  });

  // Close on outside click.
  document.addEventListener('click', (e) => {
    if (!nav.contains(e.target) && !menu.contains(e.target)) {
      menu.classList.remove('open');
    }
  });
});
