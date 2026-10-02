# Context

## Name (working)
**True · Cuts · Yours**: editorially-aware B-roll retrieval. (Rename freely; keep the three-word idea.)

## Thesis (say this first in every pitch)
> Every tool treats B-roll as a **search problem**: find shots that match the words.
> Editors judge B-roll on three things search ignores: **Is it true? Does it cut? Is it ours?**

## One-liner
An offline AI system that turns a script into a B-roll timeline from **your own footage**. Every shot is **checked against the narration's claims**, chosen as a **sequence that cuts**, and **ranked by what you chose in your past edits**. Works in Hindi and English.

## The three pillars
| Pillar | What it does | Why it's novel |
|---|---|---|
| **TRUE** | Provenance card per shot (date, place from OCR/GPS/landmarks, weather/season, people); claims extracted from the script; contradiction verdict with evidence; auto "FILE · 2019" label | Fact-checking today happens *after* publishing. We stop out-of-context footage *at the point of editing*. India's 2024 election fakes were mostly relabelled old footage. |
| **CUTS** | Per-shot cut features (motion direction, exposure, colour, size); transition costs; DP/Viterbi picks the whole sequence | *Learning to Cut* (ICCV 2021) exists as research; nobody applies it to retrieval |
| **YOURS** | Mine (narration → chosen shot) pairs from past timelines; memory boost + learning-to-rank + house-style priors | Zero labelling; B-Script needed expert annotation; no product does this |

**Base everyone expects:** shot-level multilingual search · relevance-ranked variety (gate → dedupe → MMR → clusters) · Find similar · script → timeline · XML/EDL export.

## Our moat against 20 Claude-assisted teams
1. A named, contrarian thesis (above).
2. **Our own benchmark:** Indic B-roll Query Set (100+ Hindi/Hinglish queries) + Contradiction Set (30+ planted conflicts).
3. **Real user quotes:** talk to 2–3 editors/YouTubers on campus.
4. A demo moment no one else has: the red **"Contradicts narration"** flag with evidence.

## Problem evidence (short)
- An editor took 5 h to add B-roll to a 14-min video using footage they already owned; another spent an hour finding a 3-s clip in 100 GB.
- Most of India's 2024 election video misinformation was old footage relabelled ("cheapfakes").
- Editors hand-build V1/V2/V3 selects stacks to cut B-roll; outtakes never get used.

Full statement: [FINAL_PROBLEM_STATEMENT.md](../FINAL_PROBLEM_STATEMENT.md).
