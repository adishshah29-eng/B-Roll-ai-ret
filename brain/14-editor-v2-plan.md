# Editor v2: implementation plan (the main product)

**The flow the user wants**
1. Upload a video.
2. It is split into units on the basis of **audio** (speech segments, pauses) and **video** (scene cuts, a filmstrip of frames) + the **script** (uploaded, or the transcript).
3. All of that goes to an **LLM**, which decides *where* B-roll goes and *what* each spot should show (stock-site search queries).
4. Those queries are sent to **Pixabay's API** (live) and the best clips are downloaded.
5. The clips are placed on the timeline; the user watches the **full video with B-roll** (instant overlay preview), edits it, renders the MP4.

```
upload ─▶ normalise (ffmpeg) ─▶ ┬ AUDIO : Whisper words + speech segments + pauses
                                └ VIDEO : scene cuts (OpenCV histograms) + filmstrip frames
        ─▶ UNITS (speech segments split at scene cuts, each with text, time, keyframe)
        ─▶ LLM (Gemini if GEMINI_API_KEY, else offline "concept" fallback)
              in : units + script + cuts        out : slots [{start,end,query,alt_queries,reason}] + summary
        ─▶ LIVE SOURCING : each query → Pixabay API → new clips embedded + added to the library (Tier S, 24 h API cache)
        ─▶ FILL : existing planner picks per slot (relevance + TRUE + CUTS + YOURS + licence) from library + fresh clips
        ─▶ EDITOR : player with B-roll overlay · lanes FRAMES / CUTS / SPEECH / B-ROLL · swap / nudge / re-search Pixabay / add / delete
        ─▶ RENDER : ffmpeg overlay, original audio kept
```

## Phases (each ends runnable)
| # | Build | Done when |
|---|---|---|
| V1 | `analyse.video_shots` (scene cuts + filmstrip jpgs) + `units` (audio ∪ video boundaries) + frame endpoint | project JSON has cuts, units, filmstrip; UI shows lanes |
| V2 | `app/editor/llm.py`: Gemini JSON client (validated/clamped) + offline concept fallback (CLIP vocab + keywords, Hindi-capable) | slots with `query`, `alt_queries`, `reason`, provider shown |
| V3 | `app/editor/live.py`: queries → Pixabay → ingest (dedupe, embed, tags) → snapshot refresh | fresh clips appear as candidates within ~30 s |
| V4 | pipeline stages with real progress; slot refill with `live=true` ("Search Pixabay again" on an edited query) | UI shows stage names; edited query fetches new clips |
| V5 | UI: filmstrip + cut markers + speech lane + query chips + provider badge; AI summary | full loop visible in the browser |
| V6 | end-to-end test on the TTS video (no key → fallback) and a real clip; docs | rendered MP4 checked frame by frame |

## Decisions
- LLM gets **text only** (units, timings, cut positions), never frames: cheap, fast, private. Provider interface so Gemini can be swapped.
- No key = still works: offline fallback turns each line into Pixabay-friendly keywords via keyword extraction + the CLIP concept vocabulary (works for Hindi). The UI says which engine produced the plan.
- Live clips are added to the library as Tier-S stock (thumbnail embedded, video downloaded only when previewed/rendered) so TRUE, licences, CUTS and YOURS all apply unchanged.
- Pixabay only for live search in v2 (key already in `.env`); Commons/Archive stay in the pre-built library.

## Risks
Pixabay rate limit (100 req/min; we use ≤ ~10 per project) · CLIP embedding on CPU (~25 clips per query ≈ 5 s) · RAM (Whisper freed after use; CLIP image tower loaded on first live fetch) · LLM JSON errors (validated, fallback on any failure).

