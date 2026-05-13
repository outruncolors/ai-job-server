    async function api(path, method = 'GET', body = null) {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch('/v1' + path, opts);
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    }

    // ── Image ────────────────────────────────────────────────────────
    async function submitImage() {
      const msg  = document.getElementById('img-msg');
      const hint = document.getElementById('img-right-hint');
      msg.textContent = '';
      const body = {
        prompt: document.getElementById('img-prompt').value,
        width:  parseInt(document.getElementById('img-width').value),
        height: parseInt(document.getElementById('img-height').value),
        steps:  parseInt(document.getElementById('img-steps').value),
      };
      const neg   = document.getElementById('img-neg').value;
      const model = document.getElementById('img-model').value;
      if (neg)   body.negative_prompt = neg;
      if (model) body.model = model;
      try {
        hint.style.display = 'none';
        const job = await api('/jobs/image', 'POST', body);
        msg.style.color = '#2a6'; msg.textContent = 'Created job ' + job.job_id;
      } catch (e) {
        msg.style.color = '#e44'; msg.textContent = 'Error: ' + e.message;
      }
    }
