# stock_insights/dialogs/__init__.py
**Purpose:** Package front door: re-exports the trade and goal dialogs so callers write `from stock_insights.dialogs import TradeEditDialog`.
**Used by:** main_window, portfolio_tab (which re-exports them again for the old `from .portfolio_tab import ...` path).  **Depends on:** the sibling modules.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `GoalDashboardOptionsDialog` | re-export | goal_options.py |
| `TradeEditDialog` | re-export | trade_edit.py |
| `TradeHistoryColumnsDialog` | re-export | trade_history_columns.py |
| `FulfillOrderDialog`, `MarkDownDialog`, `DoubleDownDialog` | re-export | trade_actions.py |

## Data and state
None.

## How to change it safely
Add new dialogs to both the import list and `__all__`. Shared helpers live in `_common.py` (dialog-only) and `stock_insights/widgets.py` (layout/theme, shared app-wide).

## Map
- 1-25 whole file
