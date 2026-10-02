# Progress log

## Checklist
- [x] Problem statement final: True · Cuts · Yours ([FINAL_PROBLEM_STATEMENT.md](../FINAL_PROBLEM_STATEMENT.md))
- [x] P0 Setup: models ✅ (HI↔EN cos 0.979), 24 Pixabay test clips ✅ · TODO: own Indian footage + TRUE trap clips + 2 past projects
- [x] P1 Index: shots/embeddings/tags/thumbs/basic provenance ✅ idempotent + crash-safe · TODO cut features (P6), OCR (P5)
- [x] P2 Search ✅ gate/dedupe/MMR/clusters/labels/similar; cold 111 ms, cached 0.1 ms; 8 unit tests
- [x] P2b Open-source library ✅ Pixabay + Commons + Archive connectors, Tier-S ingest (1,500 clips), lazy hydration, export hydrates on demand + reports skipped clips
- [x] P3 API + UI ✅ search, variety slider, filter chips, preview (Range 206), Find similar, live status
- [x] P4 Script → plan → export ✅ greedy no-repeat planner, XML/EDL/SRT/credits, timeline importer, round-trip tests · TODO: real import test in Premiere/Resolve
- [x] P5 TRUE ✅ claims (EN+HI) · evidence (GPS/OCR/title/date/weather) · verdicts · place-context carry-over · FILE/STOCK labels → SRT · rejected drawer · provenance card · 5 trap clips · 38 TRUE tests (see 09-truth.md)
- [x] P6 CUTS ✅ cut features (229 local + 1,653 stock-thumbnail), transition scoring, Viterbi + local search, smart trim, A/B summary, transition chips, ▶ Play sequence · 28 tests (see 10-cuts.md)
- [x] P7 YOURS ✅ memory.py: timeline import + live feedback (swaps/exports) → boost + house style · Memory tab (see 11-results.md)
- [x] P8 Planner integration ✅ one formula, per-clip `why`, per-pillar toggles
- [~] P9 ablation table ✅ (eval/eval_all.py), health, backup, README ✅ · NOT done: 100-query Indic benchmark, Contradiction Set labelling, cluster tuning, LAN test, tests for P7/P8, rehearsal

## Log
| When | Note |
|---|---|
| 2026-10-02 | Problem statement pivoted from plain semantic search to the True/Cuts/Yours thesis for novelty |
| 2026-10-02 | P0–P4 built and verified. 24 clips → 151 shots. Gate tuned (D18). Plan 177 ms cold / 2 ms cached. 10 tests pass. |
| 2026-10-02 | P2b done. 1,858 searchable shots (own 151 · pixabay 682 · commons 725 · archive 300). Search 50–120 ms cold at that size (encode ≈ 50 ms, retrieval ≈ 1 ms). 14 tests pass. Real recorded dates flow into provenance (Commons: 1906, 1929, 2016…). |
| next | P5 TRUE → P6 CUTS → P7 YOURS → P8 → P9 |
| 2026-10-03 | P5 done. RapidOCR chosen (D19). Weather calibrated (indoor class; ✕ only at 0.97). Place context carry-over added after a Mumbai script picked Bangkok/Indonesia/Kerala clips. Mumbai demo plan: 30 wrong-place shots rejected with evidence, real *Aug 29 2017 Mumbai Floods* chosen. 52 tests pass. Bug caught: a literal-newline JS string had broken the whole UI after an earlier patch. |
| next | P6 CUTS → P7 YOURS → P8 → P9 |
| 2026-10-03 | P6 done. Weight 0.25 chosen from a measured sweep (same-size repeats 21→1, progressions 12→27, problems −42 %, relevance −1.6 %). Honest finding: jump/flip rarely occur on this library, so the ≥50 % target is not provable here. Found: Browser pane hidden ⇒ Chrome pauses video, so Play sequence can't be judged headlessly. 80 tests pass. |
| next | P7 YOURS (Edit Memory) → P8 integration/explanations → P9 benchmark + hardening |
| 2026-10-03 | P7+P8 built, P9 partly (30-minute sprint, tests skipped on request). All-three ablation: contradictions 10→0, cut problems 22→9, same-size repeats 26→2, progressions 14→31, relevance −3 %, p95 plan 64 ms. YOURS verified only with a SIMULATED editor. Backup taken (data_backup/). |
| 2026-10-03 | **Editor mode built and verified end to end** (brain/12-editor-plan.md): upload A-roll → ffmpeg normalise → faster-whisper transcript (word-perfect on the TTS test) → rule-based B-roll spots (Gemini optional via GEMINI_API_KEY) → filled by the TRUE/CUTS/YOURS planner → Editor tab with instant overlay preview, timeline, transcript highlight, swap/nudge/find/delete/add → ffmpeg render with original audio (32.6 s test rendered, frames checked). OpenCV 5 has no Haar face detector, so the face map is skipped (fail-soft). Test A-roll: python -m eval.make_aroll. |
| 2026-10-03 | Domain libraries built (brain/15-libraries.md): library tag on clips, scoped search/plan/editor, Libraries tab (upload / folder / build from Pixabay), curated travel seed list. Verified: folder library scoping; 8-clip auto-build end to end (5.5 min, OCR now skipped for stock). Editor upload now picks a library. |
