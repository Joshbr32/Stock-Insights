"""Modal dialogs lifted out of portfolio_tab.py.

Re-exports everything at the package level so existing call sites can
write `from stock_insights.dialogs import TradeEditDialog` without
caring which sub-module the class actually lives in. portfolio_tab.py
also re-exports these for back-compat with `from .portfolio_tab import
TradeEditDialog`.
"""
from .goal_options import GoalDashboardOptionsDialog
from .trade_actions import (
    DoubleDownDialog,
    FulfillOrderDialog,
    MarkDownDialog,
)
from .trade_edit import TradeEditDialog
from .trade_history_columns import TradeHistoryColumnsDialog

__all__ = [
    "GoalDashboardOptionsDialog",
    "TradeEditDialog",
    "TradeHistoryColumnsDialog",
    "FulfillOrderDialog",
    "MarkDownDialog",
    "DoubleDownDialog",
]
