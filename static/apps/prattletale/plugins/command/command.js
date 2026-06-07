/* Command plugin frontend.
 *
 * A command is a standing order — a switch the user flips on, not a message the
 * partner replies to. Contributes a ⚡ Command composer mode: the main composer
 * input is reused as the order text, and Go (relabeled "Issue") runs the `send`
 * action — which posts a user `command` turn only (no model reply). The order then
 * stays in force on every future turn until switched off. Renders the command
 * bubble (dark card, blue border, ⚡ badge) and, via the generic onRender hook, a
 * header "⚡ N" button that opens a manager modal where active commands can be
 * edited or deleted (switched off) in place (reusing the core per-item PATCH/DELETE
 * endpoints).
 *
 * Loaded by the core only when the plugin is enabled for the conversation. */
(function () {
  if (!window.PtPlugins) return;

  var APP = '/apps/prattletale';
  var _ctx = null;   // latest plugin ctx, refreshed on every onRender

  // ---- composer mode ----

  // The slide-up panel holds only an explainer; the order text comes from the
  // composer input and is sent on Issue.
  function renderPanel(container, _c) {
    container.innerHTML =
      '<div class="pt-command-panel">' +
      '<div class="pt-cmd-explainer">⚡ A <b>command</b> is an out-of-character standing ' +
      'order — a switch you flip on. The character won\'t reply to it; it stays in force on ' +
      'every reply until you switch it off. Type it below and press <b>Issue</b>.</div>' +
      '<div class="pt-cmd-msg" hidden></div>' +
      '</div>';
  }

  async function submitPanel(ctx) {
    var box = ctx.panelEl;
    var msg = box.querySelector('.pt-cmd-msg');
    var text = ctx.primaryValue();
    if (!text) {
      if (msg) { msg.hidden = false; msg.className = 'pt-cmd-msg pt-cmd-err'; msg.textContent = 'Type a command first.'; }
      return;
    }
    if (msg) { msg.hidden = false; msg.className = 'pt-cmd-msg'; msg.textContent = 'Switching command on…'; }
    try {
      var res = await ctx.invokeAction('send', { text: text });
      // A command is a switch, not a message: append the command bubble only — no
      // partner reply is generated. The order takes effect on the next normal turn.
      if (res && res.command_turn) ctx.appendTurn(res.command_turn);
      var inp = document.getElementById('pt-input');
      if (inp) inp.value = '';
      ctx.close();   // back to the previous text mode (panel slides down)
    } catch (err) {
      if (msg) { msg.className = 'pt-cmd-msg pt-cmd-err'; msg.textContent = 'Command failed: ' + ((err && err.message) || err); }
      throw err;     // let the core re-enable the composer
    }
  }

  // ---- command bubble ----

  function renderCommand(item, turn) {
    var hidden = item.hidden_from_context ? ' pt-bubble--hidden' : '';
    var tag = item.hidden_from_context
      ? '<span class="pt-hidden-tag" title="Hidden from context">🚫 hidden</span>' : '';
    return '<div class="pt-bubble pt-bubble--command' + hidden + '" data-turn="' +
      _escHtml(turn.id) + '" data-item="' + _escHtml(item.id) + '">' +
      '<span class="pt-cmd-badge" title="Command">⚡</span>' +
      '<span class="pt-cmd-bubble-label">COMMAND</span>' +
      '<span class="pt-cmd-bubble-text">' + _escHtml(item.text || '') + '</span>' + tag + '</div>';
  }

  // ---- active-commands indicator + manager ----

  // Active commands: visible (not hidden) command items, oldest first.
  function activeCommands(ctx) {
    var out = [];
    var turns = (ctx.transcript && ctx.transcript.turns) || [];
    turns.forEach(function (t) {
      (t.items || []).forEach(function (it) {
        if (it.type === 'command' && !it.hidden_from_context) {
          out.push({ turnId: t.id, itemId: it.id, text: it.text || '' });
        }
      });
    });
    return out;
  }

  // Keep the header "⚡ N" button in sync after every render.
  function onRender(ctx) {
    _ctx = ctx;
    var head = document.getElementById('pt-chat-head');
    if (!head) return;
    var btn = document.getElementById('pt-commands-btn');
    if (!btn) {
      btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'pt-commands-btn';
      btn.className = 'pt-icon-btn pt-commands-btn';
      btn.setAttribute('aria-label', 'Active commands');
      btn.title = 'Active commands';
      btn.addEventListener('click', function () { openManager(); });
      var anchor = document.getElementById('pt-config');
      head.insertBefore(btn, anchor || null);
    }
    var n = activeCommands(ctx).length;
    btn.textContent = '⚡ ' + n;
    btn.hidden = n === 0;
  }

  function ensureManagerDialog() {
    var dlg = document.getElementById('pt-commands-dialog');
    if (dlg) return dlg;
    dlg = document.createElement('dialog');
    dlg.id = 'pt-commands-dialog';
    dlg.className = 'pt-commands-dialog';
    dlg.innerHTML =
      '<div class="dlg-head"><h3>⚡ Active commands</h3>' +
      '<button type="button" class="x" id="pt-commands-close" aria-label="Close">×</button></div>' +
      '<div id="pt-commands-list" class="pt-commands-list"></div>';
    document.body.appendChild(dlg);
    dlg.querySelector('#pt-commands-close').addEventListener('click', function () { dlg.close(); });
    return dlg;
  }

  function openManager() {
    var dlg = ensureManagerDialog();
    renderManagerList();
    if (!dlg.open) dlg.showModal();
  }

  function renderManagerList() {
    var list = document.getElementById('pt-commands-list');
    if (!list || !_ctx) return;
    var cmds = activeCommands(_ctx);
    if (!cmds.length) {
      list.innerHTML = '<div class="pt-empty">No active commands.</div>';
      return;
    }
    list.innerHTML = cmds.map(function (c) {
      return '<div class="pt-cmd-row" data-turn="' + _escHtml(c.turnId) + '" data-item="' + _escHtml(c.itemId) + '">' +
        '<div class="pt-cmd-row-text">' + _escHtml(c.text) + '</div>' +
        '<div class="pt-cmd-row-actions">' +
        '<button type="button" class="pt-cmd-edit" title="Edit">✏️</button>' +
        '<button type="button" class="pt-cmd-del" title="Delete">🗑</button>' +
        '</div></div>';
    }).join('');
    list.querySelectorAll('.pt-cmd-row').forEach(function (row) {
      var turnId = row.getAttribute('data-turn');
      var itemId = row.getAttribute('data-item');
      row.querySelector('.pt-cmd-edit').addEventListener('click', function () { startEdit(row, turnId, itemId); });
      row.querySelector('.pt-cmd-del').addEventListener('click', function () { deleteCommand(turnId, itemId); });
    });
  }

  function itemPath(turnId, itemId) {
    var cid = _ctx.conversation.id;
    return APP + '/conversations/' + encodeURIComponent(cid) +
      '/turns/' + encodeURIComponent(turnId) + '/items/' + encodeURIComponent(itemId);
  }

  function startEdit(row, turnId, itemId) {
    var textEl = row.querySelector('.pt-cmd-row-text');
    var current = textEl.textContent;
    row.classList.add('pt-cmd-editing');
    row.innerHTML =
      '<textarea class="pt-cmd-edit-input" rows="2"></textarea>' +
      '<div class="pt-cmd-row-actions">' +
      '<button type="button" class="pt-cmd-save" title="Save">Save</button>' +
      '<button type="button" class="pt-cmd-cancel" title="Cancel">Cancel</button>' +
      '</div>';
    var ta = row.querySelector('.pt-cmd-edit-input');
    ta.value = current;
    ta.focus();
    row.querySelector('.pt-cmd-cancel').addEventListener('click', function () { renderManagerList(); });
    row.querySelector('.pt-cmd-save').addEventListener('click', async function () {
      var text = ta.value.trim();
      if (!text) { renderManagerList(); return; }
      try {
        await _ctx.api(itemPath(turnId, itemId), 'PATCH', { text: text });
        await _ctx.reload();   // refresh thread + _ctx
        renderManagerList();
      } catch (err) {
        if (window.toast) window.toast('error', 'Edit failed: ' + ((err && err.message) || err));
      }
    });
  }

  async function deleteCommand(turnId, itemId) {
    try {
      await _ctx.api(itemPath(turnId, itemId), 'DELETE');
      await _ctx.reload();   // refresh thread + _ctx
      var remaining = activeCommands(_ctx).length;
      if (remaining === 0) {
        var dlg = document.getElementById('pt-commands-dialog');
        if (dlg && dlg.open) dlg.close();
      } else {
        renderManagerList();
      }
    } catch (err) {
      if (window.toast) window.toast('error', 'Delete failed: ' + ((err && err.message) || err));
    }
  }

  PtPlugins.register({
    id: 'command',
    composerModes: [{
      type: 'command',
      label: '⚡ Command',
      goLabel: 'Issue',
      placeholder: 'A standing order the AI obeys until you switch it off…',
    }],
    renderPanel: renderPanel,
    submitPanel: submitPanel,
    bubble: { types: ['command'], render: renderCommand },
    onRender: onRender,
  });
})();
