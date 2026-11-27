# pwa/js/charts.js
**Purpose:** The two visual components of the PWA: the pace rail (home hero, also on each goal card) and the equity-curve chart. Hand-built DOM/SVG, no chart library.
**Used by:** `pwa/js/app.js`.  **Depends on:** `ui.js` (`el`, `svg`, formatters, `reducedMotion`).

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `weekdaysBetween(start, end)` | fn | Inclusive weekday count, O(1). Same rule as portfolio.js `tradingDaysBetween` (weekdays, no holidays). |
| `paceFraction(date, year?)` | fn | Share of this year's weekdays elapsed at `date` (0 before Jan 1, 1 after Dec 31). |
| `paceToday(target, today?)` | fn | `target * paceFraction(today)` — where realised P/L should be today. |
| `paceSentence(realized, target, pace)` | fn | "$1,240 ahead of pace" / "$860 behind pace" / "On pace" / "Goal reached". |
| `paceRail({title, target, realized, today?, compact?, animate?})` | fn -> `<section class="pace">` | Track 0..target, filled to realised P/L with a dot, amber tick at today's pace, labels "$0 / Today's pace $X / target". `role=img` with a full sentence `aria-label`. `animate` runs the 400 ms fill (skipped under reduced motion); app.js animates once per goal key. |
| `equityChart(curve, {paceTarget?})` | fn -> `<div class="eq">` | `curve` from `buildEquityCurve`. Fixed 320x140 viewBox stretched with `preserveAspectRatio=none` and non-scaling strokes; dots and tooltip are HTML overlays in % so they stay round. With `paceTarget`, draws the dashed amber pace line (24 samples from max(first point, Jan 1) to today) and extends the x-axis to today. Pointer (mouse/touch) and keyboard (arrows, Home, End, Escape) show the nearest point. |

## Data and state
None persisted. Each chart keeps its own selected index in a closure; listeners live on nodes that are discarded with the view (no global listeners).

## How to change it safely
- Amber (`--pace`) is reserved for the tick and pace line (design-system.md). Do not use it for text.
- Pace is a weekday-proportional approximation of the desktop's trading-day calendar; if the desktop changes its pace rule, change `paceFraction` to match.
- Pass `paceTarget` only when the curve is all-time realised P/L of exactly the goal's trades, otherwise the comparison is wrong.
- `.pace-label-tick` placement relies on `--at` and the `is-start` / `is-end` classes in styles.css.

## Map
- 1-46 pace maths
- 47-108 `paceRail`
- 109-233 `equityChart` (scales, pace samples, overlays, interaction)
