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
| D15 | ~~3-hour build scope~~ → full phased build for coding round 2 | The 3 h slot is for the problem statement; build time is round 2 | — |
