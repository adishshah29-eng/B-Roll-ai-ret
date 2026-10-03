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


# offline importance: no LLM, so a few honest signals instead of understanding
_SPEAKER = re.compile(r"\b(hi|hello|hey|welcome|subscribe|comment|comments|like this video|thanks for watching|see you|let me know|"
                      r"i think|i guess|you know|so yeah|anyway)\b", re.I)
_NUMBER = re.compile(r"\d|\b(one|two|three|four|five|ten|hundred|thousand|million|billion|percent)\b", re.I)


def offline_lines(units: list) -> list:
    """Score every speech clip without an LLM: visual = the filmable-line probe; importance from named places, numbers,
    proper nouns and how much content the line carries, minus greetings / calls to action / asides."""
    from .. import truth
    out = []
    speech = [u for u in units if u.get("kind") == "speech" and (u.get("text") or "").strip()]
    for k, u in enumerate(speech):
        text = u["text"]
        vis = visual_prob(text)
        places = [n for n, _ in truth.match_places(text)]
        content = len(keywords(text, n=12).split())
        proper = len(re.findall(r"(?<!^)(?<![.!?] )\b[A-Z][a-z]{2,}", text))
        imp = 0.3 + 0.25 * bool(places) + 0.12 * bool(_NUMBER.search(text)) + 0.08 * min(proper, 2) + 0.03 * min(content, 6)
        role = "place" if places else ("data" if _NUMBER.search(text) else "key point")
        if _SPEAKER.search(text):
            imp -= 0.35
            role = "cta" if k >= len(speech) - 2 else ("hook" if k == 0 else "aside")
        q, alts = offline_queries(text) if vis >= rules.VISUAL_MIN else (None, [])
        out.append({"id": u["id"], "importance": round(max(0.0, min(1.0, imp)), 2), "visual": round(vis, 2), "role": role,
                    "query": q or "", "alt_queries": alts, "anchor": places[0] if places else "",
                    "reason": {"place": "names a place", "data": "has a number", "key point": "content line",
                               "cta": "call to action", "hook": "greeting", "aside": "aside"}[role]})
    return out


def offline_plan(units: list, duration: float, fmap: list, segments: list | None = None, density: str = "balanced") -> dict:
    lines = offline_lines(units)
    spots = rules.select_spots(lines, units, duration, density, segments)
    if not spots:
        spots = topic_spot(units, duration, "", segments)
    skipped = sum(1 for l in lines if not l["query"])
    note = f" {skipped} line(s) had nothing filmable and keep the speaker on screen." if skipped else ""
    return {"provider": "offline", "slots": spots, "lines": lines,
            "summary": "Offline engine: lines scored by simple signals (places, numbers, filmable words), no LLM." + note}


# ───────────────────────── Gemini ─────────────────────────
PROMPT = """You are a senior video editor preparing B-roll (cutaway stock footage) for a talking-head video of {dur:.0f} s.
Below are its clips as [id | start-end s] text, then the places where the picture cuts, then the creator's script if supplied.
B-roll will be placed ONLY on the lines that matter most, so score EVERY clip honestly:

- importance (0-1): how much this line carries the message. High: the main claim or promise, a named place / product / person, a
  number or result, a vivid example or story beat, the emotional peak, what the viewer must remember. Low: greetings, "welcome
  back", filler, repetition, asides, meta talk about the video, the closing call to action. Use the full range; most videos have
  only a few lines above 0.8. If a script is supplied, use its emphasis (headings, repeated ideas, what it builds up to) to judge.
- visual (0-1): how well REAL stock footage could show this line (concrete things, places, actions = high; opinions, abstract
  talk, direct address to the camera = low).
- role: one of hook, key point, example, place, data, story, transition, aside, cta.
- reason: at most 8 words on why it matters or not ("names the destination", "key claim", "just a greeting").
- For every clip with visual >= 0.4 also give:
  `query` = 2-4 plain English words about ONE subject only, the way you would type it on a stock-footage site. Name the real subject
  ("python code", not "programming interface"; never join two ideas). Prefer real footage (people, hands, objects, places,
  actions) over abstract, CGI, neon or "digital" imagery. Never use these words: {banned}. Match the place named in the narration
  (do not show a different city or region). Translate the idea if the narration is not English.
  `alt_queries` = up to 2 other phrasings of the same idea, same rules.
  `anchor` = the exact word in the clip at which the footage should appear (the thing being named).
Also write a one-sentence `summary` of the video.

Return JSON only: {{"summary": str, "lines": [{{"id": int, "importance": float, "visual": float, "role": str, "reason": str,
"query": str, "alt_queries": [str], "anchor": str}}]}}

CLIPS
{units}

PICTURE CUTS (s): {cuts}

SCRIPT
{script}"""

