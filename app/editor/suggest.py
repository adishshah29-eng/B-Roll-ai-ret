"""Clip suggestions that fit THIS video, not just the words of one sentence.

1. Queries are grounded in the video: the spot's own query and alternatives, the spoken line, and each of those combined with the
   video's topic words (taken from the project summary and the place names in the script), so "market" in a Rajasthan video
   searches "market jaipur rajasthan travel" instead of any market anywhere.
2. Candidates come from the project's library (plus the clips fetched for this project), best score first, one per video.
3. Gemini then LOOKS at the pictures against the line and the video's topic (one call, up to 30 thumbnails) and marks which fit.
   Pictures that do not fit are flagged (the editor hides them behind "less relevant"), never silently deleted.
Without a Gemini key, or if it fails, the list is returned ordered by score and nothing is flagged.
"""
import base64
import time

from .. import gemini, truth
from . import judge, llm, store

MAX_CANDIDATES = 30
_cache: dict = {}            # (pid, line, ids) -> (time, {id: rank}) so reopening a tab does not re-ask Gemini
CACHE_S = 600


FILLER = {"introduction", "intro", "brief", "video", "explains", "explaining", "showcasing", "showcase", "journey", "week", "long",
          "vibrant", "filled", "known", "about", "overview", "guide", "tour", "speaker", "creator", "highlighting", "emphasizing",
          "discusses", "describes", "teaser", "vlog", "channel", "viewers", "popular", "famous", "various", "different"}


def video_places(proj: dict) -> list:
    """Places named anywhere in the video's speech or script, in order of first mention."""
    text = " ".join(s.get("text", "") for s in proj.get("segments", [])) + " " + (proj.get("script") or "")
    out = []
    for n, _ in truth.match_places(text):
        if n not in out:
            out.append(n)
    return out


def topic_words(proj: dict) -> str:
    """A few words describing what the whole video is about: summary keywords + places named anywhere in the script."""
    summary = (proj.get("llm") or {}).get("summary") or ""
    kws = [w for w in llm.keywords(summary, n=8).split() if w.lower() not in FILLER]
    out = []
    for w in video_places(proj)[:3] + kws:
        if w.lower() not in [o.lower() for o in out]:
            out.append(w)
    return " ".join(out[:5])


def scope(proj: dict):
    if proj.get("library"):
        return {"library": proj["library"]}
    if proj.get("live_library"):
        return {"also_lib": proj["live_library"]}
    return None


def queries(proj: dict, text: str, query: str, alts: list) -> list:
    topic = topic_words(proj)
    base = [q for q in [query, *(alts or []), text] if q and q.strip()]
    out = []
    for q in base:
        out.append(q.strip())
        if topic:
            out.append(f"{llm.keywords(q, n=4) or q} {topic}")       # same idea, pinned to the video's topic
    seen, res = set(), []
    for q in out:
        if q.lower() not in seen:
            seen.add(q.lower())
            res.append(q[:140])
    return res[:5]


def wrong_place(clip: dict, vplaces: list) -> str | None:
    """The clip's title/file name names a known place that is unrelated to every place in the video: return that place."""
    if not vplaces:
        return None
    cp = [n for n, _ in truth.match_places(f"{clip.get('title') or ''} {clip.get('file') or ''}")]
    if cp and not any(truth.related(a, b) for a in cp for b in vplaces):
        return cp[0]
    return None


def candidates(searcher, proj: dict, qs: list, k: int) -> list:
    flt = scope(proj)
    best = {}
    for q in qs:
        try:
            r = searcher.search(q, k=min(60, k), diversity=0.3, filters=flt)
        except Exception:
            continue
        for c in r.get("clusters", []):
            for x in c.get("shots", []):
                if x["id"] not in best or best[x["id"]]["score"] < x["score"]:
                    best[x["id"]] = x
    seen_vid, per_src = set(), {}
    for x in sorted(best.values(), key=lambda x: -x["score"]):
        key = ("s", x["stock_id"]) if x.get("stock_id") is not None else ("f", x.get("file_id"), x["id"] if x.get("file_id") is None else 0)
        if key in seen_vid:                                  # one entry per video
            continue
        seen_vid.add(key)
        per_src.setdefault(x.get("source") or "own", []).append(x)
    # CLIP scores are flat, so a plain top-k is dominated by whichever source has the most footage. Interleave the sources
    # (best clip of each first) so clean stock clips are always in the pool the picture check looks at.
    order = sorted(per_src.values(), key=lambda g: -g[0]["score"])
    out = []
    for rank in range(max((len(g) for g in order), default=0)):
        for g in order:
            if rank < len(g):
                out.append(g[rank])
    return out[:k]


