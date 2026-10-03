"""Live sourcing: turn the LLM's queries into fresh clips from Pixabay's API and add them to the library.

queries ─▶ Pixabay API, all at once (24 h cached, rate-limited) ─▶ per query keep the clips whose tags match it ─▶ drop clips we
already have ─▶ ONE batch: preview download + CLIP embedding + near-duplicate check ─▶ Tier-S library entries (title/tags/licence/
preview kept; the video is downloaded only when previewed or rendered) ─▶ snapshot refreshed.
Because they land in the normal library, TRUE, licences, CUTS and YOURS apply to them like to everything else.

Speed: embedding the previews is the slow part (CPU), so we embed fewer, better images: only clips whose tags/title share a word with
the query (a few untagged ones only when too few match), and each clip once even if several queries return it.
"""
from concurrent.futures import ThreadPoolExecutor

from .. import db, textutil
from ..sources import ingest
from ..sources.pixabay import Pixabay

PER_QUERY = 18          # clips kept from a spot's main query
PER_ALT = 8             # ...and from each alternative phrasing
MIN_PER_QUERY = 5       # if fewer clips match the query's words, top up with the most popular ones
MAX_QUERIES = 12
SEARCH_THREADS = 4
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
    if not qs:
        return {"added": 0, "queries": []}

    def one(q):
        try:
            return _pix.search(q, 1), None
        except Exception as e:
            return [], e

    with ThreadPoolExecutor(SEARCH_THREADS) as ex:              # network-bound: the API client rate-limits itself
        found = list(ex.map(one, qs))
    if progress:
        progress(0.3, f"{len(qs)} searches done")

    c = db.conn()
    chosen, stats = {}, []
    for i, (q, (items, err)) in enumerate(zip(qs, found)):
        if err:
            stats.append({"query": q, "found": 0, "new": 0, "error": f"{type(err).__name__}: {err}"})
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

        cap = PER_QUERY if i < n_main else PER_ALT
        ranked = sorted((it for it in items if it.source_id not in have), key=overlap, reverse=True)
        keep = [it for it in ranked if overlap(it) > 0][:cap]
        if len(keep) < MIN_PER_QUERY:
            keep += [it for it in ranked if it not in keep][:MIN_PER_QUERY - len(keep)]
        new = [it for it in keep if it.source_id not in chosen]
        for it in new:
            chosen[it.source_id] = it
        stats.append({"query": q, "found": len(items), "new": len(new)})

    added = 0
    if chosen:
        if progress:
            progress(0.5, f"embedding {len(chosen)} new clips")
        S = ingest._stock_matrix()
        added, S = ingest.process_items(list(chosen.values()), S, library_id)
    if library_id:
        db.bump_version()
    searcher.holder.refresh_if_stale()          # the new clips are searchable right now
    if progress:
        progress(1.0, "done")
    return {"added": added, "queries": stats}
