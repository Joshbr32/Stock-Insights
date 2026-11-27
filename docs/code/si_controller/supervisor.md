# si_controller/supervisor.py
**Purpose:** The state machine that starts `server/server.py`, health-checks it, restarts it with back-off, gives up after a crash loop and stops it gracefully; plus the real child process (`ServerProcess`) and the real checks (`http_health`, `port_in_use`, `machine_status`).
**Used by:** `controller.py` (one `Supervisor`), `api.py` (commands via `controller.supervisor`), `tests/test_controller.py`.  **Depends on:** `config.Config/Policy`, `logs.EventLog/OutputLog`, `redaction.redact_line`, `win` (job object, usage, service state); stdlib only.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `STOPPED … FAILED` | consts | `stopped, waiting, starting, running, stopping, backoff, failed`: the `state` strings in `/status` (the manager and `words.py` map them). |
| `Supervisor(cfg, events, output, spawn=, probe=, service_state=, port_check=, clock=)` | class | Everything external is injectable. Thread-safe (RLock); the probe runs outside the lock. |
| `.start/.stop/.restart(who)` | method | Only change `desired` (+ event `<action>_requested` with `who`). `start` on `failed`/`backoff` clears the crash history. `restart` of a running server = graceful stop then start (not counted as a failure). `who="controller"` records nothing (shutdown has its own event). |
| `.tick()` | method | Advance once; called every 0.5 s by the controller (0.05 s in tests). |
| `.status()` | method | Served as `server` in `GET /status`: state, desired, message, pid, port, started_at, uptime_seconds, restarts (automatic only), failures_in_window, retry_in_seconds, last_exit `{at, reason, code}`, last_command `{action, who, at}`, health `{alive, ok, detail, checked_at, data}` (`data` = the server's raw /health JSON, e.g. `server_version`, `db_ok`, `db_error`, `schema`), usage `{working_set_mb, private_mb, cpu_seconds, cpu_percent}`. |
| `.refresh_usage()` / `.wait_stopped(timeout)` | method | Memory/CPU re-read for `/status`; drive ticks until down (shutdown). |
| `ServerProcess(argv, cwd, output)` | class | Popen with stdin/stdout/stderr pipes, `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`, inside a kill-on-close `win.Job`. Two reader threads redact each line and drop the controller's own `/health` 200 lines from 127.0.0.1. `request_stop()` writes `stop` to stdin (see `launch/run_server.py`). |
| `http_health(port, timeout)` | func | `GET http://127.0.0.1:port/health`, no proxy. Any HTTP answer = alive; `ok` from the JSON. |
| `port_in_use(port)` | func | Exclusive bind test on 0.0.0.0 (instant; a connect test waits ~2 s on Windows). TIME_WAIT does not count. |
| `machine_status(cfg)` | func | `{sql: {name, state}, tunnel: {name, state}, disk: {path, free_gb, total_gb}}`. |

## Rules (Policy defaults are in `config.py`)
- Waits (state `waiting`) while `sql_service` is not running (unless it is `missing`/`unknown`: a remote or renamed SQL Server) or the port is taken (e.g. `server.py` open in a window); re-checks every 3 s / `port_wait`.
- `/health` every 1 s while starting, every `health_interval` (15 s) while running. No answer within `start_timeout` (90 s), or `unhealthy_after` (3) misses in a row: killed and counted as a failure. Only *alive* drives restarts; `ok=false` (database down) is reported, never restarted for.
- A failure waits `backoff[n-1]` (2, 5, 15, 30, 60 s). `crash_limit` (5) failures within `crash_window` (10 min): state `failed`, left stopped until someone presses Start.
- Stop: `stop` on stdin, kill after `stop_grace` (20 s) with event `killed`. CTRL_BREAK is deliberately not used: it needs a shared console, and sent to a group outside the caller's console Windows can deliver it to the caller.

## How to change it safely
- Event `kind` strings are read by `si_manager/pages.py` (`EVENT_LOOK`); `message` is the sentence people see. Add a new kind there too.
- Keep `status()` keys stable: `si_manager`, `words.verdict` and `cli._print_status` read them.
- Tests: `./.venv/Scripts/python.exe -m pytest tests/test_controller.py -q` (real child processes, about 20 s).

## Map
- 1-53 docstring, imports, states, `LAUNCHER`
- 55-73 `Health`, `Process` protocol
- 78-162 `ServerProcess`
- 164-204 `http_health`, `port_in_use`
- 209-288 `Supervisor` init and commands
- 290-330 `tick`
- 332-480 internals: wait, start, health, stop, crash/back-off, usage
- 482-515 `status`, `wait_stopped`
- 517-end `machine_status`
