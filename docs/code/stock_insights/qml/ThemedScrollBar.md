# stock_insights/qml/ThemedScrollBar.qml
**Purpose:** Thin, trackless vertical scrollbar (border-coloured thumb, muted on hover) for every list and the page.
**Used by:** all lists, PortfolioView, ThemedComboBox popup.  **Depends on:** `app.theme`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| ScrollBar | type | AsNeeded; thumb hidden when everything fits. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Keep it quiet: no accent colour.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-22 whole file
