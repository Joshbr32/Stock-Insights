# stock_insights/main_window.py
**Purpose:** The desktop main window: hosts the QML scene (`qml/Main.qml`) in a QQuickWidget, owns the menu bar + status corner, the background timers/workers, and every QML callback that opens a QWidget dialog or writes to the store.
**Used by:** `main.py` (`MainWindow(store)`), `qml_bridge.AppController` (via the callback dict).  **Depends on:** `qml_bridge.AppController`, `theme.ThemeManager`, `api_client` stores, `background` (threads), `file_actions` (File menu), `admin_dialogs`, `dialogs/*`, `symbol_history_dialog`, `settings_dialog`, `workers` (Marks/NetCheck/Reconnect), `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `MainWindow(store)` | QMainWindow | Builds theme → AppController → menus → status corner → QML, then starts timers. `self.theme` (ThemeManager) and `self._app` (AppController) are read by other modules. |
| `_offlineReported` / `_syncedReported` | Signal(int) | FallbackDataStore's `_on_offline_cb` / `_on_online_cb` are set to these `.emit`s so status updates from worker threads are queued onto the GUI thread. |
| callback dict in `__init__` | QML API | Keys `add_ticker, remove_ticker, rename_ticker, refresh_marks, add_trade, edit_trade, delete_trade, set_goal_target, open_goal_options, open_trade_history_options, holdings_menu, trade_menu`. Keep keys + arities stable (qml_bridge calls them). Dialog/menu handlers go through `_safe_run`. |
| `_safe_run(fn, *a)` | method | Defers to the next event-loop tick and shows errors. Required for anything QML triggers that opens a QDialog/QMenu (nested event loops crash on Windows). |
| `_run_in_background(fn, args, kwargs, on_done, on_error, label)` | method | Thin wrapper over `BackgroundCalls.run`; callbacks run on the GUI thread. |
| `_save_trades(account, trades, failure_note="")` | method | One background call that runs `store.save_trade(account, t)` for each trade in order, then `refresh_all_accounts()`. On error: refresh, then the "Couldn't save" box. |
| `_delete_trade(account, uid)` | method | Background `store.delete_trade`, then refresh. |
| trade handlers | methods | add / edit / mark down / double down / fulfil save one trade; close position saves each closed lot; delete uses the uid; `_on_move_trade` is one save under the destination account. None of them sends the whole account. Restore (`_on_restore`) still uses the bulk path through `io_utils.apply_backup`. |
| `_set_connection_state(state, n)` | method | Status corner text/role/tooltip from `_CONNECTION_STATES`; no-op on repeat; mirrors to `AppController.set_status`. |
| `_level1_tick` / `_kick_netcheck` / `_attempt_reconnect` | methods | Start single-flight workers (`SingleFlight`), ignored while one is running. |
| `_kick_health_probe` / `_on_health_result` | methods | `/health` every 15 s (skipped when the netcheck says no internet); result goes in the status tooltip. |
| `_on_restore` | method | Validate/confirm on GUI thread (`file_actions.choose_restore`), then pre-restore snapshot + `apply_backup` in the background. |
| `_open_manage_passwords` / `_open_view_user_portfolio` | methods | Check admin + server (`_server_available`), fetch `list_users` in the background, then open the dialog. |
| `update_ui()` | method | Called by `ThemeManager.apply()`; re-mirrors the status colour to QML. |
| `closeEvent` | override | Saves QSettings (local only), stops all timers, closes viewer windows, shuts down flights (4 s) and background calls (2 s, with `requestInterruption`). |

## Data and state
QSettings `("StockInsights","StocksGUI")`: `ui/THEME_OVERRIDE`, `ui/MATCH_SYSTEM_ACCENT`, `ui/THEME_NAME`, `ui/FONT_SIZE`, `intervals/L1_INTERVAL|NET_INTERVAL|L1_ENABLED` (ms / bool), `view/EQUITY_CURVE_VISIBLE`, `trade_defaults/default_quantity|quantity_increment`, `watchlist/items` (list; local mirror of the store watchlist). Launch auto-snapshot via `io_utils.write_auto_snapshot` (deferred 0 ms).

## How to change it safely
- Never connect worker signals to lambdas/plain functions when the handler touches widgets: PySide6 runs those on the emitting thread. Use bound methods of QObjects or `BackgroundCalls`/`SingleFlight`.
- `_current_account_trades`/`_all_trades` may do a network GET on the GUI thread when the store's trade cache is cold (after a write).
- `_BASE_MIN_HEIGHT` (640) assumes the QML page scrolls; raise it only if the top of the page stops fitting.
- `_holding_symbols` is the one place that reads the private `account.holdings._rows` (no public accessor in qml_bridge).
- Amber/`pace` is QML-only; status colours use `good`/`bad`/`text_muted` via `widgets.set_text_role`.
- Visual check: `python scripts/ui_snapshot_dialogs.py --out <dir> --only main_window`.

- Trade identity: a dialog's `to_trade()` builds a NEW `Trade` (new uid). An edit must copy `uid` from the trade being edited; changes to an existing trade are made on a `dataclasses.replace` copy, never on an object returned by the store (those are shared with its cache).
- `source_index` from QML indexes the current account's trades in store order; the uid is looked up from that list at the moment of the action.

## Map
- 1-101 imports, constants, `_CONNECTION_STATES`
- 103-120 trade-lot helpers
- 126-260 `__init__`; then minimum window size
- 268-400 helpers (`_save_trades` 299, `_delete_trade`, `_safe_run`, `_run_in_background`, trade dialog factory 386)
- 403-527 menus, status corner, QML host, status corner state
- 529-607 watchlist; 609-702 trade CRUD (move 647) + goal target
- 704-765 launch snapshot, View toggles, goal options
- 767-928 context menus (holdings / trade), close 797 / mark down / double down / fulfill 911
- 930-1087 settings, File menu actions, account + admin
- 1089-1300 timers, marks, netcheck, health, reconnect, offline/sync status
- 1302-1347 save settings + closeEvent
