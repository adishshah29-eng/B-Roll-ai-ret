# CUTS pillar: as built (P6)

Code: `app/indexer/cutfeat.py` (features) · `app/cuts.py` (transition scoring, Viterbi, local search, trim, report) ·
`app/planner.py` (slots + A/B) · `eval/eval_cuts.py` (measurement). Tests: `tests/test_cuts.py` (28).

## What it does
A script becomes a *sequence*, not a list of independently best shots. Every transition between consecutive clips is scored:

| Term | Meaning | Weight (raw) |
|---|---|---|
| jump | same take, close in time, near-identical framing; or an identical look from another file | ×2.0 |
| flip | screen direction reverses (A's out-motion vs B's in-motion; needs optical flow) | ×1.0 |
| exposure | brightness jump `\|tail luma(A) − head luma(B)\|` (flag > 0.25) | ×0.8 |
| colour | colour-temperature jump (flag > 0.20) | ×0.5 |
| subject | horizontal jump of the subject position | ×0.3 |
| same size | two wides / two close-ups in a row | +0.6 |
| progress | wide → medium → close (establish → detail) | −0.4 |
| continuity | motion continues in the same direction | −0.2 |

`J = Σ unary − CUT_WEIGHT · Σ cost/4 − repeat penalty`; **Viterbi** finds the optimum of the chain in O(slots·K²) (K = 8 candidates per slot),
a **local search** pass removes shots repeated far apart. Unary = relevance + TRUE evidence bonus, so TRUE and CUTS optimise together.
Long beats (> 6 s) get two slots so size progression can happen inside a beat. **Smart trim** starts a clip so its motion peak lands ~40 % in.

## Features (index time → query time is lookups only)
- Local clips (229 shots): head/tail optical flow (Farneback, 160 px), luma, warmth, saliency centroid, motion peak. ~0.2–0.5 s/shot.
- Stock shots (1,653): from the stored thumbnail only (luma, warmth, saliency); flow = 0, `approx=1`, so flips cannot occur between stock clips.
- New files get `cutfeat` jobs automatically after OCR (priority 9). `python -m app.indexer.cutfeat --enqueue-all | --approx`.

## Measured (eval/eval_cuts.py: 15 scripts incl. Hindi and dense single-topic, 52 transitions per strategy)
| CUT_WEIGHT | same-size repeats | size progressions | problems (jump+flip+exposure+colour) | mean relevance lost |
|---|---|---|---|---|
| greedy (relevance only) | 21 | 12 | 26 | – |
| 0.06 | 11 | 20 | −25 % | 0.7 % |
| **0.25 (default)** | **1** | **27** | **−42 %** | **1.6 %** |
| 1.00 | 1 | 27 | −78 % | 2.0 % |
UI offers *balanced* (0.25), *smoothest* (0.8) and *relevance only*.

## Honest limits
- Greedy rarely produced jump cuts (1) or flips (0) on this library, because retrieval already de-duplicates near-copies and flips need flow
  (local clips only). The plan's "≥ 50 % fewer jump/flip" target cannot be demonstrated here; unit tests prove those terms work
  (`test_cut_aware_trades_…`, `test_viterbi_matches_brute_force_optimum`, `test_report_counts_problems`). The measurable wins are
  grammar (same-size repeats, progression) and exposure / colour continuity.
- At 0.25, two of 15 scripts (`tech`, `old street`) trade one brightness/colour shift for better shot-size structure: the objective, not a bug.
- Head/tail features describe the shot's own edges; a trimmed clip starting mid-shot only approximates them (trim is used only when a shot is ≥ 1 s longer than the beat).
- The A/B uses the same candidate slots for both strategies, so differences are purely the sequencing.

## UI
Script tab: mode selector, A/B summary (problems / same-size repeats / progressions / relevance vs relevance-only), per-clip transition chips
(✓ clean cut · ✓ size progression · ⚠ jump · ⚠ direction flip · ⚠ brightness jump · ⚠ colour shift · = same size), and **▶ Play sequence**
(plays the chosen clips back to back; downloads stock clips first with a 15 s cap, still image if a clip can't load).
Note: Chrome pauses video in a hidden tab/pane, so playback can only be judged with the app visible.
