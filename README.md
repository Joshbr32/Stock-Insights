# Stock Insights

A personal-scale trade tracker built for a small group of friends. Tracks
realized + unrealized P/L, computes goal-pace projections, surfaces
drawdown / win-rate / profit-factor, and visualizes everything as an
interactive equity curve.

Three runnable pieces, one shared SQL Server backend:

| Piece           | Lives in                      | What it is                                                                                                                                                                                                                         |
|-----------------|-------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Desktop app** | `main.py` + `stock_insights/` | PySide6 + QML hybrid. The hosting QMainWindow + menu bar + thread/timer lifecycle is QWidget-based; the actual content (Goal Dashboard, Analytics, Equity Curve, Holdings, Trade History) is QML. Runs on Windows / macOS / Linux. |
| **Mobile PWA**  | `pwa/`                        | Pure HTML / CSS / JS. No build step. Same backend as desktop. Installs to phone home screen via "Add to Home Screen".                                                                                                              |
| **Sync server** | `server/server.py`            | FastAPI + SQL Server. Stores trades, accounts, goal config, watchlist, user logins. Also serves the `pwa/` static files.                                                                                                           |

---

## Quick start

### Desktop client (this repo, locally)

```sh
# 1. Create + activate a venv (Python 3.10–3.12 recommended)
python -m venv .venv
.venv\Scripts\activate                                 # Windows
source .venv/bin/activate                              # macOS / Linux

# 2. Install
pip install -r requirements.txt

# 3. Run
python main.py
```

First launch shows a connection dialog. Either:

- Point it at your sync server (typical), or
- Pick "Local only" — uses QSettings as a single-user data store.

### Sync server (one-time setup on the server PC)

See `server/.env.example` for the required env vars. TL;DR:

```sh
cd server
copy .env.example .env                                  # then edit PORTFOLIO_SQL_PASSWORD
pip install -r requirements.txt
python server.py
```

The server reads `.env` automatically via `python-dotenv` — no shell-export
dance needed. SQL Server schema lives in `init_stockinsights.sql` (run
once via SSMS).

### Mobile PWA

The server mounts `pwa/` at `/`, so the PWA is reachable wherever the
sync server is. On the LAN that's `http://192.168.x.x:8742/`; externally
it's the Cloudflare Tunnel URL — for this deployment, **<https://si.coloniallawns.ca/>**.
See `pwa/README.md` for HTTPS / install-to-home-screen / cache-busting
notes.

---

## Repo layout

```
.
├── main.py                              # Desktop entry point
├── stock_insights/                      # Desktop app source
│   ├── main_window.py                   # QMainWindow shell (menus, timers, status pill)
│   ├── qml_bridge.py                    # AppController / AccountController — Python ↔ QML bridge
│   ├── portfolio.py                     # Pure trade math (compute_*_analytics, drawdown, etc.)
│   ├── api_client.py                    # DataStore implementations (Local / Remote / Fallback)
│   ├── data.py                          # yfinance wrapper for live marks
│   ├── workers.py                       # QThread workers (Marks, NetCheck, Reconnect, StoreCall)
│   ├── io_utils.py                      # CSV export + JSON backup/restore + auto-snapshots
│   ├── theme.py                         # 9 themes, font scales, system-accent matching
│   ├── admin_dialogs.py                 # User account / view-other-user / password-reset dialogs
│   ├── symbol_history_dialog.py         # Per-symbol drill-down (mini equity curve + trade table)
│   ├── dialogs/                         # Trade-edit / mark-down / double-down / goal options
│   │   ├── _common.py                   # Shared GROUP_STYLE + spinbox factories + preset I/O
│   │   ├── goal_options.py              # GoalDashboardOptionsDialog + _AccountGoalBlock
│   │   ├── trade_edit.py                # TradeEditDialog (long / short / pending)
│   │   ├── trade_actions.py             # FulfillOrderDialog + MarkDownDialog + DoubleDownDialog
│   │   └── trade_history_columns.py     # Column visibility + sort config
│   ├── portfolio_tab.py                 # Legacy QWidget portfolio view (used by admin viewer)
│   ├── settings_dialog.py               # File → Settings (theme, fonts, intervals, etc.)
│   └── qml/                             # All QML scenes
│       ├── Main.qml                     # SplitView: Watchlist | PortfolioPane
│       ├── PortfolioView.qml            # Goal/Analytics row + EquityCurve + Holdings + Trades
│       ├── EquityCurveCard.qml          # QtCharts curve with hover tooltip + daily resampling
│       ├── AnalyticsPanel.qml           # 7-row metrics grid + Est. Yearly featured row
│       ├── GoalDashboard.qml            # Hero progress + presets + per-day/week/month math
│       ├── HoldingsTable.qml            # Open positions, sortable, right-click menu
│       ├── TradesTable.qml              # Trade history with date-range + tag + status filters
│       ├── WatchlistPane.qml            # Side pane with live prices
│       └── ...                          # (Card / SectionTitle / ThemedComboBox / Metric / Pill)
├── server/                              # Sync server (independent venv)
│   ├── server.py                        # FastAPI app + SQL Server access
│   ├── .env.example                     # Committed template
│   ├── .env                             # Real values (gitignored)
│   ├── requirements.txt                 # fastapi / uvicorn / pyodbc / python-dotenv
│   └── init_stockinsights.sql           # One-time DB / login / table setup
├── pwa/                                 # Mobile PWA (companion to the desktop)
│   ├── index.html                       # App shell
│   ├── styles.css                       # All styling (editorial / cream-paper aesthetic)
│   ├── manifest.webmanifest             # PWA install metadata
│   ├── sw.js                            # Service worker (cache the shell, network-first APIs)
│   ├── js/
│   │   ├── api.js                       # Fetch wrapper around the FastAPI backend
│   │   ├── portfolio.js                 # JS port of compute fns from portfolio.py (1:1 numbers)
│   │   └── app.js                       # Views, routing, drill-down modal, equity SVG
│   └── README.md                        # PWA-specific setup + cache-busting notes
├── tests/                               # Pure-Python unit tests
│   ├── test_portfolio.py                # 51 tests — math + drawdown + tag + date-range filter
│   └── test_io_utils.py                 # 38 tests — CSV writer + backup roundtrip + auto-snapshot
├── scripts/                             # Helper scripts (git hooks, etc.)
│   ├── pre-commit-pwa-version-check.sh  # Blocks shell-file commits without sw.js VERSION bump
│   └── install-git-hooks.sh             # One-time hook installer
└── requirements.txt                     # Desktop deps (PySide6, yfinance, pandas, etc.)
```

