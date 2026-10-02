"""Editor HTTP API (mounted under /api/editor)."""
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import live, llm, pipeline, store

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
                 library: int = Form(0), live: str = Form("")):
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
                     "live_search": (live == "1") if library else True})
    store.set_status(pid, "uploaded", 0.02)
    pipeline.start_analyse(pid, get_searcher())
    return {"id": pid}


@router.get("/config")
def config(check: int = 0):
    import os
    from .. import gemini
    g = gemini.check() if check else {"enabled": gemini.enabled(), "ok": None, "model": None, "error": None}
    return {"llm": "gemini" if g["enabled"] else "offline", "gemini": g, "pixabay": bool(os.getenv("PIXABAY_API_KEY"))}


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
