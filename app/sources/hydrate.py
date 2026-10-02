"""Lazy hydration: Tier-S stock item → local video file, only when someone previews / plans / exports it.
Picks the smallest sensible rendition, registers a `files` row, and queues full analysis in the background."""
import json
import os
import re

from .. import db, media
from ..config import HYDRATED
from ..indexer import jobs
from .base import download, fetch_json, head_status

MAX_BYTES = 300 << 20
WIKI = "https://upload.wikimedia.org/wikipedia/commons/"


class NotHydratable(Exception):
    pass


def _pixabay(item):
    r = json.loads(item["renditions"] or "{}")
    for k in ("small", "tiny", "medium"):
        if k in r and r[k].get("url"):
            return r[k]["url"], ".mp4"
    raise NotHydratable("no pixabay rendition")


def _commons(item):
    r = json.loads(item["renditions"] or "{}").get("original")
    if not r:
        raise NotHydratable("no original")
    url = r["url"].split("?")[0]
    name = url.rsplit("/", 1)[-1]
    path = url.replace(WIKI, "")                       # 7/7a/Name.webm
    busy = False
    for q in ("480p.vp9.webm", "360p.vp9.webm", "240p.vp9.webm"):
        code = head_status(f"{WIKI}transcoded/{path}/{name}.{q}")
        if code == 200:
            return f"{WIKI}transcoded/{path}/{name}.{q}", ".webm"
        if code == 429 or code >= 500:
            busy = True                       # throttled: not the same as 'no transcode'
    if (r.get("size") or 0) <= 60 << 20:
        return url, os.path.splitext(name)[1] or ".webm"
    if busy:
        raise NotHydratable("Wikimedia is rate-limiting us right now; try again in a minute")
    raise NotHydratable(f"original is {(r.get('size') or 0) / 1e6:.0f} MB and no small transcode exists")


def _archive(item):
    d = fetch_json("archive", f"https://archive.org/metadata/{item['source_id']}")
    best = None
    for f in d.get("files", []):
        n = f.get("name", "")
        size = int(f.get("size") or 0)
        if n.lower().endswith((".mp4", ".m4v")) and 0 < size <= MAX_BYTES and (best is None or size < best[1]):
            best = (n, size)
    if not best:
        raise NotHydratable("no mp4 derivative under 300 MB")
    return f"https://archive.org/download/{item['source_id']}/{best[0]}", os.path.splitext(best[0])[1]


PICKERS = {"pixabay": _pixabay, "commons": _commons, "archive": _archive}


def ensure_file(stock_id: int):
    """Return the `files` row for a stock item, downloading it first if needed. Raises NotHydratable."""
    c = db.conn()
    f = c.execute("SELECT * FROM files WHERE stock_id=? AND status IN ('ok','hydrated') ORDER BY id LIMIT 1",
                  (stock_id,)).fetchone()
    if f and os.path.exists(f["path"]):
        return f
    item = c.execute("SELECT * FROM stock_items WHERE id=?", (stock_id,)).fetchone()
    if item is None:
        raise NotHydratable("unknown stock item")
    url, ext = PICKERS[item["source"]](item)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{item['source']}_{item['source_id']}")[:100]
    dest = HYDRATED / f"{safe}{ext}"
    if not dest.exists():
        download(url, dest, max_bytes=MAX_BYTES)
    info = media.probe(dest)
    if info is None:
        dest.unlink(missing_ok=True)
        raise NotHydratable("downloaded file is not readable by OpenCV")
    c.execute("""INSERT OR IGNORE INTO files(path,status,tier,stock_id,duration,fps,width,height)
                 VALUES(?,'hydrated','L',?,?,?,?,?)""",
              (str(dest.resolve()), stock_id, info["duration"], info["fps"], info["width"], info["height"]))
    c.commit()
    f = c.execute("SELECT * FROM files WHERE path=?", (str(dest.resolve()),)).fetchone()
    jobs.enqueue("file", f["id"], jobs.STAGE_INDEX, priority=7)   # full shot analysis in the background
    return f


def hydrate_shot(shot_id: int) -> dict:
    c = db.conn()
    s = c.execute("SELECT stock_id, file_id FROM shots WHERE id=?", (shot_id,)).fetchone()
    if s is None:
        raise NotHydratable("unknown shot")
    if s["file_id"] is not None:
        return {"file_id": s["file_id"], "hydrated": False}
    f = ensure_file(s["stock_id"])
    return {"file_id": f["id"], "hydrated": True, "duration": f["duration"]}
