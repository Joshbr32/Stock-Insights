# stock_insights/qml/Metric.qml
**Purpose:** Label/value pair. Inline (label left, value right, 13 px) for statement lists; `stacked` (12 px label over 15 px value) for the goal strip.
**Used by:** GoalDashboard, AnalyticsPanel.  **Depends on:** `app.theme`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| label / value | string props |  |
| sign | int | +1 good, -1 bad, 0 neutral colour. Values already carry +/−. |
| stacked | bool | Switches GridLayout to one column. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Numbers use tabular figures (`tnum`).
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-16 props
- 18-40 labels
