# stock_insights/io_utils.py
**Purpose:** CSV export of trades, the full JSON backup (build/write/read/validate/apply), and best-effort auto-snapshots before destructive operations and at launch.
**Used by:** `main_window.py` (`_on_export_csv`, `_on_backup`, `_on_restore`, `_write_launch_snapshot`), `tests/test_io_utils.py`. `pwa/js/app.js` re-implements the same backup format and validation.  **Depends on:** `portfolio` (`Trade`, `trade_to_dict`, `trades_from_json`), `logging_utils`, and any DataStore (`api_client`) through duck typing.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `_atomic_write(path, newline)` | ctx manager | Writes a UTF-8 temp file (`.<name>.*.tmp`) in the same folder, fsyncs it, then `os.replace`s it over the destination. On an error the temp file is removed and the original is left untouched. Creates parent dirs. |
| `CSV_COLUMNS`, `export_trades_to_csv(trades, path)` | const, fn | One row per trade; prices to 2 dp; days_held in calendar days. UTF-8 without BOM, `newline=""`. Returns the row count. Atomic. |
| `BACKUP_SCHEMA_VERSION` | const | 1. Also hard-coded in app.js. |
| `build_backup(store)` | fn | Snapshot dict: schema_version, exported_at (UTC ISO), username, accounts, goal_targets, goal_presets, goal_group, watchlist, trades. Each store read falls back to a default on error. |
| `write_backup(store, path)` | fn | Serialises first, then writes atomically. Returns the path. |
| `write_auto_snapshot(store, kind)` | fn | Writes `~/.stock_insights/auto_backups/<kind>-YYYYmmdd-HHMMSS.json`, then prunes. Returns the path, or None on any failure (logged as a warning). Must never raise. |
| `_prune_auto_snapshots(folder, keep)` | fn | Keeps the `keep` newest `*.json` by mtime, across all kinds. |
| `read_backup(path)` | fn | Parses the file and checks schema_version. Raises ValueError (including JSON and Unicode errors, or a non-numeric version). |
| `validate_backup(snapshot)` | fn | Returns a list of error strings; empty means safe. Read-only. |
| `apply_backup(store, snapshot)` | fn | Overwrites store data and returns `{accounts, trades, watchlist}` counts. Per-step store errors are swallowed. Trades with no account go to the first account, or "Default". |

## Data and state
- User-chosen CSV and backup paths (from a file dialog in main_window).
- `~/.stock_insights/auto_backups/*.json`: the newest 5 (`AUTO_BACKUP_KEEP`) are kept.
- Each trade in a backup carries `uid` and `tag` (from `trade_to_dict`). Backups made before uids existed restore fine: a uid is generated per trade. `BACKUP_SCHEMA_VERSION` stays 1 (the field is optional). Restore uses the bulk `save_account_trades`, not per-trade saves.
- The backup JSON format is shared with the PWA (`app.js` around lines 1216 and 1322). Keep the two in step.

## How to change it safely
- Any change to the backup format needs a matching change in `pwa/js/app.js`, and probably a new `BACKUP_SCHEMA_VERSION` with a migration path, because restore rejects any other version.
- Keep `write_auto_snapshot` non-raising: callers run it right before destructive operations.
- `apply_backup` is not transactional. Callers must run `validate_backup` first (main_window does).
- Verify with `./.venv/Scripts/python.exe -m pytest tests/test_io_utils.py -q`.

## Map
- 1-26 docstring, imports, logger
- 29-53 `_atomic_write`
- 55-108 CSV export
- 111-185 backup build/write
- 187-253 auto-snapshots + pruning
- 256-273 `read_backup`
- 276-372 `validate_backup`
- 375-447 `apply_backup`
