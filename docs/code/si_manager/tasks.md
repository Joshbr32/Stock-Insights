# si_manager/tasks.py
**Purpose:** The Tasks page's jobs (what each does, the exact command) and how they start: elevated ones in their own PowerShell window through Windows' "Run as administrator" prompt, so the manager never runs elevated.
**Used by:** `window.py`, `pages.TasksPage`, `tests/test_controller.py`.  **Depends on:** `si_controller.config` (`REPO_ROOT`, `logs_dir`); stdlib (`ctypes` ShellExecuteW, `subprocess`). No Qt.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `Task` | dataclass | `key, title, description, command, elevated, missing` (`missing` = why it can't run here). |
| `build_tasks(sql_service, home)` | func | `migrate` (`sqlcmd -S <server> -d StockInsights -E -b -I -i "...\001_tags_trade_uid.sql"`, elevated), `logs` (Explorer on `<home>\logs`), `install` / `uninstall` (the two autostart scripts, elevated). |
| `sql_server_name(service)` | func | `MSSQL$X` -> `localhost\X`; `MSSQLSERVER` -> `localhost`. |
| `powershell_args(task)` | func | `-NoProfile -ExecutionPolicy Bypass -EncodedCommand <base64 UTF-16>` of a script that echoes the command, runs it, says "Finished." or "It stopped with an error (see above).", and waits for Enter. Encoding avoids every quoting problem with paths. |
| `run(task)` | func | Never blocks; returns a sentence ("Started … in an administrator window." / "Windows did not start … (administrator permission was not given, code 5)."). |

## How to change it safely
A new task: add it to `build_tasks` (shown in that order) and, if elevated, nothing else. The migration uses `-I` because the file's filtered indexes need QUOTED_IDENTIFIER ON (see its header). Test: `test_manager_tasks_commands`.

## Map
- 1-33 docstring, paths, `Task`
- 35-74 `sql_server_name`, `_ps_quote`, `build_tasks`
- 76-99 `_script_for`, `powershell_args`
- 101-end `run`
