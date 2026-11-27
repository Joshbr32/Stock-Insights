# stock_insights/qml/ThemedComboBox.qml
**Purpose:** ComboBox drawn entirely in QML (widget QSS doesn't reach QML): 32 px, `cardAlt` field, Canvas chevron, popup fades in 100 ms.
**Used by:** AnalyticsPanel (tag, range), EquityCurveCard (mode), TradesTable (status).  **Depends on:** FocusRing, ThemedScrollBar.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| model / currentIndex / activated | ComboBox API | Callers map display labels to keys themselves. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Chevron Canvas repaints on `stroke` change (theme switch).
- Popup width >= 140 px so short combos still show full labels.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-26 field
- 28-50 chevron
- 52-77 popup
- 79-102 delegate
