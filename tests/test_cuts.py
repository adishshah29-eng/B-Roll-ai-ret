"""CUTS pillar: transition scoring + sequence optimiser. Pure logic with synthetic shots (no DB, no models)."""
import numpy as np
import pytest

from app import cuts
from app.cuts import Feat, Node


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def feat(head=(0, 0), tail=(0, 0), hl=0.5, tl=0.5, hw=0.0, tw=0.0, sx=0.5, peak=None):
    return Feat(head, tail, hl, tl, hw, tw, sx, False, peak)


_row = iter(range(10**6))


def node(rel=0.3, key=1, t0=0.0, size="wide", emb=None, f=None, row=None, unary=None):
    emb = unit([1, 0, 0]) if emb is None else emb
    return Node(next(_row) if row is None else row, rel if unary is None else unary, rel, emb, key, t0, size, f)


# ---------- transition scoring ----------
def test_jump_cut_same_take_similar_framing():
    a = node(key=1, t0=0, emb=unit([1, 0, 0]))
    b = node(key=1, t0=4, emb=unit([0.99, 0.05, 0]))
    far_different = node(key=1, t0=40, emb=unit([0.6, 0.8, 0]))   # same file, 40 s later, looks different: a new moment
    far_identical = node(key=1, t0=40, emb=unit([0.99, 0.05, 0]))  # ...but an identical look is a jump cut at any distance
    other = node(key=2, t0=4, emb=unit([0, 1, 0]))
    assert "jump" in cuts.transition(a, b).flags
    assert "jump" not in cuts.transition(a, far_different).flags
    assert "jump" in cuts.transition(a, far_identical).flags
    assert "jump" not in cuts.transition(a, other).flags


def test_identical_look_from_another_file_still_counts_as_a_repeat():
    a, b = node(key=1, emb=unit([1, 0, 0])), node(key=2, emb=unit([1, 0.01, 0]))
    assert "jump" in cuts.transition(a, b).flags


def test_screen_direction_flip_vs_continuity():
    a = node(f=feat(tail=(3, 0)), emb=unit([1, 0, 0]), key=1)
    right = node(f=feat(head=(3, 0)), emb=unit([0, 1, 0]), key=2)
    left = node(f=feat(head=(-3, 0)), emb=unit([0, 0, 1]), key=3)
    still = node(f=feat(head=(0.05, 0)), emb=unit([0, 1, 1]), key=4)
    assert "flip" in cuts.transition(a, left).flags
    assert "flip" not in cuts.transition(a, right).flags
    assert cuts.transition(a, right).cost < cuts.transition(a, still).cost < cuts.transition(a, left).cost


def test_exposure_and_colour_jumps():
    a = node(f=feat(tl=0.9, tw=0.3), key=1, emb=unit([1, 0, 0]))
    b = node(f=feat(hl=0.2, hw=-0.2), key=2, emb=unit([0, 1, 0]))
    t = cuts.transition(a, b)
    assert "exposure" in t.flags and "colour" in t.flags


def test_size_progression_is_rewarded_and_repeats_penalised():
    wide, med, close = node(size="wide", key=1), node(size="medium", key=2), node(size="close", key=3)
    for n, e in zip((wide, med, close), ([1, 0, 0], [0, 1, 0], [0, 0, 1])):
        n.emb = unit(e)
    assert "progress" in cuts.transition(wide, med).flags and "progress" in cuts.transition(med, close).flags
    assert "progress" not in cuts.transition(wide, close).flags
    w2 = node(size="wide", key=4, emb=unit([1, 1, 0]))
    assert "same-size" in cuts.transition(wide, w2).flags
    assert cuts.transition(wide, med).cost < cuts.transition(wide, w2).cost


def test_missing_features_are_neutral_not_penalised():
    a, b = node(f=None, key=1, emb=unit([1, 0, 0])), node(f=None, key=2, emb=unit([0, 1, 0]), size="medium")
    t = cuts.transition(a, b)
    assert not {"flip", "exposure", "colour"} & set(t.flags)


def test_same_shot_twice_is_forbidden():
    a = node(row=7)
    assert cuts.transition(a, a).cost > 1e3


