"""The LLM step: read the whole script (units with timings + scene cuts) and decide
   (1) WHERE B-roll should cover the speaker and (2) WHAT each spot should show, as stock-site search queries.

Providers (same output either way, validated and clamped here):
  gemini     GEMINI_API_KEY in .env  → Gemini reads the timestamped transcript (text only, never video)
  offline    no key / any failure    → rules pick the spots; each line becomes queries via keyword extraction + the
                                       CLIP concept vocabulary (works for Hindi too)
Output: {"provider", "slots":[{start,end,text,query,alt_queries,reason}], "summary", "ms", "error"}
"""
import json
import os
import re
import time

import requests

from .. import gemini
from ..textutil import STOP as _STOP
from . import slots as rules

MAX_QUERIES = 4

STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being am i me my we our us you your
he she it they them his her its their this that these those there here what which who whom whose when where why how not no yes do does did
done have has had will would can could should may might must just very really also too than about into over under up down out off again
more most some any each other such only own same both few all let lets lot lots like get got going go goes went gonna want need think know
say said tell told hi hello everyone welcome back channel today comments comment subscribe video guys thing things stuff one two""".split())


def provider_name() -> str:
    return "gemini" if gemini.enabled() else "offline"


# ───────────────────────── offline "understanding" ─────────────────────────
TECH_SHORT = {"ai", "ml", "api", "apis", "web", "dev", "app", "apps", "ui", "ux", "vr", "ar", "sql", "css", "html", "gpu", "cpu",
              "seo", "iot", "llm", "cad", "gps"}
_CONTRACTION = re.compile(r"'(s|t|re|ve|ll|d|m)$")


def keywords(text: str, n=4) -> str:
    """Content words for a stock-site search. Keeps short acronyms (AI, web, dev, API); drops stop words and contractions
    (that's -> that, it's -> it)."""
    out, seen = [], set()
    for w in re.findall(r"[A-Za-z][A-Za-z']*", text or ""):
        t = _CONTRACTION.sub("", w.lower().strip("'"))
        if not t or t in STOP or t in _STOP or t in seen:
            continue
        acronym = w.isupper() and 2 <= len(w) <= 5
        if len(t) < 4 and t not in TECH_SHORT and not acronym:
            continue
        seen.add(t)
        out.append((t, len(t) + (4 if (t in TECH_SHORT or acronym) else 0)))
    best = sorted(range(len(out)), key=lambda i: -out[i][1])[:n]
    return " ".join(out[i][0] for i in sorted(best))


def concepts(text: str, k=2) -> list:
    """Nearest B-roll concepts from the CLIP vocabulary as [(phrase, similarity)] (multilingual: a Hindi line maps to
    an English concept)."""
    from .. import models
    from ..indexer import tags
    V, words = tags.vocab()
    e = models.embed_texts([text])[0]
    sims = V @ e
    return [(words[i], float(sims[i])) for i in sims.argsort()[::-1][:k]]


VISUAL_MIN = 0.5            # P(line is filmable) needed before the offline engine will write a query for it
_probe = {}


def visual_prob(text: str) -> float:
    """P(this line can be shown on screen) from a small linear probe on the sentence embedding, trained on
    resources/visualness.yaml (labelled visual vs talk lines; add yours to improve it). Calibration, eval/calibrate_concepts.py:
    concept-list similarity cannot tell the two apart (59 %), the probe does (100 % leave-one-out on a clean set of 93 lines)."""
    import yaml
    from sklearn.linear_model import LogisticRegression
    from .. import models
    from ..config import RESOURCES
    if "clf" not in _probe:
        spec = yaml.safe_load(open(RESOURCES / "visualness.yaml", encoding="utf-8"))
        lines = spec["visual"] + spec["talk"]
        y = [1] * len(spec["visual"]) + [0] * len(spec["talk"])
        _probe["clf"] = LogisticRegression(C=2.0, max_iter=1000).fit(models.embed_texts(lines), y)
    return float(_probe["clf"].predict_proba(models.embed_texts([text]))[0, 1])


def offline_queries(text: str) -> tuple:
    """Clean stock-site phrases without an LLM. Returns (None, []) when the line is not something you can film: a spot is
    then left alone instead of being filled with a guess ("people celebrating" for a line of pure talk)."""
    from .. import truth
    if visual_prob(text) < VISUAL_MIN:
        return None, []
    (c1, _), (c2, _) = concepts(text, 2)
    kw = keywords(text)
    place = next((n for n, _ in truth.match_places(text) if (truth.entry(n) or {}).get("kind") in ("city", "region")), None)
    primary = c1
    out = []
    for q in ([f"{place} {primary}"] if place else []) + ([kw] if len(kw.split()) >= 2 else []) + [c2]:
        if q and q != primary and q not in out:
            out.append(q)
    return primary, out[:2]


def offline_plan(units: list, duration: float, fmap: list) -> dict:
    segs = [{"start": u["start"], "end": u["end"], "text": u["text"]} for u in units if u["kind"] == "speech"]
    picked = rules.rule_slots(segs, duration, fmap)
    out, skipped = [], 0
    for s in picked:
        q, alts = offline_queries(s["text"])
        if q is None:
            skipped += 1
            continue
        out.append({**s, "query": q, "alt_queries": alts, "reason": s.get("reason") or "visual line"})
    note = f" {skipped} line(s) had no confident visual and were left alone." if skipped else ""
    return {"provider": "offline", "slots": out,
            "summary": "Offline engine: spots chosen by rules, queries from the concept vocabulary (no LLM)." + note}


# ───────────────────────── Gemini ─────────────────────────
PROMPT = """You are a professional video editor adding B-roll (cutaway stock footage) to a talking-head video.
The video is {dur:.0f} s long. Below are its clips as [id | start-end s] text, then the places where the picture cuts, then the
creator's script if they supplied one.

