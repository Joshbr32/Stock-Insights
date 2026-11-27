"""qml_bridge.py — view-model layer that exposes trades, holdings, goal and
theme data to the QML scene (stock_insights/qml/*.qml).

Architecture
────────────
    AppController (root, exposed to QML as `app`)
        ├── ThemeController        — cached colour tokens + fonts from ThemeManager
        ├── WatchlistModel         — QAbstractListModel (symbol + live price)
        └── accounts: [AccountController]
                ├── HoldingsModel  — QAbstractListModel
                ├── TradesModel    — QAbstractListModel
                ├── goal / pace / summary   (notify: metricsChanged)
                └── analytics / equity curve / tags (notify: analyticsChanged)

All P/L maths lives in `portfolio.py`; this module only caches inputs,
calls those pure functions, and formats strings for display.

Update paths (cheapest first) — keep them separate, they run on the UI thread:
  * marks tick   -> AppController.apply_marks -> AccountController.update_marks:
                    holdings + summary + goal/pace only. No store reads, no
                    trade-row rebuild, no equity-curve repaint.
  * filter change (date range / tag / text / status) -> trade-side only.
  * trades saved -> AppController.refresh_all_accounts (reads the store).
Signals fire only when the published values actually changed, so an
unchanged marks tick does not re-evaluate any QML binding.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta
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
    filter_trades_by_date_range_with_orig_index,
)
from .theme import FONT_SIZES, reduce_motion_enabled, resolve_fonts

_log = logging.getLogger(__name__)

MINUS = "−"  # real minus sign; design rule: never a hyphen for negatives
DASH = "—"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


# ---------------------------------------------------------------------------
# Formatting helpers. Unsigned values (prices, costs, values) never show "+";
# P/L values are signed. symbol_history_dialog.py keeps the older "$ x" style.
# ---------------------------------------------------------------------------

def _money(value: Optional[float]) -> str:
    """$1,234.56 / −$1,234.56 — for prices, costs and market values."""
    if value is None:
        return DASH
    v = float(value)
    return f"{MINUS if v < 0 else ''}${abs(v):,.2f}"


def _signed_money(value: Optional[float]) -> str:
    """+$412.50 / −$88.00 / $0.00 — for profit and loss."""
    if value is None:
        return DASH
    v = float(value)
    if abs(v) < 0.005:
        return "$0.00"
    return f"{'+' if v > 0 else MINUS}${abs(v):,.2f}"


def _goal_money(value: Optional[float]) -> str:
    """Whole dollars, for goal targets and pace amounts."""
    if value is None:
        return DASH
    v = float(value)
    return f"{MINUS if v < 0 else ''}${abs(v):,.0f}"


def _pct(value: Optional[float]) -> str:
    return DASH if value is None else f"{float(value):,.1f}%"


def _signed_pct(value: Optional[float]) -> str:
    if value is None:
        return DASH
    v = float(value)
    if abs(v) < 0.05:
        return "0.0%"
    return f"{'+' if v > 0 else MINUS}{abs(v):,.1f}%"


def _arrow_pct(value: Optional[float]) -> str:
    """▲ 4.2% / ▼ 1.3% — table change column, so colour is never the only cue."""
    if value is None:
        return DASH
    v = float(value)
    if abs(v) < 0.05:
        return "0.0%"
    return f"{'▲' if v > 0 else '▼'} {abs(v):,.1f}%"


def _int(value: Optional[int]) -> str:
    return DASH if value is None else f"{int(value):,d}"


def _date(value: Optional[date], today: Optional[date] = None) -> str:
    """'Mar 7' this year, 'Mar 7, 2025' otherwise."""
    if value is None:
        return DASH
    today = today or date.today()
    text = f"{_MONTHS[value.month - 1]} {value.day}"
    return text if value.year == today.year else f"{text}, {value.year}"


def _preset_label(value: float) -> str:
    if value >= 1_000_000:
        return f"${(value / 1_000_000):g}M"
    if value >= 1_000:
        return f"${(value / 1_000):g}K"
    return f"${value:g}"


def _sign(value: Optional[float]) -> int:
    """+1 / -1 / 0 — QML colours values good / bad / neutral from this."""
    if value is None or value == 0:
        return 0
    return 1 if value > 0 else -1


def _profit_factor_text(value: Optional[float]) -> str:
    if value is None:
        return DASH
    return f"{value:,.2f}"


_STATUS_TEXT = {
    "WAITING": "Pending",
    "OPEN": "Open",
    "SHORT": "Short",
    "CLOSED": "Closed",
    "COVERED": "Covered",
}


def _ms(d: date, at: time = time(16, 0)) -> float:
    """ms-since-epoch for QtCharts DateTimeAxis (local time)."""
    return float(int(datetime.combine(d, at).timestamp() * 1000))


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
            return DASH if p is None else f"{p:,.2f}"
        return None

    def roleNames(self) -> Dict[int, QByteArray]:
        return {
            self.SymbolRole: QByteArray(b"symbol"),
            self.PriceRole: QByteArray(b"price"),
            self.PriceTextRole: QByteArray(b"priceText"),
        }

    def set_symbols(self, symbols: List[str]) -> None:
        if symbols == self.symbols():
            return  # avoid a reset (and lost selection/scroll) when nothing changed
        previous = len(self._rows)
        self.beginResetModel()
        self._rows = [{"symbol": s, "price": None} for s in symbols]
        self.endResetModel()
        if previous != len(self._rows):
            self.countChanged.emit()

    def update_prices(self, marks: Dict[str, Dict[str, Optional[float]]]) -> None:
        for i, row in enumerate(self._rows):
            new_price = marks.get(row["symbol"], {}).get("price")
            if new_price != row["price"]:
                row["price"] = new_price
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.PriceRole, self.PriceTextRole])

    def symbols(self) -> List[str]:
        return [r["symbol"] for r in self._rows]


class HoldingsModel(QAbstractListModel):
    """Open positions. `_rows` is a list of dicts keyed like the role table
    below; main_window reads `_rows[i]["instrument"]` to build the marks
    ticker list, so keep that key."""

    InstrumentRole = Qt.UserRole + 1
    QtyTextRole = Qt.UserRole + 2
    AvgCostRole = Qt.UserRole + 3
    MarkRole = Qt.UserRole + 4
    UnrealizedPlRole = Qt.UserRole + 5
    UnrealizedSignRole = Qt.UserRole + 6
    MarketValueRole = Qt.UserRole + 7
    WeightRole = Qt.UserRole + 8
    IsShortRole = Qt.UserRole + 9
    UnrealizedPctRole = Qt.UserRole + 10

    _KEYS = {
        InstrumentRole: ("instrument", b"instrument"),
        QtyTextRole: ("qty_text", b"qtyText"),
        AvgCostRole: ("avg_cost", b"avgCost"),
        MarkRole: ("mark", b"mark"),
        UnrealizedPlRole: ("unrealized", b"unrealizedPl"),
        UnrealizedSignRole: ("unrealized_sign", b"unrealizedSign"),
        MarketValueRole: ("market_value", b"marketValue"),
        WeightRole: ("weight", b"weight"),
        IsShortRole: ("is_short", b"isShort"),
        UnrealizedPctRole: ("unrealized_pct", b"unrealizedPctText"),
    }

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        key = self._KEYS.get(role)
        return None if key is None else self._rows[index.row()][key[0]]

    def roleNames(self) -> Dict[int, QByteArray]:
        return {role: QByteArray(name) for role, (_k, name) in self._KEYS.items()}

    @staticmethod
    def _row(h) -> Dict[str, Any]:
        is_short = h.qty < 0
        basis = abs(float(h.avg_cost) * h.qty)
        pct = (float(h.unrealized_pl) / basis * 100.0) if basis > 0 and h.mark is not None else None
        return {
            "instrument": h.instrument,
            "qty_text": f"{abs(h.qty):,d}",
            "avg_cost": _money(h.avg_cost),
            "mark": DASH if h.mark is None else _money(h.mark),
            "unrealized": _signed_money(h.unrealized_pl) if h.mark is not None else DASH,
            "unrealized_sign": _sign(h.unrealized_pl) if h.mark is not None else 0,
            "unrealized_pct": _arrow_pct(pct),
            "market_value": _money(h.market_value),
            "weight": _pct(h.weight_pct),
            "is_short": is_short,
        }

    def set_rows(self, views) -> None:
        out = [self._row(h) for h in views]
        same_shape = len(out) == len(self._rows) and all(
            a["instrument"] == b["instrument"] and a["is_short"] == b["is_short"]
            for a, b in zip(out, self._rows))
        if not same_shape:
            self.beginResetModel()
            self._rows = out
            self.endResetModel()
            return
        # Same positions, new marks: update in place so delegates (hover,
        # scroll position) survive the 20-second marks tick.
        for i, new in enumerate(out):
            if new != self._rows[i]:
                self._rows[i] = new
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)


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
    StatusTextRole = Qt.UserRole + 16
    ReturnTextRole = Qt.UserRole + 17
    TagRole = Qt.UserRole + 18

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._rows: List[Dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        return self._rows[index.row()].get(_TRADE_ROLE_KEY.get(role))

    def roleNames(self) -> Dict[int, QByteArray]:
        return _TRADE_ROLE_NAMES

    def set_rows(self, rows: List[Dict[str, Any]]) -> None:
        if rows == self._rows:
            return
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def source_index_for(self, view_row: int) -> Optional[int]:
        if 0 <= view_row < len(self._rows):
            value = self._rows[view_row].get("source_index")
            return int(value) if value is not None else None
        return None


# role -> (row-dict key, QML role name)
_TRADE_ROLES = {
    TradesModel.InstrumentRole: ("instrument", "instrument"),
    TradesModel.ShareCountRole: ("share_count", "shareCount"),
    TradesModel.StatusRole: ("status", "status"),
    TradesModel.BuyPriceRole: ("buy_price", "buyPrice"),
    TradesModel.SellPriceRole: ("sell_price", "sellPrice"),
    TradesModel.TradeProfitRole: ("trade_profit", "tradeProfit"),
    TradesModel.ProfitSignRole: ("profit_sign", "profitSign"),
    TradesModel.OpenDateRole: ("open_date", "openDate"),
    TradesModel.CloseDateRole: ("close_date", "closeDate"),
    TradesModel.DaysRole: ("days", "daysToClose"),
    TradesModel.AvgDailyRole: ("avg_daily", "avgDaily"),
    TradesModel.NotesRole: ("notes", "notes"),
    TradesModel.SourceIndexRole: ("source_index", "sourceIndex"),
    TradesModel.IsPendingRole: ("is_pending", "isPending"),
    TradesModel.IsShortRole: ("is_short", "isShort"),
    TradesModel.StatusTextRole: ("status_text", "statusText"),
    TradesModel.ReturnTextRole: ("return_text", "returnText"),
    TradesModel.TagRole: ("tag", "tag"),
}
_TRADE_ROLE_KEY = {role: key for role, (key, _n) in _TRADE_ROLES.items()}
_TRADE_ROLE_NAMES = {role: QByteArray(name.encode("ascii")) for role, (_k, name) in _TRADE_ROLES.items()}


# ---------------------------------------------------------------------------
# Per-account controller
# ---------------------------------------------------------------------------

class AccountController(QObject):
    """Exposes one account's computed data to QML.

    Property bags (goal, pace, analytics, summary, presets) are plain
    QVariantMap / QVariantList so QML binds to them as `account.goal.realized`.

    Filter state (text, status, date range, tag) lives here per account so
    switching tabs keeps each account's filters. Filtered-out rows are
    removed from the TradesModel (not hidden in the delegate), so the list
    has no gaps.
    """

    # goal, pace, summary, presets, realized/progress raws — mark-dependent
    metricsChanged = Signal()
    # analytics, equity curve, tags, trade count — trade/filter-dependent
    analyticsChanged = Signal()
    filterChanged = Signal()
    loadedChanged = Signal()

    def __init__(self, name: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._name = name
        self._holdings = HoldingsModel(self)
        self._trades = TradesModel(self)
        # Published, mark-dependent state (metricsChanged)
        self._goal: Dict[str, Any] = {}
        self._pace: Dict[str, Any] = {}
        self._summary: Dict[str, str] = {}
        self._presets: List[Dict[str, Any]] = []
        self._goal_target_value: float = 500_000.0
        self._realized_raw: float = 0.0
        self._goal_progress_pct: float = 0.0
        # Published, trade-dependent state (analyticsChanged)
        self._analytics: Dict[str, Any] = {}
        self._est_yearly_raw: Optional[float] = None
        # {x: ms-since-epoch, y: cumulative realized $} for QtCharts.
        self._equity_curve: List[Dict[str, float]] = []
        self._equity_min_y: float = 0.0
        self._equity_max_y: float = 0.0
        self._pace_line: List[Dict[str, float]] = []
        self._available_tags: List[str] = []
        # Unfiltered trade rows for the current date/tag range, so text /
        # status filter changes never recompute analytics.
        self._all_trade_rows: List[Dict[str, Any]] = []
        self._text_filter: str = ""
        self._status_filter: str = ""
        # Date range for the trades table + analytics:
        # "all" / "week" / "month" / "30d" / "ytd"
        self._date_range: str = "all"
        # "trades" = one curve point per close; "daily" = end-of-day buckets.
        self._equity_curve_mode: str = "trades"
        self._tag_filter: str = ""  # "" = all tags
        # Cached inputs so filter/marks changes never go back to the store.
        self._last_trades: List[Trade] = []
        self._last_goal_trades: List[Trade] = []
        self._last_marks: Dict[str, Optional[float]] = {}
        self._last_goal_target: float = 500_000.0
        self._last_presets: List[float] = []
        # Mark-independent intermediates, rebuilt only when trades change.
        self._holdings_base = []
        self._realized_base: Dict[str, float] = {}
        self._goal_holdings_base = []
        self._goal_realized_base: Dict[str, float] = {}
        self._goal_has_closed = False
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

    # Pace rail data: expected-by-today vs realized. Keys: state
    # ("ahead"/"behind"/"reached"/"start" = no closed trades/"none" = no goal), sentence, targetText, endText,
    # expectedText, realizedText, fraction (realized/target, 0..1),
    # paceFraction (expected/target, 0..1).
    @Property("QVariantMap", notify=metricsChanged)
    def pace(self) -> Dict[str, Any]:
        return self._pace

    @Property("QVariantMap", notify=analyticsChanged)
    def analytics(self) -> Dict[str, Any]:
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

    @Property(float, notify=metricsChanged)
    def realizedRaw(self) -> float:
        return self._realized_raw

    @Property(float, notify=metricsChanged)
    def goalProgressPct(self) -> float:
        return self._goal_progress_pct

    @Property(float, notify=analyticsChanged)
    def estYearlyRaw(self) -> float:
        return 0.0 if self._est_yearly_raw is None else float(self._est_yearly_raw)

    # ── Equity curve: one point per closed trade (or per day) in range ──
    @Property("QVariantList", notify=analyticsChanged)
    def equityCurve(self) -> List[Dict[str, float]]:
        return self._equity_curve

    @Property(float, notify=analyticsChanged)
    def equityCurveMinY(self) -> float:
        return self._equity_min_y

    @Property(float, notify=analyticsChanged)
    def equityCurveMaxY(self) -> float:
        return self._equity_max_y

    # Straight goal-pace line [{x, y}, {x, y}] from Jan 1 ($0) to today
    # (expected-by-now). Empty unless the range is "all"/"ytd", the curve
    # has data and there is a positive goal — otherwise it would compare
    # a sub-range curve against a full-year pace.
    @Property("QVariantList", notify=analyticsChanged)
    def equityPaceLine(self) -> List[Dict[str, float]]:
        return self._pace_line

    @Property(int, notify=metricsChanged)
    def realizedSign(self) -> int:
        return _sign(self._realized_raw)

    # False until update() has run once, so QML can suppress empty states
    # in the gap between mounting and the first data load.
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

    @Property(int, notify=analyticsChanged)
    def totalTradeCount(self) -> int:
        return len(self._all_trade_rows)

    @Property(str, notify=filterChanged)
    def dateRangeKey(self) -> str:
        return self._date_range

    @Slot(str)
    def setDateRange(self, key: str) -> None:
        new = (key or "all").strip().lower()
        if new not in ("all", "week", "month", "30d", "ytd"):
            new = "all"
        if new != self._date_range:
            self._date_range = new
            self.filterChanged.emit()
            self._recompute_trade_side()

    @Property(str, notify=filterChanged)
    def tagFilter(self) -> str:
        return self._tag_filter

    @Slot(str)
    def setTagFilter(self, tag: str) -> None:
        new = (tag or "").strip()
        if new != self._tag_filter:
            self._tag_filter = new
            self.filterChanged.emit()
            self._recompute_trade_side()

    # Distinct non-empty tags in the account, sorted case-insensitively.
    @Property("QVariantList", notify=analyticsChanged)
    def availableTags(self) -> List[str]:
        return self._available_tags

    @Property(str, notify=analyticsChanged)
    def equityCurveMode(self) -> str:
        return self._equity_curve_mode

    @Slot(str)
    def setEquityCurveMode(self, mode: str) -> None:
        new = (mode or "trades").strip().lower()
        if new not in ("trades", "daily"):
            new = "trades"
        if new != self._equity_curve_mode:
            self._equity_curve_mode = new
            self._recompute_trade_side()

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

    # ── Computation ─────────────────────────────────────────────────────────

    def _build_equity_curve(self, trades: List[Trade]) -> List[Dict[str, float]]:
        """(x: ms-since-epoch, y: cumulative realized $) from closed trades.

        Seeded with a $0 point the day before the first close so the line
        rises from the axis. "daily" mode sums same-day closes into one
        end-of-day point, which reads better on dense histories.
        """
        closed = [
            t for t in trades
            if t.is_closed and t.close_date is not None
            and t.trade_profit is not None and not t.is_pending
        ]
        if not closed:
            return []
        closed.sort(key=lambda t: t.close_date)
        points: List[Dict[str, float]] = [
            {"x": _ms(closed[0].close_date - timedelta(days=1), time(0, 0)), "y": 0.0}]
        running = 0.0
        if self._equity_curve_mode == "daily":
            daily_pl: Dict[date, float] = defaultdict(float)
            for t in closed:
                daily_pl[t.close_date] += float(t.trade_profit or 0.0)
            for d in sorted(daily_pl):
                running += daily_pl[d]
                points.append({"x": _ms(d), "y": running})
        else:
            for t in closed:
                running += float(t.trade_profit or 0.0)
                points.append({"x": _ms(t.close_date), "y": running})
        return points

    def _date_filtered_with_orig_index(self, trades: List[Trade]) -> List[tuple]:
        """Index-preserving date filter (logic + tests live in portfolio.py).
        The original index is what edit/delete/move handlers use."""
        return filter_trades_by_date_range_with_orig_index(trades, self._date_range)

    def _reapply_filter(self) -> None:
        rows = self._all_trade_rows
        text = self._text_filter.lower()
        status = self._status_filter
        if text or status:
            rows = [
                r for r in rows
                if (not status or r["status"] == status)
                and (not text or text in r["haystack"])
            ]
        self._trades.set_rows(rows)

    def update(
            self,
            account_trades: List[Trade],
            goal_trades: List[Trade],
            marks: Dict[str, Optional[float]],
            goal_target: float,
            presets: List[float],
    ) -> None:
        """Full refresh after the trade list (or goal settings) changed."""
        self._last_trades = list(account_trades)
        self._last_goal_trades = list(goal_trades)
        self._last_marks = dict(marks)
        self._last_goal_target = float(goal_target)
        self._last_presets = list(presets)
        # Holdings and the goal are deliberately NOT date/tag-filtered: they
        # are "what you own now" and "your annual progress".
        self._holdings_base = compute_holdings_from_trades(self._last_trades)
        self._realized_base = compute_realized_pl_by_symbol(self._last_trades)
        self._goal_holdings_base = compute_holdings_from_trades(self._last_goal_trades)
        self._goal_realized_base = compute_realized_pl_by_symbol(self._last_goal_trades)
        self._goal_has_closed = any(t.is_closed and not t.is_pending for t in self._last_goal_trades)
        tags = sorted({(t.tag or "").strip() for t in self._last_trades} - {""}, key=str.lower)
        self._available_tags = tags
        self._recompute_trade_side(emit=False)
        self._recompute_mark_side(force_emit=True)
        self.analyticsChanged.emit()
        if not self._loaded:
            self._loaded = True
            self.loadedChanged.emit()

    def update_marks(self, marks: Dict[str, Optional[float]]) -> None:
        """Marks-only refresh: holdings, summary, goal and pace. Cheap."""
        if marks == self._last_marks:
            return
        self._last_marks = dict(marks)
        if self._loaded:  # before the first update() there is nothing to price
            self._recompute_mark_side()

    def _recompute_with_current_filter(self) -> None:
        """Recompute everything from the cached inputs (kept for callers
        that predate the split update paths)."""
        self._recompute_trade_side()
        self._recompute_mark_side()

    def _recompute_trade_side(self, emit: bool = True) -> None:
        """Analytics, equity curve and trade rows for the current date range
        and tag. Independent of marks."""
        account_trades = self._last_trades
        ranged_with_idx = self._date_filtered_with_orig_index(account_trades)
        if self._tag_filter:
            target = self._tag_filter
            ranged_with_idx = [(i, t) for (i, t) in ranged_with_idx if (t.tag or "").strip() == target]
        ranged_trades = [t for _, t in ranged_with_idx]
        orig_indices = [i for i, _ in ranged_with_idx]

        analytics = compute_trade_analytics(ranged_trades)
        curve = self._build_equity_curve(ranged_trades)
        self._equity_curve = curve
        ys = [p["y"] for p in curve]
        self._equity_min_y = min(0.0, min(ys)) if ys else 0.0
        self._equity_max_y = max(0.0, max(ys)) if ys else 0.0
        self._pace_line = self._build_pace_line(curve)

        today = date.today()
        enriched: List[Dict[str, Any]] = []
        for r in compute_trade_rows(ranged_trades):
            original_index = orig_indices[r.index]
            source = account_trades[original_index]
            basis = float(r.buy_price) * int(r.share_count)
            ret = (float(r.trade_profit) / basis * 100.0) if (r.trade_profit is not None and basis > 0) else None
            notes = source.notes or ""
            tag = r.tag or ""
            enriched.append({
                "instrument": r.instrument,
                "share_count": f"{r.share_count:,d}",
                "status": r.status,
                "status_text": _STATUS_TEXT.get(r.status, r.status.title()),
                "buy_price": _money(r.buy_price),
                "sell_price": _money(r.sell_price),
                "trade_profit": _signed_money(r.trade_profit),
                "profit_sign": _sign(r.trade_profit),
                "return_text": _arrow_pct(ret),
                "open_date": _date(r.open_date, today),
                "close_date": _date(r.close_date, today),
                "days": _int(r.days_to_close),
                "avg_daily": _signed_money(r.avg_daily_return),
                "notes": notes,
                "tag": tag,
                "source_index": original_index,
                "is_pending": bool(source.is_pending),
                "is_short": bool(source.is_short),
                # Pre-lowered search text for the filter box (hot path while typing).
                "haystack": " ".join((r.instrument, r.status, notes, tag)).lower(),
            })
        # Newest activity first (pending orders on top): the user is
        # usually checking what they just did. source_index is unaffected.
        def _recency(row: Dict[str, Any]):
            t = account_trades[row["source_index"]]
            when = t.close_date or t.open_date or date.min
            return (not t.is_pending, -when.toordinal(), -row["source_index"])

        enriched.sort(key=_recency)
        self._all_trade_rows = enriched
        self._reapply_filter()

        self._est_yearly_raw = analytics.est_yearly_profit
        self._analytics = {
            "openTrades": f"{analytics.open_trades:,d}",
            "closedTrades": f"{analytics.closed_trades:,d}",
            "winRate": _pct(analytics.win_rate_pct),
            "winRateSign": 0,
            "profitFactor": _profit_factor_text(analytics.profit_factor),
            "profitFactorSign": 0 if analytics.profit_factor is None
            else (1 if analytics.profit_factor >= 1.0 else -1),
            "avgProfit": _signed_money(analytics.avg_profit_per_trade),
            "avgProfitSign": _sign(analytics.avg_profit_per_trade),
            "avgTradeValue": _money(analytics.avg_trade_value),
            "avgWin": _signed_money(analytics.avg_win),
            "avgWinSign": _sign(analytics.avg_win),
            "avgLoss": _signed_money(analytics.avg_loss),
            "avgLossSign": _sign(analytics.avg_loss),
            "bestTrade": _signed_money(analytics.best_trade),
            "bestTradeSign": _sign(analytics.best_trade),
            "worstTrade": _signed_money(analytics.worst_trade),
            "worstTradeSign": _sign(analytics.worst_trade),
            "avgRoi": _signed_pct(analytics.avg_roi_pct),
            "avgRoiSign": _sign(analytics.avg_roi_pct),
            "avgDailyReturn": _signed_money(analytics.avg_daily_closed_profit),
            "avgDailyReturnSign": _sign(analytics.avg_daily_closed_profit),
            "estYearly": _signed_money(analytics.est_yearly_profit),
            "estYearlySign": _sign(analytics.est_yearly_profit),
            # Drawdowns are reported as positive amounts by portfolio.py;
            # shown as losses (−$x) since that is what they are.
            "maxDrawdown": _signed_money(-analytics.max_drawdown) if analytics.max_drawdown else _money(
                analytics.max_drawdown),
            "maxDrawdownSign": -1 if analytics.max_drawdown else 0,
            "currentDrawdown": _signed_money(-analytics.current_drawdown) if analytics.current_drawdown else _money(
                analytics.current_drawdown),
            "currentDrawdownSign": -1 if (analytics.current_drawdown or 0) > 0 else 0,
        }
        if emit:
            self.analyticsChanged.emit()

    def _build_pace_line(self, curve: List[Dict[str, float]]) -> List[Dict[str, float]]:
        expected = self._pace.get("expectedRaw") if self._pace else None
        if not curve or self._date_range not in ("all", "ytd") or not self._last_goal_target or expected is None:
            return []
        today = date.today()
        return [{"x": _ms(date(today.year, 1, 1), time(0, 0)), "y": 0.0},
                {"x": _ms(today), "y": float(expected)}]

    def _recompute_mark_side(self, force_emit: bool = False) -> None:
        """Holdings, portfolio summary, goal progress and pace. These are
        the only outputs that depend on live marks."""
        marks = self._last_marks
        goal_target = self._last_goal_target

        holding_views, summary = compute_portfolio(self._holdings_base, marks, self._realized_base)
        self._holdings.set_rows(holding_views)

        _, goal_summary = compute_portfolio(self._goal_holdings_base, marks, self._goal_realized_base)
        goal = compute_goal_progress(
            self._last_goal_trades, goal_target, unrealized_profit=goal_summary.unrealized_pl)

        realized = float(goal.realized_profit)
        progress = max(0.0, min(100.0, realized / goal_target * 100.0)) if goal_target > 0 else 0.0

        # Year-end forecast: realized so far + avg daily profit × days left.
        if goal.avg_daily_profit is not None and goal.business_days_remaining >= 0:
            year_end_forecast: Optional[float] = (
                    realized + float(goal.avg_daily_profit) * int(goal.business_days_remaining))
        else:
            year_end_forecast = None

        new_goal = {
            "target": _goal_money(goal.goal_target),
            "realized": _signed_money(goal.realized_profit),
            "unrealized": _signed_money(goal.unrealized_profit),
            "remaining": _money(goal.remaining_profit),
            "monthly": _money(goal.monthly_profit_to_goal),
            "weekly": _money(goal.weekly_profit_to_goal),
            "daily": _money(goal.daily_profit_to_goal),
            "avgDaily": _signed_money(goal.avg_daily_profit),
            "catchUp": _money(goal.profit_to_match_daily_avg),
            "daysElapsed": f"{goal.business_days_elapsed:,d}",
            "daysRemaining": f"{goal.business_days_remaining:,d}",
            "yearEndForecast": _signed_money(year_end_forecast),
            "yearEndForecastSign": _sign(year_end_forecast),
            "unrealizedSign": _sign(goal.unrealized_profit),
            "remainingSign": _sign(goal.remaining_profit),
        }
        new_pace = self._pace_map(goal, realized, goal_target, self._goal_has_closed)
        new_summary = {
            "marketValue": _money(summary.market_value),
            "costBasis": _money(summary.cost_basis),
            "unrealizedPl": _signed_money(summary.unrealized_pl),
            "unrealizedSign": _sign(summary.unrealized_pl),
            "totalPl": _signed_money(summary.total_pl),
            "positions": f"{summary.positions:,d}",
        }
        new_presets = [{"label": _preset_label(p), "value": float(p)} for p in self._last_presets]

        changed = force_emit or (
                new_goal != self._goal or new_pace != self._pace or new_summary != self._summary
                or new_presets != self._presets or goal_target != self._goal_target_value
                or realized != self._realized_raw)
        pace_moved = new_pace.get("expectedRaw") != self._pace.get("expectedRaw")
        self._goal, self._pace, self._summary, self._presets = new_goal, new_pace, new_summary, new_presets
        self._goal_target_value = float(goal_target)
        self._realized_raw = realized
        self._goal_progress_pct = progress
        if changed:
            self.metricsChanged.emit()
        if pace_moved and not force_emit:
            # The pace line on the equity curve follows the expected value.
            self._pace_line = self._build_pace_line(self._equity_curve)
            self.analyticsChanged.emit()
        elif force_emit:
            self._pace_line = self._build_pace_line(self._equity_curve)

    @staticmethod
    def _pace_map(goal, realized: float, target: float, has_closed: bool = True) -> Dict[str, Any]:
        """Data for the pace rail. Pace = target × elapsed / total trading
        days this year, the same "expected by now" compute_goal_progress uses."""
        elapsed, remaining = goal.business_days_elapsed, goal.business_days_remaining
        total = elapsed + remaining
        if target <= 0 or total <= 0:
            return {"state": "none", "sentence": "Set a goal to track your pace", "fraction": 0.0,
                    "paceFraction": 0.0, "targetText": DASH, "endText": "", "expectedText": DASH,
                    "realizedText": _signed_money(realized), "expectedRaw": None}
        expected = target * elapsed / total
        delta = realized - expected
        if not has_closed:
            # A brand-new account is not "behind"; it just hasn't started.
            state, sentence = "start", "Close a trade to start your pace"
        elif realized >= target:
            state, sentence = "reached", "Goal reached"
        elif delta >= 0:
            state, sentence = "ahead", f"{_goal_money(delta)} ahead of pace"
        else:
            state, sentence = "behind", f"{_goal_money(-delta)} behind pace"
        return {
            "state": state,
            "sentence": sentence,
            "fraction": max(0.0, min(1.0, realized / target)),
            "paceFraction": max(0.0, min(1.0, expected / target)),
            "targetText": _goal_money(target),
            "endText": "by Dec 31",
            "expectedText": _goal_money(expected),
            "expectedRaw": float(expected),
            "realizedText": _goal_money(realized),
            "deltaRaw": float(delta),
        }


# ---------------------------------------------------------------------------
# Theme controller
# ---------------------------------------------------------------------------

class ThemeController(QObject):
    """Colour tokens, fonts and motion preference for QML (`app.theme.*`).

    Tokens are cached in refresh(): the getters used to call into
    ThemeManager (which reads the Windows registry for System mode) on
    every binding evaluation — hundreds of registry reads per theme change.
    MainWindow connects ThemeManager.themeApplied -> refresh().
    """

    themeChanged = Signal()

    _FALLBACK = {
        "bg": "#E8ECEF", "card": "#F8FAFB", "card2": "#EEF2F5", "text": "#15202B",
        "text_muted": "#566472", "button": "#EEF2F5", "primary": "#2C55C9",
        "secondary": "#2C55C9", "border": "#D3DAE0", "good": "#0B7A5C",
        "bad": "#B83A2E", "text_on_color": "#FFFFFF", "pace": "#B07610",
    }

    def __init__(self, theme_manager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._theme = theme_manager
        self._cache: Dict[str, str] = dict(self._FALLBACK)
        self._fonts: Dict[str, str] = {"text": "", "display": ""}
        self._font_scale = 1.0
        self._is_light = True
        self._reduce_motion = False
        self._load()

    def _load(self) -> None:
        try:
            tokens = self._theme._tokens()
            self._is_light = bool(self._theme._is_light())
        except Exception:  # theme manager half-initialised: keep previous values
            _log.exception("ThemeController: could not read theme tokens")
            tokens = None
        if tokens:
            self._cache = {**self._FALLBACK, **tokens}
        self._fonts = dict(resolve_fonts())
        self._reduce_motion = reduce_motion_enabled()
        self._font_scale = float(FONT_SIZES.get(getattr(self._theme, "font_size_label", "Normal"), 11)) / 11.0

    def refresh(self) -> None:
        self._load()
        self.themeChanged.emit()

    def _color(self, name: str) -> str:
        return self._cache.get(name, "#000000")

    # Color Q_PROPERTYs. All change signals share themeChanged.
    @Property(str, notify=themeChanged)
    def bg(self) -> str:
        return self._cache["bg"]

    @Property(str, notify=themeChanged)
    def card(self) -> str:
        return self._cache["card"]

    @Property(str, notify=themeChanged)
    def cardAlt(self) -> str:
        return self._cache["card2"]

    @Property(str, notify=themeChanged)
    def text(self) -> str:
        return self._cache["text"]

    @Property(str, notify=themeChanged)
    def textMuted(self) -> str:
        return self._cache["text_muted"]

    @Property(str, notify=themeChanged)
    def button(self) -> str:
        return self._cache["button"]

    @Property(str, notify=themeChanged)
    def primary(self) -> str:
        return self._cache["primary"]

    @Property(str, notify=themeChanged)
    def secondary(self) -> str:
        return self._cache["secondary"]

    @Property(str, notify=themeChanged)
    def border(self) -> str:
        return self._cache["border"]

    @Property(str, notify=themeChanged)
    def good(self) -> str:
        return self._cache["good"]

    @Property(str, notify=themeChanged)
    def bad(self) -> str:
        return self._cache["bad"]

    @Property(str, notify=themeChanged)
    def textOnColor(self) -> str:
        return self._cache["text_on_color"]

    # Goal-pace amber. Only the pace rail tick and equity-curve pace line use it.
    @Property(str, notify=themeChanged)
    def pace(self) -> str:
        return self._cache["pace"]

    @Property(bool, notify=themeChanged)
    def isLight(self) -> bool:
        return self._is_light

    # Resolved once by theme.resolve_fonts(): UI text and >= 20 px numbers.
    @Property(str, notify=themeChanged)
    def fontFamily(self) -> str:
        return self._fonts.get("text", "")

    @Property(str, notify=themeChanged)
    def displayFontFamily(self) -> str:
        return self._fonts.get("display", "")

    @Property(bool, notify=themeChanged)
    def reduceMotion(self) -> bool:
        return self._reduce_motion

    # QML sizes are designed at "Normal" (11 pt) and multiplied by this, so
    # the Settings font-size choice reaches the QML scene.
    @Property(float, notify=themeChanged)
    def fontScale(self) -> float:
        return self._font_scale


# ---------------------------------------------------------------------------
# Root controller exposed to QML as `app`
# ---------------------------------------------------------------------------

class AppController(QObject):
    accountsChanged = Signal()
    currentAccountChanged = Signal()
    statusChanged = Signal()
    adminChanged = Signal()
    # View-menu toggles (currently only the equity curve card).
    viewPrefsChanged = Signal()

    def __init__(self, store, theme_manager, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._store = store
        self._theme_manager = theme_manager
        self._theme_controller = ThemeController(theme_manager, self)
        self._watchlist = WatchlistModel(self)
        self._accounts: List[AccountController] = []
        self._current_index = 0
        self._marks_by_symbol: Dict[str, Dict[str, Optional[float]]] = {}
        self._status_text = "Connecting…"
        self._status_color = "#9ca3af"
        self._username = str(store.username)
        self._is_admin = bool(store.is_admin)
        # MainWindow overrides this from QSettings before QML mounts.
        self._equity_curve_visible: bool = True
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

    # ---- view-menu preferences ----
    # MainWindow's QAction persists the choice and calls the setter.

    @Property(bool, notify=viewPrefsChanged)
    def equityCurveVisible(self) -> bool:
        return self._equity_curve_visible

    def set_equity_curve_visible(self, visible: bool) -> None:
        visible = bool(visible)
        if visible != self._equity_curve_visible:
            self._equity_curve_visible = visible
            self.viewPrefsChanged.emit()

    # ---- status ----

    def set_status(self, text: str, color: str) -> None:
        if (text, color) != (self._status_text, self._status_color):
            self._status_text = text
            self._status_color = color
            self.statusChanged.emit()

    # ---- account management ----

    def rebuild_accounts(self) -> None:
        """(Re)create AccountControllers to match the store's account list.
        Existing controllers are reused by name so their filter state and
        QML delegates survive an account add/rename elsewhere."""
        try:
            names = self._store.get_account_names()
        except Exception:
            _log.exception("get_account_names failed; showing a Default account")
            names = ["Default"]
        if names == [a.name for a in self._accounts]:
            return
        existing = {a.name: a for a in self._accounts}
        self._accounts = [existing.get(n) or AccountController(n, self) for n in names]
        if self._current_index >= len(self._accounts):
            self._current_index = max(0, len(self._accounts) - 1)
        self.accountsChanged.emit()
        self.currentAccountChanged.emit()

    def _price_marks(self) -> Dict[str, Optional[float]]:
        return {sym: info.get("price") for sym, info in self._marks_by_symbol.items()}

    def refresh_all_accounts(self) -> None:
        """Re-read trades + goal settings from the store and recompute every
        account. Call after a save; marks ticks use apply_marks instead.
        NOTE: with RemoteDataStore this can hit the network on the UI thread
        when its cache was just invalidated by a save."""
        try:
            trades = self._store.get_all_trades()
        except Exception:
            _log.exception("get_all_trades failed")
            trades = []
        try:
            shared_names, _ = self._store.get_goal_group()
            shared_set = set(shared_names)
        except Exception:
            _log.exception("get_goal_group failed")
            shared_set = set()

        by_account: Dict[str, List[Trade]] = defaultdict(list)
        for t in trades:
            by_account[(t.account or "").strip()].append(t)
        shared_trades = [t for name in shared_set for t in by_account.get(name, [])]
        marks = self._price_marks()

        for account in self._accounts:
            account_trades = by_account.get(account.name, [])
            try:
                target = float(self._store.get_goal_target(account.name))
                presets = list(self._store.get_goal_presets(account.name))
            except Exception:
                _log.exception("goal settings for %r failed; using defaults", account.name)
                target = 500_000.0
                presets = [250_000.0, 500_000.0, 1_000_000.0]
            goal_trades = shared_trades if account.name in shared_set else account_trades
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
        """Merge a marks payload and refresh only mark-dependent views.
        No store access: trades have not changed on a price tick."""
        for sym, info in marks.items():
            existing = dict(self._marks_by_symbol.get(sym, {}))
            existing.update(info)
            self._marks_by_symbol[sym] = existing
        self._watchlist.update_prices(self._marks_by_symbol)
        price_marks = self._price_marks()
        for account in self._accounts:
            account.update_marks(price_marks)

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
        except Exception:  # a failing handler must not unwind into QML
            _log.exception("callback '%s' raised", name)
