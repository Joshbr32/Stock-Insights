# scripts/ui_snapshot.py
**Purpose:** Render the real desktop QML scene (Main.qml + real AppController + ThemeManager) on fixture data and save PNGs, fully offline and without touching the user's settings. Use it to check any QML/theme change visually.
**Used by:** developers / agents (not imported by the app).  **Depends on:** stock_insights.api_client (`LocalDataStore`), portfolio (`Trade`), qml_bridge (`AppController`), theme (`ThemeManager`), PySide6 QtQuickWidgets + QtCharts.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `_block_network()` | func | Replaces `socket.connect`/`create_connection` with a raiser at import time. |
| `PRICES` | dict | Fixed marks applied via `AppController.apply_marks` (no yfinance). `XYZQ` in the watchlist has no price on purpose. |
| `FixtureStore` | LocalDataStore subclass | Same behaviour, but `_settings` is an explicit INI file in a temp dir (ORG `StockInsightsSnapshot`). |
| `_fixture_trades(today)` | func | 40 deterministic trades dated relative to today: "Main" (24 closed longs, 2 covered shorts, 4 open longs, 1 open short, 1 pending) and "Roth IRA" (5 closed, 2 open, 1 pending). |
| `_seed_store(store, today)` | func | Accounts, trades, goals (Main $5,000 = behind pace, Roth $4,800 = ahead), presets, watchlist. |
| `main(argv)` | func | CLI. `--out DIR` (required), `--sizes 1440x900,1100x700`, `--modes light,dark`, `--theme NAME`, `--account N`, `--empty-account`, `--hide-curve`. Writes `main-<mode>-<WxH>[-theme][-accountN].png`, prints each path; exit 1 on QML load error. |

## Data and state
QSettings default format/paths redirected to a fresh `tempfile.mkdtemp()` (IniFormat, user + system scope) and the organisation name set to `StockInsightsSnapshot` before QApplication exists. `LocalDataStore.__init__` still opens `QSettings(ORG, APP)` (native format ignores setDefaultFormat) under the snapshot org, but it is replaced before any read/write. Temp dirs are left behind (small INI).

## How to change it safely
- Never point it at the real org/app names or a RemoteDataStore.
- Renders with `WA_DontShowOnScreen` on the real Windows platform plugin (the offscreen plugin has no Segoe fonts, so it would not show the real typography). Waits 900 ms per shot for layout + the 400 ms pace-rail animation.
- QML warnings are echoed to stderr as `[qt] ...`; a clean run prints only the PNG paths.
- If LocalDataStore's constructor changes, keep calling `super().__init__` and then swap `_settings`.

## Map
- 1-60 docstring, network block, imports
- 61-85 constants, `FixtureStore`
- 87-145 fixture data + seeding
- 147-157 Qt message echo, event pump
- 159-end `main()`
