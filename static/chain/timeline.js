// Timeline component for the chain page.
//
// Consumes SSE events emitted by GET /v1/jobs/{id}/stream and renders a
// vertical stream of "nodes" — one per chain event (input, streaming LLM
// output, audio, image, summary, goto, error, done).
//
// Public API:
//   const tl = createTimeline(rootEl);
//   tl.reset();
//   tl.handleEvent('llm_chunk', payload);
//   tl.attach(eventSource);   // subscribes to the well-known event names
//   tl.destroy();
//
// Self-contained — relies only on document and a global _escHtml() (defined
// in chain.js); falls back to a local escape if that's not available.

(function () {
  'use strict';

  const EVENT_TYPES = [
    'job_start', 'step_start', 'step_input', 'llm_chunk', 'artifact_ready',
    'summary', 'goto', 'step_done', 'step_error', 'job_done',
  ];

  function _esc(s) {
    if (typeof window._escHtml === 'function') return window._escHtml(String(s == null ? '' : s));
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function _typeLabel(stepType) {
    return ({
      llm: 'llm',
      voice: 'voice',
      image_prompt: 'image-prompt',
      write_context: 'context',
      save_wildcard: 'wildcard',
      create_ticket: 'ticket',
      goto: 'goto',
      sequence: 'sequence',
    })[stepType] || stepType || '';
  }

  function _key(step_number, invocation, kind) {
    return `${step_number}:${invocation || 0}:${kind}`;
  }

  function createTimeline(rootEl) {
    if (!rootEl) throw new Error('createTimeline requires a root element');

    // Per-job state — reset() wipes this.
    let nodes = new Map();          // key → { el, body, header, status }
    let stepMeta = new Map();       // step:inv → { name, type }
    let currentLlm = null;          // pointer to the active streaming pre
    let userScrolledUp = false;
    let lastSeq = 0;
    let attachedSource = null;

    function _onScroll() {
      const slack = 100;
      userScrolledUp =
        rootEl.scrollHeight - rootEl.scrollTop - rootEl.clientHeight > slack;
    }
    rootEl.addEventListener('scroll', _onScroll);

    function _scrollToBottom() {
      if (!userScrolledUp) rootEl.scrollTop = rootEl.scrollHeight;
    }

    function _makeNode(klass, headerHtml, bodyHtml) {
      const wrap = document.createElement('div');
      wrap.className = 'tl-node ' + klass;
      const head = document.createElement('div');
      head.className = 'tl-node-head';
      head.innerHTML = headerHtml;
      wrap.appendChild(head);
      const body = document.createElement('div');
      body.className = 'tl-node-body';
      if (bodyHtml != null) body.innerHTML = bodyHtml;
      wrap.appendChild(body);
      return { wrap, head, body };
    }

    function _setStatus(rec, label, kind) {
      if (!rec || !rec.head) return;
      let badge = rec.head.querySelector('.tl-status');
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'tl-status';
        rec.head.appendChild(badge);
      }
      badge.textContent = label || '';
      badge.dataset.kind = kind || '';
    }

    function reset() {
      nodes.clear();
      stepMeta.clear();
      currentLlm = null;
      lastSeq = 0;
      userScrolledUp = false;
      rootEl.innerHTML = '';
      if (attachedSource && attachedSource.readyState !== 2) {
        try { attachedSource.close(); } catch (_) {}
      }
      attachedSource = null;
    }

    function _onJobStart(p) {
      const { wrap } = _makeNode(
        'tl-node-meta tl-node-job-start',
        `<span class="tl-step">Job</span> <span class="tl-type">${_esc(p.step_count)} steps</span>`,
        '',
      );
      rootEl.appendChild(wrap);
      _scrollToBottom();
    }

    function _onStepStart(p) {
      const sk = `${p.step_number}:${p.invocation || 0}`;
      stepMeta.set(sk, { name: p.name, type: p.step_type || '', alt_index: p.alt_index });
      // The actual input node is appended on step_input — step_start is
      // bookkeeping. We do nothing here to keep the timeline tidy.
    }

    function _onStepInput(p) {
      const sk = `${p.step_number}:${p.invocation || 0}`;
      const meta = stepMeta.get(sk) || { name: '', type: '' };
      const key = _key(p.step_number, p.invocation, 'input');
      if (nodes.has(key)) return;
      const header =
        `<span class="tl-step">Step ${_esc(p.step_number)}</span>` +
        ` · <span class="tl-type">${_esc(_typeLabel(meta.type))}</span>` +
        ` · <span class="tl-label">${_esc(meta.name || 'input')}</span>`;
      const ctx = p.context
        ? `<details class="tl-context"><summary>context</summary><pre class="tl-pre">${_esc(p.context)}</pre></details>`
        : '';
      const body =
        ctx +
        (p.rendered_prompt
          ? `<pre class="tl-pre">${_esc(p.rendered_prompt)}</pre>`
          : '');
      const rec = _makeNode('tl-node-input', header, body);
      nodes.set(key, rec);
      rootEl.appendChild(rec.wrap);
      _scrollToBottom();
    }

    function _onLlmChunk(p) {
      const key = _key(p.step_number, p.invocation, 'llm_output');
      let rec = nodes.get(key);
      if (!rec) {
        const sk = `${p.step_number}:${p.invocation || 0}`;
        const meta = stepMeta.get(sk) || { name: '', type: 'llm' };
        const header =
          `<span class="tl-step">Step ${_esc(p.step_number)}</span>` +
          ` · <span class="tl-type">${_esc(_typeLabel(meta.type) || 'llm')}</span>` +
          ` · <span class="tl-label">output</span>`;
        rec = _makeNode('tl-node-llm-output streaming', header, '');
        const pre = document.createElement('pre');
        pre.className = 'tl-pre tl-streaming';
        rec.body.appendChild(pre);
        rec.pre = pre;
        nodes.set(key, rec);
        rootEl.appendChild(rec.wrap);
        _setStatus(rec, 'streaming…', 'streaming');
        currentLlm = rec;
      }
      if (p.delta) rec.pre.appendChild(document.createTextNode(p.delta));
      _scrollToBottom();
    }

    function _onArtifactReady(p) {
      const kind = p.kind || 'file';
      const key = _key(p.step_number, p.invocation, 'artifact:' + (p.filename || kind));
      const sk = `${p.step_number}:${p.invocation || 0}`;
      const meta = stepMeta.get(sk) || { name: '', type: '' };
      const header =
        `<span class="tl-step">Step ${_esc(p.step_number)}</span>` +
        ` · <span class="tl-type">${_esc(_typeLabel(meta.type))}</span>` +
        ` · <span class="tl-label">${_esc(p.filename || kind)}</span>`;
      let body = '';
      if (kind === 'audio') {
        body = `<audio class="tl-audio" controls preload="none" src="${_esc(p.file_url)}"></audio>`;
      } else if (kind === 'image') {
        body =
          `<a href="${_esc(p.file_url)}" target="_blank" rel="noopener">` +
          `<img class="tl-image" src="${_esc(p.file_url)}" alt=""></a>`;
      } else {
        body =
          `<a class="tl-file-link" href="${_esc(p.file_url)}" target="_blank" rel="noopener">` +
          `${_esc(p.filename || 'file')}</a>`;
      }
      const rec = _makeNode('tl-node-artifact tl-node-artifact-' + kind, header, body);
      nodes.set(key, rec);
      rootEl.appendChild(rec.wrap);
      _scrollToBottom();
    }

    function _onSummary(p) {
      const key = _key(p.step_number, p.invocation, 'summary:' + (p.kind || 's'));
      const sk = `${p.step_number}:${p.invocation || 0}`;
      const meta = stepMeta.get(sk) || { name: '', type: '' };
      const header =
        `<span class="tl-step">Step ${_esc(p.step_number)}</span>` +
        ` · <span class="tl-type">${_esc(_typeLabel(meta.type))}</span>` +
        ` · <span class="tl-label">${_esc(p.summary || '')}</span>`;
      const detail = p.detail
        ? `<details class="tl-detail"><summary>details</summary><pre class="tl-pre tl-pre-mono">${_esc(JSON.stringify(p.detail, null, 2))}</pre></details>`
        : '';
      const rec = _makeNode('tl-node-summary', header, detail);
      nodes.set(key, rec);
      rootEl.appendChild(rec.wrap);
      _scrollToBottom();
    }

    function _onGoto(p) {
      const arrow = p.fall_through
        ? '→ fall_through'
        : `→ jump to step ${_esc(p.target_step)}`;
      const header =
        `<span class="tl-step">Step ${_esc(p.from_step)}</span>` +
        ` · <span class="tl-type">goto</span>` +
        ` · <span class="tl-label">${arrow}</span>`;
      const rec = _makeNode('tl-node-goto', header, '');
      rootEl.appendChild(rec.wrap);
      _scrollToBottom();
    }

    function _onStepDone(p) {
      // For LLM steps, replace the streamed pre with full_text if the
      // server included it (handles any chunk-loss case).
      if (p.full_text != null) {
        const out = nodes.get(_key(p.step_number, p.invocation, 'llm_output'));
        if (out && out.pre) {
          if (out.pre.textContent !== p.full_text) {
            out.pre.textContent = p.full_text;
          }
          out.pre.classList.remove('tl-streaming');
          out.wrap.classList.remove('streaming');
        }
      }
      // Flip status badges on whichever node(s) we have for this step.
      for (const kind of ['input', 'llm_output']) {
        const r = nodes.get(_key(p.step_number, p.invocation, kind));
        if (r) _setStatus(r, '✓', 'done');
      }
      currentLlm = null;
    }

    function _onStepError(p) {
      const errBody = `<pre class="tl-pre tl-error-text">${_esc(p.error || 'error')}</pre>`;
      const header =
        `<span class="tl-step">Step ${_esc(p.step_number)}</span>` +
        ` · <span class="tl-type">error</span>`;
      const rec = _makeNode('tl-node-error', header, errBody);
      rootEl.appendChild(rec.wrap);
      // Also tag prior nodes for this step as error.
      for (const kind of ['input', 'llm_output']) {
        const r = nodes.get(_key(p.step_number, p.invocation, kind));
        if (r) {
          r.wrap.classList.add('tl-node-error');
          _setStatus(r, 'error', 'error');
        }
      }
      _scrollToBottom();
    }

    function _onJobDone(p) {
      const status = p.status || 'done';
      const klass = status === 'done' ? 'tl-node-done' : 'tl-node-error';
      let label = status === 'done' ? '✓ done' : '✗ error';
      if (p.duration_ms) label += ` · ${(p.duration_ms / 1000).toFixed(1)}s`;
      const header = `<span class="tl-step">Job</span> · <span class="tl-label">${label}</span>`;
      const body = (p.error)
        ? `<pre class="tl-pre tl-error-text">${_esc(p.error)}</pre>`
        : '';
      const rec = _makeNode('tl-node-job-done ' + klass, header, body);
      rootEl.appendChild(rec.wrap);
      _scrollToBottom();
      if (attachedSource) {
        try { attachedSource.close(); } catch (_) {}
        attachedSource = null;
      }
    }

    function handleEvent(type, payload) {
      // Dedup by seq.
      if (payload && typeof payload.seq === 'number') {
        if (payload.seq <= lastSeq) return;
        lastSeq = payload.seq;
      }
      switch (type) {
        case 'job_start':    return _onJobStart(payload || {});
        case 'step_start':   return _onStepStart(payload || {});
        case 'step_input':   return _onStepInput(payload || {});
        case 'llm_chunk':    return _onLlmChunk(payload || {});
        case 'artifact_ready': return _onArtifactReady(payload || {});
        case 'summary':      return _onSummary(payload || {});
        case 'goto':         return _onGoto(payload || {});
        case 'step_done':    return _onStepDone(payload || {});
        case 'step_error':   return _onStepError(payload || {});
        case 'job_done':     return _onJobDone(payload || {});
      }
    }

    function attach(eventSource) {
      attachedSource = eventSource;
      for (const t of EVENT_TYPES) {
        eventSource.addEventListener(t, (e) => {
          let p = {};
          try { p = JSON.parse(e.data); } catch (_) {}
          handleEvent(t, p);
        });
      }
    }

    function destroy() {
      reset();
      rootEl.removeEventListener('scroll', _onScroll);
    }

    return { reset, handleEvent, attach, destroy };
  }

  // Export to the window so chain.js can pick it up.
  window.createTimeline = createTimeline;
})();
