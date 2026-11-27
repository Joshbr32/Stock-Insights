# stock_insights/qml/PortfolioView.qml
**Purpose:** One account's page as a vertically scrolling Flickable: GoalDashboard, HoldingsTable, [EquityCurveCard | AnalyticsPanel], TradesTable.
**Used by:** PortfolioPane.qml.  **Depends on:** the four cards; `app.equityCurveVisible`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| page | ColumnLayout | `height = max(implicitHeight, viewport)`: cards keep natural heights; the TradesTable (min 420) absorbs spare height. Scrolls instead of clipping, so no window minimum is needed for correctness. |
| row 3 | RowLayout | Curve height follows `analytics.implicitHeight`; analytics width 300-380 px, full width when the curve is hidden. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Only TradesTable may have `Layout.fillHeight`; any other fillHeight child steals spare height (nested layouts inherit fillHeight from children).
- The 14 px scrollbar gutter appears only when the page overflows.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-14 header
- 15-24 Flickable
- 26-77 page layout
