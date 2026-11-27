# Code map

One line per source file. Each links to a doc with the file's purpose, key functions, the data it stores,
how to change it safely, and a line map. Read the doc first, then jump to the lines you need.
Keep these docs current: a change to a file's interface or invariants updates its doc in the same commit.

## Desktop app (`stock_insights/`)

**Data and maths (no UI)**
- [portfolio.py](stock_insights/portfolio.md): the trade model and all trade maths. Mirrored by `pwa/js/portfolio.js`.
- [api_client.py](stock_insights/api_client.md): the `DataStore` interface: `RemoteDataStore` (HTTP), `LocalDataStore` (QSettings), `FallbackDataStore` (offline cache + sync).
- [sync_queue.py](stock_insights/sync_queue.md): durable queue of writes made offline, replayed in order on reconnect.
- [data.py](stock_insights/data.md): live prices from Yahoo via yfinance.
- [io_utils.py](stock_insights/io_utils.md): CSV export, JSON backup and restore, auto-snapshots.

**Threads and app plumbing**
- [workers.py](stock_insights/workers.md): QThread workers for prices, the connection check and reconnect.
- [background.py](stock_insights/background.md): `BackgroundCalls` / `SingleFlight`: run blocking work off the GUI thread, deliver results on it.
- [logging_utils.py](stock_insights/logging_utils.md): rotating file log and console log.
- [update_checker.py](stock_insights/update_checker.md): "Check for updates" against a JSON manifest.
- [version.py](stock_insights/version.md): `APP_VERSION` and the update manifest URL.
- [\_\_init\_\_.py](stock_insights/__init__.md): package marker.

**Main window and QML bridge**
- [main_window.py](stock_insights/main_window.md): QMainWindow hosting the QML scene; menus, status corner, timers, background threads.
- [qml_bridge.py](stock_insights/qml_bridge.md): view models exposed to QML as `app` (accounts, holdings, trades, goal, pace, theme).
- [theme.py](stock_insights/theme.md): the 9 themes (Default = Harbor), font resolution, palette and global QSS.
- [widgets.py](stock_insights/widgets.md): Harbor building blocks for QWidget dialogs (panels, forms, button rows, money labels).
- [file_actions.py](stock_insights/file_actions.md): File menu actions (export, back up, restore).

**Dialogs and windows (QWidget)**
- [connection_dialog.py](stock_insights/connection_dialog.md): startup sign-in, or work offline.
- [settings_dialog.py](stock_insights/settings_dialog.md): File > Settings.
- [admin_dialogs.py](stock_insights/admin_dialogs.md): own account, admin password reset, view another user's portfolio.
- [symbol_history_dialog.py](stock_insights/symbol_history_dialog.md): one symbol's trades, stats and chart.
- [portfolio_tab.py](stock_insights/portfolio_tab.md): legacy QWidget portfolio view, used by the admin viewer.
- [dialogs/](stock_insights/dialogs/__init__.md): [trade_edit](stock_insights/dialogs/trade_edit.md) (log, edit, close, cover), [trade_actions](stock_insights/dialogs/trade_actions.md) (mark filled, mark down, double down), [goal_options](stock_insights/dialogs/goal_options.md), [trade_history_columns](stock_insights/dialogs/trade_history_columns.md), [_common](stock_insights/dialogs/_common.md).

**QML scene (`stock_insights/qml/`)**
- [Main](stock_insights/qml/Main.md): root SplitView: watchlist | portfolio.
- [PortfolioPane](stock_insights/qml/PortfolioPane.md): account tabs, Log trade, the page.
- [PortfolioView](stock_insights/qml/PortfolioView.md): scrolling page: goal, positions, equity curve | performance, trade history.
- [GoalDashboard](stock_insights/qml/GoalDashboard.md) with [PaceRail](stock_insights/qml/PaceRail.md) (the signature element).
- [HoldingsTable](stock_insights/qml/HoldingsTable.md), [TradesTable](stock_insights/qml/TradesTable.md), [EquityCurveCard](stock_insights/qml/EquityCurveCard.md), [AnalyticsPanel](stock_insights/qml/AnalyticsPanel.md), [WatchlistPane](stock_insights/qml/WatchlistPane.md).
- Components: [Card](stock_insights/qml/Card.md), [Metric](stock_insights/qml/Metric.md), [Pill](stock_insights/qml/Pill.md), [SectionTitle](stock_insights/qml/SectionTitle.md), [ToolButton2](stock_insights/qml/ToolButton2.md), [ThemedComboBox](stock_insights/qml/ThemedComboBox.md), [ThemedScrollBar](stock_insights/qml/ThemedScrollBar.md), [FocusRing](stock_insights/qml/FocusRing.md), [qmldir](stock_insights/qml/qmldir.md).

- [main.py](main.md): desktop entry point.

## Phone app (`pwa/`)
- [index.html](pwa/index.md): the only page.
- [js/app.js](pwa/js/app.md): state, data loading and every view.
- [js/api.js](pwa/js/api.md): HTTP client for the server (timeouts, retry, auth).
- [js/portfolio.js](pwa/js/portfolio.md): JS port of the trade maths; lists known divergences from Python.
- [js/charts.js](pwa/js/charts.md): pace rail and equity curve.
- [js/ui.js](pwa/js/ui.md): safe DOM builders, icons, formatting, guarded localStorage.
- [js/demo.js](pwa/js/demo.md): `?demo` fixture mode for design review.
- [styles.css](pwa/styles.md): all styling (Harbor tokens).
- [sw.js](pwa/sw.md): service worker (offline shell; API never cached).
- [make_icons.py](pwa/make_icons.md): icon generator.

## Server (`server/`)
- [server.py](server/server.md): FastAPI + SQL Server sync API, quotes proxy, static PWA host.
- [requirements and .env.example](server/requirements.md).

## Server PC: controller and manager
- [si_controller/](si_controller/__init__.md): keeps the sync server running (child process, health checks, back-off restarts, redacted logs); loopback API on 127.0.0.1:8746. [supervisor](si_controller/supervisor.md), [controller](si_controller/controller.md), [api](si_controller/api.md), [client](si_controller/client.md), [cli](si_controller/cli.md), [config](si_controller/config.md), [logs](si_controller/logs.md), [redaction](si_controller/redaction.md), [win](si_controller/win.md), [words](si_controller/words.md).
- [si_manager/](si_manager/__init__.md): the Stock Insights Server Manager window (dashboard, server output, events, tasks); talks only to the controller API. [window](si_manager/window.md), [pages](si_manager/pages.md), [tasks](si_manager/tasks.md), [widgets](si_manager/widgets.md), [theme](si_manager/theme.md).
- [server/install_autostart.ps1](server/install_autostart.md) and `uninstall_autostart.ps1`: start SQL Server and the controller at boot.
- Runbook: [../ops/server-pc.md](../ops/server-pc.md). API changes in 1.1: [../api/server-1.1-changes.md](../api/server-1.1-changes.md).

## Tooling
- [tests/](tests/README.md): pure-Python regression suite.
- [scripts/ui_snapshot.py](scripts/ui_snapshot.md) and [scripts/ui_snapshot_dialogs.py](scripts/ui_snapshot_dialogs.md): offline PNG renders of every desktop screen.
- [scripts/pre-commit-pwa-version-check.sh](scripts/pre-commit-pwa-version-check.md), [scripts/install-git-hooks.sh](scripts/install-git-hooks.md).
- [build.bat](build.md), [requirements.txt](requirements.md).

## Design
- [../design/design-system.md](../design/design-system.md): Harbor tokens, type, the pace rail, words, accessibility floor.
