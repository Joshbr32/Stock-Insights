# stock_insights/dialogs/trade_actions.py
**Purpose:** Dialogs acting on an existing order/position: Mark order filled, Mark down (solve the buy price for a target average), Double down (preview the new average).
**Used by:** main_window, portfolio_tab (edit mode).  **Depends on:** `portfolio` (Holding, Trade, solve_buy_mark_for_target_avg), `dialogs/_common`, `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `FulfillOrderDialog(trade, parent)` | QDialog | `get_fill_date()`, `get_fill_price()` (defaults to the order price). Primary "Mark filled". |
| `MarkDownDialog(holding, default_quantity=1, quantity_increment=1, parent=None)` | QDialog | Recomputes on qty/target change; unreachable target → inline error and disabled "Log trade". `to_trade()` uses the solved price. |
| `DoubleDownDialog(holding, current_mark=None, quantity_increment=1, parent=None)` | QDialog | Default qty = current qty, default price = mark or avg cost. `to_trade()`. |
| `_position_panel`, `_blended_avg` | funcs | Shared "Your X position" panel; blended average maths. |

## Data and state
None.

## How to change it safely
- Averages must match portfolio.py (and pwa/js/portfolio.js).
- `buy_qty_spin`, `target_avg_spin`, `buy_price_spin`, `btn_save` names are used by the snapshot script.

## Map
- 1-46 docstring, imports, helpers; 53-87 FulfillOrderDialog; 94-185 MarkDownDialog; 192-259 DoubleDownDialog
