# Epoch design system (source of truth for app/static)

Direction: Natural, archival, cinematic design sampled from film footage. Deep navy night (`#06111C`), ice (`#E6F1F6`), steel blue (`#487697`), warm archival paper (`#F4F1EA`), and deep ink (`#0B1520`), with a single recording red accent (`#C63A33`). Zero generic purple gradients or AI-slop washes. White and paper canvases, solid flat ink buttons with high contrast, pill controls, crisp hairline borders, and dark film-grade player/timeline framing.

Typography: Instrument Serif (display editorial titles), Inter (crisp UI body & controls), JetBrains Mono (timecodes, metrics, and provenance data). All fonts self-hosted in `app/static/fonts/`.

Skill rules applied: contrast >= 4.5:1 (WCAG AA compliant), visible ink focus rings, 44px minimum touch targets on coarse pointers, mobile-first breakpoints (375/768/1024/1440), reduced-motion support, loading + empty + error states with aria-live, skip link, no emoji icons, 150-300ms ease-out transitions, flat solid fills with zero purple/violet gradients.

## Color Tokens

### Dark Canvas & Hero Surfaces
| Token | Value | Use / Contrast |
|---|---|---|
| --night | #06111C | Dark base canvas, hero background, player outer frame |
| --night-2 | #0B1A28 | Timeline backing, dark cards, elevated surfaces |
| --night-3 | #122436 | Dark control hover, inset tracks |
| --night-line | #1E3447 | Hairline borders on dark canvas |
| --ice | #E6F1F6 | Primary text on dark (16.5:1 on night) |
| --ice-muted | #9DB4C4 | Secondary text on dark (8.8:1 on night) |
| --steel | #487697 | Accent borders, selected cuts, timeline markers |

### Light Canvas & App Surfaces
| Token | Value | Use / Contrast |
|---|---|---|
| --paper | #F4F1EA | Warm light page canvas |
| --paper-2 | #EAE6DC | Warm card backgrounds, subtle elevations |
| --bg | #FFFFFF | Pure white card surfaces, inputs, dropzone base |
| --surface | #F8F7F3 | Light secondary surface |
| --raise | #EAE6DC | Hover states, pill fills, badge backing |
| --line | #D9D4C7 | Light dividers, subtle card borders |
| --line2 | #C4BEB1 | Control outlines, input borders |
| --ink | #0B1520 | Headings, primary text, solid button fill (16.3:1 on paper) |
| --text | #0B1520 | Body text |
| --ink-2 / --muted | #4A5663 | Secondary text, descriptions (6.6:1 on paper) |
| --faint | #5E6873 | Labels, caption metadata (5.0:1 on paper) |
| --disabled | #8C96A0 | Disabled states, empty placeholders |

### Accents & Semantic States
| Token | Value | Use |
|---|---|---|
| --rec / --mark | #C63A33 | Recording indicator dot, playhead needle, active cuts |
| --accent | #1B4568 | Deep navy steel accent |
| --accent-d | #0B1520 | Solid ink links & active tab markers |
| --cta | #0B1520 | Primary CTA fill (solid ink, 16.3:1 contrast with white text) |
| --selection | #D2E4EE | Crisp ice-blue text selection |
| --ok | #2A7553 | Verified truth badge, healthy status |
| --ok-dot | #2A7553 | Green indicator dot |
| --ok-bg | #E3EFE8 | Verified pill background |
| --warn | #8A5A12 | Inconclusive check, warning callouts |
| --warn-dot | #B87B19 | Amber indicator dot |
| --warn-bg | #FAF1DC | Warning pill background |
| --bad | #BA332C | Rejected cut, error banner |
| --bad-dot | #BA332C | Red reject dot |
| --bad-bg | #FAECEB | Error pill background |
| --info-bg | #E6F1F6 | Info notice backing |

### Radii & Elevation
| Token | Value |
|---|---|
| --pill | 999px (badges, buttons, searchbar) |
| --r-card | 24px (content cards, dialogs) |
| --r-frame | 32px (player stage, hero canvas container) |
| --r | 12px (form controls, inputs) |
| --r-thumb | 8px (thumbnail cuts, scrubber previews) |
| --sh1 | 0 1px 6px -4px rgba(11, 21, 32, .12) |
| --sh2 | 0 10px 30px rgba(11, 21, 32, .08) |

## Typography
- `--display`: 'Instrument Serif', Georgia, serif (400, 400 italic)
- `--sans`: Inter, "Segoe UI Variable Text", system-ui, sans-serif (400, 500, 600)
- `--mono`: 'JetBrains Mono', "Cascadia Mono", monospace (400, 500)

## Components
- **Status bar** (`#06111C`): 34px, engine + library status with green/amber pulse dot.
- **Floating nav pill**: sticky, blurred `#FAF9F6` at 85%, logo left with black badge + white play glyph + red rec dot, tabs centre (pills), "New project" CTA right.
- **Buttons**:
  - `button.primary`: flat solid `#0B1520` background, `#FFFFFF` text, subtle elevation.
  - `button.secondary` / ghost: white or paper pill with `--line2` border, hover to `--paper-2`.
  - `button.hero`: on dark surfaces, solid `--ice` `#E6F1F6` with `--night` `#06111C` text.
- **Player & Timeline**: dark stage frame (`#06111C` / `#0B1A28`), lanes for Voice, B-roll, and Truth Check, timeline ruler, playhead `--rec` needle.

## Strict Prohibitions
- No purple or violet accents (`#B738FF`, `#7118EE`, etc.).
- No gradient fills on buttons, text headers, or backgrounds.
- No lavender washes or AI-slop decorative blobs.
- No contrast failures under 4.5:1.
