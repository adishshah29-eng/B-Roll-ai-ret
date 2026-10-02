# Final Problem Statement

## Title
**True · Cuts · Yours: An Editorially-Aware B-Roll Retrieval System that finds footage which is *truthful to the narration*, *cuts well in sequence*, and *learns from the editor's own past edits***

**Theme:** Smart Automation / AI for Media & Trustworthy Information
**Category:** Software

---

## 1. The thesis (why this is different)
> Every B-roll tool today treats B-roll as a **search problem**: *find shots that match the words.*
> Editors judge B-roll on three questions search ignores:
> 1. **Is it true?** Does the shot contradict what the narration claims (wrong city, wrong year, wrong season, wrong person)?
> 2. **Does it cut?** Does it flow with the shots before and after it, or does it create jump cuts, direction flips and exposure jumps?
> 3. **Is it ours?** Does it match how *this* editor or channel actually uses B-roll?

We treat B-roll retrieval as an **editorial decision problem**, not a keyword-matching problem.

---

## 2. Background
B-roll is the supporting footage that plays over narration and interviews. Creators, newsrooms, colleges, government departments and companies build up hundreds of hours of it and reuse it for years. Today:
- The footage is **unsearchable**: files named `C0042.MP4`, sorted only by date, manual tagging that never happens.
- AI search tools (Premiere Media Intelligence, Jumper, Twelve Labs) only **match content to words**. They are English-first, limited to one project or cloud-based, and blind to truth, continuity and personal style.
- **Reusing old footage out of context is India's dominant form of video misinformation.** Most misleading visuals in the 2024 elections were "cheapfakes", meaning old or mislabelled footage, not deepfakes. Newsrooms also routinely air file visuals without marking them as file footage.

## 3. Problem Description
Editors lose hours, and sometimes credibility, on B-roll:
- **Time:** 5 hours to add B-roll to a 14-minute video; nearly an hour to find a single 3-second clip; close to a year to tag a 150 TB archive by hand.
- **Truth:** B-roll that contradicts the narration is one of the most credibility-damaging editing mistakes. Today it is caught only by manual review, or by fact-checkers after the video has already spread.
- **Craft:** search returns ten near-identical shots. Editors then hand-build "selects" timelines (V1 = all, V2 = good, V3 = great) and assemble sequences that avoid jump cuts and mismatched motion. None of that is automated.
- **Memory:** every past edit records *which shot an editor chose for which line of narration*, but that knowledge is thrown away. Each new project starts from zero, and good footage ("outtakes and alternate takes") never gets used.

**No existing system retrieves B-roll that is simultaneously relevant, truthful, cuttable and personalised, from the user's own footage, offline, in Indian languages.**

