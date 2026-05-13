// Workflows tab — list registered workflows and their detected params.

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
        'Export a workflow from the ComfyUI editor (API format) and save it there.</p>';
      return;
    }
    container.innerHTML = '';
    workflows.forEach(w => {
      const card = document.createElement('div');
      card.className = 'wf-card';

      const nameEl = document.createElement('div');
      nameEl.className = 'wf-name';
      nameEl.textContent = w.name;

      const paramsEl = document.createElement('div');
      paramsEl.className = 'wf-params';
      (w.params || []).forEach(p => {
        const tag = document.createElement('span');
        tag.className = 'wf-param-tag';
        tag.textContent = p.name + ' (' + p.type + ')';
        paramsEl.appendChild(tag);
      });
      if (!w.params || !w.params.length) {
        paramsEl.innerHTML = '<span style="color:#444;font-size:0.76rem;">No tunable params detected</span>';
      }

      card.appendChild(nameEl);
      card.appendChild(paramsEl);
      container.appendChild(card);
    });
  } catch (e) {
    container.innerHTML = '<p class="wf-empty">Could not load workflows: ' + _escHtml(e.message) + '</p>';
  }
}
