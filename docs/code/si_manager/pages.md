# si_manager/pages.py
**Purpose:** The four pages. They only display what the window gives them and emit what the user asked for.
**Used by:** `window.py`.  **Depends on:** `si_controller.words`, `theme`, `tasks.Task`, `widgets`; PySide6.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `clock(iso, with_day)` | func | `14:03:22`, or `26 Nov 14:03` for another day. |
| `DashboardPage` | class | Signal `action(str)` ("start"/"restart"/"stop"). `update_status(status or None)` fills: the state mark + word, the reason line, facts (up for, server version, automatic restarts, last health check, memory, processor, process, port), Database (reachable from `db_ok`/`db_error`; schema from `/health` `schema` = `ok`/`needs_migration`, or `schema_version`/`schema_expected` if a server sends those), This PC (SQL Server, Cloudflare tunnel, disk with a warning under 10 GB, controller). `set_recent(events)` shows the last 4 events. Buttons are enabled only where they make sense. |
| `OutputPage` | class | `append(entries, gap)`; find (Enter next, Shift+Enter previous, all matches highlighted, count), Pause (buffers, says how many lines wait), Wrap long lines, Copy all. 5000 lines kept. Each line is `HH:MM:SS  <mark>  text`: mark `✕` for errors (also red; tracebacks are followed to their last line), `!` for warnings (amber band), blank otherwise. |
| `_OutputHighlighter` | class | Colours by the mark at column 10; keep `format_line` and it in step. |
| `EVENT_LOOK` | dict | Event `kind` -> (tone, word) for the Events table and the dashboard list. Add new controller event kinds here. |
| `EventsPage.set_events(events)` | method | Newest first; icon + word, when, the controller's own sentence. |
| `TasksPage` | class | Signal `run(Task)`. `set_tasks(tasks)` builds one panel per task: description, the exact command (wrapped, selectable), Run…/Open, Copy command, why it can't run or that Windows will ask for administrator rights. `show_result(task, sentence)`. "Turn off autostart" is outlined red. |

## How to change it safely
State is never colour alone: always a shape (`widgets.Mark`) and a word or sentence. Words follow the design system: sentence case, the result reuses the verb.

## Map
- 1-35 imports, `clock`
- 37-228 `DashboardPage`
- 230-401 server output: patterns, highlighter, `OutputPage`
- 403-460 `EVENT_LOOK`, `EventsPage`
- 462-end `TasksPage`