## 4. Evidence
| Pillar | Evidence |
|---|---|
| Base (time) | r/premiere: "5 hours … 14 minutes of footage … B-roll from footage I already had" · r/NewTubers: an hour for a 3-s clip in 100 GB · r/editors (28 comments): scrolling through hundreds of clips "takes forever" · Adobe Community (2025): a documentary editor with 12 h of B-roll asks for a way to find every shot of a person or object |
| **True** | India 2024 elections: most fakes were relabelled old footage ("cheapfakes") · fact-checkers repeatedly debunk "old video shared as recent" · B-roll guides list "visuals that contradict the narration" as a top mistake, but no tool checks for it automatically |
| **Cuts** | r/premiere's top-voted workflow is a manual V1/V2/V3 selects stack for cutting B-roll · r/documentaryfilmmaking: editors check for "a range of wides, closeups… static shots as well as movement" · *Learning to Cut by Watching Movies* (ICCV 2021) learned cut quality from 255k real cuts but has never been applied to retrieval |
| **Yours** | r/editors: "editors ignore all the selects/string-outs I laid out" (a team's knowledge is lost) · r/premiere: one YouTuber renames every clip by hand each year just to search later · r/Filmmakers: "B-roll, outtakes and alternate takes never get used" · B-Script (CHI 2019) needed hired experts to annotate data; nobody learns from the user's own timelines |

## 5. Gaps in Existing Solutions
| Capability | Premiere MI | Jumper | Twelve Labs | Stock auto-B-roll | Research (B-Script / EditDuet) | **Ours** |
|---|---|---|---|---|---|---|
| Shot-level search of *own* footage | ✅ (project only) | ✅ | ✅ (cloud) | ❌ | partial | ✅ offline |
| Indian languages | ❌ | ❌ | partial | ❌ | ❌ | ✅ |
| Script → B-roll timeline | ❌ | ❌ | ❌ | ✅ (stock) | ✅ | ✅ |
| Relevant variety (anti-duplicate) | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Narration-contradiction / provenance check** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Cut-aware sequence selection** | ❌ | ❌ | ❌ | ❌ | partial (EditDuet critic) | ✅ |
| **Learns from the user's past timelines** | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |

## 6. Objective
Build an **offline-first, editorially-aware B-roll retrieval system** that:
1. indexes a private footage library **shot by shot**, with search in **English and Indian languages** and **relevance-ranked variety**;
2. turns a **script or voiceover** into a B-roll timeline exportable to Premiere Pro, DaVinci Resolve and Final Cut Pro;
3. **(True)** attaches a **provenance card** to every shot, checks every shot against the **claims in the narration**, and flags or replaces contradicting footage;
4. **(Cuts)** chooses **sequences** of shots that cut well together, not just individually relevant shots;
5. **(Yours)** learns from the editor's **past timelines** to personalise ranking and house style, with no manual labelling.

---

## 7. Expected Solution

### Base layer: Shot-level multilingual retrieval
- **Indexing:** shot segmentation → visual embeddings (multilingual CLIP/SigLIP) → tags (shot size, camera motion, action level, orientation, quality).
- **Search:** hybrid dense + keyword search, filters, **relevance gate → near-duplicate collapse → MMR diversification → clusters**, "Find similar".
- **Script → B-roll:** split into beats, retrieve per beat, export as FCP7 XML / FCPXML / EDL.

### Pillar A: TRUE (provenance- and claim-aware retrieval)
1. **Provenance card per shot**, built automatically:
   - **When:** container/EXIF creation date, plus visual cues.
   - **Where:** GPS metadata when present, OCR'd signboards and their script/language, zero-shot landmark and city cues.
   - **Conditions:** season, weather and time of day (zero-shot).
   - **Who:** face clusters with consent and active status.
   - **Source:** own / stock / licensed / user-generated.
2. **Claim extraction from narration:** pull out place, time ("today", "this monsoon", "2026"), weather, event and person from each beat (multilingual).
3. **Consistency check** for each (beat, shot) pair gives a verdict:
   - ✅ consistent
   - ⚠️ unverifiable
   - ❌ **contradicts**

   Each verdict comes with **human-readable evidence**, e.g. *"OCR: 'Delhi Metro' vs narration: Mumbai · shot 2022 vs 'today' · sunny vs 'heavy rain'"*.
4. **Truth-aware ranking:** contradicting shots are pushed down or removed; consistent alternatives are offered.
5. **Auto disclosure:** when a time claim is "today" but the shot is old, suggest a **"FILE FOOTAGE · <year>"** on-screen label in the export.
6. **Timeline audit mode:** scan a whole existing edit (imported XML plus narration) and produce a contradiction report.

### Pillar B: CUTS (cut-aware sequence retrieval)
1. **Per-shot cut features:**
   - motion direction at head and tail (optical flow)
   - brightness and colour temperature at head and tail
   - shot size
   - subject position (saliency centroid)
   - motion-peak time
2. **Transition cost** between consecutive shots, which penalises:
   - jump cuts (same source + similar framing)
   - screen-direction flips
   - exposure/colour jumps
   - repeated shot sizes

   and rewards **size progression** (wide → medium → close).
3. **Sequence optimisation:** choose shots for all beats together with **dynamic programming (Viterbi)**, maximising Σ relevance − Σ transition cost − repetition penalty. The output is a *sequence that cuts*, not a ranked list.
4. **Smart trimming:** place in/out points around motion peaks, fitted to the beat's duration.
5. *(Advanced)* A learned **cut-plausibility model** (after *Learning to Cut*, ICCV 2021), fine-tuned on cuts from the user's own timelines (from Pillar C).

### Pillar C: YOURS (Edit Memory)
1. **Import past timelines** (FCP7 XML / FCPXML / EDL) plus the A-roll narration (transcribed with Whisper, or an SRT).
2. **Mine (narration → chosen shot) pairs:** for every B-roll clip on a past timeline, take the narration it covered. This gives **free, zero-labelling training data**. Shots that were offered but never chosen become negatives.
3. **Memory-boosted retrieval:** a new script line is matched to similar past lines; the shots chosen then, and their visual neighbours, get boosted.
4. **Learning-to-rank adapter:** a lightweight re-ranker trained on the user's positives and negatives; it keeps improving from swaps and accepts in our planner (implicit feedback).
5. **House-style priors:** learned shot-size mix, typical B-roll duration, opener patterns (e.g. "always starts with an aerial"), and overuse limits for frequently used shots.
6. **Cold start:** works fully without history and improves as history grows.

### Governance and privacy
- Fully **on-device**; footage is never uploaded.
- People tags with consent/expiry flags, in line with India's DPDP Act 2023.

---

## 8. Example (end-to-end)
**Script line:** *"Heavy rain lashed Mumbai today, bringing traffic to a halt."*

| Candidate | Relevance | TRUE check | CUTS (after previous wide shot) | YOURS | Result |
|---|---|---|---|---|---|
| Rainy traffic, signboard "Delhi Metro", 2022 | 0.78 | ❌ location + date contradiction | ok | — | **Rejected, with evidence shown** |
| Rainy Mumbai local station, 2026, close-up | 0.71 | ✅ | ✅ wide → close | Similar shots chosen 4× before | **Picked** |
| Sunny Marine Drive drone shot | 0.55 | ❌ weather contradiction | jump in shot size | — | Rejected |
| Old flood footage, 2019 (only option for the next beat) | 0.74 | ⚠️ old | ok | — | Kept with an auto **"FILE · 2019"** label |

## 9. Deliverables
1. Desktop/web app: index a footage folder; multilingual search with variety clusters and Find similar.
2. Script/voiceover → **truth-checked, cut-aware, personalised** B-roll timeline → export to Premiere, Resolve or Final Cut.
3. Provenance cards and contradiction reports with evidence; a timeline audit mode for existing edits.
4. Edit Memory: import past timelines and show the before/after improvement in ranking.
5. **Our own benchmark:**
   - **Indic B-roll Query Set:** 100+ Hindi/Hinglish/English queries over Indian visual concepts (auto-rickshaw, chai stall, monsoon street, diya…).
   - **Contradiction Set:** 30+ planted narration ↔ shot conflicts.

## 10. Evaluation Metrics
| Pillar | Metric | Target |
|---|---|---|
| Base | Recall@10 / nDCG on the Indic Query Set | Beats CLIP4Clip / similarity-only baseline |
| Base | Near-duplicate rate in top 10 | < 10% |
| **True** | Precision / recall of contradiction flags on the Contradiction Set | ≥ 0.8 / ≥ 0.7 |
| **True** | Contradicting shots in the final auto-timeline | 0 (or labelled) |
| **Cuts** | Jump cuts / direction flips per minute vs relevance-only greedy | ≥ 50% reduction |
| **Cuts** | Editor A/B preference: cut-aware vs greedy sequence | > 65% prefer cut-aware |
| **Yours** | Leave-one-project-out Recall@10: with vs without Edit Memory | Significant gain (target +20% relative) |
| Overall | Time to add B-roll to a 5-minute script | Hours → < 15 minutes |
| System | Search latency at 100 h of footage, CPU-only laptop | < 1 s |

## 11. Stakeholders / Beneficiaries
- **Newsrooms and public broadcasters** (DD/Akashvani archives): truthful reuse of file footage.
- **YouTubers and creators**, especially regional-language ones: speed and personal style.
- **Corporate, college and government media teams**: consent-aware reuse.
- **Documentary editors**: sequences that cut.
- **Fact-checking ecosystem**: misinformation prevented *at the point of editing* rather than debunked afterwards.

## 12. Impact
- Cuts B-roll editing time from **hours to minutes**.
- **Prevents out-of-context footage misuse** before publication, the dominant form of video misinformation in India.
- Produces **ready-to-cut sequences**, not lists.
- Turns every past edit into **compounding, personalised knowledge**.
- Private, offline, and works in **Indian languages**.

## 13. Key References
1. B-Script: Transcript-based B-roll Video Editing with Recommendations (CHI 2019) — arXiv:1902.11216
2. EditDuet: A Multi-Agent System for Video Non-Linear Editing (SIGGRAPH 2025) — arXiv:2509.10761
3. Memory-Guided B-Roll Generation from User Video Collections (2026) — arXiv:2610.01884
4. **Learning to Cut by Watching Movies (ICCV 2021) — arXiv:2108.04294** *(Cuts pillar)*
5. CLIP4Clip — arXiv:2104.08860
6. SigLIP 2: Multilingual Vision-Language Encoders — arXiv:2502.14786
7. Shot Type Classification (MovieShots) — arXiv:2008.03548
8. Towards Understanding Camera Motions in Any Video (CameraBench) — arXiv:2504.15376
9. TransNet V2 — arXiv:2008.04838
10. The 2023 Video Similarity Dataset and Challenge — arXiv:2306.09489 *(near-duplicate / provenance)*
11. MultiVENT 2.0: Multilingual Event-Centric Video Retrieval — arXiv:2410.11619
12. PP-OCRv3 — arXiv:2206.03001 *(signboard OCR for provenance)*
13. Whisper — arXiv:2212.04356
14. Carbonell & Goldstein, MMR diversity re-ranking — SIGIR 1998
15. "Cheapfakes, not deepfakes, spread election lies in India" — The Standard / AFP, 2024
