/* Hoodat master list: character cards + search + create→redirect to profile. */
(function () {
  const $ = (id) => document.getElementById(id);
  const APP = '/apps/hoodat';

  let _characters = [];

  async function load() {
    const data = await api(`${APP}/characters`);
    _characters = data.characters || [];
    render();
  }

  function avatarColor(id) {
    const s = String(id || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return `hsl(${h} 38% 30%)`;
  }

  function visible() {
    const q = $('hd-search').value.trim().toLowerCase();
    if (!q) return _characters;
    return _characters.filter((c) =>
      [c.name, c.tagline, c.summary, c.occupation].join(' ').toLowerCase().includes(q));
  }

  function render() {
    const grid = $('hd-grid');
    const items = visible();
    if (!items.length) {
      grid.innerHTML = '<div class="hd-empty">No characters yet. Create one to get started.</div>';
      return;
    }
    grid.innerHTML = items.map((c) => {
      const initial = _escHtml((c.name || '?').trim().charAt(0).toUpperCase() || '?');
      const av = c.avatar_path
        ? `<img class="hd-card-av" src="${_escHtml(c.avatar_path)}?v=${_escHtml(c.updated_at || '')}" alt="">`
        : `<span class="hd-card-av hd-card-av-ph" style="background:${avatarColor(c.id)}">${initial}</span>`;
      return `<a class="hd-card" href="profile.html?id=${encodeURIComponent(c.id)}">
        ${av}
        <span class="hd-card-name">${_escHtml(c.name || 'Unnamed')}</span>
        <span class="hd-card-tag">${_escHtml(c.tagline || c.occupation || '')}</span>
      </a>`;
    }).join('');
  }

  // ---- create dialog ----
  function openCreate() {
    $('hd-create-name').value = '';
    $('hd-create-prompt').value = '';
    $('hd-create-msg').textContent = '';
    $('hd-create-submit').disabled = false;
    $('hd-create-dialog').showModal();
  }

  async function submitCreate() {
    const name = $('hd-create-name').value.trim();
    const msg = $('hd-create-msg');
    if (!name) { msg.textContent = 'Name is required.'; return; }
    const btn = $('hd-create-submit');
    btn.disabled = true;
    msg.textContent = 'Generating character… this can take a moment.';
    try {
      const res = await api(`${APP}/characters`, 'POST', { name, prompt: $('hd-create-prompt').value });
      location.href = `profile.html?id=${encodeURIComponent(res.character.id)}`;
    } catch (err) {
      msg.textContent = 'Create failed: ' + err.message;
      btn.disabled = false;
    }
  }

  function wire() {
    $('hd-search').addEventListener('input', render);
    $('hd-new').addEventListener('click', openCreate);
    $('hd-create-close').addEventListener('click', () => $('hd-create-dialog').close());
    $('hd-create-cancel').addEventListener('click', () => $('hd-create-dialog').close());
    $('hd-create-submit').addEventListener('click', submitCreate);
  }

  wire();
  load();
})();
