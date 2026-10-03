"""Editor HTTP API (mounted under /api/editor)."""
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import export as editor_export
from . import suggest as editor_suggest
from . import live, llm, pipeline, store
from . import slots as rules

router = APIRouter(prefix="/api/editor")
get_searcher = None          # set by main.py at startup
MAX_UPLOAD = 1 << 30         # 1 GB
OK_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def _project(pid):
    try:
        return store.load(pid)
    except (FileNotFoundError, ValueError):
        raise HTTPException(404, "no such project")


@router.post("/projects")
async def create(file: UploadFile = File(...), script: str = Form(""), name: str = Form(""),
                 library: int = Form(0), live: str = Form(""), density: str = Form("balanced")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in OK_EXT:
        raise HTTPException(400, f"unsupported file type {ext or '?'}; use mp4, mov, webm, mkv or avi")
    pid = store.new_id()
    d = store.folder(pid)
    d.mkdir(parents=True)
    dst = d / f"source{ext}"
    size = 0
    with open(dst, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                out.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, "file larger than 1 GB")
            out.write(chunk)
    store.save(pid, {"id": pid, "name": name or Path(file.filename).stem, "source": dst.name, "script": script.strip(),
                     "stage": "analysing", "slots": [], "library": library or None,
                     "live_search": (live == "1") if library else True,
                     "density": density if density in rules.DENSITY else "balanced"})
    store.set_status(pid, "uploaded", 0.02)
    pipeline.start_analyse(pid, get_searcher())
    return {"id": pid}


@router.get("/config")
def config(check: int = 0):
    import os
    from .. import gemini, jev
    g = gemini.check() if check else {"enabled": gemini.enabled(), "ok": None, "model": None, "error": None}
    return {"llm": llm.provider_name(), "gemini": g, "jev": {"enabled": jev.enabled(), "model": jev.model()},
            "pixabay": bool(os.getenv("PIXABAY_API_KEY"))}


@router.get("/projects/{pid}/frames/{name}")
def frame(pid: str, name: str):
    _project(pid)
    path = store.folder(pid) / "frames" / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/projects")
def projects():
    return store.listing()


@router.get("/projects/{pid}")
def get(pid: str):
    p = _project(pid)
    p["status"] = store.status(pid)
    return p


@router.get("/projects/{pid}/status")
def status(pid: str):
    return store.status(pid)


class SlotsReq(BaseModel):
    slots: list
    refill: bool = False          # re-run the B-roll engine for these slots (after adding/moving/editing queries)
    live: bool = False            # also ask Pixabay for fresh clips for the spots being refilled


@router.put("/projects/{pid}/slots")
def put_slots(pid: str, req: SlotsReq):
    p = _project(pid)
    dur = p.get("duration") or 0
    clean = []
    for s in sorted(req.slots, key=lambda s: float(s.get("start", 0))):
        a, b = max(0.0, float(s["start"])), min(dur, float(s["end"]))
        if b - a < 0.5:
            continue
        clean.append({**s, "start": round(a, 2), "end": round(b, 2)})
    fixed = []                                           # spots must not overlap: trim the earlier one, drop slivers
    for s in clean:
        if fixed and s["start"] < fixed[-1]["end"] + 0.05:
            fixed[-1]["end"] = round(s["start"] - 0.05, 2)
            if fixed[-1]["end"] - fixed[-1]["start"] < 0.5:
                fixed.pop()
        fixed.append(s)
    clean = fixed
    if req.refill:
        keep = {i: s.get("shot") for i, s in enumerate(clean) if s.get("locked")}
        also = p.get("live_library") if not p.get("library") else None
        if req.live:
            qs, n_main = pipeline.queries_for([s for s in clean if not s.get("locked")])
            if not p.get("library"):
                also = pipeline.live_library(pid, p)
            live.fetch(qs, get_searcher(), library_id=p.get("library") or also, n_main=n_main)
        clean = pipeline._fill(get_searcher(), clean, library=p.get("library"), also_lib=also)
        for i, sh in keep.items():                    # your locked picks are never judged, moved or replaced
            clean[i]["shot"], clean[i]["locked"] = sh, True
        pipeline.finish(get_searcher(), clean, p.get("library"), also, live_on=req.live)
    p["slots"], p["rendered"] = clean, False
    store.save(pid, p)
    return {"slots": clean}


@router.post("/projects/{pid}/render")
def render(pid: str):
    p = _project(pid)
    if p.get("stage") != "ready":
        raise HTTPException(409, "project is not ready yet")
    store.set_status(pid, "queued for render", 0.05)
    pipeline.start_render(pid)
    return {"started": True}


def _range(path: Path, request: Request, mime="video/mp4"):
    if not path.exists():
        raise HTTPException(404)
    size = path.stat().st_size
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type=mime, headers={"Accept-Ranges": "bytes"})
    a, b = rng.replace("bytes=", "").split("-")
    start = int(a) if a else 0
    end = min(int(b) if b else start + (4 << 20) - 1, size - 1)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    return Response(data, status_code=206, media_type=mime, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(len(data))})


