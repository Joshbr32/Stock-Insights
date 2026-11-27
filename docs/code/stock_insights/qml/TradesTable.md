# stock_insights/qml/TradesTable.qml
**Purpose:** Trade history for the selected range: search field, status filter, 10-column table (newest first, pending on top), keyboard actions and helpful empty states.
**Used by:** PortfolioView.  **Depends on:** `account.trades` (TradesModel), `textFilter`, `statusFilter`, `setTextFilter`, `setStatusFilter`, `totalTradeCount`, `dateRangeKey`; `app.editTrade`, `app.showTradeMenu`, `app.deleteTrade`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| statusLabels / statusCodes | arrays | Sentence-case labels mapped to the model's status codes. |
| keys | ListView | Enter = edit, Menu = trade menu, Delete = delete (MainWindow confirms); double-click edits, right-click opens menu. |
| selection | delegate | `cardAlt` fill + 2 px primary bar on the left; P/L colours stay intact. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Use `sourceIndex` (never the view row) for edit/delete/menu calls.
- Notes show as a tooltip after 600 ms.
- 'Log trade' lives in PortfolioPane, not here.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-37 header, columns, helpers
- 39-89 title + filter row
- 91-120 header band
- 122-225 list + delegate
- 227-262 empty states
