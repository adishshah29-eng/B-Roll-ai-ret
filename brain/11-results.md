# Results, YOURS (P7), integration (P8), hardening (P9)

## YOURS: Edit Memory (as built)
Code: `app/memory.py` · routes `/api/memory/{import,status}`, `/api/feedback`, `DELETE /api/memory` · Memory tab · "Use my edit history" toggle.
- **Teach sources:** an imported past timeline (XML/EDL) + its script → each clip placed under a line becomes a (line, shot) lesson; every **swap** (chosen vs passed-over) and every **XML export** (accepted) teaches too. No labelling.
- **Use:** a new line is matched to similar past lines (cosine ≥ 0.55); shots chosen then get up to **+0.04** relevance, visually near-identical shots (cos > 0.88) get half; passed-over shots get up to −0.03.
  House style (share of each shot size among your picks) adds ≤ +0.02 once ≥ 5 lessons exist. Cold start = no effect.
- **Not built (cut for time):** the logistic-regression re-ranker from the plan; kNN boost + style prior replaced it. No leave-one-project-out split; the effect is shown with a simulated editor instead (below).

## P8: one formula + explanations
`unary = relevance + TRUE evidence delta + memory boost + style prior` → CUTS optimises the sequence on top.
Every chosen clip carries `why`: relevance · truth evidence · auto label · cut quality · memory ("chosen 3x in your past edits" / "matches your style").
Each pillar has its own switch (Script tab: TRUE checkbox, cut-mode selector, memory checkbox) and a matching API flag (`use_truth`, `use_cuts`, `use_memory`).

## Ablation (`python -m eval.eval_all --seed-memory`; 19 scripts, 2,007-shot library, CPU laptop)
| configuration | contradicting shots | cut problems | same-size repeats | progressions | relevance | close-ups* | p50 / p95 plan |
|---|---|---|---|---|---|---|---|
| baseline | 10 | 22 | 26 | 14 | 0.296 | 2 % | 141 / 213 ms |
| + TRUE | **0** | 19 | 28 | 12 | 0.293 | 3 % | 26 / 59 ms |
| + CUTS | 9 | 15 | **4** | **32** | 0.292 | 11 % | 16 / 44 ms |
| + YOURS | 7 | 22 | 22 | 17 | 0.290 | **18 %** | 20 / 54 ms |
| **all three** | **0** | **9** | **2** | **31** | 0.287 | 17 % | 30 / 64 ms |
\* taste of a **simulated** editor (always picks local close-ups), learned from 3 synthetic past projects (12 lessons). It shows the mechanism works;
it is not evidence about real editors. Real past projects + a real user test are still needed.
"Contradicting" = chosen shots the TRUE rules reject for their own line, judged identically for every row (circular for TRUE by design: the rules are the spec;
the evidence that the rules are *right* is the hand-checked cases in `brain/09-truth.md`, not this number).
All pillars together cost ~3 % mean relevance.

## P9: hardening done / not done
Done: `GET /api/health` · `eval/backup.py` (index snapshot + restore, 175 MB) · README with run + results · per-pillar toggles · UI error messages for API failures · stale-cache lesson (hard reload after UI edits).
**Not done (time):** the 100+ query Indic benchmark and the 30-case Contradiction Set were not labelled (no hand-labelled recall/precision numbers beyond the unit-tested rules);
tests for YOURS/P8 were skipped on request; cluster-threshold tuning ("rain on the road" still gives few variation groups); LAN test from a second laptop; Windows firewall prompt.

## Known weaknesses to say out loud
Weather is a weak signal (excludes only at ≥ 0.97). Place evidence needs a title, tag, signboard or GPS; plain stock stays "unverified". Hindi signboards are not read.
Stock clips have thumbnail-only cut features (no flips). The synthetic trap clips are not real footage. XML import into Premiere/Resolve has never been opened in the real apps.
