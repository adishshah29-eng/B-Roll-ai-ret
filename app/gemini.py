"""One place for every Gemini call: model rotation, JSON parsing, and key redaction.

* Each model has its own rate limit, so calls rotate round-robin across every usable model instead of hammering one.
* A model that answers 429/5xx is put on a short cooldown and skipped; one that answers 404 ("no longer available to new
  users") is skipped for the rest of the session. If everything is cooling down we still try the one that frees up first.
* The API key travels in the URL, so any error text is run through `redact()` before it is stored, printed or shown.
"""
import itertools
import json
import os
import re
import threading
import time

import requests

CANDIDATES = ["gemini-flash-latest", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]
COOLDOWN_429 = 60.0          # rate limited: leave that model alone for a minute
COOLDOWN_BUSY = 15.0         # 5xx / overloaded: short pause
_KEY_IN_URL = re.compile(r"key=[^&\s\"'\\]+")
_state = {"model": None, "ok": None, "error": None, "at": 0.0}
_until: dict = {}            # model -> time.time() when it may be used again (inf = dead this session)
_ring = itertools.count()
_lock = threading.Lock()


def key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or None


def enabled() -> bool:
    return bool(key())


def redact(text) -> str:
    s = _KEY_IN_URL.sub("key=<redacted>", str(text))
    k = key()
    return s.replace(k, "<redacted>") if k else s


def _models() -> list:
    env = os.getenv("GEMINI_MODEL")
    return ([env] if env else []) + [m for m in CANDIDATES if m != env]


def _order() -> list:
    """Round-robin start, models in cooldown last (soonest-free first), dead models never."""
    now = time.time()
    with _lock:
        ms = [m for m in _models() if _until.get(m, 0) != float("inf")]
        if not ms:
            return []
        i = next(_ring) % len(ms)
        ms = ms[i:] + ms[:i]
    ready = [m for m in ms if _until.get(m, 0) <= now]
    cooling = sorted((m for m in ms if _until.get(m, 0) > now), key=lambda m: _until[m])
    return ready + cooling


def _cool(model: str, seconds: float):
    with _lock:
        _until[model] = time.time() + seconds if seconds != float("inf") else float("inf")


def generate_json(prompt: str, temperature: float = 0.3, timeout: int = 90, parts: list | None = None) -> dict:
    """Ask Gemini for a JSON object. `parts` (text and {"inline_data": {...}} items) replaces `prompt` for image requests.
    Raises RuntimeError with a REDACTED message on failure."""
    k = key()
    if not k:
        raise RuntimeError("no GEMINI_API_KEY")
    body = {"contents": [{"parts": parts or [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    last = "no model answered"
    for attempt in range(2):
        for model in _order():
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  params={"key": k}, json=body, timeout=timeout)
            except requests.RequestException as e:
                last = redact(f"{model}: request failed ({type(e).__name__})")
                _cool(model, COOLDOWN_BUSY)
                continue
            if r.status_code in (400, 404, 429, 500, 502, 503, 504):
                msg = ""
                try:
                    msg = r.json().get("error", {}).get("message", "")[:110]
                except Exception:
                    pass
                last = redact(f"{model}: HTTP {r.status_code} {msg}")
                _cool(model, float("inf") if r.status_code in (400, 404) else
                      COOLDOWN_429 if r.status_code == 429 else COOLDOWN_BUSY)
                continue
            if not r.ok:                                      # 401/403: the key itself is the problem
                _state.update(ok=False, error=redact(f"HTTP {r.status_code}: key rejected or not allowed ({model})"), at=time.time())
                raise RuntimeError(_state["error"])
            try:
                data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            except Exception:
                last = f"{model}: returned something that is not JSON"
                continue
            _state.update(model=model, ok=True, error=None, at=time.time())
            return data
        if attempt == 0:
            time.sleep(3)                                     # one pause, then every candidate once more
    _state.update(ok=False, error=redact(last), at=time.time())
    raise RuntimeError(redact(f"Gemini unavailable right now ({last})"))


def status() -> dict:
    """Which models are usable, cooling down or dead (for debugging / the UI)."""
    now = time.time()
    return {m: ("dead" if _until.get(m, 0) == float("inf") else f"cooling {int(_until[m] - now)}s" if _until.get(m, 0) > now else "ready")
            for m in _models()}


def check(max_age: int = 600) -> dict:
    """Cheap, cached health check for the UI: {'enabled','ok','model','error'}."""
    if not enabled():
        return {"enabled": False, "ok": False, "model": None, "error": None}
    age_limit = max_age if _state["ok"] else 30             # a failure may be a passing overload: look again soon
    if _state["ok"] is None or time.time() - _state["at"] > age_limit:
        try:
            generate_json('Reply with the JSON object {"ok": true}', temperature=0, timeout=30)
        except Exception as e:
            _state.update(ok=False, error=redact(e), at=time.time())
    return {"enabled": True, "ok": bool(_state["ok"]), "model": _state["model"], "error": _state["error"]}
