# Full Implementation Plan: True · Cuts · Yours

> The build bible for coding round 2. Read with [02-architecture.md](02-architecture.md) (data model, API contract, performance design) and [08-sources.md](08-sources.md) (stock sources).
> **Rule:** every phase ends **runnable**, with its acceptance test passing. Never start a phase while the previous one is red.

---

## 0. Principles
1. **Heavy work at index time, light work at query time.** The query path is lookups + small maths only.
2. **Vertical slices.** Each phase adds a user-visible capability end-to-end (backend + API + UI).
3. **Fail soft.** Every pillar degrades to "unknown" or "neutral"; search never crashes because a signal is missing.
4. **One scoring function** (`planner.score`) is the only place pillars combine. Easy to tune, easy to explain.
5. **Measure.** Every API response carries `timings`; `eval.py` produces the numbers we show.

---

## 1. Stack & dependencies

| Need | Choice | Status |
|---|---|---|
| Language/runtime | Python 3.11 | ✅ installed |
| Vision-language model | `sentence-transformers` `clip-ViT-B-32` (image + English text, 512-d) | lib ✅ · model ⬇ ~600 MB |
| Multilingual text model | `clip-ViT-B-32-multilingual-v1` (same 512-d space; Hindi ✅) | ⬇ ~540 MB |
| Video decode | OpenCV `cv2` 5.0 (no ffmpeg on the machine) | ✅ |
| Optical flow, image ops | OpenCV, numpy | ✅ |
| Clustering, re-ranker | scikit-learn | ✅ |
| Sequence DP | numpy (own Viterbi) | ✅ |
| OCR (TRUE) | **EasyOCR** (`en` + `hi`) | ⬇ `pip install easyocr` + ~100 MB models (P5 only) |
| API | FastAPI + uvicorn | ✅ |
| HTTP clients | requests / httpx | ✅ |
| Config | python-dotenv, PyYAML | ✅ |
| Tests | pytest | ✅ |
| MP4 metadata (date/GPS) | **own ~60-line MP4 atom parser** (`mvhd` creation time, `©xyz` GPS) | write it; no dependency |
| UI | Vanilla HTML/CSS/JS served by FastAPI (no build step) | — |

---

## 2. Repository structure
```
Epoch/
├── .env                      PIXABAY_API_KEY=... (gitignored)
├── run.bat                   start server (+ LAN)
├── requirements.txt
├── app/
│   ├── config.py             paths, tunables (all knobs in one place)
│   ├── log.py                timing helper: with timer("stage"): ...
│   ├── db.py                 SQLite connect (WAL), schema migrate, small query helpers
│   ├── models.py             lazy singletons: clip (img+en text), mtext (multilingual); embed_images, embed_texts
│   ├── store.py              EmbeddingStore: append-only .npy + id map + active mask; Snapshot (immutable, atomic swap)
│   ├── media.py              cv2 helpers: probe, sample frames, thumbs, mp4 atom parser (date, GPS)
│   ├── indexer/
│   │   ├── jobs.py           SQLite job queue: enqueue, claim, complete, fail, reset_stale
│   │   ├── pipeline.py       stages: probe → sample → segment → embed → tags → cut_features → provenance → ocr
│   │   ├── tags.py           zero-shot size/weather/daypart/season/place prompts; motion level
│   │   ├── cutfeat.py        head/tail flow, luma, warmth, saliency centroid, motion peak
│   │   └── worker.py         loop: claim → run stage → commit → bump index_version
│   ├── sources/
│   │   ├── base.py           Connector interface, StockItem dataclass, TokenBucket, api_cache (24 h)
│   │   ├── pixabay.py
│   │   ├── archive.py        Internet Archive advancedsearch + item thumbs
│   │   ├── commons.py        Wikimedia Commons search + imageinfo (date, licence, geo)
│   │   ├── ingest.py         CLI: seed queries → normalise → dedupe → previews → Tier-S index
│   │   └── hydrate.py        download rendition → register as local file → enqueue full pipeline
│   ├── search.py             retrieve(), gate, dedupe, mmr, cluster, label, similar, filters
│   ├── truth.py              gazetteer, extract_claims, verdict, labels
│   ├── cuts.py               transition_cost, plan_sequence (Viterbi), fix_repeats, smart_trim
│   ├── memory.py             import_timeline, pairs, boost, reranker train/predict, house_style
│   ├── planner.py            beats(), score(), plan() → combines all pillars
│   ├── export.py             xmeml v4, EDL, labels SRT, credits.txt
│   ├── timeline_import.py    parse xmeml/EDL → placements (used by memory + audit)
│   ├── main.py               FastAPI app, routes, startup warm-up, snapshot reloader
│   └── static/  index.html · app.js · style.css
├── data/                     index.db · emb.npy · ids.npy · vocab_emb.npy · thumbs/ · previews/ · hydrated/ · cache/
├── resources/                gazetteer.json · vocab.txt · prompts.yaml · seed_queries.yaml
├── eval/                     queries.yaml · contradictions.yaml · projects/ · eval.py · label_tool notes
├── footage/                  own clips (gitignored)
└── tests/                    test_mmr.py · test_viterbi.py · test_claims.py · test_mp4meta.py · test_xml_roundtrip.py
```

