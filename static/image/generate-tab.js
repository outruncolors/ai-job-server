// Generate tab — workflow picker, prompt input, job submission + polling.

let _workflows = [];  // [{name, filename, valid, promptNodeId, imageParams, error}]
let _savedPrompts = [];  // [{id, name, prompt, workflow, ...}]
let _pollHandle = null;
let _currentJobId = null;
let _uploadedImageParams = {};  // { REF_IMAGE_1: 'man.png', ... } — keyed by node title
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

  const wfMeta = _workflows.find(w => w.name === req.workflow);

  // Restore Denoise + Seed if the workflow still exposes them (rows already
  // rendered by onWorkflowChange above).
  if (wfMeta && wfMeta.denoiseNodeId && req.denoise != null) {
    document.getElementById('gen-denoise').value = req.denoise;
  }
  if (wfMeta && wfMeta.seedNodeId) {
    const randCb = document.getElementById('gen-seed-randomize');
    if (req.randomize_seed) {
      randCb.checked = true;
    } else if (req.seed != null && req.seed !== '') {
      randCb.checked = false;
      onSeedRandomizeChange();
      document.getElementById('gen-seed').value = String(req.seed);
    }
    onSeedRandomizeChange();
  }

  const hadRefs = req.image_params && Object.keys(req.image_params).length > 0;
  const hasRefSlots = wfMeta && (wfMeta.imageParams || []).length > 0;
  const noteLines = [];
  if (missing.length > 0) {
    noteLines.push('Recreate notice — these references no longer exist:');
    missing.forEach(m => noteLines.push('· ' + m));
  }
  if (hadRefs || hasRefSlots) {
    if (noteLines.length > 0) noteLines.push('');
    noteLines.push('Reference images aren\'t restored on recreate — re-upload them above.');
  }
  if (noteLines.length > 0) {
    notice.innerHTML = noteLines
      .map(s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'))
      .join('<br>');
    notice.style.display = 'block';
  }
}

function onWorkflowChange() {
  const sel = document.getElementById('gen-workflow');
  const name = sel.value;
  const submitBtn = document.getElementById('gen-submit');
  const errEl = document.getElementById('gen-workflow-error');
  _uploadedImageParams = {};
  if (!name) {
    submitBtn.disabled = true;
    errEl.style.display = 'none';
    _renderImageParamFields([]);
    return;
  }
  const wf = _workflows.find(w => w.name === name);
  if (wf && !wf.valid) {
    submitBtn.disabled = true;
    errEl.textContent = wf.error || 'Workflow is not compatible';
    errEl.style.display = '';
    _renderImageParamFields([]);
    _renderSeedDenoiseFields(null);
  } else {
    submitBtn.disabled = false;
    errEl.style.display = 'none';
    _renderImageParamFields((wf && wf.imageParams) || []);
    _renderSeedDenoiseFields(wf || null);
  }
}

// Show/hide the Denoise + Seed rows based on whether the selected workflow
// exposes the corresponding titled node. Resets to defaults each switch.
function _renderSeedDenoiseFields(wf) {
  const denoiseRow = document.getElementById('gen-denoise-row');
  const seedRow = document.getElementById('gen-seed-row');

  const hasDenoise = !!(wf && wf.denoiseNodeId);
  denoiseRow.style.display = hasDenoise ? '' : 'none';
  if (hasDenoise) document.getElementById('gen-denoise').value = '';

  const hasSeed = !!(wf && wf.seedNodeId);
  seedRow.style.display = hasSeed ? '' : 'none';
  if (hasSeed) {
    document.getElementById('gen-seed').value = '';
    document.getElementById('gen-seed-used').textContent = '';
    // Default to randomize on.
    document.getElementById('gen-seed-randomize').checked = true;
    onSeedRandomizeChange();
  }
}

function onSeedRandomizeChange() {
  const rand = document.getElementById('gen-seed-randomize').checked;
  const seedInput = document.getElementById('gen-seed');
  seedInput.disabled = rand;
  if (rand) seedInput.value = '';
}

// After a run, read the concrete seed the job actually used out of its resolved
// workflow.json and surface it so a randomized result can be reproduced.
async function _showUsedSeed(jobId, workflowName) {
  const out = document.getElementById('gen-seed-used');
  if (!out) return;
  const wf = _workflows.find(w => w.name === workflowName);
  if (!wf || !wf.seedNodeId) { out.textContent = ''; return; }
  try {
    const r = await fetch('/v1/jobs/' + jobId + '/files/workflow.json');
    if (!r.ok) return;
    const resolved = await r.json();
    const node = resolved[wf.seedNodeId];
    const seed = node && node.inputs && node.inputs.value;
    if (seed == null) return;
    out.textContent = '';
    const label = document.createElement('span');
    label.textContent = 'seed used: ';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'seed-copy';
    btn.textContent = String(seed);
    btn.title = 'Click to reuse this seed';
    btn.onclick = () => {
      document.getElementById('gen-seed-randomize').checked = false;
      onSeedRandomizeChange();
      document.getElementById('gen-seed').value = String(seed);
    };
    out.appendChild(label);
    out.appendChild(btn);
  } catch (_) {}
}

