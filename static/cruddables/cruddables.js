// Cruddables page — per-type Export / Copy / Extend.
// api() prepends /v1; cruddables router is /v1/cruddables → /cruddables/types,
// /cruddables/<type>/export, /cruddables/<type>/extend.

(function () {
  const esc = (s) => (typeof _escHtml === "function" ? _escHtml(String(s ?? "")) : String(s ?? ""));
  const note = (msg, kind) => {
    if (typeof toast === "function") toast(msg, kind);
    else console.log(`[${kind || "info"}] ${msg}`);
  };
  const $ = (id) => document.getElementById(id);

  async function load() {
    let types = [];
    try {
      const data = await api("/cruddables/types");
      types = (data && data.types) || [];
    } catch (e) {
      note("Failed to load cruddable types: " + e.message, "error");
    }
    render(types);
  }

  function render(types) {
    const root = $("cr-types");
    if (!types.length) {
      root.innerHTML = '<p class="muted">No cruddable types registered.</p>';
      return;
    }
    root.innerHTML = types
      .map(
        (t) => `<div class="cr-card" data-type="${esc(t.type)}">
          <div class="cr-head">
            <h3>${esc(t.label)}</h3>
            <span class="count">(${t.count})</span>
            <span class="spacer"></span>
            <button class="btn act-export">Export JSON</button>
            <button class="btn act-copy">Copy JSON</button>
          </div>
          <div class="cr-extend">
            <textarea placeholder='Paste an array of envelopes to upsert, e.g. [{"type":"${esc(t.type)}", "id":"…", "name":"…", "data":{…}}]'></textarea>
            <div class="cr-extend-row">
              <input type="file" accept="application/json,.json" class="act-file" />
              <button class="btn btn-primary act-extend">Extend</button>
            </div>
            <pre class="cr-report"></pre>
          </div>
        </div>`
      )
      .join("");

    root.querySelectorAll(".cr-card").forEach((card) => {
      const type = card.dataset.type;
      card.querySelector(".act-export").addEventListener("click", () => exportType(type));
      card.querySelector(".act-copy").addEventListener("click", () => copyType(type));
      card.querySelector(".act-extend").addEventListener("click", () => extendType(type, card));
      card.querySelector(".act-file").addEventListener("change", (e) => readFile(e, card));
    });
  }

  async function fetchExport(type) {
    return api(`/cruddables/${encodeURIComponent(type)}/export`);
  }

  async function exportType(type) {
    try {
      const items = await fetchExport(type);
      const text = JSON.stringify(items, null, 2);
      const blob = new Blob([text], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${type}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      note("Export failed: " + e.message, "error");
    }
  }

  async function copyType(type) {
    try {
      const items = await fetchExport(type);
      await navigator.clipboard.writeText(JSON.stringify(items, null, 2));
      note(`Copied ${items.length} ${type} item(s)`, "success");
    } catch (e) {
      note("Copy failed: " + e.message, "error");
    }
  }

  function readFile(ev, card) {
    const file = ev.target.files && ev.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      card.querySelector("textarea").value = reader.result;
    };
    reader.readAsText(file);
  }

  async function extendType(type, card) {
    const ta = card.querySelector("textarea");
    const report = card.querySelector(".cr-report");
    let items;
    try {
      items = JSON.parse(ta.value);
    } catch (e) {
      note("Invalid JSON: " + e.message, "error");
      return;
    }
    if (!Array.isArray(items)) {
      note("Body must be a JSON array of envelopes", "error");
      return;
    }
    try {
      const r = await api(`/cruddables/${encodeURIComponent(type)}/extend`, "POST", items);
      const c = r.created || 0, u = r.updated || 0, e = r.errored || 0;
      note(`${c} created, ${u} updated${e ? `, ${e} errored` : ""}`, e ? "warn" : "success");
      report.textContent = JSON.stringify(r, null, 2);
      if (!e) load();
    } catch (err) {
      note("Extend failed: " + err.message, "error");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
