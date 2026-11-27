# stock_insights/qml/FocusRing.qml
**Purpose:** 2 px `primary` ring drawn 3 px outside its parent; the shared keyboard-focus indicator.
**Used by:** Pill, ToolButton2, ThemedComboBox, PortfolioPane tabs, WatchlistPane list.  **Depends on:** `app.theme.primary`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| shown | bool | Bind to the control's visualFocus/activeFocus. |
| controlRadius | real | Parent radius; ring radius = +3. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Parent must not clip, or the outside ring is cut off (set `anchors.margins: 0` inside clipping parents).
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-16 whole file
