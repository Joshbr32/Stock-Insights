"""Live price ("marks") fetching via yfinance.

`fetch_marks` is called from `workers.MarksWorker` on a QThread, never on
the UI thread: it blocks on network I/O. It never raises for per-symbol
failures; a symbol that cannot be priced comes back with price=None.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List, Optional

import yfinance as yf

from .logging_utils import get_logger

logger = get_logger("data")

# Seconds yf.download waits for Yahoo before giving up on the batch request
# (yfinance's own default, stated explicitly so it is visible and tunable).
_BATCH_TIMEOUT_S = 10


def _configure_yfinance_cache() -> None:
    """Route yfinance's sqlite cache into a known writable app folder."""
    base_dir = tempfile.gettempdir()
    cache_dir = Path(base_dir) / "StockInsights" / "yfinance"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        yf.set_tz_cache_location(str(cache_dir))
    except Exception as exc:
        # Import-time side effect: never let a read-only temp dir stop the app.
        logger.debug("Could not set yfinance cache directory: %s", exc)


_configure_yfinance_cache()


def _batch_close(df, ticker: str) -> Optional[float]:
    """Last non-NaN 1-minute close for `ticker` from a yf.download frame.

    With group_by="ticker", yfinance returns (ticker, field) MultiIndex
    columns even for a single symbol, so select by ticker whenever it is a
    top-level column; only a flat frame is read as-is.
    """
    try:
        sub = df[ticker] if ticker in df.columns.get_level_values(0) else df
        return float(sub["Close"].dropna().iloc[-1])
    except Exception:
        # Missing column, empty frame (delisted / no trades yet today) etc.
        return None


def _fmt(value) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "None"


def fetch_marks(tickers: List[str]) -> dict:
    """Return {ticker: {price, bid, ask}} with batching plus per-symbol fallback.

    One batched yf.download for all symbols; only symbols the batch could
    not price fall back to a per-symbol `fast_info.last_price` request.
    """
    symbols = list(dict.fromkeys((ticker or "").strip().upper() for ticker in tickers if ticker))
    out = {ticker: {"price": None, "bid": None, "ask": None} for ticker in symbols}
    if not symbols:
        logger.debug("fetch_marks skipped: no instruments")
        return out

    logger.debug("fetch_marks start: %s", ", ".join(symbols))

    df = None
    try:
        df = yf.download(
            tickers=symbols,
            interval="1m",
            period="1d",
            group_by="ticker",
            progress=False,
            # threads=False: yfinance's internal thread pool nests badly with
            # QThread on Windows and has been seen to trigger C-level crashes
            # on Python 3.13+. One HTTP roundtrip per batch is plenty fast.
            threads=False,
            timeout=_BATCH_TIMEOUT_S,
        )
        logger.debug("yfinance batch download succeeded for %d instrument(s)", len(symbols))
    except Exception as exc:
        logger.warning("yfinance batch download failed: %s", exc)
        df = None

    for ticker in symbols:
        price = _batch_close(df, ticker) if df is not None else None
        bid = None
        ask = None

        # Per-symbol fallback only when the batch had no price: each
        # fast_info.last_price is its own network request, so doing it
        # for every symbol on every tick multiplied traffic by N.
        # (yfinance's FastInfo has no bid/ask keys, so the old
        # unconditional lookup always produced None for them anyway.)
        if price is None:
            try:
                fi = yf.Ticker(ticker).fast_info
            except Exception as exc:
                logger.debug("fast_info failed for %s: %s", ticker, exc)
                fi = None
            if fi:
                try:
                    last_price = fi.get("last_price")
                    price = float(last_price) if last_price is not None else None
                except Exception:
                    price = None
                try:
                    bid = fi.get("bid")
                    ask = fi.get("ask")
                except Exception:
                    bid = ask = None

        out[ticker] = {"price": price, "bid": bid, "ask": ask}
        logger.debug(
            "Mark result %s -> price=%s bid=%s ask=%s",
            ticker, _fmt(price), _fmt(bid), _fmt(ask),
        )

    success_count = sum(1 for row in out.values() if row.get("price") is not None)
    logger.info("fetch_marks completed: %d/%d instrument(s) priced", success_count, len(symbols))
    return out
