// Generate tab — workflow picker, dynamic param form, job submission + polling.

let _workflows = [];     // [{name, filename, params}]
let _activeParams = [];  // params for currently selected workflow
let _pollTimer = null;
let _currentJobId = null;

function initGenerateTab() {
  loadWorkflowList();
}

async function loadWorkflowList() {
  try {
    const data = await api('/comfyui/workflows');
    _workflows = data.workflows || [];
    const sel = document.getElementById('gen-workflow');
    // Preserve current selection
    const prev = sel.value;
    sel.innerHTML = '<option value="">— select a workflow —</option>';
    _workflows.forEach(w => {
      const opt = document.createElement('option');
      opt.value = w.name;
      opt.textContent = w.name;
      sel.appendChild(opt);
    });
    if (prev && _workflows.find(w => w.name === prev)) {
      sel.value = prev;
    }
    const submitBtn = document.getElementById('gen-submit');
    if (submitBtn) submitBtn.disabled = !sel.value;
  } catch (_) {}
}

function onWorkflowChange() {
  const sel = document.getElementById('gen-workflow');
  const name = sel.value;
  const submitBtn = document.getElementById('gen-submit');
  if (submitBtn) submitBtn.disabled = !name;
  if (!name) { _buildParamForm([]); return; }
  const wf = _workflows.find(w => w.name === name);
  _activeParams = wf ? wf.params : [];
  _buildParamForm(_activeParams);
}

function _buildParamForm(params) {
  const container = document.getElementById('gen-params');
  container.innerHTML = '';
  params.forEach(p => {
    const label = document.createElement('label');
    label.textContent = p.label || p.name;

    let input;
    if (p.type === 'integer') {
      input = document.createElement('input');
      input.type = 'number';
      input.step = '1';
      input.value = p.default ?? '';
    } else if (p.type === 'float') {
      input = document.createElement('input');
      input.type = 'number';
      input.step = 'any';
      input.value = p.default ?? '';
    } else {
      // string — large text for prompts, small input for others
      const isPrompt = p.name === 'prompt' || p.name === 'negative_prompt';
      if (isPrompt) {
        input = document.createElement('textarea');
        input.rows = p.name === 'prompt' ? 4 : 2;
      } else {
        input = document.createElement('input');
        input.type = 'text';
      }
      input.value = p.default ?? '';
    }
    input.id = 'param-' + p.name;

    container.appendChild(label);
    container.appendChild(input);
  });
}

function _collectParams() {
  const result = {};
  _activeParams.forEach(p => {
    const el = document.getElementById('param-' + p.name);
    if (!el) return;
    const raw = el.value;
    if (p.type === 'integer') result[p.name] = parseInt(raw, 10) || 0;
    else if (p.type === 'float') result[p.name] = parseFloat(raw) || 0;
    else result[p.name] = raw;
  });
  return result;
}

async function submitGenerate() {
  const sel = document.getElementById('gen-workflow');
  const workflow = sel.value;
  if (!workflow) return;

  const statusEl = document.getElementById('gen-status');
  const imagesEl = document.getElementById('gen-images');
  imagesEl.innerHTML = '';
  statusEl.style.color = '#888';
  statusEl.textContent = 'Submitting…';

  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }

  try {
    const job = await api('/jobs/image', 'POST', { workflow, params: _collectParams() });
    _currentJobId = job.job_id;
    statusEl.textContent = 'Job ' + job.job_id + ' — queued';
    _pollTimer = setInterval(() => _pollJob(_currentJobId), 800);
  } catch (e) {
    statusEl.style.color = '#c44';
    statusEl.textContent = 'Error: ' + e.message;
  }
}

async function _pollJob(jobId) {
  try {
    const job = await api('/jobs/' + jobId);
    const statusEl = document.getElementById('gen-status');
    const imagesEl = document.getElementById('gen-images');

    if (job.status === 'done') {
      clearInterval(_pollTimer); _pollTimer = null;
      statusEl.style.color = '#2a6';
      statusEl.textContent = 'Done';
      // Fetch artifacts to find image filenames
      try {
        const artifactsResp = await fetch('/v1/jobs/' + jobId + '/files/artifacts.json');
        if (artifactsResp.ok) {
          const artifacts = await artifactsResp.json();
          imagesEl.innerHTML = '';
          artifacts.forEach(a => {
            if (/\.(png|jpg|jpeg|webp|gif)$/i.test(a.filename)) {
              const img = document.createElement('img');
              img.src = '/v1/jobs/' + jobId + '/files/' + encodeURIComponent(a.filename);
              img.alt = a.filename;
              img.title = a.filename;
              imagesEl.appendChild(img);
            }
          });
        }
      } catch (_) {}
    } else if (job.status === 'error') {
      clearInterval(_pollTimer); _pollTimer = null;
      statusEl.style.color = '#c44';
      statusEl.textContent = 'Error: ' + (job.error || 'unknown');
    } else {
      statusEl.style.color = '#fa0';
      statusEl.textContent = 'Job ' + jobId + ' — ' + job.status;
    }
  } catch (_) {}
}
