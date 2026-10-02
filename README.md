# Epoch: True · Cuts · Yours

Offline B-roll retrieval that treats B-roll as an **editorial decision**, not a keyword search.
Paste a script and get a B-roll timeline from your own footage (plus open stock) that is
**true** to the narration, **cuts** well in sequence, and learns what is **yours**. Hindi and English, CPU-only, nothing leaves the machine.

## Run
```
run.bat                     # then open http://localhost:8000   (LAN: this PC's IP from ipconfig, port 8000)
python -m app.indexer.worker --path footage        # index a folder of videos (the server also indexes in the background)
python -m app.sources.ingest --seed --max 3000     # grow the library from Pixabay / Wikimedia Commons / Internet Archive
python -m eval.eval_all --seed-memory              # the results table below
python -m eval.backup                              # snapshot the index (restore: --restore)
```
Needs Python 3.11 and `pip install -r requirements.txt` (+ `rapidocr-onnxruntime` for signboard OCR). Put `PIXABAY_API_KEY=...` in `.env` for Pixabay.
Docs for humans and agents live in `brain/` (start at `brain/README.md`).

## What each pillar does
| | |
|---|---|
| **TRUE** | Reads the claims in each line (place, time, weather; Hindi too), checks every shot against GPS, signboard text (OCR), stock titles, recorded dates and look, rejects contradicting footage **with evidence**, and adds `FILE · 2017` / `STOCK` labels to the export. |
| **CUTS** | Picks the whole sequence at once (Viterbi + local search): no repeated shot sizes, wide→medium→close progression, no brightness / colour / direction / jump-cut breaks. |
| **YOURS** | Learns from past timelines you import and from your swaps and exports (no labelling): boosts shots you chose for similar lines, folds in your house style. |

## Results (`python -m eval.eval_all --seed-memory`; 19 scripts, 1,985-shot library, CPU laptop)
| configuration | contradicting shots | cut problems | same-size repeats | progressions | relevance | close-ups* | p50 / p95 plan |
|---|---|---|---|---|---|---|---|
| baseline (relevance only) | 10 | 22 | 26 | 14 | 0.296 | 2 % | 141 / 213 ms |
| + TRUE | **0** | 19 | 28 | 12 | 0.293 | 3 % | 26 / 59 ms |
| + CUTS | 9 | 15 | **4** | **32** | 0.292 | 11 % | 16 / 44 ms |
| + YOURS | 7 | 22 | 22 | 17 | 0.290 | **18 %** | 20 / 54 ms |
| **all three** | **0** | **9** | **2** | **31** | 0.287 | 17 % | 30 / 64 ms |

\* a **simulated** editor who prefers close-ups taught the system through 3 past projects (12 lessons); the column shows it picking that taste up.
Relevance cost of everything together is about 3 %. Latencies after warm-up (first run pays the cache warm-up).
Honest limits are listed in `brain/09-truth.md`, `brain/10-cuts.md`, `brain/11-results.md`.
