# tests/
**Purpose:** Pure-Python regression suite (no Qt event loop, no network, writes only to `tmp_path`). Run: `./.venv/Scripts/python.exe -m pytest tests -q`.

| File | Covers |
|---|---|
| `conftest.py` | Adds repo root to `sys.path`; `FakeStore` (in-memory DataStore) and the `fake_store_cls` fixture. |
| `test_portfolio.py` | Trade math (long/short), status, parse_date, business days, (de)serialization, `solve_buy_mark_for_target_avg`, holdings, realized P/L, `compute_portfolio`, analytics, drawdown, goal progress, date-range filter index preservation, tags, uid. |
| `test_io_utils.py` | CSV export, `build/write/read_backup`, `validate_backup`, `apply_backup`, auto-snapshot (slug, prune, failure returns None). |
| `test_server.py` | `server/server.py` on a fake pyodbc (in-memory sqlite) through raw ASGI calls: hashed tokens and legacy upgrade, scrypt + PBKDF2 rehash, per-trade upsert/move/delete, tags, bulk replace, docs off, unmigrated (reduced) mode. |
| `test_controller.py` | `si_controller`: supervisor start/health/back-off/crash loop/graceful stop with a fake child server, the token-protected API, output redaction. See [test_controller.md](test_controller.md). |
| `test_sync.py` | Per-trade saves: `DataStore` default `save_trade`/`delete_trade`, `LocalDataStore`, `RemoteDataStore` and `FallbackDataStore` against an in-process HTTP server on 127.0.0.1 (1.1 routes, 1.0 server answering 404, unmigrated server answering 503, uid conflict 409), `sync_queue` coalescing and replay. |

Gotchas:
- `compute_holdings_from_trades` sorts shorts FIRST (sort key `qty >= 0`); a test pins that.
- The auto-backup dir is redirected by monkeypatching `io_utils._auto_backup_dir`; keep that name stable.
- Business-day tests avoid holidays so they pass with or without pandas_market_calendars.
- Expected values in `test_portfolio.py` mirror `pwa/js/portfolio.js`; if one changes, change both.
- `test_sync.py`'s `isolated` fixture replaces `api_client.QSettings` with an .ini factory under `tmp_path` and patches `sync_queue._QUEUE_FILE`. Do not rely on `QSettings.setDefaultFormat`: `QSettings(org, app)` ignores it and writes to the registry. Any new test that builds a `LocalDataStore` must use that fixture.
