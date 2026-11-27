"""Log / edit a trade, close a position, or buy to cover.

One dialog, four modes (title + primary button change with the mode):
  * new trade            "Log trade"        (trade=None)
  * edit existing        "Save changes"     (trade given)
  * close long position  "Close position"   (close_holdings_mode=True)
  * cover short position "Buy to cover"     (cover_mode=True)
In the close/cover modes everything except the closing price and date is
locked. Sections show and hide with the order state: the "Position"
panel hides for pending orders, the "Close" panel shows only when the
status is Closed.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from ._common import date_edit, price_spin, shares_spin
from ..portfolio import Trade
from ..widgets import Panel, add_dialog_buttons, align_form_labels, dialog_layout, fmt_signed_money, pl_role, set_text_role

_OPEN, _CLOSED = "OPEN", "CLOSED"


class TradeEditDialog(QDialog):
    """Trade add/edit dialog supporting long, short and pending orders.

    Sizing is driven by the layout (adjustSize after visibility changes);
    calling setFixedHeight() repeatedly while parented to a window hosting a
    QQuickWidget has crashed on Windows.
    """

    def __init__(
            self,
            trade: Optional[Trade] = None,
            watchlist_symbols: Optional[List[str]] = None,
            default_quantity: int = 1,
            quantity_increment: int = 1,
            close_holdings_mode: bool = False,
            cover_mode: bool = False,
            parent=None,
    ):
        super().__init__(parent)
        # Application-modal: otherwise the QQuickWidget can re-render under
        # the dialog and steal focus / mouse events.
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(440)

        self._editing = trade
        self._watchlist_symbols = [str(s).strip().upper() for s in (watchlist_symbols or []) if str(s).strip()]
        self._default_quantity = max(1, int(default_quantity or 1))
        self._quantity_increment = max(1, int(quantity_increment or 1))
        self._close_holdings_mode = bool(close_holdings_mode)
        self._cover_mode = bool(cover_mode)

        if close_holdings_mode:
            title = primary = "Close position"
        elif cover_mode:
            title = primary = "Buy to cover"
        elif trade is not None:
            title, primary = "Edit trade", "Save changes"
        else:
            title = primary = "Log trade"
        self.setWindowTitle(title)

        root = dialog_layout(self)

        # ── Order ───────────────────────────────────────────────────────
        order = Panel("Order")
        form = order.form()
        self.type_combo = QComboBox()
        self.type_combo.addItem("Long (buy)", False)
        self.type_combo.addItem("Short (sell short)", True)
        self.type_lbl = QLabel("Direction")
        form.addRow(self.type_lbl, self.type_combo)

        self.pending_combo = QComboBox()
        self.pending_combo.addItem("Filled", False)
        self.pending_combo.addItem("Pending (not filled yet)", True)
        self.pending_lbl = QLabel("Order")
        form.addRow(self.pending_lbl, self.pending_combo)

        self.instrument_edit = QComboBox()
        self.instrument_edit.setEditable(True)
        self.instrument_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.instrument_edit.addItems(self._watchlist_symbols)
        self.instrument_edit.setEditText("")
        if self.instrument_edit.lineEdit() is not None:
            self.instrument_edit.lineEdit().setPlaceholderText("e.g. NVDA")
        completer = QCompleter(self._watchlist_symbols, self.instrument_edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.instrument_edit.setCompleter(completer)
        form.addRow("Symbol", self.instrument_edit)

        self.share_count_spin = shares_spin(self._default_quantity, self._quantity_increment)
        form.addRow("Shares", self.share_count_spin)

        self.buy_price_spin = price_spin(blank_at_minimum=True)
        self.buy_price_lbl = QLabel("Buy price")
        form.addRow(self.buy_price_lbl, self.buy_price_spin)

        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("Optional, e.g. swing, earnings")
        self.tag_edit.setMaxLength(40)
        form.addRow("Tag", self.tag_edit)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional")
        form.addRow("Notes", self.notes_edit)
        root.addWidget(order)

        # ── Position (hidden while the order is pending) ────────────────
        self._open_section = Panel("Position")
        pform = self._open_section.form()
        self.open_date_edit = date_edit()
        self.status_combo = QComboBox()
        self.status_combo.addItem("Open", _OPEN)
        self.status_combo.addItem("Closed", _CLOSED)
        pform.addRow("Opened", self.open_date_edit)
        pform.addRow("Status", self.status_combo)
        root.addWidget(self._open_section)

        # ── Close (shown when status is Closed) ─────────────────────────
        self._close_section = Panel("Close")
        cform = self._close_section.form()
        self.sell_price_spin = price_spin(blank_at_minimum=True)
        self.sell_price_lbl = QLabel("Sell price")
        self.close_date_edit = date_edit()
        cform.addRow(self.sell_price_lbl, self.sell_price_spin)
        cform.addRow("Closed", self.close_date_edit)
        self.preview_label = QLabel("—")
        self.preview_label.setTextFormat(Qt.TextFormat.PlainText)
        f = self.preview_label.font()
        f.setWeight(f.Weight.DemiBold)
        self.preview_label.setFont(f)
        cform.addRow("Profit", self.preview_label)
        root.addWidget(self._close_section)
        align_form_labels(form, pform, cform)

        root.addStretch(1)
        _row, self.btn_save = add_dialog_buttons(self, root, primary, on_primary=self._accept_if_valid)

        self.type_combo.currentIndexChanged.connect(lambda _i: self._sync_type())
        self.pending_combo.currentIndexChanged.connect(lambda _i: self._sync_pending())
        self.status_combo.currentIndexChanged.connect(lambda _i: self._sync_status())
        self.share_count_spin.valueChanged.connect(self._update_preview)
        self.buy_price_spin.valueChanged.connect(self._update_preview)
        self.sell_price_spin.valueChanged.connect(self._update_preview)

        self._apply_trade(trade)
        self._apply_mode_constraints()
        self._sync_type()
        self._sync_pending()
        self._update_preview()
        self._focus_first_field()

    # ---- state helpers ----

    def _status(self) -> str:
        return self.status_combo.currentData() or _OPEN

    def _set_status(self, status: str) -> None:
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(status)))

    def _is_pending(self) -> bool:
        return bool(self.pending_combo.currentData())

    def _is_short(self) -> bool:
        return bool(self.type_combo.currentData())

    def _apply_trade(self, trade: Optional[Trade]):
        today = date.today()
        self.instrument_edit.setEditText(trade.normalized_instrument() if trade else "")
        self.share_count_spin.setValue(max(1, int(trade.share_count) if trade else self._default_quantity))
        self.buy_price_spin.setValue(float(trade.buy_price) if trade else 0.0)
        self.sell_price_spin.setValue(float(trade.sell_price) if trade and trade.sell_price is not None else 0.0)
        self.type_combo.setCurrentIndex(1 if trade and trade.is_short else 0)
        self.pending_combo.setCurrentIndex(1 if trade and trade.is_pending else 0)
        closed = self._close_holdings_mode or self._cover_mode or bool(trade and trade.is_closed)
        self._set_status(_CLOSED if closed else _OPEN)
        for edit, d in ((self.open_date_edit, trade.open_date if trade else None),
                        (self.close_date_edit, trade.close_date if trade else None)):
            d = d or today
            edit.setDate(QDate(d.year, d.month, d.day))
        self.notes_edit.setText(trade.notes if trade else "")
        self.tag_edit.setText(getattr(trade, "tag", "") if trade else "")

    def _apply_mode_constraints(self):
        if not (self._close_holdings_mode or self._cover_mode):
            return
        self._set_status(_CLOSED)
        self.type_combo.setCurrentIndex(1 if self._cover_mode else 0)
        for w in (self.status_combo, self.instrument_edit, self.share_count_spin, self.buy_price_spin,
                  self.open_date_edit, self.notes_edit, self.tag_edit, self.type_combo,
                  self.pending_combo):
            w.setEnabled(False)

    def _focus_first_field(self) -> None:
        if self._close_holdings_mode or self._cover_mode:
            self.sell_price_spin.setFocus()
            self.sell_price_spin.selectAll()
        elif self._editing is None:
            self.instrument_edit.setFocus()

    def _sync_type(self, *_args):
        if self._is_short():
            self.buy_price_lbl.setText("Short price")
            self.sell_price_lbl.setText("Cover price")
        else:
            self.buy_price_lbl.setText("Buy price")
            self.sell_price_lbl.setText("Sell price")
        self._update_preview()

    def _sync_pending(self, *_args):
        """A pending order has no open date or close yet: hide both panels."""
        pending = self._is_pending()
        self._open_section.setVisible(not pending)
        if pending:
            self._set_status(_OPEN)
            self._close_section.setVisible(False)
        else:
            self._sync_status()
        self._update_preview()
        self._resize_to_content()

    def _sync_status(self, *_args):
        self._close_section.setVisible(self._status() == _CLOSED)
        self._update_preview()
        self._resize_to_content()

    def _resize_to_content(self):
        # Deferred so every visibility change in this call chain has settled.
        QTimer.singleShot(0, self.adjustSize)

    def _update_preview(self, *_args):
        if self._status() != _CLOSED or self.sell_price_spin.value() <= 0:
            self.preview_label.setText("—")
            set_text_role(self.preview_label, "muted")
            return
        qty = int(self.share_count_spin.value())
        buy = float(self.buy_price_spin.value())
        sell = float(self.sell_price_spin.value())
        profit = (buy - sell) * qty if self._is_short() else (sell - buy) * qty
        self.preview_label.setText(fmt_signed_money(profit))
        set_text_role(self.preview_label, pl_role(profit))

    def _invalid(self, message: str, widget) -> None:
        QMessageBox.warning(self, self.windowTitle(), message)
        widget.setFocus()

    def _accept_if_valid(self):
        if not self.instrument_edit.currentText().strip():
            return self._invalid("Enter a symbol, like NVDA.", self.instrument_edit)
        if self.buy_price_spin.value() <= 0:
            label = "short" if self._is_short() else "buy"
            return self._invalid(f"Enter the {label} price.", self.buy_price_spin)
        if self._status() == _CLOSED and not self._is_pending():
            if self.sell_price_spin.value() <= 0:
                label = "cover" if self._is_short() else "sell"
                return self._invalid(f"Enter the {label} price.", self.sell_price_spin)
            opened = self.open_date_edit.date().toPython()
            if self.close_date_edit.date().toPython() < opened:
                return self._invalid(
                    f"The close date is before the open date. Pick {opened:%b %d, %Y} or later.",
                    self.close_date_edit)
        self.accept()

    def to_trade(self) -> Trade:
        closed = self._status() == _CLOSED
        pending = self._is_pending()
        return Trade(
            instrument=self.instrument_edit.currentText().strip().upper(),
            share_count=int(self.share_count_spin.value()),
            buy_price=float(self.buy_price_spin.value()),
            sell_price=(float(self.sell_price_spin.value()) if closed else None),
            open_date=(None if pending else self.open_date_edit.date().toPython()),
            close_date=(self.close_date_edit.date().toPython() if closed else None),
            notes=self.notes_edit.text().strip(),
            is_pending=pending,
            is_short=self._is_short(),
            tag=self.tag_edit.text().strip(),
        )
