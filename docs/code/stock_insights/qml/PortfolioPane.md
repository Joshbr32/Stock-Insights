# stock_insights/qml/PortfolioPane.qml
**Purpose:** Right column: account tabs (text + 2 px primary underline), the primary 'Log trade' button, and the PortfolioView for `app.currentAccount`, with a 120 ms cross-fade on tab switch.
**Used by:** Main.qml.  **Depends on:** PortfolioView, ToolButton2, FocusRing; `app.accounts`, `app.currentAccountIndex`, `app.setCurrentAccountIndex`, `app.addTrade`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| tab delegate | AbstractButton | Focusable (Tab, Space), Accessible.PageTab, FocusRing on keyboard focus. |
| fadeIn | NumberAnimation | Runs on `app.currentAccountChanged` unless `app.theme.reduceMotion`. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- The tab RowLayout sets `Layout.fillHeight: false`; without it the tab's fillHeight propagates and the row eats the page height.
- 'Log trade' is the only primary button on the page; don't add a second one in TradesTable.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-12 header
- 13-63 tab row + Log trade
- 65-70 PortfolioView
- 72-92 cross-fade
