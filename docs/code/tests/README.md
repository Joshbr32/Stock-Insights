# tests/
**Purpose:** Pure-Python regression suite (no Qt event loop, no network, writes only to `tmp_path`). Run: `./.venv/Scripts/python.exe -m pytest tests -q`.

| File | Covers |
|---|---|
| `conftest.py` | Adds repo root to `sys.path`; `FakeStore` (in-memory DataStore) and the `fake_store_cls` fixture. |
| `test_portfolio.py` | Trade math (long/short), status, parse_date, business days, (de)serialization, `solve_buy_mark_for_target_avg`, holdings, realized P/L, `compute_portfolio`, analytics, drawdown, goal progress, date-range filter index preservation, tags. |
| `test_io_utils.py` | CSV export, `build/write/read_backup`, `validate_backup`, `apply_backup`, auto-snapshot (slug, prune, failure returns None). |

Gotchas:
- `compute_holdings_from_trades` sorts shorts FIRST (sort key `qty >= 0`); a test pins that.
- The auto-backup dir is redirected by monkeypatching `io_utils._auto_backup_dir`; keep that name stable.
- Business-day tests avoid holidays so they pass with or without pandas_market_calendars.
- Expected values in `test_portfolio.py` mirror `pwa/js/portfolio.js`; if one changes, change both.
