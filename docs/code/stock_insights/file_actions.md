# stock_insights/file_actions.py
**Purpose:** File menu actions (Export CSV, Back up data, Restore from backup) with their file pickers and user-facing messages. Data work is in `io_utils.py`.
**Used by:** main_window (`_on_export_csv`, `_on_backup`, `_on_restore`).  **Depends on:** `io_utils` (export_trades_to_csv, write_backup, read_backup, validate_backup), `widgets.confirm`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `default_export_dir()` | func | `~/Documents` if it exists, else `~`. |
| `export_csv(parent, trades)` | func | Save dialog → CSV → result box. OSError shown with a fix. |
| `back_up(parent, store)` | func | Save dialog → `write_backup` (reads the store; may hit network) → result box. |
| `choose_restore(parent) -> dict or None` | func | Read-only: pick file, `read_backup`, `validate_backup` (errors listed in "Show details"), destructive confirm. Returns the snapshot to apply. |
| `show_restore_result(parent, result)` / `show_restore_failed(parent, msg)` | funcs | Messages after the caller's background `apply_backup`. |

## Data and state
No state. Backups are JSON (schema in io_utils); auto-backups live in `~/.stock_insights/auto_backups`.

## How to change it safely
- Keep validation before any write: a bad file must never half-restore.
- The destructive apply is deliberately not here (caller runs it in the background and writes the pre-restore snapshot first).

## Map
- 1-27 docstring/imports; 29-37 helpers; 39-60 export; 62-83 backup; 86-132 choose_restore; 135-148 result messages
