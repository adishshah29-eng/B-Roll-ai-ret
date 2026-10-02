"""Lazy model singletons. Load once, reuse. Indexer uses `clip` (images + EN text);
the API uses `mtext` (multilingual text, same 512-d space) so it never loads the image tower."""
import threading

import numpy as np

from .config import CLIP_MODEL, MULTI_TEXT_MODEL

_lock = threading.Lock()
_models = {}


def _load(name):
    with _lock:
        if name not in _models:
            from sentence_transformers import SentenceTransformer
            _models[name] = SentenceTransformer(name, device="cpu")
        return _models[name]


def clip():
    return _load(CLIP_MODEL)


def mtext():
    return _load(MULTI_TEXT_MODEL)


def _norm(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.maximum(n, 1e-9)


def embed_images(images, batch_size=16) -> np.ndarray:
    """images: list of PIL.Image. Returns L2-normalised (N, 512) float32."""
    if not images:
        return np.zeros((0, 512), dtype=np.float32)
    e = clip().encode(images, batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
    return _norm(e)


def embed_texts(texts, multilingual=True, batch_size=32) -> np.ndarray:
    """texts: list[str]. Multilingual tower handles Hindi + English; clip tower is English-only."""
    m = mtext() if multilingual else clip()
    e = m.encode(list(texts), batch_size=batch_size, convert_to_numpy=True, show_progress_bar=False)
    return _norm(e)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        en = embed_texts(["rain on the road"])[0]
        hi = embed_texts(["सड़क पर बारिश"])[0]
        en_clip = embed_texts(["rain on the road"], multilingual=False)[0]
        print("cos(HI, EN)        =", round(float(en @ hi), 3))
        print("cos(multi, clip EN)=", round(float(en @ en_clip), 3))
