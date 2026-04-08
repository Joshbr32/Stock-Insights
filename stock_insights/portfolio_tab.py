from __future__ import annotations

import json

from datetime import date
from typing import Dict, List, Optional

from PySide6.QtCore import QDate, QPoint, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .portfolio import (
    GoalProgress,
    Holding,
    Trade,
    compute_goal_progress,
    compute_holdings_from_trades,
    compute_portfolio,
    compute_realized_pl_by_symbol,
    compute_trade_analytics,
    compute_trade_rows,
    solve_buy_mark_for_target_avg,
    trades_from_json,
    trades_to_json,
)

GROUP_STYLE = (
    "QGroupBox { margin-top: 8px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
)

_DEFAULT_PRESETS = [250_000.0, 500_000.0, 1_000_000.0]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_money(value: float) -> str:
    return f"$ {float(value):,.2f}"


def _fmt_goal(value: float) -> str:
    return f"$ {float(value):,.0f}"


def _fmt_preset_label(value: float) -> str:
    """Compact label for a preset button: '250K', '1M', '1.5M', etc."""
    if value >= 1_000_000:
        n = value / 1_000_000
        return f"{n:g}M"
    if value >= 1_000:
        n = value / 1_000
        return f"{n:g}K"
    return f"{value:g}"


def _make_goal_spin(value: float = 500_000.0) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(1.0, 999_000_000.0)
    spin.setDecimals(0)
    spin.setSingleStep(10_000.0)
    spin.setPrefix("$ ")
    spin.setMinimumWidth(130)
    spin.setValue(float(value))
    return spin


def _make_preset_spin(value: float) -> QDoubleSpinBox:
    """Compact spinbox for editing a preset value inside the dialog."""
    spin = QDoubleSpinBox()
    spin.setRange(1.0, 999_000_000.0)
    spin.setDecimals(0)
    spin.setSingleStep(10_000.0)
    spin.setPrefix("$ ")
    spin.setMinimumWidth(110)
    spin.setValue(float(value))
    return spin


def _load_account_presets(settings: QSettings, account_name: str) -> List[float]:
    """Load the 3 preset values for an account, falling back to defaults."""
    raw = settings.value(f"goals/presets/{account_name}", None)
    if raw is not None:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list) and len(parsed) == 3:
                return [max(1.0, float(x)) for x in parsed]
        except Exception:
            pass
    return list(_DEFAULT_PRESETS)


def _save_account_presets(settings: QSettings, account_name: str, presets: List[float]):
    settings.setValue(f"goals/presets/{account_name}", json.dumps([float(p) for p in presets]))


# ---------------------------------------------------------------------------
# Goal Dashboard Options dialog
# ---------------------------------------------------------------------------

class _AccountGoalBlock(QGroupBox):
    """A self-contained block for one account inside the GoalDashboardOptionsDialog.

    Layout
    ──────
      ┌ Josh ──────────────────────────────────────────────────────────────┐
      │  [x] Include in shared goal group                                  │
      │  Individual Goal: [$ 500,000]   (hidden when shared)              │
      │  Presets:  [$ 250,000]  [$ 500,000]  [$ 1,000,000]               │
      └────────────────────────────────────────────────────────────────────┘
    """

    sharedToggled = Signal()

    def __init__(
        self,
        account_name: str,
        is_shared: bool,
        current_goal: float,
        preset_values: List[float],
        parent=None,
    ):
        super().__init__(account_name, parent)
        self.setStyleSheet(GROUP_STYLE)
        self._account_name = account_name

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 16, 14, 10)
        root.setSpacing(6)

        # -- Shared checkbox --
        self.cb_shared = QCheckBox("Include in shared goal group")
        self.cb_shared.setChecked(is_shared)
        root.addWidget(self.cb_shared)

        # -- Individual goal row (visible when NOT shared) --
        self._indiv_row = QWidget()
        indiv_h = QHBoxLayout(self._indiv_row)
        indiv_h.setContentsMargins(0, 0, 0, 0)
        indiv_h.setSpacing(8)
        indiv_h.addWidget(QLabel("Individual Goal:"))
        self.goal_spin = _make_goal_spin(current_goal)
        indiv_h.addWidget(self.goal_spin)
        indiv_h.addStretch(1)
        root.addWidget(self._indiv_row)

        # -- Presets row (always visible) --
        presets_h = QHBoxLayout()
        presets_h.setContentsMargins(0, 0, 0, 0)
        presets_h.setSpacing(8)
        presets_h.addWidget(QLabel("Presets:"))
        p = preset_values if len(preset_values) == 3 else list(_DEFAULT_PRESETS)
        self.preset_spins: List[QDoubleSpinBox] = []
        for i, val in enumerate(p):
            lbl = QLabel(f"{'Min' if i == 0 else 'Mid' if i == 1 else 'Max'}:")
            spin = _make_preset_spin(val)
            self.preset_spins.append(spin)
            presets_h.addWidget(lbl)
            presets_h.addWidget(spin)
        presets_h.addStretch(1)
        root.addLayout(presets_h)

        self._sync_visibility()
        self.cb_shared.stateChanged.connect(self._on_toggle)

    def _on_toggle(self):
        self._sync_visibility()
        self.sharedToggled.emit()

    def _sync_visibility(self):
        self._indiv_row.setVisible(not self.cb_shared.isChecked())

    # ---- accessors ----

    @property
    def account_name(self) -> str:
        return self._account_name

    @property
    def is_shared(self) -> bool:
        return self.cb_shared.isChecked()

    @property
    def individual_goal(self) -> float:
        return float(self.goal_spin.value())

    @property
    def preset_values(self) -> List[float]:
        return [float(s.value()) for s in self.preset_spins]


