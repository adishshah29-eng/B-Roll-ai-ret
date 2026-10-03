"""Editor exports: take the finished edit into another tool or hand it to someone.

  xml      FCP7 xmeml v4 (Premiere Pro and DaVinci Resolve import it): V1 = your original video, V2 = the B-roll at the spot
           times (with the chosen in-points), A1 = your original audio. Paths are absolute local paths on this machine.
  edl      CMX3600 of the B-roll events on the A-roll's timeline (an EDL holds one video track, so V1 is not in it).
  srt      captions of what is said, from Whisper's word timings (≤ 2 lines, ≤ 42 characters a line, ≤ 6 s each).
  credits  licence + credit sheet for every clip used (source, author, licence, page, where it is used, commercial yes/no).
  zip      all of the above + the B-roll clips themselves + the rendered MP4 if there is one + a README.
B-roll that is still a stock thumbnail is downloaded first (same as rendering). Clips that cannot be downloaded are listed,
never silently dropped.
"""
import io
import json
import re
import zipfile
import zlib
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from .. import db, licence
from ..sources import hydrate
from . import ffmpeg, store

LINE_MAX = 42
CAPTION_MAX_S = 6.0


# ───────────────────────── timeline model ─────────────────────────
def _fps(path) -> float:
    """Frame rate from `ffmpeg -i` (imageio-ffmpeg ships no ffprobe)."""
    import subprocess
    err = subprocess.run([ffmpeg.EXE, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"([\d.]+) fps", err)
    return float(m.group(1)) if m else 25.0


def _rate(fps: float) -> tuple:
    """(timebase, ntsc) for xmeml: 29.97 → (30, TRUE), 25 → (25, FALSE)."""
    tb = int(round(fps))
    return tb, abs(fps - tb) > 0.01


def _file_row(sh: dict):
    c = db.conn()
    if sh.get("file_id"):
        r = c.execute("SELECT path, fps, width, height, duration FROM files WHERE id=?", (sh["file_id"],)).fetchone()
        if r:
            return r
    if sh.get("stock_id"):
        return hydrate.ensure_file(sh["stock_id"], index=False)
    return None


def timeline(pid: str) -> dict:
    """Everything the writers need: the A-roll, the placed B-roll clips, captions and what was skipped."""
    p = store.load(pid)
    d = store.folder(pid)
    src = d / p["source"]
    info = ffmpeg.probe(src)
    fps = _fps(src)
    broll, skipped = [], []
    for i, s in enumerate(sorted(p.get("slots", []), key=lambda x: x["start"])):
        sh = s.get("shot")
        if not sh:
            continue
        try:
            row = _file_row(sh)
        except Exception as e:                      # download refused, network...
            row, why = None, f"{type(e).__name__}: {e}"
        else:
            why = "no local video file"
        if row is None:
            skipped.append({"spot": i + 1, "at": s["start"], "clip": sh.get("file"), "reason": why})
            continue
        dur = s["end"] - s["start"]
        fd = row["duration"] or (sh["t_end"] or dur)
        src_in = sh.get("trim_in") if sh.get("trim_in") is not None else sh.get("t_start", 0.0)
        if src_in + dur > fd:
            src_in = max(0.0, fd - dur)
        broll.append({"spot": i + 1, "start": s["start"], "end": min(s["end"], s["start"] + (fd - src_in)),
                      "src_in": src_in, "path": row["path"], "name": Path(row["path"]).name, "fps": row["fps"] or fps,
                      "w": row["width"], "h": row["height"], "file_dur": fd, "text": s.get("text") or "",
                      "query": s.get("query") or "", "shot": sh})
    return {"project": p, "aroll": {"path": str(src.resolve()), "name": src.name, "duration": info["duration"] or p.get("duration") or 0,
                                    "w": info["width"] or p.get("width") or 1920, "h": info["height"] or p.get("height") or 1080,
                                    "has_audio": info["has_audio"]},
            "fps": fps, "broll": broll, "skipped": skipped}


# ───────────────────────── writers ─────────────────────────
def _tc(frames: int, tb: int) -> str:
    f, s = frames % tb, frames // tb
    return f"{s // 3600:02d}:{(s // 60) % 60:02d}:{s % 60:02d}:{f:02d}"


def _srt_time(sec: float) -> str:
    ms = int(round(max(0.0, sec) * 1000))
    return f"{ms // 3600000:02d}:{(ms // 60000) % 60:02d}:{(ms // 1000) % 60:02d},{ms % 1000:03d}"


def _url(path: str) -> str:
    return "file://localhost/" + quote(path.replace("\\", "/"), safe="/:")


def to_xml(tl: dict) -> str:
    tb, ntsc = _rate(tl["fps"])
    rate = f"<rate><timebase>{tb}</timebase><ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc></rate>"
    fr = lambda sec: int(round(sec * tb))
    a = tl["aroll"]
    total = fr(a["duration"])
    name = escape(tl["project"].get("name") or "Epoch edit")

    def file_el(fid, path, nm, dur_s, w, h, audio):
        aud = "<audio><channelcount>2</channelcount></audio>" if audio else ""
        return (f'<file id="{fid}"><name>{escape(nm)}</name><pathurl>{escape(_url(path))}</pathurl>{rate}'
                f'<duration>{fr(dur_s)}</duration><media><video><samplecharacteristics>{rate}<width>{w}</width>'
                f'<height>{h}</height></samplecharacteristics></video>{aud}</media></file>')

    afid = f"file-a-{zlib.crc32(a['path'].encode()) & 0xffffffff}"
    v1 = (f'<clipitem id="clipitem-a-v"><name>{escape(a["name"])}</name><enabled>TRUE</enabled><duration>{total}</duration>{rate}'
          f'<start>0</start><end>{total}</end><in>0</in><out>{total}</out>'
          f'{file_el(afid, a["path"], a["name"], a["duration"], a["w"], a["h"], a["has_audio"])}'
          f'<link><linkclipref>clipitem-a-v</linkclipref><mediatype>video</mediatype></link>'
          + (f'<link><linkclipref>clipitem-a-a</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex></link>' if a["has_audio"] else "")
          + '</clipitem>')
    declared, v2 = set(), []
    for n, c in enumerate(tl["broll"], 1):
        s, e = fr(c["start"]), fr(c["end"])
        i0 = fr(c["src_in"])
        fid = f"file-b-{zlib.crc32(c['path'].encode()) & 0xffffffff}"
        fx = f'<file id="{fid}"/>' if fid in declared else file_el(fid, c["path"], c["name"], c["file_dur"], c["w"], c["h"], False)
        declared.add(fid)
        v2.append(f'<clipitem id="clipitem-b-{n}"><name>{escape(c["name"])}</name><enabled>TRUE</enabled>'
                  f'<duration>{fr(c["file_dur"])}</duration>{rate}<start>{s}</start><end>{e}</end>'
                  f'<in>{i0}</in><out>{i0 + (e - s)}</out>{fx}'
                  f'<comments><mastercomment1>{escape(c["text"][:200])}</mastercomment1>'
                  f'<mastercomment2>{escape("search: " + c["query"][:120])}</mastercomment2></comments></clipitem>')
    audio = ""
    if a["has_audio"]:
        audio = (f'<audio><track><clipitem id="clipitem-a-a"><name>{escape(a["name"])}</name><enabled>TRUE</enabled>'
                 f'<duration>{total}</duration>{rate}<start>0</start><end>{total}</end><in>0</in><out>{total}</out>'
                 f'<file id="{afid}"/><sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>'
                 f'<link><linkclipref>clipitem-a-v</linkclipref><mediatype>video</mediatype></link>'
                 f'<link><linkclipref>clipitem-a-a</linkclipref><mediatype>audio</mediatype><trackindex>1</trackindex></link>'
                 f'</clipitem></track></audio>')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
            f'<sequence id="sequence-1"><name>{name}</name><duration>{total}</duration>{rate}'
            f'<media><video><format><samplecharacteristics>{rate}<width>{a["w"]}</width><height>{a["h"]}</height>'
            '<pixelaspectratio>square</pixelaspectratio></samplecharacteristics></format>'
            f'<track>{v1}</track><track>{"".join(v2)}</track></video>{audio}</media></sequence></xmeml>')


