# pwa/js/app.js
**Purpose:** Entry module of the PWA: app state, data loading from the FastAPI server, every view (login, home, trades, goals, watchlist, settings), the trade editor and drill-down dialogs, backup/restore, background quote refresh, service-worker registration.
**Used by:** `pwa/index.html` (`<script type="module">`).  **Depends on:** `api.js` (`Api`), `portfolio.js` (all maths), `charts.js` (`paceRail`, `equityChart`), `ui.js` (DOM builders, formatters, `store`), `demo.js` (dynamic import, only with `?demo`).

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `State` | object | Single source of truth: accounts, normalized trades, `byAccount` index, goalGroup, watchlist, marks, quote status, selected account, current view, filters, animated-rail keys. |
| `loadAll()` | async | Fetches accounts, trades, goal group, watchlist in parallel, rebuilds the index, then `refreshMarks()`. Throws API errors (401 => caller shows login). |
| `reloadTrades()` | async | After a write: re-fetch trades only; quotes only if a new open symbol appeared. |
| `refreshMarks()` | async | Fetch quotes for open symbols + watchlist. Never throws except 401; on failure keeps old marks and sets `quotesOk=false`. Returns true if anything changed. |
| `goalForSelection()` | fn | Goal for the home pace rail: the account's `goal_target`; for "All" the shared goal group, else the sum of targets. `covers` says whether the goal's trades equal the selection's (pace line only then). |
| `toTradeIn(t)` | fn | Builds the `TradeIn` payload (incl. `uid` and `tag`) for both the per-trade and the bulk PUT. Used by save, delete fallback, backup. |
| `renderShell()` / `renderView()` | fn | Shell is built once (top bar, outlet, tab bar; nodes kept in `Shell`). `renderView` swaps only the outlet and updates `aria-current` on tabs. |
| `viewHome/Trades/Goals/Watchlist/Settings` | fn | Return a fresh subtree. Filter controls re-render only their section via `rerenderSection()`, which restores focus to the changed control. |
| `performanceSection()` | fn | Filters, equity curve (with pace line when `goal.covers && range=all && no tag`), analytics. |
| `openTradeEditor` / `saveTradeFromForm` / `deleteTrade` | fn | Form handling; a new trade gets its `uid` (`newTradeUid`) before the first save so a retry cannot duplicate it. Errors shown inline in the dialog. |
| `writeTrades(perTrade, legacy)`, `saveTrade`, `removeTrade` | fn | Per-trade writes (`Api.putTrade` / `deleteTradeByUid`; a move is a PUT under the new account). On 404/405 (`Api.isLegacyRouteError`) sets module flag `perTradeRoutes=false` and uses whole-account replaces for the rest of the session (a move rewrites both accounts). Trades are matched by `uid`. |
| `pollQuotes`, `startPolling`, `stopPolling` | fn | 60 s quote poll only while `document.visibilityState === "visible"`; `visibilitychange` stops it, and on return reloads everything if > 5 min stale. Skips re-render while a dialog is open or a form control in the view has focus (`safeToRerender`). |
| `openDialog` / `closeDialog` | fn | Native `<dialog>.showModal()` bottom sheet: focus trap, Escape, backdrop click closes; focus returns to the opener (or the view). |
| `buildBackupSnapshot`, `validateBackupShape`, `applyBackupSnapshot` | fn | Backup format = `stock_insights/io_utils.py` schema 1 (trades include `uid`). Restore always uses the bulk PUT; it keeps a valid, first-seen `uid` and drops a malformed or repeated one so the server generates it instead of rejecting the account (422). Reports which parts failed. |
| `isOffline(err)` / `friendly(err, fallback)` | fn | api.js reports unreachable server as `code 0`; these turn errors into sentences. |

## Data and state
- localStorage (via `ui.js` `store`, all try/catch): `si.dateRange` (all|week|month|30d|ytd), `si.curveMode` (trades|daily). Old keys `date_range_key` / `equity_curve_mode` are migrated once and removed. Auth keys `si.token` / `si.user` belong to api.js.
- Tag filter and selected account are deliberately not persisted.
- No portfolio data is cached locally; offline the shell opens but shows the load-error screen.

## How to change it safely
- All maths comes from `portfolio.js`, which must match `stock_insights/portfolio.py`; do not compute P/L here.
- Never use `innerHTML`; build with `el()`/`svg()` so symbols, notes, tags and account names stay text.
- Keep `api.js` call signatures; `demo.js` replaces the same method names.
- New modules must be added to `SHELL` in `pwa/sw.js` and `VERSION` bumped on any shell change.
- Copy follows Harbor: sentence case, verbs on buttons ("Log trade"), result toast reuses the verb ("Trade logged"), signed numbers with U+2212.
- Goal / analytics field names are portfolio.py's (`realized_profit`, `monthly_profit_to_goal`, ...); `profit_factor` null renders "—".
- Pace rails get `hasClosed` (any closed, non-pending trade) so a new account shows the start state, like the desktop.
- Check visually with `python -m http.server --directory pwa` and `?demo`, `?demo=login`, `?demo=offline`, `?demo=legacy` (pre-1.1 server fallback).

## Map
- 1-84 imports, prefs migration, constants, `State`
- 85-215 data loading, derived data, `hasClosedTrade`, `goalForSelection`, `toTradeIn`
- 217-247 errors and toast
- 248-346 boot, loading, boot error, login
- 347-506 shell, tabs, manual refresh, background polling
- 507-575 shared view helpers (field, kv, panel, filters, rerenderSection)
- 576-757 home view, holdings, performance, drill-down
- 758-897 trades view, trade editor
- 898-994 trade writes (per-trade + legacy fallback), save/delete
- 995-1099 goals, watchlist
- 1100-1261 settings, backup/restore
- 1262-1305 dialog, service worker, `boot()`
