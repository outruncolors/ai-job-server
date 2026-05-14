// Generate tab — workflow picker, prompt input, job submission + polling.

let _workflows = [];  // [{name, filename, valid, promptNodeId, error}]
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
      onWorkflowChange();
    }
  } catch (_) {}
}

function onWorkflowChange() {
  const sel = document.getElementById('gen-workflow');
  const name = sel.value;
  const submitBtn = document.getElementById('gen-submit');
  const errEl = document.getElementById('gen-workflow-error');
  if (!name) {
    submitBtn.disabled = true;
    errEl.style.display = 'none';
    return;
  }
  const wf = _workflows.find(w => w.name === name);
  if (wf && !wf.valid) {
    submitBtn.disabled = true;
    errEl.textContent = wf.error || 'Workflow is not compatible';
    errEl.style.display = '';
  } else {
    submitBtn.disabled = false;
    errEl.style.display = 'none';
  }
}

async function submitGenerate() {
  const sel = document.getElementById('gen-workflow');
  const workflow = sel.value;
  if (!workflow) return;

  const prompt = (document.getElementById('gen-prompt').value || '').trim();
  const statusEl = document.getElementById('gen-status');
  const imagesEl = document.getElementById('gen-images');
  imagesEl.innerHTML = '';
  statusEl.style.color = '#888';
  statusEl.textContent = 'Submitting…';

  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }

  try {
    const job = await api('/jobs/image', 'POST', { workflow, prompt });
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
