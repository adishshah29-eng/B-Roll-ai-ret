"""CUTS pillar, query side: choose the whole B-roll sequence so consecutive shots CUT well together.

    J(sequence) = Σ unary(slot, shot)  −  CUT_WEIGHT · Σ transition_cost(shot_i → shot_i+1)  −  repeat_penalty

unary  = relevance (+ TRUE evidence bonus), computed by the planner
transition_cost (normalised to about [-0.2, 1]):
    jump        same take, close in time, near-identical framing (or an identical look from another file)  ×2.0
    flip        screen direction reverses (out-motion of A vs in-motion of B)                                ×1.0
    exposure    |tail luma of A − head luma of B|                                                            ×0.8
    colour      |tail warmth of A − head warmth of B|                                                        ×0.5
    subject     horizontal jump of the subject position                                                      ×0.3
    same size   two wides in a row, two close-ups in a row                                                   +0.6
    progress    wide→medium→close (establish → detail)                                                       −0.4
    continuity  motion continues in the same direction                                                       −0.2
Viterbi gives the optimum of the chain in O(slots × K²); a local-search pass then removes repeated shots globally.
Everything is explainable: every transition returns the flags that explain its cost.
"""
import itertools
from dataclasses import dataclass, field

import numpy as np

from . import db

CUT_WEIGHT = 0.25          # relevance units per unit of normalised transition cost; tuned in eval/eval_cuts.py (D24)
NORM = 4.0
REPEAT_PENALTY = 1.0
FLOW_MIN = 0.25            # px of mean motion per 0.3 s at 160 px width below which a shot counts as static
JUMP_WINDOW_S = 10.0
SIZE_RANK = {"aerial": 1, "wide": 1, "medium": 2, "close": 3, "detail": 4}
W = {"jump": 2.0, "flip": 1.0, "exposure": 0.8, "colour": 0.5, "subject": 0.3, "same_size": 0.6,
     "progress": -0.4, "continuity": -0.2}


@dataclass
class Feat:
    head: tuple            # (dx, dy)
    tail: tuple
    head_luma: float
    tail_luma: float
    head_warmth: float
    tail_warmth: float
    sal_x: float
    approx: bool = False
    peak_t: float | None = None

    @staticmethod
    def from_row(r):
        if r is None:
            return None
        return Feat((r["head_dx"] or 0.0, r["head_dy"] or 0.0), (r["tail_dx"] or 0.0, r["tail_dy"] or 0.0),
                    r["head_luma"] or 0.0, r["tail_luma"] or 0.0, r["head_warmth"] or 0.0, r["tail_warmth"] or 0.0,
                    r["sal_x"] if r["sal_x"] is not None else 0.5, bool(r["approx"]), r["peak_t"])


@dataclass
class Node:
    """One candidate shot for one slot."""
    row: int                       # snapshot row (identity of the shot)
    unary: float                   # relevance + evidence bonus
    rel: float                     # pure relevance (for reporting)
    emb: np.ndarray
    key: int                       # source identity (file or stock item)
    t0: float
    size: str
    feat: Feat | None = None


@dataclass
class Transition:
    cost: float                    # normalised
    flags: list = field(default_factory=list)
    parts: dict = field(default_factory=dict)


def _unit(v):
    m = float(np.hypot(*v))
    return (v[0] / m, v[1] / m) if m >= FLOW_MIN else None


def transition(a: Node, b: Node) -> Transition:
    if a.row == b.row:
        return Transition(1e6, ["same-shot"], {})
    parts, flags = {}, []
    cos = float(a.emb @ b.emb)
    if a.key == b.key and abs(a.t0 - b.t0) < JUMP_WINDOW_S:
        jump = float(np.clip((cos - 0.8) / 0.15, 0.0, 1.0))
    else:
        jump = 0.7 if cos > 0.95 else 0.0                 # an identical look from another file is still a repeat
    if jump >= 0.5:
        flags.append("jump")
    parts["jump"] = jump

    fa, fb = a.feat, b.feat
    flip = cont = exposure = colour = subject = 0.0
    if fa and fb:
        ua, ub = _unit(fa.tail), _unit(fb.head)
        if ua and ub:
            dot = ua[0] * ub[0] + ua[1] * ub[1]
            flip, cont = max(0.0, -dot), max(0.0, dot)
            if flip >= 0.3:
                flags.append("flip")
        exposure = abs(fa.tail_luma - fb.head_luma)
        colour = abs(fa.tail_warmth - fb.head_warmth)
        subject = abs(fa.sal_x - fb.sal_x)
        if exposure > 0.25:
            flags.append("exposure")
        if colour > 0.20:
            flags.append("colour")
    parts.update(flip=flip, continuity=cont, exposure=exposure, colour=colour, subject=subject)

    ra, rb = SIZE_RANK.get(a.size), SIZE_RANK.get(b.size)
    same = float(a.size == b.size and a.size in SIZE_RANK)
    prog = float(ra is not None and rb is not None and rb == ra + 1)
    if same:
        flags.append("same-size")
    if prog:
        flags.append("progress")
    parts.update(same_size=same, progress=prog)

    raw = sum(W[k] * parts[k] for k in W)
    return Transition(raw / NORM, flags, parts)


