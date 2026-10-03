# Landing page + palette reset: implementation plan (2026-10-03)

Status: PLAN ONLY. The only things built so far are the hero frames (below). Nothing in `app/static` UI code has been changed.

## 0. What is already done
`python -m eval.make_hero_frames` cut `app/static/media/hero.mp4` (1920x1080, 10 s, 24 fps) into:
| Asset | What | Size |
|---|---|---|
| `media/hero/d/f001..f150.webp` | desktop, 1600x900, 15 fps, q72 | 3.6 MB total (about 24 KB each) |
| `media/hero/m/f001..f150.webp` | mobile, 800x450, q66 | 1.6 MB total (about 10 KB each) |
| `media/hero/poster.jpg` | frame 1, 1600 wide, first paint and reduced-motion | about 50 KB |
| `media/hero/manifest.json` | frame count, fps, sizes (the page reads it) | tiny |
The source has a small fixed generator mark bottom-right. It was removed with ffmpeg `delogo` (checked on frames 1, 75, 150: clean on the dark starfield). Audio dropped.

## 1. Problem 1: the colours look like AI slop. Why, and the fix
Why: purple-to-violet gradient buttons, lavender washes, pastel chips and a purple "grad" word in the headline are the default look of generated SaaS pages. They also have nothing to do with a film tool, and white text on the #B738FF half of the gradient fails 4.5:1.

Fix: derive the colour from the product's own footage. Sampled from the hero video (k-means over 25 frames): near-black navy #06111C (46 % of pixels), deep blue #11263D, steel #487697, ice #AFDAEC, sand #D2C4AA, one saturated red frame. No purple anywhere. Rules: one accent, no gradients on UI (gradient only inside the video glow), flat solid buttons, colour carries meaning.

| Token | Hex | Role | Contrast |
|---|---|---|---|
| `--night` | #06111C | landing hero, dark frames (player, timeline) | |
| `--night-2` | #0B1A28 | dark panels | |
| `--ice` | #E6F1F6 | text on night, hero button fill | 16.5:1 on night |
| `--ice-muted` | #9DB4C4 | secondary text on night | 8.8:1 |
| `--steel` | #487697 | decorative lines, glow only (not text) | 3.9:1 |
| `--link-night` | #8FC3E0 | links on night | 10.0:1 |
| `--paper` | #F4F1EA | page background below the hero and in the app | |
| `--paper-2` | #EAE6DC | cards, inputs, hover | |
| `--line` | #D9D4C7 | hairlines | |
| `--ink` | #0B1520 | headings, body, primary button fill | 16.3:1 on paper |
| `--ink-2` | #4A5663 | secondary text | 6.6:1 |
| `--faint` | #5E6873 | meta text | 5.0:1 (4.5 on paper-2) |
| `--link` | #1F5F8B | links on paper | 6.1:1 |
| `--rec` | #C63A33 | the one accent: record dot, playhead, "True" mark, small emphasis | white on it 5.2:1, on paper 4.6:1 |
| `--ok` / `--warn` | #2A7553 / #8A5A12 | verdict text | 4.9 / 5.2 on paper |

Buttons: primary = solid `--ink` with `--paper` text on light, solid `--ice` with `--night` text on the hero. Ghost = transparent with 1 px border. Chips selected = ink fill. Verdict pills keep green / amber / red but flat.
Typography: headings Instrument Serif (display, tight, large) so it stops looking like every Inter template; body Inter; mono for timecodes = JetBrains Mono. (Inter and JetBrains Mono appear in the ui-ux-pro-max pairing database; Instrument Serif is my pick, not from it. Fallbacks if you dislike it: Fraunces, Playfair Display.) Self-host the three font files in `static/fonts` for offline use.
The same tokens replace the purple ones across the app (`style.css`), so landing and tool match.

## 2. Problem 2: a landing page first
Routing: `/` = landing (`landing.html`), `/app` = the tool (current `index.html` renamed `app.html`, same JS), `/static/*` unchanged. Every "Open Epoch" / "Try it" button goes to `/app`; the app's logo links back to `/`. `main.py` change is two routes plus a redirect for `/#editor/<id>` style links (they become `/app#editor/<id>`).

### Sections (all copy must be true; no invented customer numbers, logos or testimonials)
1. **Nav** over the hero: wordmark, anchors (How it works, True/Cuts/Yours, Licences), "Open Epoch" button. Turns solid paper after the hero.
2. **Hero (pinned, scroll-scrubbed, see section 3).** Headline in 3 beats over the film strip.
3. **The problem** (paper): one sentence and three short lines: keyword search guesses, stock sites mislead, licences are unclear.
4. **How it works**: 3 steps (Listens / Plans and checks / Cuts on the word), each with a real screenshot of the editor from this app, revealed on scroll.
5. **True, Cuts, Yours**: three pillars with a small real example each (a Gemini picture-check note, a cut-cost chip, a Memory line). Real UI crops, not illustrations.
6. **Licence on every clip**: a mock of the credits sheet export (real format from `/api/export`).
7. **Product shot**: the editor in the dark device frame (player + timeline), autoplaying a short muted capture of the preview.
8. **FAQ** (5 questions: what it costs to run, does it need internet, which sources, which licences, is my video uploaded anywhere. The honest answers: Gemini receives the transcript text and thumbnails, the video stays local).
9. **Final CTA** + footer (licence notes, sources).

## 3. Hero engine (GSAP scroll scrub on a canvas)
Why frames + canvas, not `<video>` + `currentTime`: seeking a video on scroll stutters (keyframe distance); a preloaded image sequence on a canvas scrubs smoothly in both directions.

