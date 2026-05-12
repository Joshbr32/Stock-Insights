"""Per-symbol drill-down dialog.

Opened from the Holdings + Trade History context menus via
"View All Trades for {SYMBOL}". Shows everything that's ever happened
for one ticker:

  • Header — symbol + current open position (if any)
  • Stat strip — closed trades, win rate, realized P/L, max drawdown
  • Mini equity curve scoped to the symbol (cumulative realized $)
  • Chronological trade list (read-only — just for review)

Reuses portfolio.py compute helpers — no new math, just a focused
projection of what's already on screen elsewhere.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional

# QtCharts is in PySide6-Addons. Importing here registers the C++
# widget side; the QML side is registered separately (main_window.py).
from PySide6.QtCharts import (
    QChart,
    QChartView,
    QDateTimeAxis,
    QLineSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .portfolio import (
    Trade,
    compute_trade_analytics,
)


# ─────────────────────────────────────────────────────────────────────────────
# Formatting helpers (mirror the QML _money / _date helpers in qml_bridge.py
# so dialog text reads the same as the surrounding UI)
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    return f"{sign}$ {abs(value):,.2f}"


def _fmt_signed(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}$ {abs(value):,.2f}".replace("+-", "-")


def _fmt_pct(value: Optional[float], digits: int = 1) -> str:
    return "—" if value is None else f"{value:.{digits}f}%"


def _fmt_date(d: Optional[date]) -> str:
    return "" if d is None else d.isoformat()


def _profit_color(value: Optional[float]) -> str:
    """Hex color for a P/L value — matches the theme's good/bad tokens
    but hard-coded here because dialogs don't have access to the QML
    theme controller. Close enough across all themes that the user
    won't notice."""
    if value is None or abs(value) < 0.005:
        return "#9ca3af"  # neutral grey
    return "#10b981" if value > 0 else "#ef4444"  # green / red


# ─────────────────────────────────────────────────────────────────────────────
# Dialog
# ─────────────────────────────────────────────────────────────────────────────

