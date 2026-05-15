async function resolveWildcards(text) {
  if (!text || !text.includes('%%')) return text;
  const wildcards = await _wc_fetch();
  const map = Object.fromEntries(wildcards.map(w => [w.name.toLowerCase(), w]));
  return text.replace(/%%([^%]+)%%/g, (match, name) => {
    const wc = map[name.toLowerCase()];
    if (!wc || !wc.entries.length) return match;
    return _wc_pickWeighted(wc.entries);
  });
}

function _wc_pickWeighted(entries) {
  const total = entries.reduce((s, e) => s + (e.weight || 5), 0);
  let r = Math.random() * total;
  for (const e of entries) {
    r -= (e.weight || 5);
    if (r <= 0) return e.text;
  }
  return entries[entries.length - 1].text;
}

async function _wc_fetch() {
  try {
    const r = await fetch('/v1/wildcards');
    if (!r.ok) return [];
    const data = await r.json();
    return data.wildcards || [];
  } catch {
    return [];
  }
}