Decide:
1. Which moments should be covered by B-roll. Do NOT cover the first {hook} s (the speaker introduces themselves) or the closing call
   to action; leave the speaker on screen for personal, emotional or direct-address lines ("I", "you", "subscribe"). Cover concrete,
   visual statements. Cover roughly {cover}% of the video, which means at least {nspots} spot(s) here (fewer only if the script has
   nothing filmable). Each spot is {mn}-{mx} s, inside one clip, and spots never overlap.
   A clip longer than {long:.0f} s may hold two spots with different footage. Editors cut to the picture the moment the subject is
   named, so give each spot an `anchor`: the exact word from the narration at which the footage should appear (the place, object or
   action being named).
2. For each spot, what footage to show, as a stock-video search the way you would type it on a stock-footage site:
   - `query` = 2-4 plain English words about ONE subject only. Never join two ideas ("artificial intelligence code" is bad: it
     returns neon robots). Name the real subject of the video: if the video teaches Python, a coding spot says "python code" or
     "programmer typing code", not "programming interface".
   - Prefer real, filmable footage (people, hands, objects, places, actions) over abstract, CGI, neon, sci-fi or "digital" imagery.
   - NEVER use these words, stock sites misread them: {banned}.
   - `alt_queries` = up to 2 different phrasings of the same idea (each also one subject, same rules).
   Match the topic and the place named in the narration (do not show a different city). If the narration is not English, translate the idea.
3. A one-sentence `summary` of what the video is about.

Return JSON only: {{"summary": str, "slots": [{{"start": float, "end": float, "anchor": str, "query": str, "alt_queries": [str], "reason": str}}]}}

CLIPS
{units}

PICTURE CUTS (s): {cuts}