## Fixes after the first real test (2026-10-03, Python lecture project)
A Python lecture got a cow clip. Root causes, all verified:
1. **Gemini was silently failing.** The key was valid (ListModels returned 44 models) but the default model `gemini-2.5-flash` answers "no longer available to new users" (HTTP 404) for new keys, so the app fell back to the offline engine without saying so.
   Fix, `app/gemini.py`: tries the configured model, then `gemini-flash-latest`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`; remembers the one that works; treats 429/5xx as transient (next model, one retry, failures cached 30 s); every error is redacted. The editor start screen runs a cached key check and shows green "Gemini (model)", amber "Gemini not working: offline engine" plus the reason, or "Offline engine".
2. **The key leaked into `project.json`** inside the HTTP error text (the key travels in the URL). Errors are now redacted everywhere they are stored or printed, and the one saved copy was scrubbed (`python -m eval.gemini_models` re-scrubs any project and lists usable models). Regenerate the key anyway: it also passed through the chat.
3. **The offline engine guessed.** Measured on 93 labelled lines (`eval/calibrate_concepts.py`): text-vs-concept similarity separates filmable lines from talk at only 59 % (filler scored 0.89, visual lines 0.81-0.92), so the old `CONCEPT_MIN` threshold could never reject anything. Replaced by a small linear probe trained on `resources/visualness.yaml` (leave-one-out 100 % on that clean set; real transcripts with borderline lines will do worse, so add lines there to improve it). Lines it judges unfilmable get no spot at all.
4. **Vocabulary had no tech concepts:** added 40 (code on screen, programmer typing, server room, website, AI robot, data charts, lecture, lab, gym...). **Keywords** now keep AI / web / dev / API and drop contractions (that's, it's).

Result on a Python-lecture sample: Gemini returns "python code laptop", "artificial intelligence robot", "code editor typing", "server room data center"; the offline engine leaves "Hi everyone", "I think the key idea", "Let me know in the comments" alone and maps Python lines to code concepts.

**Still open:** `MIN_CONF = 0.31` (a clip's relevance to its *query*) is too close to a typical good match to filter much, and the planner searches the whole library, so pick a domain library in the editor to keep clips on-topic.

## Fixes after the 8 s Python test (2026-10-03)
Test video: a man explaining Python (8 s). First run put Matrix rain over "used in AI and web dev", never showed Python, and scored every candidate 0.29-0.32.
- **(a) Queries**: prompt now demands one subject per query, the real topic named ("python code"), real footage over CGI, a banned-word list (screen, background, intro, subscribe, abstract, matrix ...) enforced again in `llm.clean_query`; asks for at least N spots and re-asks once (higher temperature) if fewer come back.
- **(b) Vision check**: `app/editor/judge.py` sends the sentence + up to 6 candidate thumbnails per spot to Gemini in ONE call; it returns which pictures really fit. Good ones are promoted, none-fit leaves the spot empty. Falls back silently without a key. Slot panel shows "Gemini checked the pictures: x of y fit" + reason. Needed because CLIP text-to-thumbnail scores are flat.
- **(c)** The editor no longer applies the house-style size bonus (`style_prior=False`); only real past choices count.
- **(d)** Opening-hook rule and minimum spot length scale with duration (`slots.hook_s`, `slots.min_slot`): max 10 % of a short video, 1.0 s minimum spot under 20 s.
- **(e)** With no library chosen, fetched clips go to a per-project `live` library ("Fetched: <project>"). "All footage" search and other projects exclude `live` libraries (`search._mask`), the editor adds its own via `also_lib`. 413 earlier test clips moved to "Fetched earlier (editor tests)".
- **(f)** Every alternative phrasing is searched (main query 25 clips, alternatives 12 each, up to 12 queries). App opens on the Editor tab, `#editor/<id>` opens a project, the project list refreshes when the tab is opened.
- Gemini calls rotate round-robin across models with per-model cooldowns (`app/gemini.py`).
Result: "Python is an incredibly powerful language" gets real programming code (snake clips rejected by the judge), "AI and web dev" gets a developer at a computer. Tests: 79 passed, 1 skipped.
Still open: coverage is Gemini-dependent (2 spots, 3.1 s of 8 s); CLIP scores stay flat so the judge needs Gemini; the judge sees thumbnails, not motion.

## General improvements after the 32 s travel test (2026-10-03)
Research: B-Script (115 expert editors): 73 % of cutaways start within 1 s of a transcript keyword; MLLM query paraphrasing; retrieve-then-LLM-rerank (MERLIN, X-CoT); frame-level matching (X-CLIP). None of this is travel-specific.
1. **Judge loop** (`pipeline.finish`, `judge.rewrite_queries`): spots where the vision judge says nothing fits get 3 new queries written from its reason, fetched, re-searched and re-judged on a wider pool (12). One round.
2. **Keyword-anchored cuts** (`llm._validate`, `_word`): Gemini returns an `anchor` word per spot; the cut starts on that word's Whisper timestamp (-0.15 s), kept inside its speech clip. UI: "Cut starts on <word>".
3. **In-point** (`app/editor/inpoint.py`): up to 5 windows per chosen clip, frames + narration to Gemini in one call, `shot.trim_in` set to the best window (preview and render already honour it). "No moment fits" is flagged in the panel.
4. **Phrasing fusion** (`pipeline._fill`, `_fuse`): main query + both alternatives are always searched; the candidate pool is their reciprocal-rank fusion (one entry per video). The pick still comes from the main query (so CUTS planning applies to it); the judge may override it.
5. **Coverage**: prompt allows two spots per long clip; planner retries once if it returns too few spots or < 30 % coverage.
Result on the 32 s travel video: 4/4 spots filled (was 3/4), 30-33 % coverage (was 28 %), 1 spot repaired by the loop, in-points chosen (e.g. train clip starts 28.5 s in). Tests: 79 passed.
Known: the whole analysis takes 3-4 min on this machine (12 Pixabay queries + embedding + 3 Gemini calls + clip downloads); the Gemini in-point choice may favour the first frame; coverage is still under the 45 % target.

## Speed pass (2026-10-03), not yet measured
The 32 s travel video took 175-240 s. Changes (from reading the code; no timing run was made, per the user):
- `live.fetch`: all Pixabay searches in parallel (4 threads); per query only clips whose tags match the query (a few untagged ones only if < 5 match); caps 25/12 -> 18/8; every clip embedded once in ONE batch (was one embedding call per query).
- `judge.check` also returns 3 new searches for spots where nothing fits (was a separate Gemini call).
- Gemini repair (search + fill + re-judge) overlaps with in-point selection for the spots that are already fine; in-point downloads and frame grabs run 4 at a time.
- `hydrate.ensure_file(index=False)` for in-point downloads: no background full-analysis job per clip (it competed for CPU and the database; the `database is locked` seen once was probably this).
- Audio (Whisper) and picture scan run at the same time; Whisper uses all CPU threads (`WHISPER_MODEL=base` in .env for ~3x faster, slightly less accurate); the face map is only computed if the offline engine is needed.
- The planner's second Gemini call now happens only when too few spots come back (not for coverage).
- Each project stores `timings` (seconds per stage); the editor header shows "analysed in N s", hover for the breakdown.
