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
    cands = []
    for s in segments:
        a, b = max(s["start"], HOOK_S), s["end"]
        if b - a < MIN_SLOT:
            continue
        a2, b2 = a + 0.2, min(b - 0.1, a + 0.2 + MAX_SLOT)       # short lead-in so the cut lands after the word starts
        if b2 - a2 < MIN_SLOT:
            continue
        score = _visual_score(s["text"]) - 0.5 * analyse.face_share(fmap, a2, b2)
        cands.append({"start": round(a2, 2), "end": round(b2, 2), "text": s["text"], "query": s["text"],
                      "score": score, "reason": "visual line" if score > 0 else "keeps the pace"})
    budget = TARGET_COVER * max(duration - HOOK_S, 1.0)
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
        print("gemini slot picker failed, using rules:", e)
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
