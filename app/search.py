"""Search core: relevance → gate → dedupe → MMR → clusters (+labels, missing-variety, find-similar).

Funnel (bounded cost): one matmul over the snapshot → top 500 → gate → dedupe → MMR on ≤100 → cluster ≤ k.
Read path touches only the immutable Snapshot (no SQL in the hot loop except fetching ≤k display rows).
"""
import json
from collections import OrderedDict

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from . import db, models
from .config import (CANDIDATES_TOP, CLUSTER_DIST, DEDUPE_SIM, DEDUPE_WINDOW_S, DEFAULT_DIVERSITY,
                     DEFAULT_K, GATE_DELTA, MIN_SCORE)
from .indexer import tags
from .log import Timings
from .store import Snapshot, SnapshotHolder

MMR_POOL = 100
SIMILAR_PER_SOURCE = 2


class LRU:
    def __init__(self, n):
        self.n, self.d = n, OrderedDict()

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        while len(self.d) > self.n:
            self.d.popitem(last=False)

    def clear(self):
        self.d.clear()


# ---------- pure functions (unit-testable) ----------
def gate(scores: np.ndarray, min_score=MIN_SCORE, delta=GATE_DELTA) -> np.ndarray:
    """Boolean keep-mask: relevant = within `delta` of the best AND above an absolute floor."""
    if len(scores) == 0:
        return np.zeros(0, dtype=bool)
    return scores >= max(min_score, float(scores.max()) - delta)


def dedupe(order: np.ndarray, E: np.ndarray, key: np.ndarray, t0: np.ndarray,
           sim=DEDUPE_SIM, window=DEDUPE_WINDOW_S) -> list:
    """order: row indices sorted by descending relevance. Drop near-copies: same source, close in time, cos>sim."""
    kept = []
    for i in order:
        dup = False
        for j in kept:
            if key[i] == key[j] and abs(t0[i] - t0[j]) < window and float(E[i] @ E[j]) > sim:
                dup = True
                break
        if not dup:
            kept.append(int(i))
    return kept


def mmr(cand: list, rel: np.ndarray, E: np.ndarray, k: int, lam: float) -> list:
    """Maximal Marginal Relevance. rel is min-max normalised to [0,1] so λ is a meaningful dial."""
    if not cand:
        return []
    r = rel[cand].astype(np.float64)
    rng = r.max() - r.min()
    rn = (r - r.min()) / rng if rng > 1e-9 else np.ones_like(r)
    S = E[cand] @ E[cand].T
    chosen = [int(np.argmax(rn))]
    remaining = set(range(len(cand))) - set(chosen)
    while remaining and len(chosen) < k:
        best, best_v = None, -1e9
        for i in remaining:
            v = (1 - lam) * rn[i] - lam * max(S[i, j] for j in chosen)
            if v > best_v:
                best, best_v = i, v
        chosen.append(best)
        remaining.discard(best)
    return [cand[i] for i in chosen]


def cluster(picked: list, E: np.ndarray, dist=CLUSTER_DIST) -> list:
    """Group picked rows into variations. Returns list of lists (row indices)."""
    if len(picked) < 2:
        return [picked] if picked else []
    X = E[picked]
    lab = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                  distance_threshold=dist).fit_predict(X)
    groups = {}
    for p, l in zip(picked, lab):
        groups.setdefault(int(l), []).append(p)
    return list(groups.values())


def label_clusters(groups: list, E: np.ndarray) -> list:
    """Name each cluster by the closest B-roll vocabulary concept; keep labels unique across clusters."""
    V, words = tags.vocab()
    used, out = set(), []
    for g in groups:
        c = E[g].mean(axis=0)
        c /= max(np.linalg.norm(c), 1e-9)
        sims = V @ c
        for idx in np.argsort(-sims):
            if words[idx] not in used:
                used.add(words[idx])
                out.append(words[idx])
                break
        else:
            out.append("more shots")
    return out