# ---------- optimiser ----------
def random_slots(rng, n_slots=4, k=3, share_rows=False):
    slots, rows = [], iter(range(1000, 10**6))
    for s in range(n_slots):
        cands = []
        for _ in range(k):
            emb = unit(rng.normal(size=3))
            f = feat(head=tuple(rng.normal(size=2) * 3), tail=tuple(rng.normal(size=2) * 3),
                     hl=float(rng.random()), tl=float(rng.random()), hw=float(rng.normal() * .2), tw=float(rng.normal() * .2),
                     sx=float(rng.random()))
            cands.append(Node(next(rows), float(0.25 + rng.random() * 0.1), 0.3, emb, int(rng.integers(1, 3)),
                              float(rng.integers(0, 3) * 4), str(rng.choice(["wide", "medium", "close"])), f))
        slots.append(cands)
    return slots


@pytest.mark.parametrize("seed", range(8))
def test_viterbi_matches_brute_force_optimum(seed):
    slots = random_slots(np.random.default_rng(seed))
    got, want = cuts.viterbi(slots), cuts.brute_force(slots)
    assert cuts.objective(got) == pytest.approx(cuts.objective(want), abs=1e-9)


@pytest.mark.parametrize("seed", range(8))
def test_plan_is_never_worse_than_greedy_and_has_no_repeats(seed):
    slots = random_slots(np.random.default_rng(100 + seed), n_slots=5, k=4)
    plan = [n for n in cuts.plan_sequence(slots) if n]
    base = [n for n in cuts.greedy(slots) if n]
    assert cuts.objective(plan) >= cuts.objective(base) - 1e-9
    assert len({n.row for n in plan}) == len(plan)


def test_refine_removes_a_shot_repeated_far_apart():
    shared = node(row=1, rel=0.34, key=1, t0=0, emb=unit([1, 0, 0]), size="wide")
    alt1 = node(row=2, rel=0.30, key=2, emb=unit([0, 1, 0]), size="wide")
    mid = node(row=3, rel=0.30, key=3, emb=unit([0, 0, 1]), size="medium")
    slots = [[shared, alt1], [mid], [shared, alt1]]
    plan = cuts.plan_sequence(slots)
    assert len({n.row for n in plan}) == 3


def test_cut_aware_trades_a_little_relevance_for_a_jump_cut_but_not_a_lot():
    first = node(row=1, rel=0.30, key=1, t0=0, emb=unit([1, 0, 0]), size="wide")
    jumpy = node(row=2, rel=0.31, key=1, t0=4, emb=unit([0.99, 0.05, 0]), size="wide")      # same take, same framing
    clean = node(row=3, rel=0.30, key=2, t0=0, emb=unit([0, 1, 0]), size="medium")
    assert cuts.plan_sequence([[first], [jumpy, clean]])[1] is clean                          # tiny relevance gap: avoid the jump
    # a relevance gap larger than the whole penalty must still win (derived from the live weight, not hard-coded)
    penalty = cuts.CUT_WEIGHT * (cuts.transition(first, jumpy).cost - cuts.transition(first, clean).cost)
    assert penalty > 0.01
    great_but_jumpy = node(row=4, rel=0.30 + penalty * 1.5, key=1, t0=4, emb=unit([0.99, 0.05, 0]), size="wide")
    assert cuts.plan_sequence([[first], [great_but_jumpy, clean]])[1] is great_but_jumpy


def test_empty_slots_are_bridged_and_reported_as_none():
    a, b = node(row=1, key=1), node(row=2, key=2, emb=unit([0, 1, 0]), size="medium")
    out = cuts.plan_sequence([[a], [], [b]])
    assert out[0] is a and out[1] is None and out[2] is b
    assert cuts.plan_sequence([[], []]) == [None, None]


def test_report_counts_problems():
    a = node(row=1, key=1, t0=0, emb=unit([1, 0, 0]), f=feat(tail=(3, 0), tl=0.9))
    b = node(row=2, key=1, t0=4, emb=unit([0.99, 0.05, 0]), f=feat(head=(-3, 0), hl=0.1))
    r = cuts.report([a, b])
    assert r["transitions"] == 1 and r["jump"] == 1 and r["flip"] == 1 and r["exposure"] == 1 and r["problems"] == 3


# ---------- trimming ----------
def test_smart_trim():
    assert cuts.smart_trim(10, 14, 12, 3.5) == 10                    # barely longer than the beat: start at the head
    assert cuts.smart_trim(10, 30, None, 4) == 10                    # unknown peak
    t = cuts.smart_trim(10, 30, 20, 5)
    assert t == pytest.approx(18.0)                                  # peak lands 40 % into the clip
    assert cuts.smart_trim(10, 30, 29.5, 5) == 25                    # clamped so the clip stays inside the shot
