# stock_insights/api_client.py
**Purpose:** The `DataStore` abstraction for all user data (trades, accounts, goals, goal group, watchlist) and its three implementations: HTTP (`RemoteDataStore`), QSettings (`LocalDataStore`), and remote-with-offline-fallback (`FallbackDataStore`).
**Used by:** `main_window.py`, `portfolio_tab.py`, `connection_dialog.py`, `admin_dialogs.py`, `io_utils.py`, `workers.py` (ReconnectWorker), `sync_queue.py` (replay).  **Depends on:** `requests`/`urllib3`, `PySide6.QtCore`, `portfolio.py` (Trade + JSON helpers), `sync_queue.py`, `logging_utils.py`. HTTP contract: `server/server.py`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `DataStore` | ABC | get/save for trades (per-account full replace), accounts, goal target/presets, goal group, watchlist; `user_info`, `username`, `is_admin`. |
| `APIError(message, status_code)` | exception | Server answered non-2xx (or 200 with non-JSON, reported as 502). `.is_transient` = 5xx, 401, 408, 425, 429. |
| `is_transient_status(code)` | function | Same rule as `APIError.is_transient`. |
| `RemoteDataStore(base_url, token, user_info_dict, for_user_id=None, session=None)` | class | One pooled `requests.Session` (1 quick retry on connect errors and on 502/503/504 for GET/PUT), timeout `(4, 10)` s. Caches accounts, trades, goal group in memory until a write invalidates them. Raises `APIError` or `requests.RequestException`. Thread-safe. |
| `RemoteDataStore._request/_get/_put` | methods | The only place HTTP happens. `_headers()` and `_base` are also read by `admin_dialogs.py`. |
| `RemoteDataStore.invalidate_caches()` | method | Drop all cached reads (called after a reconnect). |
| `RemoteDataStore.check_auth()` | method | `GET /auth/me`; used as the reconnect ping. |
| `RemoteDataStore.ping_health()` | method | `GET /health`, 3 s timeout, never raises; returns `{ok, latency_ms, ...}`. |
| `RemoteDataStore.store_for_user / list_users` | methods | Admin: a store scoped by `?for_user_id=` (shares the session); `GET /users`. |
| `LocalDataStore(username)` | class | QSettings store. Also the on-device cache: `mirror_trades/accounts/goal_group/watchlist` overwrite a dataset with server data and record it in `mirrored_datasets()`. All access under one lock. |
| `remote_login(base_url, username, password, timeout=5)` | function | `POST /auth/login`; returns a `RemoteDataStore` that keeps the login connection. |
| `FallbackDataStore(remote, local, on_offline_cb, on_online_cb)` | class | See the state machine below. Public extras: `attempt_reconnect() -> bool`, `pending_sync_count`, `store_for_user`, `list_users`. Attributes read by other files: `_is_online`, `_remote`, `_on_offline_cb`, `_on_online_cb`. |
| `_call_on_gui_thread(fn, *args)` | function | Runs status callbacks on the GUI thread (queued via `_MainThreadInvoker` from a worker thread; direct if already there or if no Qt app exists). |

## FallbackDataStore state machine
- **online** (`_is_online` True): reads go to the server and are mirrored into `LocalDataStore`; writes go local first, then server.
- **offline**: entered on a network error, timeout, 5xx or 401 during any read or write, and at construction when this user still has queued writes. Reads come from the local cache and writes go to `sync_queue`, both with no network call, so the UI never waits on a dead server. Exception: a dataset that was never mirrored is still read from the server while offline.
- Only `attempt_reconnect()` (ReconnectWorker, every 30 s while offline) goes back online: `check_auth` ping, `sync_queue.flush`, `invalidate_caches`, then online if the queue is empty.
- **Invariant:** online implies no queued writes for this user. This keeps writes ordered and makes mirroring safe.
- A write the server rejects for good (4xx except 401/408/425/429) raises `APIError` and is not queued. Other write failures are absorbed (queued).

## Data and state
- QSettings `("StockInsights", "StocksGUI")` (Windows registry), all keys under `user_cache/<hex(utf8 username)>/`:
  `portfolio/trades` (JSON list from `trades_to_json`), `user_account/accounts` (JSON list of names), `portfolio/goal_target/<account>` (float), `goals/presets/<account>` (JSON list of 3 floats), `portfolio/goal_dashboard_accounts` (JSON list), `portfolio/goal_dashboard_shared_goal` (float), `watchlist/items` (list), `cache/mirrored` (JSON list of dataset names: `accounts`, `trades`, `goal_group`, `watchlist`).
- In memory: RemoteDataStore caches with generation counters; the bearer token (never persisted).
- Queued writes: see `sync_queue.md`.

## How to change it safely
- Routes and JSON shapes are fixed by `server/server.py` and shared with the PWA. Account names in URL paths must go through `_account_path()`.
- Every data route is a GET or a full-replace PUT. The session retry and the queue replay both rely on that idempotency; a non-idempotent route needs its own handling.
- Keep the generation check when adding a cache (fetch outside the lock, store only if the generation is unchanged), and invalidate in `finally` after a PUT (a timed-out PUT may have been applied).
- Never hold `FallbackDataStore._state_lock` or `RemoteDataStore._lock` across a network call.
- New write method: add it to `DataStore`, all three stores, a `sync_queue` action (`_replay`, `_merge_key`), and route it through `FallbackDataStore._write`.
- The server does not store `Trade.tag`, so tags do not survive a server round trip.
- `QSettings(org, app)` ignores `setDefaultFormat`; a test must patch `api_client.QSettings` with an INI factory to stay out of the registry.
- No unit tests cover this file. Smoke-test with a fake HTTP server plus an unreachable URL (`http://127.0.0.1:9`), a temp QSettings and a patched `sync_queue._QUEUE_FILE`.

## Map
- 1-66 docstring, imports, timeouts, `is_transient_status`
- 68-147 `DataStore`
- 149-205 `APIError`, `_new_session`, `_error_message`, `_account_path`
- 207-526 `RemoteDataStore` (internals 249-328, DataStore methods 330-463, admin 465-483, health 485-526)
- 528-766 `LocalDataStore` (mirroring 703-766)
- 768-799 `remote_login`
- 801-913 helpers, `_MainThreadInvoker`, `_call_on_gui_thread`
- 915-1271 `FallbackDataStore` (read path `_safe_remote_get` 1002, mirroring 1045, write path `_write` 1066, `attempt_reconnect` 1231)
