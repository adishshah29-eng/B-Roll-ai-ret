"use strict";
// Libraries: create / fill / watch domain libraries, and feed the library pickers (editor, search, script).
(() => {
  const q = (s) => document.querySelector(s);
  window.LIBS = [];
  let timer = null;

  async function refresh() {
    try { window.LIBS = await (await fetch("/api/libraries")).json(); } catch { return; }
    renderList(); fillSelects();
    const busy = window.LIBS.some((l) => l.pending > 0 || (l.build && !["ready", "failed"].includes(l.build.stage)));
    clearTimeout(timer);
    if (busy) timer = setTimeout(refresh, 3000);
  }

  function fillSelects() {
    for (const id of ["edLib", "libFilter", "planLib"]) {
      const sel = q("#" + id); if (!sel) continue;
      const keep = sel.value;
      sel.replaceChildren(el("option", { value: "0" }, "All footage"),
        ...window.LIBS.map((l) => el("option", { value: String(l.id) }, `${l.name} (${l.clips} clips)`)));
      sel.value = [...sel.options].some((o) => o.value === keep) ? keep : (id === "edLib" && window.LIBS.length === 1 ? String(window.LIBS[0].id) : "0");
    }
    syncLive();
  }

  function syncLive() {                              // "All footage" always searches Pixabay live; a library can work fully offline
    const none = q("#edLib").value === "0";
    q("#edLive").disabled = none;
    if (none) q("#edLive").checked = true;
  }
  q("#edLib").addEventListener("change", () => { syncLive(); if (q("#edLib").value !== "0") q("#edLive").checked = false; });

  function stateLine(l) {
    const b = l.build;
    if (b && b.stage === "failed") return el("div", { class: "st bad" }, `Build failed: ${b.error}`);
    if (b && !["ready"].includes(b.stage)) {
      const extra = b.stage === "downloading clips" ? ` ${b.downloaded || 0}/${(b.picked || 0)}` : "";
      return el("div", { class: "st" }, `${b.stage}${extra} · ${Math.round((b.progress || 0) * 100)}%${l.pending ? ` · ${l.pending} clips still analysing` : ""}`);
    }
    if (l.pending) return el("div", { class: "st" }, `analysing ${l.pending} clip${l.pending > 1 ? "s" : ""}…`);
    return el("div", { class: "st ok" }, l.clips ? "ready" : "empty: add clips");
  }

  function renderList() {
    const box = q("#libList");
    if (!window.LIBS.length) { box.replaceChildren(el("div", { class: "meta" }, "No libraries yet. Create one below.")); return; }
    box.replaceChildren(...window.LIBS.map((l) => {
      const file = el("input", { type: "file", accept: "video/*", multiple: "", hidden: "" });
      file.addEventListener("change", () => upload(l.id, file.files));
      return el("div", { class: "librow" },
        el("div", {}, el("div", { class: "nm" }, l.name), el("div", { class: "dm" }, l.domain || "")),
        el("div", {}, el("div", { class: "ct" }, `${l.clips} clips · ${l.shots} shots`), stateLine(l)),
        el("div", { class: "acts" }, file,
          el("button", { onclick: () => file.click() }, "Add clips"),
          el("button", { onclick: () => remove(l) }, "Delete")));
    }));
  }

  async function upload(id, files) {
    if (!files || !files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    q("#libMsg").textContent = `Uploading ${files.length} clip${files.length > 1 ? "s" : ""}…`;
    q("#libProg").style.width = "40%";
    const r = await fetch(`/api/libraries/${id}/upload`, { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    q("#libMsg").textContent = r.ok ? `Added ${d.saved} clip${d.saved > 1 ? "s" : ""}; analysing in the background.` : (d.detail || "Upload failed");
    q("#libProg").style.width = r.ok ? "100%" : "0";
    refresh();
  }

  async function remove(l) {
    if (!confirm(`Delete the library "${l.name}"? Its clips stay on disk and return to the general pool.`)) return;
    await fetch(`/api/libraries/${l.id}`, { method: "DELETE" });
    refresh();
  }

  document.querySelectorAll('input[name="libKind"]').forEach((r) => r.addEventListener("change", () => {
    const k = document.querySelector('input[name="libKind"]:checked').value;
    q("#libUploadBox").hidden = k !== "upload"; q("#libAutoBox").hidden = k !== "auto"; q("#libFolderBox").hidden = k !== "folder";
  }));

  q("#libCreate").addEventListener("click", async () => {
    const kind = document.querySelector('input[name="libKind"]:checked').value, msg = q("#libMsg");
    const name = q("#libName").value.trim(), domain = q("#libDomain").value.trim();
    if (!name) { msg.textContent = "Give the library a name."; return; }
    if (kind === "upload" && !q("#libFiles").files.length) { msg.textContent = "Choose the clips to upload."; return; }
    if (kind === "auto" && !domain) { msg.textContent = "Describe the domain so Pixabay can be searched."; return; }
    if (kind === "folder" && !q("#libFolder").value.trim()) { msg.textContent = "Enter the folder path."; return; }
    q("#libCreate").disabled = true; msg.textContent = "Creating…";
    try {
      const r = await fetch("/api/libraries", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, domain, kind: kind === "upload" ? "empty" : kind, folder: q("#libFolder").value.trim() || null, n_clips: +q("#libN").value || 60 }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "could not create");
      if (kind === "upload") await upload(d.id, q("#libFiles").files);
      else msg.textContent = kind === "auto" ? "Building: searching Pixabay, downloading and analysing clips…" : "Indexing the folder…";
      q("#libName").value = ""; q("#libFiles").value = "";
    } catch (e) { msg.textContent = e.message; }
    q("#libCreate").disabled = false;
    refresh();
  });

  q("#libFilter").addEventListener("change", () => {          // Search tab: limit results to one library
    const v = +q("#libFilter").value;
    if (v) filters.library = v; else delete filters.library;
    if (q("#q").value.trim()) runSearch();
  });

  refresh();
})();
