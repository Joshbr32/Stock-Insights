# stock_insights/portfolio_tab.py
**Purpose:** Legacy QWidget portfolio view for one account (goal, performance, open positions, trade history). Today only used read-only inside `admin_dialogs.UserPortfolioViewer`. Also re-exports the dialog classes and `_fmt_*` helpers by their historical import path.
**Used by:** admin_dialogs.  **Depends on:** `portfolio` (all compute_* functions), `dialogs` (re-exported), `dialogs/_common`, `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `PortfolioTab(account_name, store, settings, read_only=False, parent=None)` | QWidget | Loads all trades from `store`, filters to `account_name`. Signal `tradesChanged` (edit mode only). |
| `holdings_symbols()` | method | Distinct open symbols (for marks refresh). |
| `update_marks(data)` | method | `{sym: {"price": float}}` → re-render. |
| `update_ui()` / `reload_from_store()` / `refresh_view(selected)` | methods | Theme refresh / reload / full recompute + render. |
| `TRADE_HISTORY_COLUMNS` | class attr | `(key, label)` pairs; keys persisted in QSettings, labels display-only. |
| `_sorted_trade_rows` | method | Parses sort rules once per sort and passes them to `_compare_trade_rows`. |

## Data and state
QSettings (passed in): `portfolio/trade_history_visible_columns`, `portfolio/trade_history_sort` (JSON lists), `trade_defaults/*`. Writes to the store only when `read_only=False`.

## How to change it safely
- `read_only=True` must never write: `_load_state` skips `sync_goal_dashboard_accounts()` (a goal-group write) in that mode.
- `refresh_view` runs on every marks update (30 s) per tab: keep per-row work cheap (theme colours are looked up once per render).
- Edit mode still saves the whole account (`save_account_trades`); `_edit_trade` copies the edited trade's `uid` onto the dialog's new `Trade`.
- Numbers must match the QML view and pwa/js/portfolio.js (they all come from portfolio.py).

## Map
- 1-74 docstring, imports/re-exports; 80-168 class attrs, init, public API
- 170-258 QSettings helpers; 260-351 store/goal helpers
- 353-514 `_build_ui`; 516-563 presets; 565-613 load/save
- 615-863 selection, trade CRUD, context menus (edit mode)
- 865-992 sorting + filtering; 994-1163 refresh + render helpers
