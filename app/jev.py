"""One place for every Jev call. Jev (TypeSafe, served through OpenRouter) is a decision model: it does not write text, it answers
typed questions about a `state` with calibrated probabilities. Three kinds of question:
  noul    yes/no            -> {"noul": P(yes)}
  choice  one of N options  -> {"choice": name, "confidence": c, "probabilities": {name: p}}
  score   ordered rubric    -> {"score": probability-weighted level index, "confidence": c, "probabilities": {...}}
All questions in one request are answered in parallel against the same state and cannot see each other's answers.
Text only: Jev never sees a picture, so the picture check stays with Gemini.
Docs: https://openrouter.ai/docs/guides/community/jev
"""
import os

import requests

URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"      # pinned: thresholds below were set against this release
TIMEOUT_S = 30


def key() -> str | None:
    return os.getenv("OPENROUTER_API_KEY") or None


def enabled() -> bool:
    return bool(key())


def model() -> str:
    return os.getenv("JEV_MODEL") or DEFAULT_MODEL


def redact(text) -> str:
    s = str(text)
    k = key()
    return s.replace(k, "<redacted>") if k else s


def decide(state: dict, questions: dict, session: requests.Session | None = None) -> dict:
    """POST one decision request; returns {question name: typed answer}. Raises on HTTP / network errors."""
    r = (session or requests).post(URL, timeout=TIMEOUT_S,
                                   headers={"Authorization": f"Bearer {key()}", "Content-Type": "application/json"},
                                   json={"model": model(), "state": state, "questions": questions})
    if r.status_code != 200:
        raise RuntimeError(f"Jev HTTP {r.status_code}: {redact(r.text[:200])}")
    return r.json().get("answers") or {}


def noul(answer: dict | None, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(answer["noul"])))
    except (KeyError, TypeError, ValueError):
        return default


def score01(answer: dict | None, levels: int, default: float = 0.0) -> float:
    """A score answer mapped onto 0-1 (level index 0 .. levels-1)."""
    try:
        return max(0.0, min(1.0, float(answer["score"]) / (levels - 1)))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return default


def choice(answer: dict | None, default: str = "") -> str:
    return str((answer or {}).get("choice") or default)
