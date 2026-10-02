"use strict";
const $ = (s, r = document) => r.querySelector(s);
const SIZE_NAMES = { close: "close-up" };
const SRC_MULTI = new Set(["size", "motion", "source"]);

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return e;
}
const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || j.detail || r.statusText);
  return j;
}

// ---------- filters ----------
const filters = {};
document.querySelectorAll(".chip").forEach((b) =>
  b.addEventListener("click", () => {
    const f = b.dataset.f, v = b.dataset.v;
    b.classList.toggle("on");
    const on = [...document.querySelectorAll(`.chip[data-f="${f}"].on`)].map((x) => x.dataset.v);
    if (on.length) filters[f] = f === "orientation" ? on[on.length - 1] : on; else delete filters[f];
    if (f === "orientation") document.querySelectorAll(`.chip[data-f="orientation"]`).forEach((x) => x.classList.toggle("on", x.dataset.v === filters[f]));
    if ($("#q").value.trim()) runSearch();
  }));

const div = $("#div");
div.addEventListener("input", () => ($("#divOut").textContent = (+div.value).toFixed(2)));
div.addEventListener("change", () => $("#q").value.trim() && runSearch());

// ---------- search ----------
$("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });

async function runSearch() {
  const query = $("#q").value.trim();
  if (!query) return;
  $("#empty").style.display = "none";
  try {
    const t0 = performance.now();
    const res = await api("/api/search", { query, diversity: +div.value, filters, k: 24 });
    render(res, performance.now() - t0, `Results for "${query}"`);
  } catch (e) { $("#results").replaceChildren(el("div", { class: "err" }, e.message)); }
}

function render(res, ms, title) {
  const results = $("#results");
  results.replaceChildren();
  const total = res.clusters.reduce((n, c) => n + c.shots.length, 0);
  const meta = $("#meta");
  meta.replaceChildren(`${total} shots in ${res.clusters.length} variations · server ${res.took_ms ?? "cache"} ms · round trip ${ms.toFixed(0)} ms${res.cached ? " · cached" : ""}`);
  (res.missing || []).forEach((m) => meta.append(el("span", { class: "warn" }, m)));
  if (!total) { results.append(el("div", { class: "empty" }, "No relevant shots found. Try other words or remove filters.")); return; }
  res.clusters.forEach((c) => {
    results.append(el("div", { class: "cluster" },
      el("h3", {}, c.label, el("span", { class: "n" }, `${c.shots.length} shot${c.shots.length > 1 ? "s" : ""}`)),
      el("div", { class: "row" }, c.shots.map((s, i) => card(s, i === 0)))));
  });
}

function card(s, best) {
  const tags = [SIZE_NAMES[s.size] || s.size, s.motion !== "unknown" ? s.motion : null, s.weather].filter(Boolean).map((t) => el("span", { class: "tag" }, t));
  if (s.date) tags.push(el("span", { class: "tag " + (s.date_src === "recorded" || s.date_src === "meta" ? "date" : "dateguess"), title: "date source: " + s.date_src }, s.date.slice(0, 4)));
  return el("div", { class: "card" + (best ? " best" : ""), onclick: () => openModal(s) },
    el("div", { class: "th" },
      el("img", { src: s.thumb, loading: "lazy", alt: "" }),
      el("span", { class: "sc" }, s.score.toFixed(2)),
      s.source !== "own" ? el("span", { class: "src" }, s.source) : "",
      el("span", { class: "tc" }, `${fmt(s.t_start)}–${fmt(s.t_end)}`)),
    el("div", { class: "cb" }, el("div", { class: "fn", title: s.file }, s.file), el("div", { class: "tags" }, tags)));
}

// ---------- preview modal ----------
let current = null;
const player = $("#player");
function openModal(s) {
  current = s;
  $("#modal").hidden = false;
  const thumb = $("#playerThumb");
  if (s.file_id != null) {
    thumb.style.display = "none"; player.style.display = "block";
    player.src = `/media/video/${s.file_id}#t=${s.t_start}`;
    player.currentTime = s.t_start;
    player.ontimeupdate = () => { if (player.currentTime >= s.t_end) player.currentTime = s.t_start; };
    player.play().catch(() => {});
  } else {
    player.pause(); player.style.display = "none"; thumb.style.display = "block"; thumb.src = s.thumb;
  }
  const load = $("#loadBtn");
  load.hidden = !(s.file_id == null && s.stock_id != null);
  load.textContent = "Load video"; load.disabled = false;
  load.onclick = async () => {
    load.disabled = true; load.textContent = "Downloading…";
    try {
      const r = await api(`/api/shots/${s.id}/hydrate`, {});
      s.file_id = r.file_id; load.hidden = true; openModal(s);
    } catch (e) { load.textContent = "Can't load: " + e.message.slice(0, 60); }
  };
  loadProvenance(s);
  const link = $("#srcLink");
  link.hidden = !s.page_url; if (s.page_url) link.href = s.page_url;
  $("#info").replaceChildren(el("b", {}, s.file), ` · ${fmt(s.t_start)}–${fmt(s.t_end)} · ${SIZE_NAMES[s.size] || s.size} · ${s.motion} · ${s.orientation} · relevance ${s.score.toFixed(3)}`);
}
function closeModal() { $("#modal").hidden = true; player.pause(); player.removeAttribute("src"); player.load(); }
$("#modalClose").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => e.target.id === "modal" && closeModal());
document.addEventListener("keydown", (e) => e.key === "Escape" && closeModal());

