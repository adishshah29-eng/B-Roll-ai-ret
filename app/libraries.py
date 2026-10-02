"""Domain libraries: a named set of clips for ONE domain (e.g. "Travel India"), the way a real editor works.

A library is made by
  * uploading your own clips (or pointing at a folder)  → indexed fully offline, or
  * auto-building from Pixabay: the domain is expanded into search queries (Gemini if GEMINI_API_KEY, else curated seeds in
    resources/domains/<domain>.yaml, else a generic expansion), the best clips are picked round-robin across the queries,
    DOWNLOADED, and fully analysed (shots, OCR, cut features) like your own footage.
A project / search / plan can then be scoped to one library, so candidates are always on-topic.
"""
import json
import os
import re
import shutil
import threading
import traceback
from pathlib import Path

import requests
import yaml
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from . import db, gemini, textutil
from .config import DATA, RESOURCES
from .indexer import jobs
from .sources import hydrate, ingest
from .sources.pixabay import Pixabay

router = APIRouter(prefix="/api/libraries")
ROOT = DATA / "libraries"
ROOT.mkdir(parents=True, exist_ok=True)
BUILD: dict = {}                 # library id -> {"stage", "progress", "error", "target", "picked", "downloaded", "queries"}
_pix = Pixabay()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MIN_S, MAX_S = 4, 45             # clip length range worth keeping in a B-roll library
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _set(lib_id: int, **kw):
    BUILD.setdefault(lib_id, {}).update(kw)


# ───────────────────────── query planning ─────────────────────────
def domain_queries(domain: str, n: int) -> tuple:
    """-> (queries, how). Curated seeds → Gemini → generic expansion."""
    for name in (slug(domain), slug(domain).split("-")[0]):
        f = RESOURCES / "domains" / f"{name}.yaml"
        if name and f.exists():
            qs = (yaml.safe_load(open(f, encoding="utf-8")) or {}).get("pixabay", [])
            if qs:
                return qs[:n], f"curated list ({name})"
    if gemini.enabled():
        try:
            prompt = (f"You are building a stock-footage library for a video editor who works in this domain: {domain}. "
                      f"Return JSON only: {{\"queries\": [..]}} with {n} different stock-video search queries, each 2-3 plain English "
                      "words, concrete (places, objects, actions, shot types), covering what this editor needs as B-roll. No duplicates.")
            qs = gemini.generate_json(prompt, temperature=0.5, timeout=60).get("queries", [])
            qs = [re.sub(r"\s+", " ", str(q)).strip()[:60] for q in qs if str(q).strip()]
            if len(qs) >= 5:
                return list(dict.fromkeys(qs))[:n], "Gemini"
        except Exception as e:
            print("gemini domain queries failed:", gemini.redact(e))
    base = " ".join(textutil.tokens(domain)[:3]) or domain
    mods = ["", "outdoor", "city", "people", "aerial", "close up", "street", "nature", "detail", "morning", "night", "slow motion"]
    return [f"{base} {m}".strip() for m in mods][:n], "generic expansion"


