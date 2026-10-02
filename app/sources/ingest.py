"""Stock ingestion (Tier S): metadata + ONE preview image per clip → embedding + zero-shot tags → searchable.
No video is downloaded here (see hydrate.py). Idempotent (UNIQUE source,source_id), resumable (cursors),
polite (token buckets + 24 h API cache).

    python -m app.sources.ingest --seed --max 3000
    python -m app.sources.ingest --sources commons --queries "India street,Mumbai" --max 200
"""
import argparse
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np
import yaml
from PIL import Image

from .. import db, models, store
from ..config import RESOURCES, THUMBS
from ..indexer import tags
from ..indexer.pipeline import _jpeg_bytes
from .archive import Archive
from .base import get_bytes
from .commons import Commons
from .pixabay import Pixabay

CONNECTORS = {"pixabay": Pixabay(), "commons": Commons(), "archive": Archive()}
DEFAULT_CAPS = {"archive": 300, "commons": 900}      # archive = long films with a single cover image
XDEDUPE_SIM = 0.97                                   # near-identical preview across sources/ids
STATE = {"running": False, "added": 0, "dups": 0, "preview_failed": 0, "seen": 0,
         "task": "", "target": 0, "error": None}
_stop = threading.Event()


def state() -> dict:
    return dict(STATE)


def stop():
    _stop.set()


def _existing(c, source, ids):
    if not ids:
        return set()
    q = ",".join("?" * len(ids))
    return {r["source_id"] for r in c.execute(
        f"SELECT source_id FROM stock_items WHERE source=? AND source_id IN ({q})", [source] + ids)}


def _stock_matrix():
    """Embeddings of active Tier-S shots (for cross-source near-duplicate detection)."""
    c = db.conn()
    rows = [r["emb_row"] for r in c.execute(
        "SELECT emb_row FROM shots WHERE stock_id IS NOT NULL AND file_id IS NULL AND active=1 AND emb_row IS NOT NULL")]
    if not rows:
        return np.zeros((0, 512), np.float32)
    return store.load_matrix()[rows]


def _fetch_preview(item):
    try:
        raw = get_bytes(item.preview_url, timeout=25)
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        if min(img.size) < 48:
            return None
        return img
    except Exception:
        return None


def process_items(items: list, S: np.ndarray, library_id: int | None = None):
    """items: new StockItems (already filtered for existence). Returns (n_added, updated S)."""
    with ThreadPoolExecutor(8) as ex:
        imgs = list(ex.map(_fetch_preview, items))
    ok = [(it, im) for it, im in zip(items, imgs) if im is not None]
    STATE["preview_failed"] += len(items) - len(ok)
    if not ok:
        return 0, S
    E = models.embed_images([im for _, im in ok], batch_size=16)

    keep = []
    for k in range(len(ok)):
        if len(S) and float((S @ E[k]).max()) > XDEDUPE_SIM:
            STATE["dups"] += 1
            continue
        keep.append(k)
        S = np.vstack([S, E[k:k + 1]]) if len(S) else E[k:k + 1].copy()
    if not keep:
        return 0, S
    E = E[keep]
    ok = [ok[k] for k in keep]
    size_l, _ = tags.zero_shot(E, "size")
    wx_l, wx_c = tags.zero_shot(E, "weather")
    dp_l, _ = tags.zero_shot(E, "daypart")
    se_l, _ = tags.zero_shot(E, "season")

    start = store.append(E)
    c = db.conn()
    now = datetime.now(timezone.utc).isoformat()
    c.execute("BEGIN")
    try:
        for k, (it, im) in enumerate(ok):
            cur = c.execute(
                """INSERT OR IGNORE INTO stock_items(source,source_id,title,tags,author,author_url,page_url,licence,
                   licence_url,published_at,date_kind,gps_lat,gps_lon,duration,width,height,preview_urls,renditions,
                   fetched_at,library_id,tier) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'S')""",
                (it.source, it.source_id, it.title, it.tags, it.author, it.author_url, it.page_url, it.licence,
                 it.licence_url, it.published_at, it.date_kind, it.gps[0] if it.gps else None,
                 it.gps[1] if it.gps else None, it.duration, it.width, it.height,
                 json.dumps([it.preview_url]), json.dumps(it.renditions), now, library_id))
            if cur.rowcount == 0:
                continue
            stock_id = cur.lastrowid
            sh = c.execute(
                """INSERT INTO shots(stock_id,t_start,t_end,emb_row,size_tag,motion,orientation,weather,daypart,season,weather_conf)
                   VALUES(?,?,?,?,?,'unknown',?,?,?,?,?)""",
                (stock_id, 0.0, it.duration or 0.0, start + k, size_l[k],
                 tags.orientation(it.width, it.height) if it.width and it.height else "16:9",
                 wx_l[k], dp_l[k], se_l[k], wx_c[k]))
            sid = sh.lastrowid
            (THUMBS / f"{sid}.jpg").write_bytes(_jpeg_bytes(im))
            c.execute("UPDATE shots SET thumb=? WHERE id=?", (f"{sid}.jpg", sid))
            c.execute("""INSERT OR REPLACE INTO provenance(shot_id,shot_date,date_source,gps_lat,gps_lon,source_kind)
                         VALUES(?,?,?,?,?,?)""",
                      (sid, it.published_at, it.date_kind, it.gps[0] if it.gps else None,
                       it.gps[1] if it.gps else None, it.source))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    db.bump_version()
    return len(ok), S


