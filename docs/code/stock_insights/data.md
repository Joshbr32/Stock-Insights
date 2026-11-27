# stock_insights/data.py
**Purpose:** Fetches live prices ("marks") from Yahoo via yfinance.
**Used by:** `workers.py` (`MarksWorker.run`, on a QThread).  **Depends on:** `yfinance` (1.8 in the venv), `logging_utils`.

## Key types and functions
| Name | Kind | What it does / contract |
|---|---|---|
| `fetch_marks(tickers)` | fn | Returns `{SYMBOL: {"price", "bid", "ask"}}` for the de-duplicated, upper-cased symbols. Blocks on the network, so never call it on the UI thread. Never raises for per-symbol failures: an unpriceable symbol gets `price=None`. Makes one batched `yf.download(interval="1m", period="1d", group_by="ticker", threads=False, timeout=10)`, then a per-symbol `fast_info.last_price` request only for symbols the batch could not price. |
| `_batch_close(df, ticker)` | fn | The last non-NaN Close for the ticker. Handles the (ticker, field) MultiIndex that yfinance returns even for a single symbol, as well as flat frames. |
| `_configure_yfinance_cache()` | fn (runs at import) | Points the yfinance tz cache at `%TEMP%/StockInsights/yfinance`. Failures are logged at debug level and ignored. |
| `_BATCH_TIMEOUT_S` | const | The batch request timeout (10 s, the yfinance default). |

## Data and state
No app state. yfinance keeps its own sqlite tz cache in `%TEMP%/StockInsights/yfinance`. Quotes are not cached between calls.

## How to change it safely
- `bid`/`ask` are always None today: yfinance's `FastInfo` has no such keys. The shape is kept because callers read it.
- Keep `threads=False`. yfinance's thread pool inside a QThread has crashed Python 3.13+ on Windows.
- When the whole batch fails (rate limit or offline), every symbol falls back to its own request, which adds load at exactly the wrong moment. See the deferred item in the audit report.
- No tests cover this file (it needs network). To test `_batch_close`, build small pandas frames.

## Map
- 1-21 docstring, imports, timeout const
- 24-36 yfinance cache setup
- 39-55 `_batch_close`, `_fmt`
- 58-127 `fetch_marks`
