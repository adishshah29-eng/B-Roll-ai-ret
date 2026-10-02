# Design: B-Roll Search & Retrieval (hackathon build)

Companion to [FINAL_PROBLEM_STATEMENT.md](../../FINAL_PROBLEM_STATEMENT.md).
Status: **v1 hypothesis.** It holds for 1 user, ≤ 100 h of footage, and CPU-only laptops.

---

## 1. Problem & scope

### Functional requirements (MVP)
1. **Add a library:** point at one or more folders or drives, and index all video files.
2. **Natural-language search:** English and Hindi queries; returns **shots with timestamps**, not files.
3. **Relevance-ranked variety:** relevance threshold → diversified with MMR → grouped into clusters, plus "Find similar" on any shot.
4. **Filters:** shot size, camera motion, action/still, orientation, date, person, "not used before".
5. **Script → B-roll:** paste a script (or a voiceover file), get a B-roll plan with shots per beat, and edit it.
6. **Export** the plan to editing software (FCP7 XML for Premiere, FCPXML for Resolve/FCP, EDL as fallback).
7. **Preview** any shot in the UI.

### Non-functional requirements
| Requirement | Target |
|---|---|
| Runs fully offline | No internet needed after models are downloaded |
| Hardware | **CPU-only 8–16 GB laptops must work**; use a GPU if one is present |
| Search latency | < 500 ms p95 at 100 h of footage |
| Time to first search | Library searchable **while** indexing continues (progressive) |
| Basic visual index on CPU | ≤ ~2 h for 100 h of footage, or ~10 min for a 10 h demo set |
| Crash safety | Indexing resumes where it stopped; never re-does finished work |
| Privacy | Footage never leaves the machine (LAN demo mode is opt-in) |

### Out of scope (v1)
- Multi-user editing, permissions, accounts.
- Cloud sync and remote access beyond the LAN.
- Generating new footage with AI.
- Full VLM captions for every shot on CPU (too slow; see §2). Captions are **lazy**.
- 1,000+ hour archives (see §8).

### Assumptions
- Footage is mostly MP4/MOV (H.264/H.265); ProRes/MXF is supported but slower to preview.
- B-roll files are often **single continuous takes** with little speech.
- The demo uses a curated **5–10 h** library on 2–3 laptops on the same Wi-Fi.

---

## 2. Scale estimates (100 h library, 8-core CPU, no GPU)

| Quantity | Calculation | Result |
|---|---|---|
| Shots | 100 h × 3,600 s ÷ ~4 s per shot | **~90k shots** |
| Full decode for shot detection | 100 h × 30 fps = 10.8 M frames ÷ ~400 fps | **~7.5 h. Too slow** |
| **Keyframe-only decode** (`-skip_frame nokey`) | ~1 I-frame/s → 360k frames ÷ ~300 fps | **~20 min** ✅ |
| Visual embeddings (SigLIP 2 base, ONNX int8) | 90k ÷ ~30 img/s | **~50 min** |
| Shot-size / motion tags | Linear probe on the embedding + I-frame difference | **~free** |
| Speech (Whisper small int8, after VAD) | ~20% of audio has speech → 20 h ÷ ~6× real time | **~3.5 h** (low priority) |
| OCR | Only on keyframes where a text detector fires (~15%) | **~30–45 min** |
| Faces (SCRFD + ArcFace) | 90k keyframes ÷ ~50/s | **~30 min** |
| VLM caption for every shot (Florence-2 on CPU) | 90k × ~1.5 s | **~37 h. Not feasible → lazy captions only** |
| Vector memory | 90k × 768 dims × 2 B (fp16) | **~140 MB, fits in RAM** |
| Thumbnails | 90k × ~10 KB (320 px WebP) | **~0.9 GB** |
| Search cost | Brute-force dot product over 90k × 768 | **~10–20 ms** |

