"""Script → beats → B-roll plan.

Pipeline per beat:  retrieve (relevance-gated, deduped)  →  TRUE check (verdict per candidate; `bad` is excluded,
`ok` gets a small evidence bonus, `warn` a small cost + auto label)  →  CUTS: choose the whole sequence with
Viterbi + local search (or the relevance-only greedy baseline).  YOURS (P7) will add terms to `score()`.
"""
import math
import re
from dataclasses import dataclass
from datetime import date

import numpy as np

from . import cuts, licence, memory, truth

CAND_K = 10
CAND_K_TRUTH = 24            # fetch more candidates when contradicting ones will be removed
LONG_BEAT_S = 6.0
MIN_BEAT_S = 2.0
MAX_REJECTED_SHOWN = 4
VERTICAL_BONUS = 0.03         # native 9:16 clips win ties in Shorts mode
MAX_SLOTS = 5
MIN_BEAT_CUT_S = 1.5
DP_K = 8                      # candidates per slot handed to the sequence optimiser
SENT_SPLIT = re.compile(r"(?<=[.!?।])\s+|\n+")


@dataclass
class Beat:
    i: int
    text: str                    # narration (TRUE claims, memory)
    dur: float
    query: str | None = None     # visual query for retrieval (editor/LLM); defaults to the narration


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


def fit_to_target(beats: list, target_s: float | None) -> list:
    """Ad / short cuts: condense to ~target seconds. Long scripts keep the opening line, the closing line and evenly spaced
    lines in between (about 2.5 s each); durations are then scaled to hit the target (stretch capped at 1.6x)."""
    if not target_s or not beats:
        return beats
    total = sum(b.dur for b in beats)
    if total > target_s * 1.05:
        k = max(2, min(len(beats), int(target_s // 2.5)))
        if k < len(beats):
            idx = sorted({round(i * (len(beats) - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
            beats = [beats[i] for i in idx]
    base = sum(b.dur for b in beats)
    scale = min(target_s / base, 1.6) if base else 1.0
    for b in beats:
        b.dur = round(max(MIN_BEAT_CUT_S, b.dur * scale), 2)
    for k, b in enumerate(beats):
        b.i = k
    return beats


def score(beat, row, rel):
    """Single place where pillars combine. P5: relevance already includes the TRUE evidence delta."""
    return rel


def build_slots(beats, cands_per_beat, rel_of, snap, feats, k=DP_K, max_shot=LONG_BEAT_S):
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
        for _ in range(max(1, min(MAX_SLOTS, math.ceil(b.dur / max_shot)))):
            slots.append(list(nodes))
            owner.append(bi)
    return slots, owner


def _why(c: dict) -> list:
    """One short, honest line per reason this clip was chosen (relevance, truth, cut, memory)."""
    w = [f"relevance {c['score']:.2f}"]
    v = c.get("verdict")
    if v and v["status"] in ("ok", "warn") and v["evidence"]:
        w.append(v["evidence"][0])
    if c.get("label"):
        w.append(f"auto label: {c['label']}")
    cut = c.get("cut")
    if cut:
        w.append("size progression" if "progress" in cut["flags"] else "clean cut" if not cut["flags"] else "cuts: " + ", ".join(cut["flags"]))
    lic = c.get("licence")
    if lic and lic["class"] in ("attribution", "caution", "restricted", "unknown"):
        w.append(f"licence: {lic['label']}")
    m = c.get("memory")
    if m:
        w.append(f"chosen {m['hits']}x in your past edits" if m["hits"] else ("matches your style" if m["bonus"] > 0 else "you passed on similar shots"))
    return w


def plan(searcher, script: str, wpm: int = 150, use_truth: bool = True, today: str | None = None,
         use_cuts: bool = True, cut_weight: float | None = None, use_memory: bool = True,
         niche: str | None = None, commercial_only: bool = False, target_s: float | None = None,
         max_shot_s: float | None = None, vertical: bool = False, beats: list | None = None) -> dict:
    from .search import shot_cards
    snap = searcher.holder.get()
    beats = beats if beats is not None else split_beats(script, wpm)   # editor mode passes timed slots
    if not beats:
        return {"beats": []}
    beats = fit_to_target(beats, target_s)
    w = cuts.CUT_WEIGHT if cut_weight is None else cut_weight
    max_shot = max_shot_s or LONG_BEAT_S
    cand_filters = {"licence": "commercial"} if commercial_only else None
    searcher.encode_many([b.query or b.text for b in beats])             # one batch for the whole script
    raw = [searcher.candidates(b.query or b.text, k=CAND_K_TRUTH, filters=cand_filters, niche=niche) for b in beats]
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

    # ---- YOURS: edit memory (past choices + house style) -----------------------------------------------------
    mem_info, st = {}, memory.style()
    use_mem = use_memory and (st["n"] > 0 or st["negatives"] > 0)
    if use_mem:
        adj = []
        for bi, cl in enumerate(cands):
            bmap = memory.boost(searcher, beats[bi].text, [r for r, _ in cl])
            new = []
            for r, rel in cl:
                bonus, hits = bmap.get(r, (0.0, 0))
                bonus += memory.style_bonus(str(snap.size[r]), st)
                mem_info[(bi, r)] = (bonus, hits)
                new.append((r, rel + bonus))
            adj.append(new)
        cands = adj

    if vertical:                                              # Shorts: prefer native 9:16, others get a crop hint later
        cands = [[(r, rel + (VERTICAL_BONUS if snap.orient[r] == "9:16" else 0.0)) for r, rel in cl] for cl in cands]

    # ---- CUTS: pick the sequence --------------------------------------------------------------------------
    feats = cuts.fetch_feats({int(snap.ids[r]) for cl in cands for r, _ in cl})
    slots, owner = build_slots(beats, cands, rel_of, snap, feats, max_shot=max_shot)
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
            mi = mem_info.get((bi, node.row))
            if mi and (mi[1] or abs(mi[0]) > 1e-6):
                c["memory"] = {"hits": mi[1], "bonus": round(mi[0], 4)}
            if vertical and c.get("orientation") != "9:16":
                c["reframe"] = {"crop_x": round(node.feat.sal_x if node.feat else 0.5, 2)}
            c["why"] = _why(c)
            chosen_cards.append(c)
        out.append({
            "i": b.i, "text": b.text, "dur": b.dur, "claims": claims[bi].to_dict() if use_truth else None,
            "chosen": chosen_cards, "alts": [with_verdict(bi, r) for r in al],
            "rejected": [with_verdict(bi, r) for r in rej[:MAX_REJECTED_SHOWN]], "n_rejected": len(rej),
        })
    chosen_all = [(b["i"], c) for b in out for c in b["chosen"]]
    counts = {}
    for _, c in chosen_all:
        counts[c["licence"]["class"]] = counts.get(c["licence"]["class"], 0) + 1
    unsafe = [{"beat": bi, "file": c["file"], "class": c["licence"]["class"], "label": c["licence"]["label"]}
              for bi, c in chosen_all if not c["licence"]["commercial"]]
    return {"beats": out, "truth": {"enabled": use_truth, "rejected_total": n_rej}, "sequence": summary,
            "licences": {"counts": counts, "unsafe": unsafe, "commercial_ok": not unsafe, "filtered": commercial_only},
            "format": {"target_s": target_s, "actual_s": round(sum(b["dur"] for b in out), 1), "max_shot_s": max_shot,
                       "vertical": vertical, "niche": niche, "beats": len(out)},
            "memory": {"enabled": use_mem, "pairs": st["n"], "style": st["size_mix"]}}
