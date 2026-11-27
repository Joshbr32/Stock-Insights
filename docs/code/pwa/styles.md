# pwa/styles.css
**Purpose:** All PWA styling in the "Harbor" design system: tokens for light and dark, layout, controls, pace rail, equity chart, dialog sheet, toast, login, motion.
**Used by:** `pwa/index.html`; class names are produced by `pwa/js/app.js`, `charts.js`, `ui.js`.  **Depends on:** nothing (system fonts, no web fonts).

## Key parts
| Name | Kind | What it does / contract |
|---|---|---|
| `:root` tokens | vars | `--bg --card --card2 --text --text-muted --border --primary --on-primary --pace --good --bad` = the design-system table (light), overridden in `@media (prefers-color-scheme: dark)`. Type scale `--fs-12 … --fs-40` from a 15 px root; `--tap` 44 px; `--safe-*` safe-area insets. |
| `.topbar`, `.view`, `.tabbar` | layout | Sticky top bar and fixed 5-tab bar, both padded by safe-area insets; the view leaves room for the tab bar. |
| `.panel`, `.stack`, `.stats`, `.rows`, `.kv` | layout | Panels on `bg` by tone (no shadows), radius 10; rows with hairline separators; key/value lists as `<dl>`. |
| `.btn*`, `.icon-btn`, `.input`, `.select`, `.seg` | controls | All at least 44 px tall; inputs 16 px text so iOS doesn't zoom; focus ring 2 px `--primary` via `:focus-visible`. |
| `.pace*` | component | Pace rail: track, fill, dot, amber tick, scale labels (`--at`, `is-start`, `is-end`). 400 ms fill transition. |
| `.eq*` | component | Equity chart plot, line, dashed amber pace line, overlay dots, tooltip, axis. |
| `.sheet` | component | Native `<dialog>` as a bottom sheet on phones, centred above 700 px. |
| `.toast` | component | `is-ok/is-warn/is-err` add a ✓/⚠ glyph so state isn't colour-only. |

## How to change it safely
- Tokens must stay in sync with `docs/design/design-system.md` and the `theme-color` metas in `index.html` (`bg`).
- `--pace` is used only by `.pace-tick`, `.eq-pace`, `.eq-legend-pace`.
- No all-caps, letter-spaced labels or monospace for data; numbers use `font-variant-numeric: tabular-nums` (`.num`, `.stat-value`, `.pace-value`).
- `prefers-reduced-motion` neutralises every animation/transition at the bottom of the file; new motion is covered automatically.
- The old editorial stylesheet's classes are gone; grep app.js before removing any class.

## Map
- 6-57 tokens (light, dark)
- 59-114 base, utilities, focus, skip link, headings
- 115-195 app frame, tab bar, layout helpers, panels
- 196-288 buttons, inputs, selects, fields, segmented control, pills
- 289-353 pace rail, price note
- 354-397 stats, rows, key/value lists
- 398-431 equity chart
- 432-488 dialog sheet, toast, login
- 489-504 motion, wider screens
