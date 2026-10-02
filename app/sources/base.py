"""Shared plumbing for stock-footage connectors: rate limiting, 24 h API cache, retry/backoff, StockItem."""
import hashlib
import json
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .. import db
from ..config import USER_AGENT

CACHE_TTL_S = 24 * 3600          # Pixabay requires caching results for 24 h; also saves everyone's quota


@dataclass
class StockItem:
    source: str                  # pixabay | commons | archive
    source_id: str
    title: str
    tags: str = ""
    author: str = ""
    author_url: str = ""
    page_url: str = ""
    licence: str = ""
    licence_url: str = ""
    published_at: str | None = None     # ISO date (possibly year or year-month only) if known
    date_kind: str = "unknown"          # recorded | upload | unknown
    gps: tuple | None = None            # (lat, lon)
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    preview_url: str = ""
    renditions: dict = field(default_factory=dict)


class TokenBucket:
    """Thread-safe token bucket: `rate` tokens/second, burst up to `capacity`."""

    def __init__(self, rate: float, capacity: float):
        self.rate, self.capacity = rate, capacity
        self.tokens, self.t = capacity, time.monotonic()
        self.lock = threading.Lock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.t) * self.rate)
                self.t = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                wait = (1 - self.tokens) / self.rate
            time.sleep(wait)


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT
BUCKETS = {
    "pixabay": TokenBucket(1.4, 10),      # API limit is 100 req / 60 s → stay at ~84/min
    "commons": TokenBucket(2.0, 4),
    "archive": TokenBucket(1.0, 3),
    "download": TokenBucket(8.0, 16),
}


def _cache_key(url: str, params: dict) -> str:
    p = {k: v for k, v in sorted((params or {}).items()) if k != "key"}   # never key the cache on secrets
    return hashlib.sha1((url + json.dumps(p, sort_keys=True)).encode()).hexdigest()


def fetch_json(source: str, url: str, params: dict | None = None, use_cache=True, tries=5):
    c = db.conn()
    key = _cache_key(url, params or {})
    if use_cache:
        r = c.execute("SELECT body, fetched_at FROM api_cache WHERE key=?", (key,)).fetchone()
        if r and time.time() - r["fetched_at"] < CACHE_TTL_S:
            return json.loads(r["body"])
    delay = 1.0
    for attempt in range(tries):
        BUCKETS[source].acquire()
        try:
            resp = _session.get(url, params=params, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = float(resp.headers.get("Retry-After", delay))
                time.sleep(wait + random.random())          # backoff + jitter
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
            data = resp.json()
            if use_cache:
                c.execute("INSERT OR REPLACE INTO api_cache(key, body, fetched_at) VALUES(?,?,?)",
                          (key, json.dumps(data), time.time()))
                c.commit()
            return data
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(delay + random.random())
            delay = min(delay * 2, 30)
    raise RuntimeError(f"{source}: gave up after {tries} tries: {url}")


def head_status(url: str, tries=4, timeout=20) -> int:
    """HEAD with polite backoff. 429/5xx are retried and, if they persist, returned (never read as 'missing')."""
    delay, code = 1.0, 0
    for _ in range(tries):
        BUCKETS["download"].acquire()
        try:
            r = _session.head(url, timeout=timeout, allow_redirects=True)
            code = r.status_code
            if code == 429 or code >= 500:
                time.sleep(float(r.headers.get("Retry-After", delay)) + random.random())
                delay = min(delay * 2, 20)
                continue
            return code
        except requests.RequestException:
            time.sleep(delay)
            delay = min(delay * 2, 20)
    return code


def get_bytes(url: str, timeout=30) -> bytes:
    BUCKETS["download"].acquire()
    r = _session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def download(url: str, dest, max_bytes=300 << 20, timeout=60) -> int:
    """Stream to a temp file then atomically rename. Raises if larger than max_bytes."""
    dest = Path(dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    BUCKETS["download"].acquire()
    n = 0
    with _session.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        cl = int(r.headers.get("Content-Length", 0))
        if cl and cl > max_bytes:
            raise ValueError(f"too large: {cl / 1e6:.0f} MB")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                n += len(chunk)
                if n > max_bytes:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise ValueError("too large")
                f.write(chunk)
    tmp.replace(dest)
    return n


class Connector:
    name = ""
    max_pages = 3

    def search(self, query: str, page: int) -> list:       # -> list[StockItem]
        raise NotImplementedError
