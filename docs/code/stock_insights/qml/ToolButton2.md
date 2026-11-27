# stock_insights/qml/ToolButton2.qml
**Purpose:** Harbor button: 32 px, radius 6. `primary: true` = filled main action; otherwise quiet `cardAlt` secondary.
**Used by:** PortfolioPane (Log trade), WatchlistPane, TradesTable (Clear filters).  **Depends on:** FocusRing.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| primary | bool |  |
| text | string | Say what happens ('Log trade'); no '+', no arrows. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Focus ring shows on `visualFocus` (keyboard), not mouse.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-26 props + label
- 28-43 background