RANK = """You are choosing B-roll (cutaway footage) for a video editor.
The video is about: {summary}
Topic words: {topic}
The speaker says: "{text}"

Below are numbered candidate pictures. Return the numbers of the candidates that would genuinely work as B-roll for THIS line AND
fit the video's topic and place, best first. A candidate fits if it clearly shows the main subject or action of the line (or something that
naturally goes with it) in a setting that matches the video; it does not need to show every detail the line mentions. Reject: sci-fi/neon/CGI imagery for a real-world topic, green-screen or animated intro/subscribe
templates, pictures of a different subject that merely shares a keyword, and pictures that clearly show a DIFFERENT place or region
than the one the video is about (for example Himalayan snow peaks or a Mumbai street in a video about Rajasthan's palaces).
Each candidate also shows its title from the clip's uploader: if the title names a different city or region than the video's, that is
a miss even when the picture looks generic. If unsure, prefer candidates that look right for the video's place and subject.
Return JSON only: {{"good": [numbers, best first], "reason": "one short sentence"}}"""


def rank(proj: dict, text: str, cands: list) -> dict | None:
    """-> {"order": {id: position}, "good": n, "reason": str} for the candidates Gemini says fit, or None when unavailable."""
    if not gemini.enabled() or not cands:
        return None
    imgs = [(c, judge._thumb(c["id"])) for c in cands[:MAX_CANDIDATES]]
    imgs = [(c, b) for c, b in imgs if b]
    if not imgs:
        return None
    key = (proj["id"], text, tuple(c["id"] for c, _ in imgs))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    parts = [{"text": RANK.format(summary=(proj.get("llm") or {}).get("summary") or "(not available)",
                                  topic=topic_words(proj) or "(none)", text=(text or "")[:240])}]
    for k, (c, b) in enumerate(imgs, 1):
        parts += [{"text": f"candidate {k} (title: {(c.get('title') or c.get('file') or '')[:90]}):"}, {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}}]
    try:
        data = gemini.generate_json("", temperature=0.1, timeout=90, parts=parts)
    except Exception as e:
        return {"error": gemini.redact(e)}
    good = []
    for g in data.get("good", []) or []:
        try:
            i = int(g)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(imgs) and imgs[i - 1][0]["id"] not in good:
            good.append(imgs[i - 1][0]["id"])
    res = {"order": {cid: n for n, cid in enumerate(good)}, "good": len(good), "judged": [c["id"] for c, _ in imgs],
           "reason": str(data.get("reason") or "")[:200]}
    _cache[key] = (time.time(), res)
    return res


def suggest(searcher, pid: str, text: str, query: str, alts: list, k: int = 24, check: bool = False, extra: list | None = None) -> dict:
    proj = store.load(pid)
    qs = list(dict.fromkeys(queries(proj, text, query, alts) + [q for q in (extra or []) if q]))[:7]
    cands = candidates(searcher, proj, qs, max(k, 12))
    vp = video_places(proj)
    for c in cands:
        w = wrong_place(c, vp)
        if w:
            c["fit"], c["why_not"] = False, f"shows {w}"
    cands.sort(key=lambda c: (c.get("fit") is False,))          # stable: wrong-place clips drop to the bottom, order otherwise kept
    out = {"queries": qs, "topic": topic_words(proj), "judged": False, "good": None, "reason": "", "clips": cands[:k]}
    if check:
        r = rank(proj, text, cands)
        if r and "order" in r:
            judged, order = set(r["judged"]), r["order"]
            for c in cands:
                if c.get("why_not"):                             # the title already names another place: stays a miss
                    continue
                c["fit"] = True if c["id"] in order else (False if c["id"] in judged else None)
            cands.sort(key=lambda c: (0 if c.get("fit") else (2 if c.get("fit") is False else 1), order.get(c["id"], 0), -c["score"]))
            out.update(judged=True, good=r["good"], reason=r["reason"], clips=cands[:k])
        elif r:
            out["error"] = r.get("error")
    return out


MIN_FIT = 6            # fewer than this many confirmed clips triggers a topic-specific Pixabay fetch


def expand(searcher, pid: str, text: str, query: str, alts: list, k: int = 24) -> dict:
    """The library had too few clips that fit: fetch topic-specific ones from Pixabay (queries written by Gemini for this line
    in the context of this video), then run the same suggestion + picture check again."""
    from . import live, pipeline
    proj = store.load(pid)
    lib = proj.get("library")
    if not proj.get("live_search", lib is None):
        out = suggest(searcher, pid, text, query, alts, k, True)
        out.update(fetched=0, expand_note="Pixabay search is switched off for this project.")
        return out
    qs = judge.topic_queries((proj.get("llm") or {}).get("summary") or "", topic_words(proj), text or query, n=4)
    also = None
    if lib is None:
        also = pipeline.live_library(pid, proj)
        store.save(pid, proj)
    res = live.fetch(qs, searcher, None, library_id=lib or also, n_main=len(qs)) if qs else {"added": 0}
    out = suggest(searcher, pid, text, query, alts, k, True, extra=qs)       # search with the fetch queries too, so the new clips are found
    out.update(fetched=res.get("added", 0), fetched_queries=qs)
    return out