function _renderImageParamFields(params) {
  const container = document.getElementById('gen-image-params');
  if (!container) return;
  container.innerHTML = '';
  params.forEach((p, idx) => {
    const row = document.createElement('div');
    row.className = 'image-param-row';

    const label = document.createElement('label');
    label.textContent = 'Reference image ' + (idx + 1) + ' (' + p.name + ')';

    const pickrow = document.createElement('div');
    pickrow.className = 'image-param-pickrow';

    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp';
    input.dataset.param = p.name;

    const paste = document.createElement('div');
    paste.className = 'image-param-paste';
    paste.tabIndex = 0;
    paste.dataset.param = p.name;
    paste.textContent = 'or click here and paste (Ctrl/Cmd+V)';

    const status = document.createElement('span');
    status.className = 'image-param-status';
    status.textContent = 'optional — leaves the workflow default in place';

    paste.addEventListener('focus', () => paste.classList.add('focused'));
    paste.addEventListener('blur', () => paste.classList.remove('focused'));
    paste.addEventListener('paste', (e) => _handlePastedImage(e, p.name, status, paste, input));

    input.addEventListener('change', () => {
      const f = input.files && input.files[0];
      if (!f) {
        _clearImageParam(p.name, status, paste);
        return;
      }
      _uploadFileForParam(f, p.name, status, paste);
    });

    pickrow.appendChild(input);
    pickrow.appendChild(paste);

    row.appendChild(label);
    row.appendChild(pickrow);
    row.appendChild(status);
    container.appendChild(row);
  });
}

function _clearImageParam(title, statusEl, pasteEl) {
  delete _uploadedImageParams[title];
  statusEl.className = 'image-param-status';
  statusEl.textContent = 'optional — leaves the workflow default in place';
  if (pasteEl) {
    pasteEl.classList.remove('has-image');
    pasteEl.textContent = 'or click here and paste (Ctrl/Cmd+V)';
  }
}

function _handlePastedImage(event, title, statusEl, pasteEl, fileInputEl) {
  const items = (event.clipboardData && event.clipboardData.items) || [];
  for (const it of items) {
    if (it.kind === 'file' && /^image\//.test(it.type)) {
      const blob = it.getAsFile();
      if (blob) {
        event.preventDefault();
        // Clear the file input so the field reflects the pasted source.
        try { fileInputEl.value = ''; } catch (_) {}
        _uploadFileForParam(blob, title, statusEl, pasteEl);
        return;
      }
    }
  }
  statusEl.className = 'image-param-status err';
  statusEl.textContent = 'paste failed: no image found in clipboard';
}

async function _uploadFileForParam(file, title, statusEl, pasteEl) {
  statusEl.className = 'image-param-status';
  statusEl.textContent = 'uploading…';
  try {
    const form = new FormData();
    // Pasted Blobs don't carry a filename; supply one so multipart parsing works.
    const sendName = file.name || ('pasted-' + Date.now() + _extForType(file.type));
    form.append('file', file, sendName);
    const r = await fetch('/v1/comfyui/upload-image', { method: 'POST', body: form });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(txt || ('HTTP ' + r.status));
    }
    const data = await r.json();
    if (!data.image) throw new Error('upload returned no filename');
    _uploadedImageParams[title] = data.image;
    statusEl.className = 'image-param-status ok';
    statusEl.textContent = 'uploaded as ' + data.image;
    if (pasteEl) {
      pasteEl.classList.add('has-image');
      pasteEl.textContent = '✓ ' + data.image + ' — paste again to replace';
    }
  } catch (e) {
    delete _uploadedImageParams[title];
    statusEl.className = 'image-param-status err';
    statusEl.textContent = 'upload failed: ' + e.message;
    if (pasteEl) {
      pasteEl.classList.remove('has-image');
    }
  }
}

function _extForType(mime) {
  if (mime === 'image/png') return '.png';
  if (mime === 'image/jpeg') return '.jpg';
  if (mime === 'image/webp') return '.webp';
  return '';
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
  // Keep the dropdown showing the loaded prompt so the user can see which
  // saved prompt is currently in the textarea.
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

  const wf = _workflows.find(w => w.name === workflow);
  const allowed = new Set(((wf && wf.imageParams) || []).map(p => p.name));
  const image_params = {};
  Object.entries(_uploadedImageParams).forEach(([k, v]) => {
    if (allowed.has(k) && v) image_params[k] = v;
  });

  const body = { workflow, prompt, image_params };

  if (wf && wf.denoiseNodeId) {
    const dv = (document.getElementById('gen-denoise').value || '').trim();
    if (dv !== '') body.denoise = parseFloat(dv);
  }

  if (wf && wf.seedNodeId) {
    document.getElementById('gen-seed-used').textContent = '';  // clear stale readout
    if (document.getElementById('gen-seed-randomize').checked) {
      body.randomize_seed = true;
    } else {
      const sv = (document.getElementById('gen-seed').value || '').trim();
      if (sv !== '') {
        if (!/^\d+$/.test(sv)) {
          statusEl.style.color = '#c44';
          statusEl.textContent = 'Seed must be a whole number (digits only).';
          return;
        }
        body.seed = sv;  // string — preserves 64-bit precision
      }
    }
  }

  try {
    const job = await api('/jobs/image', 'POST', body);
    _currentJobId = job.job_id;
    statusEl.textContent = 'Job ' + job.job_id + ' — queued';
    OutputConsole.create(document.querySelector('#tab-generate #panel-right'), { pageKey: 'image-generate' }).start(_currentJobId);
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
        _showUsedSeed(_currentJobId, workflow);
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
