# Decision log

| # | Decision | Why | Revisit when |
|---|---|---|---|
| D1 | Single machine, SQLite + `.npy`, no vector DB | ≤ 100 h fits in RAM; zero setup in a 3 h build | Team/shared library or > 500k shots |
| D2 | **sentence-transformers `clip-ViT-B-32` + `clip-ViT-B-32-multilingual-v1`** instead of SigLIP 2 | Already installed library, 2-line API, Hindi works out of the box; SigLIP 2 needs new code and a bigger download | After the hackathon → SigLIP 2 for better quality |
| D3 | OpenCV for video decoding, not ffmpeg | ffmpeg isn't installed; cv2 is, and reads MP4 | Need HEVC/ProRes or faster decode |
| D4 | Sample 1 frame/s + similarity cuts + 4 s windows | B-roll is mostly single takes; good enough boundaries, fast on CPU | Edited/multi-cut footage → TransNet V2 |
| D5 | Zero-shot CLIP prompts for shot size | No training data or time; free given the embeddings | Accuracy matters → train a linear probe on MovieShots |
| D6 | Relevance gate → dedupe → MMR → clustering | Delivers "relevant variety" without pulling in irrelevant shots | Users always max the diversity slider |
| D7 | No LLM in the planner; each sentence is used as the query | The multilingual CLIP text encoder handles sentences; a CPU LLM is slow and risky | More time → local Qwen 1.5B writes visual queries |
| D8 | Vanilla HTML/JS UI served by FastAPI | No build step; works on LAN laptops instantly | Post-hackathon → React/Electron |
| D9 | Export FCP7 XML (xmeml) + EDL | xmeml imports into both Premiere and Resolve with linked media | FCP users → add FCPXML |
| D10 | **Thesis: True · Cuts · Yours** instead of plain semantic search | Plain search + script-to-B-roll is what most AI-researched teams will converge on; three editorial questions give a unique, defensible identity | — |
| D11 | TRUE uses rule-based claim vs provenance matching with evidence strings, not an end-to-end model | Explainable flags ("OCR says Delhi") build trust and are demoable; no training data needed | We have enough labelled contradictions → train a verifier |
| D12 | CUTS uses hand-designed transition costs + Viterbi DP over beats | Works with zero training and is explainable; replaces greedy assignment | Edit Memory gives enough real cuts → learned cut-plausibility model |
| D13 | YOURS uses kNN memory boost + a small linear re-ranker on embeddings | Works from 1–2 past timelines; trains in seconds on CPU | Many projects → a proper learning-to-rank model |
| D14 | Build our own benchmark (Indic Query Set + Contradiction Set) | No public benchmark covers Indian B-roll or narration contradictions; it is also a moat | — |
| D16 | Grow the library from open platforms (Pexels, Pixabay, Commons, Internet Archive) via **Tier S: preview-only indexing + lazy hydration** | Thousands of clips at ~150 KB each instead of GBs; ingest in minutes on CPU; respects API rate limits/caching rules | Need full cut features for all stock → hydrate everything in a background tier |
| D17 | Commons + Internet Archive used as TRUE ground truth | They carry real dates/geo/licences, unlike generic stock | — |
| D18 | `GATE_DELTA` = 0.04 (was 0.08 in the plan) | Measured on 24 Pixabay clips × 11 queries: delta 0.04 gives precision 0.68 / recall 0.75 vs 0.39 / 0.91 at 0.08. CLIP cosine gaps between relevant/irrelevant are only ~0.03–0.06, so the gate must be tight | Re-tune once the library has thousands of clips; `eval.py` will own this |
| D19 | **RapidOCR (ONNX PP-OCR) instead of EasyOCR** for signboard OCR | Measured on this CPU laptop (<1 GB free RAM): EasyOCR 4–7 s/frame even at canvas 480 (detector alone 4 s); RapidOCR 0.8 s/frame, load 0.8 s, higher confidence (0.95–0.98 on clean signs). Default models read English/Latin only → Hindi *claims* work, Hindi *signboards* deferred | Need Devanagari signboards → add PP-OCR devanagari rec model |
| D20 | Place evidence is derived on the fly (OCR text, stock title/tags, GPS), not precomputed | ≤100 candidates per plan; string scans are microseconds; no backfill needed when the gazetteer improves | Candidate sets grow into the thousands |
| D21 | Place mismatch ❌ excludes a shot; time mismatch ⚠️ keeps it with an auto `FILE · year` label; weather ❌ only at high confidence | Editors legitimately use labelled file footage; a wrong city is never acceptable. Keeps flags credible | Real editors disagree in user testing |
| D22 | Place context carries over to later lines of a script; time/weather do not | A Mumbai script otherwise chose Bangkok, Indonesian and Kerala clips for lines that never repeat "Mumbai" | Users write multi-location scripts without naming places (add a per-beat override) |
| D23 | Weather may only exclude a shot at 0.97 (warn ≥ 0.80); `indoor` class added | Contact-sheet check: 0.90 is only ~85–90 % precise; first prompt set labelled 854/1,881 shots "sunny" | A better weather model |
| D24 | `CUT_WEIGHT` = 0.25 (cut-aware sequence) | `eval/eval_cuts.py`, 15 scripts, 52 transitions: weight 0.25 → same-size repeats 21→1, wide→medium→close progressions 12→27, exposure jumps 9→2, problems −42 % at **1.6 %** mean-relevance cost (1.0 → −75 % at 2.3 %). Greedy produced only 1 jump / 0 flips: retrieval already dedupes near-copies and flips need optical flow (local clips only), so the plan's "≥ 50 % fewer jump/flip" target cannot be shown on this library | Library with many long single takes of one subject (re-run the eval) |
| D15 | ~~3-hour build scope~~ → full phased build for coding round 2 | The 3 h slot is for the problem statement; build time is round 2 | — |