$("#simBtn").addEventListener("click", async () => {
  if (!current) return;
  const base = current; closeModal();
  const res = await api(`/api/similar/${base.id}?k=18`);
  $("#empty").style.display = "none";
  render({ clusters: [{ label: `Similar to ${base.file} ${fmt(base.t_start)}`, shots: res.shots }], missing: [] }, 0, "Similar");
});

// ---------- status ----------
async function pollStatus() {
  try {
    const s = await api("/api/status");
    const q = s.queue.index || {}; const pending = (q.pending || 0) + (q.running || 0);
    const files = Object.values(s.files).reduce((a, b) => a + b, 0);
    $("#status").replaceChildren(
      el("span", { class: "dot" + (pending ? " busy" : "") }),
      el("b", {}, s.shots), ` shots · ${files} files`,
      Object.keys(s.sources || {}).length > 1 ? " · " + Object.entries(s.sources).map(([k, v]) => `${k} ${v}`).join(" · ") : "",
      s.ingest && s.ingest.running ? ` · importing ${s.ingest.added}/${s.ingest.target}` : "",
      pending ? ` · indexing ${pending} left${s.indexer.current ? " (" + s.indexer.current + ")" : ""}` : "");
  } catch { $("#status").textContent = "server unreachable"; }
}
pollStatus(); setInterval(pollStatus, 2000);

// ---------- tabs ----------
document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => {
  if (b.disabled) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + b.dataset.tab));
}));

// ---------- script → plan ----------
const SAMPLE = `Every morning, the city wakes up in a rush.
Traffic fills the roads as people head to work.
Inside offices, teams get busy on their laptops.
At lunch, street food stalls come alive.
And when the rain arrives, the whole city slows down.`;
$("#sampleBtn").addEventListener("click", () => ($("#script").value = SAMPLE));
let PLAN = null;

$("#planBtn").addEventListener("click", async () => {
  const script = $("#script").value.trim();
  if (!script) return;
  $("#planBtn").disabled = true;
  try {
    const mode = $("#cutMode").value;
    PLAN = await api("/api/plan", { script, use_truth: $("#truthOn").checked, use_memory: $("#memOn").checked, use_cuts: mode !== "greedy", cut_weight: mode === "smooth" ? 0.8 : null });
    renderPlan();
    renderSeqSummary();
    $("#playSeqBtn").disabled = !PLAN.beats.some((x) => x.chosen.length);
    $("#planMeta").textContent = `${PLAN.beats.length} beats · planned in ${PLAN.took_ms} ms`;
    document.querySelectorAll(".export").forEach((b) => (b.disabled = !PLAN.beats.some((x) => x.chosen.length)));
  } catch (e) { $("#plan").replaceChildren(el("div", { class: "err" }, e.message)); }
  $("#planBtn").disabled = false;
});

const ICON = { ok: "", unverified: "", warn: "", bad: "" };      // status is drawn with a coloured marker in CSS
const STATUS_TEXT = { ok: "Verified", unverified: "Unverified", warn: "Check label", bad: "Contradicts" };

const CUT_CHIPS = {
  "progress": ["good", "size progression"], "jump": ["bad", "jump cut"], "flip": ["bad", "direction flip"],
  "exposure": ["bad", "brightness jump"], "colour": ["bad", "colour shift"], "same-size": ["", "same shot size"],
};

function cutChips(s) {
  if (!s.cut) return "";
  const chips = s.cut.flags.filter((f) => CUT_CHIPS[f]).map((f) => el("span", { class: "cc " + CUT_CHIPS[f][0] }, CUT_CHIPS[f][1]));
  return el("div", { class: "cutchips", title: "How this clip cuts from the previous one" },
    chips.length ? chips : el("span", { class: "cc good" }, "clean cut"));
}

