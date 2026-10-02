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
  (res.missing || []).forEach((m) => meta.append(el("span", { class: "warn" }, "⚠ " + m)));
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
    PLAN = await api("/api/plan", { script });
    renderPlan();
    $("#planMeta").textContent = `${PLAN.beats.length} beats · planned in ${PLAN.took_ms} ms`;
    document.querySelectorAll(".export").forEach((b) => (b.disabled = !PLAN.beats.some((x) => x.chosen.length)));
  } catch (e) { $("#plan").replaceChildren(el("div", { class: "err" }, e.message)); }
  $("#planBtn").disabled = false;
});

function renderPlan() {
  const root = $("#plan");
  root.replaceChildren();
  PLAN.beats.forEach((b, bi) => {
    const chosen = el("div", { class: "chosen" }, b.chosen.length
      ? b.chosen.map((s) => card(s, false))
      : el("div", { class: "nomatch" }, "No relevant shot found for this line."));
    const alts = el("div", { class: "alts" }, b.alts.map((s) =>
      el("div", { class: "alt", title: `${s.file} · score ${s.score}`, onclick: () => swap(bi, s.id) },
        el("img", { src: s.thumb, loading: "lazy", alt: "" }), el("span", {}, s.score.toFixed(2)))));
    root.append(el("div", { class: "beat" },
      el("div", { class: "bt" }, el("div", { class: "no" }, `Beat ${bi + 1} · ${b.dur.toFixed(1)} s`), el("div", { class: "txt" }, b.text)),
      el("div", {}, chosen, b.alts.length ? el("div", { class: "alts-label" }, "Alternatives — click to swap") : "", alts)));
  });
}

function swap(bi, shotId) {
  const b = PLAN.beats[bi];
  const k = b.alts.findIndex((s) => s.id === shotId);
  if (k < 0) return;
  const picked = b.alts.splice(k, 1)[0];
  if (b.chosen.length) b.alts.unshift(b.chosen[0]);
  b.chosen[0] = picked;
  renderPlan();
}

document.querySelectorAll(".export").forEach((btn) => btn.addEventListener("click", async () => {
  if (!PLAN) return;
  const r = await fetch("/api/export", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ beats: PLAN.beats, format: btn.dataset.fmt }) });
  if (!r.ok) { alert("Export failed: " + (await r.text())); return; }
  const skipped = +(r.headers.get("X-Epoch-Skipped") || 0);
  if (skipped) {
    let why = "";
    try { why = JSON.parse(r.headers.get("X-Epoch-Skipped-Detail")).map((k) => `Beat ${k.beat + 1}: ${k.file} — ${k.reason}`).join("
"); } catch {}
    alert(`${skipped} clip(s) could not be added to the export:

${why}

Swap them for another shot and export again.`);
  }
  const blob = await r.blob();
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/)?.[1] || "export.txt";
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a); a.click(); a.remove();
}));
