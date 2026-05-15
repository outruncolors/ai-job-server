
// ── State ─────────────────────────────────────────────────────────────────────

let _ticks     = [];
let _sequences = [];
let _editingId = null;
let _schedMode = 'interval'; // 'interval' | 'cron'

// ── Data loading ──────────────────────────────────────────────────────────────

async function _loadAll() {
  try {
    const [td, sd] = await Promise.all([api('/ticks'), api('/chain-sequences')]);
    _ticks     = td.ticks || [];
    _sequences = sd.sequences || [];
    _renderList();
    _populateSeqDropdown();
  } catch (e) {
    setMsg('Failed to load: ' + e.message, '#e44');
  }
}

function _populateSeqDropdown() {
  const sel = document.getElementById('f-sequence');
  const prev = sel.value;
  while (sel.options.length > 1) sel.remove(1);
  for (const s of _sequences) {
    const opt = document.createElement('option');
    opt.value = s.id;
    opt.textContent = s.name;
    sel.appendChild(opt);
  }
  if (prev) sel.value = prev;
}

// ── List rendering ────────────────────────────────────────────────────────────

function _renderList() {
  const list  = document.getElementById('tick-list');
  const empty = document.getElementById('tick-empty');
  if (!_ticks.length) {
    empty.style.display = '';
    list.innerHTML = '';
    list.appendChild(empty);
    return;
  }
  list.innerHTML = '';
  for (const t of _ticks) {
    const isSelected = t.id === _editingId;
    const isEnabled  = t.enabled !== false;
    const div = document.createElement('div');
    div.className = 'tick-item' + (isSelected ? ' selected' : '') + (!isEnabled ? ' disabled' : '');
    div.onclick = () => editTick(t.id);

    const seq  = _sequences.find(s => s.id === t.sequence_id);
    const sub  = seq ? seq.name : '(missing sequence)';
    const sched = _schedSummary(t.schedule);
    const next  = t.next_fire_at ? 'next: ' + _relTime(t.next_fire_at) : '';
    const skipNote = t.last_skip_reason
      ? '<div style="font-size:0.66rem;color:#e44;margin-top:2px;">skipped: ' + _escHtml(t.last_skip_reason) + '</div>'
      : '';

    div.innerHTML =
      '<div class="tick-item-row">' +
        '<div class="tick-item-info">' +
          '<div class="tick-name">' + _escHtml(t.name) + '</div>' +
          '<div class="tick-sub">' + _escHtml(sub) + ' · ' + _escHtml(sched) + '</div>' +
          (next ? '<div class="tick-next">' + _escHtml(next) + '</div>' : '') +
          skipNote +
        '</div>' +
        '<button class="tick-fire-btn" title="Fire now" onclick="fireTick(event, \'' + t.id + '\')">▶</button>' +
      '</div>';
    list.appendChild(div);
  }
}

function _schedSummary(sched) {
  if (!sched) return '';
  if (sched.kind === 'interval' && sched.interval_unit) {
    const n = sched.interval_count || 1;
    const u = sched.interval_unit;
    let s = 'every ' + (n === 1 ? '' : n + ' ') + u + (n > 1 ? 's' : '');
    if (sched.interval_anchor && (u === 'day' || u === 'week')) s += ' at ' + sched.interval_anchor;
    return s;
  }
  return sched.cron || '';
}

function _relTime(iso) {
  const d    = new Date(iso);
  const diff = (d - Date.now()) / 1000;
  if (diff < 0)   return 'overdue';
  if (diff < 60)  return Math.round(diff) + 's';
  if (diff < 3600) return Math.round(diff / 60) + 'm';
  if (diff < 86400) return Math.round(diff / 3600) + 'h';
  return Math.round(diff / 86400) + 'd';
}

// ── Form ──────────────────────────────────────────────────────────────────────

