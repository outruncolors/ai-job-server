/* Apps landing — renders the app catalog. Add an entry here to list a new app.
   Deliberately self-contained: no systems nav, no shared api() needed. */
(function () {
  const APPS = [
    {
      href: '/apps/blaboratory/',
      name: 'Blaboratory',
      tagline: 'A virtual lab of AI residents.',
      blurb: 'Fill rooms with LLM-generated characters, each a living document.',
      glyph: '⚗', // alembic
    },
    {
      href: '/apps/hoodat/',
      name: 'Hoodat',
      tagline: 'Create & manage characters.',
      blurb: 'Build characters from a prompt, regenerate any field, and export them at any detail.',
      glyph: '🧑',
    },
    {
      href: '/apps/prattletale/',
      name: 'Prattletale',
      tagline: 'iMessage-style roleplay chat.',
      blurb: 'Text a Hoodat character; the model replies in a burst of short, typed bubbles.',
      glyph: '💬',
    },
  ];

  const esc = (s) => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  const grid = document.getElementById('apps-grid');
  grid.innerHTML = APPS.map((app) => `
    <a class="app-card" href="${esc(app.href)}">
      <div class="app-glyph">${esc(app.glyph)}</div>
      <div class="app-name">${esc(app.name)}</div>
      <div class="app-tagline">${esc(app.tagline)}</div>
      <div class="app-blurb">${esc(app.blurb)}</div>
    </a>
  `).join('');
})();
