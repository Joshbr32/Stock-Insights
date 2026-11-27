# server/install_autostart.ps1 (and uninstall_autostart.ps1)
**Purpose:** One-time, elevated, idempotent setup that makes the sync server and its SQL Server start with the PC: SQL Server service to Automatic, a controller folder with locked-down permissions, `controller.json`, and the scheduled task "StockInsights Controller" that runs `python -m si_controller run`. The uninstaller reverses exactly what the installer recorded.
**Used by:** the owner (elevated PowerShell), the manager's Tasks page ("Turn on autostart" / "Turn off autostart").  **Depends on:** Windows PowerShell 5.1 ScheduledTasks module, `icacls`, `Get-NetTCPConnection`; the server's Python (must import fastapi, uvicorn, pyodbc); `si_controller`.

## Parameters (install)
| Name | Default | Meaning |
|---|---|---|
| `-Account` | `CurrentUser` | `CurrentUser` = the installing account through an S4U logon (no password stored; same Python, packages and file access as running server.py by hand). `System` = LocalSystem; refused when the server's packages live in the user's `pip --user` folder. |
| `-PythonExe` | first of `server\.venv`, `.venv`, `python` on PATH that imports the server's packages | The server's Python (also runs the controller). WindowsApps stubs are skipped. |
| `-SqlService` | `MSSQL$STOCKINSIGHTS`, else the one `MSSQL$*STOCKINSIGHTS*`, else the only SQL service | Fails with the list when ambiguous. |
| `-TunnelService`, `-Port`, `-ApiPort`, `-DataRoot` | `cloudflared`, 8742, 8746, `%ProgramData%\StockInsights\controller` | Ports 8740-8745 (Colonial) are refused. |
| `-NoStart` | off | Register but do not start the task now. |

## What it does (each step says what it did or skipped)
1. Checks `server\server.py` and that `server\.env` exists (never opens it); picks the Python.
2. Sets the SQL service to Automatic and starts it; SQL Server Browser only if the instance's shared-memory protocol is off (registry `...\SuperSocketNetLib\Sm\Enabled`).
3. Creates the controller folder; ACL: SYSTEM and Administrators full, the installing user Modify, inheritance removed.
4. Writes/merges `controller.json` (`python_exe, server_dir, port, api_port, autostart, sql_service, tunnel_service, wait_for_sql`; other keys such as `policy` are kept). Warns if 8742 is already listening (a server window).
5. Registers the task (`-Force`, so re-running updates it): triggers At startup + every 5 minutes from today (indefinitely; does nothing while running because of `MultipleInstances IgnoreNew`), no time limit (`PT0S`), restart every minute on failure (999 times), start when available, on batteries too. A running task is stopped first when updating.
6. Starts the task and waits up to 30 s for `python -m si_controller status` to answer, printing the status.

## Data and state
`<DataRoot>\install_state.json`: `sql_service`, `sql_service_previous_start`, `browser_previous_start`, `created_data_root`, `task_name`. Previous start types are recorded only the first time, so a re-run never forgets the original.

## Uninstall
`uninstall_autostart.ps1 [-RemoveData]`: stops and unregisters the task (the server stops with the controller), restores the recorded start types only if they are still Automatic (services keep running), removes `install_state.json`; deletes the folder only with `-RemoveData` and only if the installer created it. Exits quietly when there is no state file.

## How to change it safely
- Never run them on a development PC; syntax-check instead: `powershell -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile('server\install_autostart.ps1',[ref]$null,[ref]$e); $e"`.
- Native programs are called through `Invoke-Native` (Windows PowerShell 5.1 turns their stderr into terminating errors under `ErrorActionPreference=Stop`).
- Anything new the installer changes must be recorded in `install_state.json` and reversed in the uninstaller.

## Map (install_autostart.ps1)
- 1-52 help
- 54-103 parameters, helpers, elevation and port checks, state file
- 104-134 step 1 Python
- 135-192 step 2 SQL Server (+ Browser)
- 193-209 step 3 folder and ACL
- 210-236 step 4 controller.json, port warnings
- 237-266 step 5 scheduled task
- 267-end step 6 start, summary
