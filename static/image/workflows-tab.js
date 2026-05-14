// Workflows tab — list registered workflows with compatibility status.

function onWorkflowsTabActive() {
  renderWorkflowsList();
  const link = document.getElementById('wf-editor-link');
  if (link) link.href = 'http://' + window.location.hostname + ':8188';
}

async function renderWorkflowsList() {
  const container = document.getElementById('wf-list');
  try {
    const data = await api('/comfyui/workflows');
    const workflows = data.workflows || [];
    if (!workflows.length) {
      container.innerHTML =
        '<p class="wf-empty">No workflows found in <code>config/comfyui-workflows/</code>.<br>' +
        'Export a workflow from the ComfyUI editor in API format and save it there.</p>';
      return;
    }
    container.innerHTML = '';
    workflows.forEach(w => {
      const card = document.createElement('div');
      card.className = 'wf-card';

      const nameEl = document.createElement('div');
      nameEl.className = 'wf-name';
      nameEl.textContent = w.name;

      const statusEl = document.createElement('div');
      statusEl.className = 'wf-status';
      if (w.valid) {
        statusEl.innerHTML =
          '<span class="wf-badge wf-badge-ok">Ready</span>' +
          '<span style="color:#555;font-size:0.76rem;margin-left:8px;">node ' + _escHtml(w.promptNodeId) + '</span>';
      } else {
        statusEl.innerHTML =
          '<span class="wf-badge wf-badge-err">Invalid</span>' +
          '<span style="color:#c44;font-size:0.76rem;margin-left:8px;">' + _escHtml(w.error || '') + '</span>';
      }

      card.appendChild(nameEl);
      card.appendChild(statusEl);
      container.appendChild(card);
    });
  } catch (e) {
    container.innerHTML = '<p class="wf-empty">Could not load workflows: ' + _escHtml(e.message) + '</p>';
  }
}
