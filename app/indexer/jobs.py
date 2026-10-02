"""SQLite-backed job queue. Idempotent (UNIQUE target/stage/model_ver), crash-safe, prioritised."""
from pathlib import Path

from .. import db
from ..config import MODEL_VER, VIDEO_EXTS

STAGE_INDEX = "index"      # sample → segment → embed → tags → thumbs → basic provenance
STAGE_CUTFEAT = "cutfeat"  # P6
STAGE_OCR = "ocr"          # P5


def enqueue(kind: str, target_id: int, stage: str, priority: int = 5) -> bool:
    c = db.conn()
    cur = c.execute(
        "INSERT OR IGNORE INTO jobs(target_kind,target_id,stage,model_ver,priority) VALUES(?,?,?,?,?)",
        (kind, target_id, stage, MODEL_VER, priority))
    c.commit()
    return cur.rowcount > 0


def enqueue_folder(folder: str, library_id: int | None = None) -> dict:
    """Register every video under folder (idempotent) and enqueue an index job per new file."""
    c = db.conn()
    root = Path(folder)
    found = new = 0
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in VIDEO_EXTS or not p.is_file():
            continue
        found += 1
        path = str(p.resolve())
        c.execute("INSERT OR IGNORE INTO files(path,status) VALUES(?, 'pending')", (path,))
        if library_id:
            c.execute("UPDATE files SET library_id=? WHERE path=?", (library_id, path))
        fid = c.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()["id"]
        if enqueue("file", fid, STAGE_INDEX, priority=5):
            new += 1
    c.commit()
    return {"found": found, "new_jobs": new}


def reset_stale():
    """Jobs left 'running' by a crash go back to pending."""
    c = db.conn()
    c.execute("UPDATE jobs SET status='pending' WHERE status='running'")
    c.commit()


def claim():
    """Atomically take the highest-priority pending job."""
    c = db.conn()
    row = c.execute(
        "SELECT * FROM jobs WHERE status='pending' ORDER BY priority, id LIMIT 1").fetchone()
    if not row:
        return None
    cur = c.execute("UPDATE jobs SET status='running', attempts=attempts+1, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND status='pending'", (row["id"],))
    c.commit()
    return row if cur.rowcount else None


def complete(job_id: int):
    c = db.conn()
    c.execute("UPDATE jobs SET status='done', updated_at=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
    c.commit()


def fail(job_id: int, err: str, max_attempts: int = 2):
    c = db.conn()
    att = c.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()["attempts"]
    status = "failed" if att >= max_attempts else "pending"
    c.execute("UPDATE jobs SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
              (status, err[:500], job_id))
    c.commit()


def status() -> dict:
    c = db.conn()
    rows = c.execute("SELECT stage, status, COUNT(*) n FROM jobs GROUP BY stage, status").fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["stage"], {})[r["status"]] = r["n"]
    return out
