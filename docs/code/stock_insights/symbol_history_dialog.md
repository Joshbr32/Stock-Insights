# stock_insights/symbol_history_dialog.py
**Purpose:** Read-only drill-down for one symbol in one portfolio: open position + unrealized P/L, stat row, cumulative realized P/L chart, chronological trade table.
**Used by:** main_window `_open_symbol_history` (Holdings and Trade History context menus).  **Depends on:** `portfolio.compute_trade_analytics`, QtCharts, `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `SymbolHistoryDialog(instrument, trades, current_mark=None, parent=None)` | QDialog | Filters `trades` to the symbol; `current_mark` (float) enables the unrealized P/L in the header. |
| `_build_header / _build_stat_strip / _build_chart / _build_trade_table` | methods | Each returns a widget/layout; chart shows an empty state when nothing has closed. |
| `_epoch_ms(date, time)` | static | ms since epoch for QDateTimeAxis. |

## Data and state
None.

## How to change it safely
- Colours come from `widgets.theme_color` at construction (dialog is short-lived, so no live re-theme).
- Numbers: signed with U+2212, right-aligned numeric columns (3–6), status via `fmt_status`.
- Maths must stay in portfolio.py (mirrored by pwa/js/portfolio.js).

## Map
- 1-56 docstring/imports/constants; 59-64 formatters; 67-86 `__init__`; 88-112 header; 114-142 stats; 144-207 chart; 209-259 table; 261-265 helper
