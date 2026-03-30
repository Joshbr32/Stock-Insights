from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    trades_from_json,
    trades_to_json,
)

GROUP_STYLE = (
    "QGroupBox { margin-top: 8px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }"
)


class TradeEditDialog(QDialog):
    """Trade entry dialog matching the uploaded Excel tracker structure."""

    def __init__(self, trade: Optional[Trade] = None, watchlist_symbols: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Trade")
        self.resize(440, 360)
        self._editing = trade
        self._watchlist_symbols = [str(s).strip().upper() for s in (watchlist_symbols or []) if str(s).strip()]

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
        self.btn_save = QPushButton("Save")
        buttons.addButton(self.btn_save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.reject)
        self.btn_save.clicked.connect(self._accept_if_valid)
        root.addWidget(buttons)

        self.status_combo.currentTextChanged.connect(self._sync_status)
        self.share_count_spin.valueChanged.connect(self._update_preview)
        self.buy_price_spin.valueChanged.connect(self._update_preview)
        self.sell_price_spin.valueChanged.connect(self._update_preview)

        self._apply_trade(trade)
        self._sync_status(self.status_combo.currentText())
        self._update_preview()

    def _apply_trade(self, trade: Optional[Trade]):
        today = date.today()
        self.instrument_edit.setCurrentText(trade.normalized_instrument() if trade else "")
        self.share_count_spin.setValue(max(1, int(trade.share_count) if trade else 1))
        self.buy_price_spin.setValue(float(trade.buy_price) if trade else self.buy_price_spin.minimum())
        self.sell_price_spin.setValue(float(trade.sell_price) if trade and trade.sell_price is not None else self.sell_price_spin.minimum())
        self.status_combo.setCurrentText(trade.status if trade else "OPEN")

        open_date = trade.open_date if trade and trade.open_date else today
        close_date = trade.close_date if trade and trade.close_date else today
        self.open_date_edit.setDate(QDate(open_date.year, open_date.month, open_date.day))
        self.close_date_edit.setDate(QDate(close_date.year, close_date.month, close_date.day))
        self.notes_edit.setText(trade.notes if trade else "")

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


class PortfolioTab(QWidget):
    SETTINGS_KEY = "portfolio/trades"
    LEGACY_HOLDINGS_KEY = "portfolio/holdings"
    GOAL_KEY = "portfolio/goal_target"

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._marks: Dict[str, Optional[float]] = {}
        self._trades: List[Trade] = []
        self._holdings: List[Holding] = []
        self._trade_row_indices: List[int] = []
        self._build_ui()
        self._load_state()
        self.refresh_view()

    # ---------- Public interface used by main window ----------

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

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        # Goal dashboard + analytics
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
            ("total_profit", "Total Profit"),
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
            ("best_trade", "Best Trade"),
            ("avg_daily_closed_profit", "Avg Daily Return"),
        ]
        for idx, (key, label) in enumerate(analytics_fields):
            value = QLabel("—")
            self.analytics_labels[key] = value
            analytics_grid.addWidget(QLabel(label), idx, 0)
            analytics_grid.addWidget(value, idx, 1)
        top_row.addWidget(self.analytics_group, 1)

        root.addLayout(top_row)

        # Holdings
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
            "Market Value",
            "Weight %",
            "Unrealized P/L",
        ])
        self.holdings_table.verticalHeader().setVisible(False)
        self.holdings_table.setAlternatingRowColors(True)
        self.holdings_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.holdings_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.holdings_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.holdings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        holdings_layout.addWidget(self.holdings_table)

        self.holdings_summary = QLabel("—")
        holdings_layout.addWidget(self.holdings_summary)
        root.addWidget(self.holdings_group)

        # Trade history
        self.trade_group = QGroupBox("Trade History")
        self.trade_group.setStyleSheet(GROUP_STYLE)
        trade_layout = QVBoxLayout(self.trade_group)
        trade_layout.setContentsMargins(14, 18, 14, 14)
        trade_layout.setSpacing(10)

        self.trade_table = QTableWidget(0, 10)
        self.trade_table.setHorizontalHeaderLabels([
            "Instrument",
            "Share count",
            "Status",
            "Buy Price",
            "Sell Price",
            "Trade Profit",
            "Open Date",
            "Close Date",
            "Days to Close",
            "Avg Daily Return",
        ])
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

    # ---------- Persistence ----------

    def _load_state(self):
        self._trades = trades_from_json(self._settings.value(self.SETTINGS_KEY, []))

        # Optional one-time migration from the older holdings-only model.
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
                        )
                    )
            if self._trades:
                self._save_trades()

        saved_goal = float(self._settings.value(self.GOAL_KEY, 500000.0) or 500000.0)
        self.reload_goal_presets(saved_goal)

    def _save_trades(self):
        self._settings.setValue(self.SETTINGS_KEY, trades_to_json(self._trades))
        self._settings.sync()

    # ---------- Actions ----------

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

    def _add_trade(self):
        dlg = TradeEditDialog(watchlist_symbols=self._watchlist_symbols(), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._trades.append(dlg.to_trade())
        new_index = len(self._trades) - 1
        self._save_trades()
        self.refresh_view(selected_trade_source_index=new_index)

    def _edit_trade(self):
        source_index = self._selected_trade_source_index()
        if source_index is None:
            QMessageBox.information(self, "Select trade", "Choose a trade row to edit.")
            return
        dlg = TradeEditDialog(self._trades[source_index], watchlist_symbols=self._watchlist_symbols(), parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._trades[source_index] = dlg.to_trade()
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

    # ---------- Rendering ----------

    def refresh_view(self, selected_trade_source_index: Optional[int] = None):
        self._holdings = compute_holdings_from_trades(self._trades)
        realized_by_symbol = compute_realized_pl_by_symbol(self._trades)
        holding_rows, summary = compute_portfolio(self._holdings, self._marks, realized_by_symbol)
        analytics = compute_trade_analytics(self._trades)
        goal = compute_goal_progress(self._trades, self._current_goal_target(), unrealized_profit=summary.unrealized_pl)
        trade_rows = compute_trade_rows(self._trades)

        self._render_goal(goal)
        self._render_analytics(analytics)
        self._render_trade_table(trade_rows, selected_trade_source_index)
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
        self.goal_labels["total_profit"].setText(self._money(goal.total_profit))
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
        self.analytics_labels["avg_profit_per_trade"].setText(
            self._money_or_dash(analytics.avg_profit_per_trade)
        )
        self.analytics_labels["best_trade"].setText(
            self._money_or_dash(analytics.best_trade)
        )
        self.analytics_labels["avg_daily_closed_profit"].setText(
            self._money_or_dash(analytics.avg_daily_closed_profit)
        )

    def _render_trade_table(self, rows, selected_trade_source_index: Optional[int]):
        self.trade_table.setRowCount(len(rows))
        self._trade_row_indices = [row.index for row in rows]

        for r, row in enumerate(rows):
            values = [
                row.instrument,
                self._qty(row.share_count),
                row.status,
                self._money(row.buy_price),
                self._money_or_dash(row.sell_price),
                self._money_or_dash(row.trade_profit),
                self._date_or_dash(row.open_date),
                self._date_or_dash(row.close_date),
                self._int_or_dash(row.days_to_close),
                self._money_or_dash(row.avg_daily_return),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                if c == 5 and row.trade_profit is not None:
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
        for r, row in enumerate(rows):
            values = [
                row.instrument,
                self._qty(row.qty),
                self._money(row.avg_cost),
                self._money_or_dash(row.mark),
                self._money(row.market_value),
                self._pct(row.weight_pct),
                self._money(row.unrealized_pl),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c == 0:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.holdings_table.setItem(r, c, item)

    # ---------- Formatting ----------

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
