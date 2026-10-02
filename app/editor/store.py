"""Editor projects on disk: data/projects/<id>/{source.*, work.mp4, transcript.json, project.json}."""
import json
import threading
import time
import uuid
from pathlib import Path

from ..config import DATA

ROOT = DATA / "projects"
ROOT.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()
STATUS = {}          # id -> {"stage": str, "progress": float, "error": str|None}


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def folder(pid: str) -> Path:
    if not pid or any(c in pid for c in "/\\.."):
        raise ValueError("bad project id")
    return ROOT / pid


def load(pid: str) -> dict:
    p = folder(pid) / "project.json"
    if not p.exists():
        raise FileNotFoundError(pid)
    return json.loads(p.read_text(encoding="utf-8"))


def save(pid: str, data: dict):
    with _lock:
        tmp = folder(pid) / "project.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(folder(pid) / "project.json")


def set_status(pid: str, stage: str, progress: float = 0.0, error: str | None = None):
    STATUS[pid] = {"stage": stage, "progress": round(progress, 2), "error": error}


def status(pid: str) -> dict:
    if pid in STATUS:
        return STATUS[pid]
    try:
        return {"stage": load(pid).get("stage", "unknown"), "progress": 1.0, "error": None}
    except FileNotFoundError:
        return {"stage": "missing", "progress": 0.0, "error": "no such project"}


def listing() -> list:
    out = []
    for d in sorted(ROOT.iterdir(), reverse=True):
        try:
            p = load(d.name)
            out.append({"id": d.name, "name": p.get("name"), "duration": p.get("duration"), "stage": p.get("stage")})
        except Exception:
            continue
    return out[:30]
