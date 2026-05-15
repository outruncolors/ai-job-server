# UI Cheatsheet — AI Job Server

Quick HTML+class reference for all shared patterns. Full rationale in `ui-standards.md`.

---

## Page skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>Page Name · AI Job Server</title>
  <link rel="stylesheet" href="/css/responsive.css">
  <link rel="stylesheet" href="/css/components.css">
  <link rel="stylesheet" href="styles.css">
</head>
<body>
<nav id="topnav"></nav>

<div id="panels">
  <div id="panel-left">
    <!-- controls / list -->
  </div>
  <div id="panel-right">
    <!-- output / detail -->
  </div>
</div>

<script src="/js/nav.js"></script>
<script src="/js/api.js"></script>
<script src="/js/escape.js"></script>
<script src="/js/poll.js"></script>    <!-- only if page polls jobs -->
<script src="/js/toast.js"></script>
<script src="page.js"></script>
<script src="/js/nav-mobile.js"></script>
</body>
</html>
```

**Fixed left panel:** `<div id="panel-left" style="flex: 0 0 var(--panel-w-md);">`
Width tokens: `--panel-w-sm` 300px · `--panel-w-md` 360px · `--panel-w-lg` 420px · `--panel-w-xl` 480px

---

## Buttons

```html
<button>Primary</button>
<button class="secondary">Secondary</button>
<button class="danger">Delete</button>
<button disabled>Disabled</button>
```

Wrap a button row in `<div class="form-actions">` for consistent spacing.

---

## Inputs

```html
<label>Field name</label>
<input type="text" placeholder="…">

<label>Number</label>
<input type="number" step="1" min="0">

<label>Textarea</label>
<textarea></textarea>

<!-- Checkbox stays on one line with its label -->
<label><input type="checkbox"> Option label</label>

<!-- Two fields side by side -->
<div class="row">
  <div><label>Width</label><input type="number"></div>
  <div><label>Height</label><input type="number"></div>
</div>
<!-- Add class="dims-row" if this row should stack vertically on mobile -->
```

---

## Tabs

```html
<!-- Tab bar -->
<div id="my-tabs">
  <button class="tab-btn active" data-tab="first"  onclick="switchTab('first')">First</button>
  <button class="tab-btn"        data-tab="second" onclick="switchTab('second')">Second</button>
</div>

<!-- Panels -->
<div class="tab-pane active" id="pane-first">…</div>
<div class="tab-pane"        id="pane-second">…</div>
```

```javascript
function switchTab(tab) {
  document.querySelectorAll('#my-tabs .tab-btn').forEach(b =>
    b.classList.toggle('active', b.dataset.tab === tab)
  );
  document.getElementById('pane-first').classList.toggle('active',  tab === 'first');
  document.getElementById('pane-second').classList.toggle('active', tab === 'second');
}
```

---

## Toast

```javascript
// Transient notifications — auto-dismissed
toast('success', 'Saved!');
toast('error', 'Failed: ' + e.message);
toast('info', 'Loading…');

// Persistent toast (must be dismissed manually or by code)
const id = toast('info', 'Connecting…', { persistent: true, id: 'conn' });

// Update in place (countdown display)
toast('info', 'Reconnecting in 3s', { id: 'conn', countdown: true });
toastSetCountdown('conn', '2s…');
toastDismiss('conn');
```

No HTML required — `toast.js` auto-injects `#toast-stack` on first call.

---

## Drawers

```html
<div id="drawer-overlay" onclick="closeDrawer()"></div>
<div class="drawer" id="my-drawer">
  <div class="drawer-header">
    <span>Title</span>
    <button onclick="closeDrawer()">✕</button>
  </div>
  <div class="drawer-body">…</div>
</div>
```

```javascript
function openDrawer()  { document.getElementById('my-drawer').classList.add('open');
                         document.getElementById('drawer-overlay').classList.add('open'); }
function closeDrawer() { document.getElementById('my-drawer').classList.remove('open');
                         document.getElementById('drawer-overlay').classList.remove('open'); }
```

---

## Cards

```html
<div class="card tool-card">…</div>
<div class="card tool-card selected">…</div>
```

Use a semantic modifier class alongside `.card`. The `selected` state adds accent border.

---

## Status badges

```html
<span class="status-queued">queued</span>
<span class="status-running">running</span>
<span class="status-done">done</span>
<span class="status-failed">failed</span>
```

---

## Empty state

```html
<div id="detail-empty" class="empty">Select an item to view details.</div>
```

Toggle visibility with `style.display`. Keep `id` for `getElementById` callers.

---

## Hint text

```html
<div class="hint">Comma-separated values, e.g. tag1, tag2</div>
<span class="hint">(optional)</span>
```

---

## Collapsible sections

```html
<details class="section-collapse">
  <summary>SECTION TITLE</summary>
  <div>Content goes here.</div>
</details>

<!-- Open by default -->
<details class="section-collapse" open>
  <summary>EXPANDED</summary>
  …
</details>
```

---

## API client

```javascript
// GET — auto-prepends /v1
const data = await api('/chain-sequences');

// POST with JSON body
const result = await api('/chain-sequences', 'POST', { name: 'my-seq', steps: [] });

// PUT / DELETE
await api('/chain-sequences/' + id, 'PUT', body);
await api('/chain-sequences/' + id, 'DELETE');

// Throws Error with response text on non-2xx
try {
  const data = await api('/endpoint');
} catch (e) {
  toast('error', e.message);
}
```

---

## Job polling

```javascript
const handle = pollJob(jobId, {
  intervalMs: 3000,   // default 3000ms; image page uses 800ms
  onUpdate(job) {
    statusEl.textContent = 'Running… (' + job.status + ')';
  },
  onDone(job) {
    statusEl.textContent = 'Done';
    // job.job_id, job.status, job.error available
  },
  onError(job) {
    statusEl.textContent = 'Error: ' + (job.error || 'unknown');
  },
});

// Cancel early (e.g. user navigates away):
handle.stop();
```

Polling auto-stops on `done`, `error`, or `failed`. Network errors are silently retried.

---

## HTML escaping

```javascript
// Always escape before inserting into innerHTML
el.innerHTML = '<span>' + _escHtml(untrustedValue) + '</span>';

// Template literals — escape each interpolated value
list.innerHTML = items.map(item => `
  <div class="card" onclick="select(${_escHtml(JSON.stringify(item.id))})">
    ${_escHtml(item.name)}
  </div>
`).join('');
```
