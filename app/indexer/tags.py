"""Zero-shot tags from CLIP embeddings + cheap motion level. Prompt/vocab embeddings are cached on disk
so the API process never has to load the image/EN text tower."""
import numpy as np
import yaml

from .. import models
from ..config import (DATA, MODEL_VER, MOTION_ACTION, MOTION_STILL, RESOURCES)

_PROMPT_CACHE = DATA / f"prompt_emb_{MODEL_VER}.npz"
_VOCAB_CACHE = DATA / f"vocab_emb_{MODEL_VER}.npz"
_mem = {}


def _prompts() -> dict:
    return yaml.safe_load(open(RESOURCES / "prompts.yaml", encoding="utf-8"))


def _build_prompt_cache():
    P = _prompts()
    texts, keys = [], []
    for group, labels in P.items():
        for label, plist in labels.items():
            for p in plist:
                texts.append(p)
                keys.append(f"{group}|{label}")
    E = models.embed_texts(texts, multilingual=False)
    np.savez(_PROMPT_CACHE, E=E, keys=np.array(keys))


def _build_vocab_cache():
    lines = [l.strip() for l in open(RESOURCES / "vocab.txt", encoding="utf-8") if l.strip()]
    E = models.embed_texts(lines, multilingual=False)
    np.savez(_VOCAB_CACHE, E=E, words=np.array(lines))


def ensure_caches():
    if not _PROMPT_CACHE.exists():
        _build_prompt_cache()
    if not _VOCAB_CACHE.exists():
        _build_vocab_cache()


def _groups():
    if "groups" not in _mem:
        ensure_caches()
        z = np.load(_PROMPT_CACHE)
        E, keys = z["E"], [str(k) for k in z["keys"]]
        groups = {}
        for i, k in enumerate(keys):
            g, l = k.split("|")
            groups.setdefault(g, {}).setdefault(l, []).append(i)
        _mem["groups"] = {g: {l: E[idx] for l, idx in d.items()} for g, d in groups.items()}
    return _mem["groups"]


def vocab():
    if "vocab" not in _mem:
        ensure_caches()
        z = np.load(_VOCAB_CACHE)
        _mem["vocab"] = (z["E"], [str(w) for w in z["words"]])
    return _mem["vocab"]


def zero_shot(emb: np.ndarray, group: str, temp=100.0):
    """emb: (512,) or (N,512) normalised. Returns (label(s), confidence(s)). Per label = max over its prompts."""
    g = _groups()[group]
    labels = list(g)
    single = emb.ndim == 1
    X = emb[None] if single else emb
    sims = np.stack([(X @ g[l].T).max(axis=1) for l in labels], axis=1)  # (N, L)
    z = sims * temp
    z = z - z.max(axis=1, keepdims=True)
    p = np.exp(z)
    p /= p.sum(axis=1, keepdims=True)
    best = p.argmax(axis=1)
    out_l = [labels[i] for i in best]
    out_c = [float(p[n, i]) for n, i in enumerate(best)]
    return (out_l[0], out_c[0]) if single else (out_l, out_c)


def motion_level(greys) -> tuple[float, str]:
    """greys: list of 36x64 uint8 frames inside one shot. Mean abs diff between consecutive samples."""
    if len(greys) < 2:
        return 0.0, "still"
    d = [float(np.mean(np.abs(greys[i + 1].astype(np.int16) - greys[i].astype(np.int16))))
         for i in range(len(greys) - 1)]
    s = float(np.mean(d))
    return s, ("still" if s < MOTION_STILL else "moderate" if s < MOTION_ACTION else "action")


def orientation(w: int, h: int) -> str:
    if w > h * 1.1:
        return "16:9"
    if h > w * 1.1:
        return "9:16"
    return "1:1"


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv:
        ensure_caches()
        print("caches built:", _PROMPT_CACHE.name, _VOCAB_CACHE.name)
