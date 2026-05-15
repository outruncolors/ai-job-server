  let _tools = [];
  let _selected = null;


  async function loadTools() {
    try {
      const data = await api('/mcp/tools');
      _tools = data.tools || [];
      renderToolList();
    } catch (e) {
      toast('error', 'Failed to load tools: ' + e.message);
    }
  }

  function renderToolList() {
    const list = document.getElementById('tool-list');
    if (_tools.length === 0) {
      list.innerHTML = '<div style="color:#333;font-size:0.78rem">No tools registered.</div>';
      return;
    }
    list.innerHTML = _tools.map(t => `
      <div class="tool-card" id="card-${_escHtml(t.name)}" onclick="selectTool(${_escHtml(JSON.stringify(t.name))})">
        <div class="tool-name">${_escHtml(t.name)}</div>
        <div class="tool-desc">${_escHtml(t.description)}</div>
      </div>
    `).join('');
  }

  function selectTool(name) {
    const tool = _tools.find(t => t.name === name);
    if (!tool) return;
    _selected = tool;

    document.querySelectorAll('.tool-card').forEach(c => c.classList.remove('selected'));
    const card = document.getElementById('card-' + name);
    if (card) card.classList.add('selected');

    document.getElementById('try-empty').style.display = 'none';
    const panel = document.getElementById('try-panel');
    panel.style.display = 'block';

    document.getElementById('try-title').textContent = tool.name;
    document.getElementById('try-desc').textContent = tool.description;

    // Schema table
    const props = tool.input_schema.properties;
    const required = tool.input_schema.required || [];
    const tbody = document.getElementById('schema-tbody');
    tbody.innerHTML = Object.entries(props).map(([k, p]) => `
      <tr>
        <td>${_escHtml(k)}</td>
        <td>${_escHtml(p.type)}</td>
        <td>${required.includes(k) ? '<span class="req-badge">required</span>' : '<span style="color:#333">—</span>'}</td>
        <td>${_escHtml(p.description)}</td>
      </tr>
    `).join('');

    // Arg form
    const form = document.getElementById('arg-form');
    form.innerHTML = Object.entries(props).map(([k, p]) => {
      let input;
      if (p.type === 'boolean') {
        input = `<input type="checkbox" id="arg-${_escHtml(k)}" style="width:auto">`;
      } else if (p.enum) {
        input = `<select id="arg-${_escHtml(k)}"><option value="">— select —</option>${p.enum.map(v => `<option value="${_escHtml(v)}">${_escHtml(v)}</option>`).join('')}</select>`;
      } else {
        const isNum = p.type === 'integer' || p.type === 'number';
        const attrs = isNum ? 'type="number" step="1"' : 'type="text"';
        input = `<input ${attrs} id="arg-${_escHtml(k)}" placeholder="${_escHtml(p.description)}">`;
      }
      return `<label>${_escHtml(k)}</label>${input}`;
    }).join('');

    document.getElementById('result-wrap').style.display = 'none';
  }

  async function runTool() {
    if (!_selected) return;
    const btn = document.getElementById('run-btn');
    btn.disabled = true;

    const props = _selected.input_schema.properties;
    const args = {};
    for (const [k, p] of Object.entries(props)) {
      const el = document.getElementById('arg-' + k);
      if (!el) continue;
      if (p.type === 'boolean') {
        args[k] = el.checked;
      } else if (p.type === 'integer') {
        const raw = el.value.trim();
        if (raw !== '') args[k] = parseInt(raw, 10);
      } else if (p.type === 'number') {
        const raw = el.value.trim();
        if (raw !== '') args[k] = parseFloat(raw);
      } else {
        const raw = el.value.trim();
        if (raw !== '') args[k] = raw;
      }
    }

    const box = document.getElementById('result-box');
    const meta = document.getElementById('result-meta');
    document.getElementById('result-wrap').style.display = 'block';
    box.className = '';
    box.textContent = '…';
    meta.textContent = '';

    try {
      const data = await api(`/mcp/tools/${_selected.name}/call`, 'POST', { arguments: args });
      if (data.validation_status) {
        box.className = 'err';
        box.textContent = data.error;
        meta.textContent = `status: ${data.validation_status}`;
      } else {
        box.className = 'ok';
        box.textContent = JSON.stringify(data.result, null, 2);
        meta.textContent = `${data.execution_ms} ms · ${data.timestamp}`;
      }
    } catch (e) {
      box.className = 'err';
      box.textContent = e.message;
    }

    btn.disabled = false;
  }

  loadTools();
