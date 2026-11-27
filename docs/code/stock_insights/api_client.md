# stock_insights/api_client.py
**Purpose:** The `DataStore` abstraction for all user data (trades, accounts, goals, goal group, watchlist) and its three implementations: HTTP (`RemoteDataStore`), QSettings (`LocalDataStore`), and remote-with-offline-fallback (`FallbackDataStore`).
**Used by:** `main_window.py`, `portfolio_tab.py`, `connection_dialog.py`, `admin_dialogs.py`, `io_utils.py`, `workers.py` (ReconnectWorker), `sync_queue.py` (replay).  **Depends on:** `requests`/`urllib3`, `PySide6.QtCore`, `portfolio.py` (Trade + JSON helpers), `sync_queue.py`, `logging_utils.py`. HTTP contract: `server/server.py`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `DataStore` | ABC | get/save for trades, accounts, goal target/presets, goal group, watchlist; `user_info`, `username`, `is_admin`. |
| `DataStore.save_trade(account_name, trade) -> uid` | method | Upsert ONE trade by `trade.uid` into `account_name` (a trade in another account is moved). Idempotent. Returns the uid it is stored under (differs from `trade.uid` only after a server 409, see below). Not abstract: the default reads all trades and rewrites the affected account(s) through `save_account_trades` (source account first on a move). |
| `DataStore.delete_trade(account_name, uid)` | method | Delete by uid; unknown uid is not an error. Default works through `save_account_trades`. |
| `DataStore.save_account_trades(account_name, trades)` | method | Whole-account replace. Kept for restore-from-backup, the admin viewer, old queue entries and the old-server fallback. |
| `APIError(message, status_code)` | exception | Server answered non-2xx (or 200 with non-JSON, reported as 502). `.is_transient` = 5xx, 401, 408, 425, 429. |
| `is_transient_status(code)` | function | Same rule as `APIError.is_transient`. |
| `RemoteDataStore(base_url, token, user_info_dict, for_user_id=None, session=None)` | class | One pooled `requests.Session` (1 quick retry on connect errors and on 502/503/504 for GET/PUT/DELETE), timeout `(4, 10)` s. Caches accounts, trades, goal group in memory until a write invalidates them. Raises `APIError` or `requests.RequestException`. Thread-safe. |
| `RemoteDataStore.save_trade / delete_trade` | methods | `PUT` / `DELETE /trades/{account}/{uid}` (both parts URL-encoded by `_trade_path`). On success the cached trade list is replaced by an edited copy (`_edit_trade_cache`), so the refresh after a save costs no request. See "Per-trade saves" below for 404/405, 503 and 409. |
| `RemoteDataStore._request/_get/_put` | methods | The only place HTTP happens. `_headers()` and `_base` are also read by `admin_dialogs.py`. |
| `RemoteDataStore.invalidate_caches()` | method | Drop all cached reads (called after a reconnect). |
| `RemoteDataStore.check_auth()` | method | `GET /auth/me`; used as the reconnect ping. |
| `RemoteDataStore.ping_health()` | method | `GET /health`, 3 s timeout, never raises; returns `{ok, latency_ms, ...}`. |
| `RemoteDataStore.store_for_user / list_users` | methods | Admin: a store scoped by `?for_user_id=` (shares the session); `GET /users`. |
| `LocalDataStore(username)` | class | QSettings store. `save_trade`/`delete_trade` are one read + one write under the lock. `get_all_trades` writes generated uids back once for data stored before uids existed. Also the on-device cache: `mirror_trades/accounts/goal_group/watchlist` overwrite a dataset with server data and record it in `mirrored_datasets()`. All access under one lock. |
| `remote_login(base_url, username, password, timeout=5)` | function | `POST /auth/login`; returns a `RemoteDataStore` that keeps the login connection. |
| `FallbackDataStore(remote, local, on_offline_cb, on_online_cb)` | class | See the state machine below. Public extras: `attempt_reconnect() -> bool`, `pending_sync_count`, `store_for_user`, `list_users`. Attributes read by other files: `_is_online`, `_remote`, `_on_offline_cb`, `_on_online_cb`. |
| `_call_on_gui_thread(fn, *args)` | function | Runs status callbacks on the GUI thread (queued via `_MainThreadInvoker` from a worker thread; direct if already there or if no Qt app exists). |

