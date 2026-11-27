# stock_insights/dialogs/goal_options.py
**Purpose:** View > Goal options: which portfolios share one goal, the shared and per-portfolio targets, and each portfolio's three quick-set amounts.
**Used by:** main_window `_on_open_goal_options`, portfolio_tab (edit mode).  **Depends on:** `dialogs/_common`, `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `GoalDashboardOptionsDialog(accounts, included_accounts, goal_targets, preset_values, parent)` | QDialog | Results: `selected_accounts()`, `shared_goal()`, `individual_goals()` (only non-shared), `all_preset_values()` (3 floats per account). Shared-goal row hidden when nobody shares. |
| `_AccountGoalBlock` | Panel | One portfolio: checkbox, own goal (hidden while shared), Low/Middle/High preset spins. Signal `sharedToggled`. |

## Data and state
None; caller writes via `store.set_goal_group(...)`.

## How to change it safely
The four accessor return shapes feed `DataStore.set_goal_group` directly; keep them.

## Map
- 1-29 docstring/imports; 32-94 `_AccountGoalBlock`; 97-158 dialog + accessors