def _tasks(sources, queries_by_source):
    """Round-robin across sources and queries, page by page, so one source/query can't dominate."""
    per_source = {}
    for s in sources:
        conn = CONNECTORS[s]
        per_source[s] = [(s, q, p) for p in range(1, conn.max_pages + 1) for q in queries_by_source.get(s, [])]
    lists = list(per_source.values())
    i = 0
    while any(lists):
        for lst in lists:
            if i < len(lst):
                yield lst[i]
        i += 1
        if all(i >= len(l) for l in lists):
            break


def run_ingest(sources=("pixabay", "commons", "archive"), max_items=3000, queries_by_source=None,
               caps=None, progress=print) -> dict:
    caps = {**DEFAULT_CAPS, **(caps or {})}
    seeds = yaml.safe_load(open(RESOURCES / "seed_queries.yaml", encoding="utf-8"))
    queries_by_source = queries_by_source or seeds
    _stop.clear()
    STATE.update(running=True, added=0, dups=0, preview_failed=0, seen=0, task="", target=max_items, error=None)
    tags.ensure_caches()
    c = db.conn()
    S = _stock_matrix()
    per_src_added = {s: 0 for s in sources}
    try:
        for source, q, page in _tasks(list(sources), queries_by_source):
            if STATE["added"] >= max_items or _stop.is_set():
                break
            if per_src_added[source] >= caps.get(source, 10**9):
                continue
            if c.execute("SELECT done FROM ingest_cursors WHERE source=? AND query=? AND page=?",
                         (source, q, page)).fetchone():
                continue
            STATE["task"] = f"{source}:{q}:p{page}"
            try:
                items = CONNECTORS[source].search(q, page)
            except Exception as e:
                progress(f"[warn] {STATE['task']} failed: {e}")
                continue
            STATE["seen"] += len(items)
            have = _existing(c, source, [i.source_id for i in items])
            fresh, seen_ids = [], set()
            for it in items:
                if it.source_id not in have and it.source_id not in seen_ids:
                    seen_ids.add(it.source_id)
                    fresh.append(it)
            room = min(max_items - STATE["added"], caps.get(source, 10**9) - per_src_added[source])
            fresh = fresh[:room]
            added, S = process_items(fresh, S) if fresh else (0, S)
            STATE["added"] += added
            per_src_added[source] += added
            c.execute("INSERT OR REPLACE INTO ingest_cursors(source,query,page,done) VALUES(?,?,?,1)",
                      (source, q, page))
            c.commit()
            progress(f"[ingest] {STATE['task']:<38} fetched={len(items):>3} new={len(fresh):>3} added={added:>3} "
                     f"total={STATE['added']}/{max_items} dups={STATE['dups']}")
            if not items:      # exhausted this query's pages
                continue
    except Exception as e:
        STATE["error"] = f"{type(e).__name__}: {e}"
        raise
    finally:
        STATE["running"] = False
    return dict(STATE) | {"by_source": per_src_added}


def start_background(**kw):
    if STATE["running"]:
        return False
    threading.Thread(target=lambda: run_ingest(progress=lambda *_: None, **kw), daemon=True, name="ingest").start()
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="use resources/seed_queries.yaml")
    ap.add_argument("--sources", default="pixabay,commons,archive")
    ap.add_argument("--queries", default=None, help="comma-separated; overrides the seeds for the chosen sources")
    ap.add_argument("--max", type=int, default=3000)
    a = ap.parse_args()
    sources = [s for s in a.sources.split(",") if s in CONNECTORS]
    qbs = {s: [q.strip() for q in a.queries.split(",")] for s in sources} if a.queries else None
    t0 = time.time()
    res = run_ingest(sources, a.max, qbs)
    print(f"done in {time.time() - t0:.0f}s: {res}")


if __name__ == "__main__":
    main()