---

## 3. Process & runtime model (system design)

```
 ┌──────────────── API process (uvicorn) ────────────────┐      ┌──────── Indexer process ─────────┐
 │ models: multilingual text (+ clip for image queries)  │      │ models: clip (image + en text)   │
 │ Snapshot: emb matrix + ids + tag arrays (read-only)   │◀─────│ writes rows, appends emb.npy,    │
 │ reloads when meta.index_version changes (poll 2 s)    │ SQLite│ bumps index_version per batch   │
 │ LRU caches: query→emb, (query,filters,λ)→result       │  WAL  │ 1 process, torch threads = n−2   │
 └───────────────────────────────────────────────────────┘      │ I/O thread pool (8) for previews │
                                                               └──────────────────────────────────┘
```
- **Why one indexer process, not a pool:** RAM is 6 GB and each process would load CLIP (~600 MB). We use **torch intra-op threads** for CPU parallelism and **threads for I/O** (downloads). Revisit with ≥ 16 GB RAM.
- **Consistency:** the API serves an **immutable snapshot**; the indexer never mutates arrays the API reads. A version bump makes the API build a new snapshot off-thread, then swap one reference.
- **Idempotency:** jobs are unique on `(target_id, stage, model_ver)`. On startup, `running` jobs are reset to `pending`.
- **Backpressure:** the queue is drained in priority order; batch size adapts (halved on MemoryError); downloads limited by the TokenBucket per source.

---

## 4. Database schema (complete)
```sql
PRAGMA journal_mode=WAL;
meta(key PK, value)                               -- index_version, schema_version
files(id PK, path UNIQUE, content_hash, duration, fps, width, height, rotation,
      created_at, gps_lat, gps_lon, status, tier, stock_id NULL)
stock_items(id PK, source, source_id, title, tags, author, author_url, page_url, licence, licence_url,
            published_at, gps_lat, gps_lon, duration, width, height,
            preview_urls JSON, renditions JSON, fetched_at, tier, UNIQUE(source, source_id))
shots(id PK, file_id NULL, stock_id NULL, t_start, t_end, thumb, emb_row,
      size_tag, motion, motion_score, orientation, weather, daypart, season, quality, active DEFAULT 1)
provenance(shot_id PK, shot_date, date_source, gps_lat, gps_lon, ocr_text, ocr_lang,
           place_guess, place_src, place_conf, source_kind)
cut_features(shot_id PK, head_dx, head_dy, tail_dx, tail_dy, head_luma, tail_luma,
             head_warmth, tail_warmth, sal_x, sal_y, peak_t, approx INT)
jobs(id PK, target_kind, target_id, stage, model_ver, priority, status, attempts, last_error, updated_at,
     UNIQUE(target_kind, target_id, stage, model_ver))
ingest_cursors(source, query, page, done, PRIMARY KEY(source, query, page))
api_cache(key PK, body, fetched_at)
memory_pairs(id PK, project, text, shot_id, label, created_at)   -- label 1 chosen / 0 offered-not-chosen
usage(shot_id, project, used_at)
plans(id PK, script, created_at, options JSON) ; plan_beats(plan_id, idx, text, t0, t1, chosen JSON, alts JSON)
CREATE INDEX ix_shots_file ON shots(file_id); CREATE INDEX ix_shots_stock ON shots(stock_id);
CREATE INDEX ix_shots_tags ON shots(size_tag, motion, orientation); CREATE INDEX ix_jobs_q ON jobs(status, priority);
```

