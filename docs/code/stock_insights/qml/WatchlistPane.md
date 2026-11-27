# stock_insights/qml/WatchlistPane.qml
**Purpose:** Left column: watched symbols with last price ('No price' when unknown), keyboard navigable, Add symbol / Remove buttons.
**Used by:** Main.qml.  **Depends on:** `app.watchlist` (WatchlistModel), `app.addTicker`, `app.removeTicker`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| list | ListView | Up/Down move, Delete removes; selection = `cardAlt` fill. |
| Remove | ToolButton2 | Disabled until a row is selected; tooltip explains why. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Bind counts to `app.watchlist.count` (notifying), not rowCount().
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-19 header + title
- 21-98 list + delegate + empty state
- 100-119 buttons
