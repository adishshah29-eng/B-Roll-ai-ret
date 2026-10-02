# Architecture

> Base layer below. The three pillars (TRUE / CUTS / YOURS) add `app/truth.py`, `app/cuts.py`, `app/memory.py` and the tables at the end of this file.
> Pillar features: [01-scope.md](01-scope.md) · interfaces + planner score: [03-implementation-plan.md](03-implementation-plan.md).

```
Browser (vanilla HTML/JS)  ──HTTP──▶  FastAPI (app/main.py)
                                         ├─ /api/index    → indexer thread (app/indexer.py)
                                         ├─ /api/search   → app/search.py
                                         ├─ /api/similar  → app/search.py
                                         ├─ /api/plan     → app/planner.py
                                         ├─ /api/export   → app/export.py
                                         └─ /media/*      → thumbs + video (range requests)
Storage: data/index.db (SQLite) · data/emb.npy (float32, row i = shot id order) · data/thumbs/*.jpg
Models:  sentence-transformers clip-ViT-B-32 (image + English text)
         sentence-transformers clip-ViT-B-32-multilingual-v1 (Hindi/English text → same space)
```

## Project layout
```
app/
  config.py     paths, constants (SAMPLE_EVERY_S=1.0, WINDOW_S=4, CUT_SIM=0.82, ...)
  models.py     lazy singletons: img_model, txt_model; embed_images(), embed_text()
  db.py         sqlite schema + helpers
  indexer.py    scan → sample frames → segment → embed → tag → save   (also CLI)
  search.py     search(), similar(), mmr(), cluster(), label()
  planner.py    plan(script) → beats with chosen + alternatives
  export.py     to_xmeml(plan), to_edl(plan)
  main.py       FastAPI routes + static files
  static/       index.html, app.js, style.css
data/  footage/  run.bat
```

## Data model (SQLite)
```sql
files(id INTEGER PK, path TEXT UNIQUE, duration REAL, fps REAL, width INT, height INT, status TEXT)
shots(id INTEGER PK, file_id INT, t_start REAL, t_end REAL, thumb TEXT,
      size_tag TEXT, motion TEXT, motion_score REAL, orientation TEXT, emb_row INT)
```
`emb.npy` row `emb_row` holds the shot's L2-normalised embedding (mean of its frames).

## API contract (FROZEN once UI work starts)
```
POST /api/index        {"path": "C:/.../footage"}            -> {"started": true}
GET  /api/status                                             -> {"running": bool, "done": int, "total": int, "shots": int, "current": str}
POST /api/search       {"query": str, "k": 24, "diversity": 0.3,
                        "filters": {"size": [..], "motion": [..], "orientation": str|null}}
  -> {"clusters": [{"label": str, "shots": [Shot, ...]}],   // shots[0] = best in the cluster
      "missing": ["no close-up shots"], "took_ms": int}
GET  /api/similar/{shot_id}?k=12                             -> {"shots": [Shot]}
POST /api/plan         {"script": str, "wpm": 150}
  -> {"beats": [{"i": int, "text": str, "dur": float, "chosen": [Shot], "alts": [Shot]}]}
POST /api/export       {"beats": [...same shape, chosen edited...], "format": "xml"|"edl"} -> file
GET  /media/thumb/{shot_id}      jpg
GET  /media/video/{file_id}      mp4 with Range support

Shot = {"id", "file_id", "file", "t_start", "t_end", "score", "size", "motion", "orientation", "thumb"}
```

## Algorithms
**Segmenting (per file):** sample a frame every 1 s → embed all samples in one batch. Start a new shot when cosine(prev, cur) < `CUT_SIM`, or when the window reaches `WINDOW_S` (4 s). Shot embedding = normalised mean. Thumbnail = middle sample.

**Tags:**
- **Size:** zero-shot. Compare the shot embedding to prompts {"a wide establishing shot of a scene", "a medium shot", "a close-up shot", "an extreme close-up detail shot", "an aerial drone shot"} and take the argmax.
- **Motion:** mean absolute grayscale difference between consecutive 64×36 samples → still (<4) / moderate (<12) / action.
- **Orientation:** from width/height.

**Search:**
1. q = text embedding; scores = E @ q.
2. Filter by tags.
3. Gate: keep scores ≥ max(MIN_SCORE, best − GATE_DELTA).
4. Near-duplicate collapse: same file and sim > 0.93 → keep the best.
5. MMR: pick k with `(1−λ)·rel − λ·max_sim_to_selected`.
6. Cluster the picked shots (Agglomerative, cosine, distance_threshold 0.35).
7. Label each cluster: top zero-shot concept from a ~100-word B-roll vocabulary.
8. Missing: any size tag absent from the picked set.

**Planner:**
1. Split the script on `. ! ? । \n`.
2. dur = max(2, words / (wpm/60)).
3. Per beat: search(sentence, k=8, diversity=0.4).
4. Greedy over beats: pick the best shot not already used in the plan. Beats > 6 s get 2 shots, preferring a different size tag.
5. alts = the remaining candidates.

## Performance design (system-design concepts → speed)

**Core principle: heavy work happens at index time; the query path only does lookups and small maths.** TRUE and CUTS are cheap at query time because OCR, optical flow and zero-shot tags are precomputed per shot.

