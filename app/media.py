"""Video helpers on OpenCV (no ffmpeg on this machine) + a tiny MP4 atom reader for date/GPS."""
import hashlib
import re
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import THUMB_W

_MAC_EPOCH = datetime(1904, 1, 1, tzinfo=timezone.utc)


# ---------- MP4 metadata (creation time, GPS) ----------
def _iter_atoms(f, start, end):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(8)
        if len(hdr) < 8:
            return
        size, typ = struct.unpack(">I4s", hdr)
        hdr_len = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            hdr_len = 16
        elif size == 0:
            size = end - pos
        if size < hdr_len:
            return
        yield typ, pos + hdr_len, pos + size
        pos += size


def mp4_meta(path) -> dict:
    """Returns {'created': iso|None, 'lat': float|None, 'lon': float|None}. Never raises."""
    out = {"created": None, "lat": None, "lon": None}
    try:
        size = Path(path).stat().st_size
        with open(path, "rb") as f:
            for typ, s, e in _iter_atoms(f, 0, size):
                if typ != b"moov":
                    continue
                for t2, s2, e2 in _iter_atoms(f, s, e):
                    if t2 == b"mvhd":
                        f.seek(s2)
                        ver = f.read(1)[0]
                        f.read(3)
                        ct = struct.unpack(">I" if ver == 0 else ">Q", f.read(4 if ver == 0 else 8))[0]
                        if ct > 0:
                            dt = _MAC_EPOCH + timedelta(seconds=ct)
                            if 1990 < dt.year <= datetime.now().year + 1:
                                out["created"] = dt.isoformat()
                    elif t2 == b"udta":
                        for t3, s3, e3 in _iter_atoms(f, s2, e2):
                            if t3 == b"\xa9xyz":
                                f.seek(s3)
                                raw = f.read(min(e3 - s3, 64)).decode("latin-1", "ignore")
                                m = re.search(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", raw)
                                if m:
                                    out["lat"], out["lon"] = float(m.group(1)), float(m.group(2))
                break
    except Exception:
        pass
    return out


def content_hash(path) -> str:
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(p, "rb") as f:
        h.update(f.read(1 << 20))
        if size > (2 << 20):
            f.seek(size - (1 << 20))
            h.update(f.read(1 << 20))
    return h.hexdigest()


# ---------- decoding ----------
def probe(path) -> dict | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    if w == 0 or h == 0:
        return None
    return {"fps": float(fps), "duration": float(n / fps) if fps else 0.0, "width": w, "height": h}


def sample_frames(path, every_s=1.0, max_side=224):
    """Yield (t_seconds, rgb_small (PIL), grey64 (np 36x64)) every `every_s`.
    Sequential read + grab() skipping avoids slow seeking on long files."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps * every_s)))
    i = 0
    try:
        while True:
            ok = cap.grab()
            if not ok:
                break
            if i % step == 0:
                ok, frame = cap.retrieve()
                if not ok:
                    break
                h, w = frame.shape[:2]
                s = max_side / min(h, w)
                small = cv2.resize(frame, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                grey = cv2.cvtColor(cv2.resize(frame, (64, 36), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                yield i / fps, Image.fromarray(rgb), grey
            i += 1
    finally:
        cap.release()


def save_thumb(img: Image.Image, dest: Path, width=THUMB_W):
    w, h = img.size
    img = img.resize((width, max(1, int(h * width / w))))
    img.save(dest, "JPEG", quality=80)
