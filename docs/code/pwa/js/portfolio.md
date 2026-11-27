# pwa/js/portfolio.js
**Purpose:** Browser port of the `portfolio.py` math for the phone PWA: holdings, P/L, analytics, goal pace, date filter, equity curve. Pure ES-module functions over plain trade objects.
**Used by:** `pwa/js/app.js` (imports buildEquityCurve, computeAnalytics, computeGoalProgress, computeHoldings, computePortfolio, filterTradesByDateRange, isClosed, normalizeTrade, realizedBySymbol, tradeProfit, tradeStatus); cached by `pwa/sw.js`.  **Depends on:** nothing.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `normalizeTrade(t)` | export | Turns a server `/trades` row into a uniform shape. Dates stay as `YYYY-MM-DD` strings. |
| `isClosed / tradeStatus / tradeProfit / costBasis` | export | Same rules as the `Trade` properties in Python. |
| `computeHoldings(trades)` | export | Groups open, non-pending trades by symbol; shorts get negative qty. Sorted longs first, then by `localeCompare`. |
| `realizedBySymbol(trades)` | export | {symbol: realized P/L}. |
| `computePortfolio(holdings, marks, realizedMap)` | export | Returns `{rows, summary}`. A `null`/`undefined` mark gives MV 0. |
| `computeGoalProgress(trades, target, today)` | export | Pace from realized P/L only; the caller adds unrealized. |
| `tradeInRange / filterTradesByDateRange` | export | Range keys all/week/month/30d/ytd. Pending and undated trades always pass. |
| `buildEquityCurve(trades, mode)` | export | Returns `[{x: epoch ms, y: cumulative}]`, seeded with 0 the day before the first close. Points sit at 16:00 local time. mode is "trades" or "daily". Mirrors `qml_bridge._build_equity_curve`. |
| `computeAnalytics(trades)` | export | Closed-trade stats plus drawdown (sorted by close_date). |
| `tradingDaysBetween`, `parseISODate` | private | Weekday count (a loop of at most 366 steps); date parse in local time. |

## Known divergences from portfolio.py (pre-existing, not yet reconciled)
- `computePortfolio` `summary.return_pct` = (realized + unrealized) / gross cost. Python uses unrealized / gross cost.
- `computeHoldings` order: JS puts longs first; Python puts shorts first.
- `computeAnalytics`: `open_trades` excludes pending (Python includes them). `profit_factor` is `Infinity` when there are wins and no losses (Python: None). The JS result has no avg_trade_value, ROI, avg daily or est. yearly fields.
- `computeGoalProgress`: remaining is clamped at >= 0, weeks = ceil(trading days / 5), the daily divisor is at least 1, the calendar is weekdays only, and field names differ (`monthly_to_goal`, `days_elapsed`, ...).
- `tradeInRange` "week" starts on Sunday; Python starts on Monday.

Reconciling any of these changes the numbers one client shows. Decide which side is correct, change both files, then update the tests.

## Data and state
None. Nothing here touches localStorage; persistence lives in `app.js`.

## How to change it safely
- Any math or rounding change must also be made in `stock_insights/portfolio.py`.
- Keep the export names, because app.js imports them. Changing this file needs `VERSION` in `pwa/sw.js` bumped so phones fetch the new copy (the lead decides).
- There is no node in the dev environment. Check behaviour by reasoning it through, or port the case into a Python test against portfolio.py.

## Map
- 1-16 header + divergence list
- 18-61 trade helpers
- 63-102 holdings, realizedBySymbol
- 104-150 computePortfolio
- 152-208 goal progress + trading-day helpers
- 210-266 date-range filter
- 268-324 buildEquityCurve
- 326-378 computeAnalytics
