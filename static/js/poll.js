/* Job polling helper. Returns a handle with a stop() method.
   Calls api('/jobs/' + jobId) on each tick and dispatches to callbacks.
   Per-job result handling (updating UI) stays in the caller's onUpdate/onDone/onError. */
function pollJob(jobId, { onUpdate, onDone, onError, intervalMs = 3000 } = {}) {
  let timer = setInterval(async () => {
    try {
      const job = await api('/jobs/' + jobId);
      if (onUpdate) onUpdate(job);
      if (job.status === 'done') {
        clearInterval(timer);
        if (onDone) onDone(job);
      } else if (job.status === 'error' || job.status === 'failed') {
        clearInterval(timer);
        if (onError) onError(job);
      }
    } catch (e) {
      /* network errors: keep polling */
    }
  }, intervalMs);
  return { stop: () => clearInterval(timer) };
}
