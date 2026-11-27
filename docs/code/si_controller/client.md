# si_controller/client.py
**Purpose:** The management API from the caller's side (CLI and manager): reads the token on every call, talks to 127.0.0.1 only, never through a proxy.
**Used by:** `cli.py`, `si_manager/__main__.py`, `si_manager/window.py`, tests.  **Depends on:** `config` (home, port, token); stdlib `urllib`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `ControllerError(message, status)` | exception | A sentence for people; `status` is the HTTP code when refused, None when unreachable. |
| `windows_user()` | func | `DOMAIN\user`, sent as `X-Windows-User`. |
| `Client(root=None, port=None, timeout=10)` | class | `root` defaults to `config.home()`, `port` to the config's `api_port`. Attributes `root`, `port`, `who`. |
| `.status()` (5 s timeout), `.command(action)`, `.logs(since, limit)`, `.events(limit)` | methods | Raise `ControllerError`; never return partial data. |

## How to change it safely
These calls block: the manager runs them on its thread pool only. Keep the messages full sentences (shown as they are in the status bar and the CLI).

## Map
- 1-30 docstring, error, `windows_user`
- 32-end `Client`
