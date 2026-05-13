document.addEventListener('DOMContentLoaded', () => {
  const nav = document.getElementById('topnav');
  if (!nav) return;

  // Collect all nav items except the home link (links + page-specific buttons)
  const items = [...nav.querySelectorAll(':scope > a:not(.nav-home), :scope > button:not(.nav-hamburger)')];
  if (items.length === 0) return;

  // Build mobile dropdown from cloned nav items
  const menu = document.createElement('div');
  menu.className = 'nav-links-mobile';
  items.forEach(item => menu.appendChild(item.cloneNode(true)));
  nav.parentNode.insertBefore(menu, nav.nextSibling);

  // Close menu when any item inside it is clicked
  menu.addEventListener('click', () => menu.classList.remove('open'));

  // Hamburger toggle button (appended last so it sits at far right via margin-left:auto)
  const btn = document.createElement('button');
  btn.className = 'nav-hamburger';
  btn.setAttribute('aria-label', 'Menu');
  btn.textContent = '☰';
  nav.appendChild(btn);

  btn.addEventListener('click', e => {
    e.stopPropagation();
    menu.classList.toggle('open');
  });

  // Close on outside click
  document.addEventListener('click', e => {
    if (!nav.contains(e.target) && !menu.contains(e.target)) {
      menu.classList.remove('open');
    }
  });
});
