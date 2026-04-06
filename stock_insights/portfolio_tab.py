from __future__ import annotations

import json

from datetime import date
from typing import Dict, List, Optional

from PySide6.QtCore import QDate, QPoint, QSettings, Qt
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
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
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


class TradeEditDialog(QDialog):
    """Trade entry dialog matching the uploaded Excel tracker structure."""

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
            close_date = self.close_date_edit.date().toPython()
            open_date = self.open_date_edit.date().toPython()
            if close_date < open_date:
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




class MarkDownDialog(QDialog):
    def __init__(
        self,
        holding: Holding,
        default_quantity: int = 1,
        quantity_increment: int = 1,
        parent=None,
    ):
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

        current_group = QGroupBox("Current Holding")
        current_group.setStyleSheet(GROUP_STYLE)
        current_grid = QGridLayout(current_group)
        current_grid.setContentsMargins(14, 14, 14, 14)
        current_grid.setHorizontalSpacing(18)
        current_grid.setVerticalSpacing(8)
        current_grid.addWidget(QLabel("Instrument"), 0, 0)
        current_grid.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        current_grid.addWidget(QLabel("Qty"), 1, 0)
        current_grid.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        current_grid.addWidget(QLabel("Avg Cost"), 2, 0)
        current_grid.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
        root.addWidget(current_group)

        order_group = QGroupBox("Mark Down Order")
        order_group.setStyleSheet(GROUP_STYLE)
        form = QFormLayout(order_group)
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
        root.addWidget(order_group)

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
            self.resulting_qty.setText("—")
            self.resulting_avg.setText("—")
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


class DoubleDownDialog(QDialog):
    def __init__(
        self,
        holding: Holding,
        current_mark: Optional[float] = None,
        quantity_increment: int = 1,
        parent=None,
    ):
        super().__init__(parent)
        self._holding = holding
        self._current_mark = current_mark
        self._quantity_increment = max(1, int(quantity_increment or 1))

        self.setWindowTitle("Double Down")
        self.resize(460, 340)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        current_group = QGroupBox("Current Holding")
        current_group.setStyleSheet(GROUP_STYLE)
        current_grid = QGridLayout(current_group)
        current_grid.setContentsMargins(14, 14, 14, 14)
        current_grid.setHorizontalSpacing(18)
        current_grid.setVerticalSpacing(8)
        current_grid.addWidget(QLabel("Instrument"), 0, 0)
        current_grid.addWidget(QLabel(holding.normalized_instrument()), 0, 1)
        current_grid.addWidget(QLabel("Qty"), 1, 0)
        current_grid.addWidget(QLabel(f"{holding.qty:,d}"), 1, 1)
        current_grid.addWidget(QLabel("Avg Cost"), 2, 0)
        current_grid.addWidget(QLabel(f"$ {holding.avg_cost:,.2f}"), 2, 1)
        current_grid.addWidget(QLabel("Current Mark"), 3, 0)
        current_grid.addWidget(QLabel("—" if current_mark is None else f"$ {float(current_mark):,.2f}"), 3, 1)
        root.addWidget(current_group)

        order_group = QGroupBox("Double Down Order")
        order_group.setStyleSheet(GROUP_STYLE)
        form = QFormLayout(order_group)
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
        default_buy_price = float(current_mark) if current_mark is not None else float(holding.avg_cost)
        self.buy_price_spin.setValue(max(0.01, round(default_buy_price, 2)))

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
        root.addWidget(order_group)

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


class TradeHistoryColumnsDialog(QDialog):
    def __init__(self, columns: List[tuple[str, str]], visible_keys: List[str], parent=None):
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_keys(self) -> List[str]:
        return [key for key, cb in self._checks.items() if cb.isChecked()]


