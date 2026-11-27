# pwa/js/charts.js
**Purpose:** The two visual components of the PWA: the pace rail (home hero, also on each goal card) and the equity-curve chart. Hand-built DOM/SVG, no chart library.
**Used by:** `pwa/js/app.js`.  **Depends on:** `ui.js` (`el`, `svg`, formatters, `reducedMotion`), `portfolio.js` (`goalExpectedByNow`, `tradingDaysBetween`). Pace rules mirror the desktop rail: `stock_insights/qml_bridge.py` `AccountController._pace_map` and `_build_pace_line`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `weekdaysBetween(start, end)` | fn | Alias of portfolio.js `tradingDaysBetween` (kept for callers). |
| `paceFraction(date, year?)` | fn | elapsed / (elapsed + remaining) trading days at `date`, today counted in both (as `compute_goal_progress`); 0 before Jan 1, 1 after Dec 31. |
| `paceToday(target, today?)` | fn | `goalExpectedByNow(target, today)` — where realised P/L should be today; equals the desktop's `expectedRaw`. |
| `paceSentence(realized, target, pace, hasClosed?)` | fn | Desktop wording: "Close a trade to start your pace" (no closed trade), "Goal reached", "$X ahead of pace" (delta >= 0, so also when exactly on pace), "$X behind pace". Whole dollars. |
| `paceRail({title, target, realized, hasClosed?, today?, compact?, animate?})` | fn -> `<section class="pace">` | `hasClosed=false` gives the neutral start state (no ahead/behind colour). Track 0..target, filled to realised P/L with a dot, amber tick at today's pace, labels "$0 / Today's pace $X / target". `role=img` with a full sentence `aria-label`. `animate` runs the 400 ms fill (skipped under reduced motion); app.js animates once per goal key. |
| `equityChart(curve, {paceTarget?})` | fn -> `<div class="eq">` | `curve` from `buildEquityCurve`. Fixed 320x140 viewBox stretched with `preserveAspectRatio=none` and non-scaling strokes; dots and tooltip are HTML overlays in % so they stay round. With `paceTarget`, draws the dashed amber pace line as two points, ($0, Jan 1 00:00) to (`paceToday`, today 16:00), like the desktop's `_build_pace_line`, and widens the x-axis to cover both ends (the left axis label then reads Jan 1). Pointer (mouse/touch) and keyboard (arrows, Home, End, Escape) show the nearest point. |

## Data and state
None persisted. Each chart keeps its own selected index in a closure; listeners live on nodes that are discarded with the view (no global listeners).

## How to change it safely
- Amber (`--pace`) is reserved for the tick and pace line (design-system.md). Do not use it for text.
- Pace numbers and sentences were checked equal to `_pace_map` for 7 dates x 3 targets (see docs/code/pwa/js/portfolio.md). If the desktop changes its pace rule, change `goalExpectedByNow` / `paceSentence` to match.
- Pass `paceTarget` only when the curve is all-time realised P/L of exactly the goal's trades, otherwise the comparison is wrong.
- `.pace-label-tick` placement relies on `--at` and the `is-start` / `is-end` classes in styles.css.

## Map
- 1-42 header, pace maths
- 44-105 `paceRail`
- 107-228 `equityChart` (scales, pace line, overlays, interaction)
