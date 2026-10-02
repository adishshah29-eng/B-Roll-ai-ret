"""Live sourcing: turn the LLM's queries into fresh clips from Pixabay's API and add them to the library.

query ─▶ Pixabay API (24 h cached, rate-limited) ─▶ drop clips we already have / near-duplicates ─▶ embed the preview frames ─▶
Tier-S library entries (title/tags/licence/preview kept; the video is downloaded only when previewed or rendered) ─▶ snapshot refreshed.
Because they land in the normal library, TRUE, licences, CUTS and YOURS apply to them like to everything else.
"""
from .. import db
from ..sources import ingest
from ..sources.pixabay import Pixabay

PER_QUERY = 25
MAX_QUERIES = 10
_pix = Pixabay()


def fetch(queries: list, searcher, progress=None) -> dict:
    qs = []
    for q in queries:
        q = (q or "").strip()
        if q and q.lower() not in [x.lower() for x in qs]:
            qs.append(q)
    qs = qs[:MAX_QUERIES]
    c = db.conn()
    S = ingest._stock_matrix()
    stats, added = [], 0
    for i, q in enumerate(qs):
        try:
            items = _pix.search(q, 1)
        except Exception as e:
            stats.append({"query": q, "found": 0, "new": 0, "error": f"{type(e).__name__}: {e}"})
            continue
        have = ingest._existing(c, "pixabay", [it.source_id for it in items])
        fresh = [it for it in items if it.source_id not in have][:PER_QUERY]
        n = 0
        if fresh:
            n, S = ingest.process_items(fresh, S)
        added += n
        stats.append({"query": q, "found": len(items), "new": n})
        if progress:
            progress((i + 1) / max(len(qs), 1), q)
    searcher.holder.refresh_if_stale()          # the new clips are searchable right now
    return {"added": added, "queries": stats}
