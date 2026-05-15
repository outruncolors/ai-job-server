// Shared utilities + tab initialization for the Image page.
// Loaded last so tab modules can reference these as globals from event handlers.

// ── Tab switching ──────────────────────────────────────────────────────────

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
