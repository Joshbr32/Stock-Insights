# si_controller/cli.py (and __main__.py)
**Purpose:** `python -m si_controller run|status|start|stop|restart|logs|events [--limit N]`. `run` is the controller itself; the other commands are API clients.
**Used by:** the scheduled task (`run`), the installer (`status`, to wait for it), the owner.  **Depends on:** `client`, `config`, `words`, `controller` (imported only for `run`).

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `main(argv)` | func | Exit 0, or 1 with the `ControllerError` sentence on stderr. |
| `_run()` | func | Logs to `<home>\logs\controller.log` (1 MB x 3) and stderr; SIGINT, SIGTERM and SIGBREAK call `Controller.shutdown()`. |
| `_print_status(data)` | func | The verdict sentence, then state, uptime, restarts, version, database, schema, last exit, services, disk. |

`__main__.py` only calls `sys.exit(main())`.

## How to change it safely
`install_autostart.ps1` treats exit code 0 from `status` as "the controller answers"; keep that.

## Map
- 1-40 docstring, `_run`
- 42-72 `_print_status`
- 74-end `main`