---

## Development

### Running tests

```sh
python -m pytest tests/                                    # full suite
python -m pytest tests/test_portfolio.py -v                # one file, verbose
python -m pytest tests/ -k "drawdown" -v                   # match-test-name
```

The test suite is pure Python — no Qt instantiation needed. ~93 tests
covering portfolio math, drawdown, date-range filter index preservation,
tag round-tripping, CSV write-and-read-back, backup roundtrip, and
backup validation.

### Code organization conventions

- **`portfolio.py`** is the single source of trade math. The mobile
  `pwa/js/portfolio.js` mirrors it line-for-line for the same numbers
  ("this file mirrors portfolio.py 1:1 for the numbers that appear in
  both UIs"). When you change one, change both.
- **Dialogs** that don't need MainWindow internals live in their own
  module — `admin_dialogs.py`, `symbol_history_dialog.py`, the
  `dialogs/` package. New modal dialogs should follow the same pattern.
- **Background-bound work** (HTTP writes, marks, reconnect) goes through
  `MainWindow._run_in_background` or the explicit `workers.py` classes.
  Don't add blocking calls inside QML-triggered slots — they freeze the
  UI for the duration of the network roundtrip.
- **Comments** explain *why*, not *what*. Especially around the
  `_safe_run` / `_run_in_background` patterns and any QML-side gotcha
  (ChartView's child filtering, the equity curve's epoch-0 fallback,
  etc.) — those are the surprising bits future-you will need.

### PWA cache busting

The service worker caches the app shell aggressively. When you change
`pwa/js/*.js`, `pwa/styles.css`, or `pwa/index.html`, you **must** bump
`VERSION` in `pwa/sw.js` so installed PWAs pick up the new shell.

Install the pre-commit hook to enforce this automatically:

```sh
bash scripts/install-git-hooks.sh
```

After install, any commit that touches a shell file without bumping
`sw.js` is blocked with a reminder.

### Releasing a new desktop version

1. Bump `APP_VERSION` in `stock_insights/version.py`.
2. Optionally bump `SERVER_VERSION` in `server/server.py` if the change
   requires server coordination (new endpoints, schema changes, etc.).
3. Build the .exe (PyInstaller spec is in `build/`).
4. Update the hosted `version.json` so existing installs auto-detect the
   release (see version.py docstring for the exact JSON shape + hosting
   options).

---

## Architecture notes

### Why three pieces share one backend

The trade list lives in SQL Server. Both clients (desktop + PWA) read
the same data and compute the same metrics client-side. That keeps the
API tiny — the server only stores raw trades and serves them back. New
analytics never require a server change; we just add the math to
`portfolio.py` (and mirror in `portfolio.js` for mobile).

### DataStore abstraction

Three implementations, swappable at construction time:

- `LocalDataStore` — QSettings-backed; single user, no server, no sync.
- `RemoteDataStore` — direct HTTP to the FastAPI server.
- `FallbackDataStore` — wraps both; tries remote first, falls back to a
  local cache + replays a sync queue when the server returns. Used when
  the user expects "works offline, syncs when online" behavior.

### QML bridge pattern

`AppController` (in `qml_bridge.py`) is the root context property
exposed to QML as `app`. It owns:

- `theme` — `ThemeController` for theming
- `accounts` — list of `AccountController`s (one per portfolio)
- `currentAccount` — the active tab
- `watchlist` — `WatchlistModel` (QAbstractListModel)
- view-pref toggles (`equityCurveVisible`)

Each `AccountController` exposes its own holdings / trades / analytics /
goal / equity-curve as Q_PROPERTIES with `notify=metricsChanged`, so QML
bindings re-evaluate automatically when the controller's `update()`
runs.

### Status pill (server health)

The corner widget shows online/offline at a glance. Hover the label to
see a tooltip populated by `/health` polling: server version, latency
in ms, database state, uptime. The probe runs every 15s on a background
thread; the desktop never blocks waiting for it.

---

## License

Personal use among the original three friends. No license declared —
treat this repo as private until that changes.
