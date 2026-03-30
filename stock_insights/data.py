from __future__ import annotations

from datetime import timezone
import datetime as dt
import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from .logging_utils import get_logger


logger = get_logger("data")


def safe_get(d: Dict[str, Any], key: str, default=None):
    try:
        val = d.get(key, default)
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return default
        return val if val is not None else default
    except Exception:
        return default


def compute_rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    gain_ewm = pd.Series(gain).ewm(alpha=1 / period, adjust=False).mean()
    loss_ewm = pd.Series(loss).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain_ewm / (loss_ewm.replace(0, np.nan))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not math.isnan(rsi.iloc[-1]) else float("nan")


def percent_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    try:
        return (a - b) / b * 100.0 if b != 0 else None
    except Exception:
        return None


def human_money(n: Optional[float]) -> Optional[str]:
    if n is None:
        return None
    try:
        n = float(n)
    except Exception:
        return None
    abs_n = abs(n)
    if abs_n >= 1_000_000_000_000:
        return f"{n / 1_000_000_000_000:.2f}T"
    if abs_n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.2f}K"
    return f"{n:.2f}"


def get_stock_snapshot(ticker: str) -> Dict[str, Any]:
    ticker = (ticker or "").strip().upper()
    logger.debug("Building snapshot for %s", ticker)
    t = yf.Ticker(ticker)

    try:
        fast = t.fast_info if hasattr(t, "fast_info") else {}
    except Exception as exc:
        logger.debug("fast_info unavailable for %s: %s", ticker, exc)
        fast = {}

    try:
        info = t.info
    except Exception as exc:
        logger.warning("info fetch failed for %s: %s", ticker, exc)
        info = {}

    try:
        hist = t.history(period="1y", interval="1d", auto_adjust=True)
    except Exception as exc:
        logger.warning("history fetch failed for %s: %s", ticker, exc)
        hist = pd.DataFrame()

    price = None
    fifty_sma = twohund_sma = rsi14 = fifty_two_w_high = fifty_two_w_low = None
    price_to_50sma = price_to_200sma = None

    if not hist.empty and "Close" in hist.columns:
        closes = hist["Close"].dropna()
        if not closes.empty:
            price = float(closes.iloc[-1])
            fifty_sma = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
            twohund_sma = float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None
            rsi14 = compute_rsi(closes, period=14) if len(closes) >= 15 else None
            fifty_two_w_high = float(closes.max())
            fifty_two_w_low = float(closes.min())
            price_to_50sma = percent_diff(price, fifty_sma) if fifty_sma else None
            price_to_200sma = percent_diff(price, twohund_sma) if twohund_sma else None

    long_name = safe_get(info, "longName", safe_get(info, "shortName", ticker))
    exchange = safe_get(info, "exchange", safe_get(fast, "exchange"))
    currency = safe_get(info, "currency", safe_get(fast, "currency", "USD"))
    sector = safe_get(info, "sector")
    industry = safe_get(info, "industry")
    country = safe_get(info, "country")
    website = safe_get(info, "website")

    market_cap = safe_get(info, "marketCap", safe_get(fast, "market_cap"))
    enterprise_value = safe_get(info, "enterpriseValue")
    shares_out = safe_get(info, "sharesOutstanding")

    trailing_pe = safe_get(info, "trailingPE")
    forward_pe = safe_get(info, "forwardPE")
    price_to_book = safe_get(info, "priceToBook")
    price_to_sales_ttm = safe_get(info, "priceToSalesTrailing12Months")

    beta = safe_get(info, "beta")
    dividend_yield = safe_get(info, "dividendYield")
    payout_ratio = safe_get(info, "payoutRatio")

    profit_margins = safe_get(info, "profitMargins")
    operating_margins = safe_get(info, "operatingMargins")
    gross_margins = safe_get(info, "grossMargins")

    revenue_ttm = safe_get(info, "totalRevenue")
    ebitda = safe_get(info, "ebitda")
    net_income = safe_get(info, "netIncomeToCommon")

    snapshot: Dict[str, Any] = {
        "as_of": dt.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "ticker": ticker,
        "company": {
            "name": long_name,
            "exchange": exchange,
            "currency": currency,
            "sector": sector,
            "industry": industry,
            "country": country,
            "website": website,
        },
        "quote": {
            "price": price if price is not None else safe_get(fast, "last_price"),
            "market_cap": market_cap,
            "enterprise_value": enterprise_value,
            "shares_outstanding": shares_out,
            "trailing_pe": trailing_pe,
            "forward_pe": forward_pe,
            "price_to_book": price_to_book,
            "price_to_sales_ttm": price_to_sales_ttm,
            "beta": beta,
            "dividend_yield": dividend_yield,
            "payout_ratio": payout_ratio,
        },
        "margins": {
            "profit_margins": profit_margins,
            "operating_margins": operating_margins,
            "gross_margins": gross_margins,
        },
        "financials": {
            "revenue_ttm": revenue_ttm,
            "ebitda": ebitda,
            "net_income": net_income,
        },
        "technicals": {
            "rsi_14": rsi14,
            "sma_50": fifty_sma,
            "sma_200": twohund_sma,
            "price_vs_sma50_pct": price_to_50sma,
            "price_vs_sma200_pct": price_to_200sma,
            "fifty_two_week_high": fifty_two_w_high,
            "fifty_two_week_low": fifty_two_w_low,
        },
    }

    prev_close = safe_get(info, "previousClose", safe_get(fast, "previous_close"))
    open_px = safe_get(info, "open", safe_get(fast, "open"))
    bid = safe_get(info, "bid", safe_get(fast, "bid"))
    ask = safe_get(info, "ask", safe_get(fast, "ask"))
    day_low = safe_get(info, "dayLow", safe_get(fast, "day_low"))
    day_high = safe_get(info, "dayHigh", safe_get(fast, "day_high"))
    vol = safe_get(info, "volume", safe_get(fast, "day_volume"))
    avg_vol = (
        safe_get(info, "averageVolume")
        or safe_get(info, "averageDailyVolume10Day")
        or safe_get(info, "averageVolume10days")
        or safe_get(fast, "ten_day_average_volume")
    )

    snapshot["overview"] = {
        "previous_close": prev_close,
        "open": open_px,
        "bid": bid,
        "ask": ask,
        "day_low": day_low,
        "day_high": day_high,
        "fifty_two_week_low": snapshot["technicals"]["fifty_two_week_low"],
        "fifty_two_week_high": snapshot["technicals"]["fifty_two_week_high"],
        "volume": vol,
        "avg_volume": avg_vol,
        "market_cap": market_cap,
    }

    snapshot["_history_close"] = hist["Close"].dropna().tolist() if not hist.empty else []
    logger.debug("Snapshot built for %s (history points=%d)", ticker, len(snapshot["_history_close"]))
    return snapshot


def fetch_marks(tickers: List[str]) -> dict:
    """Return {ticker: {price,bid,ask}} with batching plus per-symbol fallback."""
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
