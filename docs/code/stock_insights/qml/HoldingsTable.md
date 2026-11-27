# stock_insights/qml/HoldingsTable.qml
**Purpose:** Open positions table sized to its rows (max 6 visible, then scrolls): symbol (+ 'Short' badge), shares, avg cost, price, market value, unrealized P/L, ▲/▼ change, weight.
**Used by:** PortfolioView.  **Depends on:** `account.holdings` (HoldingsModel roles), `account.summary`, `app.showHoldingsMenu`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| cols | array | key/label/weight/right/pl per column; header and rows both render from it. |
| row delegate | Rectangle | 32 px, hairline between rows, hover/current tint `cardAlt`; right-click or Menu key opens the holdings menu. |

## Data and state
None persisted. All state comes from `app` (qml_bridge.AppController) and is per-account on the AccountController.

## How to change it safely
- Numbers right-aligned, text left; P/L columns coloured by `unrealizedSign` and always signed.
- Empty state invites 'Log a trade'.
- All QML reads colours/fonts from `app.theme` (qml_bridge.ThemeController) and sizes text as `N * app.theme.fontScale` px on the 12/13/15/20/40 scale. Imports `QtQuick.Controls.Basic` so custom backgrounds are honoured (the native Windows style ignores them and warns). Check changes with `python scripts/ui_snapshot.py --out <dir>`; it echoes QML warnings to stderr.

## Map
- 1-28 header + columns
- 30-36 title
- 38-70 header band
- 72-170 list + delegate
- 172-191 empty state
