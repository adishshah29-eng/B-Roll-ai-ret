"""Snapshot the index so a broken demo can be restored in seconds:   python -m eval.backup   (restore: python -m eval.backup --restore)"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA, BAK = ROOT / "data", ROOT / "data_backup"
FILES = ["emb.f32"] + [p.name for p in DATA.glob("*.npz")]
DIRS = ["thumbs", "hydrated"]


def backup():
    BAK.mkdir(exist_ok=True)
    src = sqlite3.connect(DATA / "index.db")                       # online-safe copy (handles the WAL)
    dst = sqlite3.connect(BAK / "index.db")
    src.backup(dst)
    src.close(), dst.close()
    for f in FILES:
        shutil.copy2(DATA / f, BAK / f)
    for d in DIRS:
        shutil.copytree(DATA / d, BAK / d, dirs_exist_ok=True)
    print("backed up to", BAK)


def restore():
    for f in ["index.db"] + FILES:
        shutil.copy2(BAK / f, DATA / f)
    for ext in ("-wal", "-shm"):
        (DATA / ("index.db" + ext)).unlink(missing_ok=True)
    for d in DIRS:
        shutil.copytree(BAK / d, DATA / d, dirs_exist_ok=True)
    print("restored from", BAK)


if __name__ == "__main__":
    restore() if "--restore" in sys.argv else backup()
