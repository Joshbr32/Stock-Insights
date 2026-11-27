# Server PC runbook: Stock Insights server autostart and the Server Manager

How the Stock Insights sync server starts by itself when the server PC starts, and how to
watch and manage it. Code: `si_controller/` (the controller), `si_manager/` (the window),
`server/install_autostart.ps1` and `server/uninstall_autostart.ps1`.

## What runs

```
Windows starts
  ├── SQL Server service MSSQL$STOCKINSIGHTS            (Automatic)
  ├── cloudflared service (Cloudflare tunnel)            (already installed, unchanged)
  └── Task Scheduler task "StockInsights Controller"     (at startup, and every 5 min if not running)
        python -m si_controller run                       controller, standard library only
          │  waits for SQL Server, then starts and watches:
          └── python server/server.py --port 8742         the sync server (inside a job object)
          management API on 127.0.0.1:8746  ◄── python -m si_controller status | Server Manager
```

- The controller restarts the server when it exits or stops answering `/health`
  (after 2, 5, 15, 30, 60 s). After 5 failures in 10 minutes it stops trying and the
  Manager shows **Failed**; press Start once the cause is fixed.
- A server whose database is down keeps running (restarting it would not help); the
  Manager says so on the Dashboard.
- If the controller is ended, Windows ends the server with it (job object), so nothing
  is left holding port 8742. The 5-minute trigger starts the controller again.
- Stop and Restart are graceful: the server finishes requests in flight and shuts down;
  only if it hangs for 20 s is it ended by force.

### Living next to the Colonial controller

The Colonial controller runs on the same PC and is not touched by any of this:

| | Colonial | Stock Insights |
|---|---|---|
| What starts it | Windows service `ColonialController` | Scheduled task `StockInsights Controller` |
| Management API | 127.0.0.1:8740 | 127.0.0.1:8746 |
| Servers | 8744 (production) | 8742 |
| Folder | `C:\ProgramData\Colonial` | `C:\ProgramData\StockInsights\controller` |
| SQL Server | `MSSQL$COLONIALSERVER` | `MSSQL$STOCKINSIGHTS` |

The installer refuses ports 8740-8745 for Stock Insights.

## Which account runs it, and why

The default is **your own Windows account, without a stored password** (Task Scheduler's
"S4U" logon, `-Account CurrentUser`). It runs whether or not you are signed in.

- The server signs in to SQL Server with the SQL login in `server\.env`
  (`PORTFOLIO_SQL_USER` / `PORTFOLIO_SQL_PASSWORD`), so it needs no Windows network
  credentials, which S4U does not have.
- It reads `server\.env` and runs the Python you run the server with today, with the
  same packages. Packages installed with `pip install --user` live in your profile and
  only your account sees them; that is why SYSTEM is not the default.
- `-Account System` is available; the installer refuses it when the server's packages
  are in your user folder.

Whoever can read `C:\ProgramData\StockInsights\controller\token` can start and stop the
server. The folder is readable only by you, SYSTEM and Administrators.

## First-time setup (once, on the server PC)

1. Close any PowerShell window where `python server.py` is running (the controller will
   start the server itself; while port 8742 is taken it only waits).
2. Make sure `server\.env` exists and the server starts by hand:
   `python server\server.py` → it prints "Listening : http://0.0.0.0:8742". Stop it
   with Ctrl+C.
3. Open **PowerShell as administrator** (right-click > Run as administrator), then:

   ```powershell
   cd C:\Users\Josh\StudioProjects\Stock-Insights
   powershell -NoProfile -ExecutionPolicy Bypass -File server\install_autostart.ps1
   ```

   It prints each step and ends with "Done. What changed:" and the controller's status
   ("The server is running and healthy."). It is safe to run again.
4. Open the Manager: double-click `si_manager\StockInsightsServerManager.bat` (or
   `.\.venv\Scripts\python.exe -m si_manager`). Right-click the .bat > Send to > Desktop
   for a shortcut.
5. Restart the PC once and check the Manager says "The server is running and healthy."
   without you starting anything.

If the schema needs updating (the Dashboard's Database panel says so), use
**Tasks > Update the database schema** (administrator window, `sqlcmd ... -E -b -I -i
server\migrations\001_tags_trade_uid.sql`, as your Windows sign-in). Take a backup first,
then press Restart.

## Every day

| I want to | Do |
|---|---|
| See whether it is up | Manager top line, or `python -m si_controller status` |
| Restart after pulling new server code | Manager > Restart (or `python -m si_controller restart`) |
| Stop it for maintenance | Manager > Stop… (it stays stopped until Start or the next PC start) |
| See what it printed | Manager > Server output (find, pause, copy), or `logs\server.log` |
| See why it restarted | Manager > Events, or `python -m si_controller events` |
| Open the logs | Manager > Tasks > Open the logs folder |

All commands run from the repository folder in an ordinary (not elevated) PowerShell.
Closing the Manager changes nothing.

## Files

`C:\ProgramData\StockInsights\controller\`

| File | What |
|---|---|
| `controller.json` | Python, server folder, ports, SQL and tunnel service names, `policy` timings (optional) |
| `token` | API token (created at the first start; delete it and restart the task to change it) |
| `install_state.json` | What the installer changed, for the uninstaller |
| `logs\server.log` (+ `.1`-`.5`) | Server output, 5 MB each, secrets replaced with `[redacted]` |
| `logs\events.jsonl` | Controller events, one per line, with a sentence each |
| `logs\controller.log` | The controller's own problems |

## When something is wrong

| The Manager says | Do |
|---|---|
| "No answer from the controller since …" | Task Scheduler > StockInsights Controller > Last Run Result; `logs\controller.log`. Run it by hand to see errors: `python -m si_controller run` (Ctrl+C stops it and the server). |
| "The server is waiting to start: port 8742 is already in use …" | A `server.py` window is open, or something else took the port: `Get-NetTCPConnection -LocalPort 8742 -State Listen` shows the process. |
| "… waiting to start: SQL Server (MSSQL$STOCKINSIGHTS) is stopped." | `Start-Service 'MSSQL$STOCKINSIGHTS'` (administrator) and check its start type is Automatic. |
| **Failed** / "kept failing" | Server output shows why (often `.env` or the database). Fix it, then Start. |
| Running, but "can't reach the database" | SQL Server or the login in `.env`; the server keeps running and recovers by itself when the database is back. |
| Cloudflare tunnel stopped | `Start-Service cloudflared` (administrator). The LAN still works on :8742. |

## Undo

```powershell
# administrator PowerShell, repository folder
powershell -NoProfile -ExecutionPolicy Bypass -File server\uninstall_autostart.ps1
```

Removes the task (the server stops), puts SQL Server's start type back to what it was
before (it keeps running for now), keeps the logs. Add `-RemoveData` to delete the
controller folder too. Then `python server\server.py` runs it by hand as before.
