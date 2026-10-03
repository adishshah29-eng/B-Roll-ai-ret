"""Editor jobs.

analyse : upload → normalise → split by picture (scene cuts + filmstrip) and by audio (Whisper) → units →
          LLM decides spots + queries → Pixabay live sourcing → planner fills every spot → project ready
render  : ffmpeg overlay of the chosen clips on the A-roll (original audio kept)
"""
import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from .. import db, planner
from ..sources import hydrate
from . import analyse, ffmpeg, inpoint, judge, live, llm, slots as rules, split, store


MIN_CONF = 0.31      # below this relevance a spot is left empty (best guess kept as `suggested`): precision over recall


def _fill_once(searcher, slot_list: list, use_truth=True, use_cuts=True, use_memory=True, library=None, also_lib=None) -> list:
    if not slot_list:
        return []
    beats = [planner.Beat(i, s.get("text") or s.get("query") or "", round(s["end"] - s["start"], 2), s.get("query") or None)
             for i, s in enumerate(slot_list)]
    p = planner.plan(searcher, "", beats=beats, use_truth=use_truth, use_cuts=use_cuts, use_memory=use_memory,
                     today=date.today().isoformat(), library=library, also_lib=also_lib, style_prior=False)
    out = []
    for s, b in zip(slot_list, p["beats"]):
        out.append({**{k: s[k] for k in ("start", "end", "text", "query", "alt_queries", "reason", "anchor") if k in s},
                    "shot": b["chosen"][0] if b["chosen"] else None, "alts": b["alts"][:12],
                    "rejected": b["rejected"][:3], "n_rejected": b["n_rejected"], "claims": b.get("claims")})
    for o in out:
        sh = o["shot"]
        if sh and sh["score"] < MIN_CONF:
            o["suggested"], o["shot"] = sh, None
    return out


RRF_K = 60


def _fuse(results: list) -> list:
    """Reciprocal-rank fusion of several candidate lists (one per search phrasing) into one pool of shots, best first."""
    score, shots = {}, {}
    for res in results:
        ranked = [x for x in [res.get("shot") or res.get("suggested"), *(res.get("alts") or [])] if x]
        for rank, sh in enumerate(ranked):
            k = ("s", sh["stock_id"]) if sh.get("stock_id") is not None else ("f", sh.get("file_id"), sh["id"] if sh.get("file_id") is None else 0)
            score[k] = score.get(k, 0.0) + 1.0 / (RRF_K + rank)     # one entry per video: a clip must not fill the pool twice
            shots.setdefault(k, sh)
    return [shots[k] for k in sorted(score, key=lambda k: -score[k])]


def _fill(searcher, slot_list: list, **flags) -> list:
    """Fill every spot from the library (which now includes the fresh Pixabay clips). Each spot is searched with its main query
    AND its alternative phrasings; the pick comes from the main query (alternatives step in when it finds nothing truthful), and
    the candidate pool shown to the reviewer / editor is the rank-fused union of all phrasings."""
    out = _fill_once(searcher, slot_list, **flags)
    runs = [[r] for r in out]
    for k in (0, 1):
        idx = [i for i, s in enumerate(slot_list) if len(s.get("alt_queries") or []) > k]
        if not idx:
            continue
        retry = _fill_once(searcher, [{**slot_list[i], "query": slot_list[i]["alt_queries"][k]} for i in idx], **flags)
        for i, r in zip(idx, retry):
            runs[i].append(r)
            if not out[i]["shot"]:
                if r["shot"]:
                    out[i] = {**r, "query": slot_list[i]["query"], "used_query": slot_list[i]["alt_queries"][k]}
                    runs[i][0] = out[i]
                elif r.get("suggested") and (not out[i].get("suggested") or r["suggested"]["score"] > out[i]["suggested"]["score"]):
                    out[i]["suggested"] = r["suggested"]
    for i, o in enumerate(out):
        cur = o.get("shot") or o.get("suggested")
        o["alts"] = [sh for sh in _fuse(runs[i]) if not cur or sh["id"] != cur["id"]][:12]
    return out


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:                      # a helper step must never sink the project
        print(f"{getattr(fn, '__name__', 'step')} failed: {type(e).__name__}")
        return None