---

## 5. Phases

### P0: Setup (foundation)
**Tasks**
1. Download models (warm the HF cache): `python -c "from sentence_transformers import SentenceTransformer as S; S('clip-ViT-B-32'); S('clip-ViT-B-32-multilingual-v1')"`.
2. Create the structure in §2, `requirements.txt`, `config.py`, `log.py`.
3. Write `resources/`: `prompts.yaml` (size/weather/daypart/season/place prompts), `vocab.txt` (~200 B-roll concepts incl. Indian ones), `seed_queries.yaml` (~60 queries), `gazetteer.json` (~150 Indian cities, metros and landmarks with Hindi spellings + aliases, e.g. "Delhi Metro" → Delhi, "CST" → Mumbai).
4. Footage: 30+ own/phone clips + planted TRUE traps (see [01-scope.md](01-scope.md)).

**✅ Accept:** `python -m app.models --selftest` embeds 1 image + an EN and a HI sentence; cos(HI, EN translation) > 0.7.

---

### P1: Indexing core (local footage)
**Files:** `db.py`, `store.py`, `media.py`, `indexer/{jobs,pipeline,tags,worker}.py`

| Stage | Logic | Notes |
|---|---|---|
| `probe` | cv2: fps, frame count, w/h; `mp4meta.read(path)` → creation_time, GPS; content hash = sha1(size + first 1 MB + last 1 MB) | rename-safe identity |
| `sample` | frame every `SAMPLE_EVERY_S` (1.0 s) via `CAP_PROP_POS_MSEC`; resize to 224 short side; keep 64×36 grey copies for motion | one decode pass per file |
| `segment` | batch-embed samples; cut when cos(prev, cur) < `CUT_SIM` (0.82) or window ≥ `WINDOW_S` (4 s); shot emb = normalised mean | B-roll = long takes → windows |
| `tags` | zero-shot vs precomputed prompt embeddings: size, weather, daypart, season; motion = mean grey diff → still/moderate/action; orientation | prompt embs cached in `vocab_emb.npy` |
| `thumb` | middle sample → 320 px JPEG | `data/thumbs/{shot}.jpg` |
| commit | one transaction per file; append embeddings; bump `index_version` | crash-safe |

**System design:** idempotent jobs · WAL · append-only embedding store · batching (32 frames/forward pass).
**✅ Accept:** `python -m app.indexer.worker --path footage` → prints files/shots/sec; re-run does 0 new work; killing it mid-run and restarting resumes; `pytest tests/test_mp4meta.py` passes.

---

### P2: Search core
**File:** `search.py`
```python
retrieve(q_emb, mask) -> (idx, scores)          # one matmul on snapshot.E (N×512), boolean tag mask
gate(scores) -> keep >= max(MIN_SCORE, best - GATE_DELTA)
dedupe(idx) -> collapse same source & |Δt| < 10 s & cos > DEDUPE_SIM (0.93)
mmr(idx, scores, k, λ) -> picked                # (1-λ)·rel − λ·max cos to picked
cluster(picked) -> groups                       # Agglomerative(cosine, distance_threshold=CLUSTER_DIST)
label(group) -> str                             # top vocab concept by mean emb; falls back to API tags (stock)
missing(picked) -> ["no close-up shots"]        # size buckets absent among relevant results
similar(shot_id, k)                             # neighbours of a shot embedding, deduped
search(query, k=24, diversity=0.3, filters) -> {clusters, missing, timings}
```
**System design:** funnel (500 → gate → ≤ 100 → k) · LRU on `encode(query)` and `search(...)` (invalidated on version bump) · snapshot reads.
**✅ Accept:** `python -m app.search "rain on the road"` and `"बारिश में सड़क"` → ≥ 3 clusters with sensible labels, < 100 ms warm; `pytest tests/test_mmr.py`.

