"""Script → beats → B-roll plan. P4 version = relevance + no-repeat greedy.
Later phases plug into `score()` (TRUE penalty, YOURS boost) and replace `assign()` with the Viterbi DP (CUTS)."""
import re
from dataclasses import dataclass

CAND_K = 10
LONG_BEAT_S = 6.0
MIN_BEAT_S = 2.0
SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


@dataclass
class Beat:
    i: int
    text: str
    dur: float


def split_beats(script: str, wpm: int = 150) -> list:
    """Sentences (EN + Hindi danda) → beats; very short sentences are merged into the previous beat."""
    parts = [p.strip() for p in SENT_SPLIT.split(script or "") if p and p.strip()]
    words_per_s = max(wpm, 60) / 60.0
    beats = []
    for p in parts:
        dur = max(len(p.split()) / words_per_s, 0.0)
        if beats and dur < MIN_BEAT_S:
            beats[-1].text += " " + p
            beats[-1].dur += dur
        else:
            beats.append(Beat(len(beats), p, dur))
    for b in beats:
        b.dur = round(max(b.dur, MIN_BEAT_S), 2)
        b.i = beats.index(b)
    return beats


def score(beat, row, rel):
    """Single place where pillars combine. P4: relevance only."""
    return rel


def assign(beats, cands_per_beat, snap):
    """Greedy no-repeat: for each beat take the best-scoring shot not yet used; long beats get a 2nd shot
    with a different size tag. Returns per-beat (chosen_rows, alt_rows)."""
    used = set()
    out = []
    for b, cands in zip(beats, cands_per_beat):
        ranked = sorted(((score(b, r, rel), r) for r, rel in cands), reverse=True)
        chosen = []
        for _, r in ranked:
            if r in used:
                continue
            chosen.append(r)
            break
        if chosen and b.dur > LONG_BEAT_S:
            first_size = snap.size[chosen[0]]
            for _, r in ranked:
                if r not in used and r not in chosen and snap.size[r] != first_size:
                    chosen.append(r)
                    break
        used.update(chosen)
        alts = [r for _, r in ranked if r not in chosen][:8]
        out.append((chosen, alts))
    return out


def plan(searcher, script: str, wpm: int = 150) -> dict:
    from .search import shot_cards
    snap = searcher.holder.get()
    beats = split_beats(script, wpm)
    if not beats:
        return {"beats": []}
    searcher.encode_many([b.text for b in beats])             # one batch for the whole script
    cands = [searcher.candidates(b.text, k=CAND_K) for b in beats]
    picks = assign(beats, cands, snap)
    # display cards for every row we mention
    score_of = {}
    for cl in cands:
        for r, rel in cl:
            score_of.setdefault(r, rel)
    rows = sorted({r for ch, al in picks for r in ch + al})
    import numpy as np
    sc = np.zeros(len(snap))
    for r, v in score_of.items():
        sc[r] = v
    cards = shot_cards(snap, rows, sc)
    out = []
    for b, (ch, al) in zip(beats, picks):
        out.append({"i": b.i, "text": b.text, "dur": b.dur,
                    "chosen": [cards[r] for r in ch], "alts": [cards[r] for r in al]})
    return {"beats": out}