class GoalDashboardAccountsDialog(QDialog):
    def __init__(self, accounts: List[str], included_accounts: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Goal Dashboard Accounts")
        self.resize(340, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        info = QLabel("Select which accounts are included for annual goal tracking.")
        info.setWordWrap(True)
        root.addWidget(info)

        self._checks: Dict[str, QCheckBox] = {}
        included = set(included_accounts)
        for account in accounts:
            cb = QCheckBox(account)
            cb.setChecked(account in included)
            self._checks[account] = cb
            root.addWidget(cb)

        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def selected_accounts(self) -> List[str]:
        return [account for account, cb in self._checks.items() if cb.isChecked()]


class PortfolioTab(QWidget):
    SETTINGS_KEY = "portfolio/trades"
    LEGACY_HOLDINGS_KEY = "portfolio/holdings"
    GOAL_KEY = "portfolio/goal_target"
    TRADE_HISTORY_VISIBLE_COLUMNS_KEY = "portfolio/trade_history_visible_columns"
    GOAL_DASHBOARD_ACCOUNTS_KEY = "portfolio/goal_dashboard_accounts"
    ACTIVE_ACCOUNT_KEY = "user_account/active_account"

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

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._marks: Dict[str, Optional[float]] = {}
        self._trades: List[Trade] = []
        self._holdings: List[Holding] = []
        self._trade_row_indices: List[int] = []
        self._holding_row_instruments: List[str] = []
        self._build_ui()
        self._load_state()
        self.refresh_view()

    def holdings_symbols(self) -> List[str]:
        seen = set()
        out: List[str] = []
        for holding in self._holdings:
            symbol = holding.normalized_instrument()
            if symbol and symbol not in seen:
                seen.add(symbol)
                out.append(symbol)
        return out

    def update_marks(self, data: Dict[str, Dict[str, Optional[float]]]):
        for symbol in self.holdings_symbols():
            row = data.get(symbol, {})
            price = row.get("price")
            if price is not None:
                self._marks[symbol] = float(price)
        self.refresh_view()

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
            try:
                import json
                raw = json.loads(raw)
            except Exception:
                raw = []
        if not isinstance(raw, list):
            raw = []
        valid = {key for key, _ in self.TRADE_HISTORY_COLUMNS}
        visible = [str(key) for key in raw if str(key) in valid]
        return visible or self._default_trade_history_visible_keys()

    def _save_trade_history_visible_keys(self, keys: List[str]):
        valid = {key for key, _ in self.TRADE_HISTORY_COLUMNS}
        cleaned = [key for key in keys if key in valid]
        if not cleaned:
            cleaned = self._default_trade_history_visible_keys()
        self._settings.setValue(self.TRADE_HISTORY_VISIBLE_COLUMNS_KEY, json.dumps(cleaned))
        self._settings.sync()


    def _account_names(self) -> List[str]:
        raw = self._settings.value("user_account/accounts", ["Default"])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list):
            raw = ["Default"]
        out: List[str] = []
        seen = set()
        for item in raw:
            name = str(item or "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out or ["Default"]

    def _active_account(self) -> str:
        accounts = self._account_names()
        saved = str(self._settings.value(self.ACTIVE_ACCOUNT_KEY, "") or "").strip()
        if saved in accounts:
            return saved
        if "Josh" in accounts:
            return "Josh"
        return accounts[0]

    def _migration_account(self) -> str:
        accounts = self._account_names()
        active = self._active_account()
        if active in accounts:
            return active
        if "Josh" in accounts:
            return "Josh"
        return accounts[0]

    def _visible_trades(self) -> List[Trade]:
        active = self._active_account()
        return [t for t in self._trades if (t.account or "").strip() == active]

    def _goal_dashboard_accounts(self) -> List[str]:
        accounts = self._account_names()
        raw = self._settings.value(self.GOAL_DASHBOARD_ACCOUNTS_KEY, [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [x.strip() for x in raw.split(",") if x.strip()]
        if not isinstance(raw, list):
            raw = []
        selected = [name for name in raw if name in accounts]
        if not selected:
            selected = list(accounts)
        if set(selected) != set(accounts) or len(selected) != len(raw):
            self._settings.setValue(self.GOAL_DASHBOARD_ACCOUNTS_KEY, json.dumps(selected))
            self._settings.sync()
        return selected

    def sync_goal_dashboard_accounts(self):
        accounts = self._account_names()
        existing = self._goal_dashboard_accounts()
        selected = [name for name in accounts if name in existing]
        if not selected:
            selected = list(accounts)
        if set(selected) != set(existing) or len(selected) != len(existing):
            self._settings.setValue(self.GOAL_DASHBOARD_ACCOUNTS_KEY, json.dumps(selected))
            self._settings.sync()

    def refresh_for_active_account_change(self):
        self.sync_goal_dashboard_accounts()
        self.refresh_view()

    def open_goal_dashboard_accounts_dialog(self):
        accounts = self._account_names()
        selected = self._goal_dashboard_accounts()
        dlg = GoalDashboardAccountsDialog(accounts, selected, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        chosen = dlg.selected_accounts()
        if not chosen:
            chosen = list(accounts)
        self._settings.setValue(self.GOAL_DASHBOARD_ACCOUNTS_KEY, json.dumps(chosen))
        self._settings.sync()
        self.refresh_view()


    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top_row = QHBoxLayout()

        self.goal_group = QGroupBox("Goal Dashboard")
        self.goal_group.setStyleSheet(GROUP_STYLE)
        goal_layout = QVBoxLayout(self.goal_group)
        goal_layout.setContentsMargins(14, 18, 14, 14)
        goal_layout.setSpacing(10)

        goal_controls = QHBoxLayout()
        self.goal_preset = QComboBox()
        goal_controls.addWidget(QLabel("Annual Target Profit"))
        goal_controls.addWidget(self.goal_preset)
        goal_controls.addStretch(1)
        goal_layout.addLayout(goal_controls)

        goal_grid = QGridLayout()
        goal_grid.setHorizontalSpacing(18)
        goal_grid.setVerticalSpacing(8)
        self.goal_labels: Dict[str, QLabel] = {}
        goal_fields = [
            ("realized_profit", "Realized Profit"),
            ("unrealized_profit", "Unrealized Profit"),
            ("remaining_profit", "Profit to Goal"),
            ("monthly_profit_to_goal", "Monthly Profit to Goal"),
            ("weekly_profit_to_goal", "Weekly Profit to Goal"),
            ("daily_profit_to_goal", "Daily Profit to Goal"),
            ("avg_daily_profit", "Avg Daily"),
            ("profit_to_match_daily_avg", "Profit to Match Daily Avg"),
            ("business_days_elapsed", "Business Days Elapsed"),
            ("business_days_remaining", "Business Days Remaining"),
        ]
        for idx, (key, label) in enumerate(goal_fields):
            value = QLabel("—")
            self.goal_labels[key] = value
            row = idx // 2
            col = (idx % 2) * 2
            goal_grid.addWidget(QLabel(label), row, col)
            goal_grid.addWidget(value, row, col + 1)
        goal_layout.addLayout(goal_grid)
        top_row.addWidget(self.goal_group, 1)

        self.analytics_group = QGroupBox("Performance Analytics")
        self.analytics_group.setStyleSheet(GROUP_STYLE)
        analytics_grid = QGridLayout(self.analytics_group)
        analytics_grid.setContentsMargins(14, 18, 14, 14)
        analytics_grid.setHorizontalSpacing(18)
        analytics_grid.setVerticalSpacing(8)
        self.analytics_labels: Dict[str, QLabel] = {}
        analytics_fields = [
            ("open_trades", "Open Trades"),
            ("closed_trades", "Closed Trades"),
            ("avg_profit_per_trade", "Avg Profit / Trade"),
            ("avg_trade_value", "Avg Trade Value"),
            ("avg_roi_pct", "Avg ROI %"),
            ("total_roi_pct", "Total ROI %"),
            ("avg_daily_closed_profit", "Avg Daily Return"),
        ]
        for idx, (key, label) in enumerate(analytics_fields):
            value = QLabel("—")
            self.analytics_labels[key] = value
            analytics_grid.addWidget(QLabel(label), idx, 0)
            analytics_grid.addWidget(value, idx, 1)
        top_row.addWidget(self.analytics_group, 1)

        root.addLayout(top_row)

        self.holdings_group = QGroupBox("Open Holdings")
        self.holdings_group.setStyleSheet(GROUP_STYLE)
        holdings_layout = QVBoxLayout(self.holdings_group)
        holdings_layout.setContentsMargins(14, 18, 14, 14)
        holdings_layout.setSpacing(10)

        self.holdings_table = QTableWidget(0, 7)
        self.holdings_table.setHorizontalHeaderLabels([
            "Instrument",
            "Qty",
            "Avg Cost",
            "Mark",
            "Unrealized P/L",
            "Market Value",
            "Weight %",
        ])
        self.holdings_table.verticalHeader().setVisible(False)
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.holdings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.holdings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.holdings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.holdings_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.holdings_table.customContextMenuRequested.connect(self._open_holdings_context_menu)
        holdings_layout.addWidget(self.holdings_table)

        self.holdings_summary = QLabel("—")
        holdings_layout.addWidget(self.holdings_summary)
        root.addWidget(self.holdings_group)

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

        trade_btns = QHBoxLayout()
        self.btn_add_trade = QPushButton("+ Add Trade")
        self.btn_edit_trade = QPushButton("Edit Selected")
        self.btn_delete_trade = QPushButton("Delete Selected")
        trade_btns.addWidget(self.btn_add_trade)
        trade_btns.addWidget(self.btn_edit_trade)
        trade_btns.addWidget(self.btn_delete_trade)
        trade_btns.addStretch(1)
        trade_layout.addLayout(trade_btns)
        root.addWidget(self.trade_group, 1)

        self.btn_add_trade.clicked.connect(self._add_trade)
        self.btn_edit_trade.clicked.connect(self._edit_trade)
        self.btn_delete_trade.clicked.connect(self._delete_trade)
        self.goal_preset.currentTextChanged.connect(self._on_goal_preset_changed)

    def _load_state(self):
        self._trades = trades_from_json(self._settings.value(self.SETTINGS_KEY, []))

        migrated = False
        default_account = self._migration_account()
        for trade in self._trades:
            if not (trade.account or "").strip():
                trade.account = default_account
                migrated = True

        if migrated:
            self._save_trades()

        if not self._trades:
            legacy = self._settings.value(self.LEGACY_HOLDINGS_KEY, [])
            legacy_rows = []
            if isinstance(legacy, str):
                try:
                    import json
                    legacy_rows = json.loads(legacy)
                except Exception:
                    legacy_rows = []
            elif isinstance(legacy, list):
                legacy_rows = legacy
            for row in legacy_rows:
                if not isinstance(row, dict):
                    continue
                instrument = str(row.get("instrument", "")).strip().upper()
                qty = int(row.get("qty", 0) or 0)
                avg_cost = float(row.get("avg_cost", 0.0) or 0.0)
                notes = str(row.get("notes", "") or "")
                if instrument and qty > 0:
                    self._trades.append(
                        Trade(
                            instrument=instrument,
                            share_count=qty,
                            buy_price=avg_cost,
                            sell_price=None,
                            open_date=date.today(),
                            close_date=None,
                            notes=notes,
                            account=default_account,
                        )
                    )
            if self._trades:
                self._save_trades()

        saved_goal = float(self._settings.value(self.GOAL_KEY, 500000.0) or 500000.0)
        self.sync_goal_dashboard_accounts()
        self.reload_goal_presets(saved_goal)

    def _save_trades(self):
        self._settings.setValue(self.SETTINGS_KEY, trades_to_json(self._trades))
        self._settings.sync()

    def _watchlist_symbols(self) -> List[str]:
        parent = self.window()
        watch = getattr(parent, "watch", None)
        out: List[str] = []
        if watch is None:
            return out
        seen = set()
        for r in range(watch.rowCount()):
            item = watch.item(r, 0)
            if item is None:
                continue
            symbol = item.text().strip().upper()
            if symbol and symbol not in seen:
                seen.add(symbol)
                out.append(symbol)
        return out

    def _selected_trade_source_index(self) -> Optional[int]:
        view_row = self.trade_table.currentRow()
        if view_row < 0 or view_row >= len(self._trade_row_indices):
            return None
        source_index = self._trade_row_indices[view_row]
        if source_index < 0 or source_index >= len(self._trades):
            return None
        return source_index

    def _selected_holding_instrument(self) -> Optional[str]:
        view_row = self.holdings_table.currentRow()
        if view_row < 0 or view_row >= len(self._holding_row_instruments):
            return None
        return self._holding_row_instruments[view_row]

    def _open_trades_for_instrument(self, instrument: str) -> List[tuple[int, Trade]]:
        symbol = (instrument or "").strip().upper()
        out: List[tuple[int, Trade]] = []
        active = self._active_account()
        for idx, trade in enumerate(self._trades):
            if (trade.account or "").strip() != active:
                continue
            if not trade.is_closed and trade.normalized_instrument() == symbol:
                out.append((idx, trade))
        return out

    def _combined_open_trade(self, instrument: str) -> Optional[Trade]:
        matching = self._open_trades_for_instrument(instrument)
        if not matching:
            return None
        trades = [trade for _, trade in matching]
        total_qty = sum(int(t.share_count) for t in trades)
        total_cost = sum(float(t.buy_price) * int(t.share_count) for t in trades)
        oldest_open_date = min((t.open_date for t in trades if t.open_date is not None), default=date.today())
        combined_notes = " | ".join([t.notes for t in trades if t.notes])
        avg_cost = (total_cost / total_qty) if total_qty > 0 else 0.0
        return Trade(
            instrument=instrument,
            share_count=total_qty,
            buy_price=avg_cost,
            sell_price=None,
            open_date=oldest_open_date,
            close_date=None,
            notes=combined_notes,
        )

    def _add_trade(self):
        dlg = TradeEditDialog(
            watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        trade = dlg.to_trade()
        trade.account = self._active_account()
        self._trades.append(trade)
        new_index = len(self._trades) - 1
        self._save_trades()
        self.refresh_view(selected_trade_source_index=new_index)

    def _edit_trade(self):
        source_index = self._selected_trade_source_index()
        if source_index is None:
            QMessageBox.information(self, "Select trade", "Choose a trade row to edit.")
            return
        dlg = TradeEditDialog(
            self._trades[source_index],
            watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated_trade = dlg.to_trade()
        updated_trade.account = (self._trades[source_index].account or self._active_account()).strip() or self._active_account()
        self._trades[source_index] = updated_trade
        self._save_trades()
        self.refresh_view(selected_trade_source_index=source_index)

    def _delete_trade(self):
        source_index = self._selected_trade_source_index()
        if source_index is None:
            QMessageBox.information(self, "Select trade", "Choose a trade row to delete.")
            return
        trade = self._trades[source_index]
        if QMessageBox.question(
            self,
            "Delete trade",
            f"Delete {trade.normalized_instrument()} trade for {trade.share_count:,d} shares?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._trades.pop(source_index)
        self._save_trades()
        self.refresh_view()

    def _open_trade_history_columns_dialog(self):
        dlg = TradeHistoryColumnsDialog(
            self.TRADE_HISTORY_COLUMNS,
            self._trade_history_visible_keys(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._save_trade_history_visible_keys(dlg.selected_keys())
        self.refresh_view(selected_trade_source_index=self._selected_trade_source_index())



    def open_trade_history_view_settings(self):
        self._open_trade_history_columns_dialog()

    def _open_holdings_context_menu(self, pos: QPoint):
        row = self.holdings_table.rowAt(pos.y())
        if row < 0:
            return
        self.holdings_table.selectRow(row)
        instrument = self._selected_holding_instrument()
        if not instrument:
            return

        menu = QMenu(self)
        act_close = menu.addAction("Close Holdings")
        act_mark_down = menu.addAction("Mark Down")
        act_double_down = menu.addAction("Double Down")
        chosen = menu.exec(self.holdings_table.viewport().mapToGlobal(pos))
        if chosen == act_close:
            self._close_selected_holding()
        elif chosen == act_mark_down:
            self._mark_down_selected_holding()
        elif chosen == act_double_down:
            self._double_down_selected_holding()

    def _close_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument:
            QMessageBox.information(self, "Select holding", "Choose an open holding first.")
            return
        combined_trade = self._combined_open_trade(instrument)
        matching = self._open_trades_for_instrument(instrument)
        if combined_trade is None or not matching:
            QMessageBox.information(self, "No open trades", "There are no open trades for that holding.")
            return

        dlg = TradeEditDialog(
            trade=combined_trade,
            watchlist_symbols=self._watchlist_symbols(),
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            close_holdings_mode=True,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        closing_trade = dlg.to_trade()
        if closing_trade.sell_price is None or closing_trade.close_date is None:
            QMessageBox.warning(self, "Missing close info", "Enter a sell price and close date.")
            return

        updated_indices: List[int] = []
        for idx, trade in matching:
            trade.sell_price = float(closing_trade.sell_price)
            trade.close_date = closing_trade.close_date
            updated_indices.append(idx)

        self._save_trades()
        selection_index = updated_indices[-1] if updated_indices else None
        self.refresh_view(selected_trade_source_index=selection_index)


    def _mark_down_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument:
            QMessageBox.information(self, "Select holding", "Choose an open holding first.")
            return
        combined_trade = self._combined_open_trade(instrument)
        if combined_trade is None or combined_trade.share_count <= 0:
            QMessageBox.information(self, "No open trades", "There are no open trades for that holding.")
            return

        holding = Holding(
            instrument=combined_trade.normalized_instrument(),
            qty=int(combined_trade.share_count),
            avg_cost=float(combined_trade.buy_price),
            notes=combined_trade.notes or "",
        )

        dlg = MarkDownDialog(
            holding=holding,
            default_quantity=self._trade_default_quantity(),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        trade = dlg.to_trade()
        trade.account = self._active_account()
        self._trades.append(trade)
        new_index = len(self._trades) - 1
        self._save_trades()
        self.refresh_view(selected_trade_source_index=new_index)

    def _double_down_selected_holding(self):
        instrument = self._selected_holding_instrument()
        if not instrument:
            QMessageBox.information(self, "Select holding", "Choose an open holding first.")
            return
        combined_trade = self._combined_open_trade(instrument)
        if combined_trade is None or combined_trade.share_count <= 0:
            QMessageBox.information(self, "No open trades", "There are no open trades for that holding.")
            return

        holding = Holding(
            instrument=combined_trade.normalized_instrument(),
            qty=int(combined_trade.share_count),
            avg_cost=float(combined_trade.buy_price),
            notes=combined_trade.notes or "",
        )

        dlg = DoubleDownDialog(
            holding=holding,
            current_mark=self._marks.get(holding.normalized_instrument()),
            quantity_increment=self._trade_quantity_increment(),
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        trade = dlg.to_trade()
        trade.account = self._active_account()
        self._trades.append(trade)
        new_index = len(self._trades) - 1
        self._save_trades()
        self.refresh_view(selected_trade_source_index=new_index)

    def _goal_preset_values(self) -> List[float]:
        return [
            float(self._settings.value("goals/preset_1", 250000.0) or 250000.0),
            float(self._settings.value("goals/preset_2", 500000.0) or 500000.0),
            float(self._settings.value("goals/preset_3", 1000000.0) or 1000000.0),
        ]

    @staticmethod
    def _format_goal_preset(value: float) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M USD"
        if value >= 1_000:
            return f"{value / 1_000:.0f}K USD"
        return f"$ {value:,.2f}"

    def _current_goal_target(self) -> float:
        values = self._goal_preset_values()
        idx = max(0, min(self.goal_preset.currentIndex(), len(values) - 1))
        return values[idx]

    def reload_goal_presets(self, selected_value: Optional[float] = None):
        values = self._goal_preset_values()
        labels = [self._format_goal_preset(v) for v in values]
        if selected_value is None:
            try:
                selected_value = float(self._settings.value(self.GOAL_KEY, values[0]) or values[0])
            except Exception:
                selected_value = values[0]

        selected_index = 0
        for idx, value in enumerate(values):
            if abs(float(value) - float(selected_value)) < 0.01:
                selected_index = idx
                break

        self.goal_preset.blockSignals(True)
        self.goal_preset.clear()
        self.goal_preset.addItems(labels)
        self.goal_preset.setCurrentIndex(selected_index)
        self.goal_preset.blockSignals(False)

        self._settings.setValue(self.GOAL_KEY, float(values[selected_index]))
        self._settings.sync()
        self.refresh_view()

    def _on_goal_preset_changed(self, text: str):
        self._on_goal_target_changed(self._current_goal_target())

    def _on_goal_target_changed(self, value: float):
        self._settings.setValue(self.GOAL_KEY, float(value))
        self._settings.sync()
        self.refresh_view()

    def refresh_view(self, selected_trade_source_index: Optional[int] = None):
        visible_trades = self._visible_trades()
        self._holdings = compute_holdings_from_trades(visible_trades)
        realized_by_symbol = compute_realized_pl_by_symbol(visible_trades)
        holding_rows, summary = compute_portfolio(self._holdings, self._marks, realized_by_symbol)
        analytics = compute_trade_analytics(visible_trades)
        goal = compute_goal_progress(visible_trades, self._current_goal_target(), unrealized_profit=summary.unrealized_pl)
        visible_source_indices = [idx for idx, trade in enumerate(self._trades) if (trade.account or "").strip() == self._active_account()]
        trade_rows = compute_trade_rows(visible_trades)

        self._render_goal(goal)
        self._render_analytics(analytics)
        self._render_trade_table(trade_rows, visible_source_indices, selected_trade_source_index)
        self._render_holdings_table(holding_rows)
        self.holdings_summary.setText(
            f"Market Value: {self._money(summary.market_value)}    "
            f"Cost Basis: {self._money(summary.cost_basis)}    "
            f"Unrealized P/L: {self._money(summary.unrealized_pl)}    "
            f"Total P/L: {self._money(summary.total_pl)}"
        )

    def _render_goal(self, goal: GoalProgress):
        self.goal_labels["realized_profit"].setText(self._money(goal.realized_profit))
        self.goal_labels["unrealized_profit"].setText(self._money(goal.unrealized_profit))
        self.goal_labels["remaining_profit"].setText(self._money(goal.remaining_profit))
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
        self.analytics_labels["total_roi_pct"].setText(self._pct(analytics.total_roi_pct))
        self.analytics_labels["avg_daily_closed_profit"].setText(self._money_or_dash(analytics.avg_daily_closed_profit))

    def _render_trade_table(self, rows, visible_source_indices: List[int], selected_trade_source_index: Optional[int]):
        self.trade_table.setColumnCount(len(self.TRADE_HISTORY_COLUMNS))
        self.trade_table.setHorizontalHeaderLabels([label for _, label in self.TRADE_HISTORY_COLUMNS])
        self.trade_table.setRowCount(len(rows))
        self._trade_row_indices = [visible_source_indices[row.index] for row in rows if 0 <= row.index < len(visible_source_indices)]

        visible_keys = set(self._trade_history_visible_keys())
        for col, (key, _) in enumerate(self.TRADE_HISTORY_COLUMNS):
            self.trade_table.setColumnHidden(col, key not in visible_keys)

        for r, row in enumerate(rows):
            value_map = {
                "instrument": row.instrument,
                "share_count": self._qty(row.share_count),
                "status": row.status,
                "buy_price": self._money(row.buy_price),
                "sell_price": self._money_or_dash(row.sell_price),
                "trade_profit": self._money_or_dash(row.trade_profit),
                "open_date": self._date_or_dash(row.open_date),
                "close_date": self._date_or_dash(row.close_date),
                "days_to_close": self._int_or_dash(row.days_to_close),
                "avg_daily_return": self._money_or_dash(row.avg_daily_return),
            }
            for c, (key, _) in enumerate(self.TRADE_HISTORY_COLUMNS):
                value = value_map[key]
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if key == "instrument":
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if key == "trade_profit" and row.trade_profit is not None:
                    if row.trade_profit > 0:
                        item.setForeground(Qt.GlobalColor.darkGreen)
                    elif row.trade_profit < 0:
                        item.setForeground(Qt.GlobalColor.red)
                self.trade_table.setItem(r, c, item)

        if rows:
            row_to_select = 0
            if selected_trade_source_index is not None:
                try:
                    row_to_select = self._trade_row_indices.index(selected_trade_source_index)
                except ValueError:
                    row_to_select = 0
            self.trade_table.selectRow(row_to_select)

    def _render_holdings_table(self, rows):
        self.holdings_table.setRowCount(len(rows))
        self._holding_row_instruments = [row.instrument for row in rows]
        for r, row in enumerate(rows):
            values = [
                row.instrument,
                self._qty(row.qty),
                self._money(row.avg_cost),
                self._money_or_dash(row.mark),
                self._money(row.unrealized_pl),
                self._money(row.market_value),
                self._pct(row.weight_pct),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.holdings_table.setItem(r, c, item)

    @staticmethod
    def _money(value: float) -> str:
        return f"$ {float(value):,.2f}"

    @staticmethod
    def _money_or_dash(value: Optional[float]) -> str:
        return "—" if value is None else f"$ {float(value):,.2f}"

    @staticmethod
    def _qty(value: int) -> str:
        return f"{int(value):,d}"

    @staticmethod
    def _pct(value: Optional[float]) -> str:
        return "—" if value is None else f"{float(value):,.2f}%"

    @staticmethod
    def _date_or_dash(value: Optional[date]) -> str:
        return "—" if value is None else value.isoformat()

    @staticmethod
    def _int_or_dash(value: Optional[int]) -> str:
        return "—" if value is None else f"{int(value):,d}"
