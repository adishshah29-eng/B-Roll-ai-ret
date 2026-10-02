"""CUTS pillar, index side: per-shot features that decide whether two shots CUT well together.

For every shot (Tier L, from the video):
  head / tail motion  mean optical flow (dx, dy) over the first / last ~0.3 s → screen direction in and out
  head / tail luma    brightness (0..1)   → exposure jumps
  head / tail warmth  (R-B)/255 in -1..1  → colour-temperature jumps
  saliency centroid   centre of mass of the edge map (x, y in 0..1) → where the subject sits in frame
  peak_t              time of the strongest motion inside the shot → where to start the clip

Tier-S stock (thumbnail only): luma / warmth / saliency from the preview, flow = 0, `approx=1`.

    python -m app.indexer.cutfeat --enqueue-all     # queue the full analysis for every analysed local file
    python -m app.indexer.cutfeat --approx          # thumbnail-based features for all stock shots
"""
import argparse

import cv2
import numpy as np

from .. import db
from ..config import THUMBS
from . import jobs

FLOW_W = 160
WIN_S = 0.3
PEAK_STEP_S = 0.5
EPS_S = 0.04


def _small_gray(frame, w=FLOW_W):
    h, ww = frame.shape[:2]
    return cv2.cvtColor(cv2.resize(frame, (w, max(2, int(h * w / ww))), interpolation=cv2.INTER_AREA),
                        cv2.COLOR_BGR2GRAY)


def _flow(g1, g2):
    f = cv2.calcOpticalFlowFarneback(g1, g2, None, 0.5, 2, 15, 2, 5, 1.1, 0)
    return float(f[..., 0].mean()), float(f[..., 1].mean())


def _luma(frame):
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean() / 255.0)


def _warmth(frame):
    b, _, r = (float(frame[..., i].mean()) for i in range(3))     # BGR order
    return (r - b) / 255.0


def _saliency(frame):
    g = _small_gray(frame, 96)
    e = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0)) + np.abs(cv2.Sobel(g, cv2.CV_32F, 0, 1))
    tot = float(e.sum())
    if tot < 1e-6:
        return 0.5, 0.5
    ys, xs = np.mgrid[0:e.shape[0], 0:e.shape[1]]
    return float((e * xs).sum() / tot / e.shape[1]), float((e * ys).sum() / tot / e.shape[0])


def _read(cap, t):
    cap.set(cv2.CAP_PROP_POS_MSEC, max(t, 0.0) * 1000)
    ok, fr = cap.read()
    return fr if ok else None


def shot_features(cap, t0: float, t1: float) -> dict | None:
    """Features for one shot spanning [t0, t1] seconds of an open VideoCapture."""
    if t1 - t0 < 0.1:
        return None
    hs = min(t0 + WIN_S, t1 - EPS_S)
    ts = max(t1 - WIN_S - EPS_S, t0)
    h1, h2, t_a, t_b = _read(cap, t0), _read(cap, hs), _read(cap, ts), _read(cap, t1 - EPS_S)
    if h1 is None or t_b is None:
        return None
    out = {"head_luma": _luma(h1), "tail_luma": _luma(t_b), "head_warmth": _warmth(h1), "tail_warmth": _warmth(t_b)}
    out["head_dx"], out["head_dy"] = _flow(_small_gray(h1), _small_gray(h2)) if h2 is not None else (0.0, 0.0)
    out["tail_dx"], out["tail_dy"] = _flow(_small_gray(t_a), _small_gray(t_b)) if t_a is not None else (0.0, 0.0)
    mid = _read(cap, (t0 + t1) / 2)
    out["sal_x"], out["sal_y"] = _saliency(mid if mid is not None else h1)
    # motion peak: strongest change between samples taken every PEAK_STEP_S
    times = list(np.arange(t0, t1 - EPS_S, PEAK_STEP_S))[:10]
    greys = []
    for t in times:
        fr = _read(cap, float(t))
        if fr is not None:
            greys.append((float(t), cv2.cvtColor(cv2.resize(fr, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)))
    peak, best = (t0 + t1) / 2, 1.0                 # below this much change the shot is "static": use the middle
    for (ta, ga), (tb, gb) in zip(greys, greys[1:]):
        d = float(np.mean(np.abs(ga.astype(np.int16) - gb.astype(np.int16))))
        if d > best:
            best, peak = d, (ta + tb) / 2
    out["peak_t"] = float(peak)
    out["approx"] = 0
    return out


def _store(c, shot_id, f):
    c.execute("""INSERT OR REPLACE INTO cut_features(shot_id, head_dx, head_dy, tail_dx, tail_dy, head_luma, tail_luma,
                 head_warmth, tail_warmth, sal_x, sal_y, peak_t, approx) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (shot_id, f["head_dx"], f["head_dy"], f["tail_dx"], f["tail_dy"], f["head_luma"], f["tail_luma"],
               f["head_warmth"], f["tail_warmth"], f["sal_x"], f["sal_y"], f.get("peak_t"), f.get("approx", 0)))


def cutfeat_file(file_id: int) -> dict:
    c = db.conn()
    f = c.execute("SELECT path, duration FROM files WHERE id=?", (file_id,)).fetchone()
    shots = c.execute("SELECT id, t_start, t_end FROM shots WHERE file_id=? AND active=1 ORDER BY t_start",
                      (file_id,)).fetchall()
    if f is None or not shots:
        return {"shots": 0, "done": 0}
    cap = cv2.VideoCapture(f["path"])
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {f['path']}")
    dur = f["duration"] or 1e9
    done = 0
    try:
        for s in shots:
            feats = shot_features(cap, s["t_start"], min(s["t_end"], dur))
            if feats:
                _store(c, s["id"], feats)
                done += 1
        c.commit()
    finally:
        cap.release()
    return {"shots": len(shots), "done": done}


def run(target_id: int) -> dict:
    return cutfeat_file(target_id)


def thumb_features(shot_id: int) -> dict | None:
    img = cv2.imread(str(THUMBS / f"{shot_id}.jpg"))
    if img is None:
        return None
    sx, sy = _saliency(img)
    return {"head_dx": 0.0, "head_dy": 0.0, "tail_dx": 0.0, "tail_dy": 0.0,
            "head_luma": _luma(img), "tail_luma": _luma(img), "head_warmth": _warmth(img),
            "tail_warmth": _warmth(img), "sal_x": sx, "sal_y": sy, "peak_t": None, "approx": 1}


def approx_all() -> int:
    """Thumbnail-based features for every active shot that has none yet (stock placeholders)."""
    c = db.conn()
    rows = c.execute("""SELECT s.id FROM shots s LEFT JOIN cut_features k ON k.shot_id=s.id
                        WHERE s.active=1 AND s.file_id IS NULL AND k.shot_id IS NULL""").fetchall()
    n = 0
    for r in rows:
        f = thumb_features(r["id"])
        if f:
            _store(c, r["id"], f)
            n += 1
        if n % 500 == 0:
            c.commit()
    c.commit()
    return n


def enqueue_all() -> int:
    c = db.conn()
    return sum(jobs.enqueue("file", r["id"], jobs.STAGE_CUTFEAT, priority=9)
               for r in c.execute("SELECT id FROM files WHERE status='ok'").fetchall())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue-all", action="store_true")
    ap.add_argument("--approx", action="store_true")
    a = ap.parse_args()
    if a.enqueue_all:
        print("cutfeat jobs queued:", enqueue_all())
    if a.approx:
        print("approximate features for", approx_all(), "stock shots")
