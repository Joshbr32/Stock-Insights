from dataclasses import dataclass
from typing import Optional


@dataclass
class TradeInputs:
    qty: float
    buy_price: float
    sell_price: Optional[float] = None
    commission_buy: float = 0.0
    commission_sell: float = 0.0
    leverage: float = 1.0  # 1x = no margin; 2x = half cash, etc.


@dataclass
class TradeResults:
    gross_cost: float                   # qty*buy_price + commission_buy
    cash_required: float                # gross_cost / leverage
    proceeds_at_sell: Optional[float]   # qty*sell_price - commission_sell
    profit_at_sell: Optional[float]     # proceeds - gross_cost
    required_sell_for_target: Optional[float]  # if target given, else None


def _sanitize_leverage(leverage: float) -> float:
    try:
        l = float(leverage)
    except Exception:
        l = 1.0
    # Never allow leverage < 1.0
    return max(1.0, l)


def trade_cost(qty: float, buy_price: float, commission_buy: float, leverage: float) -> tuple[float, float]:
    """
    Return (gross_cost, cash_required).

    leverage:
      - 1.0  => no margin (pay full cost)
      - 2.0  => 2x buying power (pay half cash)
      - 4.0  => 4x buying power (pay one quarter cash)
    """
    leverage = _sanitize_leverage(leverage)
    gross_cost = qty * buy_price + commission_buy
    cash_required = gross_cost / leverage
    return gross_cost, cash_required


def profit_at_sell(qty: float, buy_price: float, sell_price: float, commission_buy: float, commission_sell: float) -> float:
    """Net P/L after buy+sell commissions. Margin interest excluded."""
    cost = qty * buy_price + commission_buy
    proceeds = qty * sell_price - commission_sell
    return proceeds - cost


def sell_price_for_target_profit(qty: float, buy_price: float, target_profit: float,
                                 commission_buy: float, commission_sell: float) -> float:
    """
    Solve for sell price Y so that:
        (qty*Y - commission_sell) - (qty*buy + commission_buy) = target_profit
    =>  qty*Y = target_profit + qty*buy + commission_buy + commission_sell
    =>  Y = (target_profit + qty*buy + commission_buy + commission_sell) / qty
    """
    if qty == 0:
        return float("nan")
    return (target_profit + qty * buy_price + commission_buy + commission_sell) / qty