function renderSeqSummary() {
  const box = $("#seqSummary");
  box.replaceChildren();
  const q = PLAN.sequence;
  if (!q) return;
  const mine = q.mode === "cuts" ? q.cuts : q.greedy, other = q.mode === "cuts" ? q.greedy : q.cuts;
  const metric = (label, key, lowerIsBetter) => {
    const a = mine[key], b = other[key];
    const good = q.mode === "cuts" && (lowerIsBetter ? a < b : a > b);
    return el("span", { class: "m" + (good ? " good" : "") }, el("span", { class: "t" }, label), el("b", {}, a),
      q.mode === "cuts" ? el("span", { class: "vs" }, `(relevance-only: ${b})`) : "");
  };
  box.append(el("div", { class: "seqsum" },
    el("b", {}, q.mode === "cuts" ? "Cut-aware sequence" : "Relevance-only sequence"),
    metric("problems", "problems", true), metric("same-size repeats", "same_size", true),
    metric("size progressions", "progress", false),
    el("span", { class: "m" }, el("span", { class: "t" }, "relevance"), el("b", {}, mine.mean_rel.toFixed(3)),
      q.mode === "cuts" ? el("span", { class: "vs" }, `(relevance-only: ${other.mean_rel.toFixed(3)})`) : "")));
}

function verdictBlock(s) {
  const v = s.verdict;
  if (!v) return cutChips(s);
  const rows = Object.entries(v.checks || {}).map(([k, c]) =>
    el("li", {}, el("span", { class: "ic " + c.status }, ICON[c.status]), el("span", {}, c.evidence)));
  return el("div", { class: "vblock" },
    cutChips(s),
    el("div", { class: "vhead" },
      el("span", { class: "pill st-" + v.status }, STATUS_TEXT[v.status]),
      s.label ? el("span", { class: "labelpill", title: "Added automatically to the export as a caption" }, s.label) : ""),
    rows.length ? el("ul", { class: "checks" }, rows) : "");
}

function claimChips(b) {
  const c = b.claims;
  if (!c) return "";
  const chips = [];
  if (c.places.length) {
    chips.push(el("span", { class: "claim" + (c.place_inherited ? " inh" : ""), title: c.place_inherited ? "carried over from an earlier line" : "" },
      el("b", {}, "Place"), c.places[0] + (c.place_inherited ? " (carried over)" : "")));
  }
  if (c.time) chips.push(el("span", { class: "claim" }, el("b", {}, "Time"), c.time));
  if (c.weather) chips.push(el("span", { class: "claim" }, el("b", {}, "Weather"), c.weather));
  return chips.length ? el("div", { class: "claims" }, chips) : "";
}

function renderPlan() {
  const root = $("#plan");
  root.replaceChildren();
  PLAN.beats.forEach((b, bi) => {
    const none = b.n_rejected
      ? `No truthful shot found — ${b.n_rejected} candidate(s) contradict the narration (see below).`
      : "No relevant shot found for this line.";
    const chosen = el("div", { class: "chosen" }, b.chosen.length
      ? b.chosen.map((s) => el("div", { class: "chosen-item" }, card(s, false), verdictBlock(s), whyBlock(s)))
      : el("div", { class: "nomatch" }, none));
    const alts = el("div", { class: "alts" }, b.alts.map((s) =>
      el("div", { class: "alt", title: `${s.file} · score ${s.score}${s.verdict ? " · " + STATUS_TEXT[s.verdict.status] : ""}`, onclick: () => swap(bi, s.id) },
        el("img", { src: s.thumb, loading: "lazy", alt: "" }), el("span", {}, s.score.toFixed(2)),
        s.verdict ? el("i", { class: "dot " + s.verdict.status }) : "")));
    const rej = b.n_rejected ? el("details", { class: "rejected" },
      el("summary", {}, `${b.n_rejected} shot${b.n_rejected > 1 ? "s" : ""} rejected — contradict the narration`),
      b.rejected.map((s) => el("div", { class: "rej-item" },
        el("img", { src: s.thumb, alt: "" }),
        el("div", { class: "why" }, el("b", {}, s.file), el("br"), s.verdict.evidence[0]),
        el("button", { class: "ghost", title: "Use it anyway; you take responsibility for the mismatch", onclick: () => swapRejected(bi, s.id) }, "Use anyway")))) : "";
    root.append(el("div", { class: "beat" },
      el("div", { class: "bt" }, el("div", { class: "no" }, `Beat ${bi + 1} · ${b.dur.toFixed(1)} s`), el("div", { class: "txt" }, b.text), claimChips(b)),
      el("div", {}, chosen, b.alts.length ? el("div", { class: "alts-label" }, "Alternatives: click to swap") : "", alts, rej)));
  });
}