class GoalDashboardOptionsDialog(QDialog):
    """Goal Dashboard Options dialog — account grouping, targets, and per-account presets.

    ┌───────────────────────────────────────────────────────────────────┐
    │  [info]                                                           │
    │                                                                   │
    │  Shared Goal:  [$ 500,000 ▲▼]                                    │
    │  (hidden / greyed when no accounts are checked)                   │
    │                                                                   │
    │  ┌ Josh ──────────────────────────────────────────────────────┐  │
    │  │  [x] Include in shared goal group                          │  │
    │  │  Presets:  Min [$ 250K]  Mid [$ 500K]  Max [$ 1M]         │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                                                                   │
    │  ┌ Narmeen ────────────────────────────────────────────────────┐  │
    │  │  [ ] Include in shared goal group                           │  │
    │  │  Individual Goal:  [$ 25,000]                              │  │
    │  │  Presets:  Min [$ 10K]  Mid [$ 25K]  Max [$ 50K]          │  │
    │  └────────────────────────────────────────────────────────────┘  │
    │                                                                   │
    │                               [Cancel]  [Save]                   │
    └───────────────────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        accounts: List[str],
        included_accounts: List[str],
        goal_targets: Dict[str, float],
        preset_values: Dict[str, List[float]],
        parent=None,
    ):
        super().__init__(parent)
        self._accounts = accounts
        self.setWindowTitle("Goal Dashboard Options")
        self.setMinimumWidth(560)
        self.resize(600, min(100 + 130 * len(accounts) + 80, 680))

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # -- Info --
        info = QLabel(
            "Check accounts to merge their trades toward a <b>shared goal</b>. "
            "Unchecked accounts each track their own goal independently. "
            "Each account's <b>presets</b> appear as quick-set buttons on their Goal Dashboard."
        )
        info.setWordWrap(True)
        root.addWidget(info)

        # -- Shared goal row (visible only when at least one account is checked) --
        self._shared_row = QWidget()
        shared_h = QHBoxLayout(self._shared_row)
        shared_h.setContentsMargins(0, 4, 0, 4)
        shared_h.setSpacing(8)
        shared_h.addWidget(QLabel("<b>Shared Group Goal:</b>"))
        default_shared = goal_targets.get(
            included_accounts[0] if included_accounts else (accounts[0] if accounts else ""),
            500_000.0,
        )
        self.shared_goal_spin = _make_goal_spin(default_shared)
        shared_h.addWidget(self.shared_goal_spin)
        shared_h.addStretch(1)
        root.addWidget(self._shared_row)

        # -- Account blocks in a scroll area --
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.StyledPanel)
        container = QWidget()
        blocks_vbox = QVBoxLayout(container)
        blocks_vbox.setContentsMargins(4, 4, 4, 4)
        blocks_vbox.setSpacing(8)

        included_set = set(included_accounts)
        self._blocks: List[_AccountGoalBlock] = []
        for account in accounts:
            block = _AccountGoalBlock(
                account_name=account,
                is_shared=account in included_set,
                current_goal=goal_targets.get(account, 500_000.0),
                preset_values=preset_values.get(account, list(_DEFAULT_PRESETS)),
                parent=container,
            )
            block.sharedToggled.connect(self._update_shared_row_visibility)
            blocks_vbox.addWidget(block)
            self._blocks.append(block)

        blocks_vbox.addStretch(1)
        scroll.setWidget(container)
        root.addWidget(scroll, 1)

        # -- Buttons --
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._update_shared_row_visibility()

    def _update_shared_row_visibility(self):
        has_shared = any(b.is_shared for b in self._blocks)
        self._shared_row.setVisible(has_shared)

    # ---- result accessors ----

    def selected_accounts(self) -> List[str]:
        return [b.account_name for b in self._blocks if b.is_shared]

    def shared_goal(self) -> float:
        return float(self.shared_goal_spin.value())

    def individual_goals(self) -> Dict[str, float]:
        return {b.account_name: b.individual_goal for b in self._blocks if not b.is_shared}

    def all_preset_values(self) -> Dict[str, List[float]]:
        return {b.account_name: b.preset_values for b in self._blocks}


# ---------------------------------------------------------------------------
# Trade entry / edit dialog
# ---------------------------------------------------------------------------

class TradeEditDialog(QDialog):
    def __init__(
        self,
        trade: Optional[Trade] = None,
        watchlist_symbols: Optional[List[str]] = None,
        default_quantity: int = 1,
        quantity_increment: int = 1,
        close_holdings_mode: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._editing = trade
        self._watchlist_symbols = [str(s).strip().upper() for s in (watchlist_symbols or []) if str(s).strip()]
        self._default_quantity = max(1, int(default_quantity or 1))
        self._quantity_increment = max(1, int(quantity_increment or 1))
        self._close_holdings_mode = bool(close_holdings_mode)

        self.setWindowTitle("Close Holdings" if self._close_holdings_mode else "Trade")
        self.resize(440, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(10)

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

        self.sell_price_spin = QDoubleSpinBox()
        self.sell_price_spin.setRange(0.0, 1_000_000_000.0)
        self.sell_price_spin.setDecimals(2)
        self.sell_price_spin.setPrefix("$ ")
        self.sell_price_spin.setSpecialValueText("")
        self.sell_price_spin.setValue(self.sell_price_spin.minimum())

        self.open_date_edit = QDateEdit()
        self.open_date_edit.setCalendarPopup(True)
        self.open_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.close_date_edit = QDateEdit()
        self.close_date_edit.setCalendarPopup(True)
        self.close_date_edit.setDisplayFormat("yyyy-MM-dd")

        self.status_combo = QComboBox()
        self.status_combo.addItems(["OPEN", "CLOSED"])

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        form.addRow("Instrument", self.instrument_edit)
        form.addRow("Share count", self.share_count_spin)
        form.addRow("Buy price", self.buy_price_spin)
        form.addRow("Status", self.status_combo)
        form.addRow("Sell price", self.sell_price_spin)
        form.addRow("Open date", self.open_date_edit)
        form.addRow("Close date", self.close_date_edit)
        form.addRow("Notes", self.notes_edit)
        root.addLayout(form)

        self.preview_label = QLabel("Trade Profit: —")
        root.addWidget(self.preview_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.btn_save = QPushButton("Close" if self._close_holdings_mode else "Save")
        buttons.addButton(self.btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_save.clicked.connect(self._accept_if_valid)
        root.addWidget(buttons)

        self.status_combo.currentTextChanged.connect(self._sync_status)
        self.share_count_spin.valueChanged.connect(self._update_preview)
        self.buy_price_spin.valueChanged.connect(self._update_preview)
        self.sell_price_spin.valueChanged.connect(self._update_preview)

        self._apply_trade(trade)
        self._apply_mode_constraints()
        self._sync_status(self.status_combo.currentText())
        self._update_preview()

    def _apply_trade(self, trade: Optional[Trade]):
        today = date.today()
        self.instrument_edit.setCurrentText(trade.normalized_instrument() if trade else "")
        self.share_count_spin.setValue(max(1, int(trade.share_count) if trade else self._default_quantity))
        self.buy_price_spin.setValue(float(trade.buy_price) if trade else self.buy_price_spin.minimum())
        self.sell_price_spin.setValue(
            float(trade.sell_price) if trade and trade.sell_price is not None else self.sell_price_spin.minimum()
        )
        if self._close_holdings_mode:
            self.status_combo.setCurrentText("CLOSED")
        else:
            self.status_combo.setCurrentText(trade.status if trade else "OPEN")
        open_date = trade.open_date if trade and trade.open_date else today
        close_date = trade.close_date if trade and trade.close_date else today
        self.open_date_edit.setDate(QDate(open_date.year, open_date.month, open_date.day))
        self.close_date_edit.setDate(QDate(close_date.year, close_date.month, close_date.day))
        self.notes_edit.setText(trade.notes if trade else "")

    def _apply_mode_constraints(self):
        if not self._close_holdings_mode:
            return
        self.status_combo.setCurrentText("CLOSED")
        self.status_combo.setEnabled(False)
        self.instrument_edit.setEnabled(False)
        self.share_count_spin.setEnabled(False)
        self.buy_price_spin.setEnabled(False)
        self.open_date_edit.setEnabled(False)
        self.notes_edit.setEnabled(False)

    def _sync_status(self, status: str):
        closed = status == "CLOSED"
        self.sell_price_spin.setEnabled(closed)
        self.close_date_edit.setEnabled(closed)
        self._update_preview()

    def _update_preview(self):
        if self.status_combo.currentText() != "CLOSED":
            self.preview_label.setText("Trade Profit: —")
            return
        qty = int(self.share_count_spin.value())
        profit = (float(self.sell_price_spin.value()) - float(self.buy_price_spin.value())) * qty
        self.preview_label.setText(f"Trade Profit: $ {profit:,.2f}")

    def _accept_if_valid(self):
        instrument = self.instrument_edit.currentText().strip().upper()
        if not instrument:
            QMessageBox.warning(self, "Missing instrument", "Enter an instrument symbol.")
            return
        if self.status_combo.currentText() == "CLOSED":
            if self.close_date_edit.date().toPython() < self.open_date_edit.date().toPython():
                QMessageBox.warning(self, "Invalid dates", "Close date cannot be before open date.")
                return
        self.accept()

    def to_trade(self) -> Trade:
        closed = self.status_combo.currentText() == "CLOSED"
        return Trade(
            instrument=self.instrument_edit.currentText().strip().upper(),
            share_count=int(self.share_count_spin.value()),
            buy_price=float(self.buy_price_spin.value()),
            sell_price=(float(self.sell_price_spin.value()) if closed else None),
            open_date=self.open_date_edit.date().toPython(),
            close_date=(self.close_date_edit.date().toPython() if closed else None),
            notes=self.notes_edit.text().strip(),
        )


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
        cgg.addWidget(QLabel("Instrument"), 0, 0); cgg.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        cgg.addWidget(QLabel("Qty"), 1, 0); cgg.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        cgg.addWidget(QLabel("Avg Cost"), 2, 0); cgg.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
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
            self.resulting_qty.setText("—"); self.resulting_avg.setText("—"); self.order_cost.setText("—")
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
    def __init__(self, holding: Holding, current_mark: Optional[float] = None, quantity_increment: int = 1, parent=None):
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
        cgg.addWidget(QLabel("Instrument"), 0, 0); cgg.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        cgg.addWidget(QLabel("Qty"), 1, 0); cgg.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        cgg.addWidget(QLabel("Avg Cost"), 2, 0); cgg.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
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


# ---------------------------------------------------------------------------
# Trade History Columns dialog
# ---------------------------------------------------------------------------

class TradeHistoryColumnsDialog(QDialog):
    def __init__(self, columns: List[tuple], visible_keys: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trade History Columns")
        self.resize(320, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self._checks: Dict[str, QCheckBox] = {}
        for key, label in columns:
            cb = QCheckBox(label)
            cb.setChecked(key in visible_keys)
            self._checks[key] = cb
            root.addWidget(cb)

        root.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_keys(self) -> List[str]:
        return [key for key, cb in self._checks.items() if cb.isChecked()]



# ---------------------------------------------------------------------------
# PortfolioTab
# ---------------------------------------------------------------------------

class PortfolioTab(QWidget):
    """Portfolio tab bound to a single named account.

    Parameters
    ----------
    account_name : the account this tab represents
    store        : DataStore (RemoteDataStore or LocalDataStore)
    settings     : QSettings for device-local UI prefs only
    read_only    : if True, hides all trade/goal edit controls
                   (used by admin when viewing another user's portfolio)
    owner_label  : optional string shown in goal group to identify owner
    """

    tradesChanged = Signal()

    TRADE_HISTORY_VISIBLE_COLUMNS_KEY = "portfolio/trade_history_visible_columns"

    TRADE_HISTORY_COLUMNS = [
        ("instrument", "Instrument"),
        ("share_count", "Share count"),
        ("status", "Status"),
        ("buy_price", "Buy Price"),
        ("sell_price", "Sell Price"),
        ("trade_profit", "Trade Profit"),
        ("open_date", "Open Date"),
        ("close_date", "Close Date"),
        ("days_to_close", "Days to Close"),
        ("avg_daily_return", "Avg Daily Return"),
    ]

    def __init__(
        self,
        account_name: str,
        store,           # DataStore
        settings,        # QSettings (UI prefs only)
        read_only: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._account_name: str = account_name
        self._store = store
        self._settings = settings
        self._read_only = read_only
        self._marks: Dict[str, Optional[float]] = {}
        self._trades: List[Trade] = []   # all trades for all accounts (filtered per view)
        self._holdings: List[Holding] = []
        self._trade_row_indices: List[int] = []
        self._holding_row_instruments: List[str] = []
        self._build_ui()
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def holdings_symbols(self) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for h in self._holdings:
            s = h.normalized_instrument()
            if s and s not in seen:
                seen.add(s); out.append(s)
        return out

    def update_marks(self, data: Dict[str, Dict]):
        for symbol, row in data.items():
            price = row.get("price")
            if price is not None:
                self._marks[symbol] = float(price)
        self.refresh_view()

    def reload_from_store(self):
        """Re-read all data from the store and refresh. Called when siblings change."""
        self._load_state()

    # Keep old name as alias for backward compat with MainWindow signal wiring
    reload_from_settings = reload_from_store

    # ------------------------------------------------------------------
    # UI helpers (device-local settings)
    # ------------------------------------------------------------------

    def _trade_default_quantity(self) -> int:
        try:
            return max(1, int(self._settings.value("trade_defaults/default_quantity", 1) or 1))
        except Exception:
            return 1

    def _trade_quantity_increment(self) -> int:
        try:
            return max(1, int(self._settings.value("trade_defaults/quantity_increment", 1) or 1))
        except Exception:
            return 1

    def _default_trade_history_visible_keys(self) -> List[str]:
        return [key for key, _ in self.TRADE_HISTORY_COLUMNS]

    def _trade_history_visible_keys(self) -> List[str]:
        raw = self._settings.value(self.TRADE_HISTORY_VISIBLE_COLUMNS_KEY, [])
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except Exception: raw = []
        if not isinstance(raw, list): raw = []
        valid = {key for key, _ in self.TRADE_HISTORY_COLUMNS}
        visible = [str(key) for key in raw if str(key) in valid]
        return visible or self._default_trade_history_visible_keys()

    def _save_trade_history_visible_keys(self, keys: List[str]):
        valid = {key for key, _ in self.TRADE_HISTORY_COLUMNS}
        cleaned = [key for key in keys if key in valid] or self._default_trade_history_visible_keys()
        self._settings.setValue(self.TRADE_HISTORY_VISIBLE_COLUMNS_KEY, json.dumps(cleaned))
        self._settings.sync()

    # ------------------------------------------------------------------
    # Store-backed data helpers
    # ------------------------------------------------------------------

    def _account_names(self) -> List[str]:
        try:
            return self._store.get_account_names()
        except Exception:
            return [self._account_name]

    def _visible_trades(self) -> List[Trade]:
        return [t for t in self._trades if (t.account or "").strip() == self._account_name]

    def _goal_trades(self) -> List[Trade]:
        goal_accounts = set(self._goal_dashboard_accounts())
        if self._account_name in goal_accounts:
            return [t for t in self._trades if (t.account or "").strip() in goal_accounts]
        return [t for t in self._trades if (t.account or "").strip() == self._account_name]

    def _my_presets(self) -> List[float]:
        try:
            return self._store.get_goal_presets(self._account_name)
        except Exception:
            return [250_000.0, 500_000.0, 1_000_000.0]

    # ------------------------------------------------------------------
    # Goal Group (via store)
    # ------------------------------------------------------------------

    def _goal_dashboard_accounts(self) -> List[str]:
        try:
            accounts = set(self._account_names())
            shared, _ = self._store.get_goal_group()
            return [name for name in shared if name in accounts]
        except Exception:
            return []

    def sync_goal_dashboard_accounts(self):
        """Prune removed accounts from the goal group (server call)."""
        try:
            accounts = set(self._account_names())
            shared, shared_goal = self._store.get_goal_group()
            pruned = [name for name in shared if name in accounts]
            if pruned != shared:
                self._store.set_goal_group(pruned, shared_goal, {}, {})
        except Exception:
            pass

    def _current_goal_target(self) -> float:
        try:
            return self._store.get_goal_target(self._account_name)
        except Exception:
            return 500_000.0

    def open_goal_dashboard_options_dialog(self):
        if self._read_only:
            return
        accounts = self._account_names()
        try:
            shared_names, shared_goal = self._store.get_goal_group()
        except Exception:
            shared_names, shared_goal = [], 500_000.0

        goal_targets: Dict[str, float] = {}
        preset_values: Dict[str, List[float]] = {}
        for account in accounts:
            try:
                goal_targets[account] = self._store.get_goal_target(account)
                preset_values[account] = self._store.get_goal_presets(account)
            except Exception:
                goal_targets[account] = 500_000.0
                preset_values[account] = [250_000.0, 500_000.0, 1_000_000.0]

        dlg = GoalDashboardOptionsDialog(accounts, shared_names, goal_targets, preset_values, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        chosen = dlg.selected_accounts()
        shared_goal_new = dlg.shared_goal()
        individual_goals = dlg.individual_goals()
        all_presets = dlg.all_preset_values()

        try:
            self._store.set_goal_group(chosen, shared_goal_new, individual_goals, all_presets)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Save Failed", str(exc))
            return

        # Rebuild preset buttons immediately on this tab (siblings rebuild
        # via reload_from_store -> _load_state -> _rebuild_preset_buttons).
        self._rebuild_preset_buttons()
        self.tradesChanged.emit()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Read-only banner
        if self._read_only:
            banner = QLabel(f"  👁  Viewing read-only — {self._account_name}")
            banner.setStyleSheet(
                "background: #f59e0b; color: #1c1917; padding: 4px 10px; "
                "border-radius: 4px; font-weight: bold;"
            )
            root.addWidget(banner)

        top_row = QHBoxLayout()

        # ---- Goal Dashboard ----
        self.goal_group = QGroupBox("Goal Dashboard")
        self.goal_group.setStyleSheet(GROUP_STYLE)
        goal_layout = QVBoxLayout(self.goal_group)
        goal_layout.setContentsMargins(14, 18, 14, 14)
        goal_layout.setSpacing(10)

        goal_header = QHBoxLayout()
        goal_header.setSpacing(8)
        goal_header.addWidget(QLabel("Annual Target:"))
        self.goal_target_label = QLabel("—")
        font = self.goal_target_label.font()
        font.setBold(True)
        self.goal_target_label.setFont(font)
        goal_header.addWidget(self.goal_target_label)
        goal_header.addSpacing(6)

        self._preset_btn_container = QWidget()
        self._preset_btn_layout = QHBoxLayout(self._preset_btn_container)
        self._preset_btn_layout.setContentsMargins(0, 0, 0, 0)
        self._preset_btn_layout.setSpacing(4)
        goal_header.addWidget(self._preset_btn_container)
        goal_header.addStretch(1)
        goal_layout.addLayout(goal_header)

        goal_grid = QGridLayout()
        goal_grid.setHorizontalSpacing(18)
        goal_grid.setVerticalSpacing(8)
        self.goal_labels: Dict[str, QLabel] = {}
        goal_fields = [
            ("realized_profit", "Realized Profit"),
            ("unrealized_profit", "Unrealized Profit"),
            ("remaining_profit", "Profit to Goal"),
            ("monthly_profit_to_goal", "Monthly Needed"),
            ("weekly_profit_to_goal", "Weekly Needed"),
            ("daily_profit_to_goal", "Daily Needed"),
            ("avg_daily_profit", "Avg Daily"),
            ("profit_to_match_daily_avg", "Catch-up Today"),
            ("business_days_elapsed", "Trading Days Elapsed"),
            ("business_days_remaining", "Trading Days Remaining"),
        ]
        for idx, (key, label) in enumerate(goal_fields):
            value = QLabel("—")
            self.goal_labels[key] = value
            row, col = idx // 2, (idx % 2) * 2
            goal_grid.addWidget(QLabel(label), row, col)
            goal_grid.addWidget(value, row, col + 1)
        goal_layout.addLayout(goal_grid)
        top_row.addWidget(self.goal_group, 1)

        # ---- Analytics ----
        self.analytics_group = QGroupBox("Performance Analytics")
        self.analytics_group.setStyleSheet(GROUP_STYLE)
        analytics_grid = QGridLayout(self.analytics_group)
        analytics_grid.setContentsMargins(14, 18, 14, 14)
        analytics_grid.setHorizontalSpacing(18)
        analytics_grid.setVerticalSpacing(8)
        self.analytics_labels: Dict[str, QLabel] = {}
        for idx, (key, label) in enumerate([
            ("open_trades", "Open Trades"), ("closed_trades", "Closed Trades"),
            ("avg_profit_per_trade", "Avg Profit / Trade"), ("avg_trade_value", "Avg Trade Value"),
            ("avg_roi_pct", "Avg ROI %"),
            ("avg_daily_closed_profit", "Avg Daily Return"),
        ]):
            value = QLabel("—")
            self.analytics_labels[key] = value
            analytics_grid.addWidget(QLabel(label), idx, 0)
            analytics_grid.addWidget(value, idx, 1)
        top_row.addWidget(self.analytics_group, 1)
        root.addLayout(top_row)

        # ---- Holdings ----
        self.holdings_group = QGroupBox("Open Holdings")
        self.holdings_group.setStyleSheet(GROUP_STYLE)
        holdings_layout = QVBoxLayout(self.holdings_group)
        holdings_layout.setContentsMargins(14, 18, 14, 14)
        holdings_layout.setSpacing(10)
        self.holdings_table = QTableWidget(0, 7)
        self.holdings_table.setHorizontalHeaderLabels([
            "Instrument", "Qty", "Avg Cost", "Mark", "Unrealized P/L", "Market Value", "Weight %",
        ])
        self.holdings_table.verticalHeader().setVisible(False)
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.holdings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.holdings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.holdings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        if not self._read_only:
            self.holdings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.holdings_table.customContextMenuRequested.connect(self._open_holdings_context_menu)
        holdings_layout.addWidget(self.holdings_table)
        self.holdings_summary = QLabel("—")
        holdings_layout.addWidget(self.holdings_summary)
        root.addWidget(self.holdings_group)

        # ---- Trade History ----
        self.trade_group = QGroupBox("Trade History")
        self.trade_group.setStyleSheet(GROUP_STYLE)
        trade_layout = QVBoxLayout(self.trade_group)
        trade_layout.setContentsMargins(14, 18, 14, 14)
        trade_layout.setSpacing(10)
        self.trade_table = QTableWidget(0, len(self.TRADE_HISTORY_COLUMNS))
        self.trade_table.setHorizontalHeaderLabels([label for _, label in self.TRADE_HISTORY_COLUMNS])
        self.trade_table.verticalHeader().setVisible(False)
        self.trade_table.setAlternatingRowColors(True)
        self.trade_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trade_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.trade_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trade_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        trade_layout.addWidget(self.trade_table)

        if not self._read_only:
            trade_btns = QHBoxLayout()
            self.btn_add_trade = QPushButton("+ Add Trade")
            self.btn_edit_trade = QPushButton("Edit Selected")
            self.btn_delete_trade = QPushButton("Delete Selected")
            trade_btns.addWidget(self.btn_add_trade)
            trade_btns.addWidget(self.btn_edit_trade)
            trade_btns.addWidget(self.btn_delete_trade)
            trade_btns.addStretch(1)
            trade_layout.addLayout(trade_btns)
            self.btn_add_trade.clicked.connect(self._add_trade)
            self.btn_edit_trade.clicked.connect(self._edit_trade)
            self.btn_delete_trade.clicked.connect(self._delete_trade)

        root.addWidget(self.trade_group, 1)

    # ------------------------------------------------------------------
    # Preset buttons (hidden in read-only)
    # ------------------------------------------------------------------

    def _rebuild_preset_buttons(self):
        while self._preset_btn_layout.count():
            item = self._preset_btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if self._read_only:
            return

        presets = self._my_presets()
        for preset_value in presets:
            label = _fmt_preset_label(preset_value)
            btn = QPushButton(label)
            btn.setStyleSheet("padding-left: 8px; padding-right: 8px;")
            btn.setMinimumWidth(btn.fontMetrics().horizontalAdvance(label) + 24)
            btn.clicked.connect(lambda _checked, v=preset_value: self._set_goal_target(v))
            self._preset_btn_layout.addWidget(btn)

    def _set_goal_target(self, value: float):
        if self._read_only:
            return
        goal_accounts = set(self._goal_dashboard_accounts())
        try:
            if self._account_name in goal_accounts:
                # Shared — update all accounts in the group
                for account in goal_accounts:
                    self._store.set_goal_target(account, float(value))
                self.tradesChanged.emit()
            else:
                self._store.set_goal_target(self._account_name, float(value))
                self.refresh_view()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Save Failed", str(exc))

    # ------------------------------------------------------------------
    # State persistence (via DataStore)
    # ------------------------------------------------------------------

    def _load_state(self):
        try:
            all_trades = self._store.get_all_trades()
        except Exception:
            all_trades = []

        # Assign account field to any trade missing it (migration from pre-DB data)
        default_account = self._account_names()[0] if self._account_names() else self._account_name
        migrated = False
        for trade in all_trades:
            if not (trade.account or "").strip():
                trade.account = default_account
                migrated = True
        if migrated and not self._read_only:
            self._save_trades_silent()

        self._trades = all_trades
        self._holdings = compute_holdings_from_trades(self._visible_trades())
        self.sync_goal_dashboard_accounts()
        self._rebuild_preset_buttons()
        self.refresh_view()

    def _save_trades_silent(self):
        """Persist current account's trades without emitting tradesChanged."""
        visible = self._visible_trades()
        try:
            self._store.save_account_trades(self._account_name, visible)
        except Exception:
            pass

    def _save_trades(self):
        """Persist and notify siblings."""
        if self._read_only:
            return
        visible = self._visible_trades()
        try:
            self._store.save_account_trades(self._account_name, visible)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Save Failed", str(exc))
            return
        self.tradesChanged.emit()

    # ------------------------------------------------------------------
    # Watchlist / selection helpers
    # ------------------------------------------------------------------

    def _watchlist_symbols(self) -> List[str]:
        parent = self.window()
        watch = getattr(parent, "watch", None)
        out: List[str] = []
        if watch is None: return out
        seen: set = set()
        for r in range(watch.rowCount()):
            item = watch.item(r, 0)
            if item is None: continue
            symbol = item.text().strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol); out.append(symbol)
        return out

    def _selected_trade_source_index(self) -> Optional[int]:
        view_row = self.trade_table.currentRow()
        if view_row < 0 or view_row >= len(self._trade_row_indices): return None
        source_index = self._trade_row_indices[view_row]
        if source_index < 0 or source_index >= len(self._trades): return None
        return source_index

    def _selected_holding_instrument(self) -> Optional[str]:
        view_row = self.holdings_table.currentRow()
        if view_row < 0 or view_row >= len(self._holding_row_instruments): return None
        return self._holding_row_instruments[view_row]

    def open_trade_history_view_settings(self):
        dlg = TradeHistoryColumnsDialog(
            self.TRADE_HISTORY_COLUMNS, self._trade_history_visible_keys(), parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        self._save_trade_history_visible_keys(dlg.selected_keys())
        self.refresh_view(selected_trade_source_index=self._selected_trade_source_index())

    # ------------------------------------------------------------------
    # Trade CRUD
    # ------------------------------------------------------------------

    def _open_trades_for_instrument(self, instrument: str) -> List[tuple]:
        symbol = (instrument or "").strip().upper()
        return [
            (idx, trade) for idx, trade in enumerate(self._trades)
            if (trade.account or "").strip() == self._account_name
            and not trade.is_closed
            and trade.normalized_instrument() == symbol
        ]

    def _combined_open_trade(self, instrument: str) -> Optional[Trade]:
        matching = self._open_trades_for_instrument(instrument)
        if not matching: return None
        trades = [t for _, t in matching]
        total_qty = sum(int(t.share_count) for t in trades)
        total_cost = sum(float(t.buy_price) * int(t.share_count) for t in trades)
        oldest = min((t.open_date for t in trades if t.open_date), default=date.today())
        notes = " | ".join(t.notes for t in trades if t.notes)
        avg_cost = (total_cost / total_qty) if total_qty > 0 else 0.0
        return Trade(instrument=instrument, share_count=total_qty, buy_price=avg_cost,
                     sell_price=None, open_date=oldest, close_date=None, notes=notes)

    def _add_trade(self):
        if self._read_only: return
        dlg = TradeEditDialog(
            watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        trade = dlg.to_trade()
        trade.account = self._account_name
        self._trades.append(trade)
        new_index = len(self._trades) - 1
        self._save_trades()
        self.refresh_view(selected_trade_source_index=new_index)

    def _edit_trade(self):
        if self._read_only: return
        source_index = self._selected_trade_source_index()
        if source_index is None:
            QMessageBox.information(self, "Select trade", "Choose a trade row to edit."); return
        dlg = TradeEditDialog(
            self._trades[source_index],
            watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        updated = dlg.to_trade()
        updated.account = (self._trades[source_index].account or self._account_name).strip() or self._account_name
        self._trades[source_index] = updated
        self._save_trades()
        self.refresh_view(selected_trade_source_index=source_index)

    def _delete_trade(self):
        if self._read_only: return
        source_index = self._selected_trade_source_index()
        if source_index is None:
            QMessageBox.information(self, "Select trade", "Choose a trade row to delete."); return
        trade = self._trades[source_index]
        if QMessageBox.question(
            self, "Delete trade",
            f"Delete {trade.normalized_instrument()} trade for {trade.share_count:,d} shares?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._trades.pop(source_index)
        self._save_trades()
        self.refresh_view()

    # ------------------------------------------------------------------
    # Holdings context menu
    # ------------------------------------------------------------------

    def _open_holdings_context_menu(self, pos: QPoint):
        if self._read_only: return
        row = self.holdings_table.rowAt(pos.y())
        if row < 0: return
        self.holdings_table.selectRow(row)
        instrument = self._selected_holding_instrument()
        if not instrument: return
        menu = QMenu(self)
        act_close = menu.addAction("Close Holdings")
        act_mark_down = menu.addAction("Mark Down")
        act_double_down = menu.addAction("Double Down")
        chosen = menu.exec(self.holdings_table.viewport().mapToGlobal(pos))
        if chosen == act_close: self._close_selected_holding()
        elif chosen == act_mark_down: self._mark_down_selected_holding()
        elif chosen == act_double_down: self._double_down_selected_holding()

    def _close_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument: return
        combined_trade = self._combined_open_trade(instrument)
        matching = self._open_trades_for_instrument(instrument)
        if not combined_trade or not matching: return
        dlg = TradeEditDialog(
            trade=combined_trade, watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            close_holdings_mode=True, parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        closing_trade = dlg.to_trade()
        if closing_trade.sell_price is None or closing_trade.close_date is None: return
        updated_indices: List[int] = []
        for idx, trade in matching:
            trade.sell_price = float(closing_trade.sell_price)
            trade.close_date = closing_trade.close_date
            updated_indices.append(idx)
        self._save_trades()
        self.refresh_view(selected_trade_source_index=updated_indices[-1] if updated_indices else None)

    def _mark_down_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument: return
        combined = self._combined_open_trade(instrument)
        if not combined or combined.share_count <= 0: return
        holding = Holding(instrument=combined.normalized_instrument(), qty=int(combined.share_count),
                          avg_cost=float(combined.buy_price), notes=combined.notes or "")
        dlg = MarkDownDialog(holding=holding, default_quantity=self._trade_default_quantity(),
                              quantity_increment=self._trade_quantity_increment(), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        trade = dlg.to_trade(); trade.account = self._account_name
        self._trades.append(trade)
        self._save_trades()
        self.refresh_view(selected_trade_source_index=len(self._trades) - 1)

    def _double_down_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument: return
        combined = self._combined_open_trade(instrument)
        if not combined or combined.share_count <= 0: return
        holding = Holding(instrument=combined.normalized_instrument(), qty=int(combined.share_count),
                          avg_cost=float(combined.buy_price), notes=combined.notes or "")
        dlg = DoubleDownDialog(holding=holding, current_mark=self._marks.get(holding.normalized_instrument()),
                               quantity_increment=self._trade_quantity_increment(), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted: return
        trade = dlg.to_trade(); trade.account = self._account_name
        self._trades.append(trade)
        self._save_trades()
        self.refresh_view(selected_trade_source_index=len(self._trades) - 1)

    # ------------------------------------------------------------------
    # Core view refresh
    # ------------------------------------------------------------------

    def refresh_view(self, selected_trade_source_index: Optional[int] = None):
        if selected_trade_source_index is None:
            selected_trade_source_index = self._selected_trade_source_index()

        visible_trades = self._visible_trades()
        self._holdings = compute_holdings_from_trades(visible_trades)
        realized_by_symbol = compute_realized_pl_by_symbol(visible_trades)
        holding_rows, summary = compute_portfolio(self._holdings, self._marks, realized_by_symbol)
        analytics = compute_trade_analytics(visible_trades)

        goal_trades = self._goal_trades()
        goal_holdings = compute_holdings_from_trades(goal_trades)
        goal_realized_by_symbol = compute_realized_pl_by_symbol(goal_trades)
        _, goal_summary = compute_portfolio(goal_holdings, self._marks, goal_realized_by_symbol)
        goal = compute_goal_progress(
            goal_trades, self._current_goal_target(), unrealized_profit=goal_summary.unrealized_pl,
        )

        visible_source_indices = [
            idx for idx, trade in enumerate(self._trades)
            if (trade.account or "").strip() == self._account_name
        ]
        trade_rows = compute_trade_rows(visible_trades)

        self._render_goal(goal)
        self._render_analytics(analytics)
        self._render_trade_table(trade_rows, visible_source_indices, selected_trade_source_index)
        self._render_holdings_table(holding_rows)
        self.holdings_summary.setText(
            f"Market Value: {_fmt_money(summary.market_value)}    "
            f"Cost Basis: {_fmt_money(summary.cost_basis)}    "
            f"Unrealized P/L: {_fmt_money(summary.unrealized_pl)}    "
            f"Total P/L: {_fmt_money(summary.total_pl)}"
        )

    # ------------------------------------------------------------------
    # Render helpers
    # ------------------------------------------------------------------

    def _render_goal(self, goal):
        self.goal_target_label.setText(_fmt_goal(goal.goal_target))
        self.goal_labels["realized_profit"].setText(_fmt_money(goal.realized_profit))
        self.goal_labels["unrealized_profit"].setText(_fmt_money(goal.unrealized_profit))
        self.goal_labels["remaining_profit"].setText(_fmt_money(goal.remaining_profit))
        self.goal_labels["monthly_profit_to_goal"].setText(self._money_or_dash(goal.monthly_profit_to_goal))
        self.goal_labels["weekly_profit_to_goal"].setText(self._money_or_dash(goal.weekly_profit_to_goal))
        self.goal_labels["daily_profit_to_goal"].setText(self._money_or_dash(goal.daily_profit_to_goal))
        self.goal_labels["avg_daily_profit"].setText(self._money_or_dash(goal.avg_daily_profit))
        self.goal_labels["profit_to_match_daily_avg"].setText(self._money_or_dash(goal.profit_to_match_daily_avg))
        self.goal_labels["business_days_elapsed"].setText(f"{goal.business_days_elapsed:,d}")
        self.goal_labels["business_days_remaining"].setText(f"{goal.business_days_remaining:,d}")

    def _render_analytics(self, analytics):
        self.analytics_labels["open_trades"].setText(f"{analytics.open_trades:,d}")
        self.analytics_labels["closed_trades"].setText(f"{analytics.closed_trades:,d}")
        self.analytics_labels["avg_profit_per_trade"].setText(self._money_or_dash(analytics.avg_profit_per_trade))
        self.analytics_labels["avg_trade_value"].setText(self._money_or_dash(analytics.avg_trade_value))
        self.analytics_labels["avg_roi_pct"].setText(self._pct(analytics.avg_roi_pct))
        self.analytics_labels["avg_daily_closed_profit"].setText(self._money_or_dash(analytics.avg_daily_closed_profit))

    def _render_trade_table(self, rows, visible_source_indices, selected_trade_source_index):
        self.trade_table.setColumnCount(len(self.TRADE_HISTORY_COLUMNS))
        self.trade_table.setHorizontalHeaderLabels([label for _, label in self.TRADE_HISTORY_COLUMNS])
        self.trade_table.setRowCount(len(rows))
        self._trade_row_indices = [
            visible_source_indices[row.index]
            for row in rows if 0 <= row.index < len(visible_source_indices)
        ]
        visible_keys = set(self._trade_history_visible_keys())
        for col, (key, _) in enumerate(self.TRADE_HISTORY_COLUMNS):
            self.trade_table.setColumnHidden(col, key not in visible_keys)
        for r, row in enumerate(rows):
            value_map = {
                "instrument": row.instrument, "share_count": f"{row.share_count:,d}",
                "status": row.status, "buy_price": _fmt_money(row.buy_price),
                "sell_price": self._money_or_dash(row.sell_price),
                "trade_profit": self._money_or_dash(row.trade_profit),
                "open_date": self._date_or_dash(row.open_date),
                "close_date": self._date_or_dash(row.close_date),
                "days_to_close": self._int_or_dash(row.days_to_close),
                "avg_daily_return": self._money_or_dash(row.avg_daily_return),
            }
            for c, (key, _) in enumerate(self.TRADE_HISTORY_COLUMNS):
                item = QTableWidgetItem(value_map[key])
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if key == "instrument":
                    f = item.font(); f.setBold(True); item.setFont(f)
                if key == "trade_profit" and row.trade_profit is not None:
                    item.setForeground(Qt.GlobalColor.darkGreen if row.trade_profit > 0 else Qt.GlobalColor.red)
                self.trade_table.setItem(r, c, item)
        if rows:
            row_to_select = 0
            if selected_trade_source_index is not None:
                try: row_to_select = self._trade_row_indices.index(selected_trade_source_index)
                except ValueError: row_to_select = 0
            self.trade_table.selectRow(row_to_select)

    def _render_holdings_table(self, rows):
        self.holdings_table.setRowCount(len(rows))
        self._holding_row_instruments = [row.instrument for row in rows]
        for r, row in enumerate(rows):
            values = [
                row.instrument, f"{row.qty:,d}", _fmt_money(row.avg_cost),
                self._money_or_dash(row.mark), _fmt_money(row.unrealized_pl),
                _fmt_money(row.market_value), self._pct(row.weight_pct),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    f = item.font(); f.setBold(True); item.setFont(f)
                self.holdings_table.setItem(r, c, item)

    @staticmethod
    def _money_or_dash(value: Optional[float]) -> str:
        return "—" if value is None else _fmt_money(value)

    @staticmethod
    def _pct(value: Optional[float]) -> str:
        return "—" if value is None else f"{float(value):,.2f}%"

    @staticmethod
    def _date_or_dash(value) -> str:
        return "—" if value is None else value.isoformat()

    @staticmethod
    def _int_or_dash(value: Optional[int]) -> str:
        return "—" if value is None else f"{int(value):,d}"
