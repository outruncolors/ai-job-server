// Speech-to-Text tab — transcription via the multimodal model on the llm node.
// Records from the mic (webm/opus; the server transcodes to WAV with ffmpeg) or
// accepts an uploaded audio file. Loaded before voice.js, which calls initSttTab.

let _sttBlob = null;          // the audio to transcribe (recording or upload)
let _sttRecorder = null;
let _sttChunks = [];
let _sttStream = null;

function _sttSetBlob(blob, filename) {
  _sttBlob = blob;
  _sttBlob._filename = filename || 'audio.webm';
  const wrap  = document.getElementById('stt-audio-wrap');
  const audio = document.getElementById('stt-audio');
  audio.src = URL.createObjectURL(blob);
  wrap.style.display = '';
  document.getElementById('stt-submit').disabled = false;
}

function initSttTab() {
  const fileInput = document.getElementById('stt-file');
  fileInput.addEventListener('change', () => {
    if (fileInput.files && fileInput.files[0]) {
      const f = fileInput.files[0];
      _sttSetBlob(f, f.name);
    }
  });
}

async function sttToggleRecord() {
  const btn    = document.getElementById('stt-record-btn');
  const status = document.getElementById('stt-record-status');

  // Stop an in-progress recording.
  if (_sttRecorder && _sttRecorder.state === 'recording') {
    _sttRecorder.stop();
    return;
  }

  // Start a new recording.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    toast('error', 'Microphone not available in this browser');
    return;
  }
  try {
    _sttStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    toast('error', 'Microphone permission denied');
    return;
  }
  _sttChunks = [];
  _sttRecorder = new MediaRecorder(_sttStream);
  _sttRecorder.addEventListener('dataavailable', (e) => {
    if (e.data && e.data.size > 0) _sttChunks.push(e.data);
  });
  _sttRecorder.addEventListener('stop', () => {
    if (_sttStream) { _sttStream.getTracks().forEach(t => t.stop()); _sttStream = null; }
    btn.textContent = '● Record';
    btn.classList.remove('recording');
    status.textContent = '';
    if (_sttChunks.length) {
      const type = _sttRecorder.mimeType || 'audio/webm';
      const ext  = type.includes('ogg') ? 'ogg' : 'webm';
      _sttSetBlob(new Blob(_sttChunks, { type }), 'recording.' + ext);
    }
  });
  _sttRecorder.start();
  btn.textContent = '■ Stop';
  btn.classList.add('recording');
  status.textContent = 'recording…';
}

async function submitStt() {
  if (!_sttBlob) return;
  const btn    = document.getElementById('stt-submit');
  const status = document.getElementById('stt-status');
  const result = document.getElementById('stt-result');

  const fd = new FormData();
  fd.append('file', _sttBlob, _sttBlob._filename || 'audio.webm');
  fd.append('prompt', document.getElementById('stt-prompt').value || '');

  btn.disabled = true;
  status.textContent = 'Transcribing… (the model may need a moment to load on first use)';
  result.textContent = '';
  const tid = toast('info', 'Transcribing audio…', { persistent: true });

  try {
    const r = await fetch('/v1/multimodal/stt', { method: 'POST', body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const detail = (data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : r.statusText;
      throw new Error(detail);
    }
    result.textContent = data.text || '(empty transcript)';
    status.textContent = '';
    toast('success', 'Done', { id: tid });
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    toast('error', 'Transcription failed: ' + e.message, { id: tid });
  } finally {
    btn.disabled = false;
  }
}
