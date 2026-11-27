# pwa/js/portfolio.js
**Purpose:** Browser port of `stock_insights/portfolio.py` for the phone PWA: trade identity (uid), holdings, P/L, analytics, goal progress, date filter, equity curve, trading-day counts. Pure ES-module functions over plain trade objects; mirrors the Python 1:1 so both clients show the same numbers.
**Used by:** `pwa/js/app.js` (most exports), `pwa/js/charts.js` (`goalExpectedByNow`, `tradingDaysBetween`), `pwa/js/demo.js` (`newTradeUid`); cached by `pwa/sw.js`.  **Depends on:** nothing (uses `crypto.randomUUID` / `getRandomValues` when present).

## Key types and functions
| Name | Kind | What it does / contract (Python counterpart) |
|---|---|---|
| `cleanTradeUid(v)` | export | Valid uid from `v` (dashed / upper-case uuids normalised, as `portfolio._clean_uid`) or `""`. |
| `newTradeUid()` / `isTradeUid(v)` | export | 32 lowercase hex chars (uuid4 without dashes). `randomUUID` needs a secure context; falls back to `getRandomValues`, then `Math.random`. See `docs/api/server-1.1-changes.md`. |
| `normalizeTrade(t)` | export | Server row / backup entry -> uniform shape (`trade_from_dict`): trimmed upper symbol, trimmed account and tag, whole non-negative shares, `""` sell price -> null, dates stay `YYYY-MM-DD`. Keeps a valid `uid` (via `cleanTradeUid`) or generates one. |
| `isClosed / tradeStatus / tradeProfit / costBasis` | export | `Trade.is_closed / status / trade_profit / cost_basis`. Closed = sell price and close date both set. |
| `computeHoldings(trades)` | export | `compute_holdings_from_trades`: open, non-pending trades by symbol and side; shorts get negative qty. Order: shorts first, then longs, symbol by code point (Python `(qty >= 0, instrument)`). |
| `realizedBySymbol(trades)` | export | `compute_realized_pl_by_symbol`. |
| `computePortfolio(holdings, marks, realizedMap)` | export | `compute_portfolio` -> `{rows, summary}`. Null/missing mark gives MV 0 and no unrealized. `summary.return_pct` = unrealized / gross cost x 100 (null when no cost). |
| `tradingDaysBetween(a, b)` | export | Inclusive weekday count, O(1); the weekday fallback of `_nyse_day_count`. |
| `businessDaysElapsedInYear(today)` / `businessDaysRemainingInYear(today)` | export | Jan 1..today and today..Dec 31, both inclusive (today counts twice, as in Python). |
| `goalExpectedByNow(target, today)` | export | `target x elapsed / (elapsed + remaining)`: the pace value of `compute_goal_progress` and the desktop pace rail (`qml_bridge._pace_map`). |
| `computeGoalProgress(trades, target, unrealized = 0, today)` | export | `compute_goal_progress`, same field names as `GoalProgress` (`realized_profit`, `remaining_profit` (negative once beaten), `monthly/weekly/daily_profit_to_goal`, `avg_daily_profit`, `profit_to_match_daily_avg`, `business_days_elapsed/remaining`, ...). Weeks = ceil(calendar days to Dec 31 / 7) min 1; months = 12 - month + 1; daily is null when no trading days remain. |
| `tradeInRange / filterTradesByDateRange` | export | `filter_trades_by_date_range_with_orig_index`: keys all/week/month/30d/ytd, week starts Monday, date = close_date or open_date, pending and undated trades always pass, unknown key = all. Order kept. |
| `buildEquityCurve(trades, mode)` | export | `qml_bridge._build_equity_curve`: `[{x: epoch ms, y}]`, $0 seed at 00:00 the day before the first close, points at 16:00 local; mode "trades" or "daily". |
| `computeAnalytics(trades, today)` | export | `compute_trade_analytics`, same fields incl. `avg_trade_value`, `avg_roi_pct`, `total_roi_pct`, `avg_daily_closed_profit`, `est_yearly_profit` (x252). `open_trades` counts every non-closed trade (pending included). `profit_factor` is null unless there are both wins and losses (UI shows "—"). Drawdown walks closes in date order. |

## Known divergences from portfolio.py
None. Checked on 2026-11-26 with a 42-trade fixture (long, short, pending with and without dates, a pending trade with an exit, close date without exit price, undated open trade, same-day closes, lower-case / padded symbols and accounts, a missing and a null mark) for 7 fixed "today" dates (Mon, Thu, Sun, Jan 1, Dec 31, a DST-change Monday, Nov 1) x 6 range keys x 3 goal targets: 16,618 values compared (holdings and order, realized map and key order, rows, summary, analytics, both equity-curve modes, statuses, profits, filter indices, goal progress, pace expected value / fraction / sentence). 0 mismatches; largest difference 1.9e-9 (float noise). The harness lives outside the repo; to repeat it, generate expected values with `portfolio.py` (+ `qml_bridge.AccountController._build_equity_curve` / `_pace_map`) and compare in a page that imports `js/portfolio.js`.

Caveat: trading days are weekdays on both sides because `pandas_market_calendars` is not installed (not in requirements.txt). If it is ever installed for the desktop, Python counts NYSE holidays and goal / pace figures will differ by a few days' worth.

## Data and state
None. Nothing here touches localStorage; persistence lives in `app.js`.

## How to change it safely
- Any math, filter, order or rounding change must be made in `stock_insights/portfolio.py` too, and vice versa; re-run a Python-vs-JS comparison.
- Sums are accumulated in the same order as Python (trade order, insertion-ordered maps); keep that so results agree to the last bit.
- Sort keys use code-point comparison (`cmpStr`), not `localeCompare`, to match Python's `sorted`.
- Keep export names: app.js, charts.js and demo.js import them. Changing this file needs `VERSION` in `pwa/sw.js` bumped (the lead decides).
- No node in the dev environment: test in a browser (serve `pwa/` with `python -m http.server`).

## Map
- 1-40 header, uid helpers
- 42-91 trade helpers, `cmpStr`
- 93-133 holdings, realizedBySymbol
- 135-188 computePortfolio
- 190-228 trading days, `goalExpectedByNow`
- 230-268 computeGoalProgress
- 270-320 date-range filter
- 322-362 buildEquityCurve
- 364-424 computeAnalytics