**What the numbers force:**
1. **Indexing is the hard problem; search is easy.** Design around a **persistent, prioritised, resumable job pipeline**.
2. **Decode keyframes only.** Because B-roll is mostly single takes, a slightly imprecise cut boundary is fine. Long takes get split into **fixed 4–8 s windows**.
3. **Index in tiers.** Tier 0 (visual) makes everything searchable fast; speech, OCR and faces fill in afterwards; captions are generated only on demand.
4. **No vector DB server needed.** Exact search with in-memory numpy/FAISS is fast and simple.
5. **One machine.** No queue broker, no sharding.

---

## 3. API (local HTTP, FastAPI)

All endpoints are served on `http://<host>:8000`. In LAN demo mode, other laptops open the same URL.

```http
POST /api/libraries            {"path": "D:/Footage"}            -> {"library_id": "lib_1"}
GET  /api/index/status                                           -> {"files": 812, "tiers": {"t0": 0.94, "t1": 0.40, "t2": 0.10}, "eta_s": 1830}

POST /api/search
{
  "query": "बारिश में सड़क पर ट्रैफिक",
  "filters": {"shot_size": ["wide","close"], "motion": "action", "orientation": "16:9",
              "unused_only": true, "people": ["p_12"], "date_from": "2025-01-01"},
  "k": 40,
  "diversity": 0.3            // MMR λ trade-off: 0 = pure relevance, 1 = max variety
}
-> {
  "clusters": [
    {"label": "rain on cars", "best": Shot, "more": [Shot, ...]},
    ...
  ],
  "missing_variety": ["no close-up shots found"],
  "took_ms": 84
}

Shot = {"shot_id": "s_8812", "file": "C0042.MP4", "t_start": 12.4, "t_end": 18.0,
        "thumb": "/media/thumb/s_8812", "score": 0.71,
        "tags": {"size": "wide", "motion": "pan", "action": 0.2}, "used_count": 0}

GET  /api/shots/{id}/similar?k=20                                -> {"shots": [Shot, ...]}

POST /api/script/plan          {"script": "...", "voiceover_path": null, "fps": 25}
-> {"plan_id": "pl_3", "beats": [{"beat_id": 1, "text": "...", "t_start": 0, "t_end": 6.2,
     "queries": ["busy indian street morning"], "chosen": [Shot], "alternatives": [Shot, ...]}]}

PATCH /api/script/plan/{id}    {"beat_id": 1, "chosen": ["s_77"]}   // user swaps a clip
POST  /api/export              {"plan_id": "pl_3", "format": "fcp7xml|fcpxml|edl"} -> file download
POST  /api/usage               {"shot_ids": ["s_77"], "project": "Ep12"}   // marks shots as used

GET  /media/thumb/{shot_id}     WebP thumbnail
GET  /media/stream/{shot_id}    Byte-range video (original if browser-playable, else lazily made proxy)
```

**Idempotency:** `POST /libraries` with a path that is already registered returns the existing id. Index jobs are keyed by `(file_hash, stage, model_version)`, so re-adding a folder never re-does work.

---

## 4. High-level design

```
                ┌────────────────────── Browser UI (React) ──────────────────────┐
                │  Search · Clusters · Find similar · Script planner · Export    │
                └───────────────▲───────────────────────────────▲────────────────┘
                                │ HTTP (localhost or LAN)       │ video byte-range
                ┌───────────────┴───────────────────────────────┴────────────────┐
                │                    FastAPI app (single process)                 │
                │  Query service ─ Script planner ─ Exporter ─ Media server       │
                └──────┬──────────────────┬───────────────────────┬──────────────┘
                       │ read             │ read                  │ enqueue
            ┌──────────▼───────┐  ┌───────▼────────┐   ┌──────────▼──────────┐
            │ Vector index     │  │ SQLite         │   │ Job queue (SQLite)  │
            │ numpy/FAISS fp16 │  │ meta + FTS5    │   │ (file,stage,model)  │
            └──────────▲───────┘  └───────▲────────┘   └──────────┬──────────┘
                       │ write            │ write                 │ claim
                ┌──────┴──────────────────┴───────────────────────▼──────────┐
                │       Indexer worker pool (N = cores−2 processes)            │
                │ T0: probe → keyframes → segment → embed → size/motion tags  │
                │ T1: faces · OCR · VAD+ASR    T2 (lazy): VLM captions         │
                └──────────────────────────────▲───────────────────────────────┘
                                               │ reads
                                   Footage folders / drives (read-only)
```

