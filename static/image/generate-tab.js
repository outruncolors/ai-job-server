// Generate tab — workflow picker, prompt input, job submission + polling.

let _workflows = [];  // [{name, filename, valid, promptNodeId, error}]
let _pollTimer = null;
let _currentJobId = null;
const _recreateId = sessionStorage.getItem('recreate_job_id');
if (_recreateId) sessionStorage.removeItem('recreate_job_id');

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
  if (_recreateId) _hydrateFromRecreate(_recreateId);
}

async function _hydrateFromRecreate(jobId) {
  const notice = document.getElementById('recreate-notice');
  let req;
  try {
    const r = await fetch('/v1/jobs/' + jobId + '/files/request.json');
    if (!r.ok) {
      notice.textContent = 'Could not load original request (job not found).';
      notice.style.display = 'block';
      return;
    }
    const data = await r.json();
    req = data.requested;
  } catch(e) {
    notice.textContent = 'Could not load original request: ' + e.message;
    notice.style.display = 'block';
    return;
  }

  const missing = [];

  if (req.workflow) {
    document.getElementById('gen-workflow').value = req.workflow;
    const wf = _workflows.find(w => w.name === req.workflow);
    if (!wf) {
      missing.push('workflow "' + req.workflow + '"');
    }
    onWorkflowChange();
  }

  if (req.prompt != null) {
    document.getElementById('gen-prompt').value = req.prompt;
  }

  if (missing.length > 0) {
    notice.innerHTML = 'Recreate notice — these references no longer exist:<br>· ' +
      missing.map(m => String(m).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')).join('<br>· ');
    notice.style.display = 'block';
  }
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

  const prompt = await resolveWildcards((document.getElementById('gen-prompt').value || '').trim());
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
