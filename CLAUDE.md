# Stock Insights: guide for agents

A personal trade tracker for a small group of friends. Three pieces share one SQL Server backend:

| Piece       | Where                        | Stack                                               |
|-------------|------------------------------|-----------------------------------------------------|
| Desktop app | `main.py`, `stock_insights/` | PySide6: QWidget shell + dialogs, QML main content  |
| Phone app   | `pwa/`                       | Vanilla JS PWA, no build step, service worker       |
| Sync server | `server/server.py`           | FastAPI + pyodbc; also serves `pwa/`; public via Cloudflare Tunnel |

## Start here

1. `docs/code/README.md` has one line per source file. Open the matching `docs/code/<path>.md`
   before reading a large file: it lists the key functions, data stored, invariants and a line map.
2. `docs/design/design-system.md` before touching any screen, colour, font or copy.
3. `README.md` for setup and architecture background.

## Rules that bite

- **Live data.** `server/.env` and the `StockInsights` SQL Server are production. Never read `.env`, connect to the
  database, or call write endpoints on `si.coloniallawns.ca` / `COLONIAL_SERVER:8742`. Tests and scripts use fakes.
- **Never touch the user's real settings** (`QSettings("StockInsights", "StocksGUI")`, `~/.stockinsights_sync_queue.json`).
  Scripts redirect QSettings to a temp dir (see `scripts/ui_snapshot.py`).
- **Math mirror.** `stock_insights/portfolio.py` and `pwa/js/portfolio.js` compute the same numbers; change both.
  Known divergences are listed in `docs/code/pwa/js/portfolio.md`.
- **HTTP contract.** `stock_insights/api_client.py` and `pwa/js/api.js` both talk to `server/server.py`; a route or
  JSON change touches all three.
- **Versions.** Changing anything under `pwa/` that the service worker caches requires bumping `VERSION` in `pwa/sw.js`
  (pre-commit hook: `bash scripts/install-git-hooks.sh`); new PWA JS files also go in its `SHELL` list.
  Desktop releases bump `APP_VERSION` (`stock_insights/version.py`); server API changes bump `SERVER_VERSION`.
- **UI thread.** No network or disk calls in Qt slots; use `MainWindow._run_in_background` or `workers.py`.
- Don't edit `build/`, `dist/`, `stock_insights.spec` unless working on the build.

## Commands (PowerShell, repo root, venv in `.venv`)

```powershell
./.venv/Scripts/python.exe -m pytest tests -q                       # pure-Python tests (tests/ is gitignored locally)
./.venv/Scripts/python.exe -m compileall -q main.py stock_insights server
./.venv/Scripts/python.exe scripts/ui_snapshot.py --out shots        # PNGs of the QML main view, fixture data
./.venv/Scripts/python.exe scripts/ui_snapshot_dialogs.py --out shots # PNGs of every dialog
./.venv/Scripts/python.exe -m http.server 8765 --directory pwa       # then open http://127.0.0.1:8765/?demo
```

## Working as a team

Once the agent-team setup is merged, `.claude/skills/route-team` splits larger requests across
Fable / Opus / Sonnet teammates (`.claude/agents/`). Small changes are done directly.
