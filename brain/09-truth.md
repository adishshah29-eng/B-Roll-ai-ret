# TRUE pillar: as built (P5)

Code: `app/truth.py` (claims, evidence, verdicts) · `app/indexer/ocr.py` (signboard OCR) · `app/planner.py` (integration) ·
`resources/gazetteer.json` (~110 places, Hindi names, landmarks, region→country hierarchy) · `eval/make_traps.py` (fixtures).
Tests: `tests/test_truth.py` (32 pure-logic tests), `tests/test_plan_truth.py` (6 integration tests on the real library).

## How a verdict is made
```
narration line ──extract_claims──▶ places (+ inherited script context) · time (today / 1906) · weather
shot facts ─────▶ place evidence: GPS (≤60 km) · signboard OCR · stock title/tags      ← strongest first
                  date + date_source (meta/recorded = reliable · upload = upper bound · mtime/unknown = ignored)
                  weather tag + confidence (zero-shot)
verdict ─▶ ok | unverified | warn | bad  + per-check evidence strings + optional label
```
| Check | ok | warn | bad |
|---|---|---|---|
| Place | evidence inside a claimed place (Mumbai evidence confirms "Mumbai" and "Maharashtra") | — | hard evidence names a place unrelated to **every** claimed place |
| Time "today…" | recorded ≤ 45 days ago | recorded older → label `FILE · year` (kept!) | — |
| Time "in 1906" | recorded year matches | — | recorded year differs, or uploaded before that year |
| Weather | tag equals claim (≥0.60) | opposite tag ≥ 0.80 | opposite tag ≥ **0.97** |
| Stock-as-news | — | line itself names a place; clip is stock; no place evidence → label `STOCK · not event footage` | — |

`bad` ⇒ the shot is **excluded** from the plan and listed in the "rejected" drawer with its evidence ("Use anyway" overrides).
Score adjustment (relevance units, cosines are ~0.2–0.35): place/year ok **+0.03**, other ok +0.01 (bonus capped at +0.05), each warn −0.01.

## Decisions made while building (all measured)
- **OCR engine:** RapidOCR 0.8 s/frame vs EasyOCR 4–7 s on this CPU (D19). Reads English; drops spaces ("DelhiMetro") so matching also tests a space-stripped text for aliases ≥ 5 letters.
- **Weather is a soft hint.** First version had no "indoor" class, so office/food shots were tagged "sunny" (854 of 1,881!). Added `indoor`; re-checked with contact sheets: high-confidence sunny/rain tags are ~85–90 % precise at 0.90, so a weather mismatch may only *exclude* a shot at 0.97.
- **Place context carries over** within a script: "Heavy rain lashed Mumbai…" → later lines are still Mumbai. Without it a Bangkok metro, an Indonesian newsreel and a Kerala monsoon were chosen for a Mumbai story. Time and weather are line-level and are NOT inherited. Inherited places never trigger the stock label.
- **Multi-city narration** ("Mumbai to Delhi"): a shot is only `bad` if it clashes with *all* mentioned places.
- **Unreliable dates are ignored** (`mtime`, `unknown`): never a label, never a contradiction. Commons gives real recording dates; Pixabay has none.

## Real findings from the library (use in the demo)
- *Aug 29 2017 Mumbai Floods* (Commons): chosen for Mumbai flood lines; under "today" it gets `FILE · 2017`.
- A Pixabay clip titled "street food" has a shop sign reading **PARIS** (found by OCR): rejected for "street food in Mumbai".
- Rejected with evidence for a Mumbai script: Bangkok metro, Delhi signboard clip, Indonesian newsreel (Dutch spelling "Indonesië"), Kolkata COVID-campaign clip, Osaka / Hong Kong skylines, Kerala monsoon clip.

## Trap fixtures (`python -m eval.make_traps` → `footage/traps/`)
Real Pixabay footage + planted signboard + creation date patched into the MP4 `mvhd` atom (read back as `date_source=meta`).
| Clip | Planted | Expected |
|---|---|---|
| trap_delhi_sign_rain | sign DELHI METRO, 2026-09-28 | Mumbai line → place **bad** |
| trap_mumbai_sign_rain | sign MUMBAI LOCAL, 2026-09-30 | "rain in Mumbai today" → place ok, time ok, weather ok |
| trap_2019_flood | no sign, 2019-08-10 | "floods today" → warn `FILE · 2019`; "In 2019…" → ok |
| trap_sunny_mumbai | sign WELCOME TO MUMBAI, sunny | "heavy rain in Mumbai" → place ok, weather warn/bad |
| trap_kolkata_sign_traffic | sign KOLKATA HOWRAH BRIDGE | any Mumbai/Delhi line → place bad |
They are synthetic fixtures (OpenCV can only write MPEG-4 part 2 here, so they play in the app's thumbnails but not in Chrome's `<video>`); **replace or add real phone clips** for the final demo.

## Known limits
- Place evidence comes from titles/tags/OCR/GPS; a clip with none stays `unverified`. Plain generic stock ("traffic") can't be proven or disproven.
- OCR is English/Latin only; Hindi signboards are not read yet (Hindi *claims* work). OCR reads one frame per shot.
- Gazetteer is hand-made (~110 places); unknown towns are invisible to TRUE.
- GPS is read only from QuickTime `©xyz` atoms; phone clips with other GPS formats won't carry it.
- Stock clips (Tier S) are not OCR'd until hydrated; their evidence is title/tags only.
- Weather zero-shot is noisy; it never excludes below 0.97.
