// Packs page — browse/filter/sort packs and Apply them.
// api() prepends /v1; the packs router lives at /v1/packs, so endpoints are
// /packs/packs, /packs/<type>/<id>, /packs/<type>/<id>/apply.

(function () {
  const esc = (s) => (typeof _escHtml === "function" ? _escHtml(String(s ?? "")) : String(s ?? ""));
  const note = (msg, kind) => {
    if (typeof toast === "function") toast(msg, kind);
    else console.log(`[${kind || "info"}] ${msg}`);
  };

  let ALL = [];

  const $ = (id) => document.getElementById(id);

  async function load() {
    try {
      const data = await api("/packs/packs");
      ALL = (data && data.packs) || [];
    } catch (e) {
      ALL = [];
      note("Failed to load packs: " + e.message, "error");
    }
    buildFilters();
    render();
  }

  function buildFilters() {
    const typeSel = $("pk-type");
    const tagSel = $("pk-tag");
    const types = [...new Set(ALL.map((p) => p.type))].sort();
    const tags = [...new Set(ALL.flatMap((p) => p.tags || []))].sort();
    typeSel.innerHTML =
      '<option value="">All types</option>' +
      types.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
    tagSel.innerHTML =
      '<option value="">All tags</option>' +
      tags.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  }

  function filtered() {
    const q = $("pk-search").value.trim().toLowerCase();
    const type = $("pk-type").value;
    const tag = $("pk-tag").value;
    const sort = $("pk-sort").value;
    let out = ALL.filter((p) => {
      if (type && p.type !== type) return false;
      if (tag && !(p.tags || []).includes(tag)) return false;
      if (q) {
        const hay = `${p.name} ${p.description} ${(p.tags || []).join(" ")} ${p.type}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    out.sort((a, b) => {
      if (sort === "count") return (b.item_count || 0) - (a.item_count || 0);
      if (sort === "type") return (a.type || "").localeCompare(b.type || "") || (a.name || "").localeCompare(b.name || "");
      return (a.name || "").localeCompare(b.name || "");
    });
    return out;
  }

  function render() {
    const list = $("pk-list");
    const rows = filtered();
    if (!rows.length) {
      list.innerHTML = '<p class="muted">No packs found.</p>';
      return;
    }
    list.innerHTML = rows
      .map((p) => {
        const tags = (p.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("");
        return `<div class="pk-card" data-type="${esc(p.type)}" data-id="${esc(p.id)}">
          <h3>${esc(p.name)}</h3>
          <p class="pk-desc">${esc(p.description || "")}</p>
          <div class="pk-meta">
            <span class="chip type">${esc(p.type)}</span>
            <span class="chip">${p.item_count || 0} item(s)</span>
            <span class="chip source-${esc(p.source)}">${esc(p.source)}</span>
            ${tags}
          </div>
          <div class="pk-actions">
            <button class="btn btn-primary act-apply">Apply</button>
            <button class="btn act-view">View JSON</button>
          </div>
        </div>`;
      })
      .join("");

    list.querySelectorAll(".pk-card").forEach((card) => {
      const type = card.dataset.type;
      const id = card.dataset.id;
      card.querySelector(".act-apply").addEventListener("click", () => applyPack(type, id, card));
      card.querySelector(".act-view").addEventListener("click", () => viewJson(type, id));
    });
  }

  async function applyPack(type, id, card) {
    const btn = card.querySelector(".act-apply");
    btn.disabled = true;
    btn.textContent = "Applying…";
    try {
      const r = await api(`/packs/${encodeURIComponent(type)}/${encodeURIComponent(id)}/apply`, "POST");
      const c = r.created || 0, u = r.updated || 0, e = r.errored || 0;
      note(`Applied "${id}": ${c} created, ${u} updated${e ? `, ${e} errored` : ""}`, e ? "warn" : "success");
    } catch (err) {
      note("Apply failed: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Apply";
    }
  }

  async function viewJson(type, id) {
    try {
      const doc = await api(`/packs/${encodeURIComponent(type)}/${encodeURIComponent(id)}`);
      const text = JSON.stringify(doc, null, 2);
      $("pk-json-title").textContent = `${type} / ${id}`;
      $("pk-json-body").textContent = text;
      const dlg = $("pk-json-dialog");
      $("pk-json-copy").onclick = async () => {
        try { await navigator.clipboard.writeText(text); note("Copied", "success"); }
        catch { note("Copy failed", "error"); }
      };
      $("pk-json-download").onclick = () => downloadText(`${type}_${id}.json`, text);
      dlg.showModal();
    } catch (err) {
      note("Failed to load pack: " + err.message, "error");
    }
  }

  function downloadText(filename, text) {
    const blob = new Blob([text], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function init() {
    ["pk-search", "pk-type", "pk-tag", "pk-sort"].forEach((id) => {
      const el = $(id);
      el.addEventListener("input", render);
      el.addEventListener("change", render);
    });
    $("pk-json-close").addEventListener("click", () => $("pk-json-dialog").close());
    load();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