# ---------- engine ----------
class Searcher:
    def __init__(self, holder: SnapshotHolder):
        self.holder = holder
        self.q_cache = LRU(1024)
        self.r_cache = LRU(256)
        self._ver = holder.get().version

    def warmup(self):
        """Pay one-time costs (sklearn import/JIT, text tower) at startup instead of on the first user query."""
        self.encode("warm up")
        rng = np.random.default_rng(0)
        X = rng.normal(size=(6, 512)).astype(np.float32)
        X /= np.linalg.norm(X, axis=1, keepdims=True)
        cluster(list(range(6)), X)

    def _sync(self):
        if self.holder.get().version != self._ver:
            self._ver = self.holder.get().version
            self.r_cache.clear()

    def encode(self, text: str) -> np.ndarray:
        e = self.q_cache.get(text)
        if e is None:
            e = models.embed_texts([text])[0]
            self.q_cache.put(text, e)
        return e

    def encode_many(self, texts: list) -> np.ndarray:
        missing = [t for t in texts if self.q_cache.get(t) is None]
        if missing:
            for t, e in zip(missing, models.embed_texts(missing)):
                self.q_cache.put(t, e)
        return np.stack([self.q_cache.get(t) for t in texts])

    @staticmethod
    def _mask(snap: Snapshot, filters: dict | None) -> np.ndarray:
        m = np.ones(len(snap), dtype=bool)
        f = filters or {}
        if f.get("size"):
            m &= np.isin(snap.size, f["size"])
        if f.get("motion"):
            m &= np.isin(snap.motion, f["motion"])
        if f.get("orientation"):
            m &= snap.orient == f["orientation"]
        if f.get("source"):
            m &= np.isin(snap.source, f["source"])
        return m

    def _relevant(self, snap: Snapshot, q: np.ndarray, mask: np.ndarray):
        """Return (rows sorted by relevance desc, scores array for all rows). Gate + dedupe applied."""
        if len(snap) == 0:
            return [], np.zeros(0)
        scores = snap.E @ q
        s = np.where(mask, scores, -1.0)
        top = np.argpartition(-s, min(CANDIDATES_TOP, len(s) - 1))[:CANDIDATES_TOP]
        top = top[np.argsort(-s[top])]
        top = top[s[top] > -1.0]
        if len(top) == 0:
            return [], scores
        keep = gate(scores[top])
        top = top[keep]
        key = np.where(snap.file_id >= 0, snap.file_id, 1_000_000 + snap.stock_id)
        return dedupe(top, snap.E, key, snap.t0), scores

    def candidates(self, text: str, k: int = 8, filters=None) -> list:
        """Planner input: relevance-gated, deduped, NOT clustered. Returns [(row, score)]."""
        snap = self.holder.get()
        q = self.encode(text)
        rows, scores = self._relevant(snap, q, self._mask(snap, filters))
        return [(r, float(scores[r])) for r in rows[:k]]

    def search(self, query: str, k=DEFAULT_K, diversity=DEFAULT_DIVERSITY, filters=None) -> dict:
        self._sync()
        ck = (query, json.dumps(filters or {}, sort_keys=True), k, round(diversity, 3), self._ver)
        hit = self.r_cache.get(ck)
        if hit is not None:
            return {**hit, "timings": {"cache": 0.1}, "cached": True}
        t = Timings()
        snap = self.holder.get()
        with t.stage("encode"):
            q = self.encode(query)
        with t.stage("retrieve"):
            rows, scores = self._relevant(snap, q, self._mask(snap, filters))
        with t.stage("mmr"):
            pool = rows[:MMR_POOL]
            picked = mmr(pool, scores, snap.E, k, diversity)
        with t.stage("cluster"):
            groups = cluster(picked, snap.E)
            groups.sort(key=lambda g: -max(scores[r] for r in g))
            for g in groups:
                g.sort(key=lambda r: -scores[r])
            labels = label_clusters(groups, snap.E) if groups else []
        missing = self._missing(snap, rows)
        with t.stage("db"):
            allrows = [r for g in groups for r in g]
            cards = shot_cards(snap, allrows, scores)
        out = {
            "clusters": [{"label": lab, "shots": [cards[r] for r in g]} for lab, g in zip(labels, groups)],
            "missing": missing, "n_relevant": len(rows), "took_ms": t.total(),
        }
        self.r_cache.put(ck, out)
        return {**out, "timings": dict(t)}

    @staticmethod
    def _missing(snap: Snapshot, rows: list) -> list:
        if not rows:
            return []
        present = set(snap.size[rows])
        names = {"wide": "wide", "medium": "medium", "close": "close-up"}
        return [f"no {names[s]} shots among the relevant results" for s in ("wide", "medium", "close")
                if s not in present and len(rows) >= 3]

    def similar(self, shot_id: int, k=12) -> dict:
        snap = self.holder.get()
        i = snap.index_of.get(int(shot_id))
        if i is None:
            return {"shots": []}
        scores = snap.E @ snap.E[i]
        order = np.argsort(-scores)
        order = [int(r) for r in order if r != i][:300]
        key = np.where(snap.file_id >= 0, snap.file_id, 1_000_000 + snap.stock_id)
        # near-copies of the query shot itself (same take) are not interesting
        order = [r for r in order if not (key[r] == key[i] and abs(snap.t0[r] - snap.t0[i]) < DEDUPE_WINDOW_S)]
        rows, per_src = [], {}
        for r in dedupe(np.array(order), snap.E, key, snap.t0):
            if per_src.get(key[r], 0) >= SIMILAR_PER_SOURCE:   # surface other takes, not one clip's neighbours
                continue
            per_src[key[r]] = per_src.get(key[r], 0) + 1
            rows.append(r)
            if len(rows) >= k:
                break
        cards = shot_cards(snap, rows, scores)
        return {"shots": [cards[r] for r in rows]}