@router.get("/projects/{pid}/video")
def video(pid: str, request: Request):
    _project(pid)
    return _range(store.folder(pid) / "work.mp4", request)


@router.get("/projects/{pid}/final.mp4")
def final(pid: str, request: Request, download: int = 0):
    p = _project(pid)
    path = store.folder(pid) / "final.mp4"
    if download:
        return FileResponse(path, media_type="video/mp4", filename=f"{p.get('name') or pid}_broll.mp4")
    return _range(path, request)


@router.delete("/projects/{pid}")
def delete(pid: str):
    _project(pid)
    shutil.rmtree(store.folder(pid), ignore_errors=True)
    store.STATUS.pop(pid, None)
    return {"deleted": pid}

EXPORT_FORMATS = ("xml", "edl", "srt", "credits", "zip")


@router.get("/projects/{pid}/export")
def export_project(pid: str, format: str = "zip"):
    """Download the edit: Premiere/Resolve XML, EDL, captions (SRT), licence sheet, or everything as a zip."""
    p = _project(pid)
    if format not in EXPORT_FORMATS:
        raise HTTPException(400, f"format must be one of {', '.join(EXPORT_FORMATS)}")
    if p.get("stage") != "ready":
        raise HTTPException(409, "the project is not ready yet")
    if format != "srt" and not any(s.get("shot") for s in p.get("slots", [])):
        raise HTTPException(400, "there are no B-roll clips on the timeline to export yet")
    try:
        body, mime, name, skipped = editor_export.export(pid, format)
    except Exception as e:
        raise HTTPException(500, f"export failed: {type(e).__name__}: {e}")
    import json as _json
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Epoch-Skipped": str(len(skipped)),
        "X-Epoch-Skipped-Detail": _json.dumps(skipped)[:800].encode("ascii", "ignore").decode(),
        "Access-Control-Expose-Headers": "X-Epoch-Skipped, X-Epoch-Skipped-Detail, Content-Disposition"})


class ReplanReq(BaseModel):
    density: str = "balanced"


@router.post("/projects/{pid}/replan")
def replan(pid: str, req: ReplanReq):
    """Light / Balanced / Rich: re-select spots from the stored line scores (locked spots stay). Runs in the background."""
    p = _project(pid)
    if p.get("stage") != "ready":
        raise HTTPException(409, "the project is not ready yet")
    if req.density not in rules.DENSITY:
        raise HTTPException(400, f"density must be one of {', '.join(rules.DENSITY)}")
    store.set_status(pid, "re-planning", 0.02)
    pipeline.start_replan(pid, get_searcher(), req.density)
    return {"started": True}


class SuggestReq(BaseModel):
    text: str = ""                 # the spoken line the clip is for
    query: str = ""                # the spot's search query, if it has one
    alt_queries: list[str] = []
    k: int = 24
    check: bool = False            # False = fast list by score; True = Gemini looks at the pictures against the line and the video's topic
    expand: bool = False           # True = also fetch topic-specific clips from Pixabay first (slow), then check


@router.post("/projects/{pid}/suggest")
def suggest_clips(pid: str, req: SuggestReq):
    """Clips from this project's library that fit the line AND the video's topic. Call once with check=false (instant) and
    again with check=true to get the Gemini-checked order and the fit flags."""
    _project(pid)
    if not (req.text.strip() or req.query.strip()):
        raise HTTPException(400, "give the line or a query")
    if req.expand:
        return editor_suggest.expand(get_searcher(), pid, req.text.strip(), req.query.strip(), req.alt_queries[:2], max(6, min(req.k, 60)))
    return editor_suggest.suggest(get_searcher(), pid, req.text.strip(), req.query.strip(), req.alt_queries[:2],
                                  max(6, min(req.k, 60)), req.check)
