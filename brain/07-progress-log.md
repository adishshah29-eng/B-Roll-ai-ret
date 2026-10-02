# Progress log

## Checklist
- [x] Problem statement final: True · Cuts · Yours ([FINAL_PROBLEM_STATEMENT.md](../FINAL_PROBLEM_STATEMENT.md))
- [x] P0 Setup: models ✅ (HI↔EN cos 0.979), 24 Pixabay test clips ✅ · TODO: own Indian footage + TRUE trap clips + 2 past projects
- [x] P1 Index: shots/embeddings/tags/thumbs/basic provenance ✅ idempotent + crash-safe · TODO cut features (P6), OCR (P5)
- [x] P2 Search ✅ gate/dedupe/MMR/clusters/labels/similar; cold 111 ms, cached 0.1 ms; 8 unit tests
- [x] P2b Open-source library ✅ Pixabay + Commons + Archive connectors, Tier-S ingest (1,500 clips), lazy hydration, export hydrates on demand + reports skipped clips
- [x] P3 API + UI ✅ search, variety slider, filter chips, preview (Range 206), Find similar, live status
- [x] P4 Script → plan → export ✅ greedy no-repeat planner, XML/EDL/SRT/credits, timeline importer, round-trip tests · TODO: real import test in Premiere/Resolve
- [ ] P5 TRUE
- [ ] P6 CUTS
- [ ] P7 YOURS
- [ ] P8 Planner integration (one formula, explanations, toggles)
- [ ] P9 Benchmark + eval.py + hardening + rehearsal

## Log
| When | Note |
|---|---|
| 2026-10-02 | Problem statement pivoted from plain semantic search to the True/Cuts/Yours thesis for novelty |
| 2026-10-02 | P0–P4 built and verified. 24 clips → 151 shots. Gate tuned (D18). Plan 177 ms cold / 2 ms cached. 10 tests pass. |
| 2026-10-02 | P2b done. 1,858 searchable shots (own 151 · pixabay 682 · commons 725 · archive 300). Search 50–120 ms cold at that size (encode ≈ 50 ms, retrieval ≈ 1 ms). 14 tests pass. Real recorded dates flow into provenance (Commons: 1906, 1929, 2016…). |
| next | P5 TRUE → P6 CUTS → P7 YOURS → P8 → P9 |
