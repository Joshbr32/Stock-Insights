# stock_insights/qml/EquityCurveCard.qml
**Purpose:** Cumulative realized P/L line (primary) with the goal pace line (amber, 'All time'/'Year to date' only), inline legend, per-trade/daily toggle, money-formatted y axis and a hover readout.
**Used by:** PortfolioView (hidden via View menu -> `app.equityCurveVisible`).  **Depends on:** QtCharts; `account.equityCurve`, `equityCurveMinY/MaxY`, `equityPaceLine`, `equityCurveMode`, `setEquityCurveMode`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| yTicks / _niceTicks() | props/func | ~4 nice gridline values; drive the CategoryAxis labels ('$6,000', '−$500'). |
| series / paceSeries | LineSeries | Repopulated from bound properties (ChartView swallows Connections children in some PySide6 builds). |
| _onSeriesHover | function | Tooltip with date and signed value. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Axis min/max cover both series so the pace line is never clipped; DateTimeAxis min/max are pinned (falls back to 1970 otherwise).
- The curve only repaints when `analyticsChanged` fires (not on marks ticks).
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-50 header, derived props, tick + money helpers
- 52-85 title, legend, mode combo
- 87-170 ChartView, axes, series
- 172-230 empty state + tooltip
- 232-253 hover handler
