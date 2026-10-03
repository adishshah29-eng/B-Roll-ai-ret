# Architecture and data flow (as built, 2026-10-03)

Thesis: B-roll is an editorial decision. Is it TRUE to the narration, does it CUT, is it YOURS.
Stack: FastAPI + vanilla JS (no build), SQLite (WAL), CLIP (sentence-transformers) on CPU, faster-whisper, OpenCV, ffmpeg (imageio-ffmpeg), Gemini (text + images), Pixabay API.

## 1. Layers

```
Browser (app/static: index.html, style.css, app.js, editor.js, libraries.js)
   tabs: Editor | Libraries | Search | Script | Memory
        │ fetch /api/*, /media/*
FastAPI (app/main.py + app/editor/api.py + app/libraries.py)
   /api/editor/*   projects, status, slots (PUT = refill), render, video, final.mp4, frames, config
   /api/libraries  list, create (folder | auto | empty), upload, delete
   /api/search     semantic search      /api/plan  script → shot plan      /api/export  XML / EDL / SRT / credits
   /api/memory/*   import past timelines, status, delete       /api/feedback  swaps → memory pairs
   /api/shots/*    card, provenance, similar, hydrate           /media/thumb|video/*
        │
Engines
   Library + ingest   app/libraries.py, app/sources/{pixabay,commons,archive,ingest,hydrate}.py, app/indexer/*
   Search + planner   app/search.py, app/planner.py, app/truth.py, app/cuts.py, app/memory.py, app/licence.py, app/niches.py
   Editor pipeline    app/editor/{pipeline,analyse,split,slots,llm,live,judge,inpoint,ffmpeg,store}.py
   Gemini + clients   app/gemini.py (model rotation, cooldowns, redaction), app/sources/base.py (token buckets, 24 h API cache)
        │
Data (data/)
   index.db           SQLite WAL: shots, stock_items, files, provenance, cut_features, jobs, ingest_cursors,
                      api_cache, memory_pairs, usage, libraries, meta (snapshot version)
   emb.f32            raw float32 rows, 512 numbers each, append-only; loaded as an immutable RAM Snapshot (atomic swap)
   thumbs/ previews/ hydrated/ cache/    jpgs, preview clips, downloaded stock clips, model caches
   projects/<id>/     source.mp4, work.mp4, frames/, transcript.json, project.json, final.mp4
Outside: Gemini API, Pixabay API, Wikimedia Commons, Internet Archive
```

## 2. Index time (how footage becomes searchable)

```
Sources: own folder / upload  |  Pixabay (live or auto-build)  |  Commons  |  Archive
   │  per clip: preview frame(s) → CLIP image embedding (512-d) → zero-shot tags (size, weather, daypart, season)
   │  own files also: shot detection, motion, OCR, EXIF/GPS, cut features (indexer jobs, background worker)
   ▼
SQLite rows (shots, stock_items/files, provenance, libraries) + append to emb.f32
   ▼
bump snapshot version → search holder rebuilds the RAM Snapshot (arrays: embeddings, size, motion, lib, licence, ...)
Stock clips are Tier S (thumbnail + metadata); the video is downloaded ("hydrated") only when previewed, judged or rendered.
```

## 3. Query time (Search tab, Script tab)

```
query text (English or Hindi, multilingual text tower)
 → mask by filters (size, motion, orientation, source, licence, library; "all footage" excludes live-fetch libraries)
 → relevance gate (GATE_DELTA, MIN_SCORE) + hybrid tag/title overlap (TAG_WEIGHT)
 → near-duplicate removal → MMR diversity → clusters (variety lanes) → per-source caps
Script tab adds: split script into beats → candidates per beat →
   TRUE   claims (places, time, weather) vs evidence (GPS, OCR, title, date, weather) → ok / unverified / warn / bad
   CUTS   transition costs between neighbours, Viterbi + local search over the whole sequence, smart trim
   YOURS  edit-memory boost (past swaps) and house-style prior
   licence class (own / safe / attribution / caution / restricted) → commercial-only option
 → shot cards + reasons → export: Premiere/Resolve XML, EDL, SRT, credits (licence sheet)
```

## 4. Editor pipeline (the main product), step by step

1. **Upload** (`POST /api/editor/projects`): video, optional script, library (or none), "fetch fresh clips" toggle. Saved to `data/projects/<id>/`.
2. **Normalise** (ffmpeg → `work.mp4`) and probe duration/size/audio.
3. **Audio and picture at the same time**: faster-whisper (words with timestamps, VAD) and an OpenCV histogram scene scan + filmstrip.
4. **Clips**: speech segments split at scene cuts (`split.build_units`); a supplied script replaces the ASR wording but never the timing.
5. **Gemini plans** (`llm.plan`): spots, `query` (one subject, banned words removed), `alt_queries`, `anchor` word; validated and clamped (opening hook = min(3 s, 10 % of length), spot length, no overlaps); the cut starts on the anchor word's Whisper timestamp. One retry if too few spots. Fallback: offline engine (visualness probe + concept vocabulary).
6. **Live fetch** (`live.fetch`): all Pixabay searches in parallel → keep clips whose tags match the query → one CLIP batch → Tier-S library rows in a per-project "live" library.
7. **Place** (`pipeline._fill`): the planner runs for the main query and both alternatives; pick = main query's choice (alternatives step in if empty); candidate pool = rank-fused union, one entry per video.
8. **Gemini checks the pictures** (`judge.check`): sentence + up to 8 thumbnails per spot, one call; promotes good ones, empties a spot if none fit, and proposes new queries for those spots.
9. **Repair** (new queries → fetch → place → re-judge on 12) and **start point** (`inpoint.refine`: up to 5 windows of the chosen clip, frames to Gemini, `trim_in`) run at the same time.
10. **Project ready** (`project.json` incl. `timings` per stage).
11. **Edit in the browser** (`editor.js`): overlay preview of the whole video, lanes (B-roll, frames, speech), swap / nudge / lock / delete / add / edit query / "Search Pixabay". `PUT slots` with `refill` re-runs steps 6-9 for unlocked spots; locked picks are untouched.
12. **Render** (`ffmpeg.render`): overlay each clip at its start/end, scaled to cover, original audio kept → `final.mp4`.

Every Gemini step is optional: no key or any failure means the offline engine / plain retrieval picks stand. All Gemini errors are redacted (key never stored or shown).

## 5. Libraries

- **folder**: index an existing folder of clips; **empty**: upload clips; **auto**: describe a domain, queries come from `resources/domains/*.yaml` → Gemini → generic, then Pixabay clips are fetched, embedded and scoped to that library; **live**: created per editor project for fetched clips (hidden from "all footage").
- A library scopes search, planning and the editor (`snap.lib`).

## 6. Rate limits, caching, failure handling

- Pixabay: token bucket, 24 h API cache in SQLite, 429/5xx backoff with jitter; Commons/Archive: own buckets.
- Gemini: round-robin over models, 60 s cooldown on 429, 15 s on 5xx, dead for the session on 404; text only except the picture check and start-point calls (thumbnails/frames as JPEG).
- SQLite WAL with a 30 s busy timeout; the in-point step downloads clips without queueing background analysis.

## 7. Known limits

CLIP text-to-thumbnail scores are flat (about 0.29-0.32), so picture quality leans on the Gemini check; coverage is under the 45 % target; in-point choice may favour the first frame; analysis time not yet re-measured after the speed pass; Hindi signboards are not OCR'd; XML import/export into Premiere/Resolve never tested on those apps; Memory is fed by Script-tab swaps and imported timelines (editor-tab swaps are not confirmed to be recorded).