def finish(searcher, placed: list, lib, also, live_on: bool) -> dict:
    """Gemini's second look at the picks: (1) judge the pictures (it also writes new searches for spots where nothing fits),
    (2) search again for those spots, (3) choose where in each clip the cutaway starts. Step 3 runs for the spots that are already
    fine WHILE step 2 searches and downloads, so the two overlap. Each step is skipped, never fatal, without Gemini."""
    out = {"judge": None, "repair": None, "inpoint": None, "timings": {}}
    if llm.provider_name() != "gemini":
        return out
    t = time.time()
    out["judge"] = _safe(judge.check, placed)
    out["timings"]["judge"] = round(time.time() - t, 1)
    bad = {i: s for i, s in enumerate(placed) if not s.get("locked") and (s.get("judge") or {}).get("good") == 0}
    fine = [s for i, s in enumerate(placed) if i not in bad]
    pool = ThreadPoolExecutor(1)
    early = pool.submit(_safe, inpoint.refine, fine) if fine else None      # overlaps with the repair below
    t = time.time()
    repaired = []
    if bad and out["judge"] and out["judge"].get("ok"):
        new = {}
        for i, s in bad.items():
            tried = {q.lower() for q in [s.get("query") or "", *(s.get("alt_queries") or [])]}
            qs = [q for q in (s.get("judge") or {}).get("queries", []) if q and q.lower() not in tried]
            if qs:
                new[i] = qs[:3]
        missing = {i: s for i, s in bad.items() if i not in new}
        if missing:                              # the judge gave no new searches for these: ask separately
            new.update(_safe(judge.rewrite_queries, missing) or {})
        if new:
            if live_on:
                qs = [q for lst in new.values() for q in lst]
                _safe(live.fetch, qs, searcher, None, lib or also, len(qs))
            redo = [{**placed[i], "query": new[i][0], "alt_queries": new[i][1:3]} for i in new]
            refilled = _fill(searcher, redo, library=lib, also_lib=also)
            _safe(judge.check, refilled, judge.PER_SLOT_RETRY)
            fixed = 0
            for i, r in zip(new, refilled):
                r["repaired"] = True
                if r.get("shot"):
                    placed[i] = {**placed[i], **r}
                    repaired.append(placed[i])
                    fixed += 1
                else:
                    placed[i]["alt_queries"] = [*placed[i].get("alt_queries", []), *new[i]][:4]
            out["repair"] = {"tried": len(new), "fixed": fixed}
    out["timings"]["repair"] = round(time.time() - t, 1)
    t = time.time()
    late = _safe(inpoint.refine, repaired) if repaired else None
    first = early.result() if early else None
    pool.shutdown(wait=False)
    out["timings"]["inpoint_wait"] = round(time.time() - t, 1)
    parts = [x for x in (first, late) if x]
    out["inpoint"] = ({"ok": all(x.get("ok") for x in parts), "spots": sum(x.get("spots", 0) for x in parts),
                       "moved": sum(x.get("moved", 0) for x in parts)} if parts else None)
    return out


def queries_for(slot_list: list) -> tuple:
    """(queries, n_main): every spot's main query first, then all its alternative phrasings."""
    mains = [s.get("query") for s in slot_list if s.get("query")]
    alts = [a for s in slot_list for a in (s.get("alt_queries") or [])[:2] if a]
    return mains + alts, len(mains)


def live_library(pid: str, proj: dict) -> int:
    """Clips fetched for an edit with no chosen library go into their own 'live' library, so they never leak into
    Search or other projects' 'all footage'. Created once per project."""
    if proj.get("live_library"):
        return proj["live_library"]
    c = db.conn()
    name = f"Fetched: {proj.get('name') or pid}"
    if c.execute("SELECT 1 FROM libraries WHERE name=?", (name,)).fetchone():
        name = f"{name} ({pid[-6:]})"
    lid = c.execute("INSERT INTO libraries(name, domain, kind) VALUES(?,?,?)",
                    (name, f"clips fetched live for the project {proj.get('name') or pid}", "live")).lastrowid
    c.commit()
    proj["live_library"] = lid
    return lid


class _Clock:
    """Seconds spent per stage, saved on the project so a slow run can be explained."""

    def __init__(self):
        self.t0 = self.t = time.time()
        self.laps = {}

    def lap(self, name: str):
        now = time.time()
        self.laps[name] = round(now - self.t, 1)
        self.t = now

    def done(self) -> dict:
        return {**self.laps, "total": round(time.time() - self.t0, 1)}


