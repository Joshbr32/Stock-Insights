"""Per-symbol drill-down dialog ("View NVDA trade history").

Opened from the Holdings and Trade History context menus. Shows everything
that has happened for one ticker in one portfolio:

  • Header — symbol + current open position and unrealized P/L (if any)
  • Stat row — closed trades, win rate, realized P/L, best, worst, max drawdown
  • Mini equity curve of cumulative realized P/L for the symbol
  • Chronological, read-only trade table

All maths comes from portfolio.compute_trade_analytics; colours come from
the active theme (good / bad / text_muted / primary / border tokens).
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta
from typing import List, Optional

# QtCharts is in PySide6-Addons. Importing here registers the C++
# widget side; the QML side is registered separately (main_window.py).
from PySide6.QtCharts import QCategoryAxis, QChart, QChartView, QDateTimeAxis, QLineSeries
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .portfolio import Trade, compute_trade_analytics
from .widgets import (
    Panel,
    add_dialog_buttons,
    dialog_layout,
    fmt_int,
    fmt_money,
    fmt_signed_money,
    fmt_status,
    heading_label,
    muted_label,
    pl_role,
    scaled_font,
    set_text_role,
    theme_color,
)

ROW_HEIGHT = 32
_NUMERIC_COLS = (3, 4, 5, 6)
_PROFIT_COL = 6


def _fmt_pct(value: Optional[float], digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _fmt_date(d: Optional[date]) -> str:
    return "" if d is None else f"{d:%b} {d.day}, {d:%Y}"

def _nice_step(raw: float) -> float:
    """Round a tick step up to 1, 2 or 5 times a power of ten."""
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _axis_money(v: float) -> str:
    """Axis label: "$1,100", "−$50", "$0"."""
    return ("−" if v < 0 else "") + f"${abs(v):,.0f}"



class SymbolHistoryDialog(QDialog):
    """Read-only drill-down of every trade for a single symbol."""

    def __init__(self, instrument: str, trades: List[Trade], current_mark: Optional[float] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        instr = (instrument or "").strip().upper()
        self.setWindowTitle(f"{instr} trade history")
        self.resize(760, 620)

        self._symbol = instr
        self._trades = [t for t in trades if t.normalized_instrument() == instr]
        self._mark = current_mark

        root = dialog_layout(self)
        root.addLayout(self._build_header())
        root.addWidget(self._build_stat_strip())
        root.addWidget(self._build_chart(), stretch=2)
        root.addWidget(self._build_trade_table(), stretch=3)
        add_dialog_buttons(self, root, primary_text=None, cancel_text="Close")

    # ── Header ───────────────────────────────────────────────────────
    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(12)
        h.addWidget(heading_label(self._symbol, px=28))
        h.addStretch(1)

        open_trades = [t for t in self._trades if not t.is_closed and not t.is_pending]
        if not open_trades:
            h.addWidget(muted_label("No open position", wrap=False))
            return h

        qty = sum(int(t.share_count) for t in open_trades)
        cost = sum(float(t.buy_price) * int(t.share_count) for t in open_trades)
        avg = (cost / qty) if qty > 0 else 0.0
        is_short = any(t.is_short for t in open_trades)
        side = "Short" if is_short else "Holding"
        h.addWidget(QLabel(f"{side} {qty:,d} shares at {fmt_money(avg)} average"))
        if self._mark is not None:
            upl = (self._mark - avg) * qty * (-1 if is_short else 1)
            h.addWidget(muted_label(f"Price {fmt_money(self._mark)}", wrap=False))
            upl_lbl = QLabel(f"{fmt_signed_money(upl)} unrealized")
            upl_lbl.setFont(scaled_font(upl_lbl.font(), 13, 600))
            h.addWidget(set_text_role(upl_lbl, pl_role(upl)))
        return h

    # ── Stat row ─────────────────────────────────────────────────────
    def _build_stat_strip(self) -> QWidget:
        # Analytics for THIS symbol only — the point of the drill-down.
        a = compute_trade_analytics(self._trades)
        panel = Panel()
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(2)
        stats = [
            ("Closed trades", fmt_int(a.closed_trades), ""),
            ("Win rate", _fmt_pct(a.win_rate_pct), ""),
            ("Realized P/L", fmt_signed_money(a.realized_profit), pl_role(a.realized_profit)),
            ("Best trade", fmt_signed_money(a.best_trade), pl_role(a.best_trade)),
            ("Worst trade", fmt_signed_money(a.worst_trade), pl_role(a.worst_trade)),
            # Drawdown is shown as a loss-sized number, coloured as a loss.
            ("Max drawdown", fmt_money(a.max_drawdown), "bad" if a.max_drawdown else "muted"),
        ]
        for col, (label, value, role) in enumerate(stats):
            lbl = muted_label(label, wrap=False)
            lbl.setFont(scaled_font(lbl.font(), 12, 600))
            val = QLabel(value)
            val.setFont(scaled_font(val.font(), 15, 600))
            if role:
                set_text_role(val, role)
            grid.addWidget(lbl, 0, col)
            grid.addWidget(val, 1, col)
        grid.setColumnStretch(len(stats), 1)
        panel.body.addLayout(grid)
        return panel

    # ── Mini equity curve ────────────────────────────────────────────
    def _build_chart(self) -> QWidget:
        """Cumulative realized P/L for this symbol over time; an empty-state
        message when nothing has closed yet."""
        closed = [t for t in self._trades
                  if t.is_closed and t.close_date is not None
                  and t.trade_profit is not None and not t.is_pending]
        panel = Panel("Realized P/L over time")
        if not closed:
            empty = muted_label(f"No closed {self._symbol} trades yet. "
                                "Close a position to see its profit build up here.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(110)
            panel.body.addWidget(empty)
            return panel

        closed.sort(key=lambda t: t.close_date)
        series = QLineSeries()
        # Start from zero the day before the first close, like the main
        # equity curve, so the line rises from the baseline.
        series.append(self._epoch_ms(closed[0].close_date - timedelta(days=1), time(0, 0)), 0.0)
        running = 0.0
        for t in closed:
            running += float(t.trade_profit or 0.0)
            series.append(self._epoch_ms(t.close_date, time(16, 0)), running)
        pen = QPen(theme_color("primary", self))
        pen.setWidthF(2.0)
        series.setPen(pen)

        chart = QChart()
        chart.legend().hide()
        chart.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        chart.setPlotAreaBackgroundVisible(False)
        chart.setMargins(QMargins(0, 0, 0, 0))
        chart.addSeries(series)

        muted = theme_color("text_muted", self)
        grid_pen = QPen(theme_color("border", self))
        grid_pen.setWidthF(1.0)
        x_axis = QDateTimeAxis()
        x_axis.setFormat("MMM d")
        x_axis.setTickCount(5)
        # QValueAxis can only printf-format labels ("$-54", "$1129"), so use a
        # category axis with round ticks labelled like the rest of the app
        # ("−$50", "$1,100").
        ys = [series.at(i).y() for i in range(series.count())]
        lo, hi = min(0.0, min(ys)), max(0.0, max(ys))
        step = _nice_step(max(1.0, hi - lo) / 3)
        lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
        y_axis = QCategoryAxis()
        y_axis.setLabelsPosition(QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue)
        y_axis.setRange(lo, hi)
        y_axis.setTruncateLabels(False)
        v = lo
        while v <= hi + step / 2:
            y_axis.append(_axis_money(v), v)
            v += step
        for axis, align in ((x_axis, Qt.AlignmentFlag.AlignBottom), (y_axis, Qt.AlignmentFlag.AlignLeft)):
            axis.setLabelsBrush(QBrush(muted))
            axis.setGridLinePen(grid_pen)
            axis.setLinePen(grid_pen)
            chart.addAxis(axis, align)
            series.attachAxis(axis)
        x_axis.setGridLineVisible(False)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(150)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        view.setStyleSheet("background: transparent;")
        panel.body.addWidget(view, 1)
        return panel

    # ── Trade table ──────────────────────────────────────────────────
    def _build_trade_table(self) -> QWidget:
        """Every trade for the symbol, oldest first; pending orders last."""
        rows = sorted(self._trades, key=lambda tr: (tr.open_date or date.max, tr.close_date or date.max))
        cols = ["Date", "Side", "Status", "Shares", "Buy", "Sell", "Profit", "Tag", "Notes"]
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setShowGrid(False)
        table.setWordWrap(False)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i in range(len(cols) - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)
        for i in _NUMERIC_COLS:
            item = table.horizontalHeaderItem(i)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        good, bad = QBrush(theme_color("good", self)), QBrush(theme_color("bad", self))
        for r, t in enumerate(rows):
            profit = t.trade_profit
            cells = [
                _fmt_date(t.close_date or t.open_date) or "Not filled",
                "Short" if t.is_short else "Long",
                fmt_status(t.status),
                f"{int(t.share_count):,d}",
                fmt_money(float(t.buy_price)),
                "" if t.sell_price is None else fmt_money(float(t.sell_price)),
                "" if profit is None else fmt_signed_money(profit),
                (t.tag or "").strip(),
                (t.notes or "").strip(),
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c in _NUMERIC_COLS:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if c == _PROFIT_COL and profit is not None and abs(profit) >= 0.005:
                    item.setForeground(good if profit > 0 else bad)
                table.setItem(r, c, item)

        if not rows:
            wrapper = QWidget()
            v = QVBoxLayout(wrapper)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(muted_label(f"No {self._symbol} trades in this portfolio."))
            return wrapper
        return table

    # ── Small helpers ────────────────────────────────────────────────
    @staticmethod
    def _epoch_ms(d: date, t: time) -> float:
        """(date, time) -> ms since epoch, as QDateTimeAxis expects."""
        return float(int(datetime.combine(d, t).timestamp() * 1000))
