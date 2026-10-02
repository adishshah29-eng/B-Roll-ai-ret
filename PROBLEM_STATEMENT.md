# Problem Statement — Script-Aware B-Roll Retrieval from Your Own Footage

## 1. Title
**Script-aware, multilingual B-roll search and retrieval for private footage libraries**
(Given a script or voiceover, find the right *moments*, not just files, in a creator's or organisation's own footage archive, and send them straight to the editing timeline.)

## 2. Background
B-roll is the supporting footage shown over narration or interviews. Every production team, YouTuber, newsroom and corporate comms team keeps a growing pile of it: drone shots, office shots, events, products, cityscapes. It is shot once and reused for years. In practice, though, it can't be found when it's needed:
- Files are named `C0042.MP4` and sorted only by shoot date.
- Proper tagging (a Media Asset Manager) is expensive and only works if *everyone* adds metadata. Usually nobody does.
- Editors scrub through footage by hand, or re-shoot or buy stock footage they already own.

## 3. Evidence that the problem is real

### Reddit (users describing it in their own words)
| Thread | Pain |
|---|---|
| [r/NewTubers – "losing my mind searching through old clips for B-roll"](https://reddit.com/r/NewTubers/comments/1vh5e2y/) | Loses hours every week going through about 100 GB of old footage. Spent nearly an hour finding one 3-second clip. |
| [r/premiere – "Tips to edit B-roll on talking-head videos faster"](https://reddit.com/r/premiere/comments/1lzy5dl/) | Took **5 hours to B-roll 14 minutes** of talking-head footage using footage they already had. |
| [r/editors – "How do you manage hundreds of B-roll clips efficiently?"](https://reddit.com/r/editors/comments/1ncu0iz/) | Scrolling through folders and filenames "takes forever". 28 comments of workarounds (stringouts, markers, selects bins). |
| [r/premiere – "Searching footage backlog for B-roll"](https://reddit.com/r/premiere/comments/14uvn86/) | Has 200+ videos and searches by renaming every clip by hand. One commenter needed **close to a year** to tag a 150 TB company archive. |
| [r/editors – "Better workflow for finding B-roll"](https://reddit.com/r/editors/comments/1g5zrrz/) | Corporate B-roll keeps getting rejected: "that person is in the other department" or "that person no longer works here". There's no person-aware metadata. |
| [r/editors – "Cataloguing/Indexing B-roll"](https://reddit.com/r/editors/comments/1djyixd/) | A non-professional "resident techie" with a growing archive. The reply: MAM is "usually expensive" and "requires near universal buy-in". |
| [r/editors – "600 clips of B-roll… AI tool for visual searching?"](https://reddit.com/r/editors/comments/1c0999a/) | Wants automatic metadata about what happens and what is said in each clip, cheaper than muse.ai. |
| [r/Filmmakers – "an hour finding B-roll for a 5-minute video"](https://reddit.com/r/Filmmakers/comments/1w63pcu/) | Wants B-roll matched automatically to what the voiceover is saying. |
| [r/Filmmakers – "B-roll, outtakes and alternate takes never get used"](https://reddit.com/r/Filmmakers/comments/1q91zk8/) | Shot footage is wasted because nobody can find it later. |

### Industry and research
- **Adobe feature request (Sep 2025):** a documentary editor with "often 12 hours of b-roll" asks for a way to find every instance of a person or object. ([link](https://community.adobe.com/t5/premiere-pro-ideas/find-all-instances-of-an-object-or-person-in-footage-feature-request/idi-p/15495756))
- **Newsrooms:** Sinclair uses AI and OCR on tape labels so journalists can surface archive clips while writing stories. ([Meedan](https://meedan.org/post/newsrooms-draw-on-archives-and-ai-to-deepen-context), [TVNewsCheck](https://tvnewscheck.com/tech/article/archive-efforts-come-to-fruition/))
- **Government demand (India):** Prasar Bharati (DD + Akashvani) is seeking AI firms to "revive archives" and repurpose decades of footage. ([Storyboard18](https://www.storyboard18.com/brand-makers/prasar-bharati-seeks-ai-content-creators-for-digital-expansion-ws-l-110680.htm))
- **Research:** this is an active, unsolved area. See B-Script (Adobe Research, transcript-based B-roll recommendation, [arXiv 1902.11216](https://arxiv.org/abs/1902.11216)), EditDuet (SIGGRAPH 2025, LLM agents that build B-roll sequences on the EditStock dataset, [arXiv 2509.10761](https://www.alphaxiv.org/abs/2509.10761)) and MemComposer (Oct 2026, B-roll grounded in the user's own collection, [arXiv 2610.01884](https://arxiv.org/abs/2610.01884)).

### SIH (closest official problem statements; none targets B-roll directly, so the gap is open)
- **SIH26096** (MoSJE): Ambedkar archive. Asks for "AI-powered semantic search" plus an "audio-video archival system for lectures, documentaries, and interviews".
- **SIH26063** (MoES/NCPOR): a portal that archives expedition **videos** and generates content for websites and social media.
- **SIH26154** (NTRO): content transformation. A "Video" output must include a script, storyboard and "visual recommendations", which is exactly the gap: the recommended visuals then have to be *found*.
- **SIH 2025:** a multimodal RAG problem statement covering cross-format search (docs, images, audio).

## 4. Why existing solutions don't solve it
| Tool | Gap |
|---|---|
| Premiere Pro Media Intelligence | **English only**. Searches only media **inside the open project**. Can't identify *specific* people. No OCR. Locked to Adobe. ([Larry Jordan](https://larryjordan.com/articles/ai-powered-media-intelligence-search-in-premiere-pro-2025/)) |
| Jumper | Good local search, but paid and closed. It's search-box driven, not script-driven. |
| Twelve Labs / Moments Lab | Cloud and enterprise pricing. Footage has to be uploaded, which doesn't work for privacy-sensitive or very large archives. |
| Stock-footage auto-B-roll tools (InVideo etc.) | Match *stock* footage, not **your own** footage. |
| GitHub CLIP demos | Toy frame search over one video. No shot segmentation, no script matching, no people or OCR, no NLE export, no Indian languages. |

**The unsolved core:** no free or open tool takes a **script or voiceover (including Hindi/Hinglish and other Indian languages)**, works out *where* B-roll is needed and *what* it should show, and returns **ranked, timestamped, deduplicated shots from the user's own offline library**, exported straight into the editor's timeline.

## 5. Problem statement (final)
> Video creators, newsrooms and organisations collect thousands of hours of B-roll that becomes practically unusable over time, because it is unlabelled, spread across drives and projects, and searchable only by filename or date. Editors spend hours scrubbing footage (for example, 5 hours to B-roll a 14-minute video), re-shoot material they already own, or use the wrong shots (wrong person, outdated content). Current AI search tools are English-only, project-bound, cloud-dependent or expensive, and none of them start from the script itself.
>
> **Build an offline-first system that automatically indexes a private footage library at the shot level (visuals, speech, on-screen text, people, shot type and camera motion), lets users search in natural language in English and Indian languages, and, given a script or voiceover, automatically proposes ranked, diverse, timestamped B-roll candidates for each script beat, exportable directly to editing software timelines.**

## 6. Expected solution (buildable scope)
**Ingest and indexing (offline):**
1. Shot segmentation (PySceneDetect / TransNetV2). The unit of retrieval is a *shot*, not a file.
2. Per-shot signals: visual embeddings (SigLIP/CLIP), a short caption from a small VLM (Florence-2 / Qwen2.5-VL), speech-to-text (Whisper, multilingual), OCR (PaddleOCR), face clustering with naming (InsightFace), shot type (wide/close/drone) and camera motion (static/pan/handheld), plus quality flags (blur, shake, exposure).
3. Store everything in a vector DB (Qdrant/FAISS) plus a metadata DB, and support incremental re-indexing when drives change.

**Retrieval:**
4. Hybrid search: dense vectors + BM25 on captions/transcripts/OCR, then a re-ranker. Filters for person, date, location, shot type, orientation (16:9 / 9:16) and "not used before".
5. Multilingual queries, e.g. "बारिश में सड़क पर ट्रैफिक" (traffic on the road in the rain) or "drone shot of our Pune office".
6. "Find similar" by uploading a reference frame.

**Coverage-aware results ("give me variety"):**
- For any query, return a **coverage pack**: the best matching **wide / establishing**, **medium**, **close-up / detail** and **action / motion** shot, plus camera-move variants (static, pan, drone, handheld).
- Each shot is labelled at index time with shot scale (MovieShots-style classifier), camera motion (CameraBench-style) and motion intensity (optical flow).
- Ranking is relevance-first, then diversified (relevance threshold → bucket by shot type → best per bucket, MMR to avoid near-duplicates).
- If a bucket is empty, the system says so ("no close-up of the clubhouse exists"), which doubles as a pickup shot list for the next shoot.
- Script mode uses the same idea: a beat that is 6 s long can get wide → close cut automatically (classic establishing → detail sequencing).

**Script-to-B-roll (the differentiator):**
7. Paste a script or drop a voiceover. An LLM splits it into beats with timestamps and writes visual queries for each beat. Then retrieve the top-k diverse shots per beat, trimmed to the beat duration.
8. Export to Premiere / Resolve / FCP via FCPXML/EDL as a rough B-roll track.

**Governance (from the corporate Reddit pain point):**
9. Person-level tags such as "left company" or "department", consent/expiry flags, and usage history so stale or already-used shots are deprioritised.

## 7. Evaluation
- **Retrieval quality:** Recall@5/10 and nDCG on an annotated test set (the EditStock/EditDuet projects plus your own clips). Use MSR-VTT for a text-to-video baseline.
- **Script-to-B-roll:** human preference against manual selection, and beat coverage %.
- **Real-world metric:** time to B-roll a 5-minute script, manual vs. the system (target: hours down to minutes).
- **Performance:** indexing speed on a laptop GPU/CPU, and query latency under 1 s on more than 100 hours of footage.

## 8. Users and impact
- Independent YouTubers and creators, especially regional-language ones.
- Corporate and institutional comms teams, colleges and government departments.
- Newsrooms and public broadcasters (DD / Akashvani archive reuse).
- Documentary editors.

**Impact:** recovers value from footage that is already paid for, cuts post-production time, reduces stock-footage spend, and keeps footage private because indexing runs on-device.

## 9. Research papers (all arXiv IDs checked)

**A. Core B-roll / script-to-footage (cite these as the problem's foundation)**
| Paper | Year | Use it for |
|---|---|---|
| [B-Script: Transcript-based B-roll Video Editing with Recommendations](https://arxiv.org/abs/1902.11216) | 2019 (CHI) | The original framing: transcript → where to put B-roll + search keywords |
| [EditDuet: A Multi-Agent System for Video Non-Linear Editing](https://arxiv.org/abs/2509.10761) | 2025 (SIGGRAPH) | LLM agents that build B-roll sequences from A-roll; EditStock evaluation setup |
| [Memory-Guided B-Roll Generation from User Video Collections](https://arxiv.org/abs/2610.01884) | 2026 | B-roll grounded in the user's *own* collection; entity-centric memory |
| [Timeline-Bench: Evaluating Agents on Realistic Video-Editing Tasks](https://arxiv.org/abs/2609.35143) | 2026 | Raw footage → final cut benchmark |
| Write-A-Video: Computational Video Montage from Themed Text | 2019 (SIGGRAPH Asia) | Text → montage assembled from a footage library |

**B. Text-to-video retrieval models**
| Paper | Year | Use it for |
|---|---|---|
| [CLIP4Clip](https://arxiv.org/abs/2104.08860) | 2021 | Baseline: CLIP frame embeddings pooled into clip retrieval |
| [X-CLIP (Expanding Language-Image Pretrained Models for Video)](https://arxiv.org/abs/2208.02816) | 2022 | Temporal modelling on top of CLIP |
| [SigLIP 2: Multilingual Vision-Language Encoders](https://arxiv.org/abs/2502.14786) | 2025 | **Multilingual** visual embeddings (Hindi queries) |
| [InternVideo2](https://arxiv.org/abs/2403.15377) | 2024 | Strong video foundation model for embeddings |
| [LanguageBind](https://arxiv.org/abs/2310.01852) | 2023 | Video + audio + depth aligned through language |
| [HowTo100M](https://arxiv.org/abs/1906.03327) | 2019 | Learning from narration ↔ video, the same as script ↔ B-roll |
| [Temporal Alignment Networks for Long-term Video](https://arxiv.org/abs/2204.02968) | 2022 | Aligning narration sentences to the matching video segments |

**C. Moment retrieval (finding the right seconds inside a long clip)**
| Paper | Year | Use it for |
|---|---|---|
| [QVHighlights / Moment-DETR](https://arxiv.org/abs/2107.09609) | 2021 | Natural-language query → start/end timestamps |
| [UniVTG](https://arxiv.org/abs/2307.16715) | 2023 | Unified temporal grounding |
| [MomentSeeker](https://arxiv.org/abs/2502.12558) | 2025 | Benchmark for moment retrieval in long videos |
| [MUVR](https://arxiv.org/abs/2510.21406) | 2025 | Retrieval benchmark for untrimmed (raw) video |
| [VideoRAG](https://arxiv.org/abs/2501.05874) | 2025 | Retrieval-augmented generation over a video corpus |

**D. Indexing pipeline components**
| Paper | Year | Use it for |
|---|---|---|
| [TransNet V2](https://arxiv.org/abs/2008.04838) | 2020 | Shot boundary detection |
| [Shot Type Classification (Subject Centric Lens, MovieShots)](https://arxiv.org/abs/2008.03548) | 2020 | Wide/close-up shot type plus camera movement labels |
| [Towards Understanding Camera Motions in Any Video (CameraBench)](https://arxiv.org/abs/2504.15376) | 2025 | Pan/tilt/dolly/static classification |
| [Shot2Story](https://arxiv.org/abs/2312.10300) | 2023 | Captioning multi-shot videos |
| [Florence-2](https://arxiv.org/abs/2311.06242) | 2023 | Lightweight captions, detection and OCR |
| [Qwen2.5-VL](https://arxiv.org/abs/2502.13923) | 2025 | Richer shot descriptions, script beat → visual query |
| [Whisper](https://arxiv.org/abs/2212.04356) | 2022 | Speech-to-text |
| [PP-OCRv3](https://arxiv.org/abs/2206.03001) | 2022 | On-screen text (signboards, slides) |
| [ArcFace](https://arxiv.org/abs/1801.07698) | 2018 | Face embeddings for "find every shot of person X" |

**E. Multilingual / Indian-language**
| Paper | Year | Use it for |
|---|---|---|
| [MultiVENT 2.0](https://arxiv.org/abs/2410.11619) | 2024 | **Multilingual** event-centric video retrieval benchmark |
| [BGE-M3 (M3-Embedding)](https://arxiv.org/abs/2402.03216) | 2024 | Multilingual dense + sparse text retrieval over captions/transcripts |
| [Vistaar](https://arxiv.org/abs/2305.15386) | 2023 | Indian-language ASR benchmarks and models |
| [IndicTrans2](https://arxiv.org/abs/2305.16307) | 2023 | Translating across all 22 scheduled Indian languages |

## 10. Other problem statements in the same domain

| # | Problem | Evidence | Gap | Fit |
|---|---|---|---|---|
| PS-2 | **Recycled-footage provenance search.** A viral clip is posted as "new"; find the original in a news/footage archive, even when it is cropped, mirrored, re-encoded or has text overlaid. | Most fake visuals in India's 2024 election were "cheapfakes": old footage relabelled ([The Standard](https://www.thestandard.com.hk/world/article/216939/Cheapfakes-not-deepfakes-spread-election-lies-in-India)). Fact-checkers rely on keyframe reverse search. | Reverse *image* search on keyframes breaks on edits; no indexed Indian news-video archive | Strong SIH fit (NTRO / MeitY / PIB) |
| PS-3 | **Multilingual broadcast-archive event retrieval.** Search decades of DD/Akashvani-style footage by event, in Indian languages. | Prasar Bharati is seeking AI vendors to revive its archives. Vietnam runs a government AI Challenge on exactly this task ([HCMC AIC](https://aichallenge.hochiminhcity.gov.vn/en/huong-dan)). | No Indian equivalent; Premiere-style tools are English-only | Strong SIH fit (MIB) |
| PS-4 | **People- and consent-aware B-roll governance.** Find every shot of person X; flag ex-employees, wrong department or expired consent before footage is reused. | [r/editors thread](https://reddit.com/r/editors/comments/1g5zrrz/) (clips rejected because of the wrong person); [Adobe request](https://community.adobe.com/t5/premiere-pro-ideas/find-all-instances-of-an-object-or-person-in-footage-feature-request/idi-p/15495756); India's DPDP Act 2023 treats faces as personal data | Premiere can't identify specific people; no tool tracks consent | Corporate / college / govt |
| PS-5 | **Usable-moment mining ("selects") from long raw B-roll.** Automatically find the steady, in-focus, interesting seconds and surface footage that has never been used. | [r/premiere "AI for finding interesting parts in B-roll"](https://reddit.com/r/premiere/comments/14yybpr/); [r/editors "auto-trim unusable B-roll"](https://reddit.com/r/editors/comments/1j9c5bq/); [r/Filmmakers "outtakes never get used"](https://reddit.com/r/Filmmakers/comments/1q91zk8/) | Search finds *clips*; nobody ranks *usable moments* | Creators, documentary |
| PS-6 | **Short-form (9:16) aware B-roll retrieval.** Retrieve shots whose subject survives a vertical crop, matched to a podcast or talking-head transcript. | [r/premiere "plugin generates B-roll from your audio"](https://reddit.com/r/premiere/comments/1sch83m/) (16 comments); a centre 9:16 crop keeps only about a third of a 16:9 frame | Retrieval ignores whether a shot can be cropped; reframe tools ignore retrieval | Creators, agencies |
| PS-7 | **Style/continuity-matched B-roll.** "Find shots that look like this": same colour grade, time of day, lens feel and location as the A-roll. | Twelve Labs markets image-to-video search for B-roll and alternate takes; Jumper's "Find Similar" | Similarity is semantic only, not *look* (grade, light) | Production houses |
| PS-8 | **Real-estate / project footage library.** Retrieve shots by project, amenity, tower and construction stage over time for listings, ads and progress updates. | ShotAI targets real-estate marketing teams; walkthrough, drone and amenity footage is reused across many campaigns | Generic tools don't understand "Tower B, clubhouse, 2025 vs 2026" | Developers, agencies |

**Extra papers for these:**
- [The 2023 Video Similarity Dataset and Challenge (Meta VSC)](https://arxiv.org/abs/2306.09489), for PS-2: copy detection that is robust to edits.
- [U-CESE: AI Challenge HCMC 2025](https://arxiv.org/abs/2605.23274), for PS-3.
- [MERVIN: event retrieval in Vietnamese news videos](https://arxiv.org/abs/2605.16120), for PS-3.
- MultiVENT 2.0, for PS-2 and PS-3.
- ArcFace, for PS-4.
- QVHighlights and UniVTG, for PS-5.
- SigLIP 2 dense features, for PS-7.