- Markup: `<section class="hero"><canvas id="heroCanvas" aria-hidden="true"></canvas><div class="hero-copy">...beats...</div></section>`; poster `<img>` underneath for first paint.
- Libraries: `gsap` + `ScrollTrigger`, self-hosted in `static/vendor/` (about 115 KB min). GSAP and its plugins are free to use under GSAP's current licence; check the licence text when vendoring.
- Timeline (skill preset "Scroll reveal, complex, pin + scrub"; pin at most this one section):
  ```
  const state = { frame: 0 };
  gsap.to(state, { frame: FRAMES - 1, snap: "frame", ease: "none",
    scrollTrigger: { trigger: ".hero", start: "top top", end: "+=420%", scrub: 0.6, pin: true, anticipatePin: 1 },
    onUpdate: () => draw(state.frame) });
  ```
  Copy beats are a second timeline on the same ScrollTrigger (opacity/translate only, no layout properties).
- Frame to story mapping (from the contact sheet; seconds x 15 = frame):
  | Scroll | Frames | In the video | Copy beat |
  |---|---|---|---|
  | 0-18 % | 1-27 | film strip enters | H1: "B-roll that fits what you say." + sub + two buttons |
  | 22-45 % | 15-50 | red frame passes | "True": every clip is checked against the sentence |
  | 50-72 % | 60-90 | strip loops through space | "Cuts": starts on the spoken word, at the best moment |
  | 78-100 % | 105-150 | warm gold frames, tunnel | "Yours": it learns how you cut. CTA appears |
- Loader: show poster, preload frames 1-12 first, then the rest in priority order (every 4th, then fill), `img.decode()`; keep `HTMLImageElement`s (or `ImageBitmap`) in an array; while a frame is missing draw the nearest loaded one. Small progress hairline under the nav while loading. Pick set `m` when `matchMedia("(max-width: 760px)")` or `navigator.connection.saveData`, else `d`.
- Drawing: cover-fit, devicePixelRatio capped at 2, redraw only when the integer frame changes (`requestAnimationFrame`), resize handler recomputes canvas size and calls `ScrollTrigger.refresh()` after fonts load.
- Legibility: 55 % `--night` gradient scrim behind the copy blocks, text `--ice` (16:1).
- Fallbacks: `prefers-reduced-motion` = no pin, no scrub, poster image only, copy stacked as normal sections; frames fail to load = autoplay muted loop of `hero.mp4`; JS disabled = poster + static copy.
- Pin hygiene (from the skill): deterministic section height, `ScrollTrigger.refresh()` after load, do not pin anything else, native scroll speed (no scroll hijacking), keyboard and anchor links keep working.

## 4. Budgets and acceptance criteria
- First paint: poster <= 60 KB + CSS + critical JS under 40 KB before GSAP; LCP < 2.5 s on a mid laptop on localhost, CLS 0.
- Total hero: <= 3.7 MB desktop / <= 1.6 MB mobile, streamed in the background; hero usable before 20 % has loaded.
- Scrub holds 60 fps on the 1600 px set on this CPU-only machine (check with the browser performance panel); if not, drop to every other frame (75) or 1280 px.
- Contrast >= 4.5:1 for all text over solid colour and over the scrim; visible focus; keyboard reaches every control; tested at 375, 768, 1024, 1440; no horizontal scroll.
- Lighthouse (the SEO/performance check) >= 90 performance, 100 accessibility on the landing page.

## 5. Phases (each ends runnable)
| # | Work | Done when |
|---|---|---|
| L0 | Frames + manifest (DONE) | `media/hero/*` exists, script reproducible |
| L1 | Palette + type reset: new tokens in `style.css`, fonts self-hosted, update `design-system/epoch/MASTER.md`, remove every purple value and gradient button | app has no purple, contrast table passes |
| L2 | Routing: `/` landing stub, `/app` tool, redirects, logo links | both pages load, deep links still open projects |
| L3 | Landing shell: nav, sections, content, paper/night styles (static, no motion) | readable, responsive, all copy true |
| L4 | Hero engine: loader, canvas, GSAP pin/scrub, copy beats | smooth scrub both directions, 60 fps check |
| L5 | Section motion: reveals on scroll (one-shot, 200-300 ms, opacity/translate), product capture | no more than 1-2 animated things per view |
| L6 | Real assets: editor screenshots/crops and a short product capture taken from the running app (needs a finished project) | no placeholder images |
| L7 | A11y, reduced-motion, fallbacks, performance pass, checklist | acceptance criteria above |
| L8 | Docs (`13-ui.md`, README run instructions) | done |

## 6. Files
New: `app/static/landing.html`, `landing.css`, `landing.js`, `hero.js`, `vendor/gsap.min.js`, `vendor/ScrollTrigger.min.js`, `fonts/*`, `media/shots/*` (L6). Changed: `app/main.py` (routes), `app/static/index.html` to `app.html`, `style.css` (tokens), `design-system/epoch/MASTER.md`.

## 7. Risks and open questions
- **Hero is dark/blue, app was light/purple**: solved by sharing tokens (paper + ink + night) so the hero is a deliberate dark "cinema" opening into a paper page.
- **Weight of 150 frames**: mitigated by progressive loading and the mobile set; fallback loop video exists.
- **Pinning on touch devices** can feel sticky: shorter pin (`+=300%`) on mobile, test on a real phone.
- **Generator mark**: removed from the frames; keep an eye on the source video's own terms if you publish it.
- **Needs from you**: confirm the headline direction ("B-roll that fits what you say"), the font choice, and whether the product keeps the name Epoch and the placeholder logo. Real screenshots (L6) need one finished project to capture.
