"""Embedding store + immutable Snapshot for the read path.

Write path (indexer): append rows to a raw float32 file, insert shots rows, bump index_version.
Read path (API): Snapshot = (E matrix, shot ids, tag arrays) built once per version and swapped atomically.
"""
import threading
from dataclasses import dataclass

import numpy as np

from . import db, licence
from .config import EMB_DIM, EMB_PATH

_append_lock = threading.Lock()


def row_count() -> int:
    return EMB_PATH.stat().st_size // (EMB_DIM * 4) if EMB_PATH.exists() else 0


def append(embs: np.ndarray) -> int:
    """Append (n, EMB_DIM) float32 rows; returns the first new row index."""
    embs = np.ascontiguousarray(embs, dtype=np.float32)
    assert embs.ndim == 2 and embs.shape[1] == EMB_DIM
    with _append_lock:
        start = row_count()
        with open(EMB_PATH, "ab") as f:
            f.write(embs.tobytes())
            f.flush()
        return start


def load_matrix() -> np.ndarray:
    n = row_count()
    if n == 0:
        return np.zeros((0, EMB_DIM), dtype=np.float32)
    return np.fromfile(EMB_PATH, dtype=np.float32, count=n * EMB_DIM).reshape(n, EMB_DIM)


@dataclass(frozen=True)
class Snapshot:
    version: int
    E: np.ndarray            # (N, 512) normalised embeddings of ACTIVE shots only
    ids: np.ndarray          # (N,) shot ids, aligned with E
    file_id: np.ndarray      # (N,) file id or -1
    stock_id: np.ndarray     # (N,) stock id or -1
    t0: np.ndarray
    t1: np.ndarray
    size: np.ndarray         # (N,) '<U12'
    motion: np.ndarray
    orient: np.ndarray
    source: np.ndarray       # 'own' | 'stock' | 'archive' | ...
    lic: np.ndarray          # licence class: own | safe | attribution | caution | restricted | unknown
    lib: np.ndarray          # library id (0 = not in any library)
    index_of: dict           # shot id -> row in E

    def __len__(self):
        return len(self.ids)


def build_snapshot() -> Snapshot:
    c = db.conn()
    ver = db.get_version()
    rows = c.execute(
        """SELECT s.id, s.file_id, s.stock_id, s.t_start, s.t_end, s.emb_row,
                  s.size_tag, s.motion, s.orientation, si.source AS src, si.licence AS lic_text, si.licence_url AS lic_url,
                  COALESCE(f.library_id, si.library_id, 0) AS lib
           FROM shots s
           LEFT JOIN stock_items si ON si.id = s.stock_id
           LEFT JOIN files f ON f.id = s.file_id
           WHERE s.active=1 AND s.emb_row IS NOT NULL ORDER BY s.id"""
    ).fetchall()
    M = load_matrix()
    if not rows:
        z = np.zeros(0)
        return Snapshot(ver, np.zeros((0, EMB_DIM), np.float32), z.astype(int), z.astype(int), z.astype(int),
                        z, z, z.astype("U1"), z.astype("U1"), z.astype("U1"), z.astype("U1"), z.astype("U1"), z.astype(int), {})
    emb_rows = np.array([r["emb_row"] for r in rows])
    valid = emb_rows < len(M)
    rows = [r for r, v in zip(rows, valid) if v]
    emb_rows = emb_rows[valid]
    ids = np.array([r["id"] for r in rows])
    return Snapshot(
        version=ver,
        E=np.ascontiguousarray(M[emb_rows]),
        ids=ids,
        file_id=np.array([r["file_id"] if r["file_id"] is not None else -1 for r in rows]),
        stock_id=np.array([r["stock_id"] if r["stock_id"] is not None else -1 for r in rows]),
        t0=np.array([r["t_start"] for r in rows], dtype=float),
        t1=np.array([r["t_end"] for r in rows], dtype=float),
        size=np.array([r["size_tag"] or "unknown" for r in rows]),
        motion=np.array([r["motion"] or "unknown" for r in rows]),
        orient=np.array([r["orientation"] or "unknown" for r in rows]),
        source=np.array([r["src"] or "own" for r in rows]),
        lic=np.array([licence.classify(r["lic_text"], r["lic_url"], r["src"]) for r in rows]),
        lib=np.array([r["lib"] for r in rows], dtype=int),
        index_of={int(i): k for k, i in enumerate(ids)},
    )


class SnapshotHolder:
    """Atomic swap: readers grab `.get()` (a single reference read); a poller replaces it."""

    def __init__(self):
        self._snap = build_snapshot()

    def get(self) -> Snapshot:
        return self._snap

    def refresh_if_stale(self) -> bool:
        if db.get_version() != self._snap.version:
            self._snap = build_snapshot()
            return True
        return False