def shot_cards(snap: Snapshot, rows: list, scores: np.ndarray) -> dict:
    """Fetch display fields for ≤k shots in a single query."""
    if not rows:
        return {}
    ids = [int(snap.ids[r]) for r in rows]
    q = ",".join("?" * len(ids))
    recs = {r["id"]: r for r in db.conn().execute(
        f"""SELECT s.id, s.file_id, s.stock_id, s.t_start, s.t_end, s.thumb, s.size_tag, s.motion,
                   s.orientation, s.weather, f.path, si.title, si.source, si.author, si.page_url,
                   p.shot_date, p.date_source
            FROM shots s LEFT JOIN files f ON f.id=s.file_id LEFT JOIN stock_items si ON si.id=s.stock_id
                 LEFT JOIN provenance p ON p.shot_id=s.id
            WHERE s.id IN ({q})""", ids)}
    out = {}
    for r in rows:
        sid = int(snap.ids[r])
        d = recs[sid]
        name = (d["path"].replace("\\", "/").rsplit("/", 1)[-1]) if d["path"] else (d["title"] or f"stock {d['stock_id']}")
        out[r] = {
            "id": sid, "file_id": d["file_id"], "stock_id": d["stock_id"], "file": name,
            "t_start": round(d["t_start"], 2), "t_end": round(d["t_end"], 2), "score": round(float(scores[r]), 3),
            "size": d["size_tag"], "motion": d["motion"], "orientation": d["orientation"], "weather": d["weather"],
            "source": d["source"] or "own", "author": d["author"], "page_url": d["page_url"],
            "date": (d["shot_date"] or "")[:10], "date_src": d["date_source"] or "unknown",
            "thumb": f"/media/thumb/{sid}",
        }
    return out


if __name__ == "__main__":
    import sys, time
    holder = SnapshotHolder()
    s = Searcher(holder)
    print(f"snapshot: {len(holder.get())} shots")
    for qtext in sys.argv[1:] or ["rain on the road", "सड़क पर बारिश", "people working on laptops"]:
        for rep in range(2):
            t0 = time.perf_counter()
            res = s.search(qtext)
            dt = (time.perf_counter() - t0) * 1000
        print(f"\n== {qtext!r}  ({dt:.1f} ms warm, relevant={res['n_relevant']}, timings={res['timings']})")
        for c in res["clusters"]:
            print(f"  [{c['label']}]")
            for sh in c["shots"][:3]:
                print(f"     {sh['score']:.3f} {sh['file']} {sh['t_start']}-{sh['t_end']}s {sh['size']}/{sh['motion']}")
        if res["missing"]:
            print("  missing:", res["missing"])