| Concept | Where we apply it | Speed effect |
|---|---|---|
| Separate write path vs read path (CQRS-style) | Indexer worker processes write; API process only reads | Search never waits on indexing |
| Async job queue + idempotent jobs | SQLite `jobs` keyed `(file_hash, stage, model_ver)`; priority tiers (visual → cut/provenance → OCR) | UI stays responsive; crash → resume; no duplicate work |
| Funnel / two-stage retrieval | Dense top-500 → tag mask → gate → MMR on ≤ 100 → cluster ≤ 24; planner DP on top-8 per beat | Bounded cost: DP is O(beats × 8²) |
| Cheap gate before expensive work | Text-presence check (edge density) before OCR; only every N-th frame for flow | OCR runs on ~15% of keyframes |
| Batching | Embed 16–32 frames per forward pass; encode all beats of a script in one batch | 3–5× throughput on CPU |
| Hot data in memory | Normalised float32 matrix (90k × 512 ≈ 180 MB) in RAM; tags as numpy arrays for boolean masks | One matmul ≈ 5 ms |
| Caching | LRU for query text embeddings (biggest per-query cost); LRU for search results keyed (query, filters, λ); precomputed prompt/vocab/gazetteer embeddings; thumbnails with `Cache-Control: immutable` | Repeat queries ≈ 1 ms; UI scroll stays fast |
| Warm model serving | Load models once at startup (singleton) + warm-up call; `torch.set_num_threads(cores)`; optional ONNX int8 text encoder | No cold start per request |
| Snapshot reads (consistency) | Indexer appends; the API reloads an immutable snapshot (matrix + id map) on a version bump, then swaps atomically | No half-written reads, no locks on the query path |
| SQLite WAL + indexes | WAL mode; indexes on `shots(file_id)`, `shots(size_tag, motion)`, `provenance(shot_id)` | Readers don't block the writer |
| Media delivery (CDN idea, local) | HTTP Range (206) video streaming; 320 px JPEG thumbs; `loading="lazy"` | Instant preview seeking |
| Streaming responses | Plan endpoint streams beats via SSE as they're solved (stretch) | First result appears immediately |
| Backpressure / resource limits | Workers = cores − 2; bounded batch sizes; RAM guard halves the batch on pressure | 6 GB laptop doesn't swap |
| Graceful degradation | OCR/flow missing → verdict "unverifiable", DP uses relevance only; no memory → cold-start ranking | Features fail soft, never crash search |
| Observability | Every response returns `timings` per stage; `/api/status` shows the queue | Find the slow stage immediately |

### Latency budget (100 h library, CPU)
| Stage | Budget |
|---|---|
| Query text encode | 30–50 ms (0 when cached) |
| Matmul 90k × 512 + mask | ~5–10 ms |
| Gate + dedupe + MMR (≤ 100) | ~5 ms |
| Clustering + labels | ~10 ms |
| SQLite fetch of 24 shots | ~5 ms |
| **Search total** | **< 100 ms** |
| Plan, 10-beat script (batch encode + candidates + O(1) truth lookups + DP + memory kNN) | **< 400 ms** |

## Pillar additions

### Extra tables
```sql
provenance(shot_id PK, shot_date TEXT, date_source TEXT /* meta|mtime|unknown */,
           gps_lat REAL, gps_lon REAL, ocr_text TEXT, ocr_lang TEXT,
           place_guess TEXT, place_conf REAL, weather TEXT, season TEXT, daypart TEXT, source TEXT)
cut_features(shot_id PK, head_flow_dx REAL, head_flow_dy REAL, tail_flow_dx REAL, tail_flow_dy REAL,
             head_luma REAL, tail_luma REAL, head_warmth REAL, tail_warmth REAL,
             sal_x REAL, sal_y REAL, peak_t REAL)
memory_pairs(id PK, project TEXT, text TEXT, shot_id INT, chosen INT /* 1 pos, 0 neg */, created_at TEXT)
-- memory text embeddings: data/mem_emb.npy (row = memory_pairs.id order)
```

### Extra API (append-only; the base contract stays frozen)
```
POST /api/plan  body adds {"use_truth": true, "use_cuts": true, "use_memory": true}
  beat.chosen[] items add {"verdict": "ok|warn|bad", "evidence": [str], "label": "FILE · 2019"|null,
                           "mem_hits": int, "cut_cost_prev": float}
  response adds {"rejected": [{"beat": i, "shot": Shot, "evidence": [...]}], "sequence_cost": float}
GET  /api/shots/{id}/provenance           -> provenance card
POST /api/memory/import  {"xml_path": str, "script": str, "project": str} -> {"pairs": int}
GET  /api/memory/style                    -> {"size_mix": {...}, "avg_dur": float, "opener": "aerial"}
POST /api/feedback       {"beat_text": str, "chosen": id, "rejected": [ids]}   // swaps train YOURS
POST /api/audit          {"xml_path": str, "script": str} -> contradiction report (stretch)
```

### TRUE rules (v1)
| Claim | Evidence source | ❌ contradicts if | ⚠️ if |
|---|---|---|---|
| Place (gazetteer match, e.g. Mumbai) | OCR city/landmark text, GPS, zero-shot place | OCR/GPS names a *different* gazetteer city | No place evidence |
| Time "today/this week/this year/2026" | shot_date | date older than the claim window | date unknown |
| Weather (rain/flood/sunny/fog) | zero-shot weather (conf > 0.6) | strong opposite weather | weak signal |
| Person named | face cluster name/status | different person, or consent expired | — |

### CUTS transition cost (v1)
```
cost(a→b) = 2.0·jump(a,b) + 1.0·flip(a.tail_flow, b.head_flow) + 0.8·|a.tail_luma − b.head_luma|
          + 0.5·|a.tail_warmth − b.head_warmth| + 0.6·[a.size == b.size] − 0.4·[size progresses wide→close]
jump(a,b) = same file ∧ |Δt| < 10 s ∧ cos(emb_a, emb_b) > 0.9
```

**Export:**
- **xmeml v4:** one sequence, one video track; clipitems back-to-back; `pathurl` = `file://localhost/C:/...`; timebase = 25.
- **EDL:** CMX3600, reel = AX, with `* FROM CLIP NAME:` comments.
