"""WHERE should B-roll go?  Gemini (if GEMINI_API_KEY is set) reads the timestamped transcript and proposes slots;
the rule-based picker is the always-available fallback. Either way the result is validated and clamped here.

A slot = {"start", "end", "text", "query", "reason"}:  `text` is the narration under the slot (used for TRUE claims),
`query` is the visual description used for retrieval (Gemini rewrites it; the rules use the narration itself).
"""
import json
import os
import re

import requests

from . import analyse

HOOK_S = 3.0            # never cover the opening hook: the speaker introduces themselves
MIN_SLOT, MAX_SLOT = 1.5, 5.0


def hook_s(duration: float) -> float:
    """Opening seconds left uncovered: 3 s on a normal video, but never more than 10 % of a short one."""
    return round(min(HOOK_S, max(0.5, 0.1 * (duration or 0))), 2)


def min_slot(duration: float) -> float:
    return 1.0 if (duration or 0) < 20 else MIN_SLOT


# ───────────────────────── importance-weighted placement ─────────────────────────
# Every line is scored (importance = how much it carries the message, visual = can stock footage show it). B-roll goes only on
# the strongest lines, within a budget, with the speaker kept on screen in between: "not too much, but where it matters".
DENSITY = {   # floor = minimum importance, cover = max share of runtime, gap = speaker seconds kept between spots
    "light":    {"floor": 0.62, "cover": 0.25, "gap": 3.0, "per_min": 4,  "label": "Light: only the key moments"},
    "balanced": {"floor": 0.45, "cover": 0.40, "gap": 1.5, "per_min": 7,  "label": "Balanced"},
    "rich":     {"floor": 0.30, "cover": 0.55, "gap": 0.8, "per_min": 11, "label": "Rich: most visual lines"},
}
VISUAL_MIN = 0.4                   # below this a line cannot be shown with stock footage, however important it is
SPEAKER_ROLES = {"hook", "cta", "aside", "greeting"}     # lines that normally keep the speaker on screen


def weight(line: dict) -> float:
    return float(line.get("importance", 0)) * (0.4 + 0.6 * float(line.get("visual", 0)))


def find_word(segments: list, word: str, lo: float, hi: float):
    """First spoken word equal to `word` (case and punctuation ignored) that starts in [lo, hi]."""
    w0 = re.sub(r"[^\w']", "", (word or "").lower())
    if not w0:
        return None
    for seg in segments or []:
        for w in seg.get("words", []):
            if lo <= w["s"] <= hi and re.sub(r"[^\w']", "", w["w"].lower()) == w0:
                return w
    return None


