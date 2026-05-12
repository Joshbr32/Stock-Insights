"""Trade-action dialogs: Fulfill (pending → open), Mark Down, Double Down.

Three small dialogs grouped together because they all act on an
existing trade or holding rather than creating one from scratch.
Mark Down + Double Down both compute "what buy price would I need to
hit a target average cost?" via portfolio.solve_buy_mark_for_target_avg.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ._common import GROUP_STYLE
from ..portfolio import Holding, Trade, solve_buy_mark_for_target_avg


# ---------------------------------------------------------------------------
# Fulfill pending order dialog
# ---------------------------------------------------------------------------

class FulfillOrderDialog(QDialog):
    """Confirm a pending (WAITING) trade order — set the actual open date and
    optionally adjust the fill price if it differs from the order price."""

    def __init__(self, trade: Trade, parent=None):
        super().__init__(parent)
        self._trade = trade
        self.setWindowTitle("Mark Order as Fulfilled")
        self.resize(380, 240)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        info = QLabel(
            f"<b>{trade.normalized_instrument()}</b> — "
            f"{'Short' if trade.is_short else 'Long'}  {trade.share_count:,d} shares<br>"
            f"Order price: $ {trade.buy_price:,.2f}"
        )
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        self.open_date_edit = QDateEdit()
        self.open_date_edit.setCalendarPopup(True)
        self.open_date_edit.setDisplayFormat("yyyy-MM-dd")
        today = date.today()
        self.open_date_edit.setDate(QDate(today.year, today.month, today.day))

        self.fill_price_spin = QDoubleSpinBox()
        self.fill_price_spin.setRange(0.01, 1_000_000_000.0)
        self.fill_price_spin.setDecimals(2)
        self.fill_price_spin.setPrefix("$ ")
        self.fill_price_spin.setValue(float(trade.buy_price))

        form.addRow("Fill Date:", self.open_date_edit)
        form.addRow("Fill Price:", self.fill_price_spin)
        root.addLayout(form)

        note = QLabel("Fill price defaults to the order price. Adjust if your broker filled at a different price.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(note)

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_fill_date(self):
        return self.open_date_edit.date().toPython()

    def get_fill_price(self) -> float:
        return float(self.fill_price_spin.value())


# ---------------------------------------------------------------------------
# Mark Down dialog
# ---------------------------------------------------------------------------

class MarkDownDialog(QDialog):
    def __init__(self, holding: Holding, default_quantity: int = 1, quantity_increment: int = 1, parent=None):
        super().__init__(parent)
        self._holding = holding
        self._default_quantity = max(1, int(default_quantity or 1))
        self._quantity_increment = max(1, int(quantity_increment or 1))
        self._computed_buy_price: Optional[float] = None

        self.setWindowTitle("Mark Down")
        self.resize(460, 340)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        cg = QGroupBox("Current Holding")
        cg.setStyleSheet(GROUP_STYLE)
        cgg = QGridLayout(cg)
        cgg.setContentsMargins(14, 14, 14, 14)
        cgg.addWidget(QLabel("Instrument"), 0, 0);
        cgg.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        cgg.addWidget(QLabel("Qty"), 1, 0);
        cgg.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        cgg.addWidget(QLabel("Avg Cost"), 2, 0);
        cgg.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
        root.addWidget(cg)

        og = QGroupBox("Mark Down Order")
        og.setStyleSheet(GROUP_STYLE)
        form = QFormLayout(og)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.buy_qty_spin = QSpinBox()
        self.buy_qty_spin.setRange(1, 1_000_000_000)
        self.buy_qty_spin.setSingleStep(self._quantity_increment)
        self.buy_qty_spin.setValue(self._default_quantity)

        self.target_avg_spin = QDoubleSpinBox()
        self.target_avg_spin.setRange(0.01, 1_000_000_000.0)
        self.target_avg_spin.setDecimals(2)
        self.target_avg_spin.setPrefix("$ ")
        self.target_avg_spin.setValue(max(0.01, round(float(holding.avg_cost), 2)))

        self.open_date_edit = QDateEdit()
        self.open_date_edit.setCalendarPopup(True)
        self.open_date_edit.setDisplayFormat("yyyy-MM-dd")
        today = date.today()
        self.open_date_edit.setDate(QDate(today.year, today.month, today.day))

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        self.required_buy_price = QLabel("—")
        self.resulting_qty = QLabel("—")
        self.resulting_avg = QLabel("—")
        self.order_cost = QLabel("—")

        form.addRow("Buy Qty", self.buy_qty_spin)
        form.addRow("Target Avg Cost", self.target_avg_spin)
        form.addRow("Open Date", self.open_date_edit)
        form.addRow("Notes", self.notes_edit)
        form.addRow("Required Buy Price", self.required_buy_price)
        form.addRow("Resulting Qty", self.resulting_qty)
        form.addRow("Resulting Avg Cost", self.resulting_avg)
        form.addRow("Order Cost", self.order_cost)
        root.addWidget(og)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_save = QPushButton("Add Mark Down Trade")
        buttons.addButton(self.btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_save.clicked.connect(self._accept_if_valid)
        root.addWidget(buttons)

        self.buy_qty_spin.valueChanged.connect(self._recompute)
        self.target_avg_spin.valueChanged.connect(self._recompute)
        self._recompute()

    def _recompute(self):
        try:
            buy_qty = int(self.buy_qty_spin.value())
            target_avg = float(self.target_avg_spin.value())
            buy_price = solve_buy_mark_for_target_avg(
                current_qty=int(self._holding.qty),
                current_avg_cost=float(self._holding.avg_cost),
                buy_qty=buy_qty,
                target_mark=target_avg,
            )
            if buy_price < 0:
                raise ValueError("Target avg cannot be reached with a positive buy price at this quantity.")
            total_qty = int(self._holding.qty) + buy_qty
            blended_avg = ((float(self._holding.avg_cost) * int(self._holding.qty)) + (buy_price * buy_qty)) / total_qty
            self.required_buy_price.setText(f"$ {buy_price:,.2f}")
            self.resulting_qty.setText(f"{total_qty:,d}")
            self.resulting_avg.setText(f"$ {blended_avg:,.2f}")
            self.order_cost.setText(f"$ {(buy_price * buy_qty):,.2f}")
            self.btn_save.setEnabled(True)
            self._computed_buy_price = float(buy_price)
        except Exception as exc:
            self.required_buy_price.setText(str(exc))
            self.resulting_qty.setText("—");
            self.resulting_avg.setText("—");
            self.order_cost.setText("—")
            self.btn_save.setEnabled(False)
            self._computed_buy_price = None

    def _accept_if_valid(self):
        if self._computed_buy_price is None:
            return
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
# Double Down dialog
# ---------------------------------------------------------------------------

class DoubleDownDialog(QDialog):
    def __init__(self, holding: Holding, current_mark: Optional[float] = None, quantity_increment: int = 1,
                 parent=None):
        super().__init__(parent)
        self._holding = holding
        self._quantity_increment = max(1, int(quantity_increment or 1))

        self.setWindowTitle("Double Down")
        self.resize(460, 340)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        cg = QGroupBox("Current Holding")
        cg.setStyleSheet(GROUP_STYLE)
        cgg = QGridLayout(cg)
        cgg.setContentsMargins(14, 14, 14, 14)
        cgg.addWidget(QLabel("Instrument"), 0, 0);
        cgg.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        cgg.addWidget(QLabel("Qty"), 1, 0);
        cgg.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        cgg.addWidget(QLabel("Avg Cost"), 2, 0);
        cgg.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
        cgg.addWidget(QLabel("Current Mark"), 3, 0)
        cgg.addWidget(QLabel("—" if current_mark is None else f"$ {float(current_mark):,.2f}"), 3, 1)
        root.addWidget(cg)

        og = QGroupBox("Double Down Order")
        og.setStyleSheet(GROUP_STYLE)
        form = QFormLayout(og)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)

        self.buy_qty_spin = QSpinBox()
        self.buy_qty_spin.setRange(1, 1_000_000_000)
        self.buy_qty_spin.setSingleStep(self._quantity_increment)
        self.buy_qty_spin.setValue(max(1, int(holding.qty)))

        self.buy_price_spin = QDoubleSpinBox()
        self.buy_price_spin.setRange(0.01, 1_000_000_000.0)
        self.buy_price_spin.setDecimals(2)
        self.buy_price_spin.setPrefix("$ ")
        default_buy = float(current_mark) if current_mark is not None else float(holding.avg_cost)
        self.buy_price_spin.setValue(max(0.01, round(default_buy, 2)))

        self.open_date_edit = QDateEdit()
        self.open_date_edit.setCalendarPopup(True)
        self.open_date_edit.setDisplayFormat("yyyy-MM-dd")
        today = date.today()
        self.open_date_edit.setDate(QDate(today.year, today.month, today.day))

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        self.resulting_qty = QLabel("—")
        self.resulting_avg = QLabel("—")
        self.order_cost = QLabel("—")

        form.addRow("Buy Qty", self.buy_qty_spin)
        form.addRow("Buy Price", self.buy_price_spin)
        form.addRow("Open Date", self.open_date_edit)
        form.addRow("Notes", self.notes_edit)
        form.addRow("Resulting Qty", self.resulting_qty)
        form.addRow("Resulting Avg Cost", self.resulting_avg)
        form.addRow("Order Cost", self.order_cost)
        root.addWidget(og)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_save = QPushButton("Add Double Down Trade")
        buttons.addButton(self.btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self.buy_qty_spin.valueChanged.connect(self._recompute)
        self.buy_price_spin.valueChanged.connect(self._recompute)
        self._recompute()

    def _recompute(self):
        buy_qty = int(self.buy_qty_spin.value())
        buy_price = float(self.buy_price_spin.value())
        total_qty = int(self._holding.qty) + buy_qty
        blended_avg = ((float(self._holding.avg_cost) * int(self._holding.qty)) + (buy_price * buy_qty)) / total_qty
        self.resulting_qty.setText(f"{total_qty:,d}")
        self.resulting_avg.setText(f"$ {blended_avg:,.2f}")
        self.order_cost.setText(f"$ {(buy_price * buy_qty):,.2f}")

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
