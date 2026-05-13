    const JOBS_PAGE_SIZE = 25;
    let _allJobs   = [];
    let _jobsPage  = 0;
    let _activeJobId = null;

    async function api(path, method = 'GET', body = null) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch('/v1' + path, opts);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }

    function statusClass(s) { return 'status-' + s; }

    function _escHtml(s) {
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // ── Jobs table ──────────────────────────────────────────────────
    function _renderJobsPage() {
      const tbody = document.getElementById('jobs-body');
      const pager = document.getElementById('jobs-pagination');
      const totalPages = Math.max(1, Math.ceil(_allJobs.length / JOBS_PAGE_SIZE));
      const start = _jobsPage * JOBS_PAGE_SIZE;
      const page  = _allJobs.slice(start, start + JOBS_PAGE_SIZE);

      if (page.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" style="color:#333;padding:10px;">No jobs yet.</td></tr>';
        pager.innerHTML = '';
        return;
      }

      tbody.innerHTML = page.map(j => `
        <tr class="clickable${_activeJobId === j.job_id ? ' active-row' : ''}" data-job-id="${j.job_id}" onclick="openDetail('${j.job_id}')">
          <td style="color:#555">${j.job_id.slice(0,8)}&hellip;</td>
          <td style="color:#666">${j.job_type}</td>
          <td class="${statusClass(j.status)}">${j.status}</td>
          <td style="color:#555">${new Date(j.created_at).toLocaleString()}</td>
          <td class="del-cell">
            <button class="del-btn" title="Delete job" onclick="deleteJob(event,'${j.job_id}')">&#10005;</button>
          </td>
        </tr>`).join('');

      pager.innerHTML = totalPages <= 1 ? '' : `
        <button class="secondary" onclick="_jobsGo(-1)" ${_jobsPage === 0 ? 'disabled' : ''}>&#8592; Prev</button>
        <span class="page-info">${_jobsPage + 1} / ${totalPages}</span>
        <button class="secondary" onclick="_jobsGo(1)" ${_jobsPage >= totalPages - 1 ? 'disabled' : ''}>Next &#8594;</button>`;
    }

    function _jobsGo(delta) {
      const totalPages = Math.ceil(_allJobs.length / JOBS_PAGE_SIZE);
      _jobsPage = Math.max(0, Math.min(_jobsPage + delta, totalPages - 1));
      _renderJobsPage();
    }

    async function loadJobs() {
      const tbody = document.getElementById('jobs-body');
      try {
        const data = await api('/jobs');
        _allJobs = (data.jobs || []).slice().sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
        _jobsPage = 0;
        _renderJobsPage();
      } catch(e) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:#e44;padding:10px;">Error: ${_escHtml(e.message)}</td></tr>`;
      }
    }

    // ── Job detail ───────────────────────────────────────────────────
    async function openDetail(jobId) {
      _activeJobId = jobId;
      _renderJobsPage();

      document.getElementById('detail-empty').style.display = 'none';
      const view = document.getElementById('detail-view');
      view.style.display = 'block';
      document.getElementById('detail-meta').innerHTML = '<span style="color:#333;font-size:0.78rem;">Loading…</span>';
      document.getElementById('detail-artifacts-section').style.display = 'none';
      document.getElementById('detail-artifacts').innerHTML = '';
      document.getElementById('detail-raw-links').innerHTML = '';
      document.getElementById('detail-delete-btn').dataset.jobId = jobId;

      try {
        const job = await api('/jobs/' + jobId);
        _renderMeta(job);
        await _renderArtifacts(jobId);
        _renderRawLinks(jobId);
      } catch(e) {
        document.getElementById('detail-meta').innerHTML =
          `<span style="color:#e44">Error: ${_escHtml(e.message)}</span>`;
      }
    }

    function _renderMeta(job) {
      const rows = [
        ['Job ID',   job.job_id],
        ['Type',     job.job_type],
        ['Status',   `<span class="${statusClass(job.status)}">${job.status}</span>`],
        ['Created',  new Date(job.created_at).toLocaleString()],
        ['Updated',  new Date(job.updated_at).toLocaleString()],
      ];
      if (job.error) rows.push(['Error', `<span style="color:#e44">${_escHtml(job.error)}</span>`]);
      document.getElementById('detail-meta').innerHTML = rows.map(([k,v]) =>
        `<div class="detail-meta-row"><span class="detail-meta-key">${k}</span><span class="detail-meta-val">${v}</span></div>`
      ).join('');
    }

    async function _renderArtifacts(jobId) {
      let artifacts = [];
      try {
        const r = await fetch(`/v1/jobs/${jobId}/files/artifacts.json`);
        if (r.ok) artifacts = await r.json();
      } catch(e) { return; }
      if (!artifacts || artifacts.length === 0) return;

      const section = document.getElementById('detail-artifacts-section');
      section.style.display = 'block';
      const container = document.getElementById('detail-artifacts');

      const items = await Promise.all(artifacts.map(a => _renderArtifact(jobId, a)));
      container.innerHTML = '';
      items.forEach(el => container.appendChild(el));
    }

    async function _renderArtifact(jobId, artifact) {
      const div = document.createElement('div');
      div.className = 'artifact-item';
      const label = document.createElement('div');
      label.className = 'artifact-label';
      label.textContent = artifact.filename;
      div.appendChild(label);

      const ext = artifact.filename.split('.').pop().toLowerCase();
      const url = `/v1/jobs/${jobId}/files/${artifact.filename}`;

      if (ext === 'wav' || ext === 'mp3' || ext === 'ogg') {
        const audio = document.createElement('audio');
        audio.controls = true;
        audio.src = url;
        div.appendChild(audio);
      } else if (ext === 'txt') {
        const pre = document.createElement('pre');
        pre.className = 'artifact-pre';
        pre.textContent = 'Loading…';
        div.appendChild(pre);
        try {
          const r = await fetch(url);
          if (r.ok) {
            pre.textContent = await r.text();
          } else {
            pre.textContent = '(not found)';
            pre.style.color = '#444';
          }
        } catch(e) {
          pre.textContent = 'Error loading file';
          pre.style.color = '#e44';
        }
      } else {
        const a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.textContent = 'Download';
        a.style.cssText = 'color:#446;font-size:0.74rem;';
        div.appendChild(a);
      }

      return div;
    }

    function _renderRawLinks(jobId) {
      const files = ['request.json', 'logs.txt', 'status.json'];
      document.getElementById('detail-raw-links').innerHTML = files.map(f =>
        `<a href="/v1/jobs/${jobId}/files/${f}" target="_blank">${f}</a>`
      ).join('');
    }

    // ── Delete ────────────────────────────────────────────────────────
    async function deleteJob(evt, jobId) {
      evt.stopPropagation();
      if (!window.confirm('Delete this job and all its files? This cannot be undone.')) return;
      try {
        const r = await fetch('/v1/jobs/' + jobId, { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text());
        _allJobs = _allJobs.filter(j => j.job_id !== jobId);
        if (_jobsPage > 0 && _jobsPage * JOBS_PAGE_SIZE >= _allJobs.length) {
          _jobsPage = Math.max(0, _jobsPage - 1);
        }
        if (_activeJobId === jobId) {
          _activeJobId = null;
          document.getElementById('detail-view').style.display = 'none';
          document.getElementById('detail-empty').style.display = 'block';
        }
        _renderJobsPage();
      } catch(e) {
        alert('Error: ' + e.message);
      }
    }

    function deleteCurrentJob() {
      const jobId = document.getElementById('detail-delete-btn').dataset.jobId;
      if (!jobId) return;
      deleteJob({ stopPropagation: () => {} }, jobId);
    }

    // ── Init ──────────────────────────────────────────────────────────
    loadJobs();