function newTick() {
  _editingId = null;
  document.getElementById('form-heading').textContent = 'New Tick';
  document.getElementById('f-name').value       = '';
  document.getElementById('f-sequence').value   = '';
  document.getElementById('f-interval-count').value = '1';
  document.getElementById('f-interval-unit').value  = 'day';
  document.getElementById('f-anchor').value     = '09:00';
  document.getElementById('f-cron').value       = '';
  document.getElementById('f-enabled').checked  = true;
  document.getElementById('btn-delete').style.display = 'none';
  document.getElementById('recent-jobs-section').style.display = 'none';
  _schedMode = 'interval';
  _applySchedMode();
  _updateAnchorVisibility();
  setMsg('', '');
  _renderList();
}

function editTick(id) {
  const t = _ticks.find(x => x.id === id);
  if (!t) return;
  _editingId = id;
  document.getElementById('form-heading').textContent = 'Edit Tick';
  document.getElementById('f-name').value      = t.name || '';
  document.getElementById('f-sequence').value  = t.sequence_id || '';
  document.getElementById('f-enabled').checked = t.enabled !== false;
  document.getElementById('btn-delete').style.display = '';

  const sched = t.schedule || {};
  if (sched.kind === 'cron') {
    _schedMode = 'cron';
    document.getElementById('f-cron').value = sched.cron || '';
    previewCron();
  } else {
    _schedMode = 'interval';
    document.getElementById('f-interval-count').value = sched.interval_count || 1;
    document.getElementById('f-interval-unit').value  = sched.interval_unit  || 'day';
    document.getElementById('f-anchor').value         = sched.interval_anchor || '09:00';
  }
  _applySchedMode();
  _updateAnchorVisibility();
  setMsg('', '');
  _renderList();
  _loadRecentJobs(id);
}

function cancelForm() {
  newTick();
}

function toggleSchedMode() {
  _schedMode = _schedMode === 'interval' ? 'cron' : 'interval';
  _applySchedMode();
}

function _applySchedMode() {
  const isInterval = _schedMode === 'interval';
  document.getElementById('sched-interval').style.display = isInterval ? '' : 'none';
  document.getElementById('sched-cron').style.display     = isInterval ? 'none' : '';
  document.getElementById('sched-mode-btn').textContent   = isInterval ? 'cron mode' : 'interval mode';
}

function _updateAnchorVisibility() {
  const unit = document.getElementById('f-interval-unit').value;
  document.getElementById('anchor-row').style.display = (unit === 'day' || unit === 'week') ? '' : 'none';
}

document.getElementById('f-interval-unit').addEventListener('change', _updateAnchorVisibility);

function _buildSchedule() {
  if (_schedMode === 'cron') {
    return { cron: document.getElementById('f-cron').value.trim(), kind: 'cron' };
  }
  const count  = parseInt(document.getElementById('f-interval-count').value, 10) || 1;
  const unit   = document.getElementById('f-interval-unit').value;
  const anchor = document.getElementById('f-anchor').value;
  const cron   = _intervalToCron(count, unit, anchor);
  return {
    cron,
    kind: 'interval',
    interval_count:  count,
    interval_unit:   unit,
    interval_anchor: (unit === 'day' || unit === 'week') ? anchor : null,
  };
}

function _intervalToCron(count, unit, anchor) {
  const [hh, mm] = (anchor || '00:00').split(':').map(Number);
  switch (unit) {
    case 'minute': return count === 1 ? '* * * * *' : '*/' + count + ' * * * *';
    case 'hour':   return count === 1 ? '0 * * * *' : '0 */' + count + ' * * *';
    case 'day':    return mm + ' ' + hh + ' */' + count + ' * *';
    case 'week':   return mm + ' ' + hh + ' * * 0';
    default:       return '* * * * *';
  }
}

