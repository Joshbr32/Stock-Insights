# stock_insights/logging_utils.py
**Purpose:** App-wide logging: rotating file log plus an icon/colour console log.
**Used by:** `main_window.py` (`setup_logging`, `get_logger`, `serial_debug`).  **Depends on:** stdlib `logging` only.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `setup_logging()` | func | Configures the ROOT logger (DEBUG). File: `~/.stock_insights_logs/app.log`, rotating 1 MB x 3 backups, UTF-8. Console handler only if `sys.stdout` is not None (the windowed PyInstaller build has none). Closes any previous handlers first, so calling twice is safe. Returns the `stock_insights` logger. |
| `get_logger(name=None)` | func | `stock_insights` or `stock_insights.<name>` child. |
| `serial_debug(msg)` | func | Numbered `[0001] msg` DEBUG line on `stock_insights.trace`; counter is `itertools.count` (thread-safe). |
| `_IconColorFormatter` | class | Adds `record.levelicon`; ANSI colour only when stdout is a TTY. |
| `_silence_noisy_loggers()` | func | Raises levels of matplotlib/PIL/urllib3/yfinance/etc. |

## Data and state
Log files in `~/.stock_insights_logs/` (`app.log`, `app.log.1..3`). Module-level `_serial` counter.

## How to change it safely
- The console format string needs `%(levelicon)s`; only `_IconColorFormatter` supplies it.
- `sys.stdout.reconfigure(errors="replace")` avoids cp1252 crashes on the level icons.
- No tests (touches the real home dir); verify by import plus `serial_debug("x")`.

## Map
Formatter 27-53; helpers 56-80; `setup_logging` 82-end.