def objective(seq: list, w=CUT_WEIGHT) -> float:
    """seq: list of Node (one per non-empty slot, in order)."""
    j = sum(n.unary for n in seq)
    j -= w * sum(transition(a, b).cost for a, b in zip(seq, seq[1:]) if a.row != b.row)
    dup = len(seq) - len({n.row for n in seq})
    return j - REPEAT_PENALTY * dup


def viterbi(slots: list, w=CUT_WEIGHT) -> list:
    """slots: list of candidate lists (all non-empty). Returns the best node per slot for the chain objective
    (adjacent identical shots forbidden; global repeats are handled by `refine`)."""
    if not slots:
        return []
    score = [np.array([n.unary for n in slots[0]], dtype=np.float64)]
    back = []
    for s in range(1, len(slots)):
        prev, cur = slots[s - 1], slots[s]
        T = np.array([[transition(a, b).cost for b in cur] for a in prev])      # (|prev|, |cur|)
        cand = score[-1][:, None] - w * T
        best_i = cand.argmax(axis=0)
        score.append(np.array([n.unary for n in cur]) + cand[best_i, np.arange(len(cur))])
        back.append(best_i)
    j = int(score[-1].argmax())
    path = [j]
    for s in range(len(slots) - 1, 0, -1):
        j = int(back[s - 1][j])
        path.append(j)
    path.reverse()
    return [slots[s][i] for s, i in enumerate(path)]


def refine(slots: list, seq: list, w=CUT_WEIGHT, passes=4) -> list:
    """Coordinate-descent: swap single positions for better candidates while the objective improves.
    This is what removes shots repeated far apart (which a chain DP cannot see)."""
    seq = list(seq)
    best = objective(seq, w)
    for _ in range(passes):
        improved = False
        for p in range(len(seq)):
            for cand in slots[p]:
                if cand.row == seq[p].row:
                    continue
                trial = seq[:p] + [cand] + seq[p + 1:]
                v = objective(trial, w)
                if v > best + 1e-9:
                    seq, best, improved = trial, v, True
        if not improved:
            break
    return seq


def plan_sequence(slots: list, w=CUT_WEIGHT) -> list:
    """slots[i] = candidate Nodes for slot i (possibly empty). Returns a list aligned with slots:
    the chosen Node, or None for empty slots. Empty slots are skipped; the chain bridges across them."""
    idx = [i for i, c in enumerate(slots) if c]
    if not idx:
        return [None] * len(slots)
    nonempty = [slots[i] for i in idx]
    seq = refine(nonempty, viterbi(nonempty, w), w)
    out = [None] * len(slots)
    for i, n in zip(idx, seq):
        out[i] = n
    return out


def greedy(slots: list) -> list:
    """Baseline = what P4 did: best relevance per slot, no repeats, blind to how shots cut."""
    used, out = set(), []
    for cands in slots:
        pick = next((n for n in sorted(cands, key=lambda n: -n.unary) if n.row not in used), None)
        if pick:
            used.add(pick.row)
        out.append(pick)
    return out


def brute_force(slots: list, w=CUT_WEIGHT) -> list:
    """Exact optimum of `objective` over every combination (tests only: exponential)."""
    best, best_seq = -1e18, None
    for combo in itertools.product(*slots):
        v = objective(list(combo), w)
        if v > best:
            best, best_seq = v, list(combo)
    return best_seq


def report(seq: list) -> dict:
    """Quality summary of a chosen sequence (None entries are skipped)."""
    nodes = [n for n in seq if n is not None]
    tr = [transition(a, b) for a, b in zip(nodes, nodes[1:])]
    c = {k: sum(k in t.flags for t in tr) for k in ("jump", "flip", "exposure", "colour", "same-size", "progress")}
    return {"transitions": len(tr), **{k.replace("-", "_"): v for k, v in c.items()},
            "problems": c["jump"] + c["flip"] + c["exposure"] + c["colour"],
            "mean_rel": round(float(np.mean([n.rel for n in nodes])), 4) if nodes else 0.0,
            "cost": round(sum(t.cost for t in tr), 3)}


def smart_trim(t0: float, t1: float, peak_t: float | None, dur: float) -> float:
    """Source in-point for a clip of `dur` seconds from the shot [t0, t1]: start the clip so the motion peak lands
    about 40 % in. Shots barely longer than the beat start at their head (head/tail features describe that edge)."""
    if peak_t is None or (t1 - t0) < dur + 1.0:
        return t0
    return float(min(max(peak_t - 0.4 * dur, t0), t1 - dur))


def fetch_feats(shot_ids) -> dict:
    """shot id -> Feat (missing shots are simply absent: their feature terms are neutral)."""
    ids = [int(i) for i in shot_ids]
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    rows = db.conn().execute(f"SELECT * FROM cut_features WHERE shot_id IN ({q})", ids).fetchall()
    return {r["shot_id"]: Feat.from_row(r) for r in rows}
