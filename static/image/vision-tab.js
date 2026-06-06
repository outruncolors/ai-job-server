// Vision tab — image understanding via the multimodal model on the llm node.
// Self-contained; wired in from image.js switchL1('vision').

let _visionFile = null;

function _visionSetFile(file) {
  if (!file || !file.type.startsWith('image/')) return;
  _visionFile = file;
  const wrap = document.getElementById('vision-preview-wrap');
  const img  = document.getElementById('vision-preview');
  img.src = URL.createObjectURL(file);
  wrap.style.display = '';
  document.getElementById('vision-paste').classList.add('has-image');
  document.getElementById('vision-submit').disabled = false;
}

function initVisionTab() {
  const fileInput = document.getElementById('vision-file');
  const paste     = document.getElementById('vision-paste');

  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files[0]) _visionSetFile(fileInput.files[0]);
  });

  // Paste an image from the clipboard.
  paste.addEventListener('paste', (e) => {
    const items = (e.clipboardData || {}).items || [];
    for (const it of items) {
      if (it.type && it.type.startsWith('image/')) {
        _visionSetFile(it.getAsFile());
        e.preventDefault();
        return;
      }
    }
  });
  paste.addEventListener('focus', () => paste.classList.add('focused'));
  paste.addEventListener('blur',  () => paste.classList.remove('focused'));

  // Drag & drop onto the paste box.
  ['dragover', 'dragenter'].forEach(ev =>
    paste.addEventListener(ev, (e) => { e.preventDefault(); paste.classList.add('focused'); }));
  ['dragleave', 'drop'].forEach(ev =>
    paste.addEventListener(ev, () => paste.classList.remove('focused')));
  paste.addEventListener('drop', (e) => {
    e.preventDefault();
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) _visionSetFile(f);
  });
}

async function submitVision() {
  if (!_visionFile) return;
  const btn    = document.getElementById('vision-submit');
  const status = document.getElementById('vision-status');
  const result = document.getElementById('vision-result');

  const fd = new FormData();
  fd.append('file', _visionFile);
  fd.append('prompt', document.getElementById('vision-prompt').value || '');

  btn.disabled = true;
  status.textContent = 'Analyzing… (the model may need a moment to load on first use)';
  result.textContent = '';
  const tid = toast('info', 'Analyzing image…', { persistent: true });

  try {
    const r = await fetch('/v1/multimodal/vision', { method: 'POST', body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = (data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : r.statusText;
      throw new Error(detail);
    }
    result.textContent = data.text || '(empty response)';
    status.textContent = '';
    toast('success', 'Done', { id: tid });
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    toast('error', 'Vision failed: ' + e.message, { id: tid });
  } finally {
    btn.disabled = false;
  }
}
