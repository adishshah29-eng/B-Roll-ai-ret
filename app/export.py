"""Timeline export: FCP7 XML (xmeml v4 → Premiere + Resolve), CMX3600 EDL, SRT labels, credits."""
import zlib
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from . import db
from .sources import hydrate

FPS = 25


def _tc(frames: int, fps=FPS) -> str:
    f = frames % fps
    s = frames // fps
    return f"{s//3600:02d}:{(s//60)%60:02d}:{s%60:02d}:{f:02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"


def _clips_from_beats(beats: list, skipped: list | None = None) -> list:
    """Flatten beats → timeline clips. Each beat's duration is split across its chosen shots.
    Shots that cannot be turned into a file are recorded in `skipped` (never dropped silently)."""
    clips, t = [], 0.0
    skipped = skipped if skipped is not None else []
    c = db.conn()
    for b in beats:
        chosen = b.get("chosen") or []
        if not chosen:
            t += b["dur"]
            continue
        per = b["dur"] / len(chosen)
        for s in chosen:
            row = c.execute("SELECT path, fps, width, height, duration FROM files WHERE id=?",
                            (s.get("file_id"),)).fetchone() if s.get("file_id") else None
            if row is None and s.get("stock_id"):          # Tier-S stock: download the clip now (lazy hydration)
                try:
                    row = hydrate.ensure_file(s["stock_id"])
                except hydrate.NotHydratable as e:
                    skipped.append({"beat": b.get("i"), "file": s.get("file"), "reason": str(e)})
                except Exception as e:           # network etc.
                    skipped.append({"beat": b.get("i"), "file": s.get("file"), "reason": f"{type(e).__name__}: {e}"})
            if row is None:
                if not any(k["beat"] == b.get("i") and k["file"] == s.get("file") for k in skipped):
                    skipped.append({"beat": b.get("i"), "file": s.get("file"), "reason": "no local video file"})
                continue
            # fill the beat from the source: extend past the shot into the same take, or slide back if at the end
            fd = row["duration"] or (s["t_end"] + per)
            src_in = s["t_start"]
            if src_in + per > fd:
                src_in = max(0.0, fd - per)
            src_out = min(fd, src_in + per)
            per_eff = src_out - src_in
            clips.append({
                "name": Path(row["path"]).name, "path": row["path"], "fps": row["fps"] or FPS,
                "w": row["width"], "h": row["height"], "file_dur": row["duration"],
                "src_in": src_in, "src_out": src_out,
                "rec_in": t, "rec_out": t + per_eff, "label": s.get("label"), "text": b["text"],
                "author": s.get("author"), "source": s.get("source", "own"), "page_url": s.get("page_url"),
            })
            t += per_eff
    return clips


def to_xmeml(beats: list, name="Epoch B-roll") -> str:
    clips = _clips_from_beats(beats)
    total = int(round(max((c["rec_out"] for c in clips), default=0) * FPS))
    files_declared, items = set(), []
    for n, c in enumerate(clips, 1):
        a, b = int(round(c["src_in"] * FPS)), int(round(c["src_out"] * FPS))
        s, e = int(round(c["rec_in"] * FPS)), int(round(c["rec_in"] * FPS)) + (b - a)
        fid = f"file-{zlib.crc32(c['path'].encode()) & 0xffffffff}"
        url = "file://localhost/" + quote(c["path"].replace("\\", "/"), safe="/:")
        if fid in files_declared:
            file_xml = f'<file id="{fid}"/>'
        else:
            files_declared.add(fid)
            fdur = int(round((c["file_dur"] or 0) * FPS))
            file_xml = (f'<file id="{fid}"><name>{escape(c["name"])}</name><pathurl>{escape(url)}</pathurl>'
                        f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><duration>{fdur}</duration>'
                        f'<media><video><samplecharacteristics><rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
                        f'<width>{c["w"]}</width><height>{c["h"]}</height></samplecharacteristics></video></media></file>')
        items.append(
            f'<clipitem id="clipitem-{n}"><name>{escape(c["name"])}</name><enabled>TRUE</enabled>'
            f'<duration>{int(round((c["file_dur"] or 0) * FPS))}</duration>'
            f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
            f'<start>{s}</start><end>{e}</end><in>{a}</in><out>{b}</out>{file_xml}'
            f'<comments><mastercomment1>{escape(c["text"][:200])}</mastercomment1></comments></clipitem>')
    w = clips[0]["w"] if clips else 1920
    h = clips[0]["h"] if clips else 1080
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
        f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{total}</duration>'
        f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate>'
        '<media><video><format><samplecharacteristics>'
        f'<rate><timebase>{FPS}</timebase><ntsc>FALSE</ntsc></rate><width>{w}</width><height>{h}</height>'
        '<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>'
        f'<track>{"".join(items)}</track></video></media></sequence></xmeml>')


def to_edl(beats: list, title="EPOCH_BROLL") -> str:
    lines = [f"TITLE: {title}", "FCM: NON-DROP FRAME", ""]
    reels = {}
    for n, c in enumerate(_clips_from_beats(beats), 1):
        a, b = int(round(c["src_in"] * FPS)), int(round(c["src_out"] * FPS))
        s = int(round(c["rec_in"] * FPS)); e = s + (b - a)
        reel = reels.setdefault(c["path"], f"AX{len(reels) + 1:04d}").ljust(8)   # unique reel per source file
        lines += [f"{n:03d}  {reel} V     C        {_tc(a)} {_tc(b)} {_tc(s)} {_tc(e)}",
                  f"* FROM CLIP NAME: {c['name']}", f"* COMMENT: {c['text'][:80]}", ""]
    return "\n".join(lines)


def to_srt(beats: list) -> str:
    """Captions track for honest labelling (e.g. 'FILE · 2019') + beat text as reference."""
    out, n = [], 1
    for c in _clips_from_beats(beats):
        if not c.get("label"):
            continue
        out += [str(n), f"{_srt_time(c['rec_in'])} --> {_srt_time(c['rec_out'])}", c["label"], ""]
        n += 1
    return "\n".join(out)


def credits(beats: list) -> str:
    seen, lines = set(), ["CREDITS (generated by Epoch)", ""]
    for c in _clips_from_beats(beats):
        if c["source"] == "own" or c["path"] in seen:
            continue
        seen.add(c["path"])
        lines.append(f"{c['name']} · {c['source']} · by {c.get('author') or 'unknown'} · {c.get('page_url') or ''}")
    return "\n".join(lines) if len(lines) > 2 else "No third-party footage used."


def skipped_clips(beats: list) -> list:
    sk = []
    _clips_from_beats(beats, sk)
    return sk