| Component | Why it exists (ties to §1–§2) |
|---|---|
| **Indexer worker pool** | Indexing is the bottleneck (§2). Separate processes keep the UI responsive and use all cores. |
| **SQLite job queue** | Crash-safe, resumable and prioritised (T0 before T1) without running Redis or Kafka on a laptop. |
| **SQLite + FTS5** | Metadata, people, usage, plus **BM25 keyword search** over transcripts, OCR and captions, all in one file. |
| **In-memory vector index** | 140 MB fits in RAM; exact search takes ~15 ms (§2). |
| **Query service** | Hybrid retrieval → filters → MMR → clustering. This is where the "relevant variety" feature lives. |
| **Script planner** | Script/voiceover → beats → per-beat retrieval → global assignment with no repeats. |
| **Exporter** | Writes FCP7 XML / FCPXML / EDL, so the plan lands on the editor's timeline. |
| **Media server** | Thumbnails and byte-range preview; makes a proxy only when the codec won't play in a browser. |
| **Browser UI** | One UI for localhost **and** LAN demo laptops; no install on client machines. |

### 4a. Indexing pipeline (per file)
1. `probe`: ffprobe for duration, fps, resolution, rotation, creation date; partial content hash (size + first/last 1 MB).
2. `keyframes`: `ffmpeg -skip_frame nokey`, scaled to 384 px.
3. `segment`: cut where adjacent I-frames differ strongly (histogram + embedding distance); split long takes into 4–8 s windows. Each segment is a **shot**.
4. `embed`: SigLIP 2 (multilingual) image embedding of the shot's middle keyframe, plus a mean over 3 frames when time allows.
5. `tags`:
   - **shot size** = linear classifier on the SigLIP embedding (trained on MovieShots labels)
   - **camera motion** = global flow between neighbouring I-frames (static / pan / tilt / handheld / zoom)
   - **action** = local motion energy
   - **quality** = blur (Laplacian variance), exposure
6. **T1:**
   - `faces`: SCRFD detection → ArcFace embeddings → incremental clustering into people.
   - `ocr`: a text detector gates PaddleOCR.
   - `asr`: Silero VAD → faster-whisper (multilingual) on speech segments only → transcripts mapped to shots.
7. **T2 (lazy):** Florence-2 caption for shots that appear in results or get used. Captions feed the FTS index and cluster labels.

### 4b. Query path (`POST /search`)
1. **Encode the query** with the SigLIP 2 text tower (handles Hindi and English directly). Romanised Hinglish is transliterated first (indic-transliteration) and both forms are queried.
2. **Retrieve candidates:**
   - **Dense:** top 500 shots by cosine similarity.
   - **Sparse:** FTS5 BM25 over transcripts, OCR and captions (top 200).
3. **Fuse the two lists** with Reciprocal Rank Fusion, then apply SQL filters.
4. **Relevance gate:** drop anything below a calibrated score (or below 0.8 × the best score).
5. **Remove near-duplicates:** collapse shots from the same file within ±10 s whose embeddings are more than 0.95 similar.
6. **Diversify with MMR:** `score = (1−λ)·rel − λ·max_sim(selected)`, with λ taken from the `diversity` slider.
7. **Cluster** the top k (agglomerative clustering on embeddings, cosine 0.25). Each cluster is labelled with its most frequent caption or OCR/ASR terms, falling back to a SigLIP zero-shot vocabulary.
8. **Missing variety:** report any shot-size or motion bucket that is absent among relevant results.

### 4c. Script → B-roll
1. **Beats:**
   - **Script:** split into sentences, merge sentences shorter than ~3 s of speech, estimate durations at ~150 wpm.
   - **Voiceover:** Whisper word timestamps.
