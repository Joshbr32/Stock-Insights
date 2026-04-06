from __future__ import annotations

from typing import Dict, List, Optional

import yfinance as yf

from .logging_utils import get_logger


logger = get_logger("data")


def fetch_marks(tickers: List[str]) -> dict:
    """Return {ticker: {price, bid, ask}} with batching plus per-symbol fallback."""
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
            threads=True,
        )
        logger.debug("yfinance batch download succeeded for %d instrument(s)", len(symbols))
    except Exception as exc:
        logger.warning("yfinance batch download failed: %s", exc)

    for ticker in symbols:
        price = None
        bid = None
        ask = None
        fi = None

        if df is not None:
            try:
                sub = df[ticker] if len(symbols) > 1 and ticker in df else df
                price = float(sub["Close"].dropna().iloc[-1])
            except Exception:
                price = None

        try:
            fi = yf.Ticker(ticker).fast_info
        except Exception as exc:
            logger.debug("fast_info failed for %s: %s", ticker, exc)
            fi = None

        if price is None and fi:
            try:
                last_price = fi.get("last_price")
                price = float(last_price) if last_price is not None else None
            except Exception:
                price = None

        if fi:
            try:
                bid = fi.get("bid")
                ask = fi.get("ask")
            except Exception:
                bid = ask = None

        out[ticker] = {"price": price, "bid": bid, "ask": ask}
        logger.debug(
            "Mark result %s -> price=%s bid=%s ask=%s",
            ticker,
            f"{price:.2f}" if isinstance(price, (int, float)) else "None",
            f"{bid:.2f}" if isinstance(bid, (int, float)) else "None",
            f"{ask:.2f}" if isinstance(ask, (int, float)) else "None",
        )

    success_count = sum(1 for row in out.values() if row.get("price") is not None)
    logger.info("fetch_marks completed: %d/%d instrument(s) priced", success_count, len(symbols))
    return out
