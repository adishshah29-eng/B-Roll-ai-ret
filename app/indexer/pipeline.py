"""Index one local video file → shots (+ embeddings, tags, thumbs, basic provenance).

Streams frames in small chunks (RAM-safe on long files). Writes are one transaction per file, so a crash
leaves nothing half-written; embeddings are appended just before the rows that reference them.
"""
import io
import os
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image

from .. import db, media, models, store
from ..config import (CUT_SIM, EMBED_BATCH, SAMPLE_EVERY_S, THUMB_W, THUMBS, WINDOW_S)
from . import tags


class Segmenter:
    """Streaming shot segmentation on per-second embeddings.
    A shot closes when the next sample is visually different (cos < cut_sim) or the window is full."""

    def __init__(self, cut_sim=CUT_SIM, window_s=WINDOW_S, step=SAMPLE_EVERY_S):
        self.cut_sim, self.window_s, self.step = cut_sim, window_s, step
        self.cur = None
        self.done = []

    def _new(self, t, emb, grey, jpg):
        self.cur = {"t0": t, "embs": [emb], "greys": [grey], "jpgs": [jpg], "ts": [t]}

    def _close(self):
        c = self.cur
        if c is None:
            return
        m = np.mean(c["embs"], axis=0)
        m /= max(np.linalg.norm(m), 1e-9)
        mid = len(c["jpgs"]) // 2
        self.done.append({
            "t_start": c["t0"], "t_end": c["ts"][-1] + self.step, "emb": m.astype(np.float32),
            "greys": c["greys"], "jpg": c["jpgs"][mid], "n": len(c["embs"]),
        })
        self.cur = None

    def feed(self, t, emb, grey, jpg):
        if self.cur is None:
            self._new(t, emb, grey, jpg)
            return
        prev = self.cur["embs"][-1]
        if float(prev @ emb) < self.cut_sim or (t - self.cur["t0"]) >= self.window_s:
            self._close()
            self._new(t, emb, grey, jpg)
        else:
            c = self.cur
            c["embs"].append(emb); c["greys"].append(grey); c["jpgs"].append(jpg); c["ts"].append(t)

    def finish(self):
        self._close()
        return self.done


def _jpeg_bytes(img: Image.Image) -> bytes:
    w, h = img.size
    img = img.resize((THUMB_W, max(1, int(h * THUMB_W / w))))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


def _blur(jpg: bytes) -> float:
    a = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_GRAYSCALE)
    return float(cv2.Laplacian(a, cv2.CV_64F).var()) if a is not None else 0.0


MIN_SHOT_S = 1.0


def merge_short(shots: list, duration: float | None) -> list:
    """Cap t_end at the file duration, then fold shots shorter than MIN_SHOT_S into the previous one
    (embedding = frame-count-weighted mean). Avoids useless 0.04 s tail shots."""
    out = []
    for s in shots:
        if duration:
            s["t_end"] = min(s["t_end"], duration)
        if out and (s["t_end"] - s["t_start"]) < MIN_SHOT_S:
            p = out[-1]
            e = p["emb"] * p["n"] + s["emb"] * s["n"]
            p["emb"] = (e / max(np.linalg.norm(e), 1e-9)).astype(np.float32)
            p["greys"] = p["greys"] + s["greys"]
            p["n"] += s["n"]
            p["t_end"] = s["t_end"]
        else:
            out.append(s)
    return out


def segment_file(path, embed_fn=None, duration=None):
    """Decode → embed in chunks → segment. Returns list of shot dicts. embed_fn injectable for tests."""
    embed_fn = embed_fn or models.embed_images
    seg = Segmenter()
    chunk = []

    def flush():
        if not chunk:
            return
        embs = embed_fn([c[1] for c in chunk], batch_size=EMBED_BATCH)
        for (t, img, grey), e in zip(chunk, embs):
            seg.feed(t, e, grey, _jpeg_bytes(img))
        chunk.clear()

    for t, img, grey in media.sample_frames(path, SAMPLE_EVERY_S):
        chunk.append((t, img, grey))
        if len(chunk) >= EMBED_BATCH * 2:
            flush()
    flush()
    return merge_short(seg.finish(), duration)