2. **Queries per beat:**
   - A local small LLM (Qwen2.5-1.5B/3B GGUF via llama.cpp, about 30 s per script on CPU) turns each line into 1–3 visual queries.
   - **Fallback:** KeyBERT keyphrases, so it still works if the LLM is slow or missing.
3. **Candidates:** search each beat for the top 20 relevant, diversified shots.
4. **Global assignment:** a greedy pass over beats ordered by fewest candidates first. It picks the highest-relevance shot that hasn't been used yet in this plan (and isn't overused historically), and alternates shot size inside long beats (wide → close). Shots are trimmed to the beat's duration, centred on the action peak.
5. **Edit and export:** the user swaps clips (`PATCH`), then exports.

---

## 5. Data model (SQLite, one file per library)

```sql
files(id PK, path, content_hash UNIQUE, duration_s, fps, width, height, rotation,
      created_at, status /* online|offline|failed */, index_version)
shots(id PK, file_id FK, t_start, t_end, keyframe_path,
      size_tag, motion_tag, action_score, blur, exposure,
      orientation, used_count DEFAULT 0, caption NULL)
shot_text(shot_id FK, kind /* asr|ocr|caption */, lang, text)          -- + FTS5 virtual table
people(id PK, name NULL, department NULL, status /* active|left */, consent_expiry NULL)
face_instances(shot_id FK, person_id FK, bbox, embedding BLOB)
usage(shot_id FK, project, used_at)
jobs(id PK, file_id FK, stage, model_version, priority, status, attempts, last_error,
     UNIQUE(file_id, stage, model_version))
plans(id PK, script, created_at) ; plan_beats(plan_id, beat_idx, text, t_start, t_end, chosen_shot_ids JSON)
```

- **Vectors:** `embeddings_<model>.npy` (fp16), where row *i* ↔ `shot_idx[i]`. The file is memory-mapped at startup and appended as indexing proceeds.
- **Primary access patterns:** vector top-k → shot ids → one `SELECT … WHERE id IN (…)` with filters. Indexes on `shots(file_id)`, `shots(size_tag, motion_tag)` and `usage(shot_id)`.
- **IDs:** autoincrement integers (single writer). Files are identified by **content hash**, not path, so renames and drive-letter changes don't break the index.

---

## 6. Key decisions & trade-offs

| Decision | Solves | Worsens | Change it when |
|---|---|---|---|
| Keyframe-only decode + fixed windows | 20× faster CPU indexing | Cut boundaries can be off by up to one GOP (~1 s) | Edited/multi-cut footage dominates → refine boundaries with TransNet V2 on GPU |
| Tiered + lazy VLM captions | Library searchable in < 2 h on CPU | Cluster labels are weaker until captions exist | A GPU is present → caption everything in T1 |
| SigLIP 2 (multilingual) as the main retriever | One model handles Hindi and English queries | Weaker on fine actions/temporal events than video models | Queries are action-heavy → add an InternVideo2 or X-CLIP re-ranker on the top 50 |
| SQLite (+FTS5) for meta, queue and BM25 | Zero-ops, one file, crash-safe, portable | Single writer; no concurrent multi-user writes | Team or shared-NAS mode → Postgres + pgvector |
| In-memory brute-force vectors | Simplest exact search, ~15 ms | RAM grows linearly; ~1.5 GB at 1M shots | > ~500k shots → FAISS IVF/HNSW on disk |
| Local small LLM with KeyBERT fallback | Offline script understanding | Lower query quality than a large cloud LLM | User opts in to a cloud LLM; keep the same interface |
| Linear probe for shot size | Practically free on top of the embeddings | ~80–85% accuracy, below a dedicated model | Accuracy target missed → fine-tune a small CNN on MovieShots |
| Web UI served by FastAPI | One codebase works on localhost **and** LAN demo laptops | Not embedded inside Premiere | Users want it in the editor → UXP panel calling the same API |
| MMR + clustering after a relevance gate | Variety without irrelevant shots | Extra latency (~20–50 ms); λ needs tuning | Users always max the slider → raise the default λ |