def to_edl(tl: dict) -> str:
    tb, ntsc = _rate(tl["fps"])
    fr = lambda sec: int(round(sec * tb))
    title = re.sub(r"[^A-Za-z0-9_ -]", "", (tl["project"].get("name") or "EPOCH")).upper()[:60] or "EPOCH"
    lines = [f"TITLE: {title} B-ROLL", "FCM: NON-DROP FRAME", "* B-roll events on the timeline of your original video (V1 is not in an EDL).", ""]
    reels = {}
    for n, c in enumerate(tl["broll"], 1):
        a = fr(c["src_in"]); s, e = fr(c["start"]), fr(c["end"])
        b = a + (e - s)
        reel = reels.setdefault(c["path"], f"AX{len(reels) + 1:04d}").ljust(8)
        lines += [f"{n:03d}  {reel} V     C        {_tc(a, tb)} {_tc(b, tb)} {_tc(s, tb)} {_tc(e, tb)}",
                  f"* FROM CLIP NAME: {c['name']}", f"* COMMENT: {c['text'][:80]}", ""]
    return "\n".join(lines)


def _caption_chunks(seg: dict) -> list:
    """Split one transcript segment into caption-sized pieces using word timings."""
    words = seg.get("words") or []
    if not words:
        return [(seg["start"], seg["end"], seg.get("text", "").strip())]
    out, cur = [], []
    for w in words:
        cand = " ".join(x["w"] for x in cur + [w])
        too_long = len(cand) > 2 * LINE_MAX or (cur and w["e"] - cur[0]["s"] > CAPTION_MAX_S)
        if cur and too_long:
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.!?]$", w["w"]) and len(" ".join(x["w"] for x in cur)) > LINE_MAX * 0.6:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    if len(out) >= 2 and len(" ".join(x["w"] for x in out[-1])) < 20:     # no orphan word on its own caption: rebalance
        both = out[-2] + out[-1]
        total = len(" ".join(x["w"] for x in both))
        k, run = 1, 0
        for k in range(1, len(both)):
            run += len(both[k - 1]["w"]) + 1
            if run >= total / 2:
                break
        out[-2:] = [both[:k], both[k:]] if 0 < k < len(both) else [both]
    return [(c[0]["s"], c[-1]["e"], " ".join(x["w"] for x in c)) for c in out]


