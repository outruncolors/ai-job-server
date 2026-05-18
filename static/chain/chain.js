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
    }

    // ── LLM Presets (server-side, used silently at submit time) ──────
    let _currentSeqId    = null;
    let _activeTab       = 'chain';
    let _chainPresets    = [];
    let _defaultPresetId = null;

    async function _loadChainPresets() {
      try {
        const data = await api('/llm-endpoints');
        _chainPresets    = data.presets || [];
        _defaultPresetId = data.default_preset_id || null;
      } catch (_) {}
    }

    // ── Sequences ─────────────────────────────────────────────────────
    let _allSeqs = [];

    function _renderSeqList() {
      const el = document.getElementById('seq-list');
      if (_allSeqs.length === 0) {
        el.innerHTML = '<div style="color:#333;font-size:0.72rem;">No sequences saved.</div>';
        return;
      }
      const usedBy = {};
      const usesMap = {};
      for (const s of _allSeqs) {
        usedBy[s.id] = usedBy[s.id] || [];
        usesMap[s.id] = [];
        for (const step of (s.steps || [])) {
          if (step.type === 'sequence' && step.sequence_id) {
            const dep = _allSeqs.find(x => x.id === step.sequence_id);
            if (dep) {
              usesMap[s.id].push(dep.name);
              usedBy[dep.id] = usedBy[dep.id] || [];
              if (!usedBy[dep.id].includes(s.name)) usedBy[dep.id].push(s.name);
            }
          }
        }
      }
      let html = '';
      for (const s of _allSeqs) {
        const isActive = s.id === _currentSeqId;
        const depParts = [];
        if (usesMap[s.id] && usesMap[s.id].length > 0)
          depParts.push('uses: ' + usesMap[s.id].join(', '));
        if (usedBy[s.id] && usedBy[s.id].length > 0)
          depParts.push('used by: ' + usedBy[s.id].join(', '));
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
      } catch(e) { /* silently fail */ }
    }

    function _newSeq() {
      _currentSeqId = null;
      document.getElementById('chain-seq-name').value = '';
      document.getElementById('seq-edit-msg').textContent = '';
      document.getElementById('chain-steps-list').innerHTML = '';
      _chainStepCounter = 0;
      addChainStep({ prompt: 'Create five bullet points for the following task:\n\n' });
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
      loadStepsIntoForm(seq.steps);
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
          document.getElementById('chain-steps-list').innerHTML = '';
          _chainStepCounter = 0;
          addChainStep({ prompt: 'Create five bullet points for the following task:\n\n' });
          document.getElementById('seq-edit-bar').style.display = 'none';
          history.replaceState(null, '', '/chain');
        }
        await loadSeqs();
      } catch(e) { alert('Error: ' + e.message); }
    }

    async function saveSeq() {
      const name = document.getElementById('chain-seq-name').value.trim();
      const msgEl = document.getElementById('seq-edit-msg');
      msgEl.textContent = '';
      if (!name) { msgEl.style.color = '#e44'; msgEl.textContent = 'Enter a sequence name.'; return; }
      const steps = _collectSteps();
      if (steps.length === 0) { msgEl.style.color = '#e44'; msgEl.textContent = 'Add at least one step.'; return; }
      try {
        const saved = await api('/chain-sequences', 'POST', { name, steps });
        _currentSeqId = saved.id;
        history.replaceState(null, '', '/chain?sequence=' + saved.id);
        msgEl.style.color = '#2a6'; msgEl.textContent = 'Saved.';
        await loadSeqs();
      } catch(e) {
        msgEl.style.color = '#e44'; msgEl.textContent = 'Error: ' + e.message;
      }
    }

    function loadStepsIntoForm(steps) {
      document.getElementById('chain-steps-list').innerHTML = '';
      _chainStepCounter = 0;
      for (const s of steps) {
        addChainStep({
          type: s.type, prompt: s.prompt || '', context_ids: s.context_ids || [],
          tools: s.tools || [],
          voice_preset_id: s.voice_preset_id || '',
          voice_pre: s.voice_pre || '', voice_post: s.voice_post || '',
          voice_preprocess: !!s.voice_preprocess, voice_auto_segment: !!s.voice_auto_segment,
          ctx_name: s.ctx_name || '', ctx_description: s.ctx_description || '',
          ctx_tags: s.ctx_tags || [], ctx_pre: s.ctx_pre || '', ctx_post: s.ctx_post || '',
          ctx_overwrite: !!s.ctx_overwrite,
          sequence_id: s.sequence_id || '',
        });
      }
    }

    // ── Context library ──────────────────────────────────────────────
    let _ctxItems = [];

    async function loadContextItems() {
      try {
        const data = await api('/context-items');
        _ctxItems = data.items || [];
      } catch(e) { _ctxItems = []; }
    }

    function _allTags() {
      const set = new Set();
      for (const item of _ctxItems) (item.tags || []).forEach(t => set.add(t));
      return [...set].sort();
    }

    function _buildCtxSelector(stepEl, selectedIds) {
      const sel = stepEl.querySelector('.ctx-selector');
      if (!sel) return;
      const selectedTagsEl = stepEl.querySelector('.ctx-selected-tags');
      const treeEl = stepEl.querySelector('.ctx-tree');
      const datalistId = sel.getAttribute('data-list-id');
      const datalist = document.getElementById(datalistId);

      // Build datalist for tag autocomplete
      const allTags = _allTags();
      if (datalist) {
        datalist.innerHTML = allTags.map(t => `<option value="${t}">`).join('');
      }

      // Group items by tag
      const byTag = {};
      const untagged = [];
      for (const item of _ctxItems) {
        if (!item.tags || item.tags.length === 0) {
          untagged.push(item);
        } else {
          for (const tag of item.tags) {
            if (!byTag[tag]) byTag[tag] = [];
            byTag[tag].push(item);
          }
        }
      }

      const selectedTagsList = _getSelectedTags(stepEl);
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
          const items = byTag[tag];
          html += `<details class="ctx-group" open><summary>${tag} (${items.length})</summary>`;
          for (const item of items) {
            html += _entryHtml(item, selectedIds.has(item.id) || tagSelectedIds.has(item.id));
          }
          html += '</details>';
        }
        if (untagged.length > 0) {
          html += `<details class="ctx-group" open><summary>untagged (${untagged.length})</summary>`;
          for (const item of untagged) {
            html += _entryHtml(item, selectedIds.has(item.id) || tagSelectedIds.has(item.id));
          }
          html += '</details>';
        }
        treeEl.innerHTML = html;
      }
      _updateCtxCount(stepEl);
    }

    function _getSelectedTags(stepEl) {
      return [...stepEl.querySelectorAll('.ctx-tag-row .ctx-tag-chip')]
        .map(chip => chip.getAttribute('data-tag'));
    }

    function _addTag(stepEl, tag) {
      tag = tag.trim();
      if (!tag) return;
      const existing = _getSelectedTags(stepEl);
      if (existing.includes(tag)) return;
      const row = stepEl.querySelector('.ctx-tag-row');
      const input = row.querySelector('.ctx-tag-input');
      const chip = document.createElement('span');
      chip.className = 'ctx-tag-chip';
      chip.setAttribute('data-tag', tag);
      chip.innerHTML = _escHtml(tag) + `<button onclick="_removeTag(this.closest('.chain-step-card'), '${tag.replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">×</button>`;
      row.insertBefore(chip, input);
      _rebuildTree(stepEl);
    }

    function _removeTag(stepEl, tag) {
      const chip = [...stepEl.querySelectorAll('.ctx-tag-row .ctx-tag-chip')]
        .find(c => c.getAttribute('data-tag') === tag);
      if (chip) chip.remove();
      _rebuildTree(stepEl);
    }

    function _rebuildTree(stepEl) {
      const checked = new Set(
        [...stepEl.querySelectorAll('.ctx-chk:checked')].map(c => c.getAttribute('data-id'))
      );
      _buildCtxSelector(stepEl, checked);
    }

    function _onEntryClick(event, entry) {
      const chk = entry.querySelector('.ctx-chk');
      if (!chk) return;
      if (event.target !== chk) {
        // Click was on the row text, not the checkbox — toggle manually
        chk.checked = !chk.checked;
      }
      entry.classList.toggle('is-checked', chk.checked);
      const stepEl = entry.closest('.chain-step-card');
      if (stepEl) _updateCtxCount(stepEl);
    }

    function _updateCtxCount(stepEl) {
      const ids = _collectStepContextIds(stepEl);
      const summary = stepEl.querySelector('.ctx-selector > summary');
      const countEl = summary && summary.querySelector('.ctx-count');
      if (countEl) countEl.textContent = ids.length > 0 ? `(${ids.length})` : '';
    }

    function _collectStepContextIds(stepEl) {
      const checkedIds = new Set(
        [...stepEl.querySelectorAll('.ctx-chk:checked')].map(c => c.getAttribute('data-id'))
      );
      const selectedTags = _getSelectedTags(stepEl);
      for (const tag of selectedTags) {
        for (const item of _ctxItems) {
          if ((item.tags || []).includes(tag)) checkedIds.add(item.id);
        }
      }
      return [...checkedIds];
    }

    // ── Voice presets (for chain voice steps) ───────────────────────
    let _voicePresets = [];

    async function loadVoicePresets() {
      try {
        const data = await api('/voice-presets');
        _voicePresets = data || [];
      } catch(e) { _voicePresets = []; }
    }

    let _mcpTools = [];

    async function loadMcpTools() {
      try {
        const data = await api('/mcp/tools');
        _mcpTools = data.tools || [];
      } catch(e) { _mcpTools = []; }
    }

    function _voicePresetOptions(selectedId) {
      const opts = '<option value="">— select preset —</option>' +
        _voicePresets.map(p =>
          `<option value="${p.id}"${p.id === selectedId ? ' selected' : ''}>${_escHtml(p.name)}</option>`
        ).join('');
      return opts;
    }

    function _seqOptions(selectedId) {
      return '<option value="">— select sequence —</option>' +
        _allSeqs.map(s =>
          `<option value="${s.id}"${s.id === selectedId ? ' selected' : ''}>${_escHtml(s.name)}</option>`
        ).join('');
    }

    // ── Chain ────────────────────────────────────────────────────────
    const _CHAIN_DEFAULT_PROMPT =
      'Using the previous output, continue the task.\n\nPrevious:\n{{previous}}';
    let _chainStepCounter  = 0;
    let _chainJobPollTimer = null;

    function addChainStep(opts = {}) {
      const type       = opts.type || 'llm';
      const prompt     = opts.prompt !== undefined ? opts.prompt : _CHAIN_DEFAULT_PROMPT;
      const contextIds = opts.context_ids || [];
      const toolNames  = opts.tools || [];
      const presetId   = opts.voice_preset_id || '';
      const voicePre        = opts.voice_pre || '';
      const voicePost       = opts.voice_post || '';
      const voicePreprocess = !!opts.voice_preprocess;
      const voiceAutoSegment = !!opts.voice_auto_segment;
      const ctxName        = opts.ctx_name || '';
      const ctxDescription = opts.ctx_description || '';
      const ctxTags        = (opts.ctx_tags || []).join(', ');
      const ctxPre         = opts.ctx_pre || '';
      const ctxPost        = opts.ctx_post || '';
      const ctxOverwrite   = !!opts.ctx_overwrite;
      const seqId          = opts.sequence_id || '';

      const isFirst = document.querySelectorAll('#chain-steps-list > .chain-step-card').length === 0;
      const idx    = _chainStepCounter++;
      const id     = `chain-step-${idx}`;
      const listId = `ctx-list-${idx}`;
      const el     = document.createElement('div');
      el.id = id; el.className = 'chain-step-card';

      const kindSel =
        '<select class="chain-step-kind" onchange="_onStepKindChange(this)">' +
          '<option value="llm"' + (type === 'llm' ? ' selected' : '') + '>text</option>' +
          '<option value="voice"' + (type === 'voice' ? ' selected' : '') + (isFirst ? ' disabled' : '') + '>voice</option>' +
          '<option value="write_context"' + (type === 'write_context' ? ' selected' : '') + '>write context</option>' +
          '<option value="sequence"' + (type === 'sequence' ? ' selected' : '') + '>sequence</option>' +
        '</select>';

      el.innerHTML =
        '<div class="chain-step-head">' +
          '<span>Step</span>' +
          '<div style="display:flex;gap:6px;align-items:center;">' +
            kindSel +
            '<button class="secondary" onclick="removeChainStep(\'' + id + '\')" ' +
              'style="margin-top:0;padding:2px 8px;font-size:0.7rem;">Remove</button>' +
          '</div>' +
        '</div>' +
        '<div class="chain-step-text-fields"' + (type !== 'llm' ? ' style="display:none;"' : '') + '>' +
          '<label>Prompt</label>' +
          '<textarea class="chain-step-prompt" style="min-height:72px;">' + _escHtml(prompt) + '</textarea>' +
          '<datalist id="' + listId + '"></datalist>' +
          '<details class="ctx-selector" data-list-id="' + listId + '">' +
            '<summary>Context <span class="ctx-count"></span></summary>' +
            '<div class="ctx-body">' +
              '<div class="ctx-tag-row">' +
                '<input class="ctx-tag-input" type="text" list="' + listId + '" placeholder="Add tag…" ' +
                  'onkeydown="if(event.key===\'Enter\'||event.key===\',\'){event.preventDefault();_addTag(this.closest(\'.chain-step-card\'),this.value);this.value=\'\'}" ' +
                  'onchange="_addTag(this.closest(\'.chain-step-card\'),this.value);this.value=\'\'">' +
              '</div>' +
              '<div class="ctx-tree"></div>' +
            '</div>' +
          '</details>' +
          '<details class="ctx-selector" style="margin-top:6px;">' +
            '<summary>Tools <span class="ctx-count">' + (toolNames.length ? '(' + toolNames.length + ')' : '') + '</span></summary>' +
            '<div class="ctx-body">' +
              (_mcpTools.length === 0
                ? '<div style="color:#333;font-size:0.72rem;padding:4px 0;">No tools registered.</div>'
                : _mcpTools.map(t =>
                    '<label style="display:flex;align-items:flex-start;gap:6px;cursor:pointer;padding:3px 0;">' +
                      '<input type="checkbox" class="tool-chk" data-name="' + _escHtml(t.name) + '"' +
                        (toolNames.includes(t.name) ? ' checked' : '') + '>' +
                      '<div>' +
                        '<div style="color:#aaa;font-size:0.74rem;">' + _escHtml(t.name) + '</div>' +
                        '<div style="color:#444;font-size:0.68rem;">' + _escHtml(t.description) + '</div>' +
                      '</div>' +
                    '</label>'
                  ).join('')
              ) +
            '</div>' +
          '</details>' +
        '</div>' +
        '<div class="chain-step-voice-fields"' + (type !== 'voice' ? ' style="display:none;"' : '') + '>' +
          '<label>Voice Preset</label>' +
          (_voicePresets.length === 0
            ? '<div style="color:#555;font-size:0.74rem;margin-top:4px;">No presets — <a href="/voice" style="color:#2a6;">create one at /voice</a></div>'
            : '<select class="chain-step-voice-preset">' + _voicePresetOptions(presetId) + '</select>') +
          '<label>Pre <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="chain-step-voice-pre" style="min-height:48px;">' + _escHtml(voicePre) + '</textarea>' +
          '<label>Post <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="chain-step-voice-post" style="min-height:48px;">' + _escHtml(voicePost) + '</textarea>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:10px;cursor:pointer;">' +
            '<input type="checkbox" class="chain-step-voice-preprocess"' + (voicePreprocess ? ' checked' : '') + '>' +
            'Pre-process for speech' +
            '<span style="color:#383838;font-size:0.7rem;">(clean text via LLM before TTS)</span>' +
          '</label>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:6px;cursor:pointer;">' +
            '<input type="checkbox" class="chain-step-voice-auto-segment"' + (voiceAutoSegment ? ' checked' : '') + '>' +
            'Auto-segment via LLM' +
            '<span style="color:#383838;font-size:0.7rem;">(LLM splits text and sets pause timings)</span>' +
          '</label>' +
        '</div>' +
        '<div class="chain-step-write-context-fields"' + (type !== 'write_context' ? ' style="display:none;"' : '') + '>' +
          '<label>Context Name</label>' +
          '<input class="chain-step-ctx-name" type="text" placeholder="my-notes" value="' + _escHtml(ctxName) + '">' +
          '<label>Tags <span style="color:#383838;font-size:0.7rem;">(comma-separated)</span></label>' +
          '<input class="chain-step-ctx-tags" type="text" placeholder="journal, daily…" value="' + _escHtml(ctxTags) + '">' +
          '<label>Description <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="chain-step-ctx-description" style="min-height:48px;" placeholder="Short description…">' + _escHtml(ctxDescription) + '</textarea>' +
          '<label>Pre <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="chain-step-ctx-pre" style="min-height:48px;">' + _escHtml(ctxPre) + '</textarea>' +
          '<label>Post <span style="color:#383838;font-size:0.7rem;">(optional)</span></label>' +
          '<textarea class="chain-step-ctx-post" style="min-height:48px;">' + _escHtml(ctxPost) + '</textarea>' +
          '<label style="display:flex;align-items:center;gap:6px;margin-top:10px;cursor:pointer;">' +
            '<input type="checkbox" class="chain-step-ctx-overwrite"' + (ctxOverwrite ? ' checked' : '') + '>' +
            'Overwrite' +
          '</label>' +
        '</div>' +
        '<div class="chain-step-sequence-fields"' + (type !== 'sequence' ? ' style="display:none;"' : '') + '>' +
          '<label>Sequence</label>' +
          '<select class="chain-step-seq-select">' + _seqOptions(seqId) + '</select>' +
        '</div>';

      document.getElementById('chain-steps-list').appendChild(el);
      _buildCtxSelector(el, new Set(contextIds));
      _refreshFirstStepVoiceDisable();
    }

    function _refreshFirstStepVoiceDisable() {
      const cards = document.querySelectorAll('#chain-steps-list > .chain-step-card');
      cards.forEach((card, i) => {
        const voiceOpt = card.querySelector('.chain-step-kind option[value="voice"]');
        if (!voiceOpt) return;
        voiceOpt.disabled = (i === 0);
        if (i === 0 && card.querySelector('.chain-step-kind').value === 'voice') {
          card.querySelector('.chain-step-kind').value = 'llm';
          _onStepKindChange(card.querySelector('.chain-step-kind'));
        }
      });
    }

    function _onStepKindChange(sel) {
      const card = sel.closest('.chain-step-card');
      const kind = sel.value;
      card.querySelector('.chain-step-text-fields').style.display = kind === 'llm' ? '' : 'none';
      card.querySelector('.chain-step-voice-fields').style.display = kind === 'voice' ? '' : 'none';
      card.querySelector('.chain-step-write-context-fields').style.display = kind === 'write_context' ? '' : 'none';
      card.querySelector('.chain-step-sequence-fields').style.display = kind === 'sequence' ? '' : 'none';
      if (kind === 'voice') {
        const presetSel = card.querySelector('.chain-step-voice-preset');
        if (presetSel) {
          const currentVal = presetSel.value;
          presetSel.innerHTML = _voicePresetOptions(currentVal);
        }
      }
      if (kind === 'sequence') {
        const seqSel = card.querySelector('.chain-step-seq-select');
        if (seqSel) {
          const currentVal = seqSel.value;
          seqSel.innerHTML = _seqOptions(currentVal);
        }
      }
    }

    function removeChainStep(id) {
      const el = document.getElementById(id);
      if (el) el.remove();
      _refreshFirstStepVoiceDisable();
    }

    function _collectSteps() {
      const stepEls = document.querySelectorAll('#chain-steps-list > .chain-step-card');
      const steps = [];
      let i = 0;
      for (const el of stepEls) {
        const kind = el.querySelector('.chain-step-kind').value;
        if (kind === 'voice') {
          const presetId        = el.querySelector('.chain-step-voice-preset').value;
          const voice_pre       = el.querySelector('.chain-step-voice-pre').value;
          const voice_post      = el.querySelector('.chain-step-voice-post').value;
          const voice_preprocess = el.querySelector('.chain-step-voice-preprocess').checked;
          const voice_auto_segment = el.querySelector('.chain-step-voice-auto-segment').checked;
          steps.push({ name: 'Step ' + (++i), type: 'voice', prompt: '', context_ids: [], voice_preset_id: presetId || null, voice_pre, voice_post, voice_preprocess, voice_auto_segment });
        } else if (kind === 'write_context') {
          const ctx_name        = el.querySelector('.chain-step-ctx-name').value.trim();
          const ctx_description = el.querySelector('.chain-step-ctx-description').value.trim();
          const ctx_tags        = el.querySelector('.chain-step-ctx-tags').value
            .split(',').map(s => s.trim()).filter(Boolean);
          const ctx_pre         = el.querySelector('.chain-step-ctx-pre').value;
          const ctx_post        = el.querySelector('.chain-step-ctx-post').value;
          const ctx_overwrite   = el.querySelector('.chain-step-ctx-overwrite').checked;
          steps.push({ name: 'Step ' + (++i), type: 'write_context', ctx_name, ctx_description, ctx_tags, ctx_pre, ctx_post, ctx_overwrite });
        } else if (kind === 'sequence') {
          const sequence_id = el.querySelector('.chain-step-seq-select').value || null;
          steps.push({ name: 'Step ' + (++i), type: 'sequence', sequence_id });
        } else {
          const prompt = el.querySelector('.chain-step-prompt').value;
          const context_ids = _collectStepContextIds(el);
          const tools = [...el.querySelectorAll('.tool-chk:checked')].map(c => c.getAttribute('data-name'));
          steps.push({ name: 'Step ' + (++i), type: 'llm', prompt, context_ids, tools });
        }
      }
      return steps;
    }

    async function submitChain() {
      const msg           = document.getElementById('chain-msg');
      const stepStatusDiv = document.getElementById('chain-step-status');
      const outputDiv     = document.getElementById('chain-output');
      const hint          = document.getElementById('chain-right-hint');
      msg.textContent = ''; stepStatusDiv.innerHTML = ''; outputDiv.style.display = 'none';
      document.getElementById('chain-final-context').style.display = 'none';
      document.getElementById('chain-final-input').style.display = 'none';
      document.getElementById('chain-final-tool-calls').style.display = 'none';
      document.getElementById('chain-final-audio').style.display = 'none';
      document.getElementById('chain-artifacts').style.display = 'none';
      document.getElementById('chain-artifacts-list').innerHTML = '';

      const steps = _collectSteps();
      if (steps.length === 0) {
        msg.style.color = '#e44'; msg.textContent = 'Add at least one step.'; return;
      }
      const missingPreset = steps.some(s => s.type === 'voice' && !s.voice_preset_id);
      if (missingPreset) {
        msg.style.color = '#e44'; msg.textContent = 'Select a voice preset for every voice step.'; return;
      }
      const missingCtxName = steps.some(s => s.type === 'write_context' && !s.ctx_name);
      if (missingCtxName) {
        msg.style.color = '#e44'; msg.textContent = 'Enter a context name for every write context step.'; return;
      }
      const missingSeq = steps.some(s => s.type === 'sequence' && !s.sequence_id);
      if (missingSeq) {
        msg.style.color = '#e44'; msg.textContent = 'Select a sequence for every sequence step.'; return;
      }

      const _defPreset = _chainPresets.find(p => p.id === _defaultPresetId) || _chainPresets[0] || null;
      if (!_defPreset) {
        msg.style.color = '#e44';
        msg.textContent = 'No LLM preset configured — add one in Server → LLM.';
        return;
      }
      for (const step of steps) {
        if (step.prompt)     step.prompt     = await resolveWildcards(step.prompt);
        if (step.voice_pre)  step.voice_pre  = await resolveWildcards(step.voice_pre);
        if (step.voice_post) step.voice_post = await resolveWildcards(step.voice_post);
        if (step.ctx_pre)    step.ctx_pre    = await resolveWildcards(step.ctx_pre);
        if (step.ctx_post)   step.ctx_post   = await resolveWildcards(step.ctx_post);
      }
      const body = {
        llm: {
          api_base:    _defPreset.api_base,
          model:       _defPreset.model,
          temperature: _defPreset.temperature,
          max_tokens:  _defPreset.max_tokens,
        },
        steps,
      };

      try {
        hint.style.display = 'none';
        const job = await api('/jobs/chain', 'POST', body);
        msg.style.color = '#fa0';
        msg.textContent = 'Job ' + job.job_id.slice(0, 8) + '… running';
        if (_chainJobPollTimer) clearInterval(_chainJobPollTimer);
        _chainJobPollTimer = setInterval(() => _pollChainJob(job.job_id), 3000);
      } catch (e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    function _stepCollapseHtml(step, stepIndex, files) {
      const cls = step.status === 'error' ? 'status-failed' : statusClass(step.status);
      const typeTag = step.type === 'voice'
        ? ' <span style="color:#555;font-size:0.66rem;">voice</span>'
        : step.type === 'write_context'
          ? ' <span style="color:#555;font-size:0.66rem;">write context</span>'
          : '';
      let bodyHtml = '';
      if (step.type === 'voice') {
        if (files && files.audioUrl) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">AUDIO</p>' +
            '<audio controls style="width:100%;margin-top:4px;" src="' + files.audioUrl + '"></audio>';
        } else if (step.error) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">ERROR</p>' +
            '<pre class="output-pre status-failed">' + _escHtml(step.error) + '</pre>';
        }
        if (files && (files.autoSegPrompt != null || files.autoSegRaw != null)) {
          let inner = '';
          if (files.autoSegPrompt != null) {
            inner += '<details style="margin-bottom:6px;"><summary style="font-size:0.72rem;color:#555;cursor:pointer;">PROMPT</summary>' +
              '<pre class="output-pre" style="margin-top:4px;">' + _escHtml(files.autoSegPrompt) + '</pre></details>';
          }
          if (files.autoSegRaw != null) {
            inner += '<details><summary style="font-size:0.72rem;color:#555;cursor:pointer;">RAW RESPONSE</summary>' +
              '<pre class="output-pre" style="margin-top:4px;font-size:0.68rem;">' + _escHtml(files.autoSegRaw) + '</pre></details>';
          }
          bodyHtml += '<details style="margin-top:10px;border:1px solid #1e1e1e;border-radius:3px;padding:6px 8px;background:#0a0a0a;">' +
            '<summary style="font-size:0.72rem;color:#555;cursor:pointer;list-style:none;">' +
              '<span style="color:#444;">▸ </span>INTERNAL REQUESTS · auto_segment</summary>' +
            '<div style="margin-top:6px;">' + inner + '</div></details>';
        }
      } else if (step.type === 'write_context') {
        if (files && files.itemTitle) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">CONTEXT ITEM</p>' +
            '<div style="font-size:0.8rem;color:#aaa;">' + _escHtml(files.itemTitle) + '</div>';
        } else if (step.error) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">ERROR</p>' +
            '<pre class="output-pre status-failed">' + _escHtml(step.error) + '</pre>';
        }
      } else {
        const { contextText, promptText, outputText } = files || {};
        if (contextText) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">CONTEXT</p>' +
            '<pre class="output-pre">' + _escHtml(contextText) + '</pre>';
        }
        if (promptText != null) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">PROMPT</p>' +
            '<pre class="output-pre">' + _escHtml(promptText) + '</pre>';
        }
        if (outputText != null) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">OUTPUT</p>' +
            '<pre class="output-pre">' + _escHtml(outputText) + '</pre>';
        }
        if (files && files.toolCallsData && files.toolCallsData.length > 0) {
          bodyHtml += '<details style="margin-top:10px;border:1px solid #1e1e1e;border-radius:3px;padding:6px 8px;background:#0a0a0a;">' +
            '<summary style="font-size:0.72rem;color:#555;cursor:pointer;list-style:none;">' +
              '<span style="color:#444;">▸ </span>TOOL CALLS · ' + files.toolCallsData.length + '</summary>' +
            '<pre class="output-pre" style="margin-top:6px;font-size:0.68rem;">' + _escHtml(JSON.stringify(files.toolCallsData, null, 2)) + '</pre>' +
            '</details>';
        }
        if (outputText == null && step.error) {
          bodyHtml += '<p class="section-label" style="margin:10px 0 4px;">ERROR</p>' +
            '<pre class="output-pre status-failed">' + _escHtml(step.error) + '</pre>';
        }
      }
      return '<details class="step-collapse">' +
        '<summary>' +
          '<span class="step-num">Step ' + stepIndex + '</span>' +
          '<span class="step-sep">·</span>' +
          '<span class="step-col-name">' + _escHtml(step.name) + typeTag + '</span>' +
          '<span class="' + cls + '">' + step.status + '</span>' +
        '</summary>' +
        '<div class="step-collapse-body">' + bodyHtml + '</div>' +
        '</details>';
    }

    async function _fetchStepFiles(jobId, step, arrayIndex) {
      const dirName = String(arrayIndex + 1).padStart(3, '0') + '_' + step.id;
      const base = '/v1/jobs/' + jobId + '/files/steps/' + dirName + '/';
      if (step.type === 'voice') {
        const audioFile = step.output_file || 'output.wav';
        const [ar, pr, rr] = await Promise.allSettled([
          fetch(base + audioFile),
          fetch(base + 'auto_segment_prompt.txt'),
          fetch(base + 'auto_segment_raw.txt'),
        ]);
        const audioUrl = ar.status === 'fulfilled' && ar.value.ok ? base + audioFile : null;
        const autoSegPrompt = pr.status === 'fulfilled' && pr.value.ok ? await pr.value.text() : null;
        const autoSegRaw    = rr.status === 'fulfilled' && rr.value.ok ? await rr.value.text() : null;
        return { audioUrl, autoSegPrompt, autoSegRaw };
      }
      if (step.type === 'write_context') {
        const jr = await fetch(base + 'output.json').catch(() => null);
        if (jr && jr.ok) {
          const data = await jr.json().catch(() => null);
          return { itemTitle: data && data.title, itemId: data && data.id };
        }
        return {};
      }
      const fetches = [
        fetch(base + 'context.txt'),
        fetch(base + 'prompt.txt'),
        fetch(base + 'output.txt'),
      ];
      const hasTools = step.tools && step.tools.length > 0;
      if (hasTools) fetches.push(fetch(base + 'tool_calls.json'));
      const [cr, pr, or, tcr] = await Promise.allSettled(fetches);
      const contextText   = cr  && cr.status  === 'fulfilled' && cr.value.ok  ? await cr.value.text()                          : null;
      const promptText    = pr  && pr.status  === 'fulfilled' && pr.value.ok  ? await pr.value.text()                          : null;
      const outputText    = or  && or.status  === 'fulfilled' && or.value.ok  ? await or.value.text()                          : null;
      const toolCallsData = tcr && tcr.status === 'fulfilled' && tcr.value.ok ? await tcr.value.json().catch(() => null) : null;
      return { contextText, promptText, outputText, toolCallsData };
    }

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
        if (isAudio) {
          html += '<audio controls style="width:100%;margin-bottom:6px;" src="' + url + '"></audio>';
        } else if (isImage) {
          html += '<img src="' + url + '" style="max-width:100%;margin-bottom:6px;border-radius:3px;" alt="">';
        }
      }
      container.innerHTML = html;
      panel.style.display = 'block';
    }

    async function _pollChainJob(jobId) {
      try {
        const msg           = document.getElementById('chain-msg');
        const stepStatusDiv = document.getElementById('chain-step-status');
        const outputDiv     = document.getElementById('chain-output');

        const r = await fetch('/v1/jobs/' + jobId + '/files/status.json');
        if (!r.ok) return;
        const job = await r.json();

        if (job.status === 'done') {
          clearInterval(_chainJobPollTimer); _chainJobPollTimer = null;
          msg.style.color = '#2a6'; msg.textContent = 'Done.';

          try {
            const sr = await fetch('/v1/jobs/' + jobId + '/steps');
            if (sr.ok) {
              const sd = await sr.json();
              const steps = sd.steps || [];
              const interimSteps = steps.slice(0, -1);
              const fileResults = await Promise.allSettled(
                interimSteps.map((step, i) => _fetchStepFiles(jobId, step, i))
              );
              stepStatusDiv.innerHTML = interimSteps.map((step, i) => {
                const files = fileResults[i].status === 'fulfilled' ? fileResults[i].value : {};
                return _stepCollapseHtml(step, i + 1, files);
              }).join('');

              // Fetch final step content
              if (steps.length > 0) {
                const finalStep = steps[steps.length - 1];
                const finalDir = String(steps.length).padStart(3, '0') + '_' + finalStep.id;
                const finalBase = '/v1/jobs/' + jobId + '/files/steps/' + finalDir + '/';
                if (finalStep.type === 'voice') {
                  const audioFile = finalStep.output_file || 'output.wav';
                  const [far, fpr, frr] = await Promise.allSettled([
                    fetch(finalBase + audioFile),
                    fetch(finalBase + 'auto_segment_prompt.txt'),
                    fetch(finalBase + 'auto_segment_raw.txt'),
                  ]);
                  if (far.status === 'fulfilled' && far.value.ok) {
                    document.getElementById('chain-final-audio-player').src = finalBase + audioFile;
                    document.getElementById('chain-final-audio').style.display = 'block';
                  }
                  const fSegPrompt = fpr.status === 'fulfilled' && fpr.value.ok ? await fpr.value.text() : null;
                  const fSegRaw    = frr.status === 'fulfilled' && frr.value.ok ? await frr.value.text() : null;
                  if (fSegPrompt != null || fSegRaw != null) {
                    let inner = '';
                    if (fSegPrompt != null) inner +=
                      '<details style="margin-bottom:6px;"><summary style="font-size:0.72rem;color:#555;cursor:pointer;">PROMPT</summary>' +
                      '<pre class="output-pre" style="margin-top:4px;">' + _escHtml(fSegPrompt) + '</pre></details>';
                    if (fSegRaw != null) inner +=
                      '<details><summary style="font-size:0.72rem;color:#555;cursor:pointer;">RAW RESPONSE</summary>' +
                      '<pre class="output-pre" style="margin-top:4px;font-size:0.68rem;">' + _escHtml(fSegRaw) + '</pre></details>';
                    const tcEl = document.getElementById('chain-final-tool-calls');
                    document.getElementById('chain-final-tool-calls-body').innerHTML =
                      '<details style="border:1px solid #1e1e1e;border-radius:3px;padding:6px 8px;background:#0a0a0a;">' +
                      '<summary style="font-size:0.72rem;color:#555;cursor:pointer;list-style:none;">' +
                        '<span style="color:#444;">▸ </span>INTERNAL REQUESTS · auto_segment</summary>' +
                      '<div style="margin-top:6px;">' + inner + '</div></details>';
                    tcEl.style.display = 'block';
                  }
                } else if (finalStep.type === 'write_context') {
                  // nothing extra to show; final output text is displayed below
                } else {
                  try {
                    const finalFetches = [
                      fetch(finalBase + 'context.txt'),
                      fetch(finalBase + 'prompt.txt'),
                    ];
                    const finalHasTools = finalStep.tools && finalStep.tools.length > 0;
                    if (finalHasTools) finalFetches.push(fetch(finalBase + 'tool_calls.json'));
                    const [fcr, fp, ftcr] = await Promise.allSettled(finalFetches);
                    const finalCtx = fcr.status === 'fulfilled' && fcr.value.ok ? await fcr.value.text() : '';
                    if (finalCtx) {
                      document.getElementById('chain-final-context-pre').textContent = finalCtx;
                      document.getElementById('chain-final-context').style.display = 'block';
                    }
                    if (fp.status === 'fulfilled' && fp.value.ok) {
                      document.getElementById('chain-final-input-pre').textContent = await fp.value.text();
                      document.getElementById('chain-final-input').style.display = 'block';
                    }
                    const finalTcData = ftcr.status === 'fulfilled' && ftcr.value.ok ? await ftcr.value.json().catch(() => null) : null;
                    if (finalTcData && finalTcData.length > 0) {
                      const tcEl = document.getElementById('chain-final-tool-calls');
                      document.getElementById('chain-final-tool-calls-pre').textContent = JSON.stringify(finalTcData, null, 2);
                      tcEl.style.display = 'block';
                    }
                  } catch (e) {}
                }
              }
            }
          } catch (e) {}

          try {
            const or = await fetch('/v1/jobs/' + jobId + '/files/final_output.txt');
            if (or.ok) {
              document.getElementById('chain-output-pre').textContent = await or.text();
              outputDiv.style.display = 'block';
            }
          } catch (e) {}

          try {
            const ar = await fetch('/v1/jobs/' + jobId + '/files/artifacts.json');
            if (ar.ok) await _renderArtifacts(jobId, await ar.json());
          } catch (e) {}

        } else if (job.status === 'error') {
          clearInterval(_chainJobPollTimer); _chainJobPollTimer = null;
          msg.style.color = '#e44';
          msg.textContent = 'Error: ' + (job.error || 'unknown');

          try {
            const sr = await fetch('/v1/jobs/' + jobId + '/steps');
            if (sr.ok) {
              const sd = await sr.json();
              const steps = sd.steps || [];
              const fileResults = await Promise.allSettled(
                steps.map((step, i) => _fetchStepFiles(jobId, step, i))
              );
              stepStatusDiv.innerHTML = steps.map((step, i) => {
                const files = fileResults[i].status === 'fulfilled' ? fileResults[i].value : {};
                return _stepCollapseHtml(step, i + 1, files);
              }).join('');
            }
          } catch (e) {}

        } else {
          const stepInfo = job.current_step_name
            ? ' · step ' + job.current_step_index + '/' + job.step_count + ': ' + job.current_step_name
            : '';
          msg.textContent = 'Job ' + jobId.slice(0, 8) + '… ' + job.status + stepInfo;
        }
      } catch (e) {}
    }

    // ── Recreate hydration ────────────────────────────────────────────
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

      // Rebuild steps and collect missing references
      const missing = [];
      const ctxIds  = new Set((_ctxItems  || []).map(c => c.id));
      const vpIds   = new Set((_voicePresets || []).map(p => p.id));
      const seqIds  = new Set((_allSeqs   || []).map(s => s.id));
      const toolNms = new Set((_mcpTools  || []).map(t => t.name));

      document.getElementById('chain-steps-list').innerHTML = '';
      _chainStepCounter = 0;

      for (const step of (req.steps || [])) {
        if (step.type === 'sequence' && step.sequence_id && !seqIds.has(step.sequence_id)) {
          missing.push('sequence "' + step.sequence_id + '"');
        }
        if (step.type === 'voice' && step.voice_preset_id && !vpIds.has(step.voice_preset_id)) {
          missing.push('voice preset "' + step.voice_preset_id + '"');
        }
        for (const cid of (step.context_ids || [])) {
          if (!ctxIds.has(cid)) missing.push('context item "' + cid + '"');
        }
        for (const tn of (step.tools || [])) {
          if (!toolNms.has(tn)) missing.push('tool "' + tn + '"');
        }
        addChainStep(step);
      }

      if (missing.length > 0) {
        notice.innerHTML = 'Recreate notice — these references no longer exist:<br>· ' +
          missing.map(m => _escHtml(m)).join('<br>· ');
        notice.style.display = 'block';
      }
    }

    // ── Init ─────────────────────────────────────────────────────────
    Promise.all([_loadChainPresets(), loadContextItems(), loadVoicePresets(), loadSeqs(), loadMcpTools()]).then(() => {
      if (_recreateId) {
        _hydrateFromRecreate(_recreateId);
        switchTab('chain');
        return;
      }
      const params = new URLSearchParams(window.location.search);
      const seqParam = params.get('sequence');
      if (seqParam) {
        const seq = _allSeqs.find(s => s.id === seqParam);
        if (seq) {
          _editSeq(seqParam);
          return;
        }
      }
      addChainStep({ prompt: 'Create five bullet points for the following task:\n\n' });
      switchTab('chain');
    });
