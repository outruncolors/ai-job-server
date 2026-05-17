/* Render a "resolved prompt" block above output sections on submit-driven
   pages (image, voice). Each item is:
     { label?: string,
       resolved: string,                       // text actually sent
       substitutions?: [{ token, value }] }    // %%name%% → picked value
   Multiple items render as numbered blocks (e.g. voice segments).
   With no items, renders the INPUT header + an empty-state hint. */

function renderResolvedPrompt(container, items) {
  if (!container) return;
  container.innerHTML = '';
  container.style.display = 'block';

  const header = document.createElement('p');
  header.className = 'section-label resolved-section-label';
  header.textContent = 'INPUT';
  container.appendChild(header);

  if (!items || !items.length) {
    const empty = document.createElement('div');
    empty.className = 'resolved-block resolved-empty';
    empty.textContent = 'Submit a prompt to see the resolved input here.';
    container.appendChild(empty);
    return;
  }

  items.forEach((item, i) => {
    const block = document.createElement('div');
    block.className = 'resolved-block';

    if (item.label || items.length > 1) {
      const lab = document.createElement('div');
      lab.className = 'resolved-label';
      lab.textContent = item.label || ('Segment ' + (i + 1));
      block.appendChild(lab);
    }

    const text = document.createElement('div');
    text.className = 'resolved-text';
    text.textContent = item.resolved || '';
    block.appendChild(text);

    if (item.substitutions && item.substitutions.length) {
      const list = document.createElement('ul');
      list.className = 'resolved-subs';
      for (const s of item.substitutions) {
        const li = document.createElement('li');
        const tok = document.createElement('code');
        tok.textContent = s.token;
        const val = document.createElement('span');
        val.className = 'resolved-sub-val';
        val.textContent = s.value;
        li.append(tok, document.createTextNode(' → '), val);
        list.appendChild(li);
      }
      block.appendChild(list);
    }
    container.appendChild(block);
  });
}

function clearResolvedPrompt(container) {
  if (!container) return;
  renderResolvedPrompt(container, []);
}

/* Auto-initialize the placeholder state on page load. Any element with the
   class .resolved-prompt picks up the empty-state INPUT header so the user
   can confirm the script is wired even before submitting anything. */
function _initResolvedPrompts() {
  document.querySelectorAll('.resolved-prompt').forEach(el => renderResolvedPrompt(el, []));
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _initResolvedPrompts);
} else {
  _initResolvedPrompts();
}
