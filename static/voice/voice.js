    async function api(path, method = 'GET', body = null) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch('/v1' + path, opts);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }
    function _escHtml(str) {
      return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Presets ──────────────────────────────────────────────────────
    let _presets = [];
    let _activeTab = 'create';

    async function loadPresets() {
      try {
        const r = await fetch('/v1/voice-presets');
        _presets = r.ok ? await r.json() : [];
      } catch(e) { _presets = []; }
      _renderUsePresets();
    }

    function _renderUsePresets() {
      const sel      = document.getElementById('use-preset-select');
      const emptyMsg = document.getElementById('use-empty-msg');
      const row      = document.getElementById('use-preset-row');
      if (_presets.length === 0) {
        emptyMsg.style.display = 'block';
        row.style.display = 'none';
      } else {
        emptyMsg.style.display = 'none';
        row.style.display = 'block';
        const cur = sel.value;
        sel.innerHTML = _presets.map(p =>
          `<option value="${p.id}"${p.id === cur ? ' selected' : ''}>${_escHtml(p.name)}</option>`
        ).join('');
        if (!_presets.some(p => p.id === cur) && _presets.length > 0) sel.value = _presets[0].id;
      }
    }

    async function deleteSelectedPreset() {
      const sel = document.getElementById('use-preset-select');
      const id  = sel.value;
      if (!id) return;
      const preset = _presets.find(p => p.id === id);
      const name   = preset ? preset.name : id;
      if (!window.confirm(`Remove voice preset "${name}"? This cannot be undone.`)) return;
      const msg = document.getElementById('use-job-msg');
      try {
        const r = await fetch(`/v1/voice-presets/${id}`, { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text());
        msg.style.color = '#2a6'; msg.textContent = `Removed "${name}"`;
        await loadPresets();
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    // ── Tabs ─────────────────────────────────────────────────────────
    function switchTab(tab) {
      _activeTab = tab;
      const _tabOrder = ['create', 'use', 'preprocess', 'segment-prompt'];
      document.querySelectorAll('.tab-btn').forEach((b, i) =>
        b.classList.toggle('active', _tabOrder[i] === tab)
      );
      document.getElementById('create-panel').style.display        = tab === 'create'         ? '' : 'none';
      document.getElementById('use-panel').style.display           = tab === 'use'            ? '' : 'none';
      document.getElementById('preprocess-panel').style.display    = tab === 'preprocess'     ? '' : 'none';
      document.getElementById('segment-prompt-panel').style.display = tab === 'segment-prompt' ? '' : 'none';
      document.getElementById('create-output').style.display    = tab === 'create' ? '' : 'none';
      document.getElementById('use-output').style.display       = tab === 'use'    ? '' : 'none';
    }

    // ── Create: Design ───────────────────────────────────────────────
    let _createJobId   = null;
    let _createPollTimer = null;

    function _buildInstruct() {
      const ids = ['create-gender','create-age','create-pitch','create-style','create-accent','create-dialect'];
      const parts = [];
      for (const id of ids) {
        const v = document.getElementById(id).value;
        if (!v || v === 'Auto') continue;
        if (v.includes(' / ')) {
          const en = v.split(' / ')[0];
          const zh = v.split(' / ')[1];
          parts.push(en.includes('Dialect') ? zh.trim() : en.trim());
        } else { parts.push(v); }
      }
      return parts.join(', ');
    }

    async function generateSample() {
      const msg   = document.getElementById('create-job-msg');
      const audio = document.getElementById('create-audio');
      const hint  = document.getElementById('create-right-hint');
      audio.style.display = 'none';
      document.getElementById('duration-badge').style.display = 'none';
      document.getElementById('duration-warn').style.display = 'none';
      document.getElementById('save-wrap').style.display = 'none';
      _createJobId = null; msg.textContent = '';
      const text = document.getElementById('create-text').value.trim();
      if (!text) { msg.style.color = '#e44'; msg.textContent = 'Enter sample text first.'; return; }
      const body = {
        text,
        speed:          parseFloat(document.getElementById('create-spd').value),
        num_step:       parseInt(document.getElementById('create-steps').value),
        guidance_scale: parseFloat(document.getElementById('create-cfg').value),
      };
      const lang = document.getElementById('create-lang').value.trim();
      if (lang && lang !== 'Auto') body.language = lang;
      const instruct = _buildInstruct();
      if (instruct) body.instruct = instruct;
      try {
        hint.style.display = 'none';
        const job = await api('/jobs/voice', 'POST', body);
        msg.style.color = '#fa0'; msg.textContent = 'Generating sample…';
        if (_createPollTimer) clearInterval(_createPollTimer);
        _createPollTimer = setInterval(() => _pollCreateJob(job.job_id), 3000);
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    async function _pollCreateJob(jobId) {
      try {
        const job   = await api('/jobs/' + jobId);
        const msg   = document.getElementById('create-job-msg');
        const audio = document.getElementById('create-audio');
        if (job.status === 'done') {
          clearInterval(_createPollTimer); _createPollTimer = null;
          msg.style.color = '#2a6'; msg.textContent = 'Sample ready';
          _createJobId = jobId;
          audio.src = '/v1/jobs/' + jobId + '/files/output.wav';
          audio.style.display = 'block'; audio.load();
        } else if (job.status === 'error') {
          clearInterval(_createPollTimer); _createPollTimer = null;
          msg.style.color = '#e44'; msg.textContent = 'Error: ' + (job.error || 'unknown');
        } else {
          msg.textContent = 'Generating… (' + job.status + ')';
        }
      } catch(e) {}
    }

    document.getElementById('create-audio').addEventListener('loadedmetadata', function() {
      const dur   = this.duration;
      const badge = document.getElementById('duration-badge');
      const warn  = document.getElementById('duration-warn');
      const save  = document.getElementById('save-wrap');
      if (!isFinite(dur)) return;
      badge.innerHTML = `Duration: <span class="dur-val">${dur.toFixed(1)}s</span>`;
      badge.style.display = 'block';
      if (dur >= 3 && dur <= 10) {
        warn.style.display = 'none';
        save.style.display = 'block';
        document.getElementById('save-name').value = '';
        document.getElementById('save-msg').textContent = '';
        onSaveNameChange();
      } else {
        warn.textContent = `Sample is ${dur.toFixed(1)}s — must be 3–10s to save as preset`;
        warn.style.display = 'block';
        save.style.display = 'none';
      }
    });

    function onSaveNameChange() {
      document.getElementById('save-btn').disabled =
        !document.getElementById('save-name').value.trim();
    }

    async function saveFromDesign() {
      if (!_createJobId) return;
      const msg    = document.getElementById('save-msg');
      const nameEl = document.getElementById('save-name');
      const name   = nameEl.value.trim();
      if (!name) return;
      const caption = document.getElementById('create-text').value.trim();
      msg.style.color = '#fa0'; msg.textContent = 'Saving…';
      try {
        const r = await fetch('/v1/voice-presets/from-job', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: _createJobId, name, caption }),
        });
        if (!r.ok) {
          let detail = await r.text();
          try { detail = JSON.parse(detail).detail || detail; } catch(e) {}
          throw new Error(detail);
        }
        const preset = await r.json();
        msg.style.color = '#2a6'; msg.textContent = `Saved as "${preset.name}"`;
        document.getElementById('save-wrap').style.display = 'none';
        await loadPresets();
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    // ── Create: Upload ───────────────────────────────────────────────
    function onUploadChange() {
      const hasFile    = document.getElementById('upload-file').files.length > 0;
      const hasName    = document.getElementById('upload-name').value.trim() !== '';
      const hasCaption = document.getElementById('upload-caption').value.trim() !== '';
      document.getElementById('upload-btn').disabled = !(hasFile && hasName && hasCaption);
    }

    async function uploadPreset() {
      const msg    = document.getElementById('upload-msg');
      const fileEl = document.getElementById('upload-file');
      const nameEl = document.getElementById('upload-name');
      const captEl = document.getElementById('upload-caption');
      msg.textContent = '';
      const fd = new FormData();
      fd.append('file', fileEl.files[0]);
      fd.append('name', nameEl.value.trim());
      fd.append('caption', captEl.value.trim());
      try {
        const r = await fetch('/v1/voice-presets', { method: 'POST', body: fd });
        if (!r.ok) {
          let detail = await r.text();
          try { detail = JSON.parse(detail).detail || detail; } catch(e) {}
          throw new Error(detail);
        }
        const preset = await r.json();
        msg.style.color = '#2a6'; msg.textContent = `Saved "${preset.name}"`;
        fileEl.value = ''; nameEl.value = ''; captEl.value = '';
        onUploadChange();
        await loadPresets();
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    // ── Use Voice ────────────────────────────────────────────────────
    let _usePollTimer = null;

    async function synthesize() {
      const msg   = document.getElementById('use-job-msg');
      const audio = document.getElementById('use-audio');
      const hint  = document.getElementById('use-right-hint');
      audio.style.display = 'none'; msg.textContent = '';
      const presetId = document.getElementById('use-preset-select').value;
      if (!presetId) { msg.style.color = '#e44'; msg.textContent = 'Select a voice preset first.'; return; }
      const segsContainer = document.getElementById('use-segments-list');
      const segments = vsCollectSegments(segsContainer);
      if (segments.length === 0) { msg.style.color = '#e44'; msg.textContent = 'Enter text in at least one segment.'; return; }
      // Ensure last segment has no trailing silence
      segments[segments.length - 1].delay_ms = 0;
      const body = {
        segments,
        voice_preset_id: presetId,
        speed:           parseFloat(document.getElementById('use-spd').value),
        num_step:        parseInt(document.getElementById('use-steps').value),
        guidance_scale:  parseFloat(document.getElementById('use-cfg').value),
      };
      const lang = document.getElementById('use-lang').value.trim();
      if (lang && lang !== 'Auto') body.language = lang;
      try {
        hint.style.display = 'none';
        const job = await api('/jobs/voice', 'POST', body);
        msg.style.color = '#fa0'; msg.textContent = 'Synthesizing…';
        if (_usePollTimer) clearInterval(_usePollTimer);
        _usePollTimer = setInterval(() => _pollUseJob(job.job_id), 3000);
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    async function _pollUseJob(jobId) {
      try {
        const job   = await api('/jobs/' + jobId);
        const msg   = document.getElementById('use-job-msg');
        const audio = document.getElementById('use-audio');
        if (job.status === 'done') {
          clearInterval(_usePollTimer); _usePollTimer = null;
          msg.style.color = '#2a6'; msg.textContent = 'Done';
          audio.src = '/v1/jobs/' + jobId + '/files/output.wav';
          audio.style.display = 'block'; audio.load();
        } else if (job.status === 'error') {
          clearInterval(_usePollTimer); _usePollTimer = null;
          msg.style.color = '#e44'; msg.textContent = 'Error: ' + (job.error || 'unknown');
        } else {
          msg.textContent = 'Synthesizing… (' + job.status + ')';
        }
      } catch(e) {}
    }

    // ── Pre-Processing Prompt ─────────────────────────────────────────
    const _DEFAULT_VOICE_PREPROCESS_PROMPT =
      'You are a text pre-processor for text-to-speech synthesis. ' +
      'Rewrite the following text so it reads naturally when spoken aloud. ' +
      'Remove markdown formatting (headers, bold, italics, bullet points, code blocks). ' +
      'Replace or remove symbols (e.g. \'#\', \'*\', \'->\', \'%\', \'|\', \'~\', \'`\', \'=\', \'+\', \'<\', \'>\'). ' +
      'Expand abbreviations where meaning is clear. ' +
      'Preserve sentence boundaries and natural pacing punctuation. ' +
      'Output only the cleaned text with no explanation or commentary.';

    async function loadPreprocessPrompt() {
      document.getElementById('preprocess-prompt-input').placeholder = _DEFAULT_VOICE_PREPROCESS_PROMPT;
      try {
        const cfg = await api('/v1/omnivoice/config');
        document.getElementById('preprocess-prompt-input').value = cfg.voice_preprocess_prompt || '';
      } catch(e) { /* silent */ }
    }

    async function savePreprocessPrompt() {
      const msg = document.getElementById('preprocess-msg');
      const val = document.getElementById('preprocess-prompt-input').value.trim();
      try {
        const cfg = await api('/v1/omnivoice/config');
        cfg.voice_preprocess_prompt = val || null;
        await api('/v1/omnivoice/config', 'PUT', cfg);
        msg.style.color = '#2a6'; msg.textContent = 'Saved.';
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    function resetPreprocessPrompt() {
      document.getElementById('preprocess-prompt-input').value = '';
      document.getElementById('preprocess-msg').style.color = '#888';
      document.getElementById('preprocess-msg').textContent = 'Cleared — save to use built-in default.';
    }

    // ── Segmentation Prompt ───────────────────────────────────────────
    async function loadSegmentPrompt() {
      try {
        const cfg = await api('/v1/omnivoice/config');
        document.getElementById('segment-prompt-input').value = cfg.voice_auto_segment_prompt || '';
      } catch(e) { /* silent */ }
    }

    async function saveSegmentPrompt() {
      const msg = document.getElementById('segment-prompt-msg');
      const val = document.getElementById('segment-prompt-input').value.trim();
      try {
        const cfg = await api('/v1/omnivoice/config');
        cfg.voice_auto_segment_prompt = val || null;
        await api('/v1/omnivoice/config', 'PUT', cfg);
        msg.style.color = '#2a6'; msg.textContent = 'Saved.';
      } catch(e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }

    function resetSegmentPrompt() {
      document.getElementById('segment-prompt-input').value = '';
      document.getElementById('segment-prompt-msg').style.color = '#888';
      document.getElementById('segment-prompt-msg').textContent = 'Cleared — save to use built-in default.';
    }

    // ── Init ─────────────────────────────────────────────────────────
    loadPresets();
    loadPreprocessPrompt();
    loadSegmentPrompt();
    document.getElementById('use-add-seg-btn').addEventListener('click', function () {
      vsAddSegment(document.getElementById('use-segments-list'));
    });
    vsAddSegment(document.getElementById('use-segments-list'));