def _two_lines(text: str) -> str:
    if len(text) <= LINE_MAX:
        return text
    words, best = text.split(), None
    for k in range(1, len(words)):
        a, b = " ".join(words[:k]), " ".join(words[k:])
        score = max(len(a), len(b))
        if best is None or score < best[0]:
            best = (score, a + "\n" + b)
    return best[1]


def to_srt(tl: dict) -> str:
    out, n = [], 1
    for seg in tl["project"].get("segments") or []:
        for a, b, text in _caption_chunks(seg):
            if not text:
                continue
            out += [str(n), f"{_srt_time(a)} --> {_srt_time(b)}", _two_lines(text), ""]
            n += 1
    return "\n".join(out) if out else "1\n00:00:00,000 --> 00:00:01,000\n(no speech found)\n"


def credits(tl: dict) -> str:
    used = {}
    for c in tl["broll"]:
        sh = c["shot"]
        k = sh.get("stock_id") or c["path"]
        u = used.setdefault(k, {"c": c, "sh": sh, "at": []})
        u["at"].append(f"{c['start']:.1f}-{c['end']:.1f}s")
    lines = [f"LICENCE AND CREDITS: {tl['project'].get('name') or 'Epoch edit'}", "Generated by Epoch. Check each licence before publishing; this sheet is guidance, not legal advice.", ""]
    commercial_ok, credit_lines = True, []
    for u in used.values():
        sh, c = u["sh"], u["c"]
        lic = sh.get("licence") or {}
        src = sh.get("source") or "own"
        is_ok = lic.get("commercial", src == "own")
        commercial_ok &= bool(is_ok)
        lines += [f"- {sh.get('title') or c['name']}",
                  f"  source: {src}" + (f" · by {sh['author']}" if sh.get("author") else ""),
                  f"  licence: {lic.get('label') or ('your footage' if src == 'own' else 'unknown')}"
                  + (f" ({lic['text']})" if lic.get("text") else "") + (f" {lic['url']}" if lic.get("url") else ""),
                  f"  commercial use: {'yes' if is_ok else 'NO / check'}",
                  f"  page: {sh.get('page_url') or '-'}",
                  f"  used at: {', '.join(u['at'])}", ""]
        if lic.get("class") == "attribution":
            credit_lines.append(licence.attribution_text(sh.get("title"), sh.get("author"), lic.get("text"), lic.get("url"), sh.get("page_url")))
    lines.append(f"ALL CLIPS SAFE FOR COMMERCIAL USE: {'yes' if commercial_ok and used else ('no clips used' if not used else 'NO, see above')}")
    if credit_lines:
        lines += ["", "CREDIT TEXT TO PASTE IN YOUR DESCRIPTION:", *credit_lines]
    if tl["skipped"]:
        lines += ["", "NOT EXPORTED (could not be downloaded):"] + [f"- spot {s['spot']} at {s['at']:.1f}s: {s['clip']} ({s['reason']})" for s in tl["skipped"]]
    return "\n".join(lines) + "\n"


