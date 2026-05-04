"""server_quotes_patch.py — adds a /quotes endpoint to the FastAPI server.

WHY THIS FILE EXISTS
────────────────────
The desktop client uses yfinance directly to fetch live prices. The PWA
runs in a browser, so it can't import yfinance — and Yahoo Finance blocks
direct browser requests with CORS. The fix is to proxy quotes through
your own FastAPI server, which already has yfinance installed.

HOW TO APPLY
────────────
Open misc_helpers/server.py and paste the block below ABOVE the
"# Connection test" section (anywhere among the route handlers works,
but that spot keeps related code together).

Then restart the server. The PWA will hit GET /quotes?symbols=AAPL,MSFT,...
and receive {"AAPL": 187.45, "MSFT": 412.10, ...}.

────────────────────────────────────────────────────────────────────────
PASTE BELOW THIS LINE INTO misc_helpers/server.py
────────────────────────────────────────────────────────────────────────
"""

# ---------------------------------------------------------------------------
# Quotes  (live prices for the mobile / web client)
# ---------------------------------------------------------------------------
#
# yfinance is already a dependency of the desktop client; the server reuses
# it here so the PWA doesn't need to talk to Yahoo directly (which CORS
# blocks anyway). Results are cached in-process for QUOTE_TTL seconds so
# rapid-fire polling from a phone screen doesn't spam Yahoo.

import time
from threading import Lock

try:
    import yfinance as _yf

    _YF_OK = True
except ImportError:
    _YF_OK = False

_QUOTE_CACHE: dict[str, tuple[float, float]] = {}  # symbol -> (price, fetched_at)
_QUOTE_LOCK = Lock()
QUOTE_TTL = 20.0  # seconds


def _fetch_one_quote(symbol: str) -> float | None:
    """Best-effort single-symbol price fetch. Returns None on failure."""
    try:
        fi = _yf.Ticker(symbol).fast_info
        last = fi.get("last_price")
        if last is not None:
            return float(last)
    except Exception:
        pass
    try:
        df = _yf.download(
            tickers=symbol, period="1d", interval="1m",
            progress=False, threads=False,
        )
        if df is not None and "Close" in df:
            close = df["Close"].dropna()
            if len(close):
                return float(close.iloc[-1])
    except Exception:
        pass
    return None


@app.get("/quotes")
def get_quotes(symbols: str = "", user: dict = Depends(current_user)):
    """Return {symbol: price_or_null} for a comma-separated symbol list.

    Auth-gated so anonymous traffic can't drive up our yfinance usage.
    Cached in-process for QUOTE_TTL seconds per symbol.
    """
    if not _YF_OK:
        raise HTTPException(503, "yfinance not installed on server")

    requested = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    requested = list(dict.fromkeys(requested))  # de-dupe, preserve order
    if not requested:
        return {}

    now = time.time()
    out: dict[str, float | None] = {}
    to_fetch: list[str] = []

    with _QUOTE_LOCK:
        for sym in requested:
            cached = _QUOTE_CACHE.get(sym)
            if cached and (now - cached[1]) < QUOTE_TTL:
                out[sym] = cached[0]
            else:
                to_fetch.append(sym)

    # Fetch fresh ones outside the lock so concurrent requests don't block.
    fresh: dict[str, float | None] = {}
    for sym in to_fetch:
        price = _fetch_one_quote(sym)
        fresh[sym] = price

    with _QUOTE_LOCK:
        for sym, price in fresh.items():
            if price is not None:
                _QUOTE_CACHE[sym] = (price, now)
            out[sym] = price

    return out
