// Shared, page-agnostic output console: a resizable terminal pinned to the
// bottom of a generator page's right panel that tails one job's logs.txt.
//
// Usage (one line per page, idempotent — create() restructures the panel once):
//   OutputConsole.create(panelEl, { pageKey: 'chain' }).start(jobId);
//   con.stop();   // optional — start() auto-stops on done/error
//
// `panelEl` is the page's #panel-right (passed by reference, since some pages
// have several). On create() the panel's existing children are wrapped in a
// `.pr-scroll` (flex:1, scrolls) and a drag handle + console are appended below;
// the panel itself becomes a flex column. All page content is referenced by id,
// so moving it into .pr-scroll is transparent.
(function (global) {
  'use strict';

  const MIN_H = 90;      // px — smallest console height
  const MAX_FRAC = 0.6;  // largest as a fraction of the panel height
  const POLL_MS = 1000;

  function _clamp(host, h) {
    const max = Math.max(MIN_H, host.clientHeight * MAX_FRAC);
    return Math.min(Math.max(h, MIN_H), max);
  }

  function create(host, opts) {
    if (!host) return null;
    if (host.__oc) return host.__oc;
    opts = opts || {};
    const pageKey = opts.pageKey || 'default';
    const HKEY = 'oc-height:' + pageKey;
    const CKEY = 'oc-collapsed:' + pageKey;

    // ── restructure the panel once ──
    const scroll = document.createElement('div');
    scroll.className = 'pr-scroll';
    while (host.firstChild) scroll.appendChild(host.firstChild);
    host.appendChild(scroll);
    host.classList.add('oc-host');
    // Inline so we win over the `#panel-right { overflow-y:auto; flex:1 }` ID
    // rule (id > class specificity) — the panel must be a non-scrolling flex
    // column so .pr-scroll scrolls and the console stays pinned to the bottom.
    host.style.display = 'flex';
    host.style.flexDirection = 'column';
    host.style.overflow = 'hidden';

    const handle = document.createElement('div');
    handle.className = 'oc-handle';
    handle.title = 'Drag to resize';

    const con = document.createElement('section');
    con.className = 'oc';

    const dot = document.createElement('span');
    dot.className = 'oc-dot';
    const label = document.createElement('span');
    label.className = 'oc-label';
    label.textContent = 'console';
    const spacer = document.createElement('span');
    spacer.className = 'oc-spacer';
    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.className = 'oc-btn';
    clearBtn.textContent = 'Clear';
    const collapseBtn = document.createElement('button');
    collapseBtn.type = 'button';
    collapseBtn.className = 'oc-btn';

    const header = document.createElement('div');
    header.className = 'oc-header';
    header.append(dot, label, spacer, clearBtn, collapseBtn);

    const body = document.createElement('pre');
    body.className = 'oc-body';

    con.append(header, body);
    host.append(handle, con);

    const storedH = parseInt(global.localStorage.getItem(HKEY) || '', 10);
    con.style.height = (storedH > 0 ? storedH : 180) + 'px';
    let collapsed = global.localStorage.getItem(CKEY) === '1';

    const inst = {
      host: host,
      _jobId: null,
      _timer: null,
      _shownLen: 0,
    };

    function showChrome(show) {
      con.style.display = show ? '' : 'none';
      handle.style.display = show && !collapsed ? '' : 'none';
    }
    function applyCollapsed() {
      con.classList.toggle('oc-collapsed', collapsed);
      collapseBtn.textContent = collapsed ? '▸' : '▾';
      handle.style.display = collapsed ? 'none' : '';
    }
    applyCollapsed();
    showChrome(false);  // hidden until first start()

    collapseBtn.addEventListener('click', function () {
      collapsed = !collapsed;
      global.localStorage.setItem(CKEY, collapsed ? '1' : '0');
      applyCollapsed();
    });
    clearBtn.addEventListener('click', function () { body.textContent = ''; });

    // ── drag to resize (pointer events, not HTML5 DnD) ──
    let dragY = 0, dragH = 0, dragging = false;
    handle.addEventListener('pointerdown', function (e) {
      dragging = true; dragY = e.clientY; dragH = con.offsetHeight;
      handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    handle.addEventListener('pointermove', function (e) {
      if (!dragging) return;
      con.style.height = _clamp(host, dragH + (dragY - e.clientY)) + 'px';  // up = taller
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      try { handle.releasePointerCapture(e.pointerId); } catch (_) {}
      global.localStorage.setItem(HKEY, String(con.offsetHeight));
    }
    handle.addEventListener('pointerup', endDrag);
    handle.addEventListener('pointercancel', endDrag);

    // ── tail logic ──
    function atBottom() {
      return body.scrollTop + body.clientHeight >= body.scrollHeight - 6;
    }
    function setStatus(s) {
      dot.className = 'oc-dot oc-dot-' + (s || 'queued');
      const id = inst._jobId ? inst._jobId.slice(0, 8) + '… ' : '';
      label.textContent = 'console — ' + id + (s || '');
    }
    async function tick() {
      const jobId = inst._jobId;
      if (!jobId) return;
      let stop = false;
      try {
        const sr = await fetch('/v1/jobs/' + jobId);
        if (sr.ok) {
          const j = await sr.json();
          setStatus(j.status);
          stop = j.status === 'done' || j.status === 'error' || j.status === 'failed';
        }
      } catch (_) { /* keep polling */ }
      try {
        const lr = await fetch('/v1/jobs/' + jobId + '/files/logs.txt');
        if (lr.ok) {
          const text = await lr.text();
          if (text.length > inst._shownLen) {
            const chunk = text.slice(inst._shownLen);
            inst._shownLen = text.length;
            const wasBottom = atBottom();
            body.appendChild(document.createTextNode(chunk));
            if (wasBottom) body.scrollTop = body.scrollHeight;
          }
        }
      } catch (_) { /* keep polling */ }
      if (stop && inst._jobId === jobId) inst.stop();
    }

    inst.start = function (jobId) {
      this.stop();
      this._jobId = jobId;
      this._shownLen = 0;
      body.textContent = '';
      showChrome(true);
      setStatus('queued');
      tick();
      this._timer = global.setInterval(tick, POLL_MS);
      return this;
    };
    inst.stop = function () {
      if (this._timer) { global.clearInterval(this._timer); this._timer = null; }
      return this;
    };

    host.__oc = inst;
    return inst;
  }

  global.OutputConsole = { create: create };
})(window);
