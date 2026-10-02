"""SQLite (WAL) connection helper + schema. One connection per thread."""
import sqlite3
import threading

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS stock_items(
  id INTEGER PRIMARY KEY, source TEXT, source_id TEXT, title TEXT, tags TEXT,
  author TEXT, author_url TEXT, page_url TEXT, licence TEXT, licence_url TEXT,
  published_at TEXT, gps_lat REAL, gps_lon REAL, duration REAL, width INT, height INT,
  preview_urls TEXT, renditions TEXT, fetched_at TEXT, tier TEXT DEFAULT 'S',
  UNIQUE(source, source_id));
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, content_hash TEXT, duration REAL, fps REAL,
  width INT, height INT, rotation INT DEFAULT 0, created_at TEXT, gps_lat REAL, gps_lon REAL,
  status TEXT DEFAULT 'ok', tier TEXT DEFAULT 'L', stock_id INT);
CREATE TABLE IF NOT EXISTS shots(
  id INTEGER PRIMARY KEY, file_id INT, stock_id INT, t_start REAL, t_end REAL, thumb TEXT,
  emb_row INT, size_tag TEXT, motion TEXT, motion_score REAL, orientation TEXT,
  weather TEXT, daypart TEXT, season TEXT, quality REAL, active INT DEFAULT 1);
CREATE TABLE IF NOT EXISTS provenance(
  shot_id INTEGER PRIMARY KEY, shot_date TEXT, date_source TEXT, gps_lat REAL, gps_lon REAL,
  ocr_text TEXT, ocr_lang TEXT, place_guess TEXT, place_src TEXT, place_conf REAL, source_kind TEXT);
CREATE TABLE IF NOT EXISTS cut_features(
  shot_id INTEGER PRIMARY KEY, head_dx REAL, head_dy REAL, tail_dx REAL, tail_dy REAL,
  head_luma REAL, tail_luma REAL, head_warmth REAL, tail_warmth REAL,
  sal_x REAL, sal_y REAL, peak_t REAL, approx INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS jobs(
  id INTEGER PRIMARY KEY, target_kind TEXT, target_id INT, stage TEXT, model_ver TEXT,
  priority INT DEFAULT 5, status TEXT DEFAULT 'pending', attempts INT DEFAULT 0,
  last_error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(target_kind, target_id, stage, model_ver));
CREATE TABLE IF NOT EXISTS ingest_cursors(
  source TEXT, query TEXT, page INT, done INT DEFAULT 0, PRIMARY KEY(source, query, page));
CREATE TABLE IF NOT EXISTS api_cache(key TEXT PRIMARY KEY, body TEXT, fetched_at REAL);
CREATE TABLE IF NOT EXISTS memory_pairs(
  id INTEGER PRIMARY KEY, project TEXT, text TEXT, shot_id INT, label INT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS usage(shot_id INT, project TEXT, used_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_shots_file ON shots(file_id);
CREATE INDEX IF NOT EXISTS ix_shots_stock ON shots(stock_id);
CREATE INDEX IF NOT EXISTS ix_shots_tags ON shots(size_tag, motion, orientation);
CREATE INDEX IF NOT EXISTS ix_jobs_q ON jobs(status, priority);
"""

_local = threading.local()


def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        for ddl in ("ALTER TABLE stock_items ADD COLUMN date_kind TEXT",
                    "ALTER TABLE shots ADD COLUMN weather_conf REAL"):   # lightweight migrations
            try:
                c.execute(ddl)
            except sqlite3.OperationalError:
                pass
        _local.c = c
    return c


def get_version() -> int:
    r = conn().execute("SELECT value FROM meta WHERE key='index_version'").fetchone()
    return int(r["value"]) if r else 0


def bump_version() -> int:
    v = get_version() + 1
    conn().execute("INSERT OR REPLACE INTO meta(key,value) VALUES('index_version',?)", (str(v),))
    conn().commit()
    return v