## Per-trade saves (server 1.1 contract: `docs/api/server-1.1-changes.md`)
- `RemoteDataStore._per_trade_routes`: `None` until the first per-trade call answers, then `True`, or `False` for the rest of the session (`_per_trade_call`, one WARNING logged). It becomes `False` on **404/405 while still `None`** (server older than 1.1) or on **503 when `/health` reports `schema: needs_migration`** (1.1 server, database not migrated). Any other 503 stays an outage. A 404 after the routes worked is a real error.
- While `False`, `save_trade`/`delete_trade` run the `DataStore` defaults (GET if the cache is cold, then whole-account PUT). `store_for_user` copies the flag.
- Servers without uids: `_trades_from_rows` gives each row a uid derived from its content (`_content_uids`: sha256 of owner, account, fields without tag, plus a counter for identical rows), so a trade keeps its uid across refetches. `_legacy_uids` (filled by `_remember_legacy_uids` after each fallback bulk save) maps that derived uid back to the uid the session saved the trade under.
- **409** on the PUT (uid belongs to another user): saved once more under `new_trade_uid()`; the new uid is returned and `FallbackDataStore.save_trade` renames its local copy. A second 409 is raised (4xx: never queued).
- `FallbackDataStore`: local write first, then remote; offline it queues `save_trade` / `delete_trade` (see `sync_queue.md`). `_remote_trade_write` marks the remote store's new trade list as already mirrored, so the next read does not rewrite QSettings.

## FallbackDataStore state machine
- **online** (`_is_online` True): reads go to the server and are mirrored into `LocalDataStore`; writes go local first, then server.
- **offline**: entered on a network error, timeout, 5xx or 401 during any read or write, and at construction when this user still has queued writes. Reads come from the local cache and writes go to `sync_queue`, both with no network call, so the UI never waits on a dead server. Exception: a dataset that was never mirrored is still read from the server while offline.
- Only `attempt_reconnect()` (ReconnectWorker, every 30 s while offline) goes back online: `check_auth` ping, `sync_queue.flush`, `invalidate_caches`, then online if the queue is empty.
- **Invariant:** online implies no queued writes for this user. This keeps writes ordered and makes mirroring safe.
- A write the server rejects for good (4xx except 401/408/425/429) raises `APIError` and is not queued. Other write failures are absorbed (queued).

## Data and state
- QSettings `("StockInsights", "StocksGUI")` (Windows registry), all keys under `user_cache/<hex(utf8 username)>/`:
  `portfolio/trades` (JSON list from `trades_to_json`, each trade with `uid` and `tag`), `user_account/accounts` (JSON list of names), `portfolio/goal_target/<account>` (float), `goals/presets/<account>` (JSON list of 3 floats), `portfolio/goal_dashboard_accounts` (JSON list), `portfolio/goal_dashboard_shared_goal` (float), `watchlist/items` (list), `cache/mirrored` (JSON list of dataset names: `accounts`, `trades`, `goal_group`, `watchlist`).
- In memory: RemoteDataStore caches with generation counters, `_per_trade_routes`, `_legacy_uids`; the bearer token (never persisted).
- Queued writes: see `sync_queue.md`.

## How to change it safely
- Routes and JSON shapes are fixed by `server/server.py` and shared with the PWA. Account names in URL paths must go through `_account_path()`.
- Every data route is a GET, a full-replace PUT, or an upsert/delete by uid. The session retry and the queue replay both rely on that idempotency; a non-idempotent route needs its own handling.
- Keep the generation check when adding a cache (fetch outside the lock, store only if the generation is unchanged), and invalidate in `finally` after a PUT (a timed-out PUT may have been applied). `_edit_trade_cache` replaces the cached list and bumps the generation; never mutate the cached list or its `Trade` objects (callers hold them: use `dataclasses.replace`).
- Never hold `FallbackDataStore._state_lock` or `RemoteDataStore._lock` across a network call.
- New write method: add it to `DataStore`, all three stores, a `sync_queue` action (`_replay`, `_merge_key`), and route it through `FallbackDataStore._write`.
- `Trade.tag` and `Trade.uid` are sent on every trade write and read from `GET /trades` (server 1.1+). A 1.0 server drops both.
- `save_trade` must keep returning the stored uid from all three stores (the 409 path depends on it).
- `QSettings(org, app)` ignores `setDefaultFormat`; a test must patch `api_client.QSettings` with an INI factory to stay out of the registry.
- Tests: `tests/test_sync.py` (in-process fake HTTP server for 1.1, 1.0 and unmigrated servers; its `isolated` fixture does the QSettings and queue-file patching). Reads, goals, watchlist and login are still untested.

## Map
- 1-76 docstring, imports, timeouts, `is_transient_status`
- 78-188 `DataStore` (default `save_trade` / `delete_trade` 92-124)
- 190-298 `APIError`, `_new_session`, `_error_message`, URL + trade helpers (`_trade_path`, `_upsert`, `_trade_fields`, `_trade_payload`)
- 300-733 `RemoteDataStore` (internals 349-497 incl. `_per_trade_call` 389, DataStore methods 499-668 incl. per-trade 531-580, admin 670-692, health 694-733)
- 735-997 `LocalDataStore` (trades 780-815, mirroring 934-997)
- 999-1030 `remote_login`
- 1032-1196 helpers (`_content_uids`, `_trades_from_rows` 1050-1090, `_uids_stored`), `_MainThreadInvoker`, `_call_on_gui_thread`
- 1198-1594 `FallbackDataStore` (read path `_safe_remote_get` 1285, mirroring 1328, write path `_write` 1349, per-trade 1400-1440, `attempt_reconnect` 1556)
