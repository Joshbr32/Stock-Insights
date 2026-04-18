"""qml_bridge.py — Adapters that expose the existing Trade / Holding /
portfolio-math layer to QML.

Architecture
────────────
    AppController (root, exposed to QML as `app`)
        ├── ThemeController        — color tokens driven by ThemeManager
        ├── WatchlistModel         — QAbstractListModel (symbol + live price)
        └── accounts: [AccountController]
                ├── HoldingsModel  — QAbstractListModel
                ├── TradesModel    — QAbstractListModel
                ├── goal:     dict exposed as Q_PROPERTY
                ├── analytics: dict exposed as Q_PROPERTY
                └── summary:   dict exposed as Q_PROPERTY

All heavy computation still lives in `portfolio.py`. This module is just a
view-model layer — it watches trades + marks and feeds formatted strings
(and raw numbers where QML wants them) into the QML scene.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Property,
    Qt,
    Signal,
    Slot,
)

from .portfolio import (
    Trade,
    compute_goal_progress,
    compute_holdings_from_trades,
    compute_portfolio,
    compute_realized_pl_by_symbol,
    compute_trade_analytics,
    compute_trade_rows,
)


# ---------------------------------------------------------------------------
# Formatting helpers (keep parity with portfolio_tab.py)
# ---------------------------------------------------------------------------

def _money(value: Optional[float]) -> str:
    return "—" if value is None else f"$ {float(value):,.2f}"


def _goal_money(value: Optional[float]) -> str:
    return "—" if value is None else f"$ {float(value):,.0f}"


def _pct(value: Optional[float]) -> str:
    return "—" if value is None else f"{float(value):,.2f}%"


def _int(value: Optional[int]) -> str:
    return "—" if value is None else f"{int(value):,d}"


def _date(value) -> str:
    return "—" if value is None else value.isoformat()


def _preset_label(value: float) -> str:
    if value >= 1_000_000:
        return f"{(value / 1_000_000):g}M"
    if value >= 1_000:
        return f"{(value / 1_000):g}K"
    return f"{value:g}"


def _sign(value: Optional[float]) -> int:
    """Return +1 / -1 / 0 — used by QML to color metric values
    green (profit), red (loss), or neutral."""
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def _profit_factor_text(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}x"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class WatchlistModel(QAbstractListModel):
    SymbolRole = Qt.UserRole + 1
    PriceRole = Qt.UserRole + 2
    PriceTextRole = Qt.UserRole + 3

    countChanged = Signal()

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    # QML can bind to `app.watchlist.count` and re-evaluate reactively,
    # whereas calling rowCount() from QML doesn't notify on changes.
    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == self.SymbolRole:
            return row["symbol"]
        if role == self.PriceRole:
            return row["price"]
        if role == self.PriceTextRole:
            p = row["price"]
            return "—" if p is None else f"{p:,.2f}"
        return None

    def roleNames(self) -> Dict[int, QByteArray]:
        return {
            self.SymbolRole: QByteArray(b"symbol"),
            self.PriceRole: QByteArray(b"price"),
            self.PriceTextRole: QByteArray(b"priceText"),
        }

    def set_symbols(self, symbols: List[str]) -> None:
        previous = len(self._rows)
        self.beginResetModel()
        self._rows = [{"symbol": s, "price": None} for s in symbols]
        self.endResetModel()
        if previous != len(self._rows):
            self.countChanged.emit()

    def update_prices(self, marks: Dict[str, Dict[str, Optional[float]]]) -> None:
        for i, row in enumerate(self._rows):
            info = marks.get(row["symbol"], {})
            new_price = info.get("price")
            if new_price != row["price"]:
                row["price"] = new_price
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.PriceRole, self.PriceTextRole])

    def symbols(self) -> List[str]:
        return [r["symbol"] for r in self._rows]


class HoldingsModel(QAbstractListModel):
    InstrumentRole = Qt.UserRole + 1
    QtyTextRole = Qt.UserRole + 2
    AvgCostRole = Qt.UserRole + 3
    MarkRole = Qt.UserRole + 4
    UnrealizedPlRole = Qt.UserRole + 5
    UnrealizedSignRole = Qt.UserRole + 6
    MarketValueRole = Qt.UserRole + 7
    WeightRole = Qt.UserRole + 8
    IsShortRole = Qt.UserRole + 9

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        if role == self.InstrumentRole: return r["instrument"]
        if role == self.QtyTextRole: return r["qty_text"]
        if role == self.AvgCostRole: return r["avg_cost"]
        if role == self.MarkRole: return r["mark"]
        if role == self.UnrealizedPlRole: return r["unrealized"]
        if role == self.UnrealizedSignRole: return r["unrealized_sign"]
        if role == self.MarketValueRole: return r["market_value"]
        if role == self.WeightRole: return r["weight"]
        if role == self.IsShortRole: return r["is_short"]
        return None

    def roleNames(self) -> Dict[int, QByteArray]:
        return {
            self.InstrumentRole: QByteArray(b"instrument"),
            self.QtyTextRole: QByteArray(b"qtyText"),
            self.AvgCostRole: QByteArray(b"avgCost"),
            self.MarkRole: QByteArray(b"mark"),
            self.UnrealizedPlRole: QByteArray(b"unrealizedPl"),
            self.UnrealizedSignRole: QByteArray(b"unrealizedSign"),
            self.MarketValueRole: QByteArray(b"marketValue"),
            self.WeightRole: QByteArray(b"weight"),
            self.IsShortRole: QByteArray(b"isShort"),
        }

    def set_rows(self, views) -> None:
        self.beginResetModel()
        out: List[Dict[str, Any]] = []
        for h in views:
            is_short = h.qty < 0
            qty_text = f"{abs(h.qty):,d} (SHORT)" if is_short else f"{h.qty:,d}"
            sign = 0
            if h.unrealized_pl > 0:
                sign = 1
            elif h.unrealized_pl < 0:
                sign = -1
            out.append({
                "instrument": h.instrument,
                "qty_text": qty_text,
                "avg_cost": _money(h.avg_cost),
                "mark": "—" if h.mark is None else f"$ {float(h.mark):,.2f}",
                "unrealized": _money(h.unrealized_pl),
                "unrealized_sign": sign,
                "market_value": _money(h.market_value),
                "weight": _pct(h.weight_pct),
                "is_short": is_short,
            })
        self._rows = out
        self.endResetModel()


class TradesModel(QAbstractListModel):
    InstrumentRole = Qt.UserRole + 1
    ShareCountRole = Qt.UserRole + 2
    StatusRole = Qt.UserRole + 3
    BuyPriceRole = Qt.UserRole + 4
    SellPriceRole = Qt.UserRole + 5
    TradeProfitRole = Qt.UserRole + 6
    ProfitSignRole = Qt.UserRole + 7
    OpenDateRole = Qt.UserRole + 8
    CloseDateRole = Qt.UserRole + 9
    DaysRole = Qt.UserRole + 10
    AvgDailyRole = Qt.UserRole + 11
    NotesRole = Qt.UserRole + 12
    SourceIndexRole = Qt.UserRole + 13
    IsPendingRole = Qt.UserRole + 14
    IsShortRole = Qt.UserRole + 15

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        return r.get(_TRADE_ROLE_KEY.get(role))

    def roleNames(self) -> Dict[int, QByteArray]:
        return _TRADE_ROLE_NAMES

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def source_index_for(self, view_row: int) -> Optional[int]:
        if 0 <= view_row < len(self._rows):
            value = self._rows[view_row].get("source_index")
            return int(value) if value is not None else None
        return None


_TRADE_ROLE_KEY = {
    TradesModel.InstrumentRole: "instrument",
    TradesModel.ShareCountRole: "share_count",
    TradesModel.StatusRole: "status",
    TradesModel.BuyPriceRole: "buy_price",
    TradesModel.SellPriceRole: "sell_price",
    TradesModel.TradeProfitRole: "trade_profit",
    TradesModel.ProfitSignRole: "profit_sign",
    TradesModel.OpenDateRole: "open_date",
    TradesModel.CloseDateRole: "close_date",
    TradesModel.DaysRole: "days",
    TradesModel.AvgDailyRole: "avg_daily",
    TradesModel.NotesRole: "notes",
    TradesModel.SourceIndexRole: "source_index",
    TradesModel.IsPendingRole: "is_pending",
    TradesModel.IsShortRole: "is_short",
}
_TRADE_ROLE_NAMES = {role: QByteArray(name.encode("ascii"))
                     for role, name in {
                         TradesModel.InstrumentRole: "instrument",
                         TradesModel.ShareCountRole: "shareCount",
                         TradesModel.StatusRole: "status",
                         TradesModel.BuyPriceRole: "buyPrice",
                         TradesModel.SellPriceRole: "sellPrice",
                         TradesModel.TradeProfitRole: "tradeProfit",
                         TradesModel.ProfitSignRole: "profitSign",
                         TradesModel.OpenDateRole: "openDate",
                         TradesModel.CloseDateRole: "closeDate",
                         TradesModel.DaysRole: "daysToClose",
                         TradesModel.AvgDailyRole: "avgDaily",
                         TradesModel.NotesRole: "notes",
                         TradesModel.SourceIndexRole: "sourceIndex",
                         TradesModel.IsPendingRole: "isPending",
                         TradesModel.IsShortRole: "isShort",
                     }.items()}


# ---------------------------------------------------------------------------
# Per-account controller
# ---------------------------------------------------------------------------

class AccountController(QObject):
    """Exposes one account's computed data to QML.

    Whole-object property bags (goal, analytics, summary, presets) are plain
    QVariantMap / QVariantList so QML can bind to them directly as
    `account.goal.realized` etc.

    Filter state (textFilter, statusFilter) lives here per-account so that
    switching tabs preserves each account's filter independently. When the
    filter changes the underlying TradesModel is reset with the filtered
    subset — so hidden rows are *removed* from the model rather than just
    hidden in the delegate, which means no gaps in the list view.
    """

    metricsChanged = Signal()
    filterChanged = Signal()
    loadedChanged = Signal()

    def __init__(self, name: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._name = name
        self._holdings = HoldingsModel(self)
        self._trades = TradesModel(self)
        self._goal: Dict[str, Any] = {}
        self._analytics: Dict[str, str] = {}
        self._summary: Dict[str, str] = {}
        self._presets: List[Dict[str, Any]] = []
        self._goal_target_value: float = 500_000.0
        # Raw numeric values used by QML progress bars / gauges. Kept
        # separately from the formatted `goal` string dict so visual widgets
        # don't have to parse currency strings back to numbers.
        self._realized_raw: float = 0.0
        self._goal_progress_pct: float = 0.0
        self._est_yearly_raw: Optional[float] = None
        # Full unfiltered trade list — kept so we can re-apply filter without
        # round-tripping through the data store.
        self._all_trade_rows: List[Dict[str, Any]] = []
        self._text_filter: str = ""
        self._status_filter: str = ""
        self._loaded: bool = False

    @Property(str, constant=True)
    def name(self) -> str:
        return self._name

    @Property(QObject, constant=True)
    def holdings(self) -> QObject:
        return self._holdings

    @Property(QObject, constant=True)
    def trades(self) -> QObject:
        return self._trades

    @Property("QVariantMap", notify=metricsChanged)
    def goal(self) -> Dict[str, Any]:
        return self._goal

    @Property("QVariantMap", notify=metricsChanged)
    def analytics(self) -> Dict[str, str]:
        return self._analytics

    @Property("QVariantMap", notify=metricsChanged)
    def summary(self) -> Dict[str, str]:
        return self._summary

    @Property("QVariantList", notify=metricsChanged)
    def presets(self) -> List[Dict[str, Any]]:
        return self._presets

    @Property(float, notify=metricsChanged)
    def goalTargetValue(self) -> float:
        return self._goal_target_value

    # Raw realized profit and progress-to-goal percentage — used by QML
    # visual widgets (progress bars etc.) that need real numbers, not
    # formatted currency strings.
    @Property(float, notify=metricsChanged)
    def realizedRaw(self) -> float:
        return self._realized_raw

    @Property(float, notify=metricsChanged)
    def goalProgressPct(self) -> float:
        return self._goal_progress_pct

    @Property(float, notify=metricsChanged)
    def estYearlyRaw(self) -> float:
        return 0.0 if self._est_yearly_raw is None else float(self._est_yearly_raw)

    # Sign of the realized P/L — used by the Goal Dashboard's Realized
    # Profit hero to color the number green (profit), red (loss), or neutral.
    @Property(int, notify=metricsChanged)
    def realizedSign(self) -> int:
        return _sign(self._realized_raw)

    # ── Loaded flag — false until update() has been called at least once.
    # QML uses this to suppress the "No trades yet" placeholder during the
    # brief window between QML mounting and the first data refresh.
    @Property(bool, notify=loadedChanged)
    def loaded(self) -> bool:
        return self._loaded

    # ── Filter state ────────────────────────────────────────────────────────
    @Property(str, notify=filterChanged)
    def textFilter(self) -> str:
        return self._text_filter

    @Property(str, notify=filterChanged)
    def statusFilter(self) -> str:
        return self._status_filter

    @Property(int, notify=metricsChanged)
    def totalTradeCount(self) -> int:
        return len(self._all_trade_rows)

    @Slot(str)
    def setTextFilter(self, text: str) -> None:
        new = (text or "").strip()
        if new != self._text_filter:
            self._text_filter = new
            self.filterChanged.emit()
            self._reapply_filter()

    @Slot(str)
    def setStatusFilter(self, status: str) -> None:
        new = (status or "").strip()
        if new != self._status_filter:
            self._status_filter = new
            self.filterChanged.emit()
            self._reapply_filter()

    def _reapply_filter(self) -> None:
        rows = self._all_trade_rows
        text = self._text_filter.lower()
        status = self._status_filter
        if text or status:
            filtered: List[Dict[str, Any]] = []
            for r in rows:
                if status and r.get("status") != status:
                    continue
                if text:
                    haystack = " ".join((
                        r.get("instrument", ""),
                        r.get("status", ""),
                        r.get("notes", ""),
                    )).lower()
                    if text not in haystack:
                        continue
                filtered.append(r)
            rows = filtered
        self._trades.set_rows(rows)

    def update(
            self,
            account_trades: List[Trade],
            goal_trades: List[Trade],
            marks: Dict[str, Optional[float]],
            goal_target: float,
            presets: List[float],
    ) -> None:
        holdings = compute_holdings_from_trades(account_trades)
        realized = compute_realized_pl_by_symbol(account_trades)
        holding_views, summary = compute_portfolio(holdings, marks, realized)
        analytics = compute_trade_analytics(account_trades)

        goal_holdings = compute_holdings_from_trades(goal_trades)
        goal_realized = compute_realized_pl_by_symbol(goal_trades)
        _, goal_summary = compute_portfolio(goal_holdings, marks, goal_realized)
        goal = compute_goal_progress(
            goal_trades, goal_target, unrealized_profit=goal_summary.unrealized_pl,
        )

        trade_rows = compute_trade_rows(account_trades)
        enriched: List[Dict[str, Any]] = []
        for r in trade_rows:
            source = account_trades[r.index]
            profit_sign = 0
            if r.trade_profit is not None:
                profit_sign = 1 if r.trade_profit > 0 else (-1 if r.trade_profit < 0 else 0)
            enriched.append({
                "instrument": r.instrument,
                "share_count": f"{r.share_count:,d}",
                "status": r.status,
                "buy_price": _money(r.buy_price),
                "sell_price": _money(r.sell_price),
                "trade_profit": _money(r.trade_profit),
                "profit_sign": profit_sign,
                "open_date": _date(r.open_date),
                "close_date": _date(r.close_date),
                "days": _int(r.days_to_close),
                "avg_daily": _money(r.avg_daily_return),
                "notes": source.notes or "",
                "source_index": int(r.index),
                "is_pending": bool(source.is_pending),
                "is_short": bool(source.is_short),
            })

        self._holdings.set_rows(holding_views)
        # Store the full set so filter changes don't have to re-fetch from
        # the data store, then publish the filtered subset to QML.
        self._all_trade_rows = enriched
        self._reapply_filter()

        self._goal_target_value = float(goal_target)
        # Raw progress metrics for visual widgets (progress bar, gauges).
        self._realized_raw = float(goal.realized_profit)
        if goal_target > 0:
            pct = (self._realized_raw / goal_target) * 100.0
            # Clamp to [0, 100] so the progress bar never exceeds the track
            # when you've already blown past your goal (still profitable!).
            self._goal_progress_pct = max(0.0, min(100.0, pct))
        else:
            self._goal_progress_pct = 0.0
        self._est_yearly_raw = analytics.est_yearly_profit
        self._presets = [
            {"label": _preset_label(p), "value": float(p)}
            for p in presets
        ]
        # Year-End Forecast — realized so far plus a straight projection of
        # the current avg-daily-profit over the remaining trading days. Shown
        # where "Realized Profit" used to live in the grid (which is now the
        # hero, so no point duplicating).
        year_end_forecast: Optional[float]
        if goal.avg_daily_profit is not None and goal.business_days_remaining >= 0:
            year_end_forecast = (
                    float(goal.realized_profit)
                    + float(goal.avg_daily_profit) * int(goal.business_days_remaining)
            )
        else:
            year_end_forecast = None

        self._goal = {
            "target": _goal_money(goal.goal_target),
            "realized": _money(goal.realized_profit),
            "unrealized": _money(goal.unrealized_profit),
            "remaining": _money(goal.remaining_profit),
            "monthly": _money(goal.monthly_profit_to_goal),
            "weekly": _money(goal.weekly_profit_to_goal),
            "daily": _money(goal.daily_profit_to_goal),
            "avgDaily": _money(goal.avg_daily_profit),
            "catchUp": _money(goal.profit_to_match_daily_avg),
            "daysElapsed": f"{goal.business_days_elapsed:,d}",
            "daysRemaining": f"{goal.business_days_remaining:,d}",
            "yearEndForecast": _money(year_end_forecast),
            "yearEndForecastSign": _sign(year_end_forecast),
            "unrealizedSign": _sign(goal.unrealized_profit),
            "remainingSign": _sign(goal.remaining_profit),
        }
        self._analytics = {
            # Counts (always non-negative, neutral color)
            "openTrades": f"{analytics.open_trades:,d}",
            "closedTrades": f"{analytics.closed_trades:,d}",
            # Trade-quality block — always-positive / always-negative metrics
            # get a fixed sign; variable-sign metrics get _sign() based on the
            # raw numeric value so coloring matches the actual data.
            "winRate": _pct(analytics.win_rate_pct),
            "winRateSign": 0,
            "profitFactor": _profit_factor_text(analytics.profit_factor),
            "profitFactorSign": 0 if analytics.profit_factor is None
            else (1 if analytics.profit_factor >= 1.0 else -1),
            "avgProfit": _money(analytics.avg_profit_per_trade),
            "avgProfitSign": _sign(analytics.avg_profit_per_trade),
            "avgWin": _money(analytics.avg_win),
            "avgWinSign": _sign(analytics.avg_win),
            "avgLoss": _money(analytics.avg_loss),
            "avgLossSign": _sign(analytics.avg_loss),
            "bestTrade": _money(analytics.best_trade),
            "bestTradeSign": _sign(analytics.best_trade),
            "worstTrade": _money(analytics.worst_trade),
            "worstTradeSign": _sign(analytics.worst_trade),
            # Pace + projection
            "avgRoi": _pct(analytics.avg_roi_pct),
            "avgRoiSign": _sign(analytics.avg_roi_pct),
            "avgDailyReturn": _money(analytics.avg_daily_closed_profit),
            "avgDailyReturnSign": _sign(analytics.avg_daily_closed_profit),
            "estYearly": _money(analytics.est_yearly_profit),
            "estYearlySign": _sign(analytics.est_yearly_profit),
        }
        self._summary = {
            "marketValue": _money(summary.market_value),
            "costBasis": _money(summary.cost_basis),
            "unrealizedPl": _money(summary.unrealized_pl),
            "totalPl": _money(summary.total_pl),
        }
        self.metricsChanged.emit()
        if not self._loaded:
            self._loaded = True
            self.loadedChanged.emit()


# ---------------------------------------------------------------------------
# Theme controller
# ---------------------------------------------------------------------------

class ThemeController(QObject):
    """Exposes color tokens from ThemeManager to QML as Q_PROPERTYs.

    QML binds to `theme.bg`, `theme.card`, etc. When the user changes theme
    via Settings, MainWindow calls `refresh()` and every binding updates.
    """

    themeChanged = Signal()

    def __init__(self, theme_manager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._theme = theme_manager

    def refresh(self) -> None:
        self.themeChanged.emit()

    def _tokens(self) -> Optional[Dict[str, str]]:
        try:
            return self._theme._tokens()
        except Exception:
            return None

    def _fallback(self, name: str) -> str:
        try:
            is_light = self._theme._is_light()
        except Exception:
            is_light = False
        if is_light:
            table = {
                "bg": "#ffffff", "card": "#f8fafc",
                "card2": "#eef2f7", "text": "#0f1115",
                "text_muted": "#4b5563", "button": "#ffffff",
                "primary": "#0a66c2", "secondary": "#0a66c2",
                "border": "#e5e7eb", "good": "#15803d",
                "bad": "#b91c1c", "text_on_color": "#ffffff",
            }
        else:
            table = {
                "bg": "#0f1115", "card": "#151922",
                "card2": "#1b2029", "text": "#e6eaf2",
                "text_muted": "#a0a8b5", "button": "#1f2430",
                "primary": "#60a5fa", "secondary": "#60a5fa",
                "border": "#242a36", "good": "#6ee78a",
                "bad": "#f87171", "text_on_color": "#0b0f15",
            }
        return table.get(name, "#000000")

    def _color(self, name: str) -> str:
        tokens = self._tokens()
        if tokens and name in tokens:
            return tokens[name]
        return self._fallback(name)

    # Color Q_PROPERTYs. All change signals share themeChanged.
    @Property(str, notify=themeChanged)
    def bg(self) -> str:
        return self._color("bg")

    @Property(str, notify=themeChanged)
    def card(self) -> str:
        return self._color("card")

    @Property(str, notify=themeChanged)
    def cardAlt(self) -> str:
        return self._color("card2")

    @Property(str, notify=themeChanged)
    def text(self) -> str:
        return self._color("text")

    @Property(str, notify=themeChanged)
    def textMuted(self) -> str:
        return self._color("text_muted")

    @Property(str, notify=themeChanged)
    def button(self) -> str:
        return self._color("button")

    @Property(str, notify=themeChanged)
    def primary(self) -> str:
        return self._color("primary")

    @Property(str, notify=themeChanged)
    def secondary(self) -> str:
        return self._color("secondary")

    @Property(str, notify=themeChanged)
    def border(self) -> str:
        return self._color("border")

    @Property(str, notify=themeChanged)
    def good(self) -> str:
        return self._color("good")

    @Property(str, notify=themeChanged)
    def bad(self) -> str:
        return self._color("bad")

    @Property(str, notify=themeChanged)
    def textOnColor(self) -> str:
        return self._color("text_on_color")


# ---------------------------------------------------------------------------
# Root controller exposed to QML as `app`
# ---------------------------------------------------------------------------

class AppController(QObject):
    accountsChanged = Signal()
    currentAccountChanged = Signal()
    statusChanged = Signal()
    adminChanged = Signal()

    def __init__(self, store, theme_manager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._store = store
        self._theme_manager = theme_manager
        self._theme_controller = ThemeController(theme_manager, self)
        self._watchlist = WatchlistModel(self)
        self._accounts: List[AccountController] = []
        self._current_index = 0
        self._marks_by_symbol: Dict[str, Dict[str, Optional[float]]] = {}
        self._status_text = "● Connecting…"
        self._status_color = "#9ca3af"
        self._username = str(store.username)
        self._is_admin = bool(store.is_admin)

        # Python-side callbacks wired by MainWindow after __init__.
        self._callbacks: Dict[str, Callable] = {}

    # ---- wiring ----

    def set_callbacks(self, callbacks: Dict[str, Callable]) -> None:
        self._callbacks = dict(callbacks)

    # ---- properties exposed to QML ----

    @Property(QObject, constant=True)
    def theme(self) -> QObject:
        return self._theme_controller

    @Property(QObject, constant=True)
    def watchlist(self) -> QObject:
        return self._watchlist

    @Property("QVariantList", notify=accountsChanged)
    def accounts(self) -> List[QObject]:
        return list(self._accounts)

    @Property(int, notify=accountsChanged)
    def accountCount(self) -> int:
        return len(self._accounts)

    @Property(QObject, notify=currentAccountChanged)
    def currentAccount(self) -> Optional[QObject]:
        if 0 <= self._current_index < len(self._accounts):
            return self._accounts[self._current_index]
        return None

    @Property(int, notify=currentAccountChanged)
    def currentAccountIndex(self) -> int:
        return self._current_index

    @Property(str, constant=True)
    def username(self) -> str:
        return self._username

    @Property(bool, notify=adminChanged)
    def isAdmin(self) -> bool:
        return self._is_admin

    @Property(str, notify=statusChanged)
    def statusText(self) -> str:
        return self._status_text

    @Property(str, notify=statusChanged)
    def statusColor(self) -> str:
        return self._status_color

    # ---- status ----

    def set_status(self, text: str, color: str) -> None:
        if (text, color) != (self._status_text, self._status_color):
            self._status_text = text
            self._status_color = color
            self.statusChanged.emit()

    # ---- account management ----

    def rebuild_accounts(self) -> None:
        """(Re)create AccountControllers to match the store's account list."""
        try:
            names = self._store.get_account_names()
        except Exception:
            names = ["Default"]
        self._accounts = [AccountController(n, self) for n in names]
        if self._current_index >= len(self._accounts):
            self._current_index = max(0, len(self._accounts) - 1)
        self.accountsChanged.emit()
        self.currentAccountChanged.emit()

    def refresh_all_accounts(self) -> None:
        try:
            trades = self._store.get_all_trades()
        except Exception:
            trades = []
        try:
            shared_names, _ = self._store.get_goal_group()
            shared_set = set(shared_names)
        except Exception:
            shared_set = set()

        marks = {sym: info.get("price") for sym, info in self._marks_by_symbol.items()}

        for account in self._accounts:
            account_trades = [t for t in trades if (t.account or "").strip() == account.name]
            try:
                target = float(self._store.get_goal_target(account.name))
                presets = list(self._store.get_goal_presets(account.name))
            except Exception:
                target = 500_000.0
                presets = [250_000.0, 500_000.0, 1_000_000.0]
            goal_trades = (
                [t for t in trades if (t.account or "").strip() in shared_set]
                if account.name in shared_set else account_trades
            )
            account.update(
                account_trades=account_trades,
                goal_trades=goal_trades,
                marks=marks,
                goal_target=target,
                presets=presets,
            )

    # ---- watchlist ----

    def set_watchlist(self, symbols: List[str]) -> None:
        self._watchlist.set_symbols(symbols)
        self._watchlist.update_prices(self._marks_by_symbol)

    def watchlist_symbols(self) -> List[str]:
        return self._watchlist.symbols()

    # ---- marks ----

    def apply_marks(self, marks: Dict[str, Dict[str, Optional[float]]]) -> None:
        for sym, info in marks.items():
            existing = dict(self._marks_by_symbol.get(sym, {}))
            existing.update(info)
            self._marks_by_symbol[sym] = existing
        self._watchlist.update_prices(self._marks_by_symbol)
        self.refresh_all_accounts()

    # ---- slots QML calls back into ----

    @Slot(int)
    def setCurrentAccountIndex(self, index: int) -> None:
        if 0 <= index < len(self._accounts) and index != self._current_index:
            self._current_index = index
            self.currentAccountChanged.emit()

    @Slot()
    def addTicker(self) -> None:
        self._call("add_ticker")

    @Slot(int)
    def removeTicker(self, row: int) -> None:
        self._call("remove_ticker", row)

    @Slot(int, str)
    def renameTicker(self, row: int, new_symbol: str) -> None:
        self._call("rename_ticker", row, new_symbol)

    @Slot()
    def refreshMarks(self) -> None:
        self._call("refresh_marks")

    @Slot()
    def addTrade(self) -> None:
        self._call("add_trade")

    @Slot(int)
    def editTrade(self, source_index: int) -> None:
        self._call("edit_trade", int(source_index))

    @Slot(int)
    def deleteTrade(self, source_index: int) -> None:
        self._call("delete_trade", int(source_index))

    @Slot(float)
    def setGoalTarget(self, value: float) -> None:
        self._call("set_goal_target", float(value))

    @Slot(str)
    def showHoldingsMenu(self, instrument: str) -> None:
        self._call("holdings_menu", instrument)

    @Slot(int)
    def showTradeMenu(self, source_index: int) -> None:
        self._call("trade_menu", int(source_index))

    @Slot()
    def openGoalOptions(self) -> None:
        self._call("open_goal_options")

    @Slot()
    def openTradeHistoryOptions(self) -> None:
        self._call("open_trade_history_options")

    def _call(self, name: str, *args) -> None:
        cb = self._callbacks.get(name)
        if cb is None:
            return
        try:
            cb(*args)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("callback '%s' raised", name)
