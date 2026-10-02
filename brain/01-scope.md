# Scope (coding round 2)

## Base layer (must work first; everything else builds on it)
| # | Feature | How |
|---|---|---|
| B1 | Index a folder | OpenCV samples 1 frame/s → shots (visual-change cuts or 4 s windows) → multilingual CLIP embeddings → SQLite + `.npy` + thumbnails |
| B2 | Search EN + HI | Multilingual text encoder → cosine similarity; filters (size, motion, orientation) |
| B3 | Relevant variety | Relevance gate → near-duplicate collapse → MMR → clusters + labels; Find similar |
| B4 | Script → beats → plan | Sentence split, duration estimate, per-beat candidates |
| B5 | Export | FCP7 XML (Premiere/Resolve) + EDL, incl. title clips for "FILE · year" labels |
| B6 | UI | Search tab, Script/Plan tab, Memory tab, index progress, preview |

## Pillar A: TRUE
| # | Feature | How |
|---|---|---|
| A1 | Provenance card | `when`: container creation_time (OpenCV/`mutagen`/`hachoir` metadata) + file mtime fallback · `where`: GPS tag if present + **OCR** (EasyOCR/PaddleOCR on keyframes with text) + zero-shot city/landmark prompts · `conditions`: zero-shot weather/season/time of day · `source`: folder-based tag (own/stock) |
| A2 | Claim extraction | Per beat: place (gazetteer of Indian cities/landmarks + NER), time ("today/this week/2026/this monsoon"), weather/event keywords; Hindi + English rules, optional LLM |
| A3 | Verdict | Rules compare claims vs provenance → ✅/⚠️/❌ + evidence strings |
| A4 | Truth-aware ranking | ❌ shots removed/penalised in planner; ⚠️ old-date shots get an auto "FILE · year" label |
| A5 | Audit mode *(stretch)* | Import an existing XML timeline + script → contradiction report |

## Pillar B: CUTS
| # | Feature | How |
|---|---|---|
| C1 | Cut features | At shot head/tail: mean flow direction (Farneback on 160 px frames), luminance, colour temperature (R/B ratio), size tag, saliency centroid; motion-peak time |
| C2 | Transition cost | Jump cut (same file, close timecodes, similar framing) · direction flip · exposure jump · colour jump · same size twice · reward wide→medium→close |
| C3 | Sequence DP | Viterbi over beats × top-k candidates: maximise Σrel − Σcost − repeat penalty − TRUE penalty + YOURS boost |
| C4 | Smart trim | Centre in/out on the motion peak, fit to beat duration |
| C5 | A/B toggle | UI compares the "relevance-only greedy" vs the "cut-aware" sequence (for the demo + evaluation) |

## Pillar C: YOURS (Edit Memory)
| # | Feature | How |
|---|---|---|
| Y1 | Import past timelines | Parse FCP7 XML/EDL → B-roll clip placements (file, in, out, timeline position) → map to indexed shots |
| Y2 | Narration pairing | Script/SRT for that project (or Whisper on the A-roll, stretch) → the text overlapping each placement → (text, shot) pairs |
| Y3 | Memory boost | New beat → kNN over past texts → boost the shots chosen then + their visual neighbours |
| Y4 | Re-ranker | Logistic regression on [text_emb ⊙ shot_emb, tags] with positives = chosen, negatives = candidates not chosen; retrained on every swap/accept |
| Y5 | House style | Learned size mix, avg B-roll duration, opener pattern, overuse cap → priors fed into the DP |
| Y6 | Memory toggle | UI on/off + "chosen N× in your edits" badges |

## Benchmark (our moat)
- **Indic B-roll Query Set:** 100+ queries (Hindi/Hinglish/English) with relevance labels over our footage.
- **Contradiction Set:** 30+ (narration line, shot) pairs labelled ✅/⚠️/❌.
- **Leave-one-project-out set:** 2–3 small past timelines for the YOURS evaluation.

## Footage plan
40–80 clips (H.264 MP4), Indian themes: monsoon/rain streets, traffic, local trains/stations, street food/chai, offices, markets, aerials, festivals.
**Plant traps** for TRUE: rain shots with non-Mumbai signboards, files with old creation dates, sunny drone shots, a person tagged "consent expired".
Make 2 mini "past projects" (script + XML) for YOURS.

## Roadmap only (mention in the pitch, don't build)
Learned cut-plausibility model · VLM captions · speech search over B-roll audio · Premiere UXP panel · broadcaster-archive scale · LAN worker sharing.
