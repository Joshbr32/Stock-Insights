# main.py
**Purpose:** Desktop entry point: QApplication, startup theme from QSettings, ConnectionDialog login, then MainWindow.
**Used by:** `python main.py`, `stock_insights.spec` (PyInstaller).  **Depends on:** PySide6, `connection_dialog.ConnectionDialog`, `main_window.MainWindow`, `theme.ThemeManager`.

## Key types and functions
| Name | Kind | Contract |
|---|---|---|
| `_apply_startup_theme()` | func | Reads `ui/THEME_OVERRIDE`, `ui/MATCH_SYSTEM_ACCENT`, `ui/THEME_NAME`, `ui/FONT_SIZE` from QSettings("StockInsights","StocksGUI") and applies them before any window shows. |
| `main()` | func | Builds the app, runs the login dialog; `sys.exit(0)` if cancelled; else shows the window and runs the event loop. |

## Data and state
QSettings org `StockInsights`, app `StocksGUI` (theme keys above).

## How to change it safely
- The HiDPI policy call must run before `QApplication(...)` is created, and the env var before Qt imports.
- Logging is set up inside `MainWindow.__init__`, not here.

## Map
Imports/HiDPI 1-20; theme 23-40; `main` 43-57.
