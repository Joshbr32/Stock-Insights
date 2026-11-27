# scripts/ui_snapshot_dialogs.py
**Purpose:** Render every QWidget dialog/window (and the main window's menu bar + status corner) to PNG in chosen themes and modes, for visual review without running the real app.
**Used by:** developers / agents (`python scripts/ui_snapshot_dialogs.py --out <dir> [--themes Default,Forest|all] [--modes light,dark] [--only a,b] [--list]`).  **Depends on:** all desktop UI modules, `theme.ThemeManager`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `FakeStore` | DataStore | In-memory fixture data (2 portfolios, long/short/pending trades, watchlist, users). |
| `scene_*` | funcs | One per screen; `SCENES` maps name → builder. Add a `scene_<name>(host)` to add a shot. |
| `build_main_window()` | func | MainWindow with timers, launch snapshot and logging disabled. |
| `main()` | func | Applies each theme/mode, grabs each widget to `<out>/<Theme>-<mode>/<name>.png`. Exit 1 if any scene failed. |

## Data and state
Writes PNGs only. QSettings is redirected to a temp INI under organisation `StockInsightsUISnapshot` (deleted at exit).

## How to change it safely
- The network block (`socket.create_connection` / `socket.connect` raise) and the QSettings patch must stay **above** the first `stock_insights` import.
- Never let a scene start MarksWorker / NetCheckWorker or write auto-backups.
- Widgets render with `WA_DontShowOnScreen`, so nothing flashes on screen.

## Map
- 1-80 docstring, network block, QSettings sandbox, imports
- 83-190 fixtures + FakeStore; 193-345 scenes; 348-375 main-window builder; 378-450 runner
