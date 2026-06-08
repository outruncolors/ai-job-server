/* Content pane — contenteditable editor + inline proposal spans. */
(function () {
  const ContentPane = {};

  function els() {
    return {
      empty: document.getElementById('tb-content-empty'),
      head: document.getElementById('tb-content-head'),
      title: document.getElementById('tb-content-title'),
      meta: document.getElementById('tb-content-meta'),
      editor: document.getElementById('tb-editor'),
      bar: document.getElementById('tb-proposal-bar'),
      label: document.getElementById('tb-proposal-label'),
    };
  }

  // Render the current unit's body into the editor (plain text).
  ContentPane.render = function () {
    const e = els();
    const unit = TB.currentUnit();
    if (!unit) {
      e.empty.hidden = false;
      e.head.hidden = true;
      e.editor.hidden = true;
      e.bar.hidden = true;
      return;
    }
    e.empty.hidden = true;
    e.head.hidden = false;
    e.editor.hidden = false;
    e.title.textContent = unit.title || '(untitled)';
    e.meta.textContent = `${unit.type} · ${(unit.metadata || {}).word_count || 0} words · ${(unit.metadata || {}).status || 'draft'}`;
    if (!TB.pendingProposal) {
      e.editor.textContent = unit.body || '';
      e.bar.hidden = true;
      e.editor.contentEditable = 'true';
    }
  };

  // Capture the current selection inside the editor as a scope.
  ContentPane.captureSelection = function () {
    const e = els();
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) {
      TB.selection = null;
      return;
    }
    const range = sel.getRangeAt(0);
    if (!e.editor.contains(range.commonAncestorContainer)) {
      TB.selection = null;
      return;
    }
    const text = sel.toString();
    if (!text.trim()) {
      TB.selection = null;
      return;
    }
    // char range relative to the editor's text content
    const pre = range.cloneRange();
    pre.selectNodeContents(e.editor);
    pre.setEnd(range.startContainer, range.startOffset);
    const start = pre.toString().length;
    TB.selection = { selected_text: text, char_range: [start, start + text.length] };
  };

  // Save manual edits back to the concept body.
  ContentPane.saveEdits = async function () {
    const e = els();
    const unit = TB.currentUnit();
    if (!unit || TB.pendingProposal) return;
    const body = e.editor.textContent;
    if (body === (unit.body || '')) return;
    await TB.api.patchConcept(TB.tale.id, unit.id, { body });
    await TB.refreshConcepts();
    if (window.TB.OrgPane) TB.OrgPane.render();
  };

  // Show a manuscript-diff proposal inline (insert=green, delete=red).
  ContentPane.showProposal = async function (proposal) {
    const e = els();
    TB.pendingProposal = proposal;
    e.editor.contentEditable = 'false';
    let segments = null;
    try {
      const data = await TB.api.proposal(TB.tale.id, proposal.diff_id);
      segments = data.segments;
    } catch (err) {
      segments = null;
    }
    if (segments) {
      e.editor.innerHTML = segments
        .map((s) => {
          if (s.kind === 'equal') return _escHtml(s.text);
          const cls = s.kind === 'insert' ? 'tb-ins' : 'tb-del';
          return `<span class="${cls}">${_escHtml(s.text)}</span>`;
        })
        .join('');
    }
    e.bar.hidden = false;
    e.label.textContent = `Proposed edit (${proposal.scope ? proposal.scope.kind : 'unit'}) — review:`;
  };

  ContentPane.clearProposal = function () {
    TB.pendingProposal = null;
    ContentPane.render();
  };

  ContentPane.init = function () {
    const e = els();
    e.editor.addEventListener('mouseup', () => ContentPane.captureSelection());
    e.editor.addEventListener('keyup', () => ContentPane.captureSelection());
    e.editor.addEventListener('blur', () => ContentPane.saveEdits());
    document.getElementById('tb-accept').addEventListener('click', () => ContentPane.onAccept());
    document.getElementById('tb-reject').addEventListener('click', () => ContentPane.onReject());
    document.getElementById('tb-iterate').addEventListener('click', () => ContentPane.onIterate());
  };

  ContentPane.onAccept = async function () {
    if (!TB.pendingProposal) return;
    try {
      await TB.api.accept(TB.tale.id, TB.pendingProposal.request_id);
      toast('success', 'Accepted');
      TB.pendingProposal = null;
      await TB.refreshConcepts();
      ContentPane.render();
      if (TB.OrgPane) TB.OrgPane.render();
      if (TB.Assistant) TB.Assistant.reload();
    } catch (err) {
      toast('error', 'Accept failed: ' + err.message);
    }
  };

  ContentPane.onReject = async function () {
    if (!TB.pendingProposal) return;
    try {
      await TB.api.reject(TB.tale.id, TB.pendingProposal.request_id);
      toast('info', 'Rejected');
      TB.pendingProposal = null;
      ContentPane.render();
      if (TB.Assistant) TB.Assistant.reload();
    } catch (err) {
      toast('error', 'Reject failed: ' + err.message);
    }
  };

  ContentPane.onIterate = async function () {
    if (!TB.pendingProposal) return;
    const feedback = prompt('What should change in the next attempt?');
    if (feedback === null) return;
    const rid = TB.pendingProposal.request_id;
    TB.pendingProposal = null;
    try {
      const res = await TB.api.iterate(TB.tale.id, rid, feedback);
      if (TB.Assistant) TB.Assistant.handleResult(res);
    } catch (err) {
      toast('error', 'Iterate failed: ' + err.message);
    }
  };

  window.TB = window.TB || {};
  window.TB.ContentPane = ContentPane;
})();
