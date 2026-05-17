// Generate tab — workflow picker, prompt input, job submission + polling.

let _workflows = [];  // [{name, filename, valid, promptNodeId, error}]
let _savedPrompts = [];  // [{id, name, prompt, workflow, ...}]
let _pollHandle = null;
let _currentJobId = null;
const _recreateId = sessionStorage.getItem('recreate_job_id');
if (_recreateId) sessionStorage.removeItem('recreate_job_id');

function initGenerateTab() {
  loadWorkflowList();
  loadSavedPromptList();
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

async function loadSavedPromptList() {
  try {
    const data = await api('/image-prompts');
    _savedPrompts = data.prompts || [];
    const sel = document.getElementById('gen-prompt-load');
    if (!sel) return;
    sel.innerHTML = '<option value="">— load saved prompt —</option>';
    _savedPrompts.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      const tag = p.workflow ? ' (' + p.workflow + ')' : '';
      opt.textContent = p.name + tag;
      sel.appendChild(opt);
    });
  } catch (_) {}
}

function onLoadSavedPrompt() {
  const sel = document.getElementById('gen-prompt-load');
  const pid = sel.value;
  if (!pid) return;
  const p = _savedPrompts.find(x => x.id === pid);
  if (!p) return;
  document.getElementById('gen-prompt').value = p.prompt || '';
  if (p.workflow && _workflows.find(w => w.name === p.workflow)) {
    document.getElementById('gen-workflow').value = p.workflow;
    onWorkflowChange();
  }
  // Reset dropdown so the same prompt can be reloaded again later.
  sel.value = '';
}

async function savePromptDialog() {
  const promptText = (document.getElementById('gen-prompt').value || '').trim();
  if (!promptText) {
    const statusEl = document.getElementById('gen-status');
    statusEl.style.color = '#c44';
    statusEl.textContent = 'Nothing to save — prompt is empty.';
    return;
  }
  const workflow = document.getElementById('gen-workflow').value || null;
  const name = window.prompt('Name for this prompt?');
  if (name == null) return;
  const trimmedName = name.trim();
  if (!trimmedName) return;
  try {
    await api('/image-prompts', 'POST', {
      name: trimmedName,
      prompt: promptText,
      workflow: workflow,
    });
    await loadSavedPromptList();
    const statusEl = document.getElementById('gen-status');
    statusEl.style.color = '#2a6';
    statusEl.textContent = 'Saved prompt "' + trimmedName + '".';
  } catch (e) {
    const statusEl = document.getElementById('gen-status');
    statusEl.style.color = '#c44';
    statusEl.textContent = 'Save failed: ' + e.message;
  }
}

async function submitGenerate() {
  const sel = document.getElementById('gen-workflow');
  const workflow = sel.value;
  if (!workflow) return;

  const rawPrompt = (document.getElementById('gen-prompt').value || '').trim();
  const { resolved: prompt, substitutions } = await resolveWildcardsTracked(rawPrompt);
  const statusEl = document.getElementById('gen-status');
  const imagesEl = document.getElementById('gen-images');
  imagesEl.innerHTML = '';
  statusEl.style.color = '#888';
  statusEl.textContent = 'Submitting…';
  renderResolvedPrompt(
    document.getElementById('gen-resolved-prompt'),
    [{ resolved: prompt, substitutions }],
  );

  if (_pollHandle) { _pollHandle.stop(); _pollHandle = null; }

  try {
    const job = await api('/jobs/image', 'POST', { workflow, prompt });
    _currentJobId = job.job_id;
    statusEl.textContent = 'Job ' + job.job_id + ' — queued';
    _pollHandle = pollJob(_currentJobId, {
      intervalMs: 800,
      onUpdate(j) {
        const statusEl = document.getElementById('gen-status');
        statusEl.style.color = '#fa0';
        statusEl.textContent = 'Job ' + _currentJobId + ' — ' + j.status;
      },
      async onDone(j) {
        const statusEl = document.getElementById('gen-status');
        const imagesEl = document.getElementById('gen-images');
        statusEl.style.color = '#2a6';
        statusEl.textContent = 'Done';
        try {
          const artifactsResp = await fetch('/v1/jobs/' + _currentJobId + '/files/artifacts.json');
          if (artifactsResp.ok) {
            const artifacts = await artifactsResp.json();
            imagesEl.innerHTML = '';
            artifacts.forEach(a => {
              if (/\.(png|jpg|jpeg|webp|gif)$/i.test(a.filename)) {
                const img = document.createElement('img');
                img.src = '/v1/jobs/' + _currentJobId + '/files/' + encodeURIComponent(a.filename);
                img.alt = a.filename;
                img.title = a.filename;
                imagesEl.appendChild(img);
              }
            });
          }
        } catch (_) {}
      },
      onError(j) {
        const statusEl = document.getElementById('gen-status');
        statusEl.style.color = '#c44';
        statusEl.textContent = 'Error: ' + (j.error || 'unknown');
      }
    });
  } catch (e) {
    statusEl.style.color = '#c44';
    statusEl.textContent = 'Error: ' + e.message;
  }
}