# ───────────────────────── build ─────────────────────────
def build_auto(lib_id: int, domain: str, n_clips: int):
    try:
        c = db.conn()
        _set(lib_id, stage="planning searches", progress=0.02, error=None, target=n_clips, picked=0, downloaded=0)
        queries, how = domain_queries(domain, max(12, min(40, n_clips // 2)))
        _set(lib_id, stage="searching Pixabay", queries=queries, planner=how)
        dom_tok = textutil.tokens(domain)
        per_query = []
        for i, q in enumerate(queries):
            try:
                items = _pix.search(q, 1)
            except Exception:
                continue
            qt = textutil.tokens(q)

            def score(it, qt=qt):
                hay = set(textutil.tokens(f"{it.title} {it.tags}"))
                return sum(t in hay for t in qt) / max(len(qt), 1) + 0.3 * sum(t in hay for t in dom_tok) / max(len(dom_tok), 1)

            good = [it for it in items if (it.width or 0) >= (it.height or 0) and MIN_S <= (it.duration or 0) <= MAX_S]
            per_query.append(sorted(good, key=score, reverse=True))
            _set(lib_id, progress=0.02 + 0.18 * (i + 1) / len(queries))
        chosen, seen, k = [], set(), 0                      # round-robin across queries: variety, not 60 clips of one thing
        while len(chosen) < n_clips and any(k < len(g) for g in per_query):
            for g in per_query:
                if k < len(g) and g[k].source_id not in seen and len(chosen) < n_clips:
                    seen.add(g[k].source_id)
                    chosen.append(g[k])
            k += 1
        _set(lib_id, stage="adding clips", picked=len(chosen))
        have = ingest._existing(c, "pixabay", [it.source_id for it in chosen])
        if have:
            q = ",".join("?" * len(have))
            c.execute(f"UPDATE stock_items SET library_id=? WHERE source='pixabay' AND library_id IS NULL AND source_id IN ({q})",
                      [lib_id, *have])
            c.commit()
        fresh = [it for it in chosen if it.source_id not in have]
        S = ingest._stock_matrix()
        for i in range(0, len(fresh), 20):
            _, S = ingest.process_items(fresh[i:i + 20], S, lib_id)
            _set(lib_id, progress=0.2 + 0.1 * min(1.0, (i + 20) / max(len(fresh), 1)))
        db.bump_version()

        ids = [r["id"] for r in c.execute("SELECT id FROM stock_items WHERE library_id=? AND source='pixabay'", (lib_id,))]
        _set(lib_id, stage="downloading clips", progress=0.3)
        for j, sid in enumerate(ids):
            try:
                hydrate.ensure_file(sid)                       # downloads + queues full analysis (shots, OCR, cut features)
                c.execute("UPDATE files SET library_id=? WHERE stock_id=? AND library_id IS NULL", (lib_id, sid))
                c.commit()
            except Exception:
                pass
            _set(lib_id, progress=0.3 + 0.55 * (j + 1) / max(len(ids), 1), downloaded=j + 1)
        _set(lib_id, stage="analysing clips", progress=0.85)
    except Exception as e:
        traceback.print_exc()
        _set(lib_id, stage="failed", error=f"{type(e).__name__}: {e}")


# ───────────────────────── queries ─────────────────────────
def _counts(lib_id: int) -> dict:
    c = db.conn()
    r = c.execute("""SELECT COUNT(*) shots, COUNT(DISTINCT COALESCE('f'||s.file_id, 's'||s.stock_id)) clips
                     FROM shots s LEFT JOIN files f ON f.id=s.file_id LEFT JOIN stock_items si ON si.id=s.stock_id
                     WHERE s.active=1 AND COALESCE(f.library_id, si.library_id)=?""", (lib_id,)).fetchone()
    pend = c.execute("""SELECT COUNT(*) FROM jobs j JOIN files f ON f.id=j.target_id
                        WHERE j.target_kind='file' AND j.status IN ('pending','running') AND f.library_id=?""", (lib_id,)).fetchone()[0]
    return {"clips": r["clips"], "shots": r["shots"], "pending": pend}


def describe(row) -> dict:
    d = {"id": row["id"], "name": row["name"], "domain": row["domain"], "kind": row["kind"], **_counts(row["id"])}
    b = dict(BUILD.get(row["id"], {}))
    if b.get("stage") == "analysing clips" and d["pending"] == 0:
        b["stage"], b["progress"] = "ready", 1.0
        BUILD[row["id"]].update(stage="ready", progress=1.0)
    d["build"] = b or None
    return d


# ───────────────────────── API ─────────────────────────
class NewLib(BaseModel):
    name: str
    domain: str = ""
    kind: str = "empty"            # empty | folder | auto
    folder: str | None = None
    n_clips: int = 60


@router.get("")
def list_libraries():
    return [describe(r) for r in db.conn().execute("SELECT * FROM libraries ORDER BY id")]


@router.post("")
def create(req: NewLib):
    name = req.name.strip()
    if not name:
        raise HTTPException(400, "give the library a name")
    c = db.conn()
    if c.execute("SELECT 1 FROM libraries WHERE name=?", (name,)).fetchone():
        raise HTTPException(409, f"a library called '{name}' already exists")
    if req.kind == "folder" and not (req.folder and Path(req.folder).is_dir()):
        raise HTTPException(400, f"not a folder: {req.folder}")
    if req.kind == "auto" and not req.domain.strip():
        raise HTTPException(400, "describe the domain to build from")
    lib_id = c.execute("INSERT INTO libraries(name, domain, kind) VALUES(?,?,?)", (name, req.domain.strip(), req.kind)).lastrowid
    c.commit()
    if req.kind == "folder":
        jobs.enqueue_folder(req.folder, lib_id)
        db.bump_version()                       # already-indexed clips just changed library: refresh the search snapshot
    elif req.kind == "auto":
        _set(lib_id, stage="starting", progress=0.0)
        threading.Thread(target=build_auto, args=(lib_id, req.domain.strip(), max(8, min(req.n_clips, 150))),
                         daemon=True, name=f"library-{lib_id}").start()
    return {"id": lib_id}


@router.get("/{lib_id}")
def one(lib_id: int):
    r = db.conn().execute("SELECT * FROM libraries WHERE id=?", (lib_id,)).fetchone()
    if not r:
        raise HTTPException(404)
    return describe(r)


@router.post("/{lib_id}/upload")
async def upload(lib_id: int, files: list[UploadFile] = File(...)):
    if not db.conn().execute("SELECT 1 FROM libraries WHERE id=?", (lib_id,)).fetchone():
        raise HTTPException(404)
    d = ROOT / str(lib_id)
    d.mkdir(exist_ok=True)
    saved = 0
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in VIDEO_EXTS:
            continue
        dst = d / re.sub(r"[^A-Za-z0-9._-]", "_", Path(f.filename).name)
        with open(dst, "wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        saved += 1
    if not saved:
        raise HTTPException(400, "no video files in that upload")
    res = jobs.enqueue_folder(str(d), lib_id)
    db.bump_version()
    return {"saved": saved, **res}


@router.delete("/{lib_id}")
def delete(lib_id: int, remove_files: bool = False):
    c = db.conn()
    if not c.execute("SELECT 1 FROM libraries WHERE id=?", (lib_id,)).fetchone():
        raise HTTPException(404)
    c.execute("UPDATE files SET library_id=NULL WHERE library_id=?", (lib_id,))
    c.execute("UPDATE stock_items SET library_id=NULL WHERE library_id=?", (lib_id,))
    c.execute("DELETE FROM libraries WHERE id=?", (lib_id,))
    c.commit()
    BUILD.pop(lib_id, None)
    if remove_files:
        shutil.rmtree(ROOT / str(lib_id), ignore_errors=True)
    db.bump_version()
    return {"deleted": lib_id}
