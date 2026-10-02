"""All paths and tunables live here. Tune in one place."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA = ROOT / "data"
THUMBS = DATA / "thumbs"
PREVIEWS = DATA / "previews"
HYDRATED = DATA / "hydrated"
CACHE = DATA / "cache"
RESOURCES = ROOT / "resources"
FOOTAGE = ROOT / "footage"
DB_PATH = DATA / "index.db"
EMB_PATH = DATA / "emb.f32"   # raw float32 rows (EMB_DIM each), append-only

for _p in (DATA, THUMBS, PREVIEWS, HYDRATED, CACHE):
    _p.mkdir(parents=True, exist_ok=True)

# models
CLIP_MODEL = "clip-ViT-B-32"
MULTI_TEXT_MODEL = "clip-ViT-B-32-multilingual-v1"
EMB_DIM = 512
MODEL_VER = "clipb32-v1"

# indexing
SAMPLE_EVERY_S = 1.0
WINDOW_S = 4.0
CUT_SIM = 0.82
EMBED_BATCH = 16
THUMB_W = 320
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}

# search
CANDIDATES_TOP = 500
MIN_SCORE = 0.18
GATE_DELTA = 0.04   # tuned 2026-10-02: 0.04 → P=0.68 R=0.75 (0.08 gave P=0.39)
DEDUPE_SIM = 0.93
DEDUPE_WINDOW_S = 10.0
CLUSTER_DIST = 0.35
DEFAULT_K = 24
DEFAULT_DIVERSITY = 0.3

# motion level thresholds (mean abs grey diff between consecutive samples)
MOTION_STILL = 4.0
MOTION_ACTION = 12.0

PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
USER_AGENT = "EpochBroll/0.1 (hackathon research; contact parmarrproperties@gmail.com)"