function swapRejected(bi, shotId) {
  const b = PLAN.beats[bi];
  const k = b.rejected.findIndex((s) => s.id === shotId);
  if (k < 0) return;
  const picked = b.rejected.splice(k, 1)[0];
  b.n_rejected -= 1;
  if (b.chosen.length) b.alts.unshift(b.chosen[0]);
  b.chosen[0] = picked;
  renderPlan();
}

function swap(bi, shotId) {
  const b = PLAN.beats[bi];
  const k = b.alts.findIndex((s) => s.id === shotId);
  if (k < 0) return;
  const picked = b.alts.splice(k, 1)[0];
  const dropped = b.chosen[0];
  if (b.chosen.length) b.alts.unshift(b.chosen[0]);
  b.chosen[0] = picked;
  renderPlan();
  teach(b.text, picked, dropped ? [dropped.id] : []);    // a swap is a lesson: you preferred this one
}

document.querySelectorAll(".export").forEach((btn) => btn.addEventListener("click", async () => {
  if (!PLAN) return;
  const r = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ beats: PLAN.beats, format: btn.dataset.fmt }) });
  if (!r.ok) { alert("Export failed: " + (await r.text())); return; }
  const skipped = +(r.headers.get("X-Epoch-Skipped") || 0);
  if (skipped) {
    let why = "";
    try { why = JSON.parse(r.headers.get("X-Epoch-Skipped-Detail")).map((k) => `Beat ${k.beat + 1}: ${k.file} — ${k.reason}`).join("\n"); } catch {}
    alert(`${skipped} clip(s) could not be added to the export:\n\n${why}\n\nSwap them for another shot and export again.`);
  }
  if (btn.dataset.fmt === "xml") PLAN.beats.forEach((b) => b.chosen.forEach((s) => teach(b.text, s, [])));   // exporting = accepting
  const blob = await r.blob();
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "export.txt";
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
}));

async function loadProvenance(s) {
  const box = $("#prov");
  box.replaceChildren();
  try {
    const p = await api(`/api/shots/${s.id}/provenance`);
    const rows = [];
    rows.push(el("div", { class: "row2" }, el("b", {}, "Source: "), p.source,
      p.date ? [" · ", el("b", {}, "date: "), p.date.slice(0, 10), ` (${p.date_source})`] : " · date unknown"));
    rows.push(el("div", { class: "row2" }, el("b", {}, "Place: "),
      p.place_evidence.length ? p.place_evidence.map((e) => `${e.name} (${e.text})`).join(" · ") : "no evidence in the footage"));
    if (p.ocr_text) rows.push(el("div", { class: "row2" }, el("b", {}, "Text on screen: "), p.ocr_text));
    if (p.weather) rows.push(el("div", { class: "row2" }, el("b", {}, "Looks: "), p.weather + (p.weather_conf ? " (" + p.weather_conf.toFixed(2) + ")" : "")));
    box.append(el("div", { class: "prov" }, rows));
  } catch (e) { /* provenance is optional */ }
}

