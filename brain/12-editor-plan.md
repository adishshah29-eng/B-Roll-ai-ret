# Editor mode: implementation plan

**Goal:** upload a talking/A-roll video (+ optional script) → the tool transcribes it, decides *where* B-roll should go, fills each slot
with the existing engine (relevance + TRUE + CUTS + YOURS), shows an instant in-browser preview with B-roll overlaid, lets the user
swap / delete / nudge clips, and exports a finished **MP4** (original audio kept) plus the existing XML.

```
upload ──▶ normalise (ffmpeg → 720p H.264 work.mp4)
        ──▶ transcribe (faster-whisper small, word timestamps, Hindi+English)
        ──▶ face map (OpenCV Haar, every 0.5 s: where the speaker is big on screen)
        ──▶ slot picker: Gemini (if GEMINI_API_KEY) → JSON slots;  else rules (fallback, always available)
        ──▶ fill slots: planner.plan(beats=slots)  ← reuses TRUE / CUTS / YOURS unchanged
        ──▶ editor UI: A-roll player + B-roll overlay preview (two <video>, no render) · transcript strip · swap/delete/nudge
        ──▶ export: ffmpeg overlay render (MP4) · XML/EDL · captions (FILE/STOCK labels) · credits
```

## Components
| Module | Job | Notes |
|---|---|---|
| `app/editor/store.py` | project folder `data/projects/<id>/` (source, work.mp4, transcript.json, project.json), status | JSON on disk; status in memory |
| `app/editor/media.py` | ffmpeg path (imageio-ffmpeg), normalise, render | bundled static ffmpeg, no system install |
| `app/editor/transcribe.py` | faster-whisper `small`, int8 CPU, VAD, word timestamps | model loaded per job then freed (RAM) |
| `app/editor/faces.py` | Haar cascade face size per 0.5 s | "face_big" = face width > 22 % of frame |
| `app/editor/slots.py` | where B-roll goes: Gemini JSON → validate → else rules | rules: skip 0–3 s hook, cover 40–55 % of runtime, 1.5–5 s per slot, avoid sentence starts of direct address |
| `app/planner.py` | accept `beats=[Beat(text, dur)]` from slots | no other change |
| `app/editor/api.py` | upload, analyse (background), get, patch slots, render, download | mounted in main.py |
| `static/` Editor tab | upload + progress, player with overlay preview, slot strip, swap/delete/nudge, export | preview = switch to 2nd `<video>` inside a slot |

## Phases (each ends runnable)
| # | Build | Done when |
|---|---|---|
| E0 | deps: `faster-whisper`, `imageio-ffmpeg`; Whisper small cached | `ffmpeg -version` via imageio works; tiny transcription works |
| E1 | project store + upload + normalise + transcribe + faces (background job with status) | upload a 1–2 min clip → transcript with timestamps |
| E2 | slot picker (rules; Gemini optional) + fill via planner | slots with chosen B-roll + alternatives + why/verdicts |
| E3 | editor UI: preview overlay, transcript strip, swap/delete/nudge | full edit loop in the browser without rendering |
| E4 | render MP4 with ffmpeg (A-roll audio kept, B-roll scaled/cropped to frame) + XML/captions/credits | MP4 plays in the browser and VLC |
| E5 | polish: script alignment (if a script is uploaded), Gemini prompt, demo video, docs | demo rehearsed |

## Decisions
- Whisper, not OpenCV, reads speech; OpenCV only reads faces/frames.
- The LLM gets **text only** (timestamped transcript), never the video: cheaper, faster, more private. Fallback rules keep it fully offline.
- Preview never renders; render only on Export.
- Out of scope: multi-track, transitions, text overlays, effects, cloud hosting.

## Risks
CPU speed (Whisper ≈ real time, render ≈ 1–2× length → demo with 1–3 min videos) · ~6 GB RAM (free Whisper after use) · Gemini output validated and clamped, fallback on any error.