def select_spots(lines: list, units: list, duration: float, density: str = "balanced", segments: list | None = None,
                 keep: list = ()) -> list:
    """Pick B-roll spots from scored lines. `keep` = spots that must stay (locked by the user); they count against the budget
    and nothing is placed on top of them. Returns keep + new spots, sorted by time."""
    cfg = DENSITY.get(density, DENSITY["balanced"])
    hook, mn = hook_s(duration), min_slot(duration)
    budget = cfg["cover"] * max(duration - hook, 1.0)
    max_n = max(1, round(cfg["per_min"] * duration / 60))
    speech = {u["id"]: u for u in units if u.get("kind") == "speech"}
    chosen = list(keep)
    used = sum(k["end"] - k["start"] for k in chosen)
    cands = sorted((l for l in lines if l.get("query") and l.get("id") in speech), key=lambda l: -weight(l))
    for rank, l in enumerate(cands):
        if len(chosen) >= max_n or used >= budget:
            break
        imp, vis = float(l.get("importance", 0)), float(l.get("visual", 0))
        if vis < VISUAL_MIN:
            continue
        if l.get("role") in SPEAKER_ROLES and imp < 0.8:
            continue
        if imp < cfg["floor"] and not (rank == 0 and imp >= 0.3):      # the single strongest visual line always gets a chance
            continue
        u = speech[l["id"]]
        a = max(u["start"], hook)
        w = find_word(segments, l.get("anchor"), a - 0.2, u["end"] - 0.3)
        a = max(hook, w["s"] - 0.15) if w else a + 0.2          # cut on the spoken word when we know it
        b = min(u["end"] - 0.1, a + MAX_SLOT, duration)
        if b - a < mn:
            continue
        if any(not (b + cfg["gap"] <= c["start"] or a >= c["end"] + cfg["gap"]) for c in chosen):
            continue
        chosen.append({"start": round(a, 2), "end": round(b, 2), "text": u["text"], "query": l["query"],
                       "alt_queries": list(l.get("alt_queries") or [])[:2], "anchor": w["w"].strip(".,!?\"'") if w else None,
                       "reason": l.get("reason") or l.get("role") or "important line", "importance": round(imp, 2),
                       "visual": round(vis, 2), "role": l.get("role")})
        used += b - a
    # Guarantee: a video always gets B-roll, at least one spot per started 10 s (so even a 10 s video gets one). If the
    # importance floor kept everything out, take the best remaining lines anyway, speaker-role lines last.
    need = max(1, int(-(-duration // 10))) if duration else 1
    if len(chosen) < need:
        pool = sorted((l for l in lines if l.get("query") and l.get("id") in speech),
                      key=lambda l: (l.get("role") in SPEAKER_ROLES, -weight(l)))
        for l in pool:
            if len(chosen) >= need:
                break
            u = speech[l["id"]]
            a0 = max(u["start"], hook)
            w = find_word(segments, l.get("anchor"), a0 - 0.2, u["end"] - 0.3)
            a = max(hook, w["s"] - 0.15) if w else a0 + 0.1
            b = min(u["end"] - 0.05, a + MAX_SLOT, duration)
            if b - a < mn * 0.8 or any(not (b + 0.4 <= c["start"] or a >= c["end"] + 0.4) for c in chosen):
                continue
            chosen.append({"start": round(a, 2), "end": round(b, 2), "text": u["text"], "query": l["query"],
                           "alt_queries": list(l.get("alt_queries") or [])[:2], "anchor": w["w"].strip(".,!?\"'") if w else None,
                           "reason": "a video always gets B-roll: " + (l.get("reason") or "best available line"),
                           "importance": round(float(l.get("importance", 0)), 2), "visual": round(float(l.get("visual", 0)), 2),
                           "role": l.get("role"), "guaranteed": True})
    return sorted(chosen, key=lambda s: s["start"])
TARGET_COVER = 0.45     # share of runtime covered by B-roll (rules)
GAP_S = 0.6             # keep at least this much A-roll between slots
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ───────────────────────── script alignment ─────────────────────────
def align_script(segments: list, script: str | None) -> list:
    """If the user also gave a script, use its wording (cleaner than ASR) for each segment, mapped by relative word position.
    Timing always comes from the audio."""
    if not script or not script.strip():
        return segments
    words = script.split()
    tw = sum(max(1, len(s["text"].split())) for s in segments) or 1
    out, pos = [], 0
    for s in segments:
        n = max(1, len(s["text"].split()))
        a, b = round(pos / tw * len(words)), round((pos + n) / tw * len(words))
        pos += n
        t = " ".join(words[a:max(b, a + 1)]).strip()
        out.append({**s, "text": t or s["text"], "asr": s["text"]})
    return out


# ───────────────────────── rule-based picker ─────────────────────────
def _visual_score(text: str) -> float:
    """Concrete, visual lines deserve B-roll more than 'I', 'you', 'so', 'today I want to...' asides."""
    t = text.lower()
    direct = len(re.findall(r"\b(i|i'm|i've|me|my|you|your|we|let's|subscribe|comment|like this video)\b", t))
    words = max(1, len(t.split()))
    long_words = len([w for w in re.findall(r"[a-zऀ-ॿ]+", t) if len(w) >= 6])
    return long_words / words - 0.6 * direct / words


def rule_slots(segments: list, duration: float, fmap: list) -> list:
    cands, hook, mn = [], hook_s(duration), min_slot(duration)
    for s in segments:
        a, b = max(s["start"], hook), s["end"]
        if b - a < mn:
            continue
        a2, b2 = a + 0.2, min(b - 0.1, a + 0.2 + MAX_SLOT)       # short lead-in so the cut lands after the word starts
        if b2 - a2 < mn:
            continue
        score = _visual_score(s["text"]) - 0.5 * analyse.face_share(fmap, a2, b2)
        cands.append({"start": round(a2, 2), "end": round(b2, 2), "text": s["text"], "query": s["text"],
                      "score": score, "reason": "visual line" if score > 0 else "keeps the pace"})
    budget = TARGET_COVER * max(duration - hook, 1.0)
    chosen, used = [], 0.0
    for c in sorted(cands, key=lambda c: -c["score"]):
        if used >= budget:
            break
        if any(not (c["end"] + GAP_S <= o["start"] or c["start"] >= o["end"] + GAP_S) for o in chosen):
            continue
        chosen.append(c)
        used += c["end"] - c["start"]
    for c in chosen:
        c.pop("score", None)
    return sorted(chosen, key=lambda c: c["start"])


# ───────────────────────── Gemini picker ─────────────────────────
PROMPT = """You are a professional video editor placing B-roll over a talking-head video.
Transcript lines are given as [start-end seconds] text. Choose where B-roll should cover the speaker.
Rules: do not cover the first {hook} seconds; each slot {min}-{max} seconds and inside one line; leave the speaker on screen for
personal or emotional moments and direct address ("I", "you", calls to action); cover concrete, visual statements; cover about
{cover}% of the video; never overlap slots. For each slot write `query`: a short concrete description of the footage to show
(objects, place, action, shot type), in English.
Return JSON only: {{"slots":[{{"start":float,"end":float,"query":str,"reason":str}}]}}
Transcript ({dur:.0f} s):
{lines}"""


def gemini_slots(segments: list, duration: float) -> list | None:
    key = os.getenv("GEMINI_API_KEY")
    if not key or not segments:
        return None
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)
    body = {"contents": [{"parts": [{"text": PROMPT.format(hook=HOOK_S, min=MIN_SLOT, max=MAX_SLOT,
                                                            cover=int(TARGET_COVER * 100), dur=duration, lines=lines)}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.3}}
    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                          params={"key": key}, json=body, timeout=60)
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        raw = json.loads(txt).get("slots", [])
    except Exception as e:
        print("gemini slot picker failed, using rules:", re.sub(r"key=[^&\s]+", "key=<redacted>", str(e)))
        return None
    out = []
    for x in raw:
        try:
            a, b = float(x["start"]), float(x["end"])
        except (KeyError, TypeError, ValueError):
            continue
        a = max(a, HOOK_S)
        b = min(b, a + MAX_SLOT, duration)
        if b - a < MIN_SLOT or any(not (b + GAP_S <= o["start"] or a >= o["end"] + GAP_S) for o in out):
            continue
        seg = next((s for s in segments if s["start"] - 0.5 <= a <= s["end"]), None)
        out.append({"start": round(a, 2), "end": round(b, 2), "text": seg["text"] if seg else str(x.get("query", "")),
                    "query": str(x.get("query") or (seg["text"] if seg else "")).strip()[:200],
                    "reason": str(x.get("reason", ""))[:120] or "editor's choice"})
    return sorted(out, key=lambda c: c["start"]) or None


def pick(segments: list, duration: float, fmap: list) -> tuple[list, str]:
    g = gemini_slots(segments, duration)
    if g:
        return g, "gemini"
    return rule_slots(segments, duration, fmap), "rules"
