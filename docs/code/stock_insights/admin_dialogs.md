# stock_insights/admin_dialogs.py
**Purpose:** Account and admin windows: own profile/password/portfolios, the read-only viewer over another user's portfolios, the user picker, and admin password reset.
**Used by:** main_window.  **Depends on:** `api_client` (stores; private `_base`, `_headers()`, `_session`, `_is_online`, `_remote`), `background`, `portfolio_tab.PortfolioTab`, `widgets`, `workers.MarksWorker`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `UserAccountDialog(store, parent)` | QDialog | File > Account and portfolios. Profile (read-only), change password (new + confirm, ≥4 chars, background PUT), portfolios list with Add / Remove (`store.save_accounts`, synchronous). |
| `UserPortfolioViewer(user_store, username, settings, parent)` | QMainWindow | One read-only `PortfolioTab` per portfolio in a tab widget; marks refresh every 30 s via `SingleFlight`. Signal `closed`. `update_ui()` for theme refresh. |
| `SelectUserDialog(users, current_user_id, parent)` | QDialog | Pick a user (excludes self); `selected_user() -> dict or None`. |
| `ManageUserPasswordsDialog(store, parent, users=None)` | QDialog | Admin reset. `users` optional (MainWindow passes a background-fetched list; else fetched synchronously). New password shown in plain text on purpose (admin passes it on). |
| `_put_password(remote, user_id, pw)` | func | `PUT /users/{id}/password` on the store's pooled session, timeout (4, 10); raises RuntimeError with the server text. Runs on a worker thread. |
| `_online_remote(store)` | func | RemoteDataStore if reachable, else None. |

## Data and state
No local persistence. Server endpoint: `PUT /users/{id}/password {"new_password"}`.

## How to change it safely
- Constructor signatures are called by main_window; `users=` is keyword-only in practice.
- Network work must go through `BackgroundCalls` (never `requests` on the GUI thread).
- The viewer must stay read-only: PortfolioTab(read_only=True) skips the goal-group prune write.
- Missing API: RemoteDataStore has no `set_user_password()`; this module reaches into private attributes.

## Map
- 1-58 docstring, imports, constants; 61-110 helpers
- 117-275 UserAccountDialog; 281-368 UserPortfolioViewer
- 375-404 SelectUserDialog; 411-513 ManageUserPasswordsDialog
