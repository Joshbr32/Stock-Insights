"""Dialogs that act on an existing order or position.

* FulfillOrderDialog — "Mark order filled": a pending order becomes an open
  trade with a fill date and (possibly different) fill price.
* MarkDownDialog — buy more to bring the average cost down to a target;
  solves the required buy price with portfolio.solve_buy_mark_for_target_avg.
* DoubleDownDialog — buy more at a chosen price and preview the new average.

Each returns the new/updated values through accessors (`to_trade()`,
`get_fill_date()`, `get_fill_price()`); the caller persists them.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit

from ._common import date_edit, price_spin, shares_spin
from ..portfolio import Holding, Trade, solve_buy_mark_for_target_avg
from ..widgets import Panel, add_dialog_buttons, align_form_labels, dialog_layout, fmt_int, fmt_money, muted_label, set_text_role


def _result_label() -> QLabel:
    lbl = QLabel("—")
    f = lbl.font()
    f.setWeight(f.Weight.DemiBold)
    lbl.setFont(f)
    return lbl


def _position_panel(holding: Holding, current_mark: Optional[float] = None, show_mark: bool = False) -> Panel:
    panel = Panel(f"Your {holding.normalized_instrument()} position")
    form = panel.form()
    form.addRow("Shares", QLabel(fmt_int(holding.qty)))
    form.addRow("Average cost", QLabel(fmt_money(holding.avg_cost)))
    if show_mark:
        form.addRow("Current price", QLabel(fmt_money(current_mark)) if current_mark is not None
                    else muted_label("Not loaded yet", wrap=False))
    return panel


def _blended_avg(holding: Holding, buy_qty: int, buy_price: float) -> tuple:
    total_qty = int(holding.qty) + buy_qty
    avg = (float(holding.avg_cost) * int(holding.qty) + buy_price * buy_qty) / total_qty
    return total_qty, avg


# ---------------------------------------------------------------------------
# Mark order filled
# ---------------------------------------------------------------------------

class FulfillOrderDialog(QDialog):
    """Confirm a pending order: set the fill date and, if needed, the price."""

    def __init__(self, trade: Trade, parent=None):
        super().__init__(parent)
        self._trade = trade
        self.setWindowTitle("Mark order filled")
        self.setMinimumWidth(400)

        root = dialog_layout(self)
        side = "Short" if trade.is_short else "Buy"
        panel = Panel(f"{side} {trade.share_count:,d} {trade.normalized_instrument()}",
                      subtitle=f"Order price {fmt_money(trade.buy_price)}")
        form = panel.form()
        self.open_date_edit = date_edit()
        self.fill_price_spin = price_spin(float(trade.buy_price), minimum=0.01)
        form.addRow("Filled on", self.open_date_edit)
        form.addRow("Fill price", self.fill_price_spin)
        panel.body.addWidget(muted_label("Change the price if your broker filled at a different one."))
        root.addWidget(panel)

        root.addStretch(1)
        add_dialog_buttons(self, root, "Mark filled")

    def get_fill_date(self):
        return self.open_date_edit.date().toPython()

    def get_fill_price(self) -> float:
        return float(self.fill_price_spin.value())


# ---------------------------------------------------------------------------
# Mark down
# ---------------------------------------------------------------------------

class MarkDownDialog(QDialog):
    def __init__(self, holding: Holding, default_quantity: int = 1, quantity_increment: int = 1, parent=None):
        super().__init__(parent)
        self._holding = holding
        self._computed_buy_price: Optional[float] = None
        sym = holding.normalized_instrument()

        self.setWindowTitle(f"Mark down {sym}")
        self.setMinimumWidth(440)
        root = dialog_layout(self)
        position = _position_panel(holding)
        root.addWidget(position)

        order = Panel("Buy more to lower your average")
        form = order.form()
        self.buy_qty_spin = shares_spin(max(1, int(default_quantity or 1)), quantity_increment)
        self.target_avg_spin = price_spin(round(float(holding.avg_cost), 2), minimum=0.01)
        self.open_date_edit = date_edit()
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional")
        form.addRow("Shares to buy", self.buy_qty_spin)
        form.addRow("Target average", self.target_avg_spin)
        form.addRow("Date", self.open_date_edit)
        form.addRow("Notes", self.notes_edit)
        root.addWidget(order)

        result = Panel("Result")
        rform = result.form()
        self.required_buy_price = _result_label()
        self.resulting_qty = QLabel("—")
        self.resulting_avg = QLabel("—")
        self.order_cost = QLabel("—")
        rform.addRow("Buy price needed", self.required_buy_price)
        rform.addRow("New share count", self.resulting_qty)
        rform.addRow("New average", self.resulting_avg)
        rform.addRow("Order cost", self.order_cost)
        align_form_labels(position.form(), form, rform)
        self.error_label = muted_label("")
        self.error_label.setVisible(False)
        result.body.addWidget(self.error_label)
        root.addWidget(result)

        root.addStretch(1)
        _row, self.btn_save = add_dialog_buttons(self, root, "Log trade", on_primary=self._accept_if_valid)

        self.buy_qty_spin.valueChanged.connect(self._recompute)
        self.target_avg_spin.valueChanged.connect(self._recompute)
        self._recompute()

    def _recompute(self, *_args):
        buy_qty = int(self.buy_qty_spin.value())
        target_avg = float(self.target_avg_spin.value())
        try:
            buy_price = solve_buy_mark_for_target_avg(
                current_qty=int(self._holding.qty),
                current_avg_cost=float(self._holding.avg_cost),
                buy_qty=buy_qty,
                target_mark=target_avg,
            )
        except (ValueError, ZeroDivisionError) as exc:
            return self._show_unreachable(str(exc))
        if buy_price <= 0:
            return self._show_unreachable(
                "You can't reach that average with this many shares. "
                "Raise the target average or buy more shares.")
        total_qty, blended = _blended_avg(self._holding, buy_qty, buy_price)
        self.required_buy_price.setText(fmt_money(buy_price))
        self.resulting_qty.setText(fmt_int(total_qty))
        self.resulting_avg.setText(fmt_money(blended))
        self.order_cost.setText(fmt_money(buy_price * buy_qty))
        self.error_label.setVisible(False)
        self.btn_save.setEnabled(True)
        self._computed_buy_price = float(buy_price)

    def _show_unreachable(self, message: str) -> None:
        for lbl in (self.required_buy_price, self.resulting_qty, self.resulting_avg, self.order_cost):
            lbl.setText("—")
        self.error_label.setText(message)
        set_text_role(self.error_label, "error")
        self.error_label.setVisible(True)
        self.btn_save.setEnabled(False)
        self._computed_buy_price = None

    def _accept_if_valid(self):
        if self._computed_buy_price is not None:
            self.accept()

    def to_trade(self) -> Trade:
        return Trade(
            instrument=self._holding.normalized_instrument(),
            share_count=int(self.buy_qty_spin.value()),
            buy_price=float(self._computed_buy_price),
            sell_price=None,
            open_date=self.open_date_edit.date().toPython(),
            close_date=None,
            notes=self.notes_edit.text().strip(),
        )


# ---------------------------------------------------------------------------
# Double down
# ---------------------------------------------------------------------------

class DoubleDownDialog(QDialog):
    def __init__(self, holding: Holding, current_mark: Optional[float] = None, quantity_increment: int = 1,
                 parent=None):
        super().__init__(parent)
        self._holding = holding
        sym = holding.normalized_instrument()

        self.setWindowTitle(f"Double down on {sym}")
        self.setMinimumWidth(440)
        root = dialog_layout(self)
        position = _position_panel(holding, current_mark, show_mark=True)
        root.addWidget(position)

        order = Panel("Buy more")
        form = order.form()
        self.buy_qty_spin = shares_spin(max(1, int(holding.qty)), quantity_increment)
        default_buy = float(current_mark) if current_mark is not None else float(holding.avg_cost)
        self.buy_price_spin = price_spin(round(default_buy, 2), minimum=0.01)
        self.open_date_edit = date_edit()
        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional")
        form.addRow("Shares to buy", self.buy_qty_spin)
        form.addRow("Buy price", self.buy_price_spin)
        form.addRow("Date", self.open_date_edit)
        form.addRow("Notes", self.notes_edit)
        root.addWidget(order)

        result = Panel("Result")
        rform = result.form()
        self.resulting_qty = QLabel("—")
        self.resulting_avg = _result_label()
        self.order_cost = QLabel("—")
        rform.addRow("New share count", self.resulting_qty)
        rform.addRow("New average", self.resulting_avg)
        rform.addRow("Order cost", self.order_cost)
        align_form_labels(position.form(), form, rform)
        root.addWidget(result)

        root.addStretch(1)
        _row, self.btn_save = add_dialog_buttons(self, root, "Log trade")

        self.buy_qty_spin.valueChanged.connect(self._recompute)
        self.buy_price_spin.valueChanged.connect(self._recompute)
        self._recompute()

    def _recompute(self, *_args):
        buy_qty = int(self.buy_qty_spin.value())
        buy_price = float(self.buy_price_spin.value())
        total_qty, blended = _blended_avg(self._holding, buy_qty, buy_price)
        self.resulting_qty.setText(fmt_int(total_qty))
        self.resulting_avg.setText(fmt_money(blended))
        self.order_cost.setText(fmt_money(buy_price * buy_qty))

    def to_trade(self) -> Trade:
        return Trade(
            instrument=self._holding.normalized_instrument(),
            share_count=int(self.buy_qty_spin.value()),
            buy_price=float(self.buy_price_spin.value()),
            sell_price=None,
            open_date=self.open_date_edit.date().toPython(),
            close_date=None,
            notes=self.notes_edit.text().strip(),
        )