// ---------- sequence preview: play the chosen clips back to back ----------
let seqToken = 0;
async function playSequence() {
  if (!PLAN) return;
  const items = PLAN.beats.flatMap((b) => b.chosen.map((s) => ({ s, per: b.dur / b.chosen.length, text: b.text })));
  if (!items.length) return;
  const token = ++seqToken;
  const vid = $("#seqVideo"), img = $("#seqImg");
  $("#seqModal").hidden = false;
  // stock clips are only thumbnails until downloaded: fetch them now (15 s cap each, still image if it fails)
  const need = items.filter((x) => x.s.file_id == null && x.s.stock_id != null);
  if (need.length) {
    let done = 0;
    $("#seqCount").textContent = "Preparing clips…";
    $("#seqImg").style.display = "block"; vid.style.display = "none"; img.src = need[0].s.thumb;
    await Promise.all(need.map(async (x) => {
      try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 15000);
        const r = await fetch(`/api/shots/${x.s.id}/hydrate`, { method: "POST", signal: ctl.signal });
        clearTimeout(timer);
        if (r.ok) x.s.file_id = (await r.json()).file_id;
      } catch { /* keep the still image */ }
      $("#seqCap").textContent = `${++done}/${need.length} clips downloaded`;
    }));
    if (token !== seqToken) return;
  }
  const total = items.reduce((a, x) => a + x.per, 0);
  let elapsed = 0;
  for (let i = 0; i < items.length && token === seqToken; i++) {
    const { s, per, text } = items[i];
    $("#seqCount").textContent = `Clip ${i + 1}/${items.length}`;
    $("#seqCap").replaceChildren(text + (s.label ? "  [" + s.label + "]" : ""));
    let played = false;
    if (s.file_id != null) {
      vid.style.display = "block"; img.style.display = "none";
      vid.src = `/media/video/${s.file_id}`;
      try {
        await new Promise((res, rej) => { vid.onloadedmetadata = res; vid.onerror = rej; setTimeout(rej, 4000); });
        vid.currentTime = s.trim_in != null ? s.trim_in : s.t_start;
        for (let attempt = 0; attempt < 3 && !played; attempt++) {     // play() can be aborted transiently (e.g. hidden tab)
          try { await vid.play(); played = true; } catch { await new Promise((r) => setTimeout(r, 300)); }
        }
      } catch { played = false; }
    }
    if (!played) { vid.pause(); vid.style.display = "none"; img.style.display = "block"; img.src = s.thumb; }
    const t0 = performance.now();
    while (token === seqToken && performance.now() - t0 < per * 1000) {
      $("#seqFill").style.width = `${((elapsed + (performance.now() - t0) / 1000) / total) * 100}%`;
      await new Promise((r) => setTimeout(r, 100));
    }
    elapsed += per;
  }
  if (token === seqToken) { vid.pause(); $("#seqModal").hidden = true; }
}
function stopSequence() { seqToken++; $("#seqVideo").pause(); $("#seqModal").hidden = true; }
$("#playSeqBtn").addEventListener("click", playSequence);
$("#seqClose").addEventListener("click", stopSequence);
$("#seqModal").addEventListener("click", (e) => e.target.id === "seqModal" && stopSequence());

// ---------- YOURS: edit memory ----------
function whyBlock(s) {
  if (!s.why || !s.why.length) return "";
  return el("ul", { class: "why", title: "Why this clip was chosen" }, s.why.map((w) => el("li", {}, w)));
}

function teach(text, shot, rejectedIds) {
  fetch("/api/feedback", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, chosen_id: shot.id, rejected_ids: rejectedIds }) }).then(loadMemory).catch(() => {});
}

async function loadMemory() {
  try {
    const m = await api("/api/memory/status");
    const box = $("#memStats");
    box.replaceChildren(
      el("span", { class: "big" }, m.n), `lessons learned from ${m.projects.length} project${m.projects.length === 1 ? "" : "s"}`,
      m.negatives ? ` · ${m.negatives} shots you passed on` : "",
      m.n ? el("div", { class: "mix" }, el("span", { class: "meta" }, "Your house style:"),
        Object.entries(m.size_mix).map(([k, v]) => el("span", { class: "mempill" }, `${k === "close" ? "close-up" : k} ${Math.round(v * 100)}%`)),
        m.active ? "" : el("span", { class: "meta" }, `(needs ${5 - m.n} more lessons before it shapes results)`))
        : el("div", { class: "meta" }, "No history yet. Import a past timeline below, or just swap and export in the Script tab."));
  } catch { /* ignore */ }
}

$("#memFile").addEventListener("change", () => {
  const f = $("#memFile").files[0];
  if (f && !$("#memProject").value) $("#memProject").value = f.name.replace(/\.[^.]+$/, "");
});
$("#memImportBtn").addEventListener("click", async () => {
  const f = $("#memFile").files[0], script = $("#memScript").value.trim(), msg = $("#memMsg");
  if (!f || !script) { msg.textContent = "Choose a timeline file and paste its script."; return; }
  msg.textContent = "Learning…";
  try {
    const r = await api("/api/memory/import", { xml: await f.text(), script, project: $("#memProject").value || f.name });
    msg.textContent = `Learned ${r.pairs} lesson${r.pairs === 1 ? "" : "s"} (${r.unmatched} clip${r.unmatched === 1 ? "" : "s"} could not be matched to your library).`;
    loadMemory();
  } catch (e) { msg.textContent = e.message; }
});
$("#memClear").addEventListener("click", async () => {
  if (!confirm("Forget everything learned from your edits?")) return;
  await fetch("/api/memory", { method: "DELETE" });
  $("#memMsg").textContent = "Memory cleared."; loadMemory();
});
loadMemory();
