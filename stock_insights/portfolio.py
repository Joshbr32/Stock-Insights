from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


# ---------- NYSE trading-calendar support ----------
# Uses pandas_market_calendars when available; falls back to weekday counting.

try:
    import pandas_market_calendars as _mcal  # type: ignore
    _nyse_cal = _mcal.get_calendar("NYSE")
    _TRADING_CAL_OK = True
except Exception:
    _nyse_cal = None
    _TRADING_CAL_OK = False


def _nyse_day_count(start: date, end: date) -> int:
    """Count NYSE trading days between start and end (inclusive)."""
    if end < start:
        return 0
    if _TRADING_CAL_OK and _nyse_cal is not None:
        try:
            sched = _nyse_cal.schedule(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
            return len(sched)
        except Exception:
            pass
    # Weekday fallback if library unavailable or call fails
    count, cur = 0, start
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


# ---------- Core models ----------


@dataclass
class Trade:
    instrument: str
    share_count: int
    buy_price: float          # long: buy price;  short: entry (short) price
    sell_price: Optional[float] = None  # long: sell price; short: cover price
    open_date: Optional[date] = None
    close_date: Optional[date] = None
    notes: str = ""
    account: str = ""
    is_pending: bool = False  # True = unconfirmed/waiting order (excluded from calcs)
    is_short: bool = False    # True = short position (sell first, buy to cover)

    def normalized_instrument(self) -> str:
        return (self.instrument or "").strip().upper()

    @property
    def is_closed(self) -> bool:
        return self.sell_price is not None and self.close_date is not None

    @property
    def status(self) -> str:
        if self.is_pending:
            return "WAITING"
        if self.is_short:
            return "COVERED" if self.is_closed else "SHORT"
        return "CLOSED" if self.is_closed else "OPEN"

    @property
    def trade_profit(self) -> Optional[float]:
        if not self.is_closed or self.sell_price is None:
            return None
        if self.is_short:
            # Short profit: shorted high, covered low
            return (float(self.buy_price) - float(self.sell_price)) * int(self.share_count)
        return (float(self.sell_price) - float(self.buy_price)) * int(self.share_count)

    @property
    def cost_basis(self) -> float:
        return float(self.buy_price) * int(self.share_count)


@dataclass
class TradeRow:
    index: int
    instrument: str
    share_count: int
    status: str
    buy_price: float
    sell_price: Optional[float]
    trade_profit: Optional[float]
    open_date: Optional[date]
    close_date: Optional[date]
    days_to_close: Optional[int]
    avg_daily_return: Optional[float]


@dataclass
class Holding:
    instrument: str
    qty: int
    avg_cost: float
    notes: str = ""

    def normalized_instrument(self) -> str:
        return (self.instrument or "").strip().upper()

    @property
    def cost_basis(self) -> float:
        return float(self.qty) * float(self.avg_cost)


@dataclass
class HoldingView:
    instrument: str
    qty: int
    avg_cost: float
    mark: Optional[float]
    market_value: float
    weight_pct: float
    unrealized_pl: float
    realized_pl: float
    total_pl: float
    notes: str = ""


@dataclass
class PortfolioSummary:
    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_pl: float = 0.0
    realized_pl: float = 0.0
    total_pl: float = 0.0
    positions: int = 0
    return_pct: Optional[float] = None


@dataclass
class TradeAnalytics:
    realized_profit: float = 0.0
    closed_trades: int = 0
    open_trades: int = 0
    avg_profit_per_trade: Optional[float] = None
    avg_trade_value: Optional[float] = None
    avg_roi_pct: Optional[float] = None
    total_roi_pct: Optional[float] = None
    avg_daily_closed_profit: Optional[float] = None


@dataclass
class GoalProgress:
    goal_target: float
    realized_profit: float
    unrealized_profit: float
    total_profit: float
    remaining_profit: float
    monthly_profit_to_goal: Optional[float]
    weekly_profit_to_goal: Optional[float]
    daily_profit_to_goal: Optional[float]
    avg_daily_profit: Optional[float]
    profit_to_match_daily_avg: Optional[float]
    business_days_elapsed: int
    business_days_remaining: int


# ---------- Helpers ----------


def parse_date(value) -> Optional[date]:
    if value in (None, "", "—", "-"):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {value}")


def date_to_str(value: Optional[date]) -> str:
    return value.isoformat() if value else ""


def business_days_between(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if start is None or end is None:
        return None
    if end < start:
        return 0
    return _nyse_day_count(start, end)


def business_days_elapsed_in_year(today: Optional[date] = None) -> int:
    today = today or date.today()
    return _nyse_day_count(date(today.year, 1, 1), today)


def business_days_remaining_in_year(today: Optional[date] = None) -> int:
    today = today or date.today()
    return _nyse_day_count(today, date(today.year, 12, 31))


def _current_months_remaining(today: date) -> int:
    return max(1, 12 - today.month + 1)


def _weeks_remaining(today: date) -> int:
    days_left = max(0, (date(today.year, 12, 31) - today).days)
    return max(1, (days_left + 6) // 7)


# ---------- Trade serialization ----------


def trade_to_dict(trade: Trade) -> dict:
    return {
        "instrument": trade.normalized_instrument(),
        "share_count": int(trade.share_count),
        "buy_price": float(trade.buy_price),
        "sell_price": None if trade.sell_price is None else float(trade.sell_price),
        "open_date": date_to_str(trade.open_date),
        "close_date": date_to_str(trade.close_date),
        "notes": trade.notes or "",
        "account": (trade.account or "").strip(),
        "is_pending": bool(trade.is_pending),
        "is_short": bool(trade.is_short),
    }


def trade_from_dict(data: dict) -> Optional[Trade]:
    if not isinstance(data, dict):
        return None
    instrument = str(data.get("instrument", "")).strip().upper()
    if not instrument:
        return None
    try:
        share_count = int(float(data.get("share_count", 0) or 0))
        buy_price = float(data.get("buy_price", 0.0) or 0.0)
        sell_raw = data.get("sell_price", None)
        sell_price = None if sell_raw in (None, "", "—", "-") else float(sell_raw)
        return Trade(
            instrument=instrument,
            share_count=max(0, share_count),
            buy_price=buy_price,
            sell_price=sell_price,
            open_date=parse_date(data.get("open_date")),
            close_date=parse_date(data.get("close_date")),
            notes=str(data.get("notes", "") or ""),
            account=str(data.get("account", "") or "").strip(),
            is_pending=bool(data.get("is_pending", False)),
            is_short=bool(data.get("is_short", False)),
        )
    except Exception:
        return None


def trades_to_json(trades: Sequence[Trade]) -> str:
    return json.dumps([trade_to_dict(t) for t in trades], indent=2)


def trades_from_json(raw) -> List[Trade]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    out: List[Trade] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        trade = trade_from_dict(item)
        if trade is not None and trade.share_count > 0:
            out.append(trade)
    return out


def solve_buy_mark_for_target_avg(
    current_qty: int,
    current_avg_cost: float,
    buy_qty: int,
    target_mark: float,
) -> float:
    """Return the buy price required to bring the blended average cost down to target_mark."""
    if current_qty <= 0:
        raise ValueError("Buy (Mark Down) requires an existing holding.")
    if buy_qty <= 0:
        raise ValueError("Qty must be greater than zero.")
    if target_mark <= 0:
        raise ValueError("Target Mark must be greater than zero.")
    total_qty = current_qty + buy_qty
    return ((target_mark * total_qty) - (current_avg_cost * current_qty)) / buy_qty


# ---------- Calculations ----------


def sort_trades(trades: Iterable[Trade]) -> List[Trade]:
    def sort_key(item: tuple[int, Trade]):
        original_index, trade = item
        is_open = not trade.is_closed
        close_key = trade.close_date if trade.close_date is not None else date.max
        open_key = trade.open_date if trade.open_date is not None else date.max
        symbol = trade.normalized_instrument()
        return (is_open, close_key, symbol, open_key, original_index)

    indexed = list(enumerate(trades))
    return [trade for _, trade in sorted(indexed, key=sort_key)]


def compute_trade_rows(trades: Iterable[Trade]) -> List[TradeRow]:
    rows: List[TradeRow] = []
    for idx, trade in enumerate(list(trades)):
        profit = trade.trade_profit
        days = business_days_between(trade.open_date, trade.close_date) if trade.is_closed else None
        avg_daily = (profit / days) if (profit is not None and days not in (None, 0)) else None
        rows.append(
            TradeRow(
                index=idx,
                instrument=trade.normalized_instrument(),
                share_count=int(trade.share_count),
                status=trade.status,
                buy_price=float(trade.buy_price),
                sell_price=None if trade.sell_price is None else float(trade.sell_price),
                trade_profit=profit,
                open_date=trade.open_date,
                close_date=trade.close_date,
                days_to_close=days,
                avg_daily_return=avg_daily,
            )
        )
    return rows


def compute_holdings_from_trades(trades: Iterable[Trade]) -> List[Holding]:
    # Separate buckets for long (positive qty) and short (negative qty)
    grouped: Dict[str, dict] = {}
    for trade in trades:
        if trade.is_closed or trade.is_pending:
            continue
        instrument = trade.normalized_instrument()
        if not instrument or trade.share_count <= 0:
            continue
        key = f"{instrument}:SHORT" if trade.is_short else instrument
        bucket = grouped.setdefault(key, {
            "instrument": instrument, "qty": 0, "cost": 0.0,
            "notes": [], "is_short": trade.is_short,
        })
        bucket["qty"] += int(trade.share_count)
        bucket["cost"] += float(trade.buy_price) * int(trade.share_count)
        if trade.notes:
            bucket["notes"].append(trade.notes)

    holdings: List[Holding] = []
    for payload in grouped.values():
        qty = int(payload["qty"])
        if qty <= 0:
            continue
        avg_cost = payload["cost"] / qty
        notes = " | ".join([n for n in payload["notes"] if n])
        # Short holdings stored with negative qty so the UI can distinguish them
        display_qty = -qty if payload["is_short"] else qty
        holdings.append(Holding(
            instrument=payload["instrument"],
            qty=display_qty,
            avg_cost=avg_cost,
            notes=notes,
        ))
    return sorted(holdings, key=lambda h: (h.qty >= 0, h.normalized_instrument()))


def compute_realized_pl_by_symbol(trades: Iterable[Trade]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for trade in trades:
        if not trade.is_closed or trade.is_pending:
            continue
        symbol = trade.normalized_instrument()
        out[symbol] = out.get(symbol, 0.0) + float(trade.trade_profit or 0.0)
    return out


def compute_portfolio(
    holdings: Iterable[Holding],
    marks: Dict[str, Optional[float]],
    realized_by_symbol: Optional[Dict[str, float]] = None,
) -> Tuple[List[HoldingView], PortfolioSummary]:
    realized_by_symbol = realized_by_symbol or {}
    cleaned: List[Holding] = []
    for holding in holdings:
        instrument = holding.normalized_instrument()
        qty = int(holding.qty)
        if not instrument or qty == 0:
            continue
        cleaned.append(
            Holding(
                instrument=instrument,
                qty=qty,
                avg_cost=float(holding.avg_cost),
                notes=holding.notes or "",
            )
        )

    total_market_value = 0.0
    gross_market_value = 0.0
    gross_cost_basis = 0.0
    staged: List[Tuple[Holding, Optional[float], float, float, float]] = []

    for holding in cleaned:
        mark = marks.get(holding.instrument)
        cost_basis = holding.cost_basis
        market_value = (float(mark) * holding.qty) if mark is not None else 0.0
        unrealized_pl = (market_value - cost_basis) if mark is not None else 0.0
        realized_pl = float(realized_by_symbol.get(holding.instrument, 0.0))
        total_market_value += market_value
        gross_market_value += abs(market_value)
        gross_cost_basis += abs(cost_basis)
        staged.append((holding, mark, market_value, unrealized_pl, realized_pl))

    rows: List[HoldingView] = []
    total_unrealized = 0.0
    for holding, mark, market_value, unrealized_pl, realized_pl in staged:
        total_unrealized += unrealized_pl
        weight_pct = (abs(market_value) / gross_market_value * 100.0) if gross_market_value > 0 else 0.0
        rows.append(
            HoldingView(
                instrument=holding.instrument,
                qty=holding.qty,
                avg_cost=holding.avg_cost,
                mark=mark,
                market_value=market_value,
                weight_pct=weight_pct,
                unrealized_pl=unrealized_pl,
                realized_pl=realized_pl,
                total_pl=realized_pl + unrealized_pl,
                notes=holding.notes,
            )
        )

    all_realized = float(sum(realized_by_symbol.values()))
    summary = PortfolioSummary(
        market_value=total_market_value,
        cost_basis=gross_cost_basis,
        unrealized_pl=total_unrealized,
        realized_pl=all_realized,
        total_pl=all_realized + total_unrealized,
        positions=len(rows),
        return_pct=((total_unrealized / gross_cost_basis) * 100.0) if gross_cost_basis > 0 else None,
    )
    return rows, summary


def compute_trade_analytics(trades: Iterable[Trade]) -> TradeAnalytics:
    trades_list = list(trades)
    closed = [t for t in trades_list if t.is_closed and t.trade_profit is not None and not t.is_pending]
    profits = [float(t.trade_profit or 0.0) for t in closed]
    trade_values = [float(t.buy_price) * int(t.share_count) for t in closed]
    realized_profit = sum(profits)
    elapsed = business_days_elapsed_in_year()

    avg_profit_per_trade = (realized_profit / len(closed)) if closed else None
    avg_trade_value = (sum(trade_values) / len(trade_values)) if trade_values else None
    avg_roi_pct = (
        (avg_profit_per_trade / avg_trade_value) * 100.0
        if (avg_profit_per_trade is not None and avg_trade_value not in (None, 0))
        else None
    )

    total_trade_value = sum(trade_values) if trade_values else 0.0
    total_roi_pct = ((realized_profit / total_trade_value) * 100.0) if total_trade_value > 0 else None

    return TradeAnalytics(
        realized_profit=realized_profit,
        closed_trades=len(closed),
        open_trades=sum(1 for t in trades_list if not t.is_closed),
        avg_profit_per_trade=avg_profit_per_trade,
        avg_trade_value=avg_trade_value,
        avg_roi_pct=avg_roi_pct,
        total_roi_pct=total_roi_pct,
        avg_daily_closed_profit=(realized_profit / elapsed) if elapsed > 0 else None,
    )


def compute_goal_progress(
    trades: Iterable[Trade],
    goal_target: float,
    unrealized_profit: float = 0.0,
    today: Optional[date] = None,
) -> GoalProgress:
    today = today or date.today()
    realized_profit = sum(float(t.trade_profit or 0.0) for t in trades if t.is_closed and not t.is_pending)
    total_profit = realized_profit + float(unrealized_profit)
    remaining_profit = float(goal_target) - realized_profit

    elapsed = business_days_elapsed_in_year(today)
    remaining_days = business_days_remaining_in_year(today)

    monthly_target = (
        (remaining_profit / _current_months_remaining(today))
        if _current_months_remaining(today) > 0
        else None
    )
    weekly_target = (
        (remaining_profit / _weeks_remaining(today)) if _weeks_remaining(today) > 0 else None
    )
    daily_target = (remaining_profit / remaining_days) if remaining_days > 0 else None
    avg_daily_profit = (realized_profit / elapsed) if elapsed > 0 else None

    total_days = elapsed + remaining_days
    expected_by_now = (float(goal_target) * elapsed / total_days) if total_days > 0 else 0.0
    profit_to_match_daily_avg = max(0.0, expected_by_now - realized_profit)

    return GoalProgress(
        goal_target=float(goal_target),
        realized_profit=float(realized_profit),
        unrealized_profit=float(unrealized_profit),
        total_profit=float(total_profit),
        remaining_profit=float(remaining_profit),
        monthly_profit_to_goal=monthly_target,
        weekly_profit_to_goal=weekly_target,
        daily_profit_to_goal=daily_target,
        avg_daily_profit=avg_daily_profit,
        profit_to_match_daily_avg=profit_to_match_daily_avg,
        business_days_elapsed=elapsed,
        business_days_remaining=remaining_days,
    )
