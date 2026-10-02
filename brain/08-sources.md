# Footage sources: own library + open platforms

Goal: a library of **thousands** of clips, not 40–80, without blowing up disk, RAM or indexing time.

## Sources
| Source | Access | What it gives us | License / rules | Best for |
|---|---|---|---|---|
| **Own footage** | Local folders | Full video | User's own | Real provenance (dates, GPS, faces) |
| **Pexels** | Videos API `GET /v1/videos/search` (key) | `video_files` (sd/hd links, w/h/fps), `video_pictures` (preview frames), `user`, `duration`, `url` | Pexels License; API requires a prominent Pexels link + credit to the videographer · 200 req/h, 20k/month · `per_page` ≤ 80 | Bulk modern B-roll, lots of India content |
| **Pixabay** | `GET /api/videos/` (key) | large/medium/small/tiny renditions with url, size, **thumbnail**; **tags**; user | Pixabay Content License · 100 req/60 s · **must cache results 24 h** · don't permanently hotlink; download what you keep · show the source | Tags + small renditions for cheap indexing |
| **Wikimedia Commons** | MediaWiki API | Video files + **per-file licence, upload date, often geo-coordinates** | CC BY/BY-SA/PD per file → attribution required | **Ground truth for TRUE** (real place + date) |
| **Internet Archive (e.g. Prelinger)** | advancedsearch API | Historic films, many public domain, with dates | Varies per item; Prelinger is largely PD | **Genuinely old footage** → TRUE "FILE · 1960s" tests |
| Coverr / Mixkit | Website / API (Coverr) | Curated B-roll | Free licences | Optional extra variety |

> Licences change. Store the licence text/URL per clip at ingest time and re-check terms before any public release.

## Three tiers (system design: tiered storage + lazy hydration)
| Tier | What's stored locally | What's computed | Cost per clip |
|---|---|---|---|
| **L: Local / owned** | Full video | Everything: shots, embeddings, OCR, flow/cut features, provenance | Highest |
| **S: Stock, indexed** | **Metadata + preview images only** (Pexels `video_pictures`, Pixabay thumbnail/tiny) | Embeddings of preview frames, tags from the API, zero-shot size/weather; cut features **deferred** | ~50–200 KB, < 1 s |
| **W: Web, live** *(online mode only)* | Nothing until chosen; results cached 24 h | Live API search when local relevance is weak | API call |

**Lazy hydration:** a Tier-S clip is downloaded (SD rendition) only when the user **previews it, adds it to a plan, or exports it**. At that point full analysis (cut features, OCR) runs on it and it is promoted to Tier L. HD is fetched at export only.

### Numbers (CPU laptop)
| Item | Estimate |
|---|---|
| Pexels metadata throughput | 200 req/h × 80 results ≈ **16,000 clips/hour** of metadata |
| Preview frames | Assume ~6 per clip → 3,000 clips ≈ 18k images ≈ **~10 min** to embed at ~30 img/s |
| Disk for 3,000 Tier-S clips | ~3,000 × 150 KB ≈ **~450 MB** (vs ~60 GB if we downloaded HD) |
| RAM for vectors | 3,000 × 512 × 4 B ≈ **6 MB**. Trivial |

## Ingestion pipeline
```
seed_queries.yaml  (≈ 60 India-themed queries × 2 sources × up to 80 results)
   → connector.search(q, page)            # rate-limited token bucket, exponential backoff + jitter on 429
   → normalise → StockItem{source, source_id, title, tags, user, page_url, licence, duration, w, h,
                            preview_urls[], rendition_urls{tiny,sd,hd}, fetched_at}
   → dedupe (source_id; cross-source near-dup via preview embedding cos > 0.97)
   → fetch previews (thread pool, 8 concurrent) → embed (batched) → tags/zero-shot → store as Tier S
```
- **Idempotent:** key = `(source, source_id)`; re-running the seed only adds new items.
- **Resumable:** a cursor per (query, page) is saved in SQLite.
- **API response cache:** 24 h on disk (required by Pixabay; saves Pexels quota).

## How the pillars use sources
- **TRUE:**
  - Stock clips carry `source = stock`.
  - If the narration claims a **specific real event/place/time** ("Mumbai today") and the shot is generic stock, mark it ⚠️ **"Stock footage, not actual event footage"**. That's another honest-labelling case ("stock-as-news").
  - Commons/Archive items with real dates and geo give **ground-truth provenance** for the Contradiction Set.
- **CUTS:** Tier-S shots use preview-based approximations (size, brightness); full cut features are computed after hydration.
- **YOURS:** memory works across sources; it learns e.g. "this editor never uses stock for openers".
- **Export:** a credits list (videographer + source link + licence) is generated automatically with the timeline.

