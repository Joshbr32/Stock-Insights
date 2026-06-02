"""Trade entry / edit dialog.

The biggest dialog in the project — supports Long, Short, and Pending
orders with collapsible close-side fields. Lives in its own module
since editing the trade form is a high-touch surface.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ._common import GROUP_STYLE
from ..portfolio import Trade


# ---------------------------------------------------------------------------
# Trade entry / edit dialog
# ---------------------------------------------------------------------------

class TradeEditDialog(QDialog):
    """Trade add/edit dialog supporting Long, Short, and Pending orders.

    Close fields (sell price, close date, profit preview) live in a collapsible
    QWidget so the dialog shrinks when status is OPEN and expands when CLOSED.
    Sizing is driven by the layout system (no setFixedHeight) — calling
    setFixedHeight() multiple times during init while the dialog is parented
    to a QMainWindow whose central widget is a QQuickWidget has triggered
    intermittent crashes on Windows.
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
        # Block input to the rest of the app while the dialog is up — without
        # this the QQuickWidget can re-render under the modal and steal the
        # focus / mouse events the dialog expects.
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(420)

        self._editing = trade
        self._watchlist_symbols = [str(s).strip().upper() for s in (watchlist_symbols or []) if str(s).strip()]
        self._default_quantity = max(1, int(default_quantity or 1))
        self._quantity_increment = max(1, int(quantity_increment or 1))
        self._close_holdings_mode = bool(close_holdings_mode)
        self._cover_mode = bool(cover_mode)

        if close_holdings_mode:
            title = "Close Holdings"
        elif cover_mode:
            title = "Buy to Cover"
        else:
            title = "Trade"
        self.setWindowTitle(title)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Section: Trade Details (always visible) ─────────────────────
        details_grp = QGroupBox("Trade Details")
        details_grp.setStyleSheet(GROUP_STYLE)
        form = QFormLayout(details_grp)
        form.setContentsMargins(14, 14, 14, 14)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.type_combo = QComboBox()
        self.type_combo.addItems(["Long (Buy)", "Short (Sell Short)"])
        self.type_lbl = QLabel("Trade Type")
        form.addRow(self.type_lbl, self.type_combo)

        self.pending_combo = QComboBox()
        self.pending_combo.addItems(["Confirmed", "Pending"])
        self.pending_lbl = QLabel("Order Status")
        form.addRow(self.pending_lbl, self.pending_combo)

        self.instrument_edit = QComboBox()
        self.instrument_edit.setEditable(True)
        self.instrument_edit.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.instrument_edit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.instrument_edit.addItems(self._watchlist_symbols)
        self.instrument_edit.setCurrentText("")
        self.instrument_edit.setEditText("")
        if self.instrument_edit.lineEdit() is not None:
            self.instrument_edit.lineEdit().setPlaceholderText("RDDT")
        completer = QCompleter(self._watchlist_symbols, self.instrument_edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.instrument_edit.setCompleter(completer)

        self.share_count_spin = QSpinBox()
        self.share_count_spin.setRange(1, 1_000_000_000)
        self.share_count_spin.setSingleStep(self._quantity_increment)

        self.buy_price_spin = QDoubleSpinBox()
        self.buy_price_spin.setRange(0.0, 1_000_000_000.0)
        self.buy_price_spin.setDecimals(2)
        self.buy_price_spin.setPrefix("$ ")
        self.buy_price_spin.setSpecialValueText("")
        self.buy_price_spin.setValue(self.buy_price_spin.minimum())

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        # Strategy tag — short free-form label ("swing", "earnings",
        # "news") used to filter analytics + history. Optional; left
        # blank for unclassified trades.
        self.tag_edit = QLineEdit()
        self.tag_edit.setPlaceholderText("e.g. swing, earnings, news")
        self.tag_edit.setMaxLength(40)

        form.addRow("Instrument", self.instrument_edit)
        form.addRow("Share count", self.share_count_spin)
        self.buy_price_lbl = QLabel("Buy Price")
        form.addRow(self.buy_price_lbl, self.buy_price_spin)
        form.addRow("Tag", self.tag_edit)
        form.addRow("Notes", self.notes_edit)
        root.addWidget(details_grp)

        # ── Section: Open Date + Status (shown when Confirmed) ──────────
        self._open_section = QGroupBox("Order Status")
        self._open_section.setStyleSheet(GROUP_STYLE)
        open_form = QFormLayout(self._open_section)
        open_form.setContentsMargins(14, 14, 14, 14)
        open_form.setSpacing(10)
        open_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        open_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.open_date_edit = QDateEdit()
        self.open_date_edit.setCalendarPopup(True)
        self.open_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.status_combo = QComboBox()
        self.status_combo.addItems(["OPEN", "CLOSED"])

        open_form.addRow("Open date", self.open_date_edit)
        open_form.addRow("Status", self.status_combo)
        root.addWidget(self._open_section)

        # ── Section: Close Details (shown when Status = CLOSED) ─────────
        self._close_section = QGroupBox("Close Details")
        self._close_section.setStyleSheet(GROUP_STYLE)
        close_form = QFormLayout(self._close_section)
        close_form.setContentsMargins(14, 14, 14, 14)
        close_form.setSpacing(10)
        close_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        close_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.sell_price_spin = QDoubleSpinBox()
        self.sell_price_spin.setRange(0.0, 1_000_000_000.0)
        self.sell_price_spin.setDecimals(2)
        self.sell_price_spin.setPrefix("$ ")
        self.sell_price_spin.setSpecialValueText("")
        self.sell_price_spin.setValue(self.sell_price_spin.minimum())

        self.close_date_edit = QDateEdit()
        self.close_date_edit.setCalendarPopup(True)
        self.close_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.sell_price_lbl = QLabel("Sell Price")
        close_form.addRow(self.sell_price_lbl, self.sell_price_spin)
        close_form.addRow("Close date", self.close_date_edit)

        self.preview_label = QLabel("Trade Profit: —")
        self.preview_label.setStyleSheet("font-weight: 600;")
        close_form.addRow(self.preview_label)
        root.addWidget(self._close_section)

        # ---- Buttons ----
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        if close_holdings_mode:
            btn_label = "Close Holdings"
        elif cover_mode:
            btn_label = "Buy to Cover"
        else:
            btn_label = "Save"
        self.btn_save = QPushButton(btn_label)
        buttons.addButton(self.btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_save.clicked.connect(self._accept_if_valid)
        root.addWidget(buttons)

        self.type_combo.currentTextChanged.connect(self._sync_type)
        self.pending_combo.currentTextChanged.connect(self._sync_pending)
        self.status_combo.currentTextChanged.connect(self._sync_status)
        self.share_count_spin.valueChanged.connect(self._update_preview)
        self.buy_price_spin.valueChanged.connect(self._update_preview)
        self.sell_price_spin.valueChanged.connect(self._update_preview)

        self._apply_trade(trade)
        self._apply_mode_constraints()
        self._sync_type(self.type_combo.currentText())
        self._sync_pending(self.pending_combo.currentText())
        self._update_preview()

    def _apply_trade(self, trade: Optional[Trade]):
        today = date.today()
        self.instrument_edit.setCurrentText(trade.normalized_instrument() if trade else "")
        self.share_count_spin.setValue(max(1, int(trade.share_count) if trade else self._default_quantity))
        self.buy_price_spin.setValue(float(trade.buy_price) if trade else self.buy_price_spin.minimum())
        self.sell_price_spin.setValue(
            float(trade.sell_price) if trade and trade.sell_price is not None else self.sell_price_spin.minimum()
        )
        if trade and trade.is_short:
            self.type_combo.setCurrentText("Short (Sell Short)")
        else:
            self.type_combo.setCurrentText("Long (Buy)")
        if trade and trade.is_pending:
            self.pending_combo.setCurrentText("Pending")
        else:
            self.pending_combo.setCurrentText("Confirmed")
        if self._close_holdings_mode or self._cover_mode:
            self.status_combo.setCurrentText("CLOSED")
        elif trade and trade.is_closed:
            self.status_combo.setCurrentText("CLOSED")
        else:
            self.status_combo.setCurrentText("OPEN")

        open_date = trade.open_date if trade and trade.open_date else today
        close_date = trade.close_date if trade and trade.close_date else today
        self.open_date_edit.setDate(QDate(open_date.year, open_date.month, open_date.day))
        self.close_date_edit.setDate(QDate(close_date.year, close_date.month, close_date.day))
        self.notes_edit.setText(trade.notes if trade else "")
        self.tag_edit.setText(getattr(trade, "tag", "") if trade else "")

    def _apply_mode_constraints(self):
        if self._close_holdings_mode or self._cover_mode:
            self.status_combo.setCurrentText("CLOSED")
            self.status_combo.setEnabled(False)
            self.instrument_edit.setEnabled(False)
            self.share_count_spin.setEnabled(False)
            self.buy_price_spin.setEnabled(False)
            self.open_date_edit.setEnabled(False)
            self.notes_edit.setEnabled(False)
            self.type_combo.setEnabled(False)
            self.pending_combo.setEnabled(False)
            if self._cover_mode:
                self.type_combo.setCurrentText("Short (Sell Short)")
            else:
                self.type_combo.setCurrentText("Long (Buy)")

    def _sync_type(self, text: str):
        is_short = "Short" in text
        if is_short:
            self.buy_price_lbl.setText("Short Price")
            self.sell_price_lbl.setText("Cover Price")
        else:
            self.buy_price_lbl.setText("Buy Price")
            self.sell_price_lbl.setText("Sell Price")
        self._update_preview()

    def _sync_pending(self, text: str):
        """Hide open/status section when Pending — order hasn't been filled yet."""
        is_pending = text == "Pending"
        self._open_section.setVisible(not is_pending)
        if is_pending:
            # Force OPEN so close section also hides; reset status when un-pending
            self.status_combo.setCurrentText("OPEN")
            self._close_section.setVisible(False)
        else:
            # Re-apply status visibility now that open section is shown again
            self._sync_status(self.status_combo.currentText())
        self._update_preview()
        self._resize_to_content()

    def _sync_status(self, status: str):
        """Show/hide close section based on status."""
        closed = status == "CLOSED"
        self._close_section.setVisible(closed)
        self._update_preview()
        self._resize_to_content()

    def _resize_to_content(self):
        """Re-size the dialog to fit the currently visible sections.

        Replaces the previous setFixedHeight() approach which fired
        repeatedly during init and triggered crashes when the dialog was
        parented to a window hosting a QQuickWidget. adjustSize() respects
        the layout's sizeHint, so the dialog naturally grows/shrinks as
        sections become visible/invisible.
        """
        # Defer until the next event-loop tick so all visibility changes
        # in the current call chain have settled before we re-size.
        QTimer.singleShot(0, self.adjustSize)

    def _update_preview(self):
        if self.status_combo.currentText() != "CLOSED":
            self.preview_label.setText("Trade Profit: —")
            return
        is_short = "Short" in self.type_combo.currentText()
        qty = int(self.share_count_spin.value())
        buy = float(self.buy_price_spin.value())
        sell = float(self.sell_price_spin.value())
        profit = (buy - sell) * qty if is_short else (sell - buy) * qty
        self.preview_label.setText(f"Trade Profit: $ {profit:,.2f}")

    def _accept_if_valid(self):
        instrument = self.instrument_edit.currentText().strip().upper()
        if not instrument:
            QMessageBox.warning(self, "Missing instrument", "Enter an instrument symbol.")
            return
        if self.status_combo.currentText() == "CLOSED":
            if not self._is_pending():
                if self.close_date_edit.date().toPython() < self.open_date_edit.date().toPython():
                    QMessageBox.warning(self, "Invalid dates", "Close date cannot be before open date.")
                    return
        self.accept()

    def _is_pending(self) -> bool:
        return self.pending_combo.currentText() == "Pending"

    def _is_short(self) -> bool:
        return "Short" in self.type_combo.currentText()

    def to_trade(self) -> Trade:
        closed = self.status_combo.currentText() == "CLOSED"
        pending = self._is_pending()
        is_short = self._is_short()
        return Trade(
            instrument=self.instrument_edit.currentText().strip().upper(),
            share_count=int(self.share_count_spin.value()),
            buy_price=float(self.buy_price_spin.value()),
            sell_price=(float(self.sell_price_spin.value()) if closed else None),
            open_date=(None if pending else self.open_date_edit.date().toPython()),
            close_date=(self.close_date_edit.date().toPython() if closed else None),
            notes=self.notes_edit.text().strip(),
            is_pending=pending,
            is_short=is_short,
            tag=self.tag_edit.text().strip(),
        )
