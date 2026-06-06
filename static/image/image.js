// Shared utilities + tab initialization for the Image page.
// Loaded last so tab modules can reference these as globals from event handlers.

// ── L1 nav: Image ↔ Vision ──────────────────────────────────────────────────

let _visionInited = false;

function switchL1(view) {
  document.querySelectorAll('#visual-l1-nav .l1-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.l1 === view)
  );
  document.getElementById('image-view').style.display  = view === 'image'  ? '' : 'none';
  document.getElementById('vision-view').style.display = view === 'vision' ? '' : 'none';
  if (view === 'vision' && !_visionInited) { initVisionTab(); _visionInited = true; }
}

// ── Tab switching (L2, within Image) ─────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  const pane = document.getElementById('tab-' + name);
  const btn  = document.querySelector('.tab-btn[data-tab="' + name + '"]');
  if (pane) pane.classList.add('active');
  if (btn)  btn.classList.add('active');
  if (name === 'prompts') initPromptsTab();
}

// ── Init ─────────────────────────────────────────────────────────────────────

initGenerateTab();
