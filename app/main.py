"""FastAPI app. Read path = immutable Snapshot + LRU caches; indexing runs in a background thread."""
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, export, models, planner
from .config import DEFAULT_DIVERSITY, DEFAULT_K, THUMBS
from .indexer import jobs, worker
from .search import Searcher
from .sources import hydrate, ingest
from .store import SnapshotHolder

STATIC = Path(__file__).parent / "static"
state = {}


def _poller():
    """Swap in a fresh snapshot when the indexer bumps index_version (atomic reference swap)."""
    while True:
        time.sleep(2)
        try:
            state["holder"].refresh_if_stale()
        except Exception as e:
            print("snapshot refresh failed:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.conn()
    holder = SnapshotHolder()
    state["holder"] = holder
    state["search"] = Searcher(holder)
    models.mtext()                       # warm: load multilingual text tower once
    state["search"].warmup()
    threading.Thread(target=_poller, daemon=True, name="snap-poller").start()
    if os.getenv("EPOCH_INDEXER", "1") == "1":
        worker.start_thread()
    yield
    worker.stop()


app = FastAPI(title="Epoch B-roll", lifespan=lifespan)


class SearchReq(BaseModel):
    query: str
    k: int = DEFAULT_K
    diversity: float = DEFAULT_DIVERSITY
    filters: dict | None = None


class IndexReq(BaseModel):
    path: str


class IngestReq(BaseModel):
    sources: list[str] = ["pixabay", "commons", "archive"]
    max: int = 500


class PlanReq(BaseModel):
    script: str
    wpm: int = 150


class ExportReq(BaseModel):
    beats: list
    format: str = "xml"          # xml | edl | srt | credits


@app.get("/api/status")
def status():
    c = db.conn()
    snap = state["holder"].get()
    files = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM files GROUP BY status")}
    tiers = {(r["src"] or "own"): r["n"] for r in c.execute(
        """SELECT si.source AS src, COUNT(*) n FROM shots s LEFT JOIN stock_items si ON si.id=s.stock_id
           WHERE s.active=1 GROUP BY 1""")}
    return {
        "version": snap.version, "shots": len(snap), "files": files, "queue": jobs.status(),
        "indexer": worker.state(), "sources": tiers, "ingest": ingest.state(),
    }


@app.post("/api/index")
def index_folder(req: IndexReq):
    if not Path(req.path).is_dir():
        raise HTTPException(400, f"not a folder: {req.path}")
    return jobs.enqueue_folder(req.path)


@app.post("/api/ingest")
def start_ingest(req: IngestReq):
    srcs = [x for x in req.sources if x in ingest.CONNECTORS]
    if not srcs:
        raise HTTPException(400, "sources must be among pixabay|commons|archive")
    return {"started": ingest.start_background(sources=srcs, max_items=max(1, min(req.max, 20000)))}


@app.get("/api/ingest/status")
def ingest_status():
    return ingest.state()


@app.post("/api/shots/{shot_id}/hydrate")
def hydrate_shot(shot_id: int):
    try:
        return hydrate.hydrate_shot(shot_id)
    except hydrate.NotHydratable as e:
        raise HTTPException(409, f"cannot load video: {e}")


@app.post("/api/search")
def search(req: SearchReq):
    q = req.query.strip()
    if not q:
        raise HTTPException(400, "empty query")
    return state["search"].search(q, k=max(1, min(req.k, 60)),
                                  diversity=max(0.0, min(req.diversity, 1.0)), filters=req.filters)


@app.post("/api/plan")
def make_plan(req: PlanReq):
    if not req.script.strip():
        raise HTTPException(400, "empty script")
    t0 = time.perf_counter()
    out = planner.plan(state["search"], req.script, wpm=req.wpm)
    out["took_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return out


@app.post("/api/export")
def export_plan(req: ExportReq):
    kinds = {"xml": (export.to_xmeml, "application/xml", "epoch_broll.xml"),
             "edl": (export.to_edl, "text/plain", "epoch_broll.edl"),
             "srt": (export.to_srt, "text/plain", "epoch_labels.srt"),
             "credits": (export.credits, "text/plain", "epoch_credits.txt")}
    if req.format not in kinds:
        raise HTTPException(400, "format must be xml|edl|srt|credits")
    fn, mime, name = kinds[req.format]
    body = fn(req.beats)
    sk = export.skipped_clips(req.beats)            # files already downloaded by fn(), so this is cheap
    import json as _json
    return Response(body, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Epoch-Skipped": str(len(sk)),
        "X-Epoch-Skipped-Detail": _json.dumps(sk)[:800].encode("ascii", "ignore").decode(),
        "Access-Control-Expose-Headers": "X-Epoch-Skipped, X-Epoch-Skipped-Detail, Content-Disposition"})


@app.get("/api/similar/{shot_id}")
def similar(shot_id: int, k: int = 12):
    return state["search"].similar(shot_id, k=k)


@app.get("/api/shots/{shot_id}")
def shot(shot_id: int):
    c = db.conn()
    s = c.execute("""SELECT s.*, f.path, f.duration AS file_duration, p.shot_date, p.date_source,
                            p.gps_lat, p.gps_lon, p.source_kind
                     FROM shots s LEFT JOIN files f ON f.id=s.file_id
                     LEFT JOIN provenance p ON p.shot_id=s.id WHERE s.id=?""", (shot_id,)).fetchone()
    if not s:
        raise HTTPException(404)
    d = dict(s)
    d["file"] = Path(d["path"]).name if d.get("path") else None
    d.pop("path", None)
    return d


@app.get("/media/thumb/{shot_id}")
def thumb(shot_id: int):
    p = THUMBS / f"{shot_id}.jpg"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/media/video/{file_id}")
def video(file_id: int, request: Request):
    """HTTP Range streaming so the browser can seek instantly."""
    r = db.conn().execute("SELECT path FROM files WHERE id=?", (file_id,)).fetchone()
    if not r or not os.path.exists(r["path"]):
        raise HTTPException(404)
    path = r["path"]
    size = os.path.getsize(path)
    rng = request.headers.get("range")
    if not rng:
        return FileResponse(path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})
    try:
        a, b = rng.replace("bytes=", "").split("-")
        start = int(a) if a else 0
        end = int(b) if b else min(start + (4 << 20) - 1, size - 1)
    except ValueError:
        raise HTTPException(416)
    end = min(end, size - 1)
    if start > end:
        raise HTTPException(416)
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    return Response(data, status_code=206, media_type="video/mp4", headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes",
        "Content-Length": str(len(data))})


@app.exception_handler(Exception)
async def unhandled(_, exc):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