async function saveTick() {
  const name   = document.getElementById('f-name').value.trim();
  const seqId  = document.getElementById('f-sequence').value;
  if (!name)  { setMsg('Name required', '#e44'); return; }
  if (!seqId) { setMsg('Select a sequence', '#e44'); return; }

  const sched = _buildSchedule();
  if (!sched.cron) { setMsg('Schedule required', '#e44'); return; }

  const body = {
    name,
    sequence_id: seqId,
    schedule:    sched,
    enabled:     document.getElementById('f-enabled').checked,
  };
  if (_editingId) body.id = _editingId;

  setMsg('Saving…', '#777');
  try {
    const saved = await api('/ticks', 'POST', body);
    _editingId = saved.id;
    await _loadAll();
    setMsg('Saved.', '#2a6');
    document.getElementById('btn-delete').style.display = '';
    _loadRecentJobs(_editingId);
  } catch (e) {
    setMsg('Error: ' + e.message, '#e44');
  }
}

async function deleteTick() {
  if (!_editingId) return;
  const t = _ticks.find(x => x.id === _editingId);
  if (!t || !confirm('Delete tick "' + t.name + '"?')) return;
  try {
    await api('/ticks/' + _editingId, 'DELETE');
    _editingId = null;
    await _loadAll();
    newTick();
  } catch (e) {
    setMsg('Delete failed: ' + e.message, '#e44');
  }
}

async function fireTick(ev, id) {
  ev.stopPropagation();
  try {
    const r = await api('/ticks/' + id + '/fire', 'POST');
    if (r.fired) {
      await _loadAll();
      if (id === _editingId) _loadRecentJobs(id);
    } else {
      alert('Skipped: ' + (r.skip_reason || 'unknown'));
    }
  } catch (e) {
    alert('Fire failed: ' + e.message);
  }
}

// ── Cron preview ──────────────────────────────────────────────────────────────

let _cronPreviewTimer = null;

function previewCron() {
  clearTimeout(_cronPreviewTimer);
  _cronPreviewTimer = setTimeout(_doCronPreview, 500);
}

async function _doCronPreview() {
  const expr = document.getElementById('f-cron').value.trim();
  const el   = document.getElementById('cron-preview');
  if (!expr) { el.textContent = ''; return; }
  try {
    const r = await api('/ticks/preview', 'POST', { cron: expr });
    el.textContent = 'Next: ' + r.next.map(s => new Date(s).toLocaleString()).join(', ');
    el.style.color = '#555';
  } catch (e) {
    el.textContent = 'Invalid expression';
    el.style.color = '#e44';
  }
}

// ── Recent jobs ───────────────────────────────────────────────────────────────

async function _loadRecentJobs(tickId) {
  const section = document.getElementById('recent-jobs-section');
  const list    = document.getElementById('recent-jobs-list');
  section.style.display = '';
  list.innerHTML = '<div style="color:#444;font-size:0.76rem;">Loading…</div>';
  try {
    const data = await api('/ticks/' + tickId + '/recent-jobs?limit=8');
    const jobs = data.jobs || [];
    if (!jobs.length) {
      list.innerHTML = '<div style="color:#333;font-size:0.76rem;">No jobs fired yet.</div>';
      return;
    }
    list.innerHTML = jobs.map(j => {
      const d = new Date(j.created_at).toLocaleString();
      const st = j.status === 'done' ? 'done' : j.status === 'error' ? 'error' : j.status;
      return '<div class="recent-job">' +
        '<a href="/jobs?id=' + _escHtml(j.job_id) + '" target="_blank">' + _escHtml(j.job_id.slice(0, 8)) + '…</a>' +
        ' <span class="job-status job-status-' + _escHtml(st) + '">' + _escHtml(st) + '</span>' +
        ' <span style="color:#2a2a2a;">' + _escHtml(d) + '</span>' +
        '</div>';
    }).join('');
  } catch (e) {
    list.innerHTML = '<div style="color:#e44;font-size:0.76rem;">Failed: ' + _escHtml(e.message) + '</div>';
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

function setMsg(text, color) {
  const el = document.getElementById('form-msg');
  el.textContent = text;
  el.style.color  = color;
}

// ── Init ──────────────────────────────────────────────────────────────────────

_loadAll();
