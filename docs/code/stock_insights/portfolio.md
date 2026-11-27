# stock_insights/portfolio.py
**Purpose:** Single source of truth for trade math: the `Trade` model, (de)serialisation, holdings, P/L, analytics (win rate, profit factor, drawdown), goal pace, date-range filtering. Pure functions, no Qt or I/O, so they are safe on any thread.
**Used by:** `qml_bridge.py`, `portfolio_tab.py`, `main_window.py`, `symbol_history_dialog.py`, `api_client.py`, `sync_queue.py`, `io_utils.py`, `tests/test_portfolio.py`.  **Depends on:** stdlib; optional `pandas_market_calendars` for NYSE holidays (commented out in requirements.txt and not in the venv, so the weekday fallback is what normally runs).

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `Trade` | dataclass | One trade. `buy_price` = entry (for a short, the short price); `sell_price` = exit (for a short, the cover price). `is_closed` needs BOTH sell_price and close_date. `trade_profit` is None unless closed; for shorts it is (buy-sell)*qty. `status` is WAITING/SHORT/COVERED/OPEN/CLOSED. |
| `TradeRow`, `Holding`, `HoldingView`, `PortfolioSummary`, `TradeAnalytics`, `GoalProgress` | dataclasses | Return shapes. The QML bridge and widgets read the field names, so do not rename them. |
| `_nyse_day_count(start, end)` | fn, `lru_cache(8192)` | Inclusive trading-day count. Uses the mcal schedule when available, otherwise O(1) weekday arithmetic. It is cached because every tick recounts the same date pairs. |
| `business_days_between / _elapsed_in_year / _remaining_in_year` | fn | Wrappers over `_nyse_day_count`. `between` returns None when either date is None. |
| `parse_date(value)` | fn | Accepts date, datetime, ISO, `Y/m/d`, `m/d/Y`, `d/m/Y`. Blank or "—" gives None; anything else raises ValueError. |
| `filter_trades_by_date_range_with_orig_index(trades, key, today)` | fn | Returns `[(orig_index, trade)]`. MainWindow's edit and delete rely on the preserved index. Pending trades are always kept; the date used is close_date or open_date; an unknown key means "all". |
| `trade_to_dict / trade_from_dict / trades_to_json / trades_from_json` | fn | Wire and backup format. `trades_from_json` takes a JSON string OR an already-parsed list, and drops bad rows and rows with share_count <= 0. A missing `tag` becomes "". |
| `solve_buy_mark_for_target_avg` | fn | The buy price needed to bring the average cost to a target. Raises ValueError on bad input. |
| `compute_trade_rows(trades)` | fn | One `TradeRow` per trade (index = position in the input). days_to_close is counted in trading days. |
| `compute_holdings_from_trades(trades)` | fn | Groups open, non-pending trades by symbol. Shorts get their own bucket with negative qty. Sorted shorts first (qty<0), then by symbol. |
| `compute_realized_pl_by_symbol(trades)` | fn | {symbol: realized P/L} over closed, non-pending trades. |
| `compute_portfolio(holdings, marks, realized)` | fn | Returns (rows, summary). A missing mark gives MV 0 and unrealized 0. weight = abs(MV) / gross MV. `return_pct` = unrealized / gross cost. |
| `compute_trade_analytics(trades)` | fn | Uses `date.today()` for avg daily and est. yearly (x252). profit_factor is None when there are no losses. Drawdown walks the cumulative realized curve sorted by close_date (stable sort). `open_trades` includes pending trades. |
| `compute_goal_progress(trades, goal, unrealized, today)` | fn | Pace numbers. remaining_profit can go negative; `_weeks_remaining` counts calendar days. |

## Data and state
No persistence. Module state: `_nyse_cal` (the calendar object or None) and the `_nyse_day_count` LRU cache (ints keyed by date pairs, at most about 8k entries, so tiny).

## How to change it safely
- Mirror: `pwa/js/portfolio.js` ports these formulas, so change both identically. Pre-existing divergences are listed in `docs/code/pwa/js/portfolio.md`. Tests pin them, so changing one is a behaviour change, not a refactor.
- Keep every public name and dataclass field.
- Never mutate the input trade list; callers pass the canonical account list.
- If `_nyse_day_count` ever depends on anything other than its two dates, drop the cache or add that input to the key. Tests can call `_nyse_day_count.cache_clear()`.
- Verify with `./.venv/Scripts/python.exe -m pytest tests/test_portfolio.py -q`. For a refactor, also snapshot the public functions' outputs on a synthetic trade list before and after, and diff them.

## Map
- 1-17 module docstring, imports
- 19-58 NYSE calendar + cached `_nyse_day_count`
- 60-211 dataclasses (`Trade` 64, `TradeAnalytics` 167, `GoalProgress` 198)
- 213-263 date helpers, business-day wrappers
- 265-322 date-range filter
- 324-407 serialisation, `solve_buy_mark_for_target_avg`
- 409-552 trade rows, holdings, realized-by-symbol, `compute_portfolio`
- 554-648 `compute_trade_analytics` (drawdown ~607)
- 650-687 `compute_goal_progress`
