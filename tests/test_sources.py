"""Source plumbing tests: no network, no models."""
import time

from app.sources import ingest
from app.sources.base import TokenBucket, _cache_key
from app.sources.commons import parse_date


def test_parse_date_formats():
    assert parse_date("29 April 2020 at 1:16 pm") == "2020-04-29"
    assert parse_date("2021-05-27 15:15:16") == "2021-05-27"
    assert parse_date("<b>April 2020</b>") == "2020-04"
    assert parse_date("1962") == "1962"
    assert parse_date("c. 1906") == "1906"
    assert parse_date("garbage") is None and parse_date(None) is None and parse_date("") is None


def test_cache_key_ignores_api_key_and_param_order():
    a = _cache_key("http://x", {"q": "rain", "key": "SECRET1", "page": 1})
    b = _cache_key("http://x", {"page": 1, "key": "OTHER", "q": "rain"})
    assert a == b                                  # secrets never influence (or leak into) the cache key
    assert a != _cache_key("http://x", {"q": "rain", "page": 2})


def test_token_bucket_limits_rate():
    tb = TokenBucket(rate=20, capacity=2)
    t0 = time.monotonic()
    for _ in range(6):
        tb.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.15                         # 2 burst tokens, then 4 more at 20/s ≈ 0.2 s


def test_task_order_is_round_robin_across_sources_and_pages():
    qs = {"pixabay": ["a", "b"], "commons": ["c"]}
    order = list(ingest._tasks(["pixabay", "commons"], qs))
    firsts = [(s, q, p) for s, q, p in order[:4]]
    assert firsts[0][0] == "pixabay" and firsts[1][0] == "commons"      # sources interleave
    assert all(p == 1 for _, _, p in order[:3])                          # page 1 of everything before page 2
    assert len(order) == len(set(order))                                  # no duplicate tasks
    assert max(p for s, _, p in order if s == "pixabay") == ingest.CONNECTORS["pixabay"].max_pages
    assert max(p for s, _, p in order if s == "commons") == ingest.CONNECTORS["commons"].max_pages