# words that make stock sites return the wrong thing ("screen" -> green screens, "intro" -> animated intros ...)
BANNED = ["screen", "background", "intro", "outro", "subscribe", "abstract", "concept", "futuristic", "hologram", "matrix",
          "wallpaper", "template", "loop", "overlay"]
ROLES = {"hook", "key point", "example", "place", "data", "story", "transition", "aside", "cta"}


def clean_query(q: str) -> str:
    """Drop the words stock sites misread; keep the query as it was if nothing would be left."""
    words = re.sub(r"\s+", " ", str(q or "")).strip().split()
    kept = [w for w in words if w.lower().strip(",.") not in BANNED]
    return " ".join(kept if kept else words)[:80]


def _num(v, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def _parse_lines(data: dict, units: list) -> list:
    ids = {u["id"] for u in units if u.get("kind") == "speech"}
    out, seen = [], set()
    for x in data.get("lines", []) or []:
        try:
            i = int(x["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if i not in ids or i in seen:
            continue
        seen.add(i)
        vis = _num(x.get("visual"))
        q = clean_query(x.get("query")) if vis >= rules.VISUAL_MIN else ""
        alts = [clean_query(v) for v in (x.get("alt_queries") or [])][:2] if q else []
        role = str(x.get("role") or "").strip().lower()
        out.append({"id": i, "importance": round(_num(x.get("importance")), 2), "visual": round(vis, 2),
                    "role": role if role in ROLES else "key point", "reason": str(x.get("reason") or "")[:80],
                    "query": q, "alt_queries": [v for v in alts if v and v != q], "anchor": str(x.get("anchor") or "")[:40]})
    return out


def topic_spot(units: list, duration: float, summary: str, segments: list | None = None) -> list:
    """Last resort when no line looks filmable (pure talk): one spot on the longest line after the opening, searched by the
    video's topic words, so the video still gets B-roll that is at least on subject."""
    hook, mn = rules.hook_s(duration), rules.min_slot(duration)
    best = None
    for u in units:
        if u.get("kind") != "speech" or not (u.get("text") or "").strip():
            continue
        a = max(u["start"], hook) + 0.1
        b = min(u["end"] - 0.05, a + rules.MAX_SLOT, duration)
        if b - a >= mn * 0.8 and (best is None or b - a > best[1] - best[0]):
            best = (a, b, u)
    if not best:
        return []
    a, b, u = best
    q = keywords(summary, n=3) or keywords(u["text"], n=3) or "people talking"
    alt = keywords(u["text"], n=3)
    return [{"start": round(a, 2), "end": round(b, 2), "text": u["text"], "query": q,
             "alt_queries": [alt] if alt and alt != q else [], "anchor": None, "importance": 0.3, "visual": 0.4, "role": "topic",
             "reason": "no line was clearly filmable: B-roll on the video's topic", "guaranteed": True}]


def _gemini(units: list, cuts: list, duration: float, script: str | None, segments: list | None = None,
            density: str = "balanced") -> dict | None:
    if not gemini.enabled():
        return None
    speech = [u for u in units if u.get("kind") == "speech"]
    text = chr(10).join(f"[{u['id']} | {u['start']:.1f}-{u['end']:.1f}] {u['text']}" for u in speech)
    prompt = PROMPT.format(dur=duration, banned=", ".join(BANNED), units=text,
                           cuts=", ".join(f"{c:.1f}" for c in cuts) or "none", script=(script or "").strip() or "(none: use the clips)")
    best, data = [], {}
    for attempt in range(2):                    # an answer that skips lines gets one more try; the more complete one is kept
        d = gemini.generate_json(prompt, temperature=0.2 if attempt == 0 else 0.5)
        got = _parse_lines(d, units)
        if len(got) > len(best):
            best, data = got, d
        if len(best) >= max(1, int(0.8 * len(speech))):
            break
    if not best:
        return None
    spots = rules.select_spots(best, units, duration, density, segments)
    summary = str(data.get("summary", ""))[:300]
    if not spots:
        spots = topic_spot(units, duration, summary, segments)
    return {"provider": "gemini", "slots": spots, "lines": best, "summary": summary}


def plan(units: list, cuts: list, duration: float, fmap, script: str | None = None, segments: list | None = None,
         density: str = "balanced") -> dict:
    """Score every line (importance, visual, role, query) and place B-roll on the strongest ones for the chosen amount."""
    t0 = time.time()
    err = None
    try:
        g = _gemini(units, cuts, duration, script, segments, density)
        if g:
            g["ms"], g["error"] = int((time.time() - t0) * 1000), None
            return g
    except Exception as e:                      # network, quota, bad JSON: never block the edit
        err = gemini.redact(f"{type(e).__name__}: {e}")
    o = offline_plan(units, duration, fmap() if callable(fmap) else fmap, segments, density)
    o["ms"], o["error"] = int((time.time() - t0) * 1000), err
    return o