SCRIPT
{script}"""

# words that make stock sites return the wrong thing ("screen" -> green screens, "intro" -> animated intros ...)
BANNED = ["screen", "background", "intro", "outro", "subscribe", "abstract", "concept", "futuristic", "hologram", "matrix",
          "wallpaper", "template", "loop", "overlay"]


def clean_query(q: str) -> str:
    """Drop the words stock sites misread; keep the query as it was if nothing would be left."""
    words = re.sub(r"\s+", " ", str(q or "")).strip().split()
    kept = [w for w in words if w.lower().strip(",.") not in BANNED]
    return " ".join(kept if kept else words)[:80]


def _word(segments: list, word: str, lo: float, hi: float):
    """First spoken word equal to `word` that starts in [lo, hi]."""
    w0 = re.sub(r"[^\w']", "", (word or "").lower())
    if not w0:
        return None
    for seg in segments or []:
        for w in seg.get("words", []):
            if lo <= w["s"] <= hi and re.sub(r"[^\w']", "", w["w"].lower()) == w0:
                return w
    return None


def _validate(data: dict, units: list, duration: float, segments: list | None = None) -> list:
    hook, mnslot = rules.hook_s(duration), rules.min_slot(duration)
    out = []
    for x in data.get("slots", []):
        try:
            a, b = float(x["start"]), float(x["end"])
        except (KeyError, TypeError, ValueError):
            continue
        a = max(a, hook)
        b = min(b, a + rules.MAX_SLOT, duration)
        u = next((u for u in units if u["kind"] == "speech" and u["start"] - 0.5 <= a <= u["end"]), None)
        anchor = None
        w = _word(segments, str(x.get("anchor") or ""), a - 1.5, b - 0.3)
        if w:                                            # land the cut on the spoken word, as editors do (B-Script: 73 % within 1 s)
            a2 = max(hook, w["s"] - 0.15)
            end_cap = min(duration, u["end"] if u else duration)
            b2 = min(max(b, a2 + mnslot), a2 + rules.MAX_SLOT, end_cap)
            if b2 - a2 >= mnslot:
                a, b, anchor = a2, b2, w["w"].strip(".,!?\"'")
        if b - a < mnslot or any(not (b + rules.GAP_S <= o["start"] or a >= o["end"] + rules.GAP_S) for o in out):
            continue
        q = clean_query(x.get("query"))
        if not q:
            continue
        alts = [clean_query(v) for v in (x.get("alt_queries") or [])][:2]
        out.append({"start": round(a, 2), "end": round(b, 2), "text": u["text"] if u else q, "query": q, "anchor": anchor,
                    "alt_queries": [v for v in alts if v and v != q], "reason": str(x.get("reason", ""))[:140] or "editor's choice"})
    return out


def _gemini(units: list, cuts: list, duration: float, script: str | None, segments: list | None = None) -> dict | None:
    if not gemini.enabled():
        return None
    lines = chr(10).join(f"[{u['id']} | {u['start']:.1f}-{u['end']:.1f}] {u['text']}" for u in units if u["kind"] == "speech")
    n_speech = sum(1 for u in units if u["kind"] == "speech")
    nspots = max(2, round(rules.TARGET_COVER * duration / 3.5))
    prompt = PROMPT.format(
        dur=duration, hook=rules.hook_s(duration), cover=int(rules.TARGET_COVER * 100), nspots=nspots, mn=rules.min_slot(duration),
        mx=rules.MAX_SLOT, long=rules.MAX_SLOT + 1, banned=", ".join(BANNED), units=lines,
        cuts=", ".join(f"{c:.1f}" for c in cuts) or "none", script=(script or "").strip() or "(none: use the clips)")
    best, data = [], {}

    def cover(sl):
        return sum(o["end"] - o["start"] for o in sl)

    for attempt in range(2):                    # too few spots or too little coverage gets one more try; the better answer is kept
        d = gemini.generate_json(prompt, temperature=0.3 if attempt == 0 else 0.7)
        got = _validate(d, units, duration, segments)
        if cover(got) > cover(best):
            best, data = got, d
        if len(best) >= min(nspots, n_speech) and cover(best) >= 0.3 * duration:
            break
    if not best:
        return None
    return {"provider": "gemini", "slots": sorted(best, key=lambda s: s["start"]), "summary": str(data.get("summary", ""))[:300]}


def plan(units: list, cuts: list, duration: float, fmap: list, script: str | None = None, segments: list | None = None) -> dict:
    t0 = time.time()
    err = None
    try:
        g = _gemini(units, cuts, duration, script, segments)
        if g:
            g["ms"], g["error"] = int((time.time() - t0) * 1000), None
            return g
    except Exception as e:                      # network, quota, bad JSON: never block the edit
        err = gemini.redact(f"{type(e).__name__}: {e}")
    o = offline_plan(units, duration, fmap)
    o["ms"], o["error"] = int((time.time() - t0) * 1000), err
    return o
