"""Niche presets (resources/niches.yaml): a style direction blended into the query embedding."""
import numpy as np
import yaml

from . import models
from .config import RESOURCES

NICHE_WEIGHT = 0.30          # how far the query is pulled toward the niche direction (0 = ignore)
_hints = {}


def _load():
    return yaml.safe_load(open(RESOURCES / "niches.yaml", encoding="utf-8"))


def listing() -> list:
    return [{"id": k, "label": v["label"]} for k, v in _load().items()]


def bias(niche: str | None):
    """Unit vector for the niche, or None for an unknown / empty niche."""
    if not niche:
        return None
    if niche not in _hints:
        spec = _load().get(niche)
        if spec is None:
            return None
        _hints[niche] = models.embed_texts([spec["hint"]])[0]
    return _hints[niche]


def blend(q: np.ndarray, niche: str | None) -> np.ndarray:
    b = bias(niche)
    if b is None:
        return q
    v = q + NICHE_WEIGHT * b
    return (v / max(float(np.linalg.norm(v)), 1e-9)).astype(np.float32)
