# Domain libraries (built 2026-10-03)

**Why:** a real editor works in ONE domain with a curated set of clips. The old mixed pool (about 3,000 clips from every topic) is what put
off-topic clips into projects. A project now picks a library and everything it suggests comes from that library.

**What a library is:** a name + domain + a set of clips (`files.library_id` / `stock_items.library_id`; shots inherit it). `0` = not in a library.
The snapshot carries `lib` per shot, so scoping is a fast mask (`filters={"library": id}`) used by search, the script planner and the editor.

**Three ways to make one (Libraries tab, or POST /api/libraries)**
| Mode | What happens |
|---|---|
| Upload my own clips | `POST /api/libraries/{id}/upload` (multiple files) → saved in `data/libraries/<id>/` → indexed offline (shots, cut features, OCR) |
| Use a folder | points at a folder on this PC; clips are tagged and indexed in place |
| Build from Pixabay | domain → queries (curated `resources/domains/<domain>.yaml` if the domain contains that word, else Gemini, else a generic expansion) → best N clips picked round-robin across queries (landscape, 4–45 s, tag-matched) → thumbnails embedded → videos downloaded → full analysis. Needs internet once. |

**Using one**
- Editor: pick the library at upload. A library works fully offline; "Also fetch fresh clips from Pixabay" is optional and adds the fetched clips to that library.
  "All footage" keeps the old behaviour (live Pixabay always on).
- Search and Script tabs: library picker.

**Measured (2026-10-03, no-network checks + one small build)**
- Folder library of 29 clips: search inside it returned only its clips (all "own"), plan drew only from it.
- Auto-build, domain "travel in India", 8 clips: 5½ minutes end to end (search 10 s, download 8 s, analysis the rest) → 8 clips / 46 shots, scoped search works.
  Analysis was the slow part (CPU only). OCR is now skipped for stock clips (their Pixabay tags carry the place evidence); expect roughly
  20–30 s per clip, so a 60-clip library is a 20–30 minute background job. Not re-measured after the OCR change.

**Limits / not done**
- Auto-build uses Pixabay only (Commons / Archive are not used for building).
- The two test libraries ("Demo footage (own)", "Travel (build test)") are in your database: delete them in the Libraries tab if you don't want them.
- Library membership of Tier-S stock is by `stock_items.library_id`; a clip can belong to one library at a time.