class SymbolHistoryDialog(QDialog):
    """Read-only drill-down of every trade for a single symbol."""

    def __init__(
            self,
            instrument: str,
            trades: List[Trade],
            current_mark: Optional[float] = None,
            parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Trade History — {instrument}")
        # Sized so the chart has room without dominating the screen on
        # smaller monitors. Resizable; not fixed.
        self.resize(720, 580)

        # Filter input trades down to this symbol once, then derive
        # everything else from the slice.
        instr = (instrument or "").strip().upper()
        self._symbol = instr
        self._trades = [
            t for t in trades
            if t.normalized_instrument() == instr
        ]
        self._mark = current_mark

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        root.addWidget(self._build_header())
        root.addWidget(self._build_stat_strip())
        root.addWidget(self._build_chart(), stretch=2)
        root.addWidget(self._build_trade_table(), stretch=3)

        # Standard close button at the bottom — read-only dialog, no
        # OK/Cancel needed. Esc also closes.
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

    # ── Header ───────────────────────────────────────────────────────
    def _build_header(self) -> QWidget:
        row = QFrame()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        title = QLabel(self._symbol)
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        h.addWidget(title)

        # Current open position summary on the right — qty + avg cost +
        # mark + unrealized P/L. Computed inline (small enough that
        # pulling in compute_holdings_from_trades is overkill).
        open_trades = [t for t in self._trades
                       if not t.is_closed and not t.is_pending]
        if open_trades:
            qty = sum(int(t.share_count) for t in open_trades)
            cost = sum(float(t.buy_price) * int(t.share_count)
                       for t in open_trades)
            avg = (cost / qty) if qty > 0 else 0.0
            is_short = any(t.is_short for t in open_trades)
            sign_qty = -qty if is_short else qty

            label = QLabel(
                f"<b>{sign_qty:+,d} sh</b> @ avg "
                f"<b>{_fmt_money(avg)}</b>"
            )
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addStretch(1)
            h.addWidget(label)

            if self._mark is not None:
                upl = (self._mark - avg) * qty * (-1 if is_short else 1)
                upl_label = QLabel(
                    f"  Mark <b>{_fmt_money(self._mark)}</b> "
                    f"·  Unrealized <b style='color:{_profit_color(upl)}'>"
                    f"{_fmt_signed(upl)}</b>"
                )
                upl_label.setTextFormat(Qt.TextFormat.RichText)
                h.addWidget(upl_label)
        else:
            sub = QLabel("No open position")
            sub.setStyleSheet("color: #9ca3af;")
            h.addStretch(1)
            h.addWidget(sub)

        return row

    # ── Stat strip ───────────────────────────────────────────────────
    def _build_stat_strip(self) -> QWidget:
        # We deliberately compute analytics from THIS SYMBOL'S trades
        # only, not the whole account — that's the entire point of the
        # drill-down.
        a = compute_trade_analytics(self._trades)

        row = QFrame()
        row.setStyleSheet(
            "QFrame { background: rgba(127,127,127,0.06); "
            "border-radius: 6px; }"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(24)

        for label, value, color in [
            ("Closed", str(a.closed_trades), "#9ca3af"),
            ("Win rate", _fmt_pct(a.win_rate_pct), "#9ca3af"),
            ("Realized", _fmt_signed(a.realized_profit),
             _profit_color(a.realized_profit)),
            ("Best", _fmt_signed(a.best_trade), _profit_color(a.best_trade)),
            ("Worst", _fmt_signed(a.worst_trade), _profit_color(a.worst_trade)),
            # Drawdown — useful for any symbol the user has churned in
            # and out of multiple times.
            ("Max DD", _fmt_money(a.max_drawdown),
             _profit_color(-(a.max_drawdown or 0))),
        ]:
            cell = QVBoxLayout()
            cell.setSpacing(2)
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #9ca3af; font-size: 10px; "
                              "text-transform: uppercase; "
                              "letter-spacing: 0.04em;")
            val = QLabel(value)
            val.setStyleSheet(f"color: {color}; font-weight: 600; "
                              "font-size: 14px;")
            cell.addWidget(lbl)
            cell.addWidget(val)
            wrapper = QWidget()
            wrapper.setLayout(cell)
            h.addWidget(wrapper)

        h.addStretch(1)
        return row

    # ── Mini equity curve ────────────────────────────────────────────
    def _build_chart(self) -> QWidget:
        """Cumulative realized P/L for this symbol over time. Same idea
        as EquityCurveCard.qml but scoped to one ticker. Returns a
        graceful empty state when there are no closed trades."""
        closed = [t for t in self._trades
                  if t.is_closed and t.close_date is not None
                  and t.trade_profit is not None and not t.is_pending]

        chart = QChart()
        chart.setTitle("")
        chart.legend().hide()
        chart.setBackgroundBrush(Qt.BrushStyle.NoBrush)
        chart.setMargins(self._zero_margins())

        if not closed:
            # Empty-state: no chart, just a centered hint label so the
            # dialog doesn't show a confusingly empty axis.
            holder = QFrame()
            v = QVBoxLayout(holder)
            v.setContentsMargins(0, 0, 0, 0)
            empty = QLabel("No closed trades for this symbol yet")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #9ca3af; padding: 30px;")
            v.addWidget(empty)
            holder.setMinimumHeight(140)
            return holder

        # Sort by close_date so the cumulative sum reflects chronology.
        closed.sort(key=lambda t: t.close_date)

        series = QLineSeries()
        # Seed with a zero point one day before the first close — same
        # convention as the main equity curve so curves visually rise
        # from the baseline rather than starting mid-air.
        from datetime import timedelta
        seed = closed[0].close_date - timedelta(days=1)
        series.append(self._epoch_ms(seed, time(0, 0)), 0.0)
        running = 0.0
        for t in closed:
            running += float(t.trade_profit or 0.0)
            series.append(self._epoch_ms(t.close_date, time(16, 0)), running)

        chart.addSeries(series)

        x_axis = QDateTimeAxis()
        x_axis.setFormat("MMM d")
        x_axis.setTickCount(5)
        chart.addAxis(x_axis, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(x_axis)

        y_axis = QValueAxis()
        y_axis.setLabelFormat("$ %.0f")
        # Pad ±5% so the line doesn't kiss the top/bottom edges.
        ys = [series.at(i).y() for i in range(series.count())]
        lo, hi = min(0, min(ys)), max(0, max(ys))
        span = max(1.0, abs(hi - lo))
        y_axis.setRange(lo - span * 0.05, hi + span * 0.05)
        chart.addAxis(y_axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(y_axis)

        view = QChartView(chart)
        view.setRenderHint(QPainter.RenderHint.Antialiasing)
        view.setMinimumHeight(140)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return view

    # ── Trade table ──────────────────────────────────────────────────
    def _build_trade_table(self) -> QWidget:
        """Read-only chronological list of every trade for this symbol.
        Open positions render with blank close columns; pending orders
        render as their own status. Sorted oldest-first so the user can
        read the entry+exit story top-to-bottom."""
        rows = sorted(
            self._trades,
            # Sort key: (filled_date, original_order). Pending trades sort
            # last with a sentinel max date.
            key=lambda t: (t.open_date or date.max, t.close_date or date.max),
        )

        cols = ["Date", "Side", "Status", "Qty",
                "Buy", "Sell", "Profit", "Tag", "Notes"]
        table = QTableWidget(len(rows), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        # Last column (notes) takes the leftover space; everything else
        # sized to its contents.
        header = table.horizontalHeader()
        for i in range(len(cols) - 1):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(cols) - 1, QHeaderView.ResizeMode.Stretch)

        for row_idx, t in enumerate(rows):
            d = t.close_date or t.open_date
            cells = [
                _fmt_date(d),
                "Short" if t.is_short else "Long",
                t.status,
                f"{int(t.share_count):,d}",
                _fmt_money(float(t.buy_price)),
                "" if t.sell_price is None else _fmt_money(float(t.sell_price)),
                _fmt_signed(t.trade_profit) if t.trade_profit is not None else "",
                (t.tag or "").strip(),
                (t.notes or "").strip(),
            ]
            for col_idx, text in enumerate(cells):
                item = QTableWidgetItem(text)
                # Right-align numeric columns
                if col_idx in (3, 4, 5, 6):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight
                        | Qt.AlignmentFlag.AlignVCenter,
                    )
                # Color the Profit cell
                if col_idx == 6 and t.trade_profit is not None:
                    item.setForeground(self._color_brush(t.trade_profit))
                table.setItem(row_idx, col_idx, item)

        return table

    # ── Small helpers ────────────────────────────────────────────────
    @staticmethod
    def _epoch_ms(d: date, t: time) -> float:
        """Convert (date, time) to milliseconds-since-epoch — what
        QtCharts.QDateTimeAxis expects from QLineSeries.append()."""
        return float(int(datetime.combine(d, t).timestamp() * 1000))

    @staticmethod
    def _zero_margins():
        """Tight chart margins — the dialog already has its own padding."""
        from PySide6.QtCore import QMargins
        return QMargins(4, 4, 4, 4)

    @staticmethod
    def _color_brush(value: float):
        from PySide6.QtGui import QBrush, QColor
        return QBrush(QColor(_profit_color(value)))