**Breaking point:** about **1,000 hours or concurrent users**. Then the single SQLite writer, RAM-resident vectors and single-machine indexing time all fail together (see §8).

---

## 7. Failure modes & degradation

| Failure | Detection | What the user sees / recovery |
|---|---|---|
| App or laptop crash during indexing | Jobs left `running` at startup | Reset to `pending`; finished stages are kept (one transaction per stage); resumes automatically |
| Corrupt or unreadable video | ffmpeg non-zero exit | Retried twice, then `failed` with the error shown in the UI; the rest of the library continues |
| Drive unplugged | Path missing on scan or preview | File marked `offline`; its shots stay searchable with an "offline" badge; preview disabled; auto-reconnects via content hash when the drive returns (any drive letter) |
| File renamed or moved | Same content hash at a new path | Path updated; no re-index |
| Out of memory / CPU starved | Worker RSS above limit | Worker count = cores−2, bounded batch sizes; on an OOM kill, retry with batch size halved; UI process stays separate and responsive |
| ASR/OCR/face model missing or too slow | Stage error or timeout | Stage skipped; search still works on visual + other signals; the UI shows which signals are available |
| Local LLM unavailable | Load failure or timeout > 60 s | Fall back to KeyBERT keyphrase queries |
| Embedding model upgraded | `model_version` mismatch | New jobs keyed by version; old vectors serve queries until the new ones are complete, then swap |
| Codec won't play in browser (ProRes/MXF) | Media server probe | Make a 540p H.264 proxy on first request (cached); a spinner shows meanwhile |
| LAN demo network fails | Client can't reach the host | Every laptop can run standalone with its own library; LAN is only a convenience |

**Single points of failure:** the one machine and its SQLite file. Mitigation: WAL mode, plus copying the index file before upgrades. Footage is never modified, since it is opened read-only.

---

## 8. Scale evolution

| Scale | Bottleneck | Change |
|---|---|---|
| **≤ 100 h, 1 user (v1)** | CPU indexing time | This design |
| ~1,000 h / small team | Indexing time (~20 h on CPU), RAM for vectors, single writer | GPU indexing node; FAISS HNSW on disk; Postgres + pgvector; shared server with browser clients; **LAN workers pull jobs** from the shared queue (stateless jobs make this simple) |
| 10,000 h+ (broadcast archive) | Storage, indexing throughput, multi-tenant search | Object storage for proxies/thumbs; distributed workers; sharded vector index; dedicated search service (OpenSearch hybrid) |

**Signal to evolve:** index ETA > 1 night, p95 search > 500 ms, or a second simultaneous editor.

---

## 9. Hackathon build plan

**Must-have (demo-critical):** T0 indexing · search with Hindi + English · MMR + clusters · Find similar · shot-size/motion filters · script → plan → FCP7 XML export to Premiere · preview.
**Should-have:** ASR + OCR in hybrid search · faces/people filter · usage tracking · missing-variety alert.
**Stretch:** LAN worker laptops sharing indexing · voiceover input · Premiere UXP panel · consent/expiry flags.

**Demo setup:** the host laptop indexes a curated 5–10 h library beforehand (pre-built index included as a backup). Judges' or teammates' laptops open `http://host:8000` over the LAN. Live flow: Hindi query → variety clusters → Find similar → paste script → plan → export → open in Premiere.

---

## 10. Open questions
- Calibrating the relevance threshold per query; needs a small labelled set.
- Accuracy of shot-size classification on Indian, creator-style footage (vs. film-style MovieShots).
- Quality of Hinglish (romanised) queries through transliteration; needs a test.
- Whether to bundle model weights (~1–2 GB) in the installer or download them on first run.

---
### Validation
- [x] Every §6 row has a non-empty "Worsens" column and a breaking point is named.
- [x] §2 estimates have units and assumptions.
- [x] §7 gives a degradation path for every critical dependency.
- [x] Every §4 component ties to §1–§2.
- [x] Coverage sweep: media (§4, media server) · IDs (§5) · search (§4b) · logs/SLOs (deferred: local log file + `/index/status`; no SLO tooling needed for a single user).
