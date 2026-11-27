# tests/test_controller.py
**Purpose:** Tests for `si_controller` with real child processes: a 30-line fake `server.py` (written to `tmp_path`) serves `/health` on its `--port` and exits, crashes or hangs on demand. Also the API's access rules, redaction, configuration, the shared wording and the manager's task commands.
**Used by:** `./.venv/Scripts/python.exe -m pytest tests -q` (this file about 20 s).  **Depends on:** `si_controller`, `si_manager.tasks` (no Qt).

## Key fixtures and tests
| Name | What it checks |
|---|---|
| `rig` fixture | Starts a `Controller` on a thread with a temp home, free ports, `wait_for_sql=False` and the fast `FAST` policy; returns `(controller, client)`; shuts every controller down and asserts it stopped. Accepts `Config` overrides (`port=`, `autostart=`). |
| `test_start_health_status_and_output` | running, health data, verdict, output captured and redacted, own health checks filtered, `since`, events, `server.log` on disk. |
| `test_crash_restarts_with_backoff` | `/exit?code=3` -> event `exited` with code and delay, new pid, `restarts == 1`. |
| `test_crash_loop_gives_up` | `FAKE_MODE=crash` -> `failed` after 3, stays stopped, stderr password redacted. |
| `test_graceful_stop_then_start_and_restart` | stop exits 0 through the launcher (no kill), who is recorded, requested restart is not a failure. |
| `test_hung_server_is_restarted` | `/hang` -> event `hung` -> new process. |
| `test_waits_while_port_is_taken` | `waiting` with a reason until the port frees. |
| `test_api_requires_token_loopback_host_and_no_origin` | 401 without/with wrong token, with `Origin`, with a foreign `Host`; 404. |
| `test_second_controller_cannot_take_the_api_port` | second `run()` returns 2, event `api_failed`. |
| others | unreachable client message, redaction cases, config defaults/partial/broken file, task commands, `words`. |

## How to change it safely
Never point it at the real home, ports 8742/8746, SQL Server or services: the server PC runs the real ones. Keep timings short (the `FAST` policy) so the file stays near 20 s.

## Map
- 1-60 docstring, fake server, `FAST`
- 62-134 helpers, `rig`
- 136-231 supervisor tests
- 233-266 API tests
- 268-end helpers' tests