def analyse_project(pid: str, searcher):
    d = store.folder(pid)
    proj = store.load(pid)
    try:
        clock = _Clock()
        store.set_status(pid, "preparing video", 0.04)
        work = d / "work.mp4"
        ffmpeg.normalise(d / proj["source"], work)
        info = ffmpeg.probe(work)
        proj.update(duration=info["duration"], width=info["width"], height=info["height"], has_audio=info["has_audio"])
        clock.lap("prepare")

        store.set_status(pid, "splitting the picture into scenes", 0.10)
        with ThreadPoolExecutor(1) as ex:                      # picture scan (OpenCV) runs while Whisper listens
            scan_f = ex.submit(split.video_scan, work, d / "frames")
            if info["has_audio"]:
                store.set_status(pid, "transcribing the audio", 0.16)
                tr = analyse.transcribe(work, lambda f: store.set_status(pid, "transcribing the audio", 0.16 + 0.44 * f))
            else:
                tr = {"language": None, "duration": info["duration"], "segments": []}
            scan = scan_f.result()
        (d / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
        segs = rules.align_script(tr["segments"], proj.get("script"))
        clock.lap("audio+picture")

        store.set_status(pid, "building clips from audio and picture", 0.62)
        units = split.build_units(segs, scan["cuts"], scan["strip"], info["duration"])

        eng = llm.provider_name()
        store.set_status(pid, f"reading the script ({'Gemini' if eng == 'gemini' else 'offline engine'})", 0.66)
        # the face map only helps the offline engine's spot rules, so it is computed only if Gemini fails or is absent
        plan = llm.plan(units, scan["cuts"], info["duration"], lambda: analyse.face_map(work), proj.get("script"), segs)
        clock.lap("script->queries (LLM)")

        lib = proj.get("library")
        fetched = {"added": 0, "queries": []}
        also = None
        if proj.get("live_search", lib is None):               # a chosen library works offline unless live search is switched on
            store.set_status(pid, "fetching B-roll from Pixabay", 0.72)
            qs, n_main = queries_for(plan["slots"])
            if lib is None:
                also = live_library(pid, proj)
            fetched = live.fetch(qs, searcher,
                                 lambda f, q: store.set_status(pid, f"fetching B-roll from Pixabay: {q}", 0.72 + 0.14 * f),
                                 library_id=lib or also, n_main=n_main)
        clock.lap("fetch+embed clips")

        store.set_status(pid, "placing B-roll", 0.88)
        placed = _fill(searcher, plan["slots"], library=lib, also_lib=also)
        clock.lap("place")
        verdict = None
        if llm.provider_name() == "gemini":
            store.set_status(pid, "Gemini is checking the pictures and choosing where each clip starts", 0.93)
            verdict = finish(searcher, placed, lib, also, live_on=bool(proj.get("live_search", lib is None)))
            clock.lap("Gemini check+repair+in-points")
        proj.update(language=tr["language"], segments=segs, units=units, cuts=scan["cuts"], shots=scan["shots"],
                    strip=scan["strip"], strip_every=split.STRIP_EVERY_S,
                    llm={"provider": plan["provider"], "summary": plan.get("summary", ""), "ms": plan.get("ms"),
                         "error": plan.get("error"), "slots": len(plan["slots"])},
                    live=fetched, judge=verdict, slot_source=plan["provider"], slots=placed, stage="ready", timings=clock.done())
        store.save(pid, proj)
        store.set_status(pid, "ready", 1.0)
    except Exception as e:
        traceback.print_exc()
        proj["stage"] = "failed"
        store.save(pid, proj)
        store.set_status(pid, "failed", 0.0, f"{type(e).__name__}: {e}")


def start_analyse(pid, searcher):
    threading.Thread(target=analyse_project, args=(pid, searcher), daemon=True, name=f"analyse-{pid}").start()


def _shot_file(shot: dict):
    """Local file row for a shot card (downloads stock clips on demand)."""
    c = db.conn()
    if shot.get("file_id"):
        r = c.execute("SELECT path, duration FROM files WHERE id=?", (shot["file_id"],)).fetchone()
        if r:
            return r
    if shot.get("stock_id"):
        return hydrate.ensure_file(shot["stock_id"])
    return None


def render_project(pid: str):
    d = store.folder(pid)
    proj = store.load(pid)
    try:
        store.set_status(pid, "collecting clips", 0.1)
        plan = []
        for s in proj.get("slots", []):
            sh = s.get("shot")
            if not sh:
                continue
            f = _shot_file(sh)
            if f is None:
                continue
            dur = s["end"] - s["start"]
            src_in = sh.get("trim_in") if sh.get("trim_in") is not None else sh["t_start"]
            fd = f["duration"] or (src_in + dur)
            if src_in + dur > fd:
                src_in = max(0.0, fd - dur)
            plan.append({"path": f["path"], "src_in": src_in, "start": s["start"], "end": s["end"]})
        store.set_status(pid, "rendering video", 0.3)
        out = d / "final.mp4"
        ffmpeg.render(d / "work.mp4", plan, out, proj["width"], proj["height"], proj.get("has_audio", True))
        proj.update(rendered=True, render_clips=len(plan))
        store.save(pid, proj)
        store.set_status(pid, "rendered", 1.0)
    except Exception as e:
        traceback.print_exc()
        store.set_status(pid, "render failed", 0.0, f"{type(e).__name__}: {e}")


def start_render(pid):
    threading.Thread(target=render_project, args=(pid,), daemon=True, name=f"render-{pid}").start()
