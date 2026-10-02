"""Live sourcing: turn the LLM's queries into fresh clips from Pixabay's API and add them to the library.

query ─▶ Pixabay API (24 h cached, rate-limited) ─▶ drop clips we already have / near-duplicates ─▶ embed the preview frames ─▶
Tier-S library entries (title/tags/licence/preview kept; the video is downloaded only when previewed or rendered) ─▶ snapshot refreshed.
Because they land in the normal library, TRUE, licences, CUTS and YOURS apply to them like to everything else.
"""
from .. import db, textutil
from ..sources import ingest
from ..sources.pixabay import Pixabay

PER_QUERY = 25          # clips kept from a spot's main query
PER_ALT = 12            # ...and from each alternative phrasing
MAX_QUERIES = 12
_pix = Pixabay()


def fetch(queries: list, searcher, progress=None, library_id: int | None = None, n_main: int | None = None) -> dict:
    """`queries` = main queries first, then alternatives; the first `n_main` get PER_QUERY clips, the rest PER_ALT."""
    qs = []
    for q in queries:
        q = (q or "").strip()
        if q and q.lower() not in [x.lower() for x in qs]:
            qs.append(q)
    qs = qs[:MAX_QUERIES]
    n_main = len(qs) if n_main is None else n_main
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
        if library_id and have:                    # clips we already had join the library too (they matched its query)
            ph = ",".join("?" * len(have))
            c.execute(f"UPDATE stock_items SET library_id=? WHERE source='pixabay' AND library_id IS NULL AND source_id IN ({ph})", [library_id, *have])
            c.commit()
        want = textutil.tokens(q)
        def overlap(it, want=want):                 # Pixabay orders by popularity: prefer the clips whose tags match the query
            hay = set(textutil.tokens(f"{it.title} {it.tags}"))
            return sum(1 for t in want if t in hay) / max(len(want), 1)
        fresh = sorted((it for it in items if it.source_id not in have), key=overlap, reverse=True)[:PER_QUERY if i < n_main else PER_ALT]
        n = 0
        if fresh:
            n, S = ingest.process_items(fresh, S, library_id)
        added += n
        stats.append({"query": q, "found": len(items), "new": n})
        if progress:
            progress((i + 1) / max(len(qs), 1), q)
    if library_id:
        db.bump_version()
    searcher.holder.refresh_if_stale()          # the new clips are searchable right now
    return {"added": added, "queries": stats}
