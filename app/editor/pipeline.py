"""Editor jobs.

analyse : upload → normalise → split by picture (scene cuts + filmstrip) and by audio (Whisper) → units →
          LLM decides spots + queries → Pixabay live sourcing → planner fills every spot → project ready
render  : ffmpeg overlay of the chosen clips on the A-roll (original audio kept)
"""
import json
import threading
import traceback
from datetime import date

from .. import db, planner
from ..sources import hydrate
from . import analyse, ffmpeg, live, llm, slots as rules, split, store


def _fill_once(searcher, slot_list: list, use_truth=True, use_cuts=True, use_memory=True) -> list:
    if not slot_list:
        return []
    beats = [planner.Beat(i, s.get("text") or s.get("query") or "", round(s["end"] - s["start"], 2), s.get("query") or None)
             for i, s in enumerate(slot_list)]
    p = planner.plan(searcher, "", beats=beats, use_truth=use_truth, use_cuts=use_cuts, use_memory=use_memory,
                     today=date.today().isoformat())
    out = []
    for s, b in zip(slot_list, p["beats"]):
        out.append({**{k: s[k] for k in ("start", "end", "text", "query", "alt_queries", "reason") if k in s},
                    "shot": b["chosen"][0] if b["chosen"] else None, "alts": b["alts"][:8],
                    "rejected": b["rejected"][:3], "n_rejected": b["n_rejected"], "claims": b.get("claims")})
    return out


def _fill(searcher, slot_list: list, **flags) -> list:
    """Fill every spot from the library (which now includes the fresh Pixabay clips). A spot whose main query finds
    nothing truthful is retried with its alternative phrasings before it is left empty."""
    out = _fill_once(searcher, slot_list, **flags)
    for k in (0, 1):
        missing = [i for i, s in enumerate(out) if not s["shot"] and len(slot_list[i].get("alt_queries") or []) > k]
        if not missing:
            break
        retry = _fill_once(searcher, [{**slot_list[i], "query": slot_list[i]["alt_queries"][k]} for i in missing], **flags)
        for i, r in zip(missing, retry):
            if r["shot"]:
                out[i] = {**r, "query": slot_list[i]["query"], "used_query": slot_list[i]["alt_queries"][k]}
    return out


def queries_for(slot_list: list) -> list:
    qs = []
    for s in slot_list:
        qs.append(s.get("query"))
        qs += (s.get("alt_queries") or [])[:1]
    return [q for q in qs if q]


def analyse_project(pid: str, searcher):
    d = store.folder(pid)
    proj = store.load(pid)
    try:
        store.set_status(pid, "preparing video", 0.04)
        work = d / "work.mp4"
        ffmpeg.normalise(d / proj["source"], work)
        info = ffmpeg.probe(work)
        proj.update(duration=info["duration"], width=info["width"], height=info["height"], has_audio=info["has_audio"])

        store.set_status(pid, "splitting the picture into scenes", 0.10)
        scan = split.video_scan(work, d / "frames")

        if info["has_audio"]:
            store.set_status(pid, "transcribing the audio", 0.16)
            tr = analyse.transcribe(work, lambda f: store.set_status(pid, "transcribing the audio", 0.16 + 0.44 * f))
        else:
            tr = {"language": None, "duration": info["duration"], "segments": []}
        (d / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")
        segs = rules.align_script(tr["segments"], proj.get("script"))

        store.set_status(pid, "building clips from audio and picture", 0.62)
        units = split.build_units(segs, scan["cuts"], scan["strip"], info["duration"])
        fmap = analyse.face_map(work)

        eng = llm.provider_name()
        store.set_status(pid, f"reading the script ({'Gemini' if eng == 'gemini' else 'offline engine'})", 0.66)
        plan = llm.plan(units, scan["cuts"], info["duration"], fmap, proj.get("script"))

        store.set_status(pid, "fetching B-roll from Pixabay", 0.72)
        fetched = live.fetch(queries_for(plan["slots"]), searcher,
                             lambda f, q: store.set_status(pid, f"fetching B-roll from Pixabay: {q}", 0.72 + 0.16 * f))

        store.set_status(pid, "placing B-roll", 0.9)
        proj.update(language=tr["language"], segments=segs, units=units, cuts=scan["cuts"], shots=scan["shots"],
                    strip=scan["strip"], strip_every=split.STRIP_EVERY_S,
                    llm={"provider": plan["provider"], "summary": plan.get("summary", ""), "ms": plan.get("ms"),
                         "error": plan.get("error"), "slots": len(plan["slots"])},
                    live=fetched, slot_source=plan["provider"], slots=_fill(searcher, plan["slots"]), stage="ready")
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
