# stock_insights/dialogs/trade_history_columns.py
**Purpose:** Column visibility + multi-level sort order for the legacy PortfolioTab trade table (the QML table has fixed columns).
**Used by:** portfolio_tab `open_trade_history_view_settings`.  **Depends on:** `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `TradeHistoryColumnsDialog(columns, visible_keys, sort_rules, max_sort_levels=5, parent=None)` | QDialog | `columns` = `[(key, label)]`. |
| `selected_keys()` | method | Checked column keys in column order. |
| `selected_sort_rules()` | method | `[{"key", "ascending"}]`, skipping unused levels and duplicates. |
| `NONE_SORT_LABEL` | class attr | Combo data for "Not used" (never persisted). |

## Data and state
None; PortfolioTab persists to QSettings.

## How to change it safely
Keep return shapes; PortfolioTab validates keys against `TRADE_HISTORY_COLUMNS` on save.

## Map
- 1-14 docstring/imports; 17-73 `__init__`; 75-89 accessors
