/* Debug panel — request list + a full per-request trace inspector. */
(function () {
  const D = {};
  let showResolved = true;

  function drawer() {
    return document.getElementById('tb-debug');
  }

  D.toggle = async function () {
    const d = drawer();
    d.hidden = !d.hidden;
    if (!d.hidden) await D.loadList();
  };

  D.close = function () {
    drawer().hidden = true;
  };

  D.loadList = async function () {
    const list = document.getElementById('tb-debug-list');
    try {
      const data = await TB.api.requests(TB.tale.id);
      const reqs = data.requests || [];
      list.innerHTML = reqs.length
        ? reqs.map((r) => `
            <div class="tb-dbg-row" data-rid="${_escHtml(r.request_id)}">
              <span class="tb-dbg-mode">${_escHtml(r.mode || '')}</span>
              <span class="tb-dbg-action ${_escHtml(r.user_action || '')}">${_escHtml(r.user_action || '')}</span>
              ${r.error ? '<span class="tb-dbg-err">error</span>' : ''}
              <span class="tb-dbg-rid">${_escHtml(r.request_id)}</span>
            </div>`).join('')
        : '<div class="tb-empty">no requests yet</div>';
      list.querySelectorAll('[data-rid]').forEach((el) =>
        el.addEventListener('click', () => D.open(el.getAttribute('data-rid')))
      );
    } catch (err) {
      list.innerHTML = `<div class="tb-empty">${_escHtml(err.message)}</div>`;
    }
  };

  D.open = async function (rid) {
    const d = drawer();
    if (d.hidden) {
      d.hidden = false;
      await D.loadList();
    }
    const detail = document.getElementById('tb-debug-detail');
    let t;
    try {
      t = await TB.api.requestDetail(TB.tale.id, rid);
    } catch (err) {
      detail.innerHTML = `<div class="tb-empty">${_escHtml(err.message)}</div>`;
      return;
    }
    const vars = t.resolved_variables || {};
    const varRows = Object.keys(vars)
      .filter((k) => (vars[k] || '').toString().trim() !== '')
      .map((k) => `<tr><td>${_escHtml(k)}</td><td>${_escHtml(String(vars[k]).slice(0, 200))}</td></tr>`)
      .join('');
    const toolCalls = (t.mcp_tool_calls || [])
      .map((c) => `<div class="tb-dbg-tool">${_escHtml(c.tool || c.name || '?')} ${c.error ? '⚠️' : '✓'}</div>`)
      .join('') || '<span class="tb-empty">none</span>';
    const prompt = showResolved ? (t.resolved_prompt || '') : (t.unresolved_template || '');
    const proposal = t.proposal || {};

    detail.innerHTML = `
      <div class="tb-dbg-detail">
        <div class="tb-dbg-meta">
          <b>${_escHtml(t.mode || '')}</b> · action: ${_escHtml(t.user_action || '')}
          ${t.iterate_of ? `· iterate of ${_escHtml(t.iterate_of)}` : ''}
          ${t.error ? `· <span class="tb-dbg-err">${_escHtml(t.error)}</span>` : ''}
          ${t.job_id ? `· job ${_escHtml(t.job_id)}` : ''}
        </div>

        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">Prompt
            <button id="tb-dbg-toggle-prompt" class="tb-mini">${showResolved ? 'show unresolved' : 'show resolved'}</button>
          </div>
          <pre class="tb-dbg-pre">${_escHtml(prompt)}</pre>
        </div>

        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">Populated variables</div>
          <table class="tb-dbg-vars">${varRows || '<tr><td>(none)</td></tr>'}</table>
        </div>

        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">Context concepts</div>
          <div>${(t.context_concept_ids || []).map((c) => _escHtml(c)).join(', ') || '<span class="tb-empty">none</span>'}</div>
        </div>

        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">MCP tool / resource calls</div>
          ${toolCalls}
        </div>

        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">Model output</div>
          <pre class="tb-dbg-pre">${_escHtml(t.raw_model_output || '')}</pre>
        </div>

        ${proposal.after !== undefined ? `
        <div class="tb-dbg-sec">
          <div class="tb-dbg-h">Applied diff (before → after)</div>
          <pre class="tb-dbg-pre tb-del">${_escHtml(proposal.before || '')}</pre>
          <pre class="tb-dbg-pre tb-ins">${_escHtml(proposal.after || '')}</pre>
        </div>` : ''}
      </div>`;

    const tgl = document.getElementById('tb-dbg-toggle-prompt');
    if (tgl) tgl.addEventListener('click', () => { showResolved = !showResolved; D.open(rid); });
  };

  window.TB = window.TB || {};
  window.TB.Debug = D;
})();
