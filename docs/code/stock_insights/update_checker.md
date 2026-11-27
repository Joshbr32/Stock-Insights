# stock_insights/update_checker.py
**Purpose:** "Check for Updates" menu feature: fetch a JSON manifest on a QThread, compare versions, show a dialog.
**Used by:** `main_window.py::_check_for_updates` (lazy import).  **Depends on:** PySide6, `version.py` (`APP_VERSION`, `UPDATE_MANIFEST_URL`), stdlib urllib/json/webbrowser.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `check_for_updates(parent=None, silent_if_current=False)` | func | Public entry; GUI thread only. Shows a "checking" dialog, runs `_UpdateWorker` on a QThread, then `_on_result`. |
| `_UpdateWorker.run` | method | Worker thread. GET manifest with 8 s timeout, max 64 KB read, must be a JSON object. Emits `finished(dict)`; failures become `{"error": str}` (only OSError/ValueError/URLError are caught). |
| `_parse_version` / `_newer` | funcs | "v1.2.3" -> (1,2,3), non-numeric parts = 0; tuple comparison. |
| `_on_result` | func | Closes checking dialog, quits thread, shows error / update-available / up-to-date dialog. |
| `_UpdateAvailableDialog` | class | Notes are rendered as PLAIN TEXT (remote data); download URL opened only if it starts with http(s). |

## Data and state
None persisted. Manifest shape: `{"version","notes","download_url"}`; URL in `version.UPDATE_MANIFEST_URL`.

## How to change it safely
- Dialogs are modal `.exec()`; do not call from a non-GUI thread.
- The `_worker` arg of `_on_result` keeps the worker alive via the lambda closure; do not remove it.
- Needs Qt, so not covered by `tests/`. `_newer` is pure and easy to unit test.

## Map
Constants/version helpers 31-60; worker 64-85; entry 90-114; `_on_result` 117-148; dialogs 152-end.
