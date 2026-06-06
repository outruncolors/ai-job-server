/* Shared API client. Auto-prepends /v1 unless path already starts with it.
   Throws Error with response body text on non-2xx. */
async function api(path, method = 'GET', body = null) {
  const url = path.startsWith('/v1') ? path : '/v1' + path;
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(await r.text());
  if (r.status === 204) return null;          // No Content (e.g. DELETE)
  const text = await r.text();
  return text ? JSON.parse(text) : null;      // tolerate empty bodies
}
