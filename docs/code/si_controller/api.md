# si_controller/api.py
**Purpose:** The loopback management API (default 127.0.0.1:8746) used by the CLI and the manager.
**Used by:** `controller.Controller.start_api`.  **Depends on:** stdlib `http.server`; the controller object (`status()`, `output`, `events`, `supervisor`, `wake()`).

## Routes (JSON; every request needs `Authorization: Bearer <token>`)
| Route | Response |
|---|---|
| GET /status | `{controller: {version, pid, started_at, uptime_seconds, api_port, home, server_dir}, server: Supervisor.status(), machine: {sql, tunnel, disk}, time}` |
| POST /start, /stop, /restart | `{ok: true, state}`; the `X-Windows-User` header is recorded as who asked |
| GET /logs?since=SEQ&limit=N | `OutputLog.since()` (limit 1-5000) |
| GET /events?limit=N | `{events: [...]}`, newest last (1-1000) |

Errors: 401 `{error: "not authorised"}`, 404 `{error: "no such route"}`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `make_server(controller, port, token_reader)` | func | Binds (raises `OSError` if the port is taken) and returns the server; the caller runs `serve_forever` on a thread. The token is re-read per request and compared in constant time. |
| `_LoopbackServer` | class | `SO_EXCLUSIVEADDRUSE` and no `SO_REUSEADDR` (on Windows that would let a second controller share the port). Daemon threads. |

## Security rules (keep them)
Loopback bind only; `Host` must be `127.0.0.1:<port>` or `localhost:<port>`; any `Origin` header is refused, so a web page open on this PC cannot drive it. No route reveals the token, `.env` or settings.

## How to change it safely
A new route needs a branch here, a `Client` method and a test in `tests/test_controller.py`. Keep the existing shapes: the manager reads them.

## Map
- 1-24 docstring, imports
- 26-44 `_int`, `_LoopbackServer`
- 46-end `make_server` and its handler
