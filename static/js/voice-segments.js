// voice-segments.js — shared segment list widget
// Globals: vsAddSegment(container, text?, delayMs?), vsRemoveSegment(id, container), vsCollectSegments(container)

(function () {
  let _counter = 0;

  window.vsAddSegment = function (container, text, delayMs) {
    text = text || '';
    delayMs = (delayMs === undefined) ? 500 : delayMs;
    const id = 'vs-' + (_counter++);
    const el = document.createElement('div');
    el.className = 'seg-row'; el.id = id;
    el.innerHTML =
      '<div class="seg-row-head">' +
        '<span class="seg-label"></span>' +
        '<button type="button" class="seg-remove-btn secondary">×</button>' +
      '</div>' +
      '<textarea class="seg-text" placeholder="Text for this segment…"></textarea>' +
      '<div class="seg-delay-row">' +
        '<label class="seg-delay-label">Silence after (ms):</label>' +
        '<input type="number" class="seg-delay" min="0" max="30000" step="100" value="' + delayMs + '">' +
        '<span class="seg-delay-note"></span>' +
      '</div>';
    el.querySelector('.seg-text').value = text;
    el.querySelector('.seg-remove-btn').addEventListener('click', function () {
      window.vsRemoveSegment(id, container);
    });
    container.appendChild(el);
    _vsRenumber(container);
  };

  window.vsRemoveSegment = function (id, container) {
    if (container.querySelectorAll('.seg-row').length <= 1) return;
    const el = document.getElementById(id);
    if (el) { el.remove(); _vsRenumber(container); }
  };

  window.vsCollectSegments = function (container) {
    const segs = [];
    container.querySelectorAll('.seg-row').forEach(function (row) {
      const text = row.querySelector('.seg-text').value.trim();
      const delay_ms = parseInt(row.querySelector('.seg-delay').value) || 0;
      if (text) segs.push({ text: text, delay_ms: delay_ms });
    });
    return segs;
  };

  function _vsRenumber(container) {
    const rows = Array.from(container.querySelectorAll('.seg-row'));
    rows.forEach(function (row, i) {
      row.querySelector('.seg-label').textContent = 'Segment ' + (i + 1);
      const isLast = i === rows.length - 1;
      const delayRow = row.querySelector('.seg-delay-row');
      delayRow.style.opacity = isLast ? '0.3' : '1';
      row.querySelector('.seg-delay').disabled = isLast;
      row.querySelector('.seg-delay-note').textContent = isLast
        ? 'no trailing silence on last segment'
        : 'silence before next segment';
      row.querySelector('.seg-remove-btn').style.visibility = rows.length === 1 ? 'hidden' : '';
    });
  }
})();
