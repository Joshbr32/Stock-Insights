# stock_insights/workers.py
**Purpose:** Single-use `QObject` workers that MainWindow moves onto a `QThread` to keep blocking work (HTTP, price fetches) off the GUI thread.
**Used by:** `main_window.py` (all four), `admin_dialogs.py` (`MarksWorker`).  **Depends on:** `PySide6.QtCore`, `data.fetch_marks`, `logging_utils`, and (duck-typed) `FallbackDataStore.attempt_reconnect`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `StoreCallWorker(fn, args=(), kwargs=None, label="store-call")` | QObject | `run()` calls `fn`; emits `done(object)` with the result or `error(str)`. Driven by `MainWindow._run_in_background`. |
| `MarksWorker(tickers)` | QObject | `run()` calls `fetch_marks`; emits `done(dict)` or `error(str)`. Copies the ticker list. |
| `NetCheckWorker()` | QObject | `run()` probes `TEST_URLS` in order (3 s each, about 12 s worst case offline); emits `done(bool)`. Stops between probes if `QThread.requestInterruption()` was called. |
| `ReconnectWorker(store)` | QObject | `run()` calls `store.attempt_reconnect()`; emits `done(bool)`, `True` when the server is back and the sync queue is empty. |

## Data and state
None persisted. Each worker holds only its constructor arguments.

## How to change it safely
- `run()` executes on the worker thread: no widget access, results only through signals.
- Emit exactly one result signal on every path. The owner connects it to `thread.quit` and cleanup; a path that emits nothing leaves a thread running.
- Signal names and signatures (`done`, `error`) are wired in `main_window.py` and `admin_dialogs.py`.
- Lifecycle is owned by the caller: `worker.moveToThread(thread)`, `thread.started -> worker.run`, `done -> thread.quit`, `thread.finished -> deleteLater`. Keep a Python reference to both until `finished`.
- `run()` cannot be cancelled mid-call; shutdown code must `wait()` for it or accept the timeout.

## Map
- 1-25 docstring, imports
- 28-62 `StoreCallWorker`
- 65-84 `MarksWorker`
- 87-125 `NetCheckWorker`
- 128-146 `ReconnectWorker`
