# si_controller/logs.py
**Purpose:** The controller's two records: `OutputLog` (server stdout/stderr lines in memory with sequence numbers, plus a rotating `server.log`) and `EventLog` (controller events as JSON lines, each with a sentence).
**Used by:** `controller.py`, `supervisor.py`, `api.py` (`/logs`, `/events`).  **Depends on:** stdlib only.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `now_iso()` | func | Local time with offset, to the second (`2026-11-26T14:03:22-05:00`). |
| `_RotatingFile(path, max_bytes, backups)` | class | Append and flush per write; rolls over to `.1 … .N`. Not locked itself (callers lock). |
| `OutputLog.add(stream, text)` | method | `stream` is `stdout` or `stderr`; text must already be redacted. File errors are swallowed (a full disk must not block the pipe reader). |
| `OutputLog.since(after, limit)` | method | `{lines: [{seq, at, stream, text}], latest, gap}`: lines with `seq > after`, the newest `limit`; `gap` when lines the caller never saw were dropped. |
| `OutputLog.tail(n)` | method | Last n texts (attached to exit events as `console`). |
| `EventLog.record(kind, message, **fields)` | method | Appends `{at, kind, message, ...fields}`; None fields are left out. |
| `EventLog.recent(limit)` | method | Newest last, at most 1000. History is reloaded from the file at start-up. |

## Data and state
`<home>\logs\server.log` (`<iso> <stream> <text>`, 5 MB x 5 files) and `<home>\logs\events.jsonl` (2 MB x 3). In memory: the last 5000 lines and 1000 events. Sequence numbers start again at 1 when the controller restarts (the manager notices `latest` going backwards).

## How to change it safely
Keep the `since()` / `recent()` shapes: they are the `/logs` and `/events` JSON. One lock per log.

## Map
- 1-28 docstring, `now_iso`
- 30-70 `_RotatingFile`
- 72-112 `OutputLog`
- 114-end `EventLog`
