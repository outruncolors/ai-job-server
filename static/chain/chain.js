    // ── ai-job-server / chain page (v2: numbered steps + alternatives + variables + gotos) ──

    const _recreateId = sessionStorage.getItem('recreate_job_id');
    if (_recreateId) sessionStorage.removeItem('recreate_job_id');

    function statusClass(s) { return 'status-' + s; }

    // ── Tabs ─────────────────────────────────────────────────────────
    function switchTab(tab) {
      _activeTab = tab;
      document.querySelectorAll('#chain-tabs .tab-btn').forEach(b =>
        b.classList.toggle('active', b.dataset.tab === tab)
      );
      document.getElementById('chain-panel').style.display     = tab === 'chain'     ? '' : 'none';
      document.getElementById('sequences-panel').style.display = tab === 'sequences' ? '' : 'none';
      if (tab === 'chain') requestAnimationFrame(redrawGotoArrows);
    }

    // ── Global state ─────────────────────────────────────────────────
    let _currentSeqId    = null;
    let _activeTab       = 'chain';
    let _chainPresets    = [];
    let _defaultPresetId = null;
    let _llmModelPresets = [];
    let _allSeqs         = [];
    let _ctxItems        = [];
    let _voicePresets    = [];
    let _mcpTools        = [];
    let _variables       = [];           // [{name, default, choices: [...]}]
    let _chainStepCounter  = 0;
    const _STEP_TYPES = ['llm','voice','write_context','sequence','image_prompt','save_wildcard','create_ticket','goto'];

    function _uid() { return Math.random().toString(36).slice(2, 10); }

    // ── Loaders ──────────────────────────────────────────────────────
    async function _loadChainPresets() {
      try {
        const data = await api('/llm-endpoints');
        _chainPresets    = data.presets || [];
        _defaultPresetId = data.default_preset_id || null;
      } catch (_) {}
    }
    async function _loadLlmModelPresets() {
      try {
        const data = await api('/llm-presets');
        _llmModelPresets = data.presets || [];
      } catch (_) { _llmModelPresets = []; }
    }
    async function loadContextItems() {
      try {
        const data = await api('/context-items');
        _ctxItems = data.items || [];
      } catch(_) { _ctxItems = []; }
    }
    async function loadVoicePresets() {
      try {
        const data = await api('/voice-presets');
        _voicePresets = data || [];
      } catch(_) { _voicePresets = []; }
    }
    async function loadMcpTools() {
      try {
        const data = await api('/mcp/tools');
        _mcpTools = data.tools || [];
      } catch(_) { _mcpTools = []; }
    }

    function _llmModelPresetOptions(selectedName, requires) {
      const reqSet = new Set(requires || []);
      const compatible = _llmModelPresets.filter(p => {
        if (reqSet.size === 0) return true;
        const caps = new Set(p.capabilities || []);
        for (const r of reqSet) if (!caps.has(r)) return false;
        return true;
      });
      let opts = '<option value="">— default —</option>';
      for (const p of compatible) {
        const caps = (p.capabilities || []).join(',');
        const label = caps ? p.name + ' [' + caps + ']' : p.name;
        opts += '<option value="' + _escHtml(p.name) + '"' +
          (p.name === selectedName ? ' selected' : '') + '>' + _escHtml(label) + '</option>';
      }
      return opts;
    }

    function _voicePresetOptions(selectedId) {
      return '<option value="">— select preset —</option>' +
        _voicePresets.map(p =>
          `<option value="${p.id}"${p.id === selectedId ? ' selected' : ''}>${_escHtml(p.name)}</option>`
        ).join('');
    }

    function _seqOptions(selectedId) {
      return '<option value="">— select sequence —</option>' +
        _allSeqs.map(s =>
          `<option value="${s.id}"${s.id === selectedId ? ' selected' : ''}>${_escHtml(s.name)}</option>`
        ).join('');
    }

    // ── Variables pane ───────────────────────────────────────────────
    function _renderVariablesPane() {
      const list = document.getElementById('chain-variables-list');
      if (_variables.length === 0) {
        list.innerHTML = '<div class="var-empty">No variables. Click + Variable to add one.</div>';
        return;
      }
      list.innerHTML = _variables.map((v, i) =>
        '<div class="var-row" data-var-idx="' + i + '">' +
          '<input class="var-name" type="text" placeholder="name (kebab-case)" value="' + _escHtml(v.name) + '">' +
          '<input class="var-default" type="text" placeholder="default value" value="' + _escHtml(v.default) + '">' +
          '<input class="var-choices" type="text" placeholder="choices (comma-separated, optional)" value="' + _escHtml((v.choices || []).join(', ')) + '">' +
          '<button type="button" class="var-remove" onclick="_removeVariableRow(' + i + ')">×</button>' +
        '</div>'
      ).join('');
    }
    function _addVariableRow() {
      _collectVariablesFromDom();
      _variables.push({ name: '', default: '', choices: [] });
      _renderVariablesPane();
    }
    function _removeVariableRow(idx) {
      _collectVariablesFromDom();
      _variables.splice(idx, 1);
      _renderVariablesPane();
    }
    function _collectVariablesFromDom() {
      const rows = document.querySelectorAll('#chain-variables-list .var-row');
      _variables = [...rows].map(r => ({
        name: (r.querySelector('.var-name').value || '').trim(),
        default: r.querySelector('.var-default').value,
        choices: (r.querySelector('.var-choices').value || '')
          .split(',').map(s => s.trim()).filter(Boolean),
      })).filter(v => v.name);
    }

    // ── Sequences list ───────────────────────────────────────────────
    function _renderSeqList() {
      const el = document.getElementById('seq-list');
      if (_allSeqs.length === 0) {
        el.innerHTML = '<div style="color:#333;font-size:0.72rem;">No sequences saved.</div>';
        return;
      }
      const usedBy = {}, usesMap = {};
      for (const s of _allSeqs) {
        usedBy[s.id]  = usedBy[s.id]  || [];
        usesMap[s.id] = [];
        for (const step of ((s.data && s.data.steps) || [])) {
          const altList = step.alternatives || [{ sequence_id: step.sequence_id }];
          for (const alt of altList) {
            if (step.type === 'sequence' && alt && alt.sequence_id) {
              const dep = _allSeqs.find(x => x.id === alt.sequence_id);
              if (dep) {
                usesMap[s.id].push(dep.name);
                usedBy[dep.id] = usedBy[dep.id] || [];
                if (!usedBy[dep.id].includes(s.name)) usedBy[dep.id].push(s.name);
              }
            }
          }
        }
      }
      let html = '';
      for (const s of _allSeqs) {
        const isActive = s.id === _currentSeqId;
        const depParts = [];
        if (usesMap[s.id] && usesMap[s.id].length > 0) depParts.push('uses: ' + usesMap[s.id].join(', '));
        if (usedBy[s.id] && usedBy[s.id].length > 0) depParts.push('used by: ' + usedBy[s.id].join(', '));
        const depStr = depParts.join(' · ');
        html += '<div class="seq-row' + (isActive ? ' is-active' : '') + '" onclick="_editSeq(\'' + s.id + '\')" style="cursor:pointer;">' +
          '<span class="seq-row-name" title="' + _escHtml(s.name) + '">' + _escHtml(s.name) + '</span>' +
          (depStr ? '<span class="seq-row-deps" title="' + _escHtml(depStr) + '">' + _escHtml(depStr) + '</span>' : '') +
          '<span class="seq-row-actions">' +
            '<button class="danger" onclick="event.stopPropagation();_deleteSeq(\'' + s.id + '\')">Del</button>' +
          '</span>' +
          '</div>';
      }
      el.innerHTML = html;
    }

    async function loadSeqs() {
      try {
        const data = await api('/chain-sequences');
        _allSeqs = (data.sequences || []).slice().sort((a,b) => new Date(b.updated_at) - new Date(a.updated_at));
        _renderSeqList();
      } catch(_) { /* silently fail */ }
    }

    function _newSeq() {
      _currentSeqId = null;
      document.getElementById('chain-seq-name').value = '';
      document.getElementById('seq-edit-msg').textContent = '';
      _resetForm();
      addChainStep({ alternatives: [{ prompt: 'Create five bullet points for the following task:\n\n' }] });
      document.getElementById('seq-edit-bar').style.display = '';
      switchTab('chain');
      history.replaceState(null, '', '/chain');
      _renderSeqList();
    }

    function _editSeq(id) {
      const seq = _allSeqs.find(s => s.id === id);
      if (!seq) return;
      _currentSeqId = id;
      document.getElementById('chain-seq-name').value = seq.name;
      document.getElementById('seq-edit-msg').textContent = '';
      loadStepsIntoForm((seq.data && seq.data.steps) || [], (seq.data && seq.data.variables) || []);
      document.getElementById('seq-edit-bar').style.display = '';
      switchTab('chain');
      history.replaceState(null, '', '/chain?sequence=' + id);
      _renderSeqList();
    }

    function _cancelSeqEdit() {
      document.getElementById('seq-edit-bar').style.display = 'none';
      document.getElementById('seq-edit-msg').textContent = '';
      _currentSeqId = null;
      history.replaceState(null, '', '/chain');
    }

    async function _deleteSeq(id) {
      const seq = _allSeqs.find(s => s.id === id);
      if (!seq || !confirm('Delete sequence "' + seq.name + '"?')) return;
      try {
        await api('/chain-sequences/' + id, 'DELETE');
        if (_currentSeqId === id) {
          _currentSeqId = null;
          _resetForm();
          addChainStep({ alternatives: [{ prompt: 'Create five bullet points for the following task:\n\n' }] });
          document.getElementById('seq-edit-bar').style.display = 'none';
          history.replaceState(null, '', '/chain');
        }
        await loadSeqs();
      } catch(e) { alert('Error: ' + e.message); }
    }

    function _resetForm() {
      document.getElementById('chain-steps-list').innerHTML = '';
      _chainStepCounter = 0;
      _variables = [];
      _renderVariablesPane();
    }

    async function saveSeq() {
      const name = document.getElementById('chain-seq-name').value.trim();
      const msgEl = document.getElementById('seq-edit-msg');
      msgEl.textContent = '';
      if (!name) { msgEl.style.color = '#e44'; msgEl.textContent = 'Enter a sequence name.'; return; }
      _collectVariablesFromDom();
      const steps = _collectSteps();
      if (steps.length === 0) { msgEl.style.color = '#e44'; msgEl.textContent = 'Add at least one step.'; return; }
      try {
        const saved = await api('/chain-sequences', 'POST', { name, steps, variables: _variables });
        _currentSeqId = saved.id;
        history.replaceState(null, '', '/chain?sequence=' + saved.id);
        msgEl.style.color = '#2a6'; msgEl.textContent = 'Saved.';
        await loadSeqs();
      } catch(e) {
        msgEl.style.color = '#e44'; msgEl.textContent = 'Error: ' + e.message;
      }
    }

    function loadStepsIntoForm(steps, variables) {
      _resetForm();
      _variables = (variables || []).map(v => ({
        name: v.name || '',
        default: v.default || '',
        choices: Array.isArray(v.choices) ? v.choices : [],
      }));
      _renderVariablesPane();
      for (const s of (steps || [])) {
        const alternatives = (s.alternatives && s.alternatives.length)
          ? s.alternatives
          : [_v1ShorthandToAlt(s)];
        addChainStep({
          type: s.type || 'llm',
          name: s.name,
          number: s.number || 0,
          visit_cap: s.visit_cap || 100,
          alternatives,
        });
      }
      _renumberSteps();
      requestAnimationFrame(redrawGotoArrows);
    }

    // Convert any v1-shorthand fields on a step into a single alternative dict.
    function _v1ShorthandToAlt(s) {
      return {
        prompt: s.prompt || '',
        context_ids: s.context_ids || [],
        tools: s.tools || [],
        voice_preset_id: s.voice_preset_id || '',
        voice_pre: s.voice_pre || '',
        voice_post: s.voice_post || '',
        voice_preprocess: !!s.voice_preprocess,
        voice_auto_segment: !!s.voice_auto_segment,
        ctx_name: s.ctx_name || '',
        ctx_description: s.ctx_description || '',
        ctx_pre: s.ctx_pre || '',
        ctx_post: s.ctx_post || '',
        ctx_tags: s.ctx_tags || [],
        ctx_overwrite: !!s.ctx_overwrite,
        sequence_id: s.sequence_id || '',
        preset: s.preset || '',
        requires: s.requires || [],
      };
    }

    // ── Context library (selector widget) ────────────────────────────
    function _allTags() {
      const set = new Set();
      for (const item of _ctxItems) (item.tags || []).forEach(t => set.add(t));
      return [...set].sort();
    }

    function _buildCtxSelector(altEl, selectedIds) {
      const sel = altEl.querySelector('.ctx-selector');
      if (!sel) return;
      const treeEl = sel.querySelector('.ctx-tree');
      const datalistId = sel.getAttribute('data-list-id');
      const datalist = datalistId ? document.getElementById(datalistId) : null;

      if (datalist) datalist.innerHTML = _allTags().map(t => `<option value="${t}">`).join('');

      const byTag = {}, untagged = [];
      for (const item of _ctxItems) {
        if (!item.tags || item.tags.length === 0) untagged.push(item);
        else for (const tag of item.tags) (byTag[tag] = byTag[tag] || []).push(item);
      }

      const selectedTagsList = _getSelectedTags(altEl);
      const tagSelectedIds = new Set();
      for (const tag of selectedTagsList) {
        for (const item of _ctxItems) {
          if ((item.tags || []).includes(tag)) tagSelectedIds.add(item.id);
        }
      }

      if (_ctxItems.length === 0) {
        treeEl.innerHTML = '<div class="ctx-empty">No context items. <a href="/context/" style="color:#4a8;">Add some</a>.</div>';
      } else {
        const groups = Object.keys(byTag).sort();
        let html = '';
        const _entryHtml = (item, isChecked) => {
          const chk = isChecked ? 'checked' : '';
          const cls = isChecked ? ' is-checked' : '';
          return `<div class="ctx-entry${cls}" onclick="_onEntryClick(event,this)">` +
            `<input type="checkbox" class="ctx-chk" data-id="${item.id}" ${chk}>` +
            `<div class="ctx-entry-info">` +
              `<div class="ctx-entry-title">${_escHtml(item.title || '(untitled)')}</div>` +
              (item.description ? `<div class="ctx-entry-desc">${_escHtml(item.description)}</div>` : '') +
            `</div></div>`;
        };
        for (const tag of groups) {
          html += `<details class="ctx-group" open><summary>${tag} (${byTag[tag].length})</summary>`;
          for (const item of byTag[tag]) html += _entryHtml(item, selectedIds.has(item.id) || tagSelectedIds.has(item.id));
          html += '</details>';
        }
        if (untagged.length > 0) {
          html += `<details class="ctx-group" open><summary>untagged (${untagged.length})</summary>`;
          for (const item of untagged) html += _entryHtml(item, selectedIds.has(item.id) || tagSelectedIds.has(item.id));
          html += '</details>';
        }
        treeEl.innerHTML = html;
      }
      _updateCtxCount(altEl);
    }

    function _getSelectedTags(altEl) {
      return [...altEl.querySelectorAll('.ctx-tag-row .ctx-tag-chip')]
        .map(chip => chip.getAttribute('data-tag'));
    }
    function _addTag(altEl, tag) {
      tag = tag.trim();
      if (!tag) return;
      const existing = _getSelectedTags(altEl);
      if (existing.includes(tag)) return;
      const row = altEl.querySelector('.ctx-tag-row');
      const input = row.querySelector('.ctx-tag-input');
      const chip = document.createElement('span');
      chip.className = 'ctx-tag-chip';
      chip.setAttribute('data-tag', tag);
      chip.innerHTML = _escHtml(tag) + `<button onclick="_removeTag(this.closest('.alt-card'), '${tag.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">×</button>`;
      row.insertBefore(chip, input);
      _rebuildTree(altEl);
    }
    function _removeTag(altEl, tag) {
      const chip = [...altEl.querySelectorAll('.ctx-tag-row .ctx-tag-chip')]
        .find(c => c.getAttribute('data-tag') === tag);
      if (chip) chip.remove();
      _rebuildTree(altEl);
    }
    function _rebuildTree(altEl) {
      const checked = new Set([...altEl.querySelectorAll('.ctx-chk:checked')].map(c => c.getAttribute('data-id')));
      _buildCtxSelector(altEl, checked);
    }
    function _onEntryClick(event, entry) {
      const chk = entry.querySelector('.ctx-chk');
      if (!chk) return;
      if (event.target !== chk) chk.checked = !chk.checked;
      entry.classList.toggle('is-checked', chk.checked);
      const altEl = entry.closest('.alt-card');
      if (altEl) _updateCtxCount(altEl);
    }
    function _updateCtxCount(altEl) {
      const ids = _collectAltContextIds(altEl);
      const summary = altEl.querySelector('.ctx-selector > summary');
      const countEl = summary && summary.querySelector('.ctx-count');
      if (countEl) countEl.textContent = ids.length > 0 ? `(${ids.length})` : '';
    }
    function _collectAltContextIds(altEl) {
      const checkedIds = new Set([...altEl.querySelectorAll('.ctx-chk:checked')].map(c => c.getAttribute('data-id')));
      const selectedTags = _getSelectedTags(altEl);
      for (const tag of selectedTags) {
        for (const item of _ctxItems) if ((item.tags || []).includes(tag)) checkedIds.add(item.id);
      }
      return [...checkedIds];
    }

    // ── Step card construction ───────────────────────────────────────
    function addChainStep(opts = {}) {
      const type = opts.type || 'llm';
      const name = opts.name || ('Step ' + (document.querySelectorAll('#chain-steps-list > .chain-step-card').length + 1));
      const visitCap = opts.visit_cap || 100;
      const alternatives = (opts.alternatives && opts.alternatives.length) ? opts.alternatives : [{}];
      const idx = _chainStepCounter++;
      const cardId = 'card-' + _uid();
      const el = document.createElement('div');
      el.id = 'chain-step-' + idx;
      el.className = 'chain-step-card';
      el.setAttribute('data-card-id', cardId);
      el.setAttribute('data-card-type', type);
      el.setAttribute('draggable', 'true');

      const kindOptions = _STEP_TYPES.map(t =>
        '<option value="' + t + '"' + (t === type ? ' selected' : '') + '>' + _typeLabel(t) + '</option>'
      ).join('');

      el.innerHTML =
        '<span class="step-num">1</span>' +
        '<span class="step-drag-handle" title="drag to reorder">⋮⋮</span>' +
        '<div class="chain-step-head">' +
          '<input class="step-name-input" type="text" placeholder="Step name" value="' + _escHtml(name) + '">' +
          '<select class="chain-step-kind" onchange="_onStepKindChange(this)">' + kindOptions + '</select>' +
          '<label style="color:#444;font-size:0.66rem;margin:0;">visit cap</label>' +
          '<input class="visit-cap-input" type="number" min="1" value="' + visitCap + '">' +
          '<button class="secondary" onclick="removeChainStep(\'' + el.id + '\')">×</button>' +
        '</div>' +
        '<div class="alternatives-list"></div>' +
        '<div class="add-alternative-row">' +
          '<button type="button" onclick="_addAlternative(this.closest(\'.chain-step-card\'))">+ Add Alternative</button>' +
        '</div>';

      _attachStepDnd(el);
      document.getElementById('chain-steps-list').appendChild(el);
      for (const altData of alternatives) {
        _addAlternative(el, altData);
      }
      _renumberSteps();
      requestAnimationFrame(redrawGotoArrows);
    }

    function _typeLabel(t) {
      return ({
        llm: 'text',
        voice: 'voice',
        write_context: 'write context',
        sequence: 'sequence',
        image_prompt: 'image prompt',
        save_wildcard: 'save wildcard',
        create_ticket: 'create ticket',
        goto: 'goto',
      })[t] || t;
    }

    function _addAlternative(stepEl, altData) {
      const type = stepEl.getAttribute('data-card-type');
      const data = altData || {};
      const altEl = document.createElement('div');
      altEl.className = 'alt-card';
      altEl.setAttribute('data-alt-uid', _uid());
      const idx = stepEl.querySelectorAll('.alt-card').length + 1;
      altEl.innerHTML =
        '<div class="alt-head">' +
          '<span class="alt-label">Alt ' + idx + '</span>' +
          '<div class="alt-weight-row">' +
            '<label>weight</label>' +
            '<input class="weight-input" type="number" min="1" value="' + (data.weight || 1) + '">' +
            '<button type="button" class="alt-remove" onclick="_removeAlternative(this.closest(\'.alt-card\'))">×</button>' +
          '</div>' +
        '</div>' +
        '<div class="alt-body"></div>';
      stepEl.querySelector('.alternatives-list').appendChild(altEl);
      _renderAltBody(altEl, type, data);
      requestAnimationFrame(redrawGotoArrows);
    }

    function _removeAlternative(altEl) {
      const stepEl = altEl.closest('.chain-step-card');
      if (stepEl.querySelectorAll('.alt-card').length <= 1) {
        alert('Each step needs at least one alternative.');
        return;
      }
      altEl.remove();
      _relabelAlternatives(stepEl);
      requestAnimationFrame(redrawGotoArrows);
    }

    function _relabelAlternatives(stepEl) {
      [...stepEl.querySelectorAll('.alt-card')].forEach((a, i) => {
        const lbl = a.querySelector('.alt-label');
        if (lbl) lbl.textContent = 'Alt ' + (i + 1);
      });
    }

    function removeChainStep(id) {
      const el = document.getElementById(id);
      if (el) el.remove();
      _renumberSteps();
      _refreshGotoTargetsEverywhere();
      requestAnimationFrame(redrawGotoArrows);
    }

    function _onStepKindChange(sel) {
      const card = sel.closest('.chain-step-card');
      const newType = sel.value;
      card.setAttribute('data-card-type', newType);
      // Re-render every alternative body for the new type. Collect existing data first.
      const altEls = [...card.querySelectorAll('.alt-card')];
      const oldData = altEls.map(_collectAltData);
      const list = card.querySelector('.alternatives-list');
      list.innerHTML = '';
      for (const d of (oldData.length ? oldData : [{}])) {
        _addAlternative(card, d);
      }
      _refreshGotoTargetsEverywhere();
      requestAnimationFrame(redrawGotoArrows);
    }

    // ── Alternative body rendering (type-dependent) ──────────────────
    function _renderAltBody(altEl, type, data) {
      const body = altEl.querySelector('.alt-body');
      const datalistId = 'ctx-list-' + altEl.getAttribute('data-alt-uid');

      if (type === 'llm') {
        const requires = Array.isArray(data.requires) ? data.requires : [];
        body.innerHTML =
          '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px;">' +
            '<label style="margin:0;flex:0 0 auto;">Preset</label>' +
            '<select class="alt-llm-preset" style="flex:1 1 220px;min-width:160px;" onchange="_onLlmPresetChange(this)">' +
              _llmModelPresetOptions(data.preset || '', requires) +
            '</select>' +
            '<label style="margin:0;color:#383838;font-size:0.7rem;">requires:</label>' +
            '<label style="margin:0;display:flex;align-items:center;gap:3px;font-size:0.72rem;cursor:pointer;">' +
              '<input type="checkbox" class="alt-llm-req-text"' + (requires.includes('text') ? ' checked' : '') + ' onchange="_onLlmRequiresChange(this)"> text' +
            '</label>' +
            '<label style="margin:0;display:flex;align-items:center;gap:3px;font-size:0.72rem;cursor:pointer;">' +
              '<input type="checkbox" class="alt-llm-req-vision"' + (requires.includes('vision') ? ' checked' : '') + ' onchange="_onLlmRequiresChange(this)"> vision' +
            '</label>' +
          '</div>' +
          '<label>Prompt</label>' +
          '<textarea class="alt-prompt" style="min-height:72px;">' + _escHtml(data.prompt || '') + '</textarea>' +
          '<datalist id="' + datalistId + '"></datalist>' +
          '<details class="ctx-selector" data-list-id="' + datalistId + '">' +
            '<summary>Context <span class="ctx-count"></span></summary>' +
            '<div class="ctx-body">' +
              '<div class="ctx-tag-row">' +
                '<input class="ctx-tag-input" type="text" list="' + datalistId + '" placeholder="Add tag…" ' +
                  'onkeydown="if(event.key===\'Enter\'||event.key===\',\'){event.preventDefault();_addTag(this.closest(\'.alt-card\'),this.value);this.value=\'\'}" ' +
                  'onchange="_addTag(this.closest(\'.alt-card\'),this.value);this.value=\'\'">' +
              '</div>' +
              '<div class="ctx-tree"></div>' +
            '</div>' +
          '</details>' +
          _renderToolsDetails(data.tools || []);
        _buildCtxSelector(altEl, new Set(data.context_ids || []));
      } else if (type === 'voice') {
        body.innerHTML =
          '<label>Voice Preset</label>' +
          (_voicePresets.length === 0
            ? '<div style="color:#555;font-size:0.74rem;margin-top:4px;">No presets — <a href="/voice" style="color:#2a6;">create one at /voice</a></div>'
            : '<select class="alt-voice-preset">' + _voicePresetOptions(data.voice_preset_id || '') + '</select>') +
          '<label>Spoken text (template) <span style="color:#383838;font-size:0.7rem;">(falls back to previous output if empty)</span></label>' +
          '<textarea class="alt-prompt" style="min-height:60px;">' + _escHtml(data.prompt || '') + '</textarea>' +
          '<label>Pre <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="alt-voice-pre" style="min-height:48px;">' + _escHtml(data.voice_pre || '') + '</textarea>' +
          '<label>Post <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="alt-voice-post" style="min-height:48px;">' + _escHtml(data.voice_post || '') + '</textarea>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:10px;cursor:pointer;">' +
            '<input type="checkbox" class="alt-voice-preprocess"' + (data.voice_preprocess ? ' checked' : '') + '> Pre-process for speech' +
          '</label>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:6px;cursor:pointer;">' +
            '<input type="checkbox" class="alt-voice-auto-segment"' + (data.voice_auto_segment ? ' checked' : '') + '> Auto-segment via LLM' +
          '</label>';
      } else if (type === 'write_context') {
        body.innerHTML =
          '<label>Context Name</label>' +
          '<input class="alt-ctx-name" type="text" placeholder="my-notes" value="' + _escHtml(data.ctx_name || '') + '">' +
          '<label>Tags <span style="color:#383838;font-size:0.7rem;">(comma-separated)</span></label>' +
          '<input class="alt-ctx-tags" type="text" placeholder="journal, daily…" value="' + _escHtml((data.ctx_tags || []).join(', ')) + '">' +
          '<label>Description <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="alt-ctx-description" style="min-height:48px;">' + _escHtml(data.ctx_description || '') + '</textarea>' +
          '<label>Pre <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="alt-ctx-pre" style="min-height:48px;">' + _escHtml(data.ctx_pre || '') + '</textarea>' +
          '<label>Post <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="alt-ctx-post" style="min-height:48px;">' + _escHtml(data.ctx_post || '') + '</textarea>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:10px;cursor:pointer;">' +
            '<input type="checkbox" class="alt-ctx-overwrite"' + (data.ctx_overwrite ? ' checked' : '') + '> Overwrite' +
          '</label>';
      } else if (type === 'sequence') {
        body.innerHTML =
          '<label>Sequence</label>' +
          '<select class="alt-seq-select">' + _seqOptions(data.sequence_id || '') + '</select>';
      } else if (type === 'image_prompt') {
        body.innerHTML =
          '<label>Saved prompt name (template)</label>' +
          '<input class="alt-image-prompt-name" type="text" placeholder="my-image-{{var.tone}}" value="' + _escHtml(data.image_prompt_name || '') + '">' +
          '<label>Workflow <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<input class="alt-image-prompt-workflow" type="text" placeholder="default.json" value="' + _escHtml(data.image_prompt_workflow || '') + '">' +
          '<label>Prompt body (template, falls back to previous output)</label>' +
          '<textarea class="alt-prompt" style="min-height:72px;">' + _escHtml(data.prompt || '') + '</textarea>';
      } else if (type === 'save_wildcard') {
        const mode = data.wildcard_mode || 'append';
        body.innerHTML =
          '<label>Wildcard name (template)</label>' +
          '<input class="alt-wildcard-name" type="text" placeholder="names" value="' + _escHtml(data.wildcard_name || '') + '">' +
          '<label>Mode</label>' +
          '<select class="alt-wildcard-mode">' +
            '<option value="append"' + (mode === 'append' ? ' selected' : '') + '>append (create if missing)</option>' +
            '<option value="create"' + (mode === 'create' ? ' selected' : '') + '>create (always new)</option>' +
          '</select>' +
          '<label>Entry text (template, falls back to previous output)</label>' +
          '<textarea class="alt-prompt" style="min-height:60px;">' + _escHtml(data.prompt || '') + '</textarea>';
      } else if (type === 'create_ticket') {
        body.innerHTML =
          '<label>Title (template)</label>' +
          '<input class="alt-ticket-title" type="text" placeholder="Fix {{1_output}}" value="' + _escHtml(data.ticket_title_template || '') + '">' +
          '<label>Description (template, falls back to previous output)</label>' +
          '<textarea class="alt-ticket-description" style="min-height:60px;">' + _escHtml(data.ticket_description_template || '') + '</textarea>' +
          '<label>File hints <span style="color:#383838;font-size:0.7rem;">(comma-separated paths, optional)</span></label>' +
          '<input class="alt-ticket-file-hints" type="text" placeholder="app/main.py" value="' + _escHtml((data.ticket_file_hints || []).join(', ')) + '">';
      } else if (type === 'goto') {
        const fall = !!data.fall_through;
        const targetCardId = data.target_card_id || '';
        body.innerHTML =
          '<div class="goto-target-row">' +
            '<label>Target step</label>' +
            '<select class="goto-target-select" onchange="redrawGotoArrows()">' + _gotoTargetOptions(targetCardId) + '</select>' +
            '<label class="goto-fall-through"><input type="checkbox" class="alt-fall-through"' + (fall ? ' checked' : '') + ' onchange="redrawGotoArrows()"> fall through</label>' +
          '</div>' +
          '<div style="color:#444;font-size:0.7rem;margin-top:6px;">' +
            'When picked: if "fall through" is checked, advance to the next step; otherwise jump to the target step.' +
          '</div>';
      }
    }

    function _renderToolsDetails(toolNames) {
      const list = (_mcpTools && _mcpTools.length)
        ? _mcpTools.map(t =>
            '<label style="display:flex;align-items:flex-start;gap:6px;cursor:pointer;padding:3px 0;">' +
              '<input type="checkbox" class="tool-chk" data-name="' + _escHtml(t.name) + '"' +
                (toolNames.includes(t.name) ? ' checked' : '') + '>' +
              '<div>' +
                '<div style="color:#aaa;font-size:0.74rem;">' + _escHtml(t.name) + '</div>' +
                '<div style="color:#444;font-size:0.68rem;">' + _escHtml(t.description) + '</div>' +
              '</div>' +
            '</label>'
          ).join('')
        : '<div style="color:#333;font-size:0.72rem;padding:4px 0;">No tools registered.</div>';
      return '<details class="ctx-selector" style="margin-top:6px;">' +
        '<summary>Tools <span class="ctx-count">' + (toolNames.length ? '(' + toolNames.length + ')' : '') + '</span></summary>' +
        '<div class="ctx-body">' + list + '</div>' +
        '</details>';
    }

    function _gotoTargetOptions(currentCardId) {
      const cards = [...document.querySelectorAll('#chain-steps-list > .chain-step-card')];
      let html = '<option value="">— select target —</option>';
      for (const c of cards) {
        const cid = c.getAttribute('data-card-id');
        const num = c.querySelector('.step-num').textContent;
        const name = c.querySelector('.step-name-input').value;
        html += '<option value="' + cid + '"' + (cid === currentCardId ? ' selected' : '') + '>' +
          'step ' + num + ' — ' + _escHtml(name) + '</option>';
      }
      return html;
    }

    function _refreshGotoTargetsEverywhere() {
      for (const sel of document.querySelectorAll('.goto-target-select')) {
        const current = sel.value;
        sel.innerHTML = _gotoTargetOptions(current);
      }
    }

    // ── Renumbering / drag-and-drop ─────────────────────────────────
    function _renumberSteps() {
      const cards = [...document.querySelectorAll('#chain-steps-list > .chain-step-card')];
      cards.forEach((c, i) => {
        c.querySelector('.step-num').textContent = (i + 1);
        c.setAttribute('data-step-number', i + 1);
      });
      _refreshGotoTargetsEverywhere();
    }

    function _attachStepDnd(cardEl) {
      cardEl.addEventListener('dragstart', e => {
        cardEl.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', cardEl.id);
      });
      cardEl.addEventListener('dragend', () => {
        cardEl.classList.remove('dragging');
        document.querySelectorAll('.chain-step-card.drag-over').forEach(c => c.classList.remove('drag-over'));
        _renumberSteps();
        requestAnimationFrame(redrawGotoArrows);
      });
      cardEl.addEventListener('dragover', e => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        cardEl.classList.add('drag-over');
      });
      cardEl.addEventListener('dragleave', () => cardEl.classList.remove('drag-over'));
      cardEl.addEventListener('drop', e => {
        e.preventDefault();
        cardEl.classList.remove('drag-over');
        const draggedId = e.dataTransfer.getData('text/plain');
        if (!draggedId || draggedId === cardEl.id) return;
        const dragged = document.getElementById(draggedId);
        if (!dragged) return;
        const list = document.getElementById('chain-steps-list');
        const rect = cardEl.getBoundingClientRect();
        const before = (e.clientY - rect.top) < rect.height / 2;
        list.insertBefore(dragged, before ? cardEl : cardEl.nextSibling);
        _renumberSteps();
        requestAnimationFrame(redrawGotoArrows);
      });
    }

    // ── Collect step data from DOM into v2 schema ───────────────────
    function _collectAltData(altEl) {
      const stepEl = altEl.closest('.chain-step-card');
      const type = stepEl.getAttribute('data-card-type');
      const weight = parseInt(altEl.querySelector('.weight-input').value, 10) || 1;
      const data = { weight };
      if (type === 'llm') {
        data.prompt      = altEl.querySelector('.alt-prompt')?.value || '';
        data.context_ids = _collectAltContextIds(altEl);
        data.tools       = [...altEl.querySelectorAll('.tool-chk:checked')].map(c => c.getAttribute('data-name'));
        const presetEl   = altEl.querySelector('.alt-llm-preset');
        data.preset      = presetEl ? (presetEl.value || null) : null;
        const requires = [];
        if (altEl.querySelector('.alt-llm-req-text')?.checked)   requires.push('text');
        if (altEl.querySelector('.alt-llm-req-vision')?.checked) requires.push('vision');
        data.requires = requires;
      } else if (type === 'voice') {
        data.voice_preset_id     = altEl.querySelector('.alt-voice-preset')?.value || null;
        data.prompt              = altEl.querySelector('.alt-prompt')?.value || '';
        data.voice_pre           = altEl.querySelector('.alt-voice-pre')?.value || '';
        data.voice_post          = altEl.querySelector('.alt-voice-post')?.value || '';
        data.voice_preprocess    = !!altEl.querySelector('.alt-voice-preprocess')?.checked;
        data.voice_auto_segment  = !!altEl.querySelector('.alt-voice-auto-segment')?.checked;
      } else if (type === 'write_context') {
        data.ctx_name        = altEl.querySelector('.alt-ctx-name')?.value.trim() || '';
        data.ctx_description = altEl.querySelector('.alt-ctx-description')?.value.trim() || '';
        data.ctx_tags        = (altEl.querySelector('.alt-ctx-tags')?.value || '')
          .split(',').map(s => s.trim()).filter(Boolean);
        data.ctx_pre         = altEl.querySelector('.alt-ctx-pre')?.value || '';
        data.ctx_post        = altEl.querySelector('.alt-ctx-post')?.value || '';
        data.ctx_overwrite   = !!altEl.querySelector('.alt-ctx-overwrite')?.checked;
      } else if (type === 'sequence') {
        data.sequence_id = altEl.querySelector('.alt-seq-select')?.value || null;
      } else if (type === 'image_prompt') {
        data.image_prompt_name     = altEl.querySelector('.alt-image-prompt-name')?.value || '';
        data.image_prompt_workflow = altEl.querySelector('.alt-image-prompt-workflow')?.value || '';
        data.prompt                = altEl.querySelector('.alt-prompt')?.value || '';
      } else if (type === 'save_wildcard') {
        data.wildcard_name = altEl.querySelector('.alt-wildcard-name')?.value || '';
        data.wildcard_mode = altEl.querySelector('.alt-wildcard-mode')?.value || 'append';
        data.prompt        = altEl.querySelector('.alt-prompt')?.value || '';
      } else if (type === 'create_ticket') {
        data.ticket_title_template       = altEl.querySelector('.alt-ticket-title')?.value || '';
        data.ticket_description_template = altEl.querySelector('.alt-ticket-description')?.value || '';
        data.ticket_file_hints           = (altEl.querySelector('.alt-ticket-file-hints')?.value || '')
          .split(',').map(s => s.trim()).filter(Boolean);
      } else if (type === 'goto') {
        const targetCardId = altEl.querySelector('.goto-target-select')?.value || '';
        data.target_card_id = targetCardId;
        data.fall_through   = !!altEl.querySelector('.alt-fall-through')?.checked;
      }
      return data;
    }

    function _collectSteps() {
      _renumberSteps();
      const stepEls = [...document.querySelectorAll('#chain-steps-list > .chain-step-card')];
      const cardIdToNumber = new Map();
      stepEls.forEach((el, i) => cardIdToNumber.set(el.getAttribute('data-card-id'), i + 1));
      const steps = [];
      for (const el of stepEls) {
        const type = el.getAttribute('data-card-type');
        const number = parseInt(el.getAttribute('data-step-number'), 10);
        const name = el.querySelector('.step-name-input').value.trim() || ('Step ' + number);
        const visit_cap = Math.max(1, parseInt(el.querySelector('.visit-cap-input').value, 10) || 100);
        const alts = [...el.querySelectorAll('.alt-card')].map(_collectAltData);
        // Resolve goto target_card_id → numeric target_step
        for (const a of alts) {
          if (type === 'goto') {
            if (a.target_card_id) {
              const n = cardIdToNumber.get(a.target_card_id);
              if (n) a.target_step = n;
            }
            delete a.target_card_id;
            // executor expects exactly one of target_step / fall_through
            if (a.fall_through) { a.target_step = null; }
            else if (a.target_step == null) { a.fall_through = true; }
          }
        }
        steps.push({ number, name, type, visit_cap, alternatives: alts });
      }
      return steps;
    }

    // ── SVG goto-arrow overlay ───────────────────────────────────────
    function redrawGotoArrows() {
      const svg = document.getElementById('goto-arrows');
      const board = document.getElementById('chain-board');
      if (!svg || !board) return;
      const w = board.clientWidth;
      const h = board.scrollHeight;
      svg.setAttribute('width', w);
      svg.setAttribute('height', h);
      svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
      svg.innerHTML =
        '<defs><marker id="goto-arrow-head" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6" markerHeight="6" orient="auto-start-reverse">' +
          '<path d="M0,0 L8,4 L0,8 Z" fill="#c84"/></marker></defs>';
      const cards = [...document.querySelectorAll('#chain-steps-list > .chain-step-card')];
      const cardById = new Map(cards.map(c => [c.getAttribute('data-card-id'), c]));
      const boardRect = board.getBoundingClientRect();
      let drew = 0;
      for (const card of cards) {
        if (card.getAttribute('data-card-type') !== 'goto') continue;
        const alts = [...card.querySelectorAll('.alt-card')];
        let altIndex = 0;
        for (const altEl of alts) {
          altIndex++;
          const ftChk = altEl.querySelector('.alt-fall-through');
          if (ftChk && ftChk.checked) continue;
          const sel = altEl.querySelector('.goto-target-select');
          const targetId = sel ? sel.value : '';
          if (!targetId) continue;
          const target = cardById.get(targetId);
          if (!target) continue;
          const sr = card.getBoundingClientRect();
          const tr = target.getBoundingClientRect();
          const x1 = sr.right - boardRect.left - 2;
          const y1 = sr.top + sr.height / 2 - boardRect.top;
          const x2 = tr.right - boardRect.left - 2;
          const y2 = tr.top + tr.height / 2 - boardRect.top;
          const bulge = 50 + altIndex * 18;
          const cx1 = x1 + bulge;
          const cx2 = x2 + bulge;
          const weightEl = altEl.querySelector('.weight-input');
          const wgt = weightEl ? (weightEl.value || '1') : '1';
          const d = 'M' + x1 + ',' + y1 + ' C' + cx1 + ',' + y1 + ' ' + cx2 + ',' + y2 + ' ' + x2 + ',' + y2;
          svg.insertAdjacentHTML('beforeend',
            '<path d="' + d + '" stroke="#c84" stroke-width="1.5" fill="none" stroke-dasharray="4 3" marker-end="url(#goto-arrow-head)" opacity="0.75"/>' +
            '<text x="' + (Math.max(cx1, cx2) - 6) + '" y="' + ((y1 + y2) / 2) + '" fill="#c84" font-size="10" font-family="monospace" opacity="0.8">w:' + _escHtml(String(wgt)) + '</text>'
          );
          drew++;
        }
      }
    }
    window.addEventListener('resize', () => requestAnimationFrame(redrawGotoArrows));

    // Holds the active EventSource + timeline so submit/recreate flows can reset cleanly.
    let _activeSource = null;
    let _activeTimeline = null;

    function _resetOutputPane() {
      const msg = document.getElementById('chain-msg');
      const hint = document.getElementById('chain-right-hint');
      msg.textContent = '';
      hint.style.display = 'none';
      document.getElementById('chain-artifacts').style.display = 'none';
      document.getElementById('chain-artifacts-list').innerHTML = '';
      const finalCollapse = document.getElementById('chain-final-output-collapse');
      if (finalCollapse) finalCollapse.style.display = 'none';
      const pre = document.getElementById('chain-output-pre');
      if (pre) pre.textContent = '';
      if (_activeSource) { try { _activeSource.close(); } catch (_) {} _activeSource = null; }
      if (!_activeTimeline) {
        _activeTimeline = createTimeline(document.getElementById('chain-timeline'));
      }
      _activeTimeline.reset();
    }

    function _attachEventSourceFor(jobId) {
      const es = new EventSource('/v1/jobs/' + jobId + '/stream');
      _activeSource = es;
      _activeTimeline.attach(es);
      // The timeline closes the source on job_done. We additionally listen
      // for job_done at this level to update the small status message + load
      // artifacts + raw final-output collapse.
      es.addEventListener('job_done', async (e) => {
        let p = {};
        try { p = JSON.parse(e.data); } catch (_) {}
        const msg = document.getElementById('chain-msg');
        if (p.status === 'done') {
          msg.style.color = '#2a6'; msg.textContent = 'Done.';
        } else {
          msg.style.color = '#e44';
          msg.textContent = 'Error: ' + (p.error || 'unknown');
        }
        if (Array.isArray(p.artifacts) && p.artifacts.length) {
          await _renderArtifacts(jobId, p.artifacts);
        }
        if (typeof p.final_output === 'string') {
          const pre = document.getElementById('chain-output-pre');
          const wrap = document.getElementById('chain-final-output-collapse');
          if (pre) pre.textContent = p.final_output;
          if (wrap) wrap.style.display = 'block';
        } else {
          // Fall back to fetching the file for historical jobs whose
          // job_done payload didn't include final_output.
          try {
            const or = await fetch('/v1/jobs/' + jobId + '/files/final_output.txt');
            if (or.ok) {
              const pre = document.getElementById('chain-output-pre');
              const wrap = document.getElementById('chain-final-output-collapse');
              if (pre) pre.textContent = await or.text();
              if (wrap) wrap.style.display = 'block';
            }
          } catch (_) {}
          try {
            const ar = await fetch('/v1/jobs/' + jobId + '/files/artifacts.json');
            if (ar.ok) await _renderArtifacts(jobId, await ar.json());
          } catch (_) {}
        }
      });
      es.addEventListener('error', () => {
        // EventSource auto-reconnects; nothing to do unless we want to
        // surface the disconnection — leave silent for now.
      });
      return es;
    }

    // ── Sequence-form prompt for variables, then submit ─────────────
    async function submitChain() {
      const msg = document.getElementById('chain-msg');
      _resetOutputPane();

      _collectVariablesFromDom();
      const steps = _collectSteps();
      if (steps.length === 0) {
        msg.style.color = '#e44'; msg.textContent = 'Add at least one step.'; return;
      }
      const validateErr = _validateSteps(steps);
      if (validateErr) { msg.style.color = '#e44'; msg.textContent = validateErr; return; }

      // Endpoint preset is now optional — when none is configured the backend
      // falls back to the llm-capable node (gpu.local in the multi-machine setup).
      const _defPreset = _chainPresets.find(p => p.id === _defaultPresetId) || _chainPresets[0] || null;

      // Prompt for variable values if any are declared.
      let variableOverrides = {};
      if (_variables.length > 0) {
        const got = await _promptForVariables();
        if (got === null) { msg.textContent = 'Cancelled.'; return; }
        variableOverrides = got;
      }

      // Resolve %%wildcard%% tokens inside every alternative's text fields.
      for (const step of steps) {
        for (const alt of step.alternatives) {
          for (const k of ['prompt','voice_pre','voice_post','ctx_pre','ctx_post',
                            'image_prompt_name','wildcard_name','ticket_title_template','ticket_description_template']) {
            if (alt[k]) alt[k] = await resolveWildcards(alt[k]);
          }
        }
      }

      const body = {
        schema_version: 2,
        steps,
        variables: variableOverrides,
        sequence_variables: _variables,
      };
      if (_defPreset) {
        body.llm = {
          api_base:    _defPreset.api_base,
          model:       _defPreset.model,
          temperature: _defPreset.temperature,
          max_tokens:  _defPreset.max_tokens,
        };
      }

      try {
        const job = await api('/jobs/chain', 'POST', body);
        msg.style.color = '#fa0';
        msg.textContent = 'Job ' + job.job_id.slice(0, 8) + '… running';
        _attachEventSourceFor(job.job_id);
      } catch (e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    function _validateSteps(steps) {
      for (const s of steps) {
        for (const a of s.alternatives) {
          if (s.type === 'voice'         && !a.voice_preset_id)  return 'Select a voice preset for every voice alternative.';
          if (s.type === 'write_context' && !a.ctx_name)         return 'Enter a context name for every write_context alternative.';
          if (s.type === 'sequence'      && !a.sequence_id)      return 'Select a sequence for every sequence alternative.';
          if (s.type === 'image_prompt'  && !a.image_prompt_name) return 'Set an image prompt name for every image_prompt alternative.';
          if (s.type === 'save_wildcard' && !a.wildcard_name)    return 'Set a wildcard name for every save_wildcard alternative.';
          if (s.type === 'create_ticket' && !a.ticket_title_template) return 'Set a ticket title for every create_ticket alternative.';
          if (s.type === 'goto') {
            if (!a.fall_through && a.target_step == null) return 'Each goto alternative needs either a target step or fall-through.';
          }
        }
      }
      return null;
    }

    function _promptForVariables() {
      return new Promise(resolve => {
        const dlg = document.getElementById('run-vars-dialog');
        const fields = document.getElementById('run-vars-fields');
        fields.innerHTML = _variables.map(v => {
          const safeName = _escHtml(v.name);
          const safeDef  = _escHtml(v.default || '');
          if (v.choices && v.choices.length) {
            const opts = v.choices.map(c =>
              '<option value="' + _escHtml(c) + '"' + (c === v.default ? ' selected' : '') + '>' + _escHtml(c) + '</option>'
            ).join('');
            return '<div class="run-var-row"><label>' + safeName + '</label>' +
              '<select data-var-name="' + safeName + '">' + opts + '</select></div>';
          }
          return '<div class="run-var-row"><label>' + safeName + '</label>' +
            '<input type="text" data-var-name="' + safeName + '" value="' + safeDef + '"></input></div>';
        }).join('');
        const onClose = () => {
          dlg.removeEventListener('close', onClose);
          if (dlg.returnValue !== 'run') { resolve(null); return; }
          const out = {};
          for (const f of fields.querySelectorAll('[data-var-name]')) out[f.getAttribute('data-var-name')] = f.value;
          resolve(out);
        };
        dlg.addEventListener('close', onClose);
        if (typeof dlg.showModal === 'function') dlg.showModal();
        else dlg.setAttribute('open', '');
      });
    }

    function _onLlmRequiresChange(input) {
      const altEl = input.closest('.alt-card');
      if (!altEl) return;
      const sel = altEl.querySelector('.alt-llm-preset');
      if (!sel) return;
      const requires = [];
      if (altEl.querySelector('.alt-llm-req-text')?.checked) requires.push('text');
      if (altEl.querySelector('.alt-llm-req-vision')?.checked) requires.push('vision');
      sel.innerHTML = _llmModelPresetOptions(sel.value, requires);
    }
    function _onLlmPresetChange(_sel) { /* future hook */ }

    function _fmtBytes(n) {
      if (n < 1024) return n + ' B';
      if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
      return (n / 1024 / 1024).toFixed(1) + ' MB';
    }

    async function _renderArtifacts(jobId, artifacts) {
      const container = document.getElementById('chain-artifacts-list');
      const panel = document.getElementById('chain-artifacts');
      if (!artifacts || artifacts.length === 0) return;
      const nonFinal = artifacts.filter(a => a.filename !== 'final_output.txt');
      if (nonFinal.length === 0) return;
      const baseUrl = '/v1/jobs/' + jobId + '/files/';
      let html = '';
      for (const a of nonFinal) {
        const url = baseUrl + a.filename;
        const size = a.size != null ? _fmtBytes(a.size) : '';
        const isAudio = /\.(wav|mp3|ogg)$/i.test(a.filename);
        const isImage = /\.(png|jpg|jpeg|gif|webp)$/i.test(a.filename);
        html += '<div class="artifact-row">' +
          '<span class="artifact-name">' + _escHtml(a.filename) + '</span>' +
          '<span class="artifact-size">' + size + '</span>' +
          '</div>';
        if (isAudio) html += '<audio controls style="width:100%;margin-bottom:6px;" src="' + url + '"></audio>';
        else if (isImage) html += '<img src="' + url + '" style="max-width:100%;margin-bottom:6px;border-radius:3px;" alt="">';
      }
      container.innerHTML = html;
      panel.style.display = 'block';
    }

    // ── Recreate hydration (best-effort) ─────────────────────────────
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
      _resetForm();
      _variables = (req.sequence_variables || []).map(v => ({
        name: v.name || '', default: v.default || '', choices: Array.isArray(v.choices) ? v.choices : [],
      }));
      _renderVariablesPane();
      for (const step of (req.steps || [])) {
        const alternatives = (step.alternatives && step.alternatives.length)
          ? step.alternatives
          : [_v1ShorthandToAlt(step)];
        addChainStep({
          type: step.type || 'llm',
          name: step.name,
          number: step.number || 0,
          visit_cap: step.visit_cap || 100,
          alternatives,
        });
      }
      _renumberSteps();
      requestAnimationFrame(redrawGotoArrows);
      // Replay the original job's timeline alongside the rebuilt form.
      try {
        _resetOutputPane();
        _attachEventSourceFor(jobId);
      } catch (_) {}
    }

    // ── Init ────────────────────────────────────────────────────────
    Promise.all([_loadChainPresets(), _loadLlmModelPresets(), loadContextItems(), loadVoicePresets(), loadSeqs(), loadMcpTools()]).then(() => {
      _renderVariablesPane();
      if (_recreateId) {
        _hydrateFromRecreate(_recreateId);
        switchTab('chain');
        return;
      }
      const params = new URLSearchParams(window.location.search);
      const seqParam = params.get('sequence');
      if (seqParam) {
        const seq = _allSeqs.find(s => s.id === seqParam);
        if (seq) { _editSeq(seqParam); return; }
      }
      addChainStep({ alternatives: [{ prompt: 'Create five bullet points for the following task:\n\n' }] });
      switchTab('chain');
    });
