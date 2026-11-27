# stock_insights/qml_bridge.py
**Purpose:** View-model layer between the Python data/maths (portfolio.py, the DataStore) and the QML scene: list models, per-account controllers, theme tokens, and the root `app` object.
**Used by:** main_window.py (creates `AppController`, sets it as QML context property `app`, calls its Python methods), every file in `stock_insights/qml/`, scripts/ui_snapshot.py.  **Depends on:** portfolio.py (pure maths), theme.py (`FONT_SIZES`, `resolve_fonts`, `reduce_motion_enabled`, ThemeManager instance), PySide6.QtCore.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `_money` / `_signed_money` / `_goal_money` / `_pct` / `_signed_pct` / `_arrow_pct` / `_date` | funcs | Display formatting. Unsigned `$1,234.56` / `−$1,234.56`; signed P/L `+$412.50` / `−$88.00` (U+2212); `▲ 4.2%`; dates `Mar 7` (this year) or `Mar 7, 2025`. |
| `WatchlistModel` | QAbstractListModel | Roles `symbol, price, priceText`; `count` property. `set_symbols` skips the reset when unchanged; `update_prices` emits per-row dataChanged. |
| `HoldingsModel` | QAbstractListModel | Roles `instrument, qtyText, avgCost, mark, unrealizedPl, unrealizedSign, unrealizedPctText, marketValue, weight, isShort`. `set_rows` updates rows in place (dataChanged) when the positions are the same, resets only when the set changes. `_rows[i]["instrument"]` is read by main_window's marks tick: keep that key. |
| `TradesModel` | QAbstractListModel | Roles `instrument, shareCount, status (code), statusText (sentence case), buyPrice, sellPrice, tradeProfit, profitSign, returnText, openDate, closeDate, daysToClose, avgDaily, notes, tag, sourceIndex, isPending, isShort`. `source_index_for(row)`. |
| `AccountController` | QObject | One per account. Properties (QML names): `name, holdings, trades, goal, pace, analytics, summary, presets, goalTargetValue, realizedRaw, realizedSign, goalProgressPct, estYearlyRaw, equityCurve, equityCurveMinY/MaxY, equityPaceLine, equityCurveMode, availableTags, totalTradeCount, loaded, textFilter, statusFilter, dateRangeKey, tagFilter`. Slots: `setDateRange, setTagFilter, setTextFilter, setStatusFilter, setEquityCurveMode`. Python: `update(...)` (full), `update_marks(marks)` (cheap). |
| `AccountController.pace` | QVariantMap | `state` (ahead/behind/reached/start/none), `sentence`, `fraction`, `paceFraction` (0..1), `targetText`, `endText`, `expectedText`, `expectedRaw`, `realizedText`, `deltaRaw`. Pace = target × elapsed / (elapsed + remaining) trading days, same as `compute_goal_progress`. |
| `ThemeController` | QObject (`app.theme`) | Cached tokens: `bg, card, cardAlt, text, textMuted, button, primary, secondary, border, good, bad, textOnColor, pace`, plus `isLight, fontFamily, displayFontFamily, reduceMotion, fontScale`. `refresh()` reloads + emits `themeChanged`. |
| `AppController` | QObject (`app`) | Properties `theme, watchlist, accounts, accountCount, currentAccount, currentAccountIndex, username, isAdmin, statusText, statusColor, equityCurveVisible`. Slots `setCurrentAccountIndex, addTicker, removeTicker, renameTicker, refreshMarks, addTrade, editTrade, deleteTrade, setGoalTarget, showHoldingsMenu, showTradeMenu, openGoalOptions, openTradeHistoryOptions` (all forward to MainWindow callbacks). Python: `set_callbacks, rebuild_accounts, refresh_all_accounts, apply_marks, set_watchlist, watchlist_symbols, set_status, set_equity_curve_visible`. |

## Data and state
No persistence. Caches per account: last trades / goal trades / marks / goal target / presets, mark-independent intermediates (`_holdings_base`, `_realized_base`, goal equivalents, `_goal_has_closed`), and the unfiltered trade rows (with a pre-lowered `haystack` for search). `AppController._marks_by_symbol` holds the merged marks payloads (`{sym: {"price": ...}}`); main_window reads it directly.

## How to change it safely
- Update paths (all UI thread): marks tick -> `apply_marks` -> `update_marks` touches only holdings/summary/goal/pace and emits `metricsChanged` only if a value changed. Filter changes -> `_recompute_trade_side` (emits `analyticsChanged`). Trade saves -> `refresh_all_accounts` (reads the store; with RemoteDataStore that can be a network call right after a save invalidated its cache).
- Signals: `metricsChanged` = goal/pace/summary/presets/raws; `analyticsChanged` = analytics, curve, pace line, tags, trade count, curve mode. A property's notify signal is invisible to QML, but QML `on<Signal>` handlers would break if a signal were renamed: don't.
- `sourceIndex` must stay the index into the unfiltered account trade list (edit/delete/move use it). Rows are displayed newest-first (pending on top); sorting never changes `sourceIndex`.
- `status` role/filter values stay the upper-case codes (WAITING/OPEN/SHORT/CLOSED/COVERED); show `statusText` instead.
- Keep names used by main_window: see "Used by". portfolio.py is the single source of the maths (mirrored in pwa/js/portfolio.js) — don't re-implement P/L here.
- Verify: `python -m compileall -q stock_insights/qml_bridge.py`, `python -m pytest tests -q`, `python scripts/ui_snapshot.py --out <dir>` (watch stderr for QML warnings).

## Map
- 1-60 docstring, imports, constants
- 65-165 formatting helpers
- 171-231 WatchlistModel; 233-313 HoldingsModel; 315-386 TradesModel + role table
- 393-615 AccountController properties + filter slots
- 617-707 curve builder, filter, `update`, `update_marks`
- 709-806 `_recompute_trade_side` (analytics, rows, curve)
- 808-918 pace line, `_recompute_mark_side`, `_pace_map`
- 924-1048 ThemeController
- 1054-end AppController (properties, account refresh, marks, slots, `_call`)
