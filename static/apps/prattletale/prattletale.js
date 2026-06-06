/* Prattletale — iMessage-style roleplay chat (text-only).
 *
 * One page, two views: a conversation list and a chat thread, toggled by the
 * `?id=<conversation_id>` query param so reloads restore the open chat from
 * disk. Counterpart name/avatar are resolved live from the Hoodat character
 * list (never copied into the conversation). The model turn is generated
 * synchronously by the POST; while it's in flight we show a client-side typing
 * indicator. A failed model turn comes back as a `system_error` item, rendered
 * as a red bubble with a Retry button. */
(function () {
  const $ = (id) => document.getElementById(id);
  const APP = '/apps/prattletale';

  // The built-in text bubble modes. Plugin-contributed composer modes are merged
  // onto these per chat in `rebuildModes()`; staged *text* bubbles only ever cycle
  // within BASE_MODES (a plugin mode is never a text-bubble type).
  const BASE_MODES = [
    { type: 'dialogue', label: '💬 Say' },
    { type: 'action', label: '🎬 Do' },
    { type: 'narration', label: '📖 Narrate' },
  ];
  // Active composer modes (BASE_MODES + enabled plugins' modes). The input is split
  // across two axes: `_sectionIdx` picks the *input mode* (0 = Essentials, which holds
  // Say/Do/Narrate; 1..N = one section per enabled plugin), shown on the mode bar above
  // the compose row. `_textModeIdx` picks Say/Do/Narrate *within* Essentials.
  let MODES = BASE_MODES.slice();

  let _characters = {};   // id -> character summary
  let _conversations = []; // list summaries
  let _current = null;     // {conversation, transcript} of the open chat
  let _draft = [];         // staged composer items before commit
  let _sectionIdx = 0;     // 0 = Essentials; 1..N = plugin sections (index into the bar)
  let _textModeIdx = 0;    // 0/1/2 within Essentials = Say/Do/Narrate
  let _editing = -1;       // index of the staged row being inline-edited, or -1
  let _sending = false;
  let _savedTextInput = '';   // in-progress composer text, stashed while a plugin mode reuses the input

  // ---------- helpers ----------

  function avatarColor(id) {
    const s = String(id || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
    return `hsl(${h} 38% 30%)`;
  }

  function avatarHtml(name, avatarPath, id, cls) {
    const initial = _escHtml((name || '?').trim().charAt(0).toUpperCase() || '?');
    if (avatarPath) {
      return `<span class="${cls}" style="background-image:url('${_escHtml(avatarPath)}')"></span>`;
    }
    return `<span class="${cls} pt-av-ph" style="background:${avatarColor(id)}">${initial}</span>`;
  }

  // Fill an existing avatar element in place (keeps its id/classes stable).
  function fillAvatar(el, name, avatarPath, id) {
    if (avatarPath) {
      el.classList.remove('pt-av-ph');
      el.textContent = '';
      el.style.background = `url('${avatarPath}') center/cover`;
    } else {
      el.classList.add('pt-av-ph');
      el.style.background = avatarColor(id);
      el.textContent = (name || '?').trim().charAt(0).toUpperCase() || '?';
    }
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    return sameDay
      ? d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
      : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }

  function counterpartOf(conv) {
    return _characters[conv.counterpart_character_id] || null;
  }

  // ---------- view routing ----------

  function currentId() {
    return new URLSearchParams(location.search).get('id');
  }

  function goList() {
    history.pushState({}, '', location.pathname);
    showView();
  }

  function openConversation(id) {
    history.pushState({}, '', `${location.pathname}?id=${encodeURIComponent(id)}`);
    showView();
  }

  async function showView() {
    const id = currentId();
    if (id) {
      $('pt-list-view').hidden = true;
      $('pt-chat-view').hidden = false;
      await loadChat(id);
    } else {
      $('pt-chat-view').hidden = true;
      $('pt-list-view').hidden = false;
      _current = null;
      await loadList();
    }
  }

  // ---------- plugins (frontend loader + hook glue) ----------

  let _pluginManifests = null;        // cached GET /plugins
  const _assetsInjected = new Set();  // plugin id -> its frontend assets injected

  async function loadPluginManifests() {
    if (_pluginManifests) return _pluginManifests;
    try {
      const data = await api(`${APP}/plugins`);
      _pluginManifests = data.plugins || [];
    } catch (_) {
      _pluginManifests = [];
    }
    return _pluginManifests;
  }

  function enabledPluginIds() {
    return (_current && _current.conversation.config
      && _current.conversation.config.enabled_plugins) || [];
  }

  // Inject one asset (script/link), once per URL. Resolves on load or error so a
  // missing asset never blocks the chat.
  function loadAsset(rel) {
    const url = '/' + String(rel).replace(/^\/+/, '');
    return new Promise((resolve) => {
      const isCss = url.endsWith('.css');
      const sel = isCss ? `link[href="${url}"]` : `script[src="${url}"]`;
      if (document.querySelector(sel)) return resolve();
      const el = isCss
        ? Object.assign(document.createElement('link'), { rel: 'stylesheet', href: url })
        : Object.assign(document.createElement('script'), { src: url });
      el.onload = el.onerror = () => resolve();
      document.head.appendChild(el);
    });
  }

  function injectPluginAssets(manifest) {
    if (_assetsInjected.has(manifest.id)) return Promise.resolve();
    _assetsInjected.add(manifest.id);
    return Promise.all((manifest.frontend || []).map(loadAsset));
  }

  // Inject the enabled plugins' assets, then rebuild the composer mode list. Run
  // on chat load and after the config dialog toggles plugins.
  async function syncPlugins() {
    const manifests = await loadPluginManifests();
    // A conversation created before plugins has no enabled_plugins key — resolve it
    // to the default-on set so those plugins are discoverable (an explicit list,
    // including [], is left untouched). Mutates the in-memory config only; it
    // persists to disk the next time the config dialog is saved.
    const cfg = _current.conversation.config || (_current.conversation.config = {});
    if (!Array.isArray(cfg.enabled_plugins)) {
      cfg.enabled_plugins = manifests.filter((m) => m.default_enabled).map((m) => m.id);
    }
    const enabled = cfg.enabled_plugins;
    await Promise.all(manifests.filter((m) => enabled.includes(m.id)).map(injectPluginAssets));
    rebuildModes();
  }

  function rebuildModes() {
    const extra = window.PtPlugins ? PtPlugins.composerModes(enabledPluginIds()) : [];
    MODES = BASE_MODES.concat(extra);
    if (_sectionIdx >= sectionCount()) _sectionIdx = 0;
    renderMode();
  }

  // ---------- conversation list ----------

  async function loadCharacters() {
    try {
      const data = await api('/apps/hoodat/characters');
      _characters = {};
      (data.characters || []).forEach((c) => { _characters[c.id] = c; });
    } catch (_) {
      _characters = {};
    }
  }

  // Delete mode: a toolbar toggle puts the list into a destructive state where the
  // first click on a card *arms* it (turns red) and the second click deletes it.
  let _deleteMode = false;

  async function loadList() {
    const list = $('pt-list');
    list.setAttribute('aria-busy', 'true');
    await loadCharacters();
    const data = await api(`${APP}/conversations`);
    _conversations = data.conversations || [];
    setDeleteMode(false);  // never restore the list into delete mode
    renderList();
    list.setAttribute('aria-busy', 'false');
  }

  // Group conversations by counterpart character. Characters are ordered by their
  // most-recent conversation; within a character, conversations are most-recent first.
  function groupConversations() {
    const ts = (c) => String(c.updated_at || '');
    const groups = new Map();  // characterId -> {id, name, avatarPath, convs[]}
    _conversations.forEach((c) => {
      const id = c.counterpart_character_id || '';
      let g = groups.get(id);
      if (!g) {
        const cp = counterpartOf(c);
        g = {
          id,
          name: cp ? cp.name : (c.title || 'Unknown character'),
          avatarPath: cp && cp.avatar_path,
          convs: [],
        };
        groups.set(id, g);
      }
      g.convs.push(c);
    });
    const arr = [...groups.values()];
    arr.forEach((g) => g.convs.sort((a, b) => ts(b).localeCompare(ts(a))));
    arr.sort((a, b) => ts(b.convs[0]).localeCompare(ts(a.convs[0])));
    return arr;
  }

  function renderList() {
    const list = $('pt-list');
    if (!_conversations.length) {
      list.innerHTML = '<div class="pt-empty">No conversations yet. Start a new one to begin.</div>';
      return;
    }
    list.innerHTML = groupConversations().map((g) => {
      const av = avatarHtml(g.name, g.avatarPath, g.id, 'pt-av pt-av-sm');
      const cards = g.convs.map((c) => {
        const title = c.title || 'Untitled chat';
        const preview = c.last_item_preview || '';
        return `<button type="button" class="pt-card" data-id="${_escHtml(c.id)}">
          <span class="pt-card-top">
            <span class="pt-card-title">${_escHtml(title)}</span>
            <span class="pt-card-time">${_escHtml(fmtTime(c.updated_at))}</span>
          </span>
          <span class="pt-card-preview">${_escHtml(preview)}</span>
        </button>`;
      }).join('');
      return `<section class="pt-group">
        <header class="pt-group-head">
          ${av}
          <span class="pt-group-name">${_escHtml(g.name)}</span>
          <span class="pt-group-count">${g.convs.length}</span>
        </header>
        <div class="pt-conv-grid">${cards}</div>
      </section>`;
    }).join('');
    list.querySelectorAll('.pt-card').forEach((card) => {
      card.addEventListener('click', () => onCardClick(card));
    });
  }

  function onCardClick(card) {
    const id = card.dataset.id;
    if (!_deleteMode) {
      openConversation(id);
      return;
    }
    if (!card.classList.contains('armed')) {
      card.classList.add('armed');  // first click arms; second click deletes
      return;
    }
    removeConversation(id, card);
  }

  async function removeConversation(id, card) {
    try {
      await api(`${APP}/conversations/${encodeURIComponent(id)}`, 'DELETE');
    } catch (err) {
      card.classList.remove('armed');
      toast('error', `Could not delete: ${err.message}`);
      return;
    }
    _conversations = _conversations.filter((c) => c.id !== id);
    renderList();  // re-group; drops now-empty character groups
    if (!_conversations.length) setDeleteMode(false);
  }

  function setDeleteMode(on) {
    _deleteMode = on;
    $('pt-list').classList.toggle('delete-mode', on);
    const btn = $('pt-delete-mode');
    btn.classList.toggle('active', on);
    btn.textContent = on ? '✓ Done' : '🗑 Delete';
    if (!on) {
      $('pt-list').querySelectorAll('.pt-card.armed')
        .forEach((c) => c.classList.remove('armed'));
    }
  }

  function toggleDeleteMode() {
    setDeleteMode(!_deleteMode);
  }

  // ---------- chat view ----------

  async function loadChat(id) {
    const thread = $('pt-thread');
    thread.setAttribute('aria-busy', 'true');
    thread.innerHTML = '';
    if (!Object.keys(_characters).length) await loadCharacters();
    try {
      _current = await api(`${APP}/conversations/${encodeURIComponent(id)}`);
    } catch (err) {
      thread.innerHTML = `<div class="pt-empty">Could not load conversation: ${_escHtml(err.message)}</div>`;
      thread.setAttribute('aria-busy', 'false');
      return;
    }
    renderChatHead();
    renderThread();
    resetComposer();
    await syncPlugins();  // inject enabled plugins' assets + merge composer modes
    thread.setAttribute('aria-busy', 'false');
  }

  function renderChatHead() {
    const conv = _current.conversation;
    const cp = counterpartOf(conv);
    const name = cp ? cp.name : (conv.title || 'Conversation');
    fillAvatar($('pt-chat-avatar'), name, cp && cp.avatar_path, conv.counterpart_character_id);
    $('pt-chat-name').textContent = name;
    $('pt-chat-sub').textContent = conv.title && conv.title !== name ? conv.title : (conv.scenario || '');
    renderToggles();
  }

  function renderToggles() {
    const cfg = (_current && _current.conversation.config) || {};
    $('pt-voice-toggle').classList.toggle('on', !!cfg.voice_enabled);
    $('pt-timing-toggle').classList.toggle('on', !!cfg.typing_timing_enabled);
    // variety defaults on, so treat a missing flag as enabled
    $('pt-variety-toggle').classList.toggle('on', cfg.variety_pass_enabled !== false);
  }

  // Config flags that default to ON when absent (so the first click turns them off).
  const CONFIG_DEFAULT_ON = { variety_pass_enabled: true };

  async function toggleConfig(key) {
    if (!_current) return;
    const cfg = _current.conversation.config || {};
    const current = cfg[key] === undefined ? !!CONFIG_DEFAULT_ON[key] : !!cfg[key];
    try {
      const updated = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}`,
        'PATCH', { config: { [key]: !current } });
      if (updated) _current.conversation = updated;
      renderToggles();
    } catch (_) { /* leave state as-is on failure */ }
  }

  // ---------- app settings (narrator voice) ----------

  async function openSettings() {
    const sel = $('pt-settings-narrator');
    const msg = $('pt-settings-msg');
    msg.textContent = '';
    sel.innerHTML = '<option value="">Loading…</option>';
    $('pt-settings-dialog').showModal();
    try {
      const [presets, settings] = await Promise.all([
        api('/voice-presets'),
        api(`${APP}/settings`),
      ]);
      const list = Array.isArray(presets) ? presets : (presets.presets || []);
      sel.innerHTML = '<option value="">(none — narration stays text)</option>' +
        list.map((p) => `<option value="${_escHtml(p.id)}">${_escHtml(p.name || p.id)}</option>`).join('');
      sel.value = settings.narrator_voice_preset_id || '';
    } catch (err) {
      sel.innerHTML = '<option value="">(none)</option>';
      msg.textContent = 'Could not load voice presets: ' + err.message;
    }
  }

  async function saveSettings() {
    const btn = $('pt-settings-save');
    const msg = $('pt-settings-msg');
    btn.disabled = true;
    msg.textContent = 'Saving…';
    try {
      await api(`${APP}/settings`, 'PUT',
        { narrator_voice_preset_id: $('pt-settings-narrator').value || null });
      $('pt-settings-dialog').close();
    } catch (err) {
      msg.textContent = 'Save failed: ' + err.message;
    } finally {
      btn.disabled = false;
    }
  }

  // Narration (and the legacy narration_emotion) break the thread into segments:
  // they render full-width and centered between dividers rather than as a side
  // bubble, and consecutive narrations — even across a turn boundary or a switch
  // of author — merge into one segment. "Narration splits up chat segments."
  function isNarrationType(type) {
    return type === 'narration' || type === 'narration_emotion';
  }

  // Walk every item across all turns (in order) into render segments:
  //   {kind:'narration', items:[{turn,item}…]}  — one merged narration run, or
  //   {kind:'turn', turnId, author, items:[…]}   — a run of non-narration items
  //                                                from one turn (avatar + stack).
  // A turn with narration in the middle thus yields several segments.
  function buildSegments(turns) {
    const segs = [];
    let cur = null;
    for (const turn of turns) {
      for (const item of (turn.items || [])) {
        if (isNarrationType(item.type)) {
          if (!cur || cur.kind !== 'narration') { cur = { kind: 'narration', items: [] }; segs.push(cur); }
          cur.items.push({ turn, item });
        } else {
          if (!cur || cur.kind !== 'turn' || cur.turnId !== turn.id) {
            cur = { kind: 'turn', turnId: turn.id, author: turn.author, items: [] };
            segs.push(cur);
          }
          cur.items.push(item);
        }
      }
    }
    return segs;
  }

  function renderThread() {
    const thread = $('pt-thread');
    const turns = (_current.transcript && _current.transcript.turns) || [];
    if (!turns.length) {
      thread.innerHTML = '<div class="pt-empty pt-thread-empty">Say something to get started.</div>';
      firePluginRender();
      return;
    }
    thread.innerHTML = buildSegments(turns)
      .map((seg) => (seg.kind === 'narration' ? narrationSegmentHtml(seg) : turnSegmentHtml(seg)))
      .join('');
    wireRetry();
    wirePlay();
    wireThreadControls();
    scrollToBottom();
    firePluginRender();
  }

  // One avatar + bubble-stack group for a run of non-narration items from a turn.
  function turnSegmentHtml(seg) {
    const conv = _current.conversation;
    const turn = { id: seg.turnId, author: seg.author, items: seg.items };
    // A system turn (e.g. a Summarizer recap) is avatar-less and centered.
    if (seg.author === 'system') {
      const sysBubbles = seg.items.map((it) => bubbleHtml(it, turn)).join('');
      return `<div class="pt-turn pt-turn--system" data-turn="${_escHtml(seg.turnId)}">
        <div class="pt-stack pt-stack--system">${sysBubbles}</div>
      </div>`;
    }
    const isUser = seg.author === 'user';
    const cp = counterpartOf(conv);
    const name = isUser ? (conv.device_user && conv.device_user.display_name) || 'You'
                        : (cp ? cp.name : 'Character');
    const avPath = isUser ? (conv.device_user && conv.device_user.avatar_path)
                          : (cp && cp.avatar_path);
    const avId = isUser ? 'device-user' : conv.counterpart_character_id;
    const av = avatarHtml(name, avPath, avId, 'pt-av pt-av-sm');
    const bubbles = seg.items.map((it) => bubbleHtml(it, turn)).join('');
    return `<div class="pt-turn pt-turn--${isUser ? 'user' : 'model'}" data-turn="${_escHtml(seg.turnId)}">
      ${isUser ? '' : av}
      <div class="pt-stack">${bubbles}</div>
      ${isUser ? av : ''}
    </div>`;
  }

  // A full-width centered narration block bracketed by two horizontal dividers.
  // Each line is still a bubbleHtml item (data-turn/data-item) so the per-item
  // controls, play button and SFX badge keep working; CSS restyles it centered.
  function narrationSegmentHtml(seg) {
    const lines = seg.items.map(({ turn, item }) => bubbleHtml(item, turn)).join('');
    return `<div class="pt-narration-seg">
      <hr class="pt-narration-rule">
      <div class="pt-narration-body">${lines}</div>
      <hr class="pt-narration-rule">
    </div>`;
  }

  // The visible text for a bubble: strip the canonical decoration so both sides
  // read the same (colour/shape carries the type). dialogue -> drop the wrapping
  // double quotes; action -> drop the wrapping asterisks; narration is plain.
  function displayText(item) {
    const t = item.text || '';
    if (item.type === 'dialogue') {
      const m = t.match(/^"([\s\S]*)"$/);
      if (m) return m[1];
    } else if (item.type === 'action') {
      const m = t.match(/^\*([\s\S]*)\*$/);
      if (m) return m[1];
    }
    return t;
  }

  function bubbleHtml(item, turn) {
    const type = item.type || 'dialogue';
    // A plugin can own a bubble type (e.g. Summarizer's `summary` card). Fall
    // back to the core renderer if the plugin renderer throws or is absent.
    if (window.PtPlugins) {
      const r = PtPlugins.bubbleRenderer(type);
      if (r && r.render) {
        try { return r.render(item, turn); } catch (_) { /* fall through */ }
      }
    }
    if (type === 'system_error') {
      return `<div class="pt-bubble pt-bubble--error" data-turn="${_escHtml(turn.id)}">
        <span class="pt-err-text">${_escHtml(item.text || 'Generation failed.')}</span>
        <button type="button" class="pt-retry" data-turn="${_escHtml(turn.id)}">↻ Retry</button>
      </div>`;
    }
    const url = mediaUrl(item);
    const hasSfx = !!(item.sfx && item.sfx.status === 'resolved');
    // Show a play button when audio exists OR the item is voiceable (clip is
    // synthesized lazily on click) OR a resolved SFX after-cue is attached.
    let play = '';
    if (url || isVoiceable(item, turn) || hasSfx) {
      const urlAttr = url ? ` data-url="${_escHtml(url)}"` : '';
      play = `<button type="button" class="pt-play" data-turn="${_escHtml(turn.id)}"` +
        ` data-item="${_escHtml(item.id)}"${urlAttr} title="Play audio" aria-label="Play audio">🔊</button>`;
    }
    // Subtle indicator that an emote sound effect will play after the item audio.
    const sfxBadge = hasSfx ? '<span class="pt-sfx-badge" title="Sound effect attached">♪</span>' : '';
    // Hidden-from-context items still render (history) but styled as excluded,
    // with a clear "won't be sent to the model" tag (SP5).
    const hidden = item.hidden_from_context;
    const cls = `pt-bubble pt-bubble--${_escHtml(type)}${hidden ? ' pt-bubble--hidden' : ''}`;
    const tag = hidden ? '<span class="pt-hidden-tag" title="Hidden from context">🚫 hidden</span>' : '';
    return `<div class="${cls}" data-turn="${_escHtml(turn.id)}" data-item="${_escHtml(item.id)}">` +
      `${_escHtml(displayText(item))}${play}${sfxBadge}${tag}</div>`;
  }

  function scrollToBottom() {
    const thread = $('pt-thread');
    thread.scrollTop = thread.scrollHeight;
  }

  // ---------- audio + reveal cadence ----------

  // Server URL for a generated wav path ("media/<file>").
  function mediaUrlFromPath(path) {
    const file = String(path).split('/').pop();
    return `/v1/apps/prattletale/conversations/${encodeURIComponent(_current.conversation.id)}/media/${encodeURIComponent(file)}`;
  }
  function mediaUrl(item) {
    return (item && item.audio && item.audio.path) ? mediaUrlFromPath(item.audio.path) : null;
  }

  function convVoiceOn() {
    return !!(_current && _current.conversation.config && _current.conversation.config.voice_enabled);
  }
  // Items the server might voice: every non-error model item (dialogue in the
  // character's voice, everything else via the narrator). Audio is produced
  // lazily, so this decides whether to show a play button before a clip exists.
  // system_error + user items are never spoken.
  function isVoiceable(item, turn) {
    return convVoiceOn() && turn && turn.author === 'model'
      && item.type !== 'system_error';
  }

  // POST the per-item synth endpoint; returns the audio descriptor or null. The
  // endpoint is idempotent (reuses an existing wav), so re-calling is cheap.
  async function fetchItemAudio(turnId, itemId) {
    try {
      const res = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}/items/${encodeURIComponent(itemId)}/audio`, 'POST');
      return (res && res.audio) || null;
    } catch (_) { return null; }
  }

  // Resolve an item's audio, caching on the item so it's synthesized at most once.
  // The in-flight promise is shared (`__audioPromise`) so the background producer
  // and the reveal loop asking for the same clip don't both fire a synth. null
  // when not spoken / failed.
  function ensureAudio(turnId, item) {
    if (item.audio && item.audio.path) return Promise.resolve(item.audio);
    if (item.__noAudio || !convVoiceOn()) return Promise.resolve(null);
    if (!item.__audioPromise) {
      item.__audioPromise = fetchItemAudio(turnId, item.id).then((audio) => {
        if (audio && audio.path) { item.audio = audio; return audio; }
        item.__noAudio = true;
        return null;
      });
    }
    return item.__audioPromise;
  }

  let _activeAudio = null;
  // Play a clip; resolves when it ends/errors so the reveal cadence can await it.
  function playAudioUrl(url) {
    return new Promise((resolve) => {
      try {
        if (_activeAudio) { _activeAudio.pause(); _activeAudio = null; }
        const a = new Audio(url);
        _activeAudio = a;
        const done = () => { if (_activeAudio === a) _activeAudio = null; resolve(); };
        a.addEventListener('ended', done);
        a.addEventListener('error', done);
        const p = a.play();
        if (p && p.catch) p.catch(done);
      } catch (_) { resolve(); }
    });
  }

  // ---------- SFX after-cues (sfx plugin) ----------

  // Find a live turn / item object by ids (so playback reflects late-resolved SFX).
  function findTurn(turnId) {
    const turns = (_current && _current.transcript && _current.transcript.turns) || [];
    return turns.find((t) => t.id === turnId) || null;
  }
  function findItem(turnId, itemId) {
    const turn = findTurn(turnId);
    return turn ? (turn.items || []).find((it) => it.id === itemId) || null : null;
  }

  // Served URL for a resolved SFX clip (path segments encoded; spaces are common).
  function sfxUrl(item) {
    const s = item && item.sfx;
    if (!s || s.status !== 'resolved' || !s.path) return null;
    return '/v1/sfx/file/' + String(s.path).split('/').map(encodeURIComponent).join('/');
  }

  // Play an item's normal audio then its SFX after-cue (the canonical order used
  // by both live reveal and speaker-button replay). Either part may be absent.
  async function playItemAudioSequence(item, audioUrl) {
    if (audioUrl) await playAudioUrl(audioUrl);
    const url = sfxUrl(item);
    if (url) await playAudioUrl(url);
  }

  function wirePlay() {
    $('pt-thread').querySelectorAll('.pt-play').forEach((btn) => {
      if (btn.dataset.wired) return;
      btn.dataset.wired = '1';
      btn.addEventListener('click', async () => {
        let url = btn.dataset.url;
        const item = findItem(btn.dataset.turn, btn.dataset.item);
        const turn = findTurn(btn.dataset.turn);
        if (!url && item && isVoiceable(item, turn)) {
          // lazily synthesize this clip on first play
          btn.disabled = true;
          const audio = await fetchItemAudio(btn.dataset.turn, btn.dataset.item);
          btn.disabled = false;
          if (audio && audio.path) { url = mediaUrlFromPath(audio.path); btn.dataset.url = url; }
        }
        // Replay: normal audio (if any) then the SFX after-cue.
        playItemAudioSequence(item, url || null);
      });
    });
  }

  // Fire each enabled plugin's onModelTurn hook for a freshly committed turn so it
  // can resolve side content (SFX) ASAP. Best-effort and non-blocking.
  function firePluginTurn(turn) {
    if (!turn || !window.PtPlugins) return;
    PtPlugins.turnHooks(enabledPluginIds()).forEach(({ pluginId, fn }) => {
      try {
        const r = fn(turn, pluginCtx(pluginId));
        if (r && r.catch) r.catch(() => {});
      } catch (_) { /* a plugin hook must never break turn rendering */ }
    });
  }

  // Fire each enabled plugin's onRender hook after a thread render so it can keep
  // header chrome in sync with the transcript (e.g. Command's active-commands
  // button). Best-effort — a hook must never break rendering.
  function firePluginRender() {
    if (!window.PtPlugins) return;
    PtPlugins.renderHooks(enabledPluginIds()).forEach(({ pluginId, fn }) => {
      try {
        const r = fn(pluginCtx(pluginId));
        if (r && r.catch) r.catch(() => {});
      } catch (_) { /* ignore */ }
    });
  }

  // Apply a resolved SFX descriptor to a live item + its rendered bubble: cache it
  // on the item (so reveal/replay see it) and surface a play button + subtle badge.
  function applyItemSfx(turnId, itemId, sfx) {
    const item = findItem(turnId, itemId);
    if (item) item.sfx = sfx;
    if (!sfx || sfx.status !== 'resolved') return;
    const bubble = $('pt-thread').querySelector(
      `.pt-bubble[data-turn="${turnId}"][data-item="${itemId}"]`);
    if (!bubble) return;
    if (!bubble.querySelector('.pt-sfx-badge')) {
      bubble.insertAdjacentHTML('beforeend',
        '<span class="pt-sfx-badge" title="Sound effect attached">♪</span>');
    }
    if (!bubble.querySelector('.pt-play')) {
      bubble.insertAdjacentHTML('beforeend',
        `<button type="button" class="pt-play" data-turn="${turnId}" data-item="${itemId}"` +
        ' title="Play audio" aria-label="Play audio">🔊</button>');
      wirePlay();
    }
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Per-item typing duration from text length (+ jitter); mirrors voice.py.
  function typingMs(item) {
    const n = (item.text || '').trim().length;
    return Math.max(600, Math.min(4500, n * 28)) + Math.floor(Math.random() * 350);
  }

  // Animate a left->right progress bar across a just-revealed bubble for `ms`,
  // then resolve. This is the visible dwell before the next message appears
  // (matched to the audio clip length when there's audio). Resolves early if the
  // user navigates away.
  function runProgress(bubbleEl, ms, stillHere) {
    return new Promise((resolve) => {
      const bar = document.createElement('div');
      bar.className = 'pt-progress';
      const fill = document.createElement('div');
      fill.className = 'pt-progress-fill';
      bar.appendChild(fill);
      bubbleEl.appendChild(bar);
      // two frames: let the 0%-width fill paint, then transition it to 100%.
      requestAnimationFrame(() => {
        fill.style.transition = `width ${ms}ms linear`;
        requestAnimationFrame(() => { fill.style.width = '100%'; });
      });
      setTimeout(() => {
        bar.remove();
        resolve();
      }, ms);
    });
  }

  // Minimum time the typing indicator stays up so a fast/cached synth still reads
  // as "she's composing" rather than flashing.
  const _MIN_TYPING_MS = 400;

  // Reveal a fresh model turn message-by-message (timing on, non-error turn). For
  // each message: show the "..." typing indicator, and *while it shows* generate
  // that message's audio (or, with no voice, wait a typing beat); then swap the
  // dots for the bubble and play the clip with a left->right progress bar across
  // the read-aloud duration. Strictly sequential — the next "..." doesn't start
  // until the current message finishes. Otherwise render it all at once. Bails if
  // the user navigates away.
  async function revealModelTurn(turn) {
    const conv = _current.conversation;
    const timing = conv.config && conv.config.typing_timing_enabled;
    const isErr = (turn.items || []).some((i) => i.type === 'system_error');
    // Caller renders non-animated turns via renderThread(); nothing to do here.
    if (!timing || isErr) return;

    const convId = conv.id;
    const thread = $('pt-thread');
    const empty = thread.querySelector('.pt-thread-empty');
    if (empty) empty.remove();
    const cp = counterpartOf(conv);
    const av = avatarHtml(cp ? cp.name : 'Character', cp && cp.avatar_path, conv.counterpart_character_id, 'pt-av pt-av-sm');
    const el = document.createElement('div');
    el.className = 'pt-turn pt-turn--model';
    el.dataset.turn = turn.id;
    el.innerHTML = `${av}<div class="pt-stack"></div>`;
    thread.appendChild(el);
    const stack = el.querySelector('.pt-stack');

    const stillHere = () => _current && _current.conversation.id === convId;
    const items = turn.items || [];

    // Background producer: synthesize clips in order, one at a time, so an
    // upcoming message is usually ready by the time we reveal it (its "..." then
    // just covers the playback gap, not a full synth). Sequential `await` keeps
    // it to a single synth at once; ensureAudio dedupes with the loop below, so
    // each clip is synthesized exactly once whoever asks first.
    (async () => {
      for (const it of items) {
        if (!stillHere()) return;
        if (isVoiceable(it, turn)) {
          try { await ensureAudio(turn.id, it); } catch (_) { /* best-effort */ }
        }
      }
    })();

    for (const item of items) {
      if (!stillHere()) return;

      // 1) "..." typing indicator
      const dots = document.createElement('div');
      dots.className = 'pt-bubble pt-bubble--dialogue pt-typing';
      dots.innerHTML = '<span></span><span></span><span></span>';
      stack.appendChild(dots);
      scrollToBottom();

      // 2) generate this message's audio while the dots show (voiceable items),
      //    else just hold the dots for a typing beat (no-voice / action items)
      let audio = null;
      if (isVoiceable(item, turn)) {
        const t0 = Date.now();
        audio = await ensureAudio(turn.id, item);
        const elapsed = Date.now() - t0;
        if (elapsed < _MIN_TYPING_MS) await sleep(_MIN_TYPING_MS - elapsed);
      } else {
        await sleep(typingMs(item));
      }
      if (!stillHere()) { dots.remove(); return; }

      // 3) swap dots -> message, then play the clip with the reveal progress bar
      dots.remove();
      stack.insertAdjacentHTML('beforeend', bubbleHtml(item, turn));
      wirePlay();
      const bubbleEl = stack.lastElementChild;
      scrollToBottom();

      let url = null;
      if (audio && audio.path) {
        url = mediaUrlFromPath(audio.path);
        const btn = bubbleEl.querySelector('.pt-play');
        if (btn) btn.dataset.url = url;
      }
      const dwell = (audio && audio.duration_ms) || typingMs(item);
      const audioDone = url ? playAudioUrl(url) : null;
      await runProgress(bubbleEl, dwell, stillHere);
      if (audioDone) await audioDone;  // don't cut a clip off if it ran long
      if (!stillHere()) return;
      // Play the SFX after-cue if it has resolved by now (else it's replay-only).
      if (sfxUrl(item)) { await playAudioUrl(sfxUrl(item)); if (!stillHere()) return; }
    }
    wireThreadControls();  // attach edit/hide/delete + trace once fully revealed
  }

  // ---------- composer ----------

  const PLACEHOLDERS = {
    dialogue: 'Say something…',
    action: 'Describe an action…',
    narration: 'Narrate the scene…',
  };

  function modeLabel(type) {
    return (MODES.find((m) => m.type === type) || {}).label || type;
  }

  // The mode currently driving the composer, resolved from the two axes: in Essentials
  // it's the chosen Say/Do/Narrate; in a plugin section it's that plugin's composer mode.
  function activeMode() {
    if (_sectionIdx === 0) return BASE_MODES[_textModeIdx] || BASE_MODES[0];
    return MODES[BASE_MODES.length + (_sectionIdx - 1)] || BASE_MODES[0];
  }

  // Number of mode-bar sections: Essentials + one per plugin-contributed mode.
  function sectionCount() {
    return 1 + (MODES.length - BASE_MODES.length);
  }

  // A plugin mode's bar label: its `label` with any leading emoji/symbol run stripped
  // ("📋 Summarize" -> "Summarize"); the bar uppercases via CSS.
  function sectionBarLabel(mode) {
    return mode.label.replace(/^[^\p{L}\p{N}]+/u, '').trim() || mode.label;
  }

  function resetComposer() {
    _draft = [];
    _sectionIdx = 0;
    _textModeIdx = 0;
    _editing = -1;
    _savedTextInput = '';
    // Force the plugin panel closed (a stale one from a previous chat shouldn't leak).
    _panelMode = null;
    $('pt-composer').classList.remove('pt-panel-open');
    $('pt-plugin-panel').innerHTML = '';
    $('pt-input').value = '';
    autoGrow();
    renderMode();
    renderDraft();
  }

  function renderMode() {
    const mode = activeMode();
    const input = $('pt-input');
    const isPlugin = _sectionIdx !== 0;
    const panel = isPlugin && window.PtPlugins ? PtPlugins.panel(mode.type) : null;
    $('pt-mode').textContent = mode.label;

    const wasPanel = _panelMode !== null;
    if (panel && _panelMode !== mode.type) {
      // Entering a plugin mode: stash the in-progress bubble text and reuse the
      // composer input as the mode's free-text field (the panel slides up above
      // holding just its options). The staged draft is left untouched.
      if (!wasPanel) _savedTextInput = input.value;
      input.value = '';
      input.placeholder = panel.placeholder || 'Add focus… (optional)';
      openPluginPanel(mode.type, panel);
    } else if (!panel && wasPanel) {
      // Leaving a plugin mode back to text: restore the stashed in-progress text.
      closePluginPanel();
      input.value = _savedTextInput;
      input.placeholder = PLACEHOLDERS[mode.type] || 'Message…';
    } else if (!panel) {
      // Staying in a text mode (no plugin panel).
      input.placeholder = PLACEHOLDERS[mode.type] || 'Message…';
    }
    // (staying in the same panel mode: leave the input + panel as-is so a typed
    // focus and the option selections persist.)
    renderModeBar();
    autoGrow();
    updateSendBtn();
  }

  // Render the mode bar above the compose row: Essentials + one entry per plugin
  // section. Hidden entirely when no plugins are enabled (no lone "Essentials").
  function renderModeBar() {
    const bar = $('pt-modebar');
    const pluginModes = MODES.slice(BASE_MODES.length);
    if (!pluginModes.length) { bar.hidden = true; bar.innerHTML = ''; return; }
    bar.hidden = false;
    const labels = ['Essentials'].concat(pluginModes.map(sectionBarLabel));
    bar.innerHTML = labels.map((label, i) =>
      `<button type="button" class="pt-modebar-item${i === _sectionIdx ? ' pt-modebar-item--active' : ''}"`
      + ` tabindex="-1" data-idx="${i}">${_escHtml(label)}</button>`
    ).join('');
  }

  // Cycle Say/Do/Narrate within Essentials. `step` is +1 (next) or -1 (prev).
  function cycleTextMode(step) {
    const n = BASE_MODES.length;
    _textModeIdx = (_textModeIdx + (step || 1) + n) % n;
    renderMode();
  }

  // Move between mode-bar sections (Essentials <-> plugins). `step` wraps both ways.
  function cycleSection(step) {
    const n = sectionCount();
    _sectionIdx = (_sectionIdx + (step || 1) + n) % n;
    renderMode();
  }

  // Jump directly to a bar section (click handler), keeping the caret in the composer.
  function selectSection(i) {
    if (i < 0 || i >= sectionCount()) return;
    _sectionIdx = i;
    renderMode();
    $('pt-input').focus();
  }

  // ---------- plugin composer panel ----------

  let _panelMode = null;  // the mode type whose panel is open, or null

  function openPluginPanel(modeType, panel) {
    if (_panelMode === modeType) return;  // already open for this mode
    _panelMode = modeType;
    const box = $('pt-plugin-panel');
    box.innerHTML = '';
    // The composer's .pt-panel-open class drives the slide-up (CSS); the panel is
    // collapsed by max-height when closed, so it animates instead of snapping.
    $('pt-composer').classList.add('pt-panel-open');
    try {
      panel.render(box, pluginCtx(panel.pluginId));
    } catch (_) {
      box.innerHTML = '<div class="pt-empty">Plugin panel failed to load.</div>';
    }
  }

  // Run the active plugin mode's action (the Go button / Enter). Independent of
  // the staged draft — the pending bubbles survive a Go untouched. The plugin
  // reads its own options from ctx.panelEl and the focus from ctx.primaryValue().
  async function runPluginGo() {
    const panel = window.PtPlugins && PtPlugins.panel(activeMode().type);
    if (!panel || !panel.submit || _sending) return;
    _sending = true;
    setComposerEnabled(false);
    try {
      await panel.submit(pluginCtx(panel.pluginId));
    } catch (_) {
      /* the plugin surfaces its own error inline in the panel */
    } finally {
      _sending = false;
      setComposerEnabled(true);
    }
  }

  function closePluginPanel() {
    if (_panelMode === null) return;
    _panelMode = null;
    // Leave the content in place (collapsed by CSS, replaced on next open) so the
    // slide-down animates rather than emptying instantly.
    $('pt-composer').classList.remove('pt-panel-open');
  }

  // The context handed to a plugin's render/submit: the conversation, the raw api(),
  // a bound action-invoker, result helpers, and a close() that returns to Say.
  function pluginCtx(pluginId) {
    const convId = _current.conversation.id;
    return {
      conversation: _current.conversation,
      transcript: _current.transcript,
      api,
      invokeAction: (action, params) => api(
        `${APP}/conversations/${encodeURIComponent(convId)}` +
        `/plugins/${encodeURIComponent(pluginId)}/actions/${encodeURIComponent(action)}`,
        'POST', params || {}),
      onResult: (res) => applyPluginResult(res),
      appendTurn: (turn) => { _current.transcript.turns.push(turn); appendTurn(turn); scrollToBottom(); },
      markHidden: (ids) => markItemsHidden(ids),
      applySfx: (turnId, itemId, sfx) => applyItemSfx(turnId, itemId, sfx),
      // Resolve side content (e.g. SFX) for a turn produced outside the normal
      // send path, so plugin-generated model turns reach the turn hooks too.
      fireTurn: (turn) => firePluginTurn(turn),
      // Re-fetch the conversation + transcript and re-render — used after a plugin
      // edits/deletes transcript items via the core REST endpoints.
      reload: () => loadChat(convId),
      close: () => { _sectionIdx = 0; renderMode(); },
      panelEl: $('pt-plugin-panel'),
      primaryValue: () => $('pt-input').value.trim(),
    };
  }

  // Default handling of a plugin result: append a returned turn, and on a purge
  // mark the covered originals hidden in place.
  function applyPluginResult(res) {
    if (!res) return;
    if (res.summary_turn) {
      _current.transcript.turns.push(res.summary_turn);
      appendTurn(res.summary_turn);
      scrollToBottom();
    }
    if (res.mode === 'purge' && Array.isArray(res.hidden_item_ids)) {
      markItemsHidden(res.hidden_item_ids);
    }
  }

  function markItemsHidden(itemIds) {
    const set = new Set(itemIds || []);
    const affected = new Set();
    ((_current.transcript && _current.transcript.turns) || []).forEach((t) => {
      (t.items || []).forEach((it) => {
        if (set.has(it.id)) { it.hidden_from_context = true; affected.add(t.id); }
      });
    });
    affected.forEach((tid) => rerenderTurn(tid));
  }

  // The primary button doubles as Stack / Send: with text it stacks the bubble,
  // on an empty box it commits the chain. Disabled only when there's nothing to do.
  function updateSendBtn() {
    const btn = $('pt-send');
    if (_panelMode) {
      // In a plugin mode the button runs the action; its free-text is optional.
      const panel = window.PtPlugins && PtPlugins.panel(activeMode().type);
      btn.textContent = (panel && panel.goLabel) || 'Go';
      btn.disabled = _sending;
      return;
    }
    const hasText = $('pt-input').value.trim().length > 0;
    btn.textContent = hasText ? 'Stack' : 'Send';
    btn.disabled = _sending || (!hasText && _draft.length === 0);
  }

  function renderDraft() {
    const box = $('pt-draft');
    if (!_draft.length) {
      box.hidden = true;
      box.innerHTML = '';
      updateSendBtn();
      return;
    }
    box.hidden = false;
    box.innerHTML = _draft.map((d, i) =>
      i === _editing ? draftEditorHtml(d, i) : draftRowHtml(d, i)).join('');
    wireDraft();
    updateSendBtn();
  }

  function draftRowHtml(d, i) {
    return `<div class="pt-staged-row" data-i="${i}">
      <span class="pt-staged-tag pt-bubble--${_escHtml(d.type)}">${_escHtml(modeLabel(d.type))}</span>
      <span class="pt-staged-text">${_escHtml(d.text)}</span>
      <button type="button" class="pt-staged-btn pt-staged-edit" data-i="${i}" title="Edit" aria-label="Edit">✏</button>
      <button type="button" class="pt-staged-btn pt-staged-del" data-i="${i}" title="Delete" aria-label="Delete">🗑</button>
    </div>`;
  }

  function draftEditorHtml(d, i) {
    return `<div class="pt-staged-row pt-staged-editing" data-i="${i}">
      <button type="button" class="pt-staged-mode pt-bubble--${_escHtml(d.type)}" data-i="${i}"
        title="Change type">${_escHtml(modeLabel(d.type))}</button>
      <textarea class="pt-staged-input" data-i="${i}" rows="1">${_escHtml(d.text)}</textarea>
      <button type="button" class="pt-staged-btn pt-staged-save" data-i="${i}" title="Save" aria-label="Save">✓</button>
      <button type="button" class="pt-staged-btn pt-staged-cancel" data-i="${i}" title="Cancel" aria-label="Cancel">✗</button>
    </div>`;
  }

  function wireDraft() {
    const box = $('pt-draft');
    box.querySelectorAll('.pt-staged-del').forEach((b) =>
      b.addEventListener('click', () => removeStaged(Number(b.dataset.i))));
    box.querySelectorAll('.pt-staged-edit').forEach((b) =>
      b.addEventListener('click', () => { _editing = Number(b.dataset.i); renderDraft(); focusEditor(); }));
    box.querySelectorAll('.pt-staged-cancel').forEach((b) =>
      b.addEventListener('click', () => { _editing = -1; renderDraft(); $('pt-input').focus(); }));
    box.querySelectorAll('.pt-staged-mode').forEach((b) =>
      b.addEventListener('click', () => {
        const i = Number(b.dataset.i);
        const ta = box.querySelector(`.pt-staged-input[data-i="${i}"]`);
        if (ta) _draft[i].text = ta.value;            // keep in-progress edits across a type change
        // Staged text bubbles cycle only the built-in text modes (never a plugin mode).
        const cur = BASE_MODES.findIndex((m) => m.type === _draft[i].type);
        _draft[i].type = BASE_MODES[(cur + 1) % BASE_MODES.length].type;
        renderDraft();
        focusEditor();
      }));
    box.querySelectorAll('.pt-staged-save').forEach((b) =>
      b.addEventListener('click', () => saveEditor(Number(b.dataset.i))));
    box.querySelectorAll('.pt-staged-input').forEach((ta) => {
      ta.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEditor(Number(ta.dataset.i)); }
        else if (e.key === 'Escape') { e.preventDefault(); _editing = -1; renderDraft(); $('pt-input').focus(); }
      });
    });
  }

  function focusEditor() {
    const ta = $('pt-draft').querySelector('.pt-staged-input');
    if (ta) { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }
  }

  function saveEditor(i) {
    const ta = $('pt-draft').querySelector(`.pt-staged-input[data-i="${i}"]`);
    if (ta) {
      const text = ta.value.trim();
      if (!text) { removeStaged(i); return; }   // empty edit drops the bubble
      _draft[i].text = text;
    }
    _editing = -1;
    renderDraft();
    $('pt-input').focus();
  }

  function removeStaged(i) {
    _draft.splice(i, 1);
    if (_editing === i) _editing = -1;
    else if (_editing > i) _editing -= 1;
    renderDraft();
  }

  // Wrap a composed bubble in the canonical message format by type: dialogue ->
  // "spoken words", action -> *action text*, narration (and anything else) plain.
  // Idempotent — already-wrapped text is left as-is so we never double-wrap.
  function canonicalText(type, raw) {
    const text = (raw || '').trim();
    if (!text) return text;
    if (type === 'dialogue') {
      return (text.length >= 2 && text[0] === '"' && text[text.length - 1] === '"')
        ? text : `"${text}"`;
    }
    if (type === 'action') {
      return (text.length >= 2 && text[0] === '*' && text[text.length - 1] === '*')
        ? text : `*${text}*`;
    }
    return text;
  }

  // stack the active input as a new bubble; returns true if anything was staged
  function stackItem() {
    if (_panelMode) return false;  // a plugin mode owns the composer — no text bubbles
    const inp = $('pt-input');
    const text = inp.value.trim();
    if (!text) return false;
    _draft.push({ type: activeMode().type, text });
    inp.value = '';
    autoGrow();
    renderDraft();
    inp.focus();
    return true;
  }

  // Enter / Send dispatch. In a plugin mode the button is "Go" and runs the
  // plugin's action (the staged draft is untouched). Otherwise: text present ->
  // stack a bubble; empty box -> commit the chain.
  function submitOrStack() {
    if (_panelMode) { runPluginGo(); return; }
    if ($('pt-input').value.trim()) stackItem();
    else send();
  }

  async function send() {
    if (_sending) return;
    // Commit the staged draft in canonical message format (the backend also
    // normalizes, but wrapping here keeps the optimistic echo identical).
    const items = _draft.map((d) => ({ type: d.type, text: canonicalText(d.type, d.text) }));
    if (!items.length) return;

    _sending = true;
    setComposerEnabled(false);

    // clear the composer and show the user's message right away — the POST runs
    // the model turn synchronously and can take a while, so the user shouldn't
    // wait on the network to see what they just sent. We stage an optimistic
    // user turn into the transcript so renderThread() lays out its segments
    // (incl. narration) exactly as the committed turn will.
    _draft = [];
    _editing = -1;
    renderDraft();

    const id = _current.conversation.id;
    const turns = _current.transcript.turns;
    const optimistic = { id: '__pending__', author: 'user',
      items: items.map((d, i) => ({ ...d, id: `__p${i}` })) };
    turns.push(optimistic);
    renderThread();
    const typingEl = showTyping();
    try {
      const res = await api(
        `${APP}/conversations/${encodeURIComponent(id)}/turns`, 'POST', { items });
      typingEl.remove();
      // Replace the optimistic user turn with the persisted one (real ids).
      const pi = turns.findIndex((t) => t.id === '__pending__');
      if (pi >= 0) turns.splice(pi, 1, res.user_turn); else turns.push(res.user_turn);
      renderThread();

      // Reveal the model turn message-by-message when timing is on, then add it
      // to the transcript and re-render so its narration merges into segments.
      const isErr = (res.model_turn.items || []).some((i) => i.type === 'system_error');
      const timing = _current.conversation.config && _current.conversation.config.typing_timing_enabled;
      if (timing && !isErr) await revealModelTurn(res.model_turn);
      turns.push(res.model_turn);
      renderThread();

      // Kick off SFX resolution for both turns (plugins, best-effort).
      firePluginTurn(res.user_turn);
      firePluginTurn(res.model_turn);
    } catch (err) {
      // hard failure (network / 5xx): undo the optimistic turn and restore the
      // draft so the user can resend. (Model-side failures come back as a 200
      // system_error turn and flow through the success path instead.)
      typingEl.remove();
      const pi = turns.findIndex((t) => t.id === '__pending__');
      if (pi >= 0) turns.splice(pi, 1);
      renderThread();
      _draft = items;
      renderDraft();
      const thread = $('pt-thread');
      const div = document.createElement('div');
      div.className = 'pt-empty pt-send-error';
      div.textContent = 'Send failed: ' + err.message;
      thread.appendChild(div);
      scrollToBottom();
    } finally {
      _sending = false;
      setComposerEnabled(true);
      $('pt-input').focus();
    }
  }

  // The turn is already in _current.transcript; re-render the whole thread so
  // narration segments merge correctly across turn boundaries.
  function appendTurn() {
    renderThread();
  }

  function showTyping() {
    const thread = $('pt-thread');
    const cp = counterpartOf(_current.conversation);
    const name = cp ? cp.name : 'Character';
    const av = avatarHtml(name, cp && cp.avatar_path, _current.conversation.counterpart_character_id, 'pt-av pt-av-sm');
    const el = document.createElement('div');
    el.className = 'pt-turn pt-turn--model pt-typing-turn';
    el.innerHTML = `${av}<div class="pt-stack"><div class="pt-bubble pt-bubble--dialogue pt-typing">
      <span></span><span></span><span></span></div></div>`;
    thread.appendChild(el);
    scrollToBottom();
    return el;
  }

  function setComposerEnabled(on) {
    ['pt-input', 'pt-send', 'pt-mode'].forEach((id) => { $(id).disabled = !on; });
    if (on) updateSendBtn();
  }

  // ---------- retry ----------

  function wireRetry() {
    $('pt-thread').querySelectorAll('.pt-retry').forEach((btn) => {
      if (btn.dataset.wired) return;
      btn.dataset.wired = '1';
      btn.addEventListener('click', () => retryTurn(btn.dataset.turn));
    });
  }

  async function retryTurn(turnId) {
    if (_sending) return;
    _sending = true;
    setComposerEnabled(false);
    const id = _current.conversation.id;
    // swap the error bubble's stack for a typing indicator in place
    const errBubble = $('pt-thread').querySelector(`.pt-bubble--error[data-turn="${CSS.escape(turnId)}"]`);
    const turnEl = errBubble ? errBubble.closest('.pt-turn') : null;
    let stack = turnEl ? turnEl.querySelector('.pt-stack') : null;
    if (stack) {
      stack.innerHTML = `<div class="pt-bubble pt-bubble--dialogue pt-typing">
        <span></span><span></span><span></span></div>`;
    }
    try {
      const newTurn = await api(
        `${APP}/conversations/${encodeURIComponent(id)}/turns/${encodeURIComponent(turnId)}/retry`,
        'POST');
      // replace in place in both the DOM and the in-memory transcript
      const turns = _current.transcript.turns;
      const idx = turns.findIndex((t) => t.id === turnId);
      if (idx >= 0) turns[idx] = newTurn;
      renderThread();
    } catch (err) {
      if (stack) {
        stack.innerHTML = `<div class="pt-bubble pt-bubble--error" data-turn="${_escHtml(turnId)}">
          <span class="pt-err-text">Retry failed: ${_escHtml(err.message)}</span>
          <button type="button" class="pt-retry" data-turn="${_escHtml(turnId)}">↻ Retry</button>
        </div>`;
        wireRetry();
      }
    } finally {
      _sending = false;
      setComposerEnabled(true);
    }
  }

  // ---------- delete ----------

  async function deleteConversation() {
    if (!_current) return;
    const conv = _current.conversation;
    const cp = counterpartOf(conv);
    const name = cp ? cp.name : (conv.title || 'this conversation');
    if (!confirm(`Delete the conversation with ${name}? This cannot be undone.`)) return;
    await api(`${APP}/conversations/${encodeURIComponent(conv.id)}`, 'DELETE');
    goList();
  }

  // ---------- conversation config view (SP4) ----------

  function openConfig() {
    if (!_current) return;
    const conv = _current.conversation;
    const cfg = conv.config || {};
    const du = conv.device_user || {};
    $('pt-config-title').value = conv.title || '';
    $('pt-config-scenario').value = conv.scenario || '';
    $('pt-config-role').value = conv.role_instructions || '';
    $('pt-config-username').value = du.display_name || 'You';
    $('pt-config-persona').value = du.persona || '';
    $('pt-config-window').value = cfg.context_window_turns != null ? cfg.context_window_turns : 12;
    $('pt-config-voice').checked = !!cfg.voice_enabled;
    $('pt-config-timing').checked = !!cfg.typing_timing_enabled;
    $('pt-config-variety').checked = cfg.variety_pass_enabled !== false;
    $('pt-config-sfx').checked = !!cfg.sfx_enabled;
    $('pt-config-sfx-chance').value = cfg.sfx_chance != null ? cfg.sfx_chance : 0.65;
    $('pt-config-sfx-lewd').checked = Array.isArray(cfg.sfx_domains) && cfg.sfx_domains.includes('lewd');
    // Dialogue feel: toggles default on (undefined -> checked); override fields
    // are blank unless this chat set them (a blank field uses the character default).
    const feel = cfg.dialogue_feel || {};
    $('pt-config-feel').checked = cfg.dialogue_feel_enabled !== false;
    $('pt-config-feel-roll').checked = cfg.dialogue_feel_roll_enabled !== false;
    $('pt-config-feel-cadence').value = feel.cadence || '';
    $('pt-config-feel-lexicon').value = feel.lexicon || '';
    $('pt-config-feel-tactic').value = feel.conversational_tactic || '';
    $('pt-config-feel-subtext').value = feel.subtext_rules || '';
    $('pt-config-feel-avoid').value = feel.avoid || '';
    $('pt-config-feel-examples').value = Array.isArray(feel.examples) ? feel.examples.join('\n') : '';
    renderPluginToggles();
    $('pt-config-msg').textContent = '';
    $('pt-config-save').disabled = false;
    $('pt-config-dialog').showModal();
  }

  // The config dialog's Plugins section: one checkbox per registered plugin, bound
  // to the conversation's enabled_plugins. Empty (no section) when no plugins exist.
  async function renderPluginToggles() {
    const box = $('pt-config-plugins');
    if (!box) return;
    const manifests = await loadPluginManifests();
    if (!manifests.length) { box.innerHTML = ''; return; }
    const enabled = enabledPluginIds();
    box.innerHTML = '<div class="pt-config-plugins-head">Plugins</div>' +
      manifests.map((m) => `<label class="pt-check" title="${_escHtml(m.description || '')}">
        <input type="checkbox" class="pt-plugin-check" value="${_escHtml(m.id)}" ${enabled.includes(m.id) ? 'checked' : ''}>
        ${_escHtml(m.name)}</label>`).join('');
  }

  async function saveConfig() {
    if (!_current) return;
    const msg = $('pt-config-msg');
    const window = parseInt($('pt-config-window').value, 10);
    if (!Number.isInteger(window) || window < 1) {
      msg.textContent = 'Context window must be a whole number ≥ 1.';
      return;
    }
    const btn = $('pt-config-save');
    btn.disabled = true;
    msg.textContent = 'Saving…';
    let sfxChance = parseFloat($('pt-config-sfx-chance').value);
    if (!Number.isFinite(sfxChance)) sfxChance = 0.65;
    sfxChance = Math.min(1, Math.max(0, sfxChance));
    const config = {
      context_window_turns: window,
      voice_enabled: $('pt-config-voice').checked,
      typing_timing_enabled: $('pt-config-timing').checked,
      variety_pass_enabled: $('pt-config-variety').checked,
      sfx_enabled: $('pt-config-sfx').checked,
      sfx_chance: sfxChance,
      sfx_domains: $('pt-config-sfx-lewd').checked ? ['lewd'] : [],
      dialogue_feel_enabled: $('pt-config-feel').checked,
      dialogue_feel_roll_enabled: $('pt-config-feel-roll').checked,
      dialogue_feel: {
        cadence: $('pt-config-feel-cadence').value.trim(),
        lexicon: $('pt-config-feel-lexicon').value.trim(),
        conversational_tactic: $('pt-config-feel-tactic').value.trim(),
        subtext_rules: $('pt-config-feel-subtext').value.trim(),
        avoid: $('pt-config-feel-avoid').value.trim(),
        examples: $('pt-config-feel-examples').value.split('\n').map((s) => s.trim()).filter(Boolean),
      },
    };
    const pluginChecks = document.querySelectorAll('.pt-plugin-check');
    if (pluginChecks.length) {
      config.enabled_plugins = Array.from(pluginChecks).filter((c) => c.checked).map((c) => c.value);
    }
    try {
      const updated = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}`,
        'PATCH', {
          title: $('pt-config-title').value.trim() || 'Conversation',
          scenario: $('pt-config-scenario').value,
          role_instructions: $('pt-config-role').value,
          device_user: {
            display_name: $('pt-config-username').value.trim() || 'You',
            persona: $('pt-config-persona').value,
          },
          config,
        });
      if (updated) _current.conversation = updated;
      $('pt-config-dialog').close();
      renderChatHead();   // reflect new title/scenario + toggle states
      await syncPlugins();  // load/unload plugin assets + refresh composer modes
    } catch (err) {
      msg.textContent = 'Save failed: ' + err.message;
      btn.disabled = false;
    }
  }

  // ---------- per-message controls: edit / hide / delete (SP5) ----------

  function getTurn(turnId) {
    const turns = (_current && _current.transcript && _current.transcript.turns) || [];
    return turns.find((t) => t.id === turnId) || null;
  }

  function findItem(turnId, itemId) {
    const t = getTurn(turnId);
    return t ? (t.items || []).find((i) => i.id === itemId) || null : null;
  }

  // A turn can be split across several segments (narration breaks it up), so per-
  // turn edits re-render the whole thread from the in-memory transcript rather
  // than swapping one DOM node — segments and dividers recompute correctly.
  function rerenderTurn() {
    renderThread();
  }

  function removeTurnFromDom() {
    renderThread();
  }

  function startEditItem(bubbleEl, turnId, item) {
    bubbleEl.classList.add('pt-bubble--editing');
    bubbleEl.innerHTML =
      `<textarea class="pt-edit-input" rows="2"></textarea>
       <div class="pt-edit-actions">
         <button type="button" class="pt-edit-save">Save</button>
         <button type="button" class="pt-edit-cancel secondary">Cancel</button>
       </div>`;
    const ta = bubbleEl.querySelector('.pt-edit-input');
    ta.value = item.text || '';
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    bubbleEl.querySelector('.pt-edit-cancel').addEventListener('click', () => rerenderTurn(turnId));
    bubbleEl.querySelector('.pt-edit-save').addEventListener('click', () => saveEditItem(turnId, item.id, ta.value));
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveEditItem(turnId, item.id, ta.value); }
      else if (e.key === 'Escape') { e.preventDefault(); rerenderTurn(turnId); }
    });
  }

  async function saveEditItem(turnId, itemId, text) {
    try {
      const updated = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}/items/${encodeURIComponent(itemId)}`,
        'PATCH', { text });
      updateTurnInMemory(turnId, updated);
    } catch (_) { /* keep the editor open on failure */ }
    rerenderTurn(turnId);
  }

  async function toggleHiddenOp(turnId, item) {
    try {
      const updated = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}/items/${encodeURIComponent(item.id)}`,
        'PATCH', { hidden_from_context: !item.hidden_from_context });
      updateTurnInMemory(turnId, updated);
      rerenderTurn(turnId);
    } catch (_) { /* leave as-is on failure */ }
  }

  async function deleteItemOp(turnId, item) {
    if (!confirm('Delete this message?')) return;
    let res;
    try {
      res = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}/items/${encodeURIComponent(item.id)}`, 'DELETE');
    } catch (_) { return; }
    const turns = _current.transcript.turns;
    const idx = turns.findIndex((t) => t.id === turnId);
    if (res && res.turn_deleted) {
      if (idx >= 0) turns.splice(idx, 1);
      removeTurnFromDom(turnId);
    } else {
      if (idx >= 0 && res) turns[idx] = res;
      rerenderTurn(turnId);
    }
  }

  async function deleteTurnOp(turnId) {
    if (!confirm('Delete this entire turn? This cannot be undone.')) return;
    try {
      await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}`, 'DELETE');
    } catch (_) { return; }
    const turns = _current.transcript.turns;
    const idx = turns.findIndex((t) => t.id === turnId);
    if (idx >= 0) turns.splice(idx, 1);
    removeTurnFromDom(turnId);
  }

  function updateTurnInMemory(turnId, updatedTurn) {
    if (!updatedTurn) return;
    const turns = _current.transcript.turns;
    const idx = turns.findIndex((t) => t.id === turnId);
    if (idx >= 0) turns[idx] = updatedTurn;
  }

  // Save a message to long-term memory (character scope) via the Remember plugin.
  // `verbatim` stores the message text as-is; `gist` distills it server-side.
  // Memory is side data (no transcript change), so feedback is a toast.
  async function memorizeOp(kind, turnId, itemId) {
    const t = (window.toast || function () {});
    const convId = _current.conversation.id;
    const base = `${APP}/conversations/${encodeURIComponent(convId)}/plugins/memory/actions`;
    try {
      let res;
      if (kind === 'verbatim') {
        const it = findItem(turnId, itemId);
        const text = (it && it.text) || '';
        if (!text.trim()) { t('warning', 'Nothing to remember in this message.'); return; }
        res = await api(`${base}/remember`, 'POST', { text, scope: 'character' });
      } else {
        t('info', 'Distilling a memory…');
        res = await api(`${base}/gist`, 'POST', { turn_id: turnId, item_id: itemId, scope: 'character' });
      }
      t('success', 'Remembered: ' + (res && res.title ? res.title : 'saved to memory'));
    } catch (err) {
      t('error', 'Memorize failed: ' + ((err && err.message) || err));
    }
  }

  // Wrap each non-error bubble with edit / hide / delete (+ Memorize when the
  // Remember plugin is on), and each turn's avatar with delete-turn (+ trace on
  // model turns). Idempotent — FieldControls skips already-wrapped slots, so
  // re-rendered turns get fresh wrapping.
  function wireThreadControls() {
    if (!window.FieldControls) return;
    const thread = $('pt-thread');
    // Per-bubble Memorize is only offered when the Remember plugin is enabled.
    const memoryOn = enabledPluginIds().includes('memory');
    thread.querySelectorAll('.pt-bubble[data-item]').forEach((el) => {
      if (el.__fcAttached) return;
      const turnId = el.dataset.turn;
      const itemId = el.dataset.item;
      const item0 = findItem(turnId, itemId);
      const hidden = item0 && item0.hidden_from_context;
      const controls = [
        { id: 'edit', label: '✏️', title: 'Edit text',
          onClick: (_ctx, ui) => { const it = findItem(turnId, itemId); if (it) startEditItem(ui.slot, turnId, it); } },
        { id: 'hide', label: hidden ? '👁' : '🚫', title: hidden ? 'Show in context' : 'Hide from context',
          onClick: () => { const it = findItem(turnId, itemId); if (it) toggleHiddenOp(turnId, it); } },
        { id: 'del', label: '🗑', title: 'Delete message',
          onClick: () => { const it = findItem(turnId, itemId); if (it) deleteItemOp(turnId, it); } },
      ];
      if (memoryOn) {
        // 🧠 Memorize expands (via FieldControls subactions) into Verbatim / Gist
        // (+ auto Cancel): Verbatim saves the message text as-is; Gist distills it.
        controls.push({ id: 'memorize', label: '🧠', title: 'Memorize',
          subactions: [
            { id: 'verbatim', label: 'Verbatim', title: 'Save this message exactly',
              onClick: () => memorizeOp('verbatim', turnId, itemId) },
            { id: 'gist', label: 'Gist', title: 'Distill a fact worth remembering',
              onClick: () => memorizeOp('gist', turnId, itemId) },
          ] });
      }
      FieldControls.attach(el, { kind: 'field', controls });
    });
    thread.querySelectorAll('.pt-turn[data-turn]').forEach((tEl) => {
      const av = tEl.querySelector('.pt-av');
      const turnId = tEl.dataset.turn;
      if (!av || av.__fcAttached || turnId === '__pending__') return;
      const isModel = tEl.classList.contains('pt-turn--model');
      const controls = [];
      if (isModel) controls.push({ id: 'trace', label: '🔍', title: 'View turn trace', onClick: () => openTrace(turnId) });
      controls.push({ id: 'delturn', label: '🗑', title: 'Delete this turn', onClick: () => deleteTurnOp(turnId) });
      FieldControls.attach(av, { kind: 'avatar', controls });
    });
  }

  // ---------- dev tools: trace viewer + pipeline node-graph (SP6) ----------

  let _promptIds = null;  // prattletale prompt-pal key -> entry id (lazy, cached)

  async function loadPromptIds() {
    if (_promptIds) return _promptIds;
    _promptIds = {};
    try {
      const data = await api('/prompt-pal/entries?app=prattletale');
      (data.entries || []).forEach((e) => {
        const key = (e.data || {}).key;
        if (key) _promptIds[key] = e.id;
      });
    } catch (_) { /* deep-links degrade to the unfiltered Prompt Pal page */ }
    return _promptIds;
  }

  // A pipeline step id maps to its Prompt Pal entry: the guard lives on the
  // "turn" entry (it's that prompt's guard sub-section).
  function promptKeyForStep(stepId) {
    return stepId === 'guard' ? 'turn' : stepId;
  }

  function promptPalLink(stepId) {
    const id = _promptIds && _promptIds[promptKeyForStep(stepId)];
    return id ? `/prompt-pal/?app=prattletale&highlight=${encodeURIComponent(id)}`
              : '/prompt-pal/?app=prattletale';
  }

  async function openTrace(turnId) {
    const body = $('pt-trace-body');
    body.innerHTML = '<div class="pt-empty">Loading trace…</div>';
    $('pt-trace-dialog').showModal();
    await loadPromptIds();
    let trace;
    try {
      trace = await api(
        `${APP}/conversations/${encodeURIComponent(_current.conversation.id)}` +
        `/turns/${encodeURIComponent(turnId)}/trace`);
    } catch (err) {
      const m = String(err.message || '');
      body.innerHTML = `<div class="pt-empty">${m.includes('404') ? 'No trace for this turn.' : 'Could not load trace: ' + _escHtml(m)}</div>`;
      return;
    }
    renderTrace(body, trace);
  }

  function traceSection(title, contentHtml) {
    return `<details class="pt-trace-sec" open><summary>${_escHtml(title)}</summary>${contentHtml}</details>`;
  }

  function pre(text) {
    return `<pre class="pt-trace-pre">${_escHtml(text || '')}</pre>`;
  }

  // The {{memory}} block format_memory_block produces numbers each entry "N. ".
  function memoryCount(block) {
    return ((block || '').match(/^\d+\.\s/gm) || []).length;
  }
  function memoryTitle(block) {
    return `🧠 Memories in context (${memoryCount(block)})`;
  }
  function memoryHtml(block) {
    return (block || '').trim()
      ? pre(block)
      : '<div class="pt-empty">No memories matched for this turn.</div>';
  }

  function renderTrace(body, trace) {
    _traceSteps = trace.steps || [];
    const parts = [];

    // node-graph of the pipeline (turn -> variety? -> guard)
    parts.push(nodeGraphHtml(_traceSteps));

    // Which long-term memories the turn pulled into context (the {{memory}} block
    // from the step that did retrieval). Surfaced up top so it's easy to see.
    const memStep = _traceSteps.find((s) => s.memory != null);
    if (memStep) parts.push(traceSection(memoryTitle(memStep.memory), memoryHtml(memStep.memory)));

    // error first when present, so a failed turn is debuggable
    if (trace.error) parts.push(traceSection('Error', pre(trace.error)));
    if (trace.voice_error) parts.push(traceSection('Voice error', pre(trace.voice_error)));

    const ctx = trace.context_input || {};
    const ctxRows = ['scenario', 'role_instructions', 'user_persona', 'character', 'transcript']
      .filter((k) => ctx[k] != null)
      .map((k) => `<div class="pt-ctx-row"><span class="pt-ctx-key">${_escHtml(k)}</span>${pre(ctx[k])}</div>`)
      .join('');
    if (ctxRows) parts.push(traceSection('Context input', ctxRows));

    parts.push(traceSection('Raw final output', pre(trace.raw_final_output)));

    const items = trace.parsed_items || [];
    const itemsHtml = items.length
      ? items.map((it) => `<div class="pt-ctx-row"><span class="pt-ctx-key">${_escHtml(it.type || '')}</span>${pre(it.text)}</div>`).join('')
      : '<div class="pt-empty">No parsed items.</div>';
    parts.push(traceSection(`Parsed items (${items.length})`, itemsHtml));

    if (trace.reveal_schedule) {
      parts.push(traceSection('Reveal schedule', pre(JSON.stringify(trace.reveal_schedule, null, 2))));
    }
    if (trace.job_id) parts.push(`<div class="pt-trace-job">job: ${_escHtml(trace.job_id)}</div>`);

    body.innerHTML = parts.join('');
    wireNodeGraph(body);
  }

  const STEP_LABELS = { turn: 'Turn', variety: 'Variety', guard: 'Guard' };

  function nodeGraphHtml(steps) {
    if (!steps.length) return '<div class="pt-empty">No pipeline steps captured.</div>';
    const nodes = steps.map((s, i) => {
      const label = STEP_LABELS[s.id] || s.name || s.id || `Step ${i + 1}`;
      const arrow = i < steps.length - 1 ? '<span class="pt-node-arrow">→</span>' : '';
      return `<button type="button" class="pt-node" data-idx="${i}" title="Show prompt & output">${_escHtml(label)}</button>${arrow}`;
    }).join('');
    return `<div class="pt-nodegraph-wrap">
      <div class="pt-nodegraph">${nodes}</div>
      <div class="pt-node-detail" id="pt-node-detail" hidden></div>
    </div>`;
  }

  // Stash the steps on the dialog so the node buttons can pull prompt/output.
  function wireNodeGraph(body) {
    body.querySelectorAll('.pt-node').forEach((btn) => {
      btn.addEventListener('click', () => showNodeDetail(Number(btn.dataset.idx), btn));
    });
  }

  let _traceSteps = [];

  function showNodeDetail(idx, btn) {
    const step = _traceSteps[idx];
    const detail = $('pt-node-detail');
    if (!step || !detail) return;
    document.querySelectorAll('.pt-node').forEach((n) => n.classList.remove('on'));
    btn.classList.add('on');
    const link = promptPalLink(step.id);
    const out = step.output != null ? pre(step.output) : '<div class="pt-empty">(output not captured)</div>';
    const memRow = step.memory != null
      ? `<div class="pt-ctx-row"><span class="pt-ctx-key">memory</span>${memoryHtml(step.memory)}</div>`
      : '';
    detail.hidden = false;
    detail.innerHTML =
      `<div class="pt-node-head">
         <strong>${_escHtml(STEP_LABELS[step.id] || step.name || step.id)}</strong>
         <a href="${link}" target="_blank" rel="noopener" class="pt-node-link">Edit prompt ↗</a>
       </div>
       <div class="pt-ctx-row"><span class="pt-ctx-key">prompt</span>${pre(step.prompt)}</div>
       ${memRow}
       <div class="pt-ctx-row"><span class="pt-ctx-key">output</span>${out}</div>`;
  }

  // ---------- new conversation ----------

  function openCreate() {
    const sel = $('pt-create-character');
    const chars = Object.values(_characters);
    if (!chars.length) {
      sel.innerHTML = '<option value="">No characters — create one in Hoodat first</option>';
    } else {
      chars.sort((a, b) => String(a.name || '').localeCompare(String(b.name || '')));
      sel.innerHTML = chars.map((c) =>
        `<option value="${_escHtml(c.id)}">${_escHtml(c.name || c.id)}</option>`).join('');
    }
    $('pt-create-title').value = '';
    $('pt-create-scenario').value = '';
    $('pt-create-role').value = '';
    $('pt-create-username').value = 'You';
    $('pt-create-persona').value = '';
    $('pt-create-voice').checked = false;
    $('pt-create-timing').checked = false;
    $('pt-create-msg').textContent = '';
    $('pt-create-submit').disabled = false;
    $('pt-create-dialog').showModal();
  }

  async function submitCreate() {
    const counterpart = $('pt-create-character').value;
    const msg = $('pt-create-msg');
    if (!counterpart) { msg.textContent = 'Pick a counterpart character.'; return; }
    const title = $('pt-create-title').value.trim() || 'New conversation';
    const btn = $('pt-create-submit');
    btn.disabled = true;
    msg.textContent = 'Creating…';
    // New conversations start with each plugin whose default_enabled is true.
    const manifests = await loadPluginManifests();
    const defaultPlugins = manifests.filter((m) => m.default_enabled).map((m) => m.id);
    try {
      const res = await api(`${APP}/conversations`, 'POST', {
        title,
        counterpart_character_id: counterpart,
        scenario: $('pt-create-scenario').value,
        role_instructions: $('pt-create-role').value,
        device_user: {
          display_name: $('pt-create-username').value.trim() || 'You',
          persona: $('pt-create-persona').value,
        },
        config: {
          voice_enabled: $('pt-create-voice').checked,
          typing_timing_enabled: $('pt-create-timing').checked,
          enabled_plugins: defaultPlugins,
        },
      });
      $('pt-create-dialog').close();
      openConversation(res.id);
    } catch (err) {
      msg.textContent = 'Create failed: ' + err.message;
      btn.disabled = false;
    }
  }

  // ---------- input ergonomics ----------

  function autoGrow() {
    const inp = $('pt-input');
    inp.style.height = 'auto';
    inp.style.height = Math.min(inp.scrollHeight, 140) + 'px';
  }

  // ---------- wiring ----------

  function wire() {
    $('pt-new').addEventListener('click', openCreate);
    $('pt-create-close').addEventListener('click', () => $('pt-create-dialog').close());
    $('pt-create-cancel').addEventListener('click', () => $('pt-create-dialog').close());
    $('pt-create-submit').addEventListener('click', submitCreate);

    $('pt-back').addEventListener('click', goList);
    $('pt-delete').addEventListener('click', deleteConversation);
    $('pt-voice-toggle').addEventListener('click', () => toggleConfig('voice_enabled'));
    $('pt-timing-toggle').addEventListener('click', () => toggleConfig('typing_timing_enabled'));
    $('pt-variety-toggle').addEventListener('click', () => toggleConfig('variety_pass_enabled'));
    $('pt-mode').addEventListener('click', () => { if (_sectionIdx === 0) cycleTextMode(1); });
    $('pt-modebar').addEventListener('click', (e) => {
      const btn = e.target.closest('.pt-modebar-item');
      if (btn) selectSection(parseInt(btn.dataset.idx, 10));
    });
    $('pt-send').addEventListener('click', submitOrStack);

    $('pt-delete-mode').addEventListener('click', toggleDeleteMode);
    $('pt-settings').addEventListener('click', openSettings);
    $('pt-settings-close').addEventListener('click', () => $('pt-settings-dialog').close());
    $('pt-settings-cancel').addEventListener('click', () => $('pt-settings-dialog').close());
    $('pt-settings-save').addEventListener('click', saveSettings);

    $('pt-config').addEventListener('click', openConfig);
    $('pt-config-close').addEventListener('click', () => $('pt-config-dialog').close());
    $('pt-config-cancel').addEventListener('click', () => $('pt-config-dialog').close());
    $('pt-config-save').addEventListener('click', saveConfig);

    $('pt-trace-close').addEventListener('click', () => $('pt-trace-dialog').close());

    const inp = $('pt-input');
    inp.addEventListener('input', () => { autoGrow(); updateSendBtn(); });
    inp.addEventListener('keydown', onComposerKey);

    window.addEventListener('popstate', showView);
  }

  // Keyboard model: with text in the box you're *composing* (keys type, Enter
  // stacks); on an empty box the same keys become *commands* so single letters
  // don't get eaten mid-message.
  //   Enter        text -> stack a bubble · empty -> send the chain
  //   Tab/⇧Tab     cycle Say/Do/Narrate (in Essentials); from a plugin, jump back to
  //                Essentials (Tab -> Say, ⇧Tab -> Do)
  //   ←  →         (empty) move between mode-bar sections (Essentials <-> plugins)
  //   X            (empty) remove the most recent staged bubble
  //   Esc          clear all staged bubbles (and the box)
  function onComposerKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitOrStack(); return; }
    // Tab switches Say/Do/Narrate within Essentials (it types no character, so it works
    // mid-message too). From a plugin section it jumps back to Essentials: Tab -> Say,
    // Shift+Tab -> Do.
    if (e.key === 'Tab') {
      e.preventDefault();
      if (_sectionIdx !== 0) { _sectionIdx = 0; _textModeIdx = e.shiftKey ? 1 : 0; renderMode(); }
      else cycleTextMode(e.shiftKey ? -1 : 1);
      return;
    }
    if (e.key === 'Escape') {
      if (_draft.length || $('pt-input').value) {
        e.preventDefault();
        _draft = []; _editing = -1;
        $('pt-input').value = ''; autoGrow();
        renderDraft();
      }
      return;
    }
    if ($('pt-input').value !== '') return;   // below here: empty-box command mode
    if (e.key === 'ArrowLeft') { e.preventDefault(); cycleSection(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); cycleSection(1); }
    else if (e.key === 'x' || e.key === 'X') { e.preventDefault(); if (_draft.length) removeStaged(_draft.length - 1); }
  }

  wire();
  showView();
})();
