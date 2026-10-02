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

from . import slots as rules

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
MAX_QUERIES = 4

STOP = set("""a an the and or but if then so of to in on at by for with from as is are was were be been being am i me my we our us you your
he she it they them his her its their this that these those there here what which who whom whose when where why how not no yes do does did
done have has had will would can could should may might must just very really also too than about into over under up down out off again
more most some any each other such only own same both few all let lets lot lots like get got going go goes went gonna want need think know
say said tell told hi hello everyone welcome back channel today comments comment subscribe video guys thing things stuff one two""".split())


def provider_name() -> str:
    return "gemini" if os.getenv("GEMINI_API_KEY") else "offline"


# ───────────────────────── offline "understanding" ─────────────────────────
def keywords(text: str, n=4) -> str:
    toks = re.findall(r"[A-Za-z']+", (text or "").lower())
    seen, out = set(), []
    for t in toks:
        t = t.strip("'")
        if len(t) < 4 or t in STOP or t in seen:
            continue
        seen.add(t)
        out.append(t)
    best = sorted(range(len(out)), key=lambda i: -len(out[i]))[:n]
    return " ".join(out[i] for i in sorted(best))


def concepts(text: str, k=2) -> list:
    """Nearest B-roll concepts from the CLIP vocabulary as [(phrase, similarity)] (multilingual: a Hindi line maps to
    an English concept)."""
    from .. import models
    from ..indexer import tags
    V, words = tags.vocab()
    e = models.embed_texts([text])[0]
    sims = V @ e
    return [(words[i], float(sims[i])) for i in sims.argsort()[::-1][:k]]


CONCEPT_MIN = 0.22


def offline_queries(text: str) -> tuple:
    """Clean stock-site phrases without an LLM: the nearest concept ('heavy rain falling') is the main query when it is a
    confident match, plain keywords otherwise; a place named in the line gets its own variant."""
    from .. import truth
    kw = keywords(text)
    (c1, s1), (c2, _) = concepts(text, 2)
    place = next((n for n, _ in truth.match_places(text) if (truth.entry(n) or {}).get("kind") in ("city", "region")), None)
    primary = c1 if s1 >= CONCEPT_MIN or len(kw.split()) < 2 else kw
    alts = [f"{place} {primary}" if place else kw, kw if place else c2, c2]
    out = []
    for q in alts:
        if q and q != primary and q not in out:
            out.append(q)
    return primary, out[:2]


def offline_plan(units: list, duration: float, fmap: list) -> dict:
    segs = [{"start": u["start"], "end": u["end"], "text": u["text"]} for u in units if u["kind"] == "speech"]
    picked = rules.rule_slots(segs, duration, fmap)
    out = []
    for s in picked:
        q, alts = offline_queries(s["text"])
        out.append({**s, "query": q, "alt_queries": alts, "reason": s.get("reason") or "visual line"})
    return {"provider": "offline", "slots": out, "summary": "Spots chosen by rules; queries built from keywords and the concept vocabulary."}


# ───────────────────────── Gemini ─────────────────────────
PROMPT = """You are a professional video editor adding B-roll (cutaway stock footage) to a talking-head video.
The video is {dur:.0f} s long. Below are its clips as [id | start-end s] text, then the places where the picture cuts, then the
creator's script if they supplied one.

Decide:
1. Which moments should be covered by B-roll. Do NOT cover the first {hook} s (the speaker introduces themselves) or the closing call
   to action; leave the speaker on screen for personal, emotional or direct-address lines ("I", "you", "subscribe"). Cover concrete,
   visual statements. Cover roughly {cover}% of the video. Each spot is {mn}-{mx} s, inside one clip, and spots never overlap.
2. For each spot, what footage to show, as a stock-video search: `query` = 2-4 plain English keywords exactly as you would type them on
   a stock-footage site (concrete objects, place, action; no abstract words), and `alt_queries` = up to 2 different phrasings.
   Match the topic and the place named in the narration (do not show a different city). If the narration is not English, translate the idea.
3. A one-sentence `summary` of what the video is about.

Return JSON only: {{"summary": str, "slots": [{{"start": float, "end": float, "query": str, "alt_queries": [str], "reason": str}}]}}

CLIPS
{units}

PICTURE CUTS (s): {cuts}

SCRIPT
{script}"""


def _gemini(units: list, cuts: list, duration: float, script: str | None) -> dict | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    lines = "\n".join(f"[{u['id']} | {u['start']:.1f}-{u['end']:.1f}] {u['text']}" for u in units if u["kind"] == "speech")
    body = {"contents": [{"parts": [{"text": PROMPT.format(
        dur=duration, hook=rules.HOOK_S, cover=int(rules.TARGET_COVER * 100), mn=rules.MIN_SLOT, mx=rules.MAX_SLOT,
        units=lines, cuts=", ".join(f"{c:.1f}" for c in cuts) or "none", script=(script or "").strip() or "(none: use the clips)")}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                      params={"key": key}, json=body, timeout=90)
    r.raise_for_status()
    data = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    out = []
    for x in data.get("slots", []):
        try:
            a, b = float(x["start"]), float(x["end"])
        except (KeyError, TypeError, ValueError):
            continue
        a = max(a, rules.HOOK_S)
        b = min(b, a + rules.MAX_SLOT, duration)
        if b - a < rules.MIN_SLOT or any(not (b + rules.GAP_S <= o["start"] or a >= o["end"] + rules.GAP_S) for o in out):
            continue
        u = next((u for u in units if u["kind"] == "speech" and u["start"] - 0.5 <= a <= u["end"]), None)
        q = re.sub(r"\s+", " ", str(x.get("query") or "")).strip()[:80]
        if not q:
            continue
        alts = [re.sub(r"\s+", " ", str(v)).strip()[:80] for v in (x.get("alt_queries") or [])][:2]
        out.append({"start": round(a, 2), "end": round(b, 2), "text": u["text"] if u else q, "query": q,
                    "alt_queries": [v for v in alts if v and v != q], "reason": str(x.get("reason", ""))[:140] or "editor's choice"})
    if len(out) < 1:
        return None
    return {"provider": "gemini", "slots": sorted(out, key=lambda s: s["start"]), "summary": str(data.get("summary", ""))[:300]}


def plan(units: list, cuts: list, duration: float, fmap: list, script: str | None = None) -> dict:
    t0 = time.time()
    err = None
    try:
        g = _gemini(units, cuts, duration, script)
        if g:
            g["ms"], g["error"] = int((time.time() - t0) * 1000), None
            return g
    except Exception as e:                      # network, quota, bad JSON: never block the edit
        err = f"{type(e).__name__}: {e}"
    o = offline_plan(units, duration, fmap)
    o["ms"], o["error"] = int((time.time() - t0) * 1000), err
    return o
