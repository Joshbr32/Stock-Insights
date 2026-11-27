# stock_insights/dialogs/trade_edit.py
**Purpose:** Log / edit a trade, close a long position, or buy to cover a short.
**Used by:** main_window (`_trade_dialog`, `_close_position`), portfolio_tab (edit mode).  **Depends on:** `dialogs/_common` (spin/date factories), `portfolio.Trade`, `widgets`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `TradeEditDialog(trade=None, watchlist_symbols=None, default_quantity=1, quantity_increment=1, close_holdings_mode=False, cover_mode=False, parent=None)` | QDialog | Title/primary: "Log trade" / "Edit trade"+"Save changes" / "Close position" / "Buy to cover". Close modes lock everything except closing price + date. |
| `to_trade() -> Trade` | method | Pending → `open_date=None`; Closed → sell price + close date set. Account is set by the caller. |
| `_accept_if_valid()` | method | Requires symbol, buy price > 0; when closed: sell price > 0 and close date ≥ open date. |
| combos | attrs | `type_combo` (data: is_short), `pending_combo` (data: is_pending), `status_combo` (data: "OPEN"/"CLOSED"). Logic reads item data, never display text. |

## Data and state
None.

## How to change it safely
- Do not use `setFixedHeight` (crashed with a QQuickWidget parent); resizing is `adjustSize` deferred by `_resize_to_content`.
- Keep attribute names (`instrument_edit`, `share_count_spin`, `buy_price_spin`, `sell_price_spin`, `open_date_edit`, `close_date_edit`, `notes_edit`, `tag_edit`, `btn_save`, ...): the snapshot script and callers touch them.
- Profit preview uses the same formula as portfolio.Trade.trade_profit.

## Map
- 1-33 docstring/imports; 36-165 `__init__` (Order, Position, Close panels, buttons)
- 167-205 state helpers + mode constraints; 207-240 visibility sync; 242-279 preview + validation; 281-296 `to_trade`
