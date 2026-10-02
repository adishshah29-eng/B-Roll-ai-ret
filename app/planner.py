"""Script → beats → B-roll plan.

Pipeline per beat:  retrieve (relevance-gated, deduped)  →  TRUE check (verdict per candidate; `bad` is excluded,
`ok` gets a small evidence bonus, `warn` a small cost + auto label)  →  CUTS: choose the whole sequence with
Viterbi + local search (or the relevance-only greedy baseline).  YOURS (P7) will add terms to `score()`.
"""
import re
from dataclasses import dataclass
from datetime import date

import numpy as np

from . import cuts, truth

CAND_K = 10
CAND_K_TRUTH = 24            # fetch more candidates when contradicting ones will be removed
LONG_BEAT_S = 6.0
MIN_BEAT_S = 2.0
MAX_REJECTED_SHOWN = 4
DP_K = 8                      # candidates per slot handed to the sequence optimiser
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
    for k, b in enumerate(beats):
        b.dur = round(max(b.dur, MIN_BEAT_S), 2)
        b.i = k
    return beats


def score(beat, row, rel):
    """Single place where pillars combine. P5: relevance already includes the TRUE evidence delta."""
    return rel


def build_slots(beats, cands_per_beat, rel_of, snap, feats, k=DP_K):
    """One slot per beat (two for long beats). Candidates = the beat's best `k` after the TRUE filter."""
    slots, owner = [], []
    for bi, (b, cands) in enumerate(zip(beats, cands_per_beat)):
        top = sorted(cands, key=lambda c: -score(b, c[0], c[1]))[:k]
        nodes = []
        for r, adj in top:
            sid = int(snap.ids[r])
            key = int(snap.file_id[r]) if snap.file_id[r] >= 0 else 1_000_000 + int(snap.stock_id[r])
            nodes.append(cuts.Node(r, score(b, r, adj), rel_of.get(r, adj), snap.E[r], key, float(snap.t0[r]),
                                   str(snap.size[r]), feats.get(sid)))
        for _ in range(2 if b.dur > LONG_BEAT_S else 1):
            slots.append(list(nodes))
            owner.append(bi)
    return slots, owner


def plan(searcher, script: str, wpm: int = 150, use_truth: bool = True, today: str | None = None,
         use_cuts: bool = True, cut_weight: float | None = None) -> dict:
    from .search import shot_cards
    snap = searcher.holder.get()
    beats = split_beats(script, wpm)
    if not beats:
        return {"beats": []}
    w = cuts.CUT_WEIGHT if cut_weight is None else cut_weight
    searcher.encode_many([b.text for b in beats])             # one batch for the whole script
    raw = [searcher.candidates(b.text, k=CAND_K_TRUTH) for b in beats]
    rel_of = {}                                               # displayed score = pure relevance
    for cl in raw:
        for r, rel in cl:
            rel_of.setdefault(r, rel)

    claims = [truth.Claims() for _ in beats]
    verdicts, rejected = {}, [[] for _ in beats]
    cands = raw
    if use_truth:
        today_d = date.fromisoformat(today) if today else date.today()
        claims = truth.inherit_places([truth.extract_claims(b.text) for b in beats])
        facts = truth.fetch_facts({int(snap.ids[r]) for cl in raw for r, _ in cl})
        cands = []
        for bi, cl in enumerate(raw):
            kept = []
            for r, rel in cl:
                v = truth.verdict(claims[bi], facts.get(int(snap.ids[r]), {}), today_d)
                verdicts[(bi, r)] = v
                if v.status == "bad":
                    rejected[bi].append(r)
                else:
                    kept.append((r, rel + v.delta))
            cands.append(kept)

    # ---- CUTS: pick the sequence --------------------------------------------------------------------------
    feats = cuts.fetch_feats({int(snap.ids[r]) for cl in cands for r, _ in cl})
    slots, owner = build_slots(beats, cands, rel_of, snap, feats)
    greedy_pick = cuts.greedy(slots)
    cut_pick = cuts.plan_sequence(slots, w)
    picked = cut_pick if use_cuts else greedy_pick
    summary = {"mode": "cuts" if use_cuts else "greedy", "weight": w,
               "cuts": cuts.report(cut_pick), "greedy": cuts.report(greedy_pick)}

    per_beat = [[] for _ in beats]                           # chosen Nodes per beat, in timeline order
    for node, bi in zip(picked, owner):
        if node is not None:
            per_beat[bi].append(node)
    flat = [n for ns in per_beat for n in ns]
    trans = {id(b): cuts.transition(a, b) for a, b in zip(flat, flat[1:])}      # keyed by the *later* node

    picks = []
    for bi, b in enumerate(beats):
        ch = [n.row for n in per_beat[bi]]
        alts = [r for r, _ in sorted(cands[bi], key=lambda c: -score(b, c[0], c[1])) if r not in ch][:8]
        picks.append((ch, alts))

    rows = sorted({r for ch, al in picks for r in ch + al} | {r for rj in rejected for r in rj[:MAX_REJECTED_SHOWN]})
    sc = np.zeros(len(snap))
    for r, v in rel_of.items():
        sc[r] = v
    cards = shot_cards(snap, rows, sc)

    def with_verdict(bi, r):
        c = dict(cards[r])
        v = verdicts.get((bi, r))
        if v is not None:
            c["verdict"] = v.to_dict()
            c["label"] = v.label
        return c

    out, n_rej = [], 0
    for bi, (b, (ch, al)) in enumerate(zip(beats, picks)):
        rej = rejected[bi]
        n_rej += len(rej)
        chosen_cards = []
        for node in per_beat[bi]:
            c = with_verdict(bi, node.row)
            t = trans.get(id(node))
            if t is not None:
                c["cut"] = {"cost": round(t.cost, 3), "flags": t.flags}
            per = b.dur / max(len(per_beat[bi]), 1)
            peak = node.feat.peak_t if node.feat else None
            tin = cuts.smart_trim(c["t_start"], c["t_end"], peak, per)
            if tin != c["t_start"]:
                c["trim_in"] = round(tin, 2)
            chosen_cards.append(c)
        out.append({
            "i": b.i, "text": b.text, "dur": b.dur, "claims": claims[bi].to_dict() if use_truth else None,
            "chosen": chosen_cards, "alts": [with_verdict(bi, r) for r in al],
            "rejected": [with_verdict(bi, r) for r in rej[:MAX_REJECTED_SHOWN]], "n_rejected": len(rej),
        })
    return {"beats": out, "truth": {"enabled": use_truth, "rejected_total": n_rej}, "sequence": summary}
