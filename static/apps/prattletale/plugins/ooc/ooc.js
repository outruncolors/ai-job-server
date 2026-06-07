/* OOC plugin frontend.
 *
 * Contributes a ⌁ OOC composer mode: a parallel, out-of-character chat with the
 * author behind the character. The main composer input is reused as the OOC
 * message; Go (relabeled "Send") runs the `send` action — which posts the user's
 * OOC message AND the author's reply — then appends both. Unlike the other
 * plugins, it does NOT return to text mode on Go: staying in OOC mode is what lets
 * the user continue the back-and-forth. Sending a normal (Essentials) message is
 * what ends the session (the run collapses; the core renderer groups consecutive
 * ooc items into a bordered collapsible panel).
 *
 * Loaded by the core only when the plugin is enabled for the conversation. */
(function () {
  if (!window.PtPlugins) return;

  // The slide-up panel holds only an explainer; the message comes from the
  // composer input and is sent on "Send".
  function renderPanel(container, _c) {
    container.innerHTML =
      '<div class="pt-ooc-cmp-panel">' +
      '<div class="pt-ooc-explainer">⌁ <b>Out of character.</b> Talk with the author ' +
      'behind the character about the scene — they reply out of character (never as ' +
      'the character). Keep replying here to continue; send a normal message to end ' +
      'this OOC session — it collapses into a panel you can reopen later.</div>' +
      '<div class="pt-ooc-cmp-msg" hidden></div>' +
      '</div>';
  }

  async function submitPanel(ctx) {
    var box = ctx.panelEl;
    var msg = box.querySelector('.pt-ooc-cmp-msg');
    var text = ctx.primaryValue();
    if (!text) {
      if (msg) { msg.hidden = false; msg.className = 'pt-ooc-cmp-msg pt-ooc-cmp-err'; msg.textContent = 'Type a message first.'; }
      return;
    }
    if (msg) { msg.hidden = false; msg.className = 'pt-ooc-cmp-msg'; msg.textContent = 'The author is replying…'; }
    try {
      var res = await ctx.invokeAction('send', { text: text });
      // Append both ends of the exchange; they merge into the active OOC panel.
      if (res && res.ooc_user_turn) ctx.appendTurn(res.ooc_user_turn);
      if (res && res.ooc_model_turn) ctx.appendTurn(res.ooc_model_turn);
      var inp = document.getElementById('pt-input');
      if (inp) inp.value = '';
      if (msg) { msg.hidden = true; msg.textContent = ''; }
      // Deliberately stay in OOC mode (no ctx.close()) so the user can keep going.
    } catch (err) {
      if (msg) { msg.className = 'pt-ooc-cmp-msg pt-ooc-cmp-err'; msg.textContent = 'OOC failed: ' + ((err && err.message) || err); }
      throw err;     // let the core re-enable the composer
    }
  }

  // One inner OOC bubble, sided by author: the user's line (right) vs the author's
  // reply (left). Keeps data-turn/data-item so the core per-message controls attach.
  function renderOoc(item, turn) {
    var isYou = item.author === 'user';
    var side = isYou ? 'you' : 'ai';
    var who = isYou ? 'you' : 'author';
    var hidden = item.hidden_from_context ? ' pt-bubble--hidden' : '';
    var tag = item.hidden_from_context
      ? '<span class="pt-hidden-tag" title="Hidden from context">🚫 hidden</span>' : '';
    return '<div class="pt-bubble pt-ooc-msg-bubble pt-ooc-msg--' + side + hidden + '" data-turn="' +
      _escHtml(turn.id) + '" data-item="' + _escHtml(item.id) + '">' +
      '<span class="pt-ooc-who">' + who + '</span>' +
      '<span class="pt-ooc-text">' + _escHtml(item.text || '') + '</span>' + tag + '</div>';
  }

  PtPlugins.register({
    id: 'ooc',
    composerModes: [{
      type: 'ooc',
      label: '⌁ OOC',
      goLabel: 'Send',
      placeholder: 'Talk to the author, out of character…',
    }],
    renderPanel: renderPanel,
    submitPanel: submitPanel,
    bubble: { types: ['ooc'], render: renderOoc },
  });
})();
