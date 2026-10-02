"""Unit tests for the pure parts of the search funnel and segmentation (no models needed)."""
import numpy as np

from app.indexer.pipeline import Segmenter, merge_short
from app.search import cluster, dedupe, gate, mmr


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_gate_keeps_only_near_best():
    s = np.array([0.30, 0.29, 0.20, 0.10])
    assert gate(s, min_score=0.15, delta=0.08).tolist() == [True, True, False, False]


def test_gate_empty_and_floor():
    assert gate(np.array([])).size == 0
    assert not gate(np.array([0.05, 0.04]), min_score=0.18).any()


def test_dedupe_collapses_near_copies_same_take():
    a = unit([1, 0, 0]); b = unit([0.99, 0.05, 0]); c = unit([0, 1, 0])
    E = np.stack([a, b, c])
    kept = dedupe(np.array([0, 1, 2]), E, key=np.array([1, 1, 1]), t0=np.array([0.0, 4.0, 5.0]))
    assert kept == [0, 2]            # b is a near-copy of a, same file, 4 s apart


def test_dedupe_keeps_same_look_from_other_file():
    a = unit([1, 0, 0]); b = unit([0.99, 0.05, 0])
    kept = dedupe(np.array([0, 1]), np.stack([a, b]), key=np.array([1, 2]), t0=np.array([0.0, 0.0]))
    assert kept == [0, 1]


def test_mmr_lambda_zero_is_pure_relevance_and_one_prefers_diversity():
    E = np.stack([unit([1, 0, 0]), unit([0.98, 0.2, 0]), unit([0, 1, 0])])
    rel = np.array([0.30, 0.29, 0.20])
    assert mmr([0, 1, 2], rel, E, 3, 0.0) == [0, 1, 2]
    assert mmr([0, 1, 2], rel, E, 2, 0.9) == [0, 2]   # high λ skips the near-copy for the different shot


def test_cluster_groups_similar_and_separates_different():
    E = np.stack([unit([1, 0, 0]), unit([0.99, 0.1, 0]), unit([0, 1, 0]), unit([0.05, 1, 0])])
    groups = cluster([0, 1, 2, 3], E)
    sets = sorted(sorted(g) for g in groups)
    assert sets == [[0, 1], [2, 3]]


def test_segmenter_cuts_on_visual_change_and_window():
    seg = Segmenter(cut_sim=0.8, window_s=4.0, step=1.0)
    A, B = unit([1, 0, 0]), unit([0, 1, 0])
    g = np.zeros((36, 64), np.uint8)
    for t, e in [(0, A), (1, A), (2, A), (3, B), (4, B)]:
        seg.feed(float(t), e, g, b"")
    shots = seg.finish()
    assert [(s["t_start"], s["n"]) for s in shots] == [(0.0, 3), (3.0, 2)]
    seg2 = Segmenter(cut_sim=0.8, window_s=2.0, step=1.0)
    for t in range(5):
        seg2.feed(float(t), A, g, b"")
    assert [s["n"] for s in seg2.finish()] == [2, 2, 1]


def test_merge_short_folds_tail_into_previous():
    g = [np.zeros((36, 64), np.uint8)]
    e = unit([1, 0, 0])
    shots = [
        {"t_start": 0.0, "t_end": 4.0, "emb": e, "greys": g, "jpg": b"", "n": 4},
        {"t_start": 4.0, "t_end": 5.0, "emb": e, "greys": g, "jpg": b"", "n": 1},   # exactly 1 s: kept
        {"t_start": 5.0, "t_end": 5.04, "emb": e, "greys": g, "jpg": b"", "n": 1},  # tail sliver: merged
    ]
    out = merge_short(shots, duration=5.04)
    assert [(s["t_start"], round(s["t_end"], 2)) for s in out] == [(0.0, 4.0), (4.0, 5.04)]