README = """Epoch export: {name}

files
  {slug}.xml           Premiere Pro: File > Import.  DaVinci Resolve: File > Import > Timeline.
                       V1 = your original video, V2 = B-roll, A1 = your original audio.
  {slug}.edl           B-roll only, on your video's timeline (CMX3600).
  {slug}.srt           captions of the speech.
  {slug}_credits.txt   licences and credit text for every clip used.
  media/               the B-roll clips used.
  {slug}_final.mp4     the rendered video (if you rendered it).

The XML points at the files where they live on the computer that made the export. If you open it on another computer,
relink the B-roll to the files in media/ and your original video when asked.
{skipped}"""


def package(pid: str) -> bytes:
    tl = timeline(pid)
    p = tl["project"]
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", p.get("name") or pid).strip("_")[:50] or "epoch"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{slug}.xml", to_xml(tl))
        z.writestr(f"{slug}.edl", to_edl(tl))
        z.writestr(f"{slug}.srt", to_srt(tl))
        z.writestr(f"{slug}_credits.txt", credits(tl))
        for path in dict.fromkeys(c["path"] for c in tl["broll"]):
            if Path(path).exists():
                z.write(path, f"media/{Path(path).name}", compress_type=zipfile.ZIP_STORED)   # video is already compressed
        final = store.folder(pid) / "final.mp4"
        if p.get("rendered") and final.exists():
            z.write(final, f"{slug}_final.mp4", compress_type=zipfile.ZIP_STORED)
        sk = ("\nnot exported (could not be downloaded):\n" + "\n".join(f"  spot {s['spot']}: {s['clip']} ({s['reason']})" for s in tl["skipped"])) if tl["skipped"] else ""
        z.writestr("README.txt", README.format(name=p.get("name") or pid, slug=slug, skipped=sk))
        z.writestr("project.json", json.dumps({k: p.get(k) for k in ("id", "name", "duration", "slots")}, ensure_ascii=False, default=str)[:2_000_000])
    return buf.getvalue()


KINDS = {"xml": ("application/xml", ".xml", to_xml), "edl": ("text/plain", ".edl", to_edl),
         "srt": ("application/x-subrip", ".srt", to_srt), "credits": ("text/plain", "_credits.txt", credits)}


def export(pid: str, fmt: str) -> tuple:
    """-> (body bytes, mime, filename, skipped list)."""
    p = store.load(pid)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", p.get("name") or pid).strip("_")[:50] or "epoch"
    if fmt == "zip":
        return package(pid), "application/zip", f"{slug}_epoch_export.zip", []
    mime, ext, fn = KINDS[fmt]
    if fmt == "srt":                                 # captions need no clip downloads
        return fn({"project": p}).encode("utf-8"), mime, f"{slug}{ext}", []
    tl = timeline(pid)
    return fn(tl).encode("utf-8"), mime, f"{slug}{ext}", tl["skipped"]
