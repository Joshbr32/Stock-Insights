# stock_insights/background.py
**Purpose:** QThread plumbing so blocking work (store writes, /health, password PUTs, price fetches) never runs on the GUI thread, and its results always come back on the GUI thread.
**Used by:** main_window, admin_dialogs.  **Depends on:** `workers.StoreCallWorker`, `logging_utils`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `BackgroundCalls(parent)` | QObject | `run(fn, args, kwargs, on_done, on_error, label)` starts a fresh QThread + StoreCallWorker; callbacks run on the GUI thread via `_Relay`. `active_count`; `shutdown(wait_ms)` drops callbacks, requests interruption, quits and waits each thread. |
| `SingleFlight(parent, name)` | QObject | At most one worker at a time. `start(worker, wire, on_finished) -> bool` (False if busy); `wire(worker)` connects result signals to bound QObject methods; thread quits on the worker's `done`/`error`. `is_running()`, `shutdown(wait_ms)`. |
| `_Relay` | QObject | Lives on the GUI thread; `@Slot` `done`/`error` call the Python callbacks and log (not raise) callback exceptions. |

## Data and state
Keeps `(thread, worker, relay)` references until `QThread.finished` (otherwise Python GC reaps them mid-run). Deletion is Qt's `finished → deleteLater`.

## How to change it safely
- Why the relay exists: in PySide6 6.12 a signal connected to a lambda/plain function runs it on the *emitting* (worker) thread; bound methods of QObjects are queued to the receiver's thread. Verified by experiment.
- `shutdown` cannot interrupt a request already in flight; it waits up to `wait_ms`, so keep store timeouts short.
- Workers that loop should check `QThread.currentThread().isInterruptionRequested()` (NetCheckWorker does).

## Map
- 1-25 docstring/imports; 28-52 `_Relay`; 55-113 `BackgroundCalls`; 116-183 `SingleFlight`
