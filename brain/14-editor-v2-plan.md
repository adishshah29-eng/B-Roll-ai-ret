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
