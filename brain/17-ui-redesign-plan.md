# UI redesign: implementation plan (2026-10-03)

Goal: production-ready, non-generic frontend in the light "SaaS" language defined in `design-system/epoch/MASTER.md`. No framework, no build step; element ids and JS behaviour stay.

## Findings from the reference (measured, not guessed)
Framer-built, Inter, white page, black announcement bar, floating pill nav (blurred, 999px), lavender radial wash behind the hero, section chips (icon + label) above 32px headings, grey body text, 24-32px rounded cards on #F9FAFB, device-frame mockups, purple gradient pill CTA, three-stat row, numbered steps list beside a mockup, two-column feature grid.

## Phases (each ends runnable)
| # | Work | Done when |
|---|---|---|
| U1 | Tokens + base: new `style.css` foundation (colour, type, radius, shadow, focus, reduced-motion), Inter via Google Fonts with system fallback, favicon, meta, skip link | every tab renders in the new theme without layout breakage |
| U2 | Shell: black status bar (old `#status`), floating pill nav with ARIA tabs, "New project" CTA | nav works on keyboard, collapses under 760px |
| U3 | Editor start (the product front door): hero, dropzone upload card, 3 steps row, recent projects as cards | upload by click and drag-and-drop |
| U4 | Editor workspace: dark player frame, dark timeline, light inspector card, chips, verdict pills, alt thumbnails | edit loop identical, readable contrast |
| U5 | Libraries, Search, Script, Memory restyled with the same components (cards, chips, pills, summaries) | all tabs consistent |
| U6 | States + a11y + responsive: empty/loading/error, aria-live messages, 44px targets on touch, 375/768/1024/1440 checks, contrast check | checklist below passes |
| U7 | Docs + cleanup | `13-ui.md` updated |

## Pre-delivery checklist (from the skill)
No emoji icons; cursor-pointer on clickables; hover transitions 150-300 ms; text contrast >= 4.5:1; visible focus; reduced motion respected; responsive at 375/768/1024/1440; no horizontal scroll; forms have labels; errors announced; timeline and player usable by keyboard where the browser allows.

## Out of scope for this pass
Dark theme toggle, marketing landing page, i18n of UI strings, the logo (placeholder wordmark only).