---

### P2b: Open-source library (Tier S)
**Files:** `sources/{base,pixabay,archive,commons,ingest,hydrate}.py`
| Connector | Search call | Normalised fields | Preview for Tier S |
|---|---|---|---|
| Pixabay | `/api/videos/?q&per_page=200&page` (500-hit cap/query) | tags, user, page_url, renditions tiny/small/medium | `videos.tiny.thumbnail` |
| Internet Archive | `advancedsearch.php?q=<q> AND mediatype:movies&fl[]=identifier,title,date,licenseurl&rows&page` | date (→ provenance!), licence | item thumbnail `/services/img/{id}`; on hydrate use the low-res `.mp4` derivative |
| Commons | `action=query&generator=search&gsrsearch=<q> filetype:video&gsrnamespace=6&prop=imageinfo|coordinates&iiprop=url|timestamp|extmetadata` | timestamp, **coordinates**, licence | `iiurlwidth=320` thumb |

- `TokenBucket` per source (Pixabay 100/min, Commons/Archive polite 1–2 req/s + User-Agent); retries with exponential backoff + jitter on 429/5xx.
- `api_cache`: 24 h TTL (Pixabay requirement; saves quota for all).
- **Dedupe:** `(source, source_id)` unique; cross-source near-dup via preview embedding cos > 0.97.
- **Tier-S shot:** one shot per item, using the preview embedding; `t_start=0, t_end=duration`; tags from the zero-shot prompts + API tags into a keyword field; `cut_features.approx=1` (luma/warmth from the thumbnail; flow neutral).
- **Hydration** (on preview/plan/export): download the smallest usable rendition → `data/hydrated/` → `files` row (tier L, stock_id) → enqueue the full pipeline → deactivate the Tier-S placeholder shot (`active=0`) → new shots inherit provenance from the stock item.

**✅ Accept:** `python -m app.sources.ingest --seed --max 3000` → ≥ 2,000 Tier-S items in < 20 min, re-run adds 0; search mixes own + stock with source badges; hydrating one item produces real shots.

---

### P3: API + UI (base product)
**Routes (`main.py`):**
```
GET  /api/status                     queue, counts per tier, index_version, model status
POST /api/index        {path}        enqueue local folder
POST /api/ingest       {queries?, max} run stock seeding in the indexer process
POST /api/search                     (contract in 02-architecture.md)
GET  /api/similar/{shot_id}
GET  /api/shots/{id}                 full card (tags, provenance, cut features, source/licence)
POST /api/shots/{id}/hydrate
GET  /media/thumb/{shot_id}          Cache-Control: public, max-age=31536000, immutable
GET  /media/video/{file_id}          HTTP Range 206 streaming
```
- Startup: load models, warm-up encode, build snapshot, start the version poller.
- Every response includes `timings: {encode, retrieve, mmr, cluster, db}`.

**UI (`static/`):** top bar (library stats, index progress) · **Search tab**: query box, diversity slider, filter chips (size/motion/orientation/source), cluster rows (best + "N more"), shot card (thumb, timecode, tags, source badge, ⓘ provenance), click → preview modal (`<video>` seeked to the shot), "Find similar".
**✅ Accept:** from the browser, Hindi + English searches work; preview seeks correctly; LAN laptop works via `http://<ip>:8000`.

---

