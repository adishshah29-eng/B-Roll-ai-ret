"use strict";
// Editor: upload an A-roll, review the B-roll spots, preview instantly (overlay video, no render), render the MP4.
(() => {
  const E = { proj: null, sel: -1, poll: null };
  const q = (s) => document.querySelector(s);
  const mk = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "class") e.className = v;
      else if (k === "style") e.style.cssText = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k !== null && k !== undefined && k !== "") e.append(k instanceof Node ? k : document.createTextNode(String(k)));
    return e;
  };
  const tc = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
  const j = async (url, opts) => {
    const r = await fetch(url, opts);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
    return d;
  };
  const main = q("#edMain"), over = q("#edOver");

  // ---------- start screen ----------
  j("/api/editor/config").then((c) => {
    q("#edEngine").replaceChildren(mk("span", { class: "engine " + (c.llm === "gemini" ? "on" : "") }, c.llm === "gemini" ? `Gemini (${c.model})` : "Offline engine"),
      c.llm === "gemini" ? " reads your script and writes the Pixabay searches."
        : " writes the Pixabay searches from keywords. Add GEMINI_API_KEY to .env for smarter B-roll choices.",
      c.pixabay ? "" : mk("span", { style: "color:var(--bad)" }, "  Pixabay key missing: only the built-in library will be used."));
  }).catch(() => {});
  async function loadList() {
    try {
      const ps = await j("/api/editor/projects");
      q("#edList").replaceChildren(ps.length ? "" : "No projects yet.",
        ...ps.map((p) => mk("div", { class: "edproj", onclick: () => open(p.id) },
          `${p.name || p.id} · ${p.duration ? tc(p.duration) : "…"} · ${p.stage}`)));
    } catch { /* ignore */ }
  }

  q("#edUpload").addEventListener("click", async () => {
    const f = q("#edFile").files[0];
    if (!f) { q("#edMsg").textContent = "Choose a video first."; return; }
    const fd = new FormData();
    fd.append("file", f); fd.append("name", q("#edName").value); fd.append("script", q("#edScript").value);
    q("#edUpload").disabled = true; q("#edMsg").textContent = "Uploading…";
    try {
      const { id } = await j("/api/editor/projects", { method: "POST", body: fd });
      waitFor(id, ["ready"], () => open(id));
    } catch (e) { q("#edMsg").textContent = e.message; q("#edUpload").disabled = false; }
  });

  function waitFor(id, done, then) {
    clearInterval(E.poll);
    E.poll = setInterval(async () => {
      const s = await j(`/api/editor/projects/${id}/status`).catch(() => null);
      if (!s) return;
      q("#edMsg").textContent = s.error ? `Failed: ${s.error}` : `${s.stage}…`;
      q("#edProg").style.width = `${Math.round(s.progress * 100)}%`;
      if (s.error || s.stage === "failed") { clearInterval(E.poll); q("#edUpload").disabled = false; }
      if (done.includes(s.stage)) { clearInterval(E.poll); q("#edUpload").disabled = false; then(s); }
    }, 1500);
  }

  // ---------- workspace ----------
  async function open(id) {
    const p = await j(`/api/editor/projects/${id}`);
    if (p.stage !== "ready") { q("#edMsg").textContent = `Project is ${p.stage}.`; return; }
    E.proj = p; E.sel = -1;
    q("#edStart").hidden = true; q("#edWork").hidden = false;
    q("#edTitle").textContent = p.name;
    const L = p.llm || {};
    q("#edInfo").textContent = ` ${tc(p.duration)} · ${p.language || "?"} · ${(p.units || []).filter((u) => u.kind === "speech").length} clips · ${(p.cuts || []).length} scene cuts · ${p.live ? p.live.added : 0} new Pixabay clips`;
    q("#edSummary").replaceChildren(
      mk("span", { class: "engine " + (L.provider === "gemini" ? "on" : "") }, L.provider === "gemini" ? "Gemini" : "Offline engine"),
      L.summary ? " " + L.summary : "", L.error ? mk("span", { class: "meta", style: "color:var(--warn)" }, `  (Gemini failed: ${L.error})`) : "");
    main.src = `/api/editor/projects/${id}/video`;
    q("#edOut").replaceChildren();
    renderAll();
    hydrateAll();
  }

  async function hydrateAll() {           // stock clips need a local file for preview
    for (const s of E.proj.slots) {
      for (const sh of [s.shot, ...(s.alts || []).slice(0, 3)]) {
        if (sh && sh.file_id == null && sh.stock_id != null) {
          try { sh.file_id = (await j(`/api/shots/${sh.id}/hydrate`, { method: "POST" })).file_id; } catch { /* still image */ }
        }
      }
    }
  }

  q("#edBack").addEventListener("click", () => {
    main.pause(); over.pause(); q("#edWork").hidden = true; q("#edStart").hidden = false; loadList();
  });

  function renderAll() { renderTimeline(); renderTranscript(); renderPanel(); }

  function renderTimeline() {
    const tl = q("#edTimeline"), D = E.proj.duration || 1, id = E.proj.id;
    tl.replaceChildren(q("#edHead") || mk("div", { id: "edHead", class: "edhead" }));
    const every = E.proj.strip_every || 2;
    for (const f of E.proj.strip || []) {                 // FRAMES lane: filmstrip of the picture
      tl.append(mk("div", { class: "edframe", style: `left:${(f.t / D) * 100}%;width:${(every / D) * 100}%;background-image:url(/api/editor/projects/${id}/frames/${f.file})` }));
    }
    for (const c of E.proj.cuts || []) tl.append(mk("div", { class: "edcut", title: `scene cut ${tc(c)}`, style: `left:${(c / D) * 100}%` }));
    const units = E.proj.units || (E.proj.segments || []).map((x) => ({ ...x, kind: "speech" }));
    for (const u of units) {                               // SPEECH lane: audio clips (speech) and pauses
      tl.append(mk("div", { class: "edseg " + u.kind, title: u.kind === "pause" ? "pause" : u.text,
        style: `left:${(u.start / D) * 100}%;width:${((u.end - u.start) / D) * 100}%`,
        onclick: (e) => { e.stopPropagation(); main.currentTime = u.start; } }));
    }
    E.proj.slots.forEach((s, i) => {                       // B-ROLL lane
      const sh = s.shot;
      const cls = "edslot" + (i === E.sel ? " sel" : "") + (!sh ? " none" : "");
      tl.append(mk("div", { class: cls, title: `${tc(s.start)}–${tc(s.end)}  ${s.query || s.text}`,
        style: `left:${(s.start / D) * 100}%;width:${((s.end - s.start) / D) * 100}%;${sh ? `background-image:url(${sh.thumb})` : ""}`,
        onclick: (e) => { e.stopPropagation(); select(i, true); } }));
    });
  }
  q("#edTimeline").addEventListener("click", (e) => {
    const r = q("#edTimeline").getBoundingClientRect();
    main.currentTime = ((e.clientX - r.left) / r.width) * (E.proj?.duration || 0);
  });

  function renderTranscript() {
    const box = q("#edTranscript");
    box.replaceChildren(...(E.proj.segments || []).map((s) => {
      const cov = E.proj.slots.some((x) => x.start < s.end && x.end > s.start);
      return mk("span", { class: cov ? "cov" : "", "data-s": s.start, "data-e": s.end, onclick: () => { main.currentTime = s.start; main.play(); } }, s.text + " ");
    }));
  }

  function select(i, seek) {
    E.sel = i;
    if (seek && E.proj.slots[i]) main.currentTime = E.proj.slots[i].start;
    renderTimeline(); renderPanel();
  }

  function renderPanel() {
    const box = q("#edPanel");
    const s = E.proj.slots[E.sel];
    if (!s) { box.replaceChildren(mk("div", { class: "meta" }, `${E.proj.slots.length} B-roll spots. Click one on the timeline to review, swap or adjust it. Highlighted transcript = covered by B-roll.`)); return; }
    const sh = s.shot;
    const v = sh?.verdict;
    const left = mk("div", {},
      sh ? mk("img", { src: sh.thumb, style: "width:100%;border-radius:8px" }) : mk("div", { class: "nomatch" }, "No clip: pick one below or delete this spot."),
      sh ? mk("div", { class: "meta" }, `${sh.file} · ${sh.source}${sh.licence ? " · " + sh.licence.label : ""}`) : "",
      v ? mk("div", { class: "vhead", style: "margin-top:6px" }, mk("span", { class: "pill st-" + v.status }, v.status), sh.label ? mk("span", { class: "labelpill" }, sh.label) : "") : "",
      sh?.why ? mk("ul", { class: "why" }, sh.why.map((w) => mk("li", {}, w))) : "");
    const qin = mk("input", { value: s.query || s.text });
    const right = mk("div", {},
      mk("div", {}, mk("b", {}, `${tc(s.start)} – ${tc(s.end)}`), mk("span", { class: "meta" }, `  ${s.reason || ""}`)),
      mk("div", { class: "meta", style: "margin:4px 0" }, `“${s.text}”`),
      mk("div", { class: "alts-label" }, "Search query sent to Pixabay (edit it, or pick another phrasing)"),
      qin,
      mk("div", { class: "qchips" }, [s.query, ...(s.alt_queries || [])].filter((x, i, a) => x && a.indexOf(x) === i).map((x) =>
        mk("button", { class: "qchip" + (x === (s.used_query || s.query) ? " on" : ""), onclick: () => { qin.value = x; refind(x); } }, x))),
      mk("div", { class: "acts" },
        mk("button", { class: "ghost", onclick: () => nudge(-0.5, 0) }, "Start −0.5"), mk("button", { class: "ghost", onclick: () => nudge(0.5, 0) }, "Start +0.5"),
        mk("button", { class: "ghost", onclick: () => nudge(0, -0.5) }, "End −0.5"), mk("button", { class: "ghost", onclick: () => nudge(0, 0.5) }, "End +0.5"),
        mk("button", { class: "ghost", onclick: () => refind(qin.value) }, "Search Pixabay"),
        mk("button", { class: "ghost", onclick: del }, "Delete")),
      (s.alts || []).length ? mk("div", { class: "alts-label" }, "Alternatives: click to swap") : "",
      mk("div", { class: "alts" }, (s.alts || []).map((a) => mk("div", { class: "alt", title: a.file, onclick: () => swap(a) },
        mk("img", { src: a.thumb, alt: "" }), mk("span", {}, a.score.toFixed(2)), a.verdict ? mk("i", { class: "dot " + a.verdict.status }) : ""))),
      s.n_rejected ? mk("div", { class: "meta", style: "margin-top:6px;color:var(--bad)" },
        `${s.n_rejected} clip(s) rejected: ${(s.rejected[0]?.verdict?.evidence || [""])[0]}`) : "");
    box.replaceChildren(mk("div", { class: "edp" }, left, right));
  }

  // ---------- edits ----------
  async function save(refill = false, live = false) {
    const r = await j(`/api/editor/projects/${E.proj.id}/slots`, { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slots: E.proj.slots, refill, live }) });
    E.proj.slots = r.slots;
    renderAll(); hydrateAll();
  }
  function nudge(da, db) {
    const s = E.proj.slots[E.sel];
    s.start = Math.max(0, +(s.start + da).toFixed(2)); s.end = Math.min(E.proj.duration, +(s.end + db).toFixed(2));
    if (s.end - s.start < 0.8) return;
    s.locked = true;
    save(false);
  }
  async function swap(a) {
    const s = E.proj.slots[E.sel];
    const old = s.shot;
    s.alts = [old, ...s.alts.filter((x) => x.id !== a.id)].filter(Boolean);
    s.shot = a; s.locked = true;
    await save(false);
    if (typeof teach === "function") teach(s.text, a, old ? [old.id] : []);     // the swap teaches Edit Memory
  }
  async function refind(query) {
    const s = E.proj.slots[E.sel];
    s.query = query; s.alt_queries = (s.alt_queries || []).filter((x) => x !== query); s.locked = false;
    E.proj.slots.forEach((x, i) => { if (i !== E.sel && x.shot) x.locked = true; });
    q("#edPanel").prepend(mk("div", { class: "meta busy" }, `Searching Pixabay for “${query}”…`));
    await save(true, true);
  }
  function del() { E.proj.slots.splice(E.sel, 1); E.sel = -1; save(false); }
  q("#edAdd").addEventListener("click", async () => {
    const t = main.currentTime || 0;
    const seg = (E.proj.segments || []).find((s) => s.start <= t && t < s.end);
    const slot = { start: +t.toFixed(2), end: +Math.min(E.proj.duration, t + 3).toFixed(2), text: seg ? seg.text : "", query: seg ? seg.text : "", reason: "added by you" };
    E.proj.slots.forEach((x) => { if (x.shot) x.locked = true; });
    E.proj.slots.push(slot);
    await save(true);
    select(E.proj.slots.findIndex((x) => x.start === slot.start), false);
  });

  // ---------- instant preview: overlay the B-roll inside each spot ----------
  let curSlot = null;
  function tick() {
    if (!E.proj || q("#edWork").hidden) return;
    const t = main.currentTime, D = E.proj.duration || 1;
    const head = q("#edHead"); if (head) head.style.left = `${(t / D) * 100}%`;
    const s = E.proj.slots.find((x) => x.shot && t >= x.start && t < x.end);
    if (s !== curSlot) {
      curSlot = s;
      if (s && s.shot.file_id != null) {
        const src = `/media/video/${s.shot.file_id}`;
        if (!over.src.endsWith(src)) over.src = src;
        over.currentTime = (s.shot.trim_in ?? s.shot.t_start) + (t - s.start);
        over.style.display = "block";
        q("#edBadge").style.display = "block"; q("#edBadge").textContent = `B-roll · ${s.shot.file}`;
        if (!main.paused) over.play().catch(() => {});
      } else {
        over.pause(); over.style.display = "none"; q("#edBadge").style.display = "none";
      }
    }
    document.querySelectorAll("#edTranscript span").forEach((sp) => sp.classList.toggle("now", t >= +sp.dataset.s && t < +sp.dataset.e));
  }
  main.addEventListener("timeupdate", tick);
  main.addEventListener("seeked", () => { curSlot = undefined; tick(); });
  main.addEventListener("play", () => { if (curSlot) over.play().catch(() => {}); });
  main.addEventListener("pause", () => over.pause());

  // ---------- render ----------
  q("#edRender").addEventListener("click", async () => {
    q("#edRender").disabled = true;
    q("#edOut").replaceChildren(mk("div", { class: "meta" }, "Rendering… (about 1–2× the video length on this laptop)"));
    try {
      await j(`/api/editor/projects/${E.proj.id}/render`, { method: "POST" });
      const id = E.proj.id;
      const t = setInterval(async () => {
        const s = await j(`/api/editor/projects/${id}/status`).catch(() => null);
        if (!s) return;
        if (s.stage === "rendered") {
          clearInterval(t); q("#edRender").disabled = false;
          const url = `/api/editor/projects/${id}/final.mp4?v=${Date.now()}`;
          q("#edOut").replaceChildren(mk("h3", { class: "memh" }, "Finished video"),
            mk("video", { src: url, controls: "", style: "width:100%;border-radius:10px" }),
            mk("div", { class: "acts" }, mk("a", { class: "ghost link", href: `/api/editor/projects/${id}/final.mp4?download=1` }, "Download MP4")));
        } else if (s.error) {
          clearInterval(t); q("#edRender").disabled = false;
          q("#edOut").replaceChildren(mk("div", { class: "err" }, s.error));
        } else {
          q("#edOut").firstChild.textContent = `${s.stage}…`;
        }
      }, 2000);
    } catch (e) { q("#edRender").disabled = false; q("#edOut").replaceChildren(mk("div", { class: "err" }, e.message)); }
  });

  loadList();
})();
