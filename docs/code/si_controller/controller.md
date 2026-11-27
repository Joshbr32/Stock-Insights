# si_controller/controller.py
**Purpose:** The controller process: builds the logs and the `Supervisor`, starts the API, autostarts the server, ticks until `shutdown()`, then stops the server gracefully.
**Used by:** `cli._run` (`python -m si_controller run`, which the scheduled task runs), tests, the screenshot harness.  **Depends on:** `api`, `config`, `logs`, `supervisor`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `Controller(cfg, root, tick_interval=0.5, **supervisor_kwargs)` | class | Logs under `<root>\logs`. Extra kwargs go to `Supervisor` (fakes in tests). |
| `.run()` | method | Blocking. Returns 2 (event `api_failed`) when the API port is taken, i.e. a second controller; else 0 after shutdown. Records `controller_started`, then `supervisor.start("autostart")` when `cfg.autostart`. An exception in a tick is logged, never fatal. |
| `.shutdown()` | method | Thread-safe. `run()` then stops the server (up to `stop_grace + 12` s), the API and the logs. |
| `.status()` | method | The `/status` JSON (see `api.md`). |
| `.wake()` | method | Run the next tick now (after a command). |

## How to change it safely
If the controller is killed rather than shut down, the job object ends the server; there is no other cleanup path, so keep it that way. `run()` must not block on anything but the tick wait.

## Map
- 1-25 docstring, imports
- 27-42 init
- 44-67 `status`, `wake`, `start_api`
- 69-end `run`, `shutdown`, cleanup