def index_file(file_id: int) -> dict:
    c = db.conn()
    f = c.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    path = f["path"]
    if not os.path.exists(path):
        c.execute("UPDATE files SET status='offline' WHERE id=?", (file_id,)); c.commit()
        return {"shots": 0, "status": "offline"}

    info = media.probe(path)
    if info is None:
        c.execute("UPDATE files SET status='failed' WHERE id=?", (file_id,)); c.commit()
        raise RuntimeError(f"cannot open video: {path}")

    chash = media.content_hash(path)
    dup = c.execute("SELECT id FROM files WHERE content_hash=? AND id!=? AND status='ok'",
                    (chash, file_id)).fetchone()
    if dup:
        c.execute("UPDATE files SET status='duplicate', content_hash=? WHERE id=?", (chash, file_id)); c.commit()
        return {"shots": 0, "status": "duplicate"}

    meta = media.mp4_meta(path)
    mtime = datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).isoformat()
    shot_date, date_src = (meta["created"], "meta") if meta["created"] else (mtime, "mtime")

    shots = segment_file(path, duration=info["duration"])
    if not shots:
        c.execute("UPDATE files SET status='failed' WHERE id=?", (file_id,)); c.commit()
        raise RuntimeError("no frames decoded")

    E = np.stack([s["emb"] for s in shots])
    size_l, _ = tags.zero_shot(E, "size")
    wx_l, _ = tags.zero_shot(E, "weather")
    dp_l, _ = tags.zero_shot(E, "daypart")
    se_l, _ = tags.zero_shot(E, "season")
    orient = tags.orientation(info["width"], info["height"])

    start_row = store.append(E)
    try:
        c.execute("BEGIN")
        for k, s in enumerate(shots):
            mscore, mlevel = tags.motion_level(s["greys"])
            cur = c.execute(
                """INSERT INTO shots(file_id,t_start,t_end,emb_row,size_tag,motion,motion_score,orientation,
                                     weather,daypart,season,quality)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (file_id, s["t_start"], min(s["t_end"], info["duration"] or s["t_end"]), start_row + k,
                 size_l[k], mlevel, mscore, orient, wx_l[k], dp_l[k], se_l[k], _blur(s["jpg"])))
            sid = cur.lastrowid
            (THUMBS / f"{sid}.jpg").write_bytes(s["jpg"])
            c.execute("UPDATE shots SET thumb=? WHERE id=?", (f"{sid}.jpg", sid))
            c.execute("""INSERT OR REPLACE INTO provenance(shot_id,shot_date,date_source,gps_lat,gps_lon,source_kind)
                         VALUES(?,?,?,?,?,'own')""", (sid, shot_date, date_src, meta["lat"], meta["lon"]))
        c.execute("""UPDATE files SET content_hash=?, duration=?, fps=?, width=?, height=?, created_at=?,
                     gps_lat=?, gps_lon=?, status='ok' WHERE id=?""",
                  (chash, info["duration"], info["fps"], info["width"], info["height"],
                   shot_date, meta["lat"], meta["lon"], file_id))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise
    if f["stock_id"]:
        _adopt_stock(file_id, f["stock_id"])
    db.bump_version()
    return {"shots": len(shots), "status": "ok"}


def _adopt_stock(file_id: int, stock_id: int):
    """A hydrated stock file now has real shots: retire the Tier-S placeholder and carry the stock item's
    identity (source badge, credits, recorded date, GPS) over to the new shots."""
    c = db.conn()
    it = c.execute("SELECT * FROM stock_items WHERE id=?", (stock_id,)).fetchone()
    c.execute("BEGIN")
    c.execute("UPDATE shots SET active=0 WHERE stock_id=? AND file_id IS NULL", (stock_id,))
    c.execute("UPDATE shots SET stock_id=? WHERE file_id=?", (stock_id, file_id))
    if it is not None:
        c.execute("""UPDATE provenance SET
                       shot_date=COALESCE(?, shot_date), date_source=CASE WHEN ? IS NOT NULL THEN ? ELSE date_source END,
                       gps_lat=COALESCE(?, gps_lat), gps_lon=COALESCE(?, gps_lon), source_kind=?
                     WHERE shot_id IN (SELECT id FROM shots WHERE file_id=?)""",
                  (it["published_at"], it["published_at"], it["date_kind"] or "unknown",
                   it["gps_lat"], it["gps_lon"], it["source"], file_id))
    c.execute("COMMIT")
