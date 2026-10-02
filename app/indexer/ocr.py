"""Signboard OCR stage (Tier L). Reads text from the middle frame of each shot with RapidOCR (ONNX PP-OCR:
~0.8 s/frame on this CPU vs 4–7 s for EasyOCR, decision D19) and stores it in provenance.ocr_text, where
truth.place_evidence() turns it into place evidence.

    python -m app.indexer.ocr --enqueue-all        # queue OCR for every analysed local file
"""
import argparse
import threading

import cv2

from .. import db
from . import jobs

MIN_CONF = 0.6
MIN_CHARS = 3
MAX_SIDE = 800
_lock = threading.Lock()
_engine = None


def engine():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
        return _engine


def read_text(bgr) -> str:
    """OCR one BGR frame → 'LINE | LINE' (confident, non-trivial lines only)."""
    h, w = bgr.shape[:2]
    s = MAX_SIDE / max(h, w)
    if s < 1:
        bgr = cv2.resize(bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    res, _ = engine()(bgr)
    lines = []
    for r in res or []:
        t = str(r[1]).strip()
        if float(r[2]) >= MIN_CONF and sum(ch.isalnum() for ch in t) >= MIN_CHARS:
            lines.append(t)
    return " | ".join(lines)[:300]


def ocr_file(file_id: int) -> dict:
    c = db.conn()
    f = c.execute("SELECT path, duration FROM files WHERE id=?", (file_id,)).fetchone()
    shots = c.execute("SELECT id, t_start, t_end FROM shots WHERE file_id=? AND active=1 ORDER BY t_start",
                      (file_id,)).fetchall()
    if f is None or not shots:
        return {"shots": 0, "with_text": 0}
    cap = cv2.VideoCapture(f["path"])
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {f['path']}")
    dur = f["duration"] or 1e9
    found = 0
    try:
        for s in shots:
            t = (s["t_start"] + min(s["t_end"], dur)) / 2.0
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            text = read_text(frame)
            found += bool(text)
            c.execute("""INSERT INTO provenance(shot_id, ocr_text, ocr_lang) VALUES(?,?, 'en')
                         ON CONFLICT(shot_id) DO UPDATE SET ocr_text=excluded.ocr_text, ocr_lang='en'""",
                      (s["id"], text or None))
        c.commit()
    finally:
        cap.release()
    return {"shots": len(shots), "with_text": found}


def run(target_id: int) -> dict:
    return ocr_file(target_id)


def enqueue_all() -> int:
    c = db.conn()
    n = 0
    for r in c.execute("SELECT id FROM files WHERE status='ok'").fetchall():
        n += jobs.enqueue("file", r["id"], jobs.STAGE_OCR, priority=8)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--enqueue-all", action="store_true")
    a = ap.parse_args()
    if a.enqueue_all:
        print("OCR jobs queued:", enqueue_all())
