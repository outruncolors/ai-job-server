/* Assistant pane — the co-author chatroom + composer. */
(function () {
  const A = {};

  function log() {
    return document.getElementById('tb-assistant-log');
  }

  function fmtTime(at) {
    if (!at) return '';
    try {
      return new Date(at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return '';
    }
  }

  function bubble(m) {
    if (m.role === 'marker') {
      return `<div class="tb-marker">${_escHtml(m.text)}</div>`;
    }
    const side = m.role === 'user' ? 'user' : 'asst';
    const isManuscript = m.proposal && m.proposal.scope && ['selection', 'unit'].includes(m.proposal.scope.kind);
    let actions = '';
    if (m.proposal && m.proposal.status === 'pending') {
      if (isManuscript) {
        actions = `<div class="tb-msg-acts"><button data-viewdiff="${_escHtml(m.request_id)}|${_escHtml(m.proposal.diff_id)}|${_escHtml(m.proposal.scope.kind)}">View diff</button></div>`;
      } else {
        actions = `<div class="tb-msg-acts">
          <button data-acc="${_escHtml(m.request_id)}">Accept</button>
          <button data-rej="${_escHtml(m.request_id)}">Reject</button>
          <button data-itr="${_escHtml(m.request_id)}">Iterate…</button></div>`;
      }
    } else if (m.proposal && m.proposal.status) {
      actions = `<div class="tb-msg-status">${_escHtml(m.proposal.status)}</div>`;
    }
    const modeTag = m.mode ? `<span class="tb-msg-mode">${_escHtml(m.mode)}</span>` : '';
    const dbg = m.request_id ? `<button class="tb-msg-dbg" data-dbg="${_escHtml(m.request_id)}" title="Inspect in debug">🐞</button>` : '';
    return `
      <div class="tb-msg ${side}">
        <div class="tb-msg-head">${modeTag}<span class="tb-msg-time">${fmtTime(m.at)}</span>${dbg}</div>
        <div class="tb-msg-text">${_escHtml(m.text || '')}</div>
        ${actions}
      </div>`;
  }

  A.render = function (messages) {
    const l = log();
    l.innerHTML = (messages || []).map(bubble).join('');
    l.scrollTop = l.scrollHeight;
    l.querySelectorAll('[data-acc]').forEach((el) =>
      el.addEventListener('click', () => A.accept(el.getAttribute('data-acc')))
    );
    l.querySelectorAll('[data-rej]').forEach((el) =>
      el.addEventListener('click', () => A.reject(el.getAttribute('data-rej')))
    );
    l.querySelectorAll('[data-itr]').forEach((el) =>
      el.addEventListener('click', () => A.iterate(el.getAttribute('data-itr')))
    );
    l.querySelectorAll('[data-viewdiff]').forEach((el) =>
      el.addEventListener('click', () => {
        const [rid, diff, kind] = el.getAttribute('data-viewdiff').split('|');
        TB.ContentPane.showProposal({ request_id: rid, diff_id: diff, scope: { kind } });
        if (TB.switchLeftTab) TB.switchLeftTab('content');
      })
    );
    l.querySelectorAll('[data-dbg]').forEach((el) =>
      el.addEventListener('click', () => TB.Debug && TB.Debug.open(el.getAttribute('data-dbg')))
    );
  };

  A.reload = async function () {
    const data = await TB.api.assistant(TB.tale.id);
    TB.assistant = data;
    A.render(data.messages);
  };

  A.send = async function () {
    const input = document.getElementById('tb-input');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    const body = {
      text,
      mode: TB.mode,
      saved_prompt_key: TB.savedPromptKey || null,
      active_pane: TB.activePane,
      current_unit_id: TB.currentUnitId,
      scope: TB.selection
        ? { kind: 'selection', selected_text: TB.selection.selected_text, char_range: TB.selection.char_range }
        : { kind: 'unit' },
      context_concept_ids: [],
    };
    A.busy(true);
    try {
      const res = await TB.api.request(TB.tale.id, body);
      await A.handleResult(res);
    } catch (err) {
      toast('error', 'Request failed: ' + err.message);
    } finally {
      A.busy(false);
    }
  };

  A.handleResult = async function (res) {
    await A.reload();
    if (res && res.error) {
      toast('error', res.error);
      return;
    }
    if (res && res.proposal && res.proposal.scope && ['selection', 'unit'].includes(res.proposal.scope.kind)) {
      await TB.ContentPane.showProposal({
        request_id: res.request_id,
        diff_id: res.proposal.diff_id,
        scope: res.proposal.scope,
      });
      if (TB.switchLeftTab) TB.switchLeftTab('content');
    }
  };

  A.accept = async function (rid) {
    try {
      await TB.api.accept(TB.tale.id, rid);
      await TB.refreshConcepts();
      await A.reload();
      if (TB.OrgPane) TB.OrgPane.render();
      if (TB.ContentPane) TB.ContentPane.render();
      toast('success', 'Accepted');
    } catch (err) {
      toast('error', 'Accept failed: ' + err.message);
    }
  };

  A.reject = async function (rid) {
    try {
      await TB.api.reject(TB.tale.id, rid);
      await A.reload();
      toast('info', 'Rejected');
    } catch (err) {
      toast('error', 'Reject failed: ' + err.message);
    }
  };

  A.iterate = async function (rid) {
    const feedback = prompt('What should change next?');
    if (feedback === null) return;
    A.busy(true);
    try {
      const res = await TB.api.iterate(TB.tale.id, rid, feedback);
      await A.handleResult(res);
    } catch (err) {
      toast('error', 'Iterate failed: ' + err.message);
    } finally {
      A.busy(false);
    }
  };

  A.busy = function (on) {
    const btn = document.getElementById('tb-send');
    btn.disabled = on;
    btn.textContent = on ? '…' : 'Send';
  };

  A.init = function () {
    document.getElementById('tb-send').addEventListener('click', () => A.send());
    document.getElementById('tb-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        A.send();
      }
    });
  };

  window.TB = window.TB || {};
  window.TB.Assistant = A;
})();