### P4: Script → plan → export (base complete)
**`planner.py`**
```python
beats(script, wpm=150) -> [Beat(i, text, dur)]   # split on . ! ? । \n; merge < 2 s; dur = words/(wpm/60)
candidates per beat = search pipeline without clustering, k = CAND_K (8), batch-encoded
score(beat, shot) = W_REL·rel                       # pillars add terms in P5–P7
plan(script, opts) -> greedy no-repeat (P4) → Viterbi (P6)
```
**`export.py`**: **xmeml v4** (sequence 25 fps, video track, clipitems with `file` + `pathurl` file://localhost/C:/..., in/out frames), **EDL** CMX3600, **labels.srt** (FILE/STOCK labels as captions at the clip times), **credits.txt** (author, source, licence, URL). Hydrate stock clips before export.
**`timeline_import.py`**: parse xmeml/EDL → placements (used by P7 + audit). Round-trip test.
**UI Script tab:** textarea → Plan → beat rows (text, duration, chosen thumbs, alternatives strip to swap) → Export buttons.
**✅ Accept:** the 5-line sample script → plan in < 1 s; the XML imports into Premiere **and** Resolve with linked media; `pytest tests/test_xml_roundtrip.py`.

---

### P5: TRUE (headline pillar)
**Index side (new pipeline stages, priority after tags):**
- `provenance`:
  - **date:** mp4 `mvhd` → stock `published_at`/Archive `date` → file mtime (date_source records which)
  - **GPS:** mp4 `©xyz` / Commons coordinates
  - **source_kind:** own / stock / archive
- `ocr`:
  - **gate:** edge density in horizontal bands (cheap) → only text-likely keyframes go to EasyOCR (en+hi)
  - store the text; **gazetteer match** → `place_guess` (`place_src = ocr`)
- `place zero-shot`: CLIP prompts for ~20 major Indian cities/landmark types → `place_guess` (`place_src = visual`, low confidence).

**Query side (`truth.py`):**
```python
extract_claims(text) -> Claims(place, time_window, weather, event, people)
  place: gazetteer (EN/HI/aliases) · time: regex (today/aaj/आज, yesterday/kal, this week/month/year, YYYY, "this monsoon")
  weather: lexicon (rain/बारिश, flood/बाढ़, sunny/धूप, fog/कोहरा, snow) · event: lexicon (protest, rally, festival...)
verdict(claims, shot) -> Verdict(status, evidence[], label)
```
Rules (fail soft: missing evidence → ⚠️, never ❌):
| Check | ❌ bad | ⚠️ warn | label |
|---|---|---|---|
| place | OCR/GPS city ≠ claimed city (different gazetteer entry) | no evidence / only weak visual guess | — |
| time | shot_date outside the claim window (e.g. "today" vs > 30 days old) | date unknown | `FILE · <year>` |
| weather | zero-shot opposite weather, conf > 0.6 | weak | — |
| stock-as-news | — | claim names a specific place/time and source = stock | `STOCK · not event footage` |

- `planner.score += −W_TRUE · penalty` (bad → excluded; warn → 0.2) and the label is attached.
- UI: verdict badge (✅ ⚠️ ❌) per chosen shot; **"Rejected" drawer** with evidence; provenance card in the shot modal.
- `/api/audit` (stretch): imported timeline + script → report.

**✅ Accept:** on the Contradiction Set, flag precision ≥ 0.8 and recall ≥ 0.7; in the demo script, the Delhi-signboard trap is ❌ with evidence `OCR: "Delhi Metro"` and the 2019 clip is kept with `FILE · 2019`; `pytest tests/test_claims.py`.

---

### P6: CUTS
**Index side (`cutfeat.py`, a stage for Tier L):** read frames at shot head (t0, t0+0.2 s) and tail (t1−0.2 s, t1) at 160 px → Farneback flow mean (dx, dy); luma = mean Y; warmth = mean R / mean B; saliency centroid = centre of mass of a Sobel edge map; peak_t = argmax of motion diff over the shot's samples.
**Query side (`cuts.py`):**
```python
transition_cost(a, b) = 2.0·jump + 1.0·flip + 0.8·Δluma + 0.5·Δwarmth + 0.6·[same size] − 0.4·[size progresses]
  jump = same source ∧ |Δt| < 10 s ∧ cos > 0.9 ; flip = dot(a.tail_dir, b.head_dir) < −0.3 (both moving)
  approx features (Tier S) → flow terms = 0
plan_sequence(slots, cands, unary) -> Viterbi over slots × CAND_K states   # O(S·K²)
fix_repeats(seq) -> replace duplicates with next-best and re-score locally
smart_trim(shot, dur) -> in/out centred on peak_t, clamped to the shot
```
- Long beats (> 6 s) get 2 slots, so size progression can happen inside a beat.
- UI: toggle **Greedy vs Cut-aware**, a sequence-cost meter, and per-transition badges (jump, flip, exposure).

**✅ Accept:** on 10 test scripts, cut-aware has ≥ 50% fewer jump cuts + flips than greedy at ≤ 5% relevance loss; `pytest tests/test_viterbi.py` (brute-force equality on small cases).

---

### P7: YOURS (Edit Memory)
**`memory.py`**
```python
import_timeline(xml_path, script_text|srt, project) -> pairs
  placements = timeline_import.parse(xml)        # file, src_in/out, rec_in/out
  map each placement → shot ids (file path/name match, time overlap)
  narration timing: SRT if given, else script words spread at wpm → text overlapping rec_in..rec_out
  positives = (text, shot); negatives = other candidates the search returns for that text (label 0)
boost(beat_text, cand_ids) -> {id: b}            # top-5 past texts (cos > 0.6) → chosen shots + visual neighbours
train() / predict(features)                      # LogisticRegression on [rel, boost, size 1-hot, motion 1-hot,
                                                 #  is_stock, used_count, dur_fit]; retrain on /api/feedback
house_style() -> {size_mix, avg_dur, opener}     # priors → planner unary term W_STYLE·log p(size)
```
- **Implicit feedback:** every swap/accept in the Script tab → `POST /api/feedback` → new pairs → retrain (ms on this data size).
- UI **Memory tab:** import XML + script, list projects, house-style card; **Memory toggle** in the Script tab; "chosen N× before" badges.
- Eval data: create 3 small past projects (script + XML made in our own tool and edited by a teammate).

**✅ Accept:** leave-one-project-out Recall@10 with memory > without (target +20% relative); toggling memory visibly re-ranks; feedback updates rankings without a restart.

---

### P8: Planner integration (one formula)
```
unary(beat, shot)  = W_REL·rel + W_MEM·boost + W_RR·reranker_prob + W_STYLE·log p_style(size)
                     − W_TRUE·truth_penalty − W_USED·overuse
pairwise(a, b)     = W_CUT·transition_cost(a, b)
objective          = Σ unary − Σ pairwise − repeat_penalty      → Viterbi
defaults: W_REL 1.0 · W_MEM 0.3 · W_RR 0.3 · W_STYLE 0.1 · W_TRUE 1.0 (bad = excluded) · W_USED 0.1 · W_CUT 0.5
```
`/api/plan` options toggle each pillar (for the demo and ablation numbers). Each chosen shot returns an **explanation** list: why it was picked, e.g. `rel 0.71 · ✅ consistent · wide→close · chosen 4× before`.

---

### P9: Benchmark, evaluation, hardening
- **Label tool** (hidden UI mode): run a query → 👍/👎 per result → writes `eval/queries.yaml`. Fast way to label 100+ queries.
- `eval/contradictions.yaml`: (line, shot_id, expected ok/warn/bad).
- `eval.py` prints a metrics table:
  - Recall@10 · nDCG@10 · near-dup rate
  - flag P/R
  - jump cuts/flips (greedy vs DP)
  - memory LOPO Recall@10
  - p50/p95 latency
  - **ablations** with each pillar off
- Hardening:
  - error states in the UI
  - `run.bat` (activate, start, open browser)
  - `data_backup/` snapshot
  - first-run checks (models present, RAM warning)
  - Windows Firewall note for LAN

**✅ Accept:** `python eval/eval.py` prints the full table; a fresh restart → demo flow works end-to-end twice.

---

## 6. Dependency graph & team split
```
P0 → P1 → P2 → P3 → P4 ─┬→ P5 TRUE ─┐
          └→ P2b (parallel after P1) ├→ P8 → P9
                         ├→ P6 CUTS ─┤
                         └→ P7 YOURS ┘     (P5/P6/P7 are independent once P4's planner interface exists)
```
| Person | Owns | Starts on |
|---|---|---|
| **A: ML/backend** | P1, P2, P6, P8 | Indexer |
| **B: Backend/UI** | P3, P4 (API, UI, export, timeline import), UI for all pillars | UI against mocked JSON from the contract, from minute 0 |
| **C: Data/Truth** | P0 resources (gazetteer, vocab, prompts, seeds), P2b connectors, P5 TRUE, P9 benchmark labelling | Resources + footage + traps |
| P7 YOURS | A + C after P4 | — |

**Contracts to agree before splitting:** the API JSON in `02-architecture.md`, plus these Python signatures:
```python
search.candidates(texts: list[str], k:int) -> list[list[Hit]]          # batch, for planner
truth.verdict(claims, shot_id) -> Verdict ; truth.extract_claims(text) -> Claims
cuts.plan_sequence(slots, cands, unary) -> list[int] ; cuts.transition_cost(a, b) -> float
memory.boost(text, ids) -> dict[int,float] ; memory.predict(rows) -> np.ndarray
```

---

## 7. Performance checklist (verify in P9)
- [ ] Models loaded once; warm-up at startup; `torch.set_num_threads(cores-2)` in the indexer, 2–4 in the API
- [ ] Query encode cached (LRU 1024); search result cache invalidated on version bump
- [ ] Single matmul over the snapshot; tag filters as numpy masks (no SQL in the hot loop)
- [ ] OCR gated; cut features at index time; nothing heavy in `/api/plan`
- [ ] Batch encoding of all beats in one call
- [ ] SQLite WAL, indexes present, one connection per thread
- [ ] Thumbs immutable-cached; video via Range; `loading="lazy"`
- [ ] p95 search < 100 ms warm, plan (10 beats) < 400 ms, measured by `eval.py`

## 8. Risk register
| Risk | Likelihood | Mitigation |
|---|---|---|
| RAM (6 GB) with two processes + EasyOCR | High | Close apps; EasyOCR loaded only in the indexer and only during the OCR stage, then freed; API loads the multilingual text model only (image model lazily, for image queries) |
| OCR quality on signboards | Med | Gate + clear trap clips; show the OCR text as evidence; ❌ only on exact gazetteer matches |
| Zero-shot tags noisy (size/weather) | Med | Used as soft scores/filters; ❌ never from weak signals |
| xmeml import quirks between NLEs | Med | Round-trip test in P4; EDL + SRT fallbacks |
| Stock API limits / outages | Low–Med | 24 h cache, resumable cursors, token bucket, seed once and reuse |
| Archive items long/low quality | Med | Window segmentation; quality filter (blur/exposure) in gate |
| Too little data for YOURS | Med | Build 3 small past projects ourselves; feedback loop adds pairs live |

## 9. Definition of done
- [ ] Index own folder + ≥ 2,000 stock items; search EN/HI with variety clusters < 100 ms
- [ ] Script → plan with ✅/⚠️/❌ verdicts + evidence, cut-aware sequence, memory-boosted ranking, explanations
- [ ] Export XML/EDL/SRT/credits → opens in Premiere and Resolve
- [ ] Memory import + live feedback learning
- [ ] `eval.py` metrics table incl. ablations
- [ ] LAN demo + backup + rehearsed demo script ([06-demo-script.md](06-demo-script.md))
