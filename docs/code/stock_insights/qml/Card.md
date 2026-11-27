# stock_insights/qml/Card.qml
**Purpose:** Harbor panel: `card` colour, radius 10, padding 16, no border/shadow; children go into an inner ColumnLayout.
**Used by:** GoalDashboard, AnalyticsPanel, EquityCurveCard, HoldingsTable, TradesTable, WatchlistPane.  **Depends on:** `app.theme.card`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| content | default alias | Children of a Card land in the inner ColumnLayout. |
| padding / spacing | props | Default 16 / 12. |
| implicitHeight | binding | Inner layout height + 2×padding; width always comes from the parent layout. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Don't publish implicitWidth (wide content would push the card out of its column).
- `clip: true` keeps scrollbars inside the rounded corners.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-10 header
- 11-29 Rectangle + inner layout
