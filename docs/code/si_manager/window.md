# si_manager/window.py
**Purpose:** The manager's main window: side menu, verdict bar, the four pages, status bar; polls the controller off the UI thread and carries out Start / Restart / Stop and Tasks.
**Used by:** `si_manager/__main__.py`, the screenshot harness.  **Depends on:** `si_controller.client` (`ControllerError`), `si_controller.words.verdict`, `pages`, `tasks`, `widgets`, `theme`; PySide6.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `Background.run(key, fn, on_done, on_failed)` | method | Runs `fn` on a 3-thread `QThreadPool`; results return on the UI thread via signals. A key still in flight is skipped (no pile-up when the controller is slow). |
| `NavList` | class | Side menu; sets the `focused` property so the selected entry shows the focus ring. |
| `MainWindow(client, poll=True)` | class | `client` is an `si_controller.client.Client` (or a fake with the same methods and `.root`). `poll=False` for tests/screenshots driven by hand. |
| `.poll_status / poll_logs / poll_events / poll_all` | methods | Every 2 s / 1.5 s / 5 s; F5 = all. Logs are fetched incrementally (`since` = last seq; reset when the controller restarts). |
| `.apply_status(status, error=None)` | method | None = no answer: the verdict says "No answer from the controller since HH:MM:SS, …" and the status bar's right side turns red with the same sentence. |
| `.request_action(action)` | method | Stop asks first (destructive button "Stop server", default "Keep running"). |
| `.run_task(task)` | method | `tasks.run()`, result sentence on the Tasks card and status bar. |

## Data and state
Nothing on disk. Closing the window stops the timers only; the controller and server are untouched.

## How to change it safely
No network or disk calls in slots: always through `self.bg.run`. Keyboard: Ctrl+1..4 switch pages, F5 refreshes, Ctrl+F finds in the output.

## Map
- 1-80 docstring, `_Signals`, `_Job`, `Background`
- 81-106 `app_icon`, `NavList`
- 108-196 `MainWindow.__init__` (layout, shortcuts, timers)
- 198-263 polling and `apply_*`
- 265-end actions, tasks, close
