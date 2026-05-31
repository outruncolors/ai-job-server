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

  // user-authorable bubble modes, cycled by the composer's mode button
  const MODES = [
    { type: 'dialogue', label: '💬 Say' },
    { type: 'action', label: '🎬 Do' },
    { type: 'narration', label: '📖 Narrate' },
  ];

  let _characters = {};   // id -> character summary
  let _conversations = []; // list summaries
  let _current = null;     // {conversation, transcript} of the open chat
  let _draft = [];         // staged composer items before commit
  let _modeIdx = 0;
  let _sending = false;

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

  async function loadList() {
    const list = $('pt-list');
    list.setAttribute('aria-busy', 'true');
    await loadCharacters();
    const data = await api(`${APP}/conversations`);
    _conversations = data.conversations || [];
    _conversations.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    renderList();
    list.setAttribute('aria-busy', 'false');
  }

  function renderList() {
    const list = $('pt-list');
    if (!_conversations.length) {
      list.innerHTML = '<div class="pt-empty">No conversations yet. Start a new one to begin.</div>';
      return;
    }
    list.innerHTML = _conversations.map((c) => {
      const cp = counterpartOf(c);
      const name = cp ? cp.name : (c.title || 'Conversation');
      const av = avatarHtml(name, cp && cp.avatar_path, c.counterpart_character_id, 'pt-av');
      const preview = c.last_item_preview || c.title || '';
      return `<button type="button" class="pt-row" data-id="${_escHtml(c.id)}">
        ${av}
        <span class="pt-row-main">
          <span class="pt-row-top">
            <span class="pt-row-name">${_escHtml(name)}</span>
            <span class="pt-row-time">${_escHtml(fmtTime(c.updated_at))}</span>
          </span>
          <span class="pt-row-preview">${_escHtml(preview)}</span>
        </span>
      </button>`;
    }).join('');
    list.querySelectorAll('.pt-row').forEach((row) => {
      row.addEventListener('click', () => openConversation(row.dataset.id));
    });
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
    thread.setAttribute('aria-busy', 'false');
  }

  function renderChatHead() {
    const conv = _current.conversation;
    const cp = counterpartOf(conv);
    const name = cp ? cp.name : (conv.title || 'Conversation');
    fillAvatar($('pt-chat-avatar'), name, cp && cp.avatar_path, conv.counterpart_character_id);
    $('pt-chat-name').textContent = name;
    $('pt-chat-sub').textContent = conv.title && conv.title !== name ? conv.title : (conv.scenario || '');
  }

  function renderThread() {
    const thread = $('pt-thread');
    const turns = (_current.transcript && _current.transcript.turns) || [];
    if (!turns.length) {
      thread.innerHTML = '<div class="pt-empty pt-thread-empty">Say something to get started.</div>';
      return;
    }
    thread.innerHTML = turns.map(turnHtml).join('');
    wireRetry();
    scrollToBottom();
  }

  function turnHtml(turn) {
    const conv = _current.conversation;
    const isUser = turn.author === 'user';
    const cp = counterpartOf(conv);
    const name = isUser ? (conv.device_user && conv.device_user.display_name) || 'You'
                        : (cp ? cp.name : 'Character');
    const avPath = isUser ? (conv.device_user && conv.device_user.avatar_path)
                          : (cp && cp.avatar_path);
    const avId = isUser ? 'device-user' : conv.counterpart_character_id;
    const av = avatarHtml(name, avPath, avId, 'pt-av pt-av-sm');
    const bubbles = (turn.items || []).map((it) => bubbleHtml(it, turn)).join('');
    return `<div class="pt-turn pt-turn--${isUser ? 'user' : 'model'}">
      ${isUser ? '' : av}
      <div class="pt-stack">${bubbles}</div>
      ${isUser ? av : ''}
    </div>`;
  }

  function bubbleHtml(item, turn) {
    const type = item.type || 'dialogue';
    if (type === 'system_error') {
      return `<div class="pt-bubble pt-bubble--error" data-turn="${_escHtml(turn.id)}">
        <span class="pt-err-text">${_escHtml(item.text || 'Generation failed.')}</span>
        <button type="button" class="pt-retry" data-turn="${_escHtml(turn.id)}">↻ Retry</button>
      </div>`;
    }
    return `<div class="pt-bubble pt-bubble--${_escHtml(type)}">${_escHtml(item.text || '')}</div>`;
  }

  function scrollToBottom() {
    const thread = $('pt-thread');
    thread.scrollTop = thread.scrollHeight;
  }

  // ---------- composer ----------

  function resetComposer() {
    _draft = [];
    _modeIdx = 0;
    $('pt-input').value = '';
    renderMode();
    renderDraft();
  }

  function renderMode() {
    $('pt-mode').textContent = MODES[_modeIdx].label;
  }

  function cycleMode() {
    _modeIdx = (_modeIdx + 1) % MODES.length;
    renderMode();
  }

  function renderDraft() {
    const box = $('pt-draft');
    if (!_draft.length) {
      box.hidden = true;
      box.innerHTML = '';
      return;
    }
    box.hidden = false;
    box.innerHTML = _draft.map((d, i) => {
      const label = (MODES.find((m) => m.type === d.type) || {}).label || d.type;
      return `<span class="pt-chip pt-bubble--${_escHtml(d.type)}">
        <span class="pt-chip-tag">${_escHtml(label)}</span>
        <span class="pt-chip-text">${_escHtml(d.text)}</span>
        <button type="button" class="pt-chip-x" data-i="${i}" aria-label="Remove">×</button>
      </span>`;
    }).join('');
    box.querySelectorAll('.pt-chip-x').forEach((b) => {
      b.addEventListener('click', () => { _draft.splice(Number(b.dataset.i), 1); renderDraft(); });
    });
  }

  function takeInput() {
    const inp = $('pt-input');
    const text = inp.value.trim();
    if (!text) return null;
    const item = { type: MODES[_modeIdx].type, text };
    inp.value = '';
    autoGrow();
    return item;
  }

  function stackItem() {
    const item = takeInput();
    if (!item) return;
    _draft.push(item);
    renderDraft();
    $('pt-input').focus();
  }

  async function send() {
    if (_sending) return;
    const pending = takeInput();
    const items = pending ? _draft.concat([pending]) : _draft.slice();
    if (!items.length) return;

    _sending = true;
    setComposerEnabled(false);

    // optimistic: drop the staged items so the box is clean, show the user turn
    // only after the server echoes it back (keeps ids authoritative).
    _draft = [];
    renderDraft();

    const id = _current.conversation.id;
    const typingEl = showTyping();
    try {
      const res = await api(
        `${APP}/conversations/${encodeURIComponent(id)}/turns`, 'POST', { items });
      typingEl.remove();
      _current.transcript.turns.push(res.user_turn, res.model_turn);
      appendTurn(res.user_turn);
      appendTurn(res.model_turn);
      wireRetry();
      scrollToBottom();
    } catch (err) {
      typingEl.remove();
      // surface the failure inline without faking a turn
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

  function appendTurn(turn) {
    const thread = $('pt-thread');
    const empty = thread.querySelector('.pt-thread-empty');
    if (empty) empty.remove();
    thread.insertAdjacentHTML('beforeend', turnHtml(turn));
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
    ['pt-input', 'pt-send', 'pt-stack', 'pt-mode'].forEach((id) => { $(id).disabled = !on; });
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
      if (turnEl) {
        turnEl.outerHTML = turnHtml(newTurn);
        wireRetry();
      } else {
        renderThread();
      }
      scrollToBottom();
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
    $('pt-mode').addEventListener('click', cycleMode);
    $('pt-stack').addEventListener('click', stackItem);
    $('pt-send').addEventListener('click', send);

    const inp = $('pt-input');
    inp.addEventListener('input', autoGrow);
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    });

    window.addEventListener('popstate', showView);
  }

  wire();
  showView();
})();
