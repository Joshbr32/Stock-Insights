# stock_insights/sync_queue.py
**Purpose:** Durable queue of writes made while the server was unreachable, replayed in order on reconnect.
**Used by:** `api_client.py` (`FallbackDataStore` only).  **Depends on:** `api_client.APIError` and `requests` (lazy imports inside `flush`), `portfolio.trades_from_json`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `enqueue(username, action, payload)` | function | Append a write. Drops the older queued write it fully replaces (see Merging). Atomic file save. |
| `queue_length(username=None)` / `is_empty(username=None)` | function | Count entries (all users when `None`). Reads the file on each call. |
| `clear(username=None)` | function | Remove one user's entries, or everything. |
| `flush(remote_store, username=None) -> (succeeded, failed)` | function | Replay oldest first against a `RemoteDataStore`. Removes each entry once the server confirms it. Runs on the reconnect thread; no lock is held during network calls. |
| `_replay(store, action, payload)` | function | Maps an action to the store call. Unknown action raises `ValueError`. |
| `_superseded_index(...)`, `_merge_key(...)` | functions | Merge rule used by `enqueue`. |
| `_write_json_list(path, entries)` | function | Temp file + fsync + `os.replace` (3 tries for Windows `PermissionError`). |
| `_record_rejected(entry, reason)` | function | Append a discarded entry to the rejected file (last 50 kept). |

## Data and state
- `~/.stockinsights_sync_queue.json`: JSON list of `{action, username, payload, timestamp}` (UTC ISO timestamp). Module constant `_QUEUE_FILE`; tests patch it.
- `~/.stockinsights_sync_queue.rejected.json`: discarded entries plus `rejected_at` and `reason`. Path derived from `_QUEUE_FILE`.
- `~/.stockinsights_sync_queue.json.corrupt`: an unreadable queue file is moved here instead of being overwritten.
- Actions and payloads: `save_trades {account_name, trades}`, `save_accounts {accounts}`, `set_goal_target {account_name, value}`, `set_goal_presets {account_name, presets}`, `set_goal_group {account_names, shared_goal, individual_goals, individual_presets}`, `save_watchlist {symbols}`.

## Behaviour to know
- **Merging:** a new per-account write (`save_trades`, `set_goal_target`, `set_goal_presets`) or `save_watchlist` replaces that user's latest same-key entry unless a structural write (`save_accounts`, `set_goal_group`) was queued in between. A structural write only replaces the entry directly before it.
- **Flush failures:** network error, 5xx, 401, 408/425/429 stop the flush and keep that entry and all later ones (strict order). Other 4xx and unreplayable entries are moved to the rejected file and the flush continues.
- **Idempotency:** every action is a full-replace PUT, so a repeat after a crash between "server confirmed" and "entry removed" is harmless.

## How to change it safely
- All load-modify-save goes through `_lock`. Do not hold it across `_replay`.
- Entries are matched by value when removed; keep `timestamp` in every entry.
- A new action needs a `_replay` branch and an entry in `_KNOWN_ACTIONS` (plus `_PER_ACCOUNT_ACTIONS` or `_STRUCTURAL_ACTIONS`), and it must be idempotent.
- Queue files written by older versions (with `indent=2`) load unchanged.
- Two running app instances are not coordinated (the lock is in-process only).
- No unit tests; see the smoke-test note in `api_client.md`.

## Map
- 1-58 docstring, constants, lock
- 60-198 persistence helpers, merge rule, rejected file
- 200-240 `queue_length`, `is_empty`, `enqueue`, `clear`
- 242-298 `flush`
- 301-330 `_replay`
