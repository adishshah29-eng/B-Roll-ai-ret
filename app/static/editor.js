"use strict";
// Editor: upload an A-roll, review the B-roll spots, preview instantly (overlay video, no render), render the MP4.
(() => {
  const E = { proj: null, sel: -1, poll: null, pane: "spot" };
  const q = (s) => document.querySelector(s);
  const mk = (tag, props = {}, ...kids) => {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
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
  q("#edEngine").replaceChildren(mk("span", { class: "meta" }, "Checking the AI engine…"));
  j("/api/editor/config?check=1").then((c) => {
    const g = c.gemini || {};
    const badge = !g.enabled ? mk("span", { class: "engine" }, "Offline engine")
      : g.ok ? mk("span", { class: "engine on" }, `Gemini (${g.model})`)
        : mk("span", { class: "engine warn" }, "Gemini not working: offline engine");
    const note = !g.enabled ? " writes the Pixabay searches from the concept list and skips lines with nothing to film. Add GEMINI_API_KEY to .env for much better choices."
      : g.ok ? " reads your whole script and writes the Pixabay searches."
        : ` ${g.error || "the key was rejected"}. The editor still works, but with weaker offline searches.`;
    q("#edEngine").replaceChildren(badge, note,
      c.pixabay ? "" : mk("span", { style: "color:var(--bad)" }, "  Pixabay key missing: only the built-in library will be used."));
  }).catch(() => q("#edEngine").replaceChildren(mk("span", { class: "engine warn" }, "Could not check the AI engine")));
  async function loadList() {
    try {
      const ps = await j("/api/editor/projects");
      q("#edList").replaceChildren(ps.length ? "" : "No projects yet.",
        ...ps.map((p) => mk("div", { class: "edproj", onclick: () => open(p.id) },
          `${p.name || p.id} · ${p.duration ? tc(p.duration) : "…"} · ${p.stage}`)));
    } catch { /* ignore */ }
  }

  // dropzone: show the chosen file, accept drag and drop
  const showPicked = () => { const f = q("#edFile").files[0]; q("#edFileName").textContent = f ? `${f.name} · ${(f.size / 1048576).toFixed(1)} MB` : ""; };
  q("#edFile").addEventListener("change", showPicked);
  const drop = q("#edDrop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => {
    const f = [...(e.dataTransfer?.files || [])].find((x) => x.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|avi)$/i.test(x.name));
    if (!f) { q("#edMsg").textContent = "That file is not a video (use mp4, mov, webm, mkv or avi)."; return; }
    const dt = new DataTransfer(); dt.items.add(f); q("#edFile").files = dt.files; showPicked();
  });

  q("#edUpload").addEventListener("click", async () => {
    const f = q("#edFile").files[0];
    if (!f) { q("#edMsg").textContent = "Choose a video first."; return; }
    const fd = new FormData();
    fd.append("file", f); fd.append("name", q("#edName").value); fd.append("script", q("#edScript").value);
    fd.append("library", q("#edLib").value || "0"); fd.append("live", q("#edLive").checked ? "1" : "");
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
    q("#edInfo").textContent = ` ${tc(p.duration)} · ${p.language || "?"} · ${(p.units || []).filter((u) => u.kind === "speech").length} clips · ${(p.cuts || []).length} scene cuts · ${p.live ? p.live.added : 0} new Pixabay clips · library: ${((window.LIBS || []).find((l) => l.id === p.library) || {}).name || "all footage"}${p.timings ? ` · analysed in ${Math.round(p.timings.total)} s` : ""}`;
    q("#edInfo").title = p.timings ? Object.entries(p.timings).map(([k, v]) => `${k}: ${v} s`).join("\n") : "";
    q("#edSummary").replaceChildren(
      mk("span", { class: "engine " + (L.provider === "gemini" ? "on" : "") }, L.provider === "gemini" ? "Gemini" : "Offline engine"),
      L.summary ? " " + L.summary : "",
      L.error ? mk("span", { class: "engine warn", style: "margin-left:8px", title: L.error }, "Gemini failed for this project: used the offline engine") : "");
    main.src = `/api/editor/projects/${id}/video`;
    q("#edOut").replaceChildren();
    q("#edFindRes").replaceChildren(); q("#edFindMeta").textContent = "";
    showPane("spot");
    renderAll();
    hydrateAll();
  }

  // stock clips need a local file before they can play in the preview
  const hydrating = new Set(), hydrateFailed = new Set();
  async function hydrateOne(sh) {
    if (!sh || sh.file_id != null || sh.stock_id == null || hydrating.has(sh.id) || hydrateFailed.has(sh.id)) return;
    hydrating.add(sh.id);
    try { sh.file_id = (await j(`/api/shots/${sh.id}/hydrate`, { method: "POST" })).file_id; }
    catch { hydrateFailed.add(sh.id); }                   // stays a still image in the preview; render reports it
    finally { hydrating.delete(sh.id); }
    curKey = null; tick();                                 // the spot under the playhead may be playable now
  }
  async function hydrateAll() {           // the clips on the timeline first (all at once), then a few alternatives
    await Promise.all(E.proj.slots.map((s) => hydrateOne(s.shot)));
    for (const s of E.proj.slots) for (const sh of (s.alts || []).slice(0, 3)) await hydrateOne(sh);
  }

  q("#edBack").addEventListener("click", () => {
    main.pause(); over.pause(); q("#edWork").hidden = true; q("#edStart").hidden = false; loadList();
  });

  function renderAll() { renderTimeline(); renderTranscript(); renderPanel(); if (E.pane === "sugg") renderSugg(); }

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
    E.sel = i; if (typeof sugg !== "undefined") sugg.n = 24;
    if (seek && E.proj.slots[i]) main.currentTime = E.proj.slots[i].start;
    renderTimeline(); renderPanel();
    if (E.pane === "sugg") renderSugg();
  }

  function renderPanel() {
    const box = q("#edPanel");
    const s = E.proj.slots[E.sel];
    if (!s) { box.replaceChildren(mk("div", { class: "meta" }, `${E.proj.slots.length} B-roll spots. Click one on the timeline to review, swap or adjust it. Highlighted transcript = covered by B-roll.`)); return; }
    const sh = s.shot;
    const v = sh?.verdict;
    const left = mk("div", {},
      sh ? mk("img", { src: sh.thumb, style: "width:100%;border-radius:8px" })
        : s.suggested ? mk("div", {}, mk("img", { src: s.suggested.thumb, style: "width:100%;border-radius:8px;opacity:.6" }),
            mk("div", { class: "nomatch" }, `No confident match (best guess scored ${s.suggested.score.toFixed(2)}, ${s.suggested.file}). Left empty so a wrong clip is not forced in.`),
            mk("div", { class: "acts" }, mk("button", { class: "ghost", onclick: () => swap(s.suggested) }, "Use this guess anyway")))
        : mk("div", { class: "nomatch" }, "No clip: pick one below, search Pixabay with another query, or delete this spot."),
      sh ? mk("div", { class: "meta" }, `${sh.file} · ${sh.source}${sh.licence ? " · " + sh.licence.label : ""}`) : "",
      v ? mk("div", { class: "vhead", style: "margin-top:6px" }, mk("span", { class: "pill st-" + v.status }, v.status), sh.label ? mk("span", { class: "labelpill" }, sh.label) : "") : "",
      sh?.why ? mk("ul", { class: "why" }, sh.why.map((w) => mk("li", {}, w))) : "");
    const qin = mk("input", { value: s.query || s.text });
    const right = mk("div", {},
      mk("div", {}, mk("b", {}, `${tc(s.start)} – ${tc(s.end)}`), mk("span", { class: "meta" }, `  ${s.reason || ""}${s.anchor ? `  Cut starts on “${s.anchor}”.` : ""}`)),
      mk("div", { class: "meta", style: "margin:4px 0" }, `“${s.text}”`),
      s.judge ? mk("div", { class: "meta", style: "margin:4px 0" },
        mk("span", { class: "engine " + (s.judge.good ? "on" : "warn") }, s.judge.good ? `Gemini checked the pictures: ${s.judge.good} of ${s.judge.of} fit` : "Gemini: none of these fit"),
        s.judge.reason ? ` ${s.judge.reason}` : "") : "",
      s.repaired ? mk("div", { class: "meta", style: "margin:4px 0" }, "The first search found nothing that fit, so Gemini rewrote it and searched again.") : "",
      s.low_confidence ? mk("div", { class: "nomatch", style: "margin:6px 0" }, "Low confidence: nothing found clearly fits this line, so this is the closest clip. Every video gets at least one B-roll, but check this one or swap it from the Suggested tab.") : "",
      s.inpoint ? mk("div", { class: "meta", style: "margin:4px 0" },
        s.inpoint.fits ? `Clip starts ${s.inpoint.at.toFixed(1)} s in: the best of ${s.inpoint.windows} moments for this line.`
          : `No moment of this clip clearly shows the line (${s.inpoint.windows} checked). Consider swapping it.`) : "",
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
      mk("div", { class: "alts" }, (s.alts || []).map((a) => mk("div", { class: "alt", title: `${a.file}: click to swap, or drag onto the timeline`, onclick: () => swap(a), ...dragProps(a) },
        mk("img", { src: a.thumb, alt: "", draggable: "false" }), mk("span", {}, a.score.toFixed(2)), a.verdict ? mk("i", { class: "dot " + a.verdict.status }) : ""))),
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
    if (!s) return;
    const old = s.shot;
    if (old && old.id === a.id) return;
    s.alts = [old, ...s.alts.filter((x) => x.id !== a.id)].filter(Boolean);
    s.shot = a; s.locked = true; s.suggested = null;
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
    const inside = E.proj.slots.findIndex((x) => t >= x.start && t < x.end);
    if (inside >= 0) { select(inside, false); showPane("sugg"); notify("There is already a spot here: pick a different clip from Suggested, or move the playhead."); return; }
    const next = E.proj.slots.filter((x) => x.start > t).sort((a, b) => a.start - b.start)[0];
    const end = Math.min(E.proj.duration, t + 3, next ? next.start - 0.1 : E.proj.duration);
    if (end - t < 0.8) { notify("Not enough room before the next spot. Move the playhead, or shorten that spot first.", true); return; }
    const seg = (E.proj.segments || []).find((s) => s.start <= t && t < s.end);
    const slot = { start: +t.toFixed(2), end: +end.toFixed(2), text: seg ? seg.text : "", query: seg ? seg.text : "", reason: "added by you" };
    E.proj.slots.forEach((x) => { if (x.shot) x.locked = true; });
    E.proj.slots.push(slot);
    toast("Finding clips for this spot, including fresh ones from Pixabay… this takes a little while.");
    await save(true, true);                  // fills from the library AND fetches new clips for this line
    select(E.proj.slots.findIndex((x) => x.start === slot.start), false);
  });


  // anything that carries a clip can be dragged onto the timeline
  function dragProps(c) {
    return {
      draggable: "true",
      ondragstart: (e) => {
        E.drag = c;
        e.dataTransfer.effectAllowed = "copy";
        e.dataTransfer.setData("text/plain", c.title || c.file || "clip");
        e.currentTarget.classList.add("dragging");
        q(".edwrap").classList.add("dropping");
        toast("Drop it on the timeline where the B-roll should start.", false, 3500);
      },
      ondragend: (e) => { E.drag = null; e.currentTarget.classList.remove("dragging"); clearDrop(); },
    };
  }

  // ---------- side panel: Spot / Suggested / Search library ----------
  function showPane(name) {
    E.pane = name;
    document.querySelectorAll("#edTabs button").forEach((b) => {
      const on = b.dataset.pane === name;
      b.classList.toggle("on", on); b.setAttribute("aria-selected", on ? "true" : "false");
    });
    q("#edPanel").hidden = name !== "spot"; q("#edSugg").hidden = name !== "sugg"; q("#edFind").hidden = name !== "find";
    if (name === "sugg") renderSugg();
    if (name === "find") q("#edFindQ").focus();
  }
  document.querySelectorAll("#edTabs button").forEach((b) => b.addEventListener("click", () => showPane(b.dataset.pane)));

  function toast(msg, warn = false, ms = 0) {   // floats at the bottom of the window, always visible
    let box = q("#edToast");
    if (!box) { box = mk("div", { id: "edToast", role: "status", "aria-live": "polite" }); document.body.append(box); }
    const n = mk("div", { class: "toast" + (warn ? " warn" : "") }, msg,
      mk("button", { type: "button", class: "toastx", "aria-label": "Dismiss", onclick: () => n.remove() }, "×"));
    box.append(n);
    while (box.children.length > 3) box.firstChild.remove();
    setTimeout(() => n.remove(), ms || (warn ? 12000 : 7000));
    return n;
  }
  function notify(msg, warn = false) { return toast(msg, warn); }

  // search inside the project's library (or, without one, everything plus this project's fetched clips)
  const scopeFilters = () => E.proj.library ? { library: E.proj.library } : (E.proj.live_library ? { also_lib: E.proj.live_library } : null);
  async function searchOne(query, k) {
    const res = await j("/api/search", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, k: Math.min(60, k), diversity: 0.3, filters: scopeFilters() }) });
    return (res.clusters || []).flatMap((c) => c.shots || []);
  }
  // one query or several (the spot's query, its alternative phrasings, the spoken line): results merged, best score first, no duplicates
  async function searchClips(queries, k = 24) {
    const qs = [...new Set([].concat(queries).map((x) => (x || "").trim()).filter(Boolean))].slice(0, 4);
    const lists = await Promise.all(qs.map((x) => searchOne(x, k).catch(() => [])));
    const best = new Map();
    for (const l of lists) for (const x of l) if (!best.has(x.id) || best.get(x.id).score < x.score) best.set(x.id, x);
    return [...best.values()].sort((m, n) => n.score - m.score).slice(0, k);
  }
  const preview = (c) => { if (typeof openModal === "function") openModal(c); };

  function clipCard(c, o = {}) {
    const lic = c.licence ? c.licence.label : (c.source === "own" ? "Your footage" : "");
    return mk("div", { class: "scard" + (o.current ? " cur" : ""), title: "Drag onto the timeline to add it there", ...dragProps(c) },
      mk("div", { class: "sth", role: "button", tabindex: "0", title: "Preview this clip", "aria-label": `Preview ${c.title || c.file}`,
          onclick: () => preview(c), onkeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); preview(c); } } },
        mk("img", { src: c.thumb, alt: "", loading: "lazy", draggable: "false" }),
        c.score != null ? mk("span", { class: "sc" }, (+c.score).toFixed(2)) : "",
        o.tag ? mk("span", { class: "tagx " + (o.tagCls || "") }, o.tag) : "",
        c.verdict ? mk("i", { class: "dot " + c.verdict.status, title: `truth check: ${c.verdict.status}` }) : ""),
      mk("div", { class: "sb" },
        mk("div", { class: "st", title: c.title || c.file }, c.title || c.file),
        mk("div", { class: "sm" }, [c.source, lic].filter(Boolean).join(" · "))),
      mk("div", { class: "sa" }, (o.actions || []).map((a) =>
        mk("button", { type: "button", class: a.primary ? "primary" : "ghost", disabled: a.disabled ? "" : null, onclick: a.fn }, a.label))));
  }

  const sugg = { n: 24, expanded: new Set() };                       // how many library results to show; "Show more" raises it
  const dragHint = () => mk("div", { class: "hint" }, "Drag any clip onto the timeline to place it exactly there (it snaps to the nearest spoken word).");
  // Suggestions that fit THIS video: the server grounds the queries in the video's topic, we show the list at once, then Gemini
  // looks at the pictures against the line and the topic and we re-order: fits first, "less relevant" tucked away (never deleted).
  async function suggestInto(target, ctx, exclude, actionsFn, live) {
    const post = (check, expand = false) => j(`/api/editor/projects/${E.proj.id}/suggest`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: ctx.text || "", query: ctx.query || "", alt_queries: ctx.alts || [], k: sugg.n, check, expand }) });
    const more = (n) => n >= sugg.n && sugg.n < 60 ? mk("button", { type: "button", class: "ghost smorebtn", onclick: () => { sugg.n += 24; renderSugg(); } }, "Show more") : "";
    const draw = (res, checked, extra = "") => {
      const clips = (res.clips || []).filter((c) => !exclude.has(c.id));
      const fits = clips.filter((c) => c.fit !== false), less = clips.filter((c) => c.fit === false);
      const note = (extra ? extra + " " : "") + (checked
        ? (res.judged ? `Gemini looked at these against your video${res.topic ? ` (${res.topic})` : ""}: ${res.good} fit.${res.reason ? " " + res.reason : ""}${res.good < 3 ? " Few clips in this library fit: use “Fetch fresh clips from Pixabay” (select a spot) or “B-roll at playhead”, which also fetches new clips." : ""}`
          : (res.error ? "Gemini could not check these right now, so they are ordered by match score." : ""))
        : `Matching your video${res.topic ? ` (${res.topic})` : ""}. Gemini is checking the pictures…`);
      target.replaceChildren(
        note ? mk("div", { class: "meta snote" }, note) : "",
        fits.length ? mk("div", { class: "sgrid" }, fits.map((c) => clipCard(c, { tag: c.fit === true ? "Fits your video" : "", tagCls: "good", actions: actionsFn(c) })))
          : mk("div", { class: "sempty" }, checked ? "Gemini found nothing in this library that fits this line. Try “Fetch fresh clips from Pixabay” or the Search library tab." : "Nothing relevant in this library for that line."),
        less.length ? mk("details", { class: "lessrel" }, mk("summary", {}, `Less relevant (${less.length}): Gemini thinks these do not fit`),
          mk("div", { class: "sgrid" }, less.map((c) => clipCard(c, { tag: c.why_not || "Probably not", tagCls: "low", actions: actionsFn(c) })))) : "",
        more(clips.length + exclude.size));
    };
    try {
      const fast = await post(false);
      if (!live()) return;
      draw(fast, false);
      const checked = await post(true);
      if (!live()) return;
      draw(checked, true);
      const key = `${E.proj.id}|${ctx.text}`;
      if (checked.judged && checked.good < 6 && E.proj.live_search !== false && !sugg.expanded.has(key)) {
        sugg.expanded.add(key);                       // too few confirmed clips: fetch topic-specific ones, then check again
        target.prepend(mk("div", { class: "meta snote busy" }, `Only ${checked.good} clip${checked.good === 1 ? "" : "s"} in your library fit this line. Finding more on Pixabay for your video… (about half a minute)`));
        const more = await post(true, true);
        if (!live()) return;
        draw(more, true, more.fetched ? `Added ${more.fetched} new clips from Pixabay.` : (more.expand_note || "Pixabay had nothing new for this line."));
      }
    } catch (e) { if (live()) target.replaceChildren(mk("div", { class: "sempty" }, e.message)); }
  }

  async function renderSugg() {
    const box = q("#edSugg");
    const s = E.proj.slots[E.sel];
    const token = (box._tok = (box._tok || 0) + 1);          // ignore results that arrive after the user moved on
    const live = () => box._tok === token && E.pane === "sugg";
    const moreBox = mk("div", { class: "smore" }, mk("div", { class: "sempty" }, "Finding clips that fit your video…"));
    if (s) {
      const goodN = s.judge ? Math.max(0, s.judge.good - (s.shot ? 1 : 0)) : 0;     // the judge put the fitting ones first
      const list = [];
      if (s.shot) list.push([s.shot, { current: true, tag: "On timeline" }]);
      if (s.suggested && (!s.shot || s.suggested.id !== s.shot.id)) list.push([s.suggested, { tag: "Low confidence", tagCls: "low" }]);
      (s.alts || []).forEach((a, i) => { if (!s.shot || a.id !== s.shot.id) list.push([a, i < goodN ? { tag: "Gemini: fits", tagCls: "good" } : {}]); });
      const shown = new Set(list.map(([c]) => c.id));
      const actions = (c, o) => [{ label: o.current ? "In use" : "Use here", primary: !o.current, disabled: o.current, fn: () => swap(c) },
        { label: "Add at playhead", fn: () => addClipAt(c, main.currentTime || 0) }];
      box.replaceChildren(
        mk("div", { class: "shead" }, mk("b", {}, `Suggestions for ${tc(s.start)} – ${tc(s.end)}`), `  “${s.text || s.query || ""}”`,
          mk("div", { class: "acts" },
            mk("button", { type: "button", class: "ghost", onclick: () => refind(s.query || s.text) }, "Fetch fresh clips from Pixabay"),
            mk("button", { type: "button", class: "ghost", onclick: () => findFor(s.query || s.text) }, "Search with other words"),
            mk("button", { type: "button", class: "ghost", onclick: () => { E.sel = -1; renderTimeline(); renderPanel(); renderSugg(); } }, "Suggest for the playhead instead")),
          dragHint()),
        list.length ? mk("div", { class: "slabel" }, `Found for this spot (${list.length})`) : "",
        list.length ? mk("div", { class: "sgrid" }, list.map(([c, o]) => clipCard(c, { ...o, actions: actions(c, o) }))) : "",
        mk("div", { class: "slabel" }, "More from your library"),
        moreBox);
      suggestInto(moreBox, { text: s.text, query: s.query, alts: s.alt_queries }, shown, (c) => actions(c, {}), live);
      return;
    }
    // nothing selected: suggestions for the spoken line under the playhead
    const t = main.currentTime || 0;
    const segs = E.proj.segments || [];
    const exact = segs.find((x) => x.start <= t && t < x.end);
    const seg = exact || segs.slice().sort((m, n) => Math.min(Math.abs(m.start - t), Math.abs(m.end - t)) - Math.min(Math.abs(n.start - t), Math.abs(n.end - t)))[0];
    const empty = E.proj.slots.map((x, i) => [x, i]).filter(([x]) => !x.shot);
    box.replaceChildren(
      mk("div", { class: "shead" }, mk("b", {}, `Suggested for ${tc(t)}`), seg ? `  ${exact ? "" : "(nearest line) "}“${seg.text}”` : "  (no speech found)",
        mk("div", { class: "acts" },
          mk("button", { type: "button", class: "ghost", onclick: renderSugg }, "Refresh for current playhead"),
          ...empty.map(([x, i]) => mk("button", { type: "button", class: "ghost", onclick: () => select(i, true) }, `Empty spot at ${tc(x.start)}`))),
        dragHint()),
      seg ? mk("div", { class: "slabel" }, "From your library") : "",
      seg ? moreBox : mk("div", { class: "sempty" }, "This video has no speech to base suggestions on. Use the Search library tab."));
    if (!seg) return;
    suggestInto(moreBox, { text: seg.text }, new Set(), (c) => [{ label: "Add at playhead", primary: true, fn: () => addClipAt(c, t) }],
      () => live() && E.sel === -1);
  }
  main.addEventListener("pause", () => { if (E.pane === "sugg" && E.sel === -1) renderSugg(); });   // pause = "suggest for here"
  q("#edTranscript").addEventListener("click", () => { if (E.pane === "sugg" && E.sel === -1) setTimeout(renderSugg, 60); });

  function findFor(query) { showPane("find"); q("#edFindQ").value = query || ""; runFind(query || ""); }
  async function runFind(query) {
    const meta = q("#edFindMeta"), res = q("#edFindRes");
    if (!query.trim()) { meta.textContent = "Type what you want to see."; return; }
    meta.textContent = `Searching for “${query}”…`; res.replaceChildren();
    try {
      const list = await searchClips([query], 36);
      const s = E.proj.slots[E.sel];
      meta.textContent = !list.length ? "No relevant clips in this library. Try other words, or “Search Pixabay” on a spot."
        : `${list.length} clips. Drag one onto the timeline, ${s ? `use “Use here” to replace the clip at ${tc(s.start)}, ` : ""}or “Add at playhead” (${tc(main.currentTime || 0)}).`;
      res.replaceChildren(...list.map((c) => clipCard(c, { actions: [
        ...(s ? [{ label: "Use here", primary: true, fn: () => swap(c) }] : []),
        { label: "Add at playhead", primary: !s, fn: () => addClipAt(c, main.currentTime || 0) }] })));
    } catch (e) { meta.textContent = e.message; }
  }
  q("#edFindForm").addEventListener("submit", (e) => { e.preventDefault(); runFind(q("#edFindQ").value); });

  // ---------- drag a clip from Suggested / Search onto the timeline ----------
  const tlEl = q("#edTimeline");
  function dropTime(clientX) {
    const r = tlEl.getBoundingClientRect(), D = E.proj?.duration || 0;
    let t = Math.max(0, Math.min(D, ((clientX - r.left) / r.width) * D));
    let best = null;                              // snap to the nearest spoken word start (cut on the word), within 0.35 s
    for (const sg of E.proj.segments || []) for (const w of sg.words || []) {
      if (Math.abs(w.s - t) <= 0.35 && (!best || Math.abs(w.s - t) < Math.abs(best - t))) best = w.s;
    }
    return { t: best ?? t, snapped: best != null };
  }
  function clearDrop() {
    q("#edDropMark")?.remove();
    document.querySelectorAll(".edslot.dropin").forEach((x) => x.classList.remove("dropin"));
    q(".edwrap")?.classList.remove("dropping");
  }
  tlEl.addEventListener("dragover", (e) => {
    if (!E.drag || !E.proj) return;
    e.preventDefault(); e.dataTransfer.dropEffect = "copy";
    const { t, snapped } = dropTime(e.clientX), D = E.proj.duration || 1;
    const inside = E.proj.slots.findIndex((x) => t >= x.start && t < x.end);
    document.querySelectorAll(".edslot").forEach((el, i) => el.classList.toggle("dropin", i === inside));
    let mark = q("#edDropMark");
    if (inside >= 0) { mark?.remove(); return; }
    const next = E.proj.slots.filter((x) => x.start > t).sort((a, b) => a.start - b.start)[0];
    const end = Math.min(t + 3, D, next ? next.start - 0.1 : D);
    if (!mark) { mark = mk("div", { id: "edDropMark", class: "eddrop" }); tlEl.append(mark); }
    mark.classList.toggle("tight", end - t < 0.8);
    mark.style.left = `${(t / D) * 100}%`; mark.style.width = `${(Math.max(end - t, 0.3) / D) * 100}%`;
    mark.textContent = end - t < 0.8 ? "no room" : `${tc(t)}${snapped ? " · on a word" : ""}`;
  });
  tlEl.addEventListener("dragleave", (e) => { if (!tlEl.contains(e.relatedTarget)) { q("#edDropMark")?.remove(); document.querySelectorAll(".edslot.dropin").forEach((x) => x.classList.remove("dropin")); } });
  tlEl.addEventListener("drop", async (e) => {
    e.preventDefault();
    if (!E.drag) { toast("Drag a clip card (from Suggested, Search library or the Alternatives) onto the timeline.", true); return; }
    const c = E.drag, { t } = dropTime(e.clientX);
    E.drag = null; clearDrop();
    try { await addClipAt(c, t); } catch (err) { toast(`Could not add the clip: ${err.message}`, true); }
  });

  // put a chosen clip on the timeline at time t (replaces the clip if t is inside an existing spot)
  async function addClipAt(c, t) {
    const D = E.proj.duration || 0;
    t = Math.max(0, Math.min(+t || 0, Math.max(0, D - 0.8)));
    const inside = E.proj.slots.findIndex((x) => t >= x.start && t < x.end);
    if (inside >= 0) {
      E.sel = inside;
      await swap(c);
      notify(`Replaced the clip in the spot at ${tc(E.proj.slots[E.sel]?.start ?? t)}.`);
      return;
    }
    const next = E.proj.slots.filter((x) => x.start > t).sort((a, b) => a.start - b.start)[0];
    const end = Math.min(t + 3, D, next ? next.start - 0.1 : D);
    if (end - t < 0.8) { toast(`No room at ${tc(t)}: the next spot starts at ${tc(next ? next.start : D)}. Drop it earlier, or on that spot to replace its clip.`, true); return; }
    const seg = (E.proj.segments || []).find((x) => x.start <= t && t < x.end);
    const slot = { start: +t.toFixed(2), end: +end.toFixed(2), text: seg ? seg.text : "", query: c.title || c.file, alt_queries: [],
      reason: "added by you", shot: c, alts: [], locked: true };
    E.proj.slots.forEach((x) => { if (x.shot) x.locked = true; });
    E.proj.slots.push(slot);
    await save(false);
    const i = E.proj.slots.findIndex((x) => Math.abs(x.start - slot.start) < 0.01);
    if (i >= 0) select(i, false);
    notify(`Added a ${(slot.end - slot.start).toFixed(1)} s spot at ${tc(slot.start)}. Press play to preview it; drag its edges with Start/End.`);
    if (typeof teach === "function" && seg) teach(seg.text, c, []);
  }

  // ---------- export ----------
  const expBtn = q("#edExportBtn"), expList = q("#edExportList");
  function setMenu(open) {
    expList.hidden = !open; expBtn.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) expList.querySelector("button").focus();
  }
  expBtn.addEventListener("click", (e) => { e.stopPropagation(); setMenu(expList.hidden); });
  document.addEventListener("click", (e) => { if (!expList.hidden && !q("#edExport").contains(e.target)) setMenu(false); });
  expList.addEventListener("keydown", (e) => {
    const items = [...expList.querySelectorAll("button")], k = items.indexOf(document.activeElement);
    if (e.key === "Escape") { setMenu(false); expBtn.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(k + 1) % items.length].focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(k - 1 + items.length) % items.length].focus(); }
  });
  expList.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { setMenu(false); exportAs(b.dataset.fmt); }));

  async function exportAs(fmt) {
    const names = { zip: "the export package", xml: "the Premiere / Resolve timeline", edl: "the EDL", srt: "captions", credits: "the licence sheet" };
    expBtn.disabled = true;
    const busy = notify(`Preparing ${names[fmt]}…${fmt === "srt" ? "" : " B-roll clips are downloaded first if they are not on this computer yet."}`);
    try {
      const r = await fetch(`/api/editor/projects/${E.proj.id}/export?format=${fmt}`);
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.detail || r.statusText); }
      const blob = await r.blob();
      const name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || `epoch_export.${fmt}`;
      const url = URL.createObjectURL(blob);
      const a = mk("a", { href: url, download: name });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      const sk = +(r.headers.get("X-Epoch-Skipped") || 0);
      busy.remove();
      notify(`Downloaded ${name} (${blob.size > 1048576 ? (blob.size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(blob.size / 1024)) + " KB"}).`
        + (sk ? ` ${sk} clip(s) could not be downloaded and were left out (listed in the licence sheet).` : "")
        + (fmt === "zip" && !E.proj.rendered ? " Render the video first if you also want the MP4 inside." : ""), !!sk);
    } catch (e) { busy.remove(); notify(`Export failed: ${e.message}`, true); }
    finally { expBtn.disabled = false; }
  }

  // ---------- instant preview: overlay the B-roll inside each spot ----------
  // The key includes the clip's file id, so when a clip finishes downloading while the playhead is inside its spot,
  // the preview switches from the still image to the moving clip (before, the spot stayed blank until you seeked).
  let curKey = null;
  function tick() {
    if (!E.proj || q("#edWork").hidden) return;
    const t = main.currentTime, D = E.proj.duration || 1;
    const head = q("#edHead"); if (head) head.style.left = `${(t / D) * 100}%`;
    const s = E.proj.slots.find((x) => x.shot && t >= x.start && t < x.end);
    const key = s ? `${s.start}|${s.shot.id}|${s.shot.file_id ?? "still"}` : null;
    if (key !== curKey) {
      curKey = key;
      const badge = q("#edBadge");
      if (!s) {
        over.pause(); over.style.display = "none"; badge.style.display = "none";
      } else if (s.shot.file_id != null) {
        const src = `/media/video/${s.shot.file_id}`;
        if (!over.src.endsWith(src)) { over.removeAttribute("poster"); over.src = src; }
        over.currentTime = (s.shot.trim_in ?? s.shot.t_start ?? 0) + (t - s.start);
        over.style.display = "block";
        badge.style.display = "block"; badge.textContent = `B-roll · ${s.shot.title || s.shot.file}`;
        if (!main.paused) over.play().catch(() => {});
      } else {                                             // not on this computer yet: show its picture in place meanwhile
        over.pause(); over.removeAttribute("src"); over.load(); over.poster = s.shot.thumb;
        over.style.display = "block";
        badge.style.display = "block";
        badge.textContent = `B-roll · ${s.shot.title || s.shot.file} · ${hydrateFailed.has(s.shot.id) ? "still image (clip could not be downloaded)" : "loading clip…"}`;
        hydrateOne(s.shot);
      }
    }
    document.querySelectorAll("#edTranscript span").forEach((sp) => sp.classList.toggle("now", t >= +sp.dataset.s && t < +sp.dataset.e));
  }
  main.addEventListener("timeupdate", tick);
  main.addEventListener("seeked", () => { curKey = null; tick(); });
  main.addEventListener("play", () => { if (curKey && over.getAttribute("src")) over.play().catch(() => {}); });
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
          clearInterval(t); q("#edRender").disabled = false; E.proj.rendered = true;
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
  q("#tabs [data-tab=editor]").addEventListener("click", loadList);        // the list reflects projects made since the page loaded
  const m = location.hash.match(/^#editor\/([\w-]+)/);                     // a link straight to a project
  if (m) open(m[1]).catch(() => {});
})();