## Schema additions
```sql
sources(id PK, name, kind /* local|pexels|pixabay|commons|archive */, enabled)
stock_items(id PK, source, source_id, title, tags, author, author_url, page_url, licence, licence_url,
            duration, width, height, preview_urls JSON, renditions JSON, fetched_at, tier /* S|L */,
            local_path NULL, UNIQUE(source, source_id))
-- shots.file_id → files for Tier L; shots.stock_id → stock_items for Tier S (one "shot" per preview cluster)
api_cache(key PK, body, fetched_at)        -- 24 h TTL
ingest_cursors(source, query, page, done)  -- resumable seeding
```

## Status update (2026-10-02)
- **Pexels: new API key issuance is paused.** Use it only if a teammate already has a key; otherwise skip it. The connector stays optional.
- Measured availability (search hit counts, video files):
  - **Wikimedia Commons:** "India traffic" 1,826 · "monsoon" 89 · "Indian market" 48 · "Delhi street" 11
  - **Internet Archive:** "India" 224,768 · "Bombay" 1,177 · "monsoon" 742 (mixed quality; many long films → our shot segmentation splits them)
- **New priority order:** Pixabay (if a key is available) → Internet Archive → Wikimedia Commons → own footage. Commons + Archive need **no key**.

### Pixabay key: working (tested 2026-10-02, stored in `.env`, gitignored)
- `totalHits` is **capped at 500 per query**, so diversity comes from many queries (≈ 60 seed queries → up to ~30k results, deduped).
- Hit counts: "india traffic" 500 · "indian street food" 500 · "monsoon" 28 · "delhi" 22 · "mumbai" 22 · "chai" 16.
- Each hit has **one thumbnail**. Renditions: tiny ≈ 0.5 MP / 1.5–2 MB, small ≈ 4 MB, medium ≈ 6–12 MB; `large` is sometimes empty.
- **Tier-S strategy for Pixabay:** embed the thumbnail + use the API `tags` as text for keyword search. On hydration, download the `tiny` rendition and run full shot analysis.
- Observation for TRUE: the query "mumbai rain" returns generic rain clips (thunderstorm, garden, window) with **no Mumbai evidence**. That is exactly the "stock-as-news" case to flag.

## Needed from the team
- Create free API keys for **Pexels** and **Pixabay** (sign up yourselves) and put them in a `.env` file: `PEXELS_API_KEY=...`, `PIXABAY_API_KEY=...`. Never commit it.
- Commons and Internet Archive need no key.

## Implementation notes (P2b, built 2026-10-02)
- **Code:** `app/sources/{base,pixabay,commons,archive,ingest,hydrate}.py`; seeds in `resources/seed_queries.yaml`.
- **Run:** `python -m app.sources.ingest --seed --max 3000` (CLI) or `POST /api/ingest` (runs inside the server, progress in the status bar).
- **Measured:** ~1.6 clips/s; 1,500 clips ≈ 16 min on this CPU laptop; 33 cross-source near-duplicates dropped (cos > 0.97).
- **Pixabay:** no upload date → provenance `date_source=unknown` (correct: TRUE shows ⚠️ unverifiable). AI-generated and low-quality items are filtered out (`isAiGenerated`, `isLowQuality`).
- **Commons:** gives `DateTimeOriginal` (the recording date) + licence + sometimes GPS. Real finds: *A Native Street in India (1906)*, *Street Scenes in Bombay (1929)*, *Street in Mumbai (2016, CC0)*. Best ground truth for TRUE.
- **Archive:** a bare full-text query is very noisy (WW2 clips for "Bombay"), so queries are restricted to `title:`/`subject:` and `youtube-*` mirrors are excluded. Items are long films with one cover image → capped at 300.
- **Hydration:** Pixabay `small`/`tiny` (1–5 MB, ~4 s) · Commons: 480p/360p/240p VP9 transcode if it exists, else the original if ≤ 60 MB (OpenCV decodes webm fine) · Archive: smallest mp4 derivative ≤ 300 MB. After the full index runs, the Tier-S placeholder is retired and the new shots inherit source, credits, recorded date and GPS (`_adopt_stock`).
- **Gotchas found:**
  - Wikimedia answers **429** to bursts of HEAD requests; the code now backs off (Retry-After + jitter) and treats a throttled response as "busy", never as "does not exist".
  - Export used to drop un-hydratable clips silently; it now reports them (`X-Epoch-Skipped` header → UI alert).
  - Never put API keys in the cache key (tested).
