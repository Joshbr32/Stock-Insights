# stock_insights/connection_dialog.py
**Purpose:** Startup sign-in dialog. Signs in to the sync server on a background thread (external URL, then LAN URL, 3 attempts each) or lets the user work offline.
**Used by:** `main.py` (`ConnectionDialog().run()`).  **Depends on:** `api_client` (`remote_login`, `FallbackDataStore`, `LocalDataStore`, `APIError`), `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `ConnectionDialog(parent=None)` | QDialog | `run() -> DataStore or None`. Success → `FallbackDataStore(remote, LocalDataStore(username))`; Work offline → `LocalDataStore(username or "local")`; Quit → None. |
| `_LoginThread(username, password)` | QThread | `run()` does TCP pre-flight + `remote_login`; signals `success(store)`, `error(str)` (user-facing message), `log_msg(str)`. `cancel()` stops between attempts and cuts the 2 s retry delay. |
| `ConnectionDialog.done()` | override | Cancels and waits (≤ CONNECT_TIMEOUT+1 s) for a running login thread so it is never destroyed while running. |
| `_show_error(msg)` / `_show_status(msg, role)` | methods | Status line under the form (role-coloured). |
| `SERVER_URL_EXTERNAL`, `SERVER_URL_LOCAL`, `CONNECT_TIMEOUT`, `MAX_RETRIES` | consts | Live server addresses: do not change casually. |

## Data and state
QSettings `server/last_username` (written on successful sign-in). The connection log is in-memory (and `logging` DEBUG).

## How to change it safely
- Signals from `_LoginThread` must connect to bound dialog methods (lambdas would run on the login thread).
- Worst case with the server down: ~2 URLs × 3 attempts × (5 s TCP) + delays.
- Error copy follows Harbor "Words": say what happened and what to do.

## Map
- 1-50 docstring, imports, constants, messages; 53-72 TCP helpers
- 75-166 `_LoginThread`; 169-314 `ConnectionDialog`
